"""The rendered-text fingerprint: a hash of what the agent sends a model (decision 0143).

Decision 0133 hashed the source of ten files, so a comment moved the label. This module hashes
the requests instead. It drives the agent's two state machines, the case loop and arm B's tool
post-pass, over invented inputs with scripted replies, and keeps exactly the keys the provider
reads from each request body (:data:`MODEL_FACING_KEYS`): the messages, the tool definitions, the
tool choice, the parallel-calls flag and the response format. A change to any text the model
receives changes the hash; a comment, a docstring or a rename does not.

Invented, never a real case (decision 0143): :data:`_RAW` and :data:`_DOCKET` hold made-up values.
The scenarios walk every branch that writes text for the model; ``tests/test_agent_rendered.py``
parses the covered modules and fails when a text literal in them is sent by none of them.

This module imports only what already existed at commit ``fd6053f``, with the same signatures:
version 1's fingerprint is proved by running this file, unchanged, in a checkout of that commit.
It imports nothing that is new in S3.3, and not ``agent.run``, whose guidance it copies as
:data:`RENDER_GUIDANCE` (a test holds the two equal). It reads the data files the package ships
(code tables, statistics, guidance), which are part of what the agent sends.
"""

import functools
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final, Literal, Protocol

from ntsb_probable_cause.agent.documents import DocketView, docket_view
from ntsb_probable_cause.agent.loop import CaseLoop, LoopConfig, PendingCall
from ntsb_probable_cause.agent.schemas import DocumentDecision
from ntsb_probable_cause.agent.trail import LoopOutcome, Prior, ReadRecord
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.model.client import ModelReply, ToolCall, Usage
from ntsb_probable_cause.model.openrouter import request_body
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, parse_hypothesis
from ntsb_probable_cause.scoring.runner import RunSpec, prepare_case

# The keys of a request body the model reads. The rest (the model id, the temperature, the token
# budget, the reasoning level, the provider routing) is how the call is made, not what it says.
MODEL_FACING_KEYS: Final = (
    "messages",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "response_format",
)

# The guidance the live agent reads (``agent.run.GUIDANCE``), copied so that this module needs no
# module that is new since ``fd6053f``. ``tests/test_agent_rendered.py`` holds the two equal.
RENDER_GUIDANCE: Final[tuple[str, ...]] = ("r3-loc-stall", "r6-aircraft-control")

_SENT_AT: Final = datetime(2026, 10, 7, 12, tzinfo=UTC)
_NO_USAGE: Final = Usage(prompt_tokens=0, completion_tokens=0)
_CAP_USD: Final = 0.30

# --- the invented case ---

_RAW: Final[dict[str, object]] = {
    "ntsbNumber": "XXX00XX000",
    "mKey": 1,
    "eventDate": "2026-01-15T14:30:00Z",
    "highestInjuryLevel": "Minor",
    "narratives": [
        {
            "prelimNarrative": (
                "The airplane veered left during the landing roll on runway 21 and the left "
                "wing struck the ground. The pilot reported a gusting crosswind."
            )
        }
    ],
    "aircrafts": [
        {
            "aircraftMake": "Examplecraft",
            "aircraftModel": "EX-100",
            "aircraftAmateurBuilt": False,
            "aircraftRegistrationNumber": "N100XX",
            "engines": [{"engineType": "Reciprocating"}],
            "crewAndOccupants": [
                {
                    "pilotCertificates": ["Private"],
                    "pilotsFlightTimeMatrix": [
                        {
                            "flightHours": 310,
                            "flightTimeCraft": "All AC",
                            "flightTimeType": "Total",
                        },
                        {
                            "flightHours": 42,
                            "flightTimeCraft": "Make and Model",
                            "flightTimeType": "Total",
                        },
                    ],
                }
            ],
            "events": [
                {"isDefiningEvent": True, "sequenceNumber": 1, "cicttPhaseSOEGroup": "Landing"}
            ],
        }
    ],
    "weatherConditions": [
        {
            "accidentSiteCondition": "Visual (VMC)",
            "metar": "KXXX 151430Z 21018G27KT 10SM FEW040 08/M02 A2992",
        }
    ],
}


def _entry(index: int, title: str, pages: int, photos: int = 0) -> ListingEntry:
    return ListingEntry(
        index=index,
        title=title,
        pages=pages,
        photos=photos,
        doc_type="Report",
        extension="pdf",
        href=f"/invented/{index}",
    )


def _record(
    entry: ListingEntry, category: str, status: str, kind: str | None, readable: int
) -> DocumentRecord:
    return DocumentRecord.model_validate(
        {
            "entry": entry,
            "category": category,
            "status": status,
            "pages": entry.pages,
            "readable_pages": readable,
            "estimated_tokens": 40 * readable,
            "kind": kind,
        }
    )


def _docket(records: Sequence[DocumentRecord], texts: dict[int, str]) -> Docket:
    listing = Listing(mkey=1, declared_items=len(records), entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=tuple(records), texts=texts)


_TEXT_1: Final = (
    "[page 1 of 2]\nThe examination found the left main gear leg bent aft. The tire showed a "
    "flat spot on the inboard side. The brake lines were intact and the fluid was full.\n"
    "[page 2 of 2]\nThe tailwheel steering arm moved freely through its range of travel.\n"
)
_TEXT_2: Final = (
    "[page 1 of 3]\nThe operator states that the airplane was last flown two days before the "
    "event and that no discrepancy was written up.\n"
)

_READ_1: Final = _record(
    _entry(1, "Airframe Examination Report", 2), "exam_site", "read", "born-digital", 2
)
_READ_2: Final = _record(
    _entry(2, "Operator Statement", 3), "party_submission", "read", "born-digital", 3
)
_SCAN: Final = _record(
    _entry(3, "Pilot Form 6120", 4), "pilot_form_6120", "unreadable: scan", "scan", 0
)
_PHOTO: Final = _record(
    _entry(4, "Wreckage Photographs", 6, photos=6), "photos", "skipped: photo-only", None, 0
)

# Invented, never a real case (decision 0143): two readable documents, one scan, one photo sheet.
_DOCKET: Final = _docket((_READ_1, _READ_2, _SCAN, _PHOTO), {1: _TEXT_1, 2: _TEXT_2})
# A docket whose listed documents none can be read.
_DOCKET_UNREADABLE: Final = _docket((_SCAN, _PHOTO), {})

# --- the scripted replies ---

_HYPOTHESIS: Final[dict[str, object]] = {
    "evidence_narrative": "The airplane left the runway during the landing roll in a crosswind.",
    "occurrence": [
        {"phase": "552", "event": "230", "probability": 0.6},
        {"phase": "551", "event": "230", "probability": 0.2},
    ],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.7}],
    "probable_cause": "The pilot's loss of directional control during the landing roll.",
    "lay_explanation": "The plane swerved off the runway after touching down.",
    "confidence": 0.6,
    "abstain": False,
    "evidence_used": ["phase_of_flight", "weather_condition"],
}
_REFINEMENT: Final = json.dumps({"items": [{"index": 0, "item8": "02063015"}]})
_WHY: Final = {"reason": "check the defining event", "expected_effect": "confirm the first code"}


def _hypothesis(**changes: object) -> str:
    return json.dumps({**_HYPOTHESIS, **changes})


def _decisions(pairs: Sequence[tuple[int, bool]]) -> str:
    return json.dumps(
        {
            "decisions": [
                {"document": n, "read": read, "expected_effect": "the gear leg's condition"}
                for n, read in pairs
            ],
            "reason": "the examination decides between the two",
        }
    )


def _calling(*calls: tuple[str, str]) -> ModelReply:
    """A reply that calls tools, the first being the one the loop acts on."""
    return ModelReply(
        content=None,
        tool_calls=tuple(
            ToolCall(call_id=f"call-{n}", name=name, arguments=arguments)
            for n, (name, arguments) in enumerate(calls, start=1)
        ),
        finish_reason="tool_calls",
        usage=_NO_USAGE,
        model="rendered",
        response_id="rendered",
    )


def _saying(content: str) -> ModelReply:
    """A reply of text only: a refinement, or a reply that called no tool."""
    return ModelReply(content=content, usage=_NO_USAGE, model="rendered", response_id="rendered")


def _describe(*codes: str) -> tuple[str, str]:
    return "describe_codes", json.dumps({**_WHY, "kind": "occurrence", "codes": list(codes)})


def _usage(*codes: str) -> tuple[str, str]:
    return "occurrence_usage", json.dumps({**_WHY, "codes": list(codes)})


_PAST: Final = ("past_findings", json.dumps({**_WHY, "occurrence": "552230"}))
_SUGGEST: Final = ("suggest_codes", json.dumps({**_WHY, "phase_group": "Landing"}))
_RECORD: Final = ("record_hypothesis", _hypothesis())
_ANSWER: Final = ("submit_answer", _hypothesis())


# --- the machines ---


class _Machine(Protocol):
    """What the scenarios need of a case loop and of arm B's post-pass loop."""

    def next_call(self) -> PendingCall | None:
        """The next call, or None once the case has stopped."""
        ...

    def accept(self, reply: ModelReply | None, *, sent_at: datetime, returned_at: datetime) -> None:
        """Take the reply to the pending call."""
        ...

    @property
    def outcome(self) -> LoopOutcome:
        """How the case ended."""
        ...


@dataclass(frozen=True)
class _Scenario:
    """One invented case walked to its end: the machine to build and the replies it is given."""

    name: str
    build: Callable[[], _Machine]
    replies: tuple[ModelReply, ...]
    stops: str = "done"


@dataclass(frozen=True)
class ScenarioRun:
    """A scenario after it ran.

    Attributes:
        name: the scenario's name.
        requests: every request it sent, each cut to :data:`MODEL_FACING_KEYS`.
        stop_reason: how the case ended.
        expected_stop: how the scenario means it to end.
        unused_replies: scripted replies the machine never asked for.
    """

    name: str
    requests: tuple[dict[str, object], ...]
    stop_reason: str
    expected_stop: str
    unused_replies: int


def _config(**changes: object) -> LoopConfig:
    base = LoopConfig(
        tables=load_tables(),
        stats=load_stats("s3"),
        guidance=RENDER_GUIDANCE,
        exclusions=frozenset(),
        cap_usd=_CAP_USD,
        price_variant="batch",
    )
    return replace(base, **changes)  # type: ignore[arg-type]  # keyword names are the caller's


def _view(docket: Docket = _DOCKET) -> DocketView:
    return docket_view(_RAW, docket)


def _case(
    view: DocketView | None, config: LoopConfig | None = None, **later: object
) -> Callable[[], _Machine]:
    return lambda: CaseLoop(_RAW, view, config or _config(), **later)  # type: ignore[arg-type]


def _prior(*, read: Sequence[int], reads: Sequence[ReadRecord]) -> Prior:
    last = parse_hypothesis(_hypothesis(), load_tables())
    return Prior(trigger=1, last_hypothesis=last, reads=tuple(reads), read=tuple(read))


def _earlier_choice(
    *, read: Sequence[int], skip: Sequence[int], step: Literal["choice1", "choice2"] = "choice1"
) -> ReadRecord:
    decisions = [
        DocumentDecision(document=n, read=True, expected_effect="the gear leg's condition")
        for n in read
    ] + [
        DocumentDecision(document=n, read=False, expected_effect="nothing about the cause")
        for n in skip
    ]
    return ReadRecord(
        step=step,
        offered=(*read, *skip),
        decisions=tuple(decisions),
        reason="the examination decides between the two",
    )


def _capped() -> _Machine:
    """A case whose cap fits one call and not two, so the loop forces the answer at once."""
    first = CaseLoop(_RAW, _view(), _config()).next_call()
    if first is None:
        raise RuntimeError("the probe loop sent no call")
    return CaseLoop(_RAW, _view(), _config(cap_usd=first.estimated_usd * 1.6))


def _arm_b() -> _Machine:
    # Imported here: ``agent.armb`` is covered by the fingerprint and, from S3.3, its run labels
    # come from ``agent.version``, which imports this module.
    from ntsb_probable_cause.agent.armb import FixedToolsLoop, phase_group  # noqa: PLC0415

    config = _config()
    spec = RunSpec(sample="invented", arm="B", guidance=RENDER_GUIDANCE, cap_usd=_CAP_USD)
    prepared = prepare_case(_RAW, spec, config.tables, _DOCKET)
    answer: Hypothesis = parse_hypothesis(_hypothesis(), config.tables)
    return FixedToolsLoop(
        _RAW,
        prepared.payload,
        prepared.system,
        answer,
        _hypothesis(),
        phase_group(prepared.evidence.phase_of_flight),
        config,
    )


def _submitting(**changes: object) -> tuple[str, str]:
    return "submit_answer", _hypothesis(**changes)


def _choosing(pairs: Sequence[tuple[int, bool]]) -> tuple[str, str]:
    return "choose_documents", _decisions(pairs)


def _describing(kind: str, *codes: str) -> tuple[str, str]:
    return "describe_codes", json.dumps({**_WHY, "kind": kind, "codes": list(codes)})


def _guess(phase: str, event: str, probability: float) -> dict[str, object]:
    return {"phase": phase, "event": event, "probability": probability}


def _finding(category6: str, modifier: str, **more: object) -> dict[str, object]:
    return {"category6": category6, "modifier": modifier, "probability": 0.5, **more}


def _scenarios() -> list[_Scenario]:
    """Every invented case, in a fixed order."""
    view = _view()
    both = _choosing([(1, True), (2, True)])
    return [
        _Scenario(
            "full path",
            _case(view),
            (
                _calling(_RECORD),
                # Reads one document, skips the other; decides on a number the listing does not
                # hold and on a document that cannot be read.
                _calling(_choosing([(1, True), (2, False), (99, True), (3, True)])),
                _calling(_RECORD),
                # The second look: reads the other, and decides again on one read already.
                _calling(_choosing([(2, True), (1, True)])),
                _calling(_RECORD),
                _calling(_RECORD),  # a tool the coding step does not take
                _calling(_describe("552230", "551230")),
                _calling(_describe("999999")),
                _calling(_usage("552230")),
                _calling(("describe_codes", "{not json")),
                _calling(_PAST, _SUGGEST),  # a second call in one reply
                _calling(("no_such_tool", "{}")),
                _calling(_SUGGEST),
                _calling(_submitting(findings=[{"category6": "999999"}])),
                _calling(_ANSWER),
                _saying(json.dumps({"items": [{"index": 7, "item8": "02063015"}]})),
                _saying(_REFINEMENT),
            ),
        ),
        _Scenario(
            "refused replies and the coding tools' edge cases",
            _case(view, _config(max_coding_calls=20)),
            (
                _calling(("record_hypothesis", "{not json")),
                _calling(_RECORD),
                _calling(_choosing([(1, True), (1, False)])),
                _calling(both),
                _calling(
                    (
                        "record_hypothesis",
                        _hypothesis(
                            occurrence=[_guess("552", "230", 0.7), _guess("551", "230", 0.6)]
                        ),
                    )
                ),
                _calling(_RECORD),
                _calling(_describing("finding_category", "010227")),
                _calling(_submitting(occurrence=[_guess("999", "230", 0.5)])),
                _calling(_usage("552230", "451240", "999999")),
                _calling(
                    _submitting(occurrence=[_guess("552", "230", 0.5), _guess("552", "230", 0.3)])
                ),
                _calling(("past_findings", json.dumps({**_WHY, "occurrence": "552040"}))),
                _calling(_submitting(occurrence=[_guess("552", "999", 0.5)])),
                _calling(_usage("100060")),
                _calling(_submitting(findings=[_finding("999999", "44")])),
                _calling(_describing("finding_category", "999999")),
                _calling(_submitting(findings=[_finding("020630", "04")])),
                _calling(_describing("item", "99999999")),
                _calling(_submitting(findings=[_finding("020630", "44", item8="99999999")])),
                _calling(_describing("item")),
                _calling(_usage()),
                _calling(_ANSWER),
                _saying("not json"),
                _saying(_REFINEMENT),
            ),
        ),
        _Scenario(
            "no docket",
            _case(None),
            (
                _calling(_RECORD),
                _calling(_describe("552230")),
                _calling(_ANSWER),
                _saying(_REFINEMENT),
            ),
        ),
        _Scenario(
            "nothing readable",
            _case(_view(_DOCKET_UNREADABLE)),
            (
                _calling(_RECORD),
                _calling(_usage("552230")),
                _calling(_ANSWER),
                _saying(_REFINEMENT),
            ),
        ),
        _Scenario(
            "later trigger, no new structured evidence",
            _case(
                view,
                trigger=2,
                prior=_prior(read=[1], reads=[_earlier_choice(read=[1], skip=[2])]),
                new_structured=False,
            ),
            (
                _calling(_choosing([(2, True)])),
                _calling(_RECORD),
                _calling(_describe("552230")),
                _calling(_ANSWER),
                _saying(_REFINEMENT),
            ),
        ),
        _Scenario(
            "later trigger, new structured evidence",
            _case(
                view,
                trigger=2,
                prior=_prior(
                    read=[1, 2],
                    reads=[
                        _earlier_choice(read=[1], skip=[2]),
                        _earlier_choice(read=[2], skip=[], step="choice2"),
                    ],
                ),
                new_structured=True,
            ),
            (_calling(_RECORD), _calling(_PAST), _calling(_ANSWER), _saying(_REFINEMENT)),
        ),
        _Scenario(
            "later trigger, nothing read before",
            _case(view, trigger=2, prior=_prior(read=[], reads=[]), new_structured=False),
            (
                _calling(_choosing([(1, False), (2, False)])),
                _calling(_choosing([(1, False), (2, False)])),
                _calling(_PAST),
                _calling(_ANSWER),
                _saying(_REFINEMENT),
            ),
        ),
        _Scenario(
            "later trigger, every document read",
            _case(
                view,
                trigger=2,
                prior=_prior(read=[1, 2], reads=[_earlier_choice(read=[1, 2], skip=[])]),
                new_structured=False,
            ),
            (_calling(_PAST), _calling(_ANSWER), _saying(_REFINEMENT)),
        ),
        _Scenario(
            "coding ablation",
            _case(view, _config(without=frozenset({"coding"}))),
            (
                _calling(_RECORD),
                _calling(both),
                _calling(_RECORD),
                _calling(_ANSWER),
                _saying(_REFINEMENT),
            ),
        ),
        _Scenario(
            "a cap that forces the answer", _capped, (_calling(_ANSWER), _saying(_REFINEMENT))
        ),
        _Scenario(
            "arm B tool post-pass",
            _arm_b,
            (
                _calling(_RECORD),
                _calling(_ANSWER),
                _saying(json.dumps({"items": [{"index": 0, "item8": "99999999"}]})),
                _saying(_REFINEMENT),
            ),
        ),
    ]


def _play(scenario: _Scenario) -> ScenarioRun:
    machine = scenario.build()
    replies = list(scenario.replies)
    requests: list[dict[str, object]] = []
    while (call := machine.next_call()) is not None:
        if not replies:
            raise RuntimeError(f"scenario {scenario.name!r}: the machine asked for more replies")
        body = request_body(call.payload, call.settings, system=call.system, history=call.history)
        requests.append({key: body[key] for key in MODEL_FACING_KEYS if key in body})
        machine.accept(replies.pop(0), sent_at=_SENT_AT, returned_at=_SENT_AT)
    return ScenarioRun(
        name=scenario.name,
        requests=tuple(requests),
        stop_reason=machine.outcome.stop_reason,
        expected_stop=scenario.stops,
        unused_replies=len(replies),
    )


@functools.cache
def scenario_runs() -> tuple[ScenarioRun, ...]:
    """Every scenario run to its end, in a fixed order."""
    return tuple(_play(scenario) for scenario in _scenarios())


def rendered_requests() -> list[dict[str, object]]:
    """Every request the scenarios send, each cut to MODEL_FACING_KEYS, in a fixed order."""
    return [dict(body) for run in scenario_runs() for body in run.requests]


@functools.cache
def rendered_sha256() -> str:
    """SHA-256 (hex) of ``json.dumps(rendered_requests(), sort_keys=True, ensure_ascii=False)``.

    Cached for the process and computed from live module state on the first call: code that
    patches a module global the scenarios use must not make that first call (the test suite
    fills it in a session fixture in ``tests/conftest.py``).
    """
    text = json.dumps(rendered_requests(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
