"""The board/1 export builder, from invented run folders (S4 Task 11; decisions 0173, 0180, 0182).

No development or live data: every record is a redacted development fixture with invented values
planted in it, and every run folder is made here. The never-holds test reads every string and
every key of every exported file.
"""

import copy
import dataclasses
import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from tests.test_live_closure import _run as _run_record
from tests.test_live_later import _closure, _raw_with_codes, _step
from tests.test_live_morning import _call, _result, _scores

from ntsb_probable_cause.docket.manifest import Status
from ntsb_probable_cause.errors import ConfigurationError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.live import board
from ntsb_probable_cause.live.board import (
    _NOT_OFFERED,
    _SCAN_ONLY,
    build_export,
    grade,
    occurrence_marks,
)
from ntsb_probable_cause.live.closure import CASES_FILE
from ntsb_probable_cause.live.export import (
    NOT_CODED_SENTENCES,
    BoardIndex,
    CaseFile,
    NotOfferedReason,
)
from ntsb_probable_cause.live.later import LaterScore
from ntsb_probable_cause.live.names import NAME_MARKER
from ntsb_probable_cause.live.queue import backfill_digest, build_queue
from ntsb_probable_cause.live.records import (
    CLOSURES_FILE,
    INPUTS_FILE,
    Backfill,
    ClosureRecord,
    ClosureRecordV1,
    DocumentLine,
)
from ntsb_probable_cause.live.state import Closed, NightState
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.records import CaseResult, write_jsonl
from ntsb_probable_cause.store import Closure, Store

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
TODAY = NOW.date()
FORBIDDEN = (
    "N123XX",
    "N456YY",
    "Inventedmake",
    "INV-1",
    "Invented Owner",
    "LAY-MARKER",
    "Smithers",
    "DOC-TEXT-MARKER",
    "FP-MARKER",
)
FORBIDDEN_KEY_PARTS = ("registration", "make", "explanation", "fingerprint")
CASE_NUMBER = r"[A-Z]{3}\d{2}[A-Z]{2}\d{3}"

LOC_FLIGHT = "452240"
STALL = "452241"
OTHER = "551092"


def _hypothesis(
    *codes: str,
    abstain: bool = False,
    cause: str = "The pilot lost control.",
    account: str = "The airplane struck the ground.",
    findings: bool = True,
) -> Hypothesis:
    return Hypothesis(
        evidence_narrative=account,
        occurrence=tuple(OccurrenceGuess(phase=c[:3], event=c[3:], probability=0.4) for c in codes),
        findings=(
            (FindingGuess(category6="020630", modifier="11", probability=0.5, item8="02063040"),)
            if findings
            else ()
        ),
        probable_cause=cause,
        lay_explanation="LAY-MARKER",
        confidence=0.6,
        abstain=abstain,
        evidence_used=(),
    )


def _raw(case_id: str, event: date, *, amateur: bool = False) -> dict[str, Any]:
    """A development record with invented identifying values planted, and the NTSB's codes."""
    raw = copy.deepcopy(_raw_with_codes())
    raw["ntsbNumber"] = case_id
    raw["eventDate"] = event.isoformat() + "T12:00:00Z"
    raw["eventStateOrRegion"] = "TX"
    raw["highestInjuryLevel"] = "Fatal"
    aircraft = raw["aircrafts"][0]
    aircraft["aircraftRegistrationNumber"] = "N123XX"
    aircraft["aircraftMake"] = "Inventedmake"
    aircraft["aircraftModel"] = "INV-1"
    aircraft["aircraftAmateurBuilt"] = amateur
    aircraft["aircraftNumberOfEngines"] = 1
    raw["narratives"][0]["probableCause"] = "Invented Owner in N123XX failed to maintain control."
    aircraft["ownerOperators"] = [
        {
            "registeredOwner": "Invented Owner",
            "operatorName": "Invented Owner",
            "flightOperationType": "Personal",
        }
    ]
    return raw


def _two_more_aircraft(raw: dict[str, Any]) -> dict[str, Any]:
    """Item A9: a second aircraft with its own registration, and a third with a short one."""
    raw["aircrafts"] += [
        {"aircraftRegistrationNumber": "N456YY", "ownerOperators": []},
        {"aircraftRegistrationNumber": "N1", "ownerOperators": []},
    ]
    return raw


def _no_codes(raw: dict[str, Any]) -> dict[str, Any]:
    """The record as it stood before the NTSB published its codes."""
    gone = copy.deepcopy(raw)
    for key in ("events", "Findings", "findings", "occurrences"):
        for aircraft in gone["aircrafts"]:
            aircraft.pop(key, None)
    gone.pop("probableCause", None)
    return gone


def _lines() -> tuple[DocumentLine, ...]:
    return (
        DocumentLine(
            position=1, title="Statement of Smithers", status="read", ellery="read", pages=4
        ),
        DocumentLine(position=2, title="Weather data", status="read", ellery="skipped", pages=17),
        DocumentLine(
            position=3, title="Handwritten pilot form", status="unreadable: scan", ellery=None
        ),
    )


def _calls(case_id: str) -> list[Any]:
    choice = {
        "decisions": [
            {"document": 1, "read": True, "expected_effect": "Invented Owner may describe it."},
            {"document": 2, "read": False, "expected_effect": "Not likely to matter."},
        ],
        "reason": "Invented Owner's own statement comes first.",
    }
    lookup = {
        "reason": "Check Invented Owner's stall code.",
        "expected_effect": "Confirms the label for Invented Owner.",
        "kind": "occurrence",
        "codes": [STALL],
    }
    return [
        _call(case_id, "h0", 0, tool="record_hypothesis", cost_usd=0.004),
        _call(
            case_id,
            "choice1",
            1,
            tool="choose_documents",
            arguments=choice,
            offered=(1, 2),
            cost_usd=0.003,
        ),
        _call(case_id, "coding", 2, tool=None, protocol_error="bad", cost_usd=0.002),
        _call(case_id, "coding", 3, tool="describe_codes", arguments=lookup, cost_usd=0.001),
        # The real shape: the loop usually submits the answer during the coding step.
        _call(
            case_id,
            "answer" if case_id.endswith("2") else "coding",
            4,
            tool="submit_answer",
            cost_usd=0.006,
        ),
    ]


def _write_run(
    mirror: Path,
    run_id: str,
    specs: Sequence[
        tuple[ClosureRecord | ClosureRecordV1, dict[str, Any] | None, Hypothesis | None]
    ],
) -> Path:
    folder = mirror / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / CLOSURES_FILE).write_text("".join(r.model_dump_json() + "\n" for r, _, _ in specs))
    (folder / INPUTS_FILE).write_text(
        "".join(json.dumps(raw) + "\n" for _, raw, _ in specs if raw is not None)
    )
    results = []
    calls = []
    for record, _, hypothesis in specs:
        if hypothesis is None:
            results.append(_result(record.case_id, failure=record.failure, steps=()))
            continue
        first = hypothesis.model_copy(
            update={"abstain": False, "occurrence": tuple(reversed(hypothesis.occurrence))}
        )
        steps = (
            _step(record.case_id, first).model_copy(
                update={"tool": "checkpoint:h0", "payload_fingerprint": "FP-MARKER-1"}
            ),
            _step(record.case_id, hypothesis).model_copy(
                update={"step": 1, "tool": "checkpoint:answer", "cost_usd": 0.006}
            ),
        )
        scores = dataclasses.replace(
            _scores(record.top1 is True), finding_precision_10=0.4, finding_recall_10=0.3
        )
        results.append(_result(record.case_id, steps=steps, scores=scores))
        calls.extend(_calls(record.case_id))
    write_jsonl(folder / CASES_FILE, results)
    write_jsonl(folder / "trail.jsonl", calls)
    write_jsonl(folder / "run.jsonl", [_run_record()])  # finished: the commit point (item A3)
    (folder / "docket").mkdir()
    (folder / "docket" / "1.txt").write_text("DOC-TEXT-MARKER: the wreckage was examined.")
    return folder


def _record(case_id: str, closed_on: date, **changes: Any) -> ClosureRecord:
    base: dict[str, Any] = {
        "closed_on": closed_on,
        "event_date": closed_on - timedelta(days=40),
        "documents": _lines(),
        "model": "openai/gpt-6-luna",
        "scored": True,
        "top1": True,
        "top3": True,
        "abstained": False,
        "first_sent": datetime(2026, 10, 9, 3, 14, tzinfo=UTC),
        "replied_models": ("openai/gpt-6-luna-2026-09-30",),
        "providers": ("ExampleProvider",),
        "prompt_version": "s3-v1+x",
        "commit_sha": "a1b2c3d",
    }
    return _closure(case_id, **{**base, **changes})


def _mirror(tmp_path: Path) -> Path:
    mirror = tmp_path / "mirror"
    ev = date(2026, 8, 1)
    specs = [
        (
            _record("XXX26XX001", date(2026, 10, 9)),
            _two_more_aircraft(_raw("XXX26XX001", ev)),
            _hypothesis(
                LOC_FLIGHT,
                OTHER,
                cause="Invented Owner lost control of N123XX.",
                # Item A9: the second aircraft's registration, any case, and a short one kept.
                account="Invented Owner flew N123XX low past n456yy; the N1 gauge read low.",
            ),
        ),
        (
            _record("XXX26XX002", date(2026, 10, 8), top1=False, top3=True),
            _raw("XXX26XX002", ev, amateur=True),
            _hypothesis(OTHER, LOC_FLIGHT),
        ),
        (
            _record(
                "XXX26XX003",
                date(2026, 10, 7),
                top1=False,
                top3=False,
                # Item A9: the owner string in capitals, in a title.
                documents=(
                    *_lines(),
                    DocumentLine(
                        position=4,
                        title="Letter from INVENTED OWNER",
                        status="unreadable: not a pdf",
                        ellery=None,
                    ),
                ),
            ),
            _raw("XXX26XX003", ev),
            _hypothesis(OTHER),
        ),
        (
            _record("XXX26XX004", date(2026, 10, 6), top1=False, top3=False, abstained=True),
            _raw("XXX26XX004", ev),
            _hypothesis(OTHER, abstain=True),
        ),
        (
            _record("XXX26XX005", date(2026, 10, 5), scored=False, top1=None, top3=None),
            _no_codes(_raw("XXX26XX005", ev)),
            _hypothesis(STALL),
        ),
        (
            _record(
                "XXX26XX006",
                date(2026, 10, 4),
                outcome="not coded",
                failure="leak: a document held the cause",
                scored=False,
                top1=None,
                top3=None,
            ),
            _raw("XXX26XX006", ev),
            None,
        ),
        (
            _record("XXX26XX007", date(2026, 10, 3), scored=False, top1=None, top3=None),
            _no_codes(_raw("XXX26XX007", ev)),
            _hypothesis(STALL, LOC_FLIGHT, cause="Invented Owner lost it."),
        ),
    ]
    _write_run(mirror, "20261009T040000Z-abc-live-C", specs)
    (mirror / "nights").mkdir()
    state = NightState(
        unreachable={
            "XXX26XX008": Closed(mkey=8, event_date=date(2026, 8, 5), closed_on=date(2026, 10, 1))
        }
    )
    (mirror / "nights" / "state.json").write_text(state.model_dump_json() + "\n")
    scores = mirror / "scores"
    scores.mkdir()
    later = _later("XXX26XX007", raw=_raw("XXX26XX007", ev), top1=True)
    write_jsonl(scores / "2026-10-11.jsonl", [later])
    return mirror


def _later(case_id: str, *, raw: dict[str, Any], top1: bool) -> LaterScore:
    verdict = split_record(raw)[2]
    return LaterScore(
        case_id=case_id,
        scored_on=date(2026, 10, 11),
        record_sha256="0" * 64,
        verdict_occurrence=verdict.occurrence_codes,
        verdict_findings=verdict.finding_codes,
        verdict_findings_in_cause=verdict.finding_codes_in_cause,
        ntsb_cause="Invented Owner failed to maintain control.",
        top1=top1,
        top3=True,
        abstained=False,
        finding_precision_10=0.5,
        finding_recall_10=0.25,
    )


def _build(tmp_path: Path, mirror: Path | None = None) -> Path:
    return build_export(
        mirror or _mirror(tmp_path),
        tmp_path / "out",
        store=None,
        today=TODAY,
        commit="deadbee",
        now=NOW,
    )


def _case(out: Path, number: str) -> CaseFile:
    return CaseFile.model_validate_json((out / "cases" / f"{number}.json").read_text())


def test_the_export_validates_and_the_rows_are_newest_first(tmp_path: Path) -> None:
    out = _build(tmp_path)
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    assert [r.case_number for r in index.rows] == [
        "XXX26XX001",
        "XXX26XX002",
        "XXX26XX003",
        "XXX26XX004",
        "XXX26XX005",
        "XXX26XX006",
        "XXX26XX007",
        "XXX26XX008",
    ]
    assert [r.closed_on for r in index.rows] == sorted(
        (r.closed_on for r in index.rows), reverse=True
    )
    for row in index.rows:
        assert _case(out, row.case_number).grade == row.grade
    assert index.stamp.commit == "deadbee"
    assert index.stamp.model == "openai/gpt-6-luna"
    assert index.counts.open_watched == 0
    assert index.counts.closures_per_night == {}
    assert index.counts.not_coded == {"leak": 1, "unreachable": 1}
    assert index.counts.awaiting_ntsb == 1
    assert index.counts.coded == 6


def test_each_grade_comes_out_for_its_inputs(tmp_path: Path) -> None:
    out = _build(tmp_path)
    grades = {n: _case(out, n).grade for n in (f"XXX26XX00{i}" for i in range(1, 9))}
    assert grades == {
        "XXX26XX001": "same_first",
        "XXX26XX002": "same_codes_other_order",
        "XXX26XX003": "different",
        "XXX26XX004": "abstained",
        "XXX26XX005": "awaiting_ntsb",
        "XXX26XX006": "not_coded",
        "XXX26XX007": "same_first",  # graded from its later score
        "XXX26XX008": "not_coded",
    }


def test_row_shapes_match_the_sample(tmp_path: Path) -> None:
    out = _build(tmp_path)
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    rows = {r.case_number: r for r in index.rows}
    first = _case(out, "XXX26XX001")
    assert first.answer is not None
    assert (
        first.answer.occurrence[0].label == "Maneuvering-Low-alt flying / Loss of control in flight"
    )
    assert " - " in first.answer.findings[0].label
    assert rows["XXX26XX001"].agent_first == first.answer.occurrence[0]
    # abstained: no first code on the row, the codes kept in the answer
    assert rows["XXX26XX004"].agent_first is None
    abstained = _case(out, "XXX26XX004")
    assert abstained.answer is not None
    assert abstained.answer.abstained
    assert abstained.answer.occurrence
    assert abstained.comparison is not None
    # not coded: the NTSB's first code and verdict stay
    assert rows["XXX26XX006"].agent_first is None
    assert rows["XXX26XX006"].ntsb_first is not None
    failed = _case(out, "XXX26XX006")
    assert failed.verdict is not None
    assert failed.not_coded is not None
    assert failed.not_coded.sentence == NOT_CODED_SENTENCES["leak"]
    assert failed.answer is None
    assert failed.trail is None
    assert failed.withheld is None
    # awaiting: an answer and a trail, no verdict, no comparison
    waiting = _case(out, "XXX26XX005")
    assert waiting.answer is not None
    assert waiting.verdict is None
    assert waiting.comparison is None
    assert rows["XXX26XX005"].ntsb_first is None
    # took_days is the closure date less the event date
    assert first.took_days == 40
    assert first.facts is not None
    assert (first.facts.state, first.facts.kind_of_flight, first.facts.injury_level) == (
        "TX",
        "Personal",
        "Fatal",
    )
    assert (first.facts.documents_read, first.facts.documents_listed) == (1, 3)
    assert first.withheld is not None
    assert first.withheld.coded_at == datetime(2026, 10, 9, 3, 14, tzinfo=UTC)
    assert first.withheld.providers == ("ExampleProvider",)


def test_an_amateur_built_aircraft_keeps_category_and_engines_only(tmp_path: Path) -> None:
    out = _build(tmp_path)
    assert _case(out, "XXX26XX001").aircraft.engine_type is not None
    amateur = _case(out, "XXX26XX002").aircraft
    assert amateur.engine_type is None
    assert amateur.engines == 1
    assert amateur.category is not None


def test_the_trail_total_is_the_sum_of_its_parts(tmp_path: Path) -> None:
    out = _build(tmp_path)
    trail = _case(out, "XXX26XX001").trail
    assert trail is not None
    assert [b.kind for b in trail.beliefs] == ["h0", "answer"]
    assert [b.changed for b in trail.beliefs] == [False, True]
    parts = (
        sum(b.cost_usd for b in trail.beliefs)
        + sum(r.cost_usd for r in trail.read_choices)
        + sum(x.cost_usd for x in trail.lookups)
    )
    assert trail.total_usd == round(parts, 4) == 0.016
    # the answer submitted during the coding step is the answer belief's, not a lookup's
    assert [b.cost_usd for b in trail.beliefs] == [0.004, 0.006]
    assert trail.total_usd == round(sum(c.cost_usd for c in _calls("XXX26XX001")), 4)
    # the failed coding call's cost went onto the lookup that followed it
    assert [x.cost_usd for x in trail.lookups] == [0.003]
    (choice,) = trail.read_choices
    assert choice.step == "choice1"
    assert [(d.position, d.decision) for d in choice.documents] == [
        (1, "read"),
        (2, "skipped"),
        (3, "scan_only"),
    ]
    assert choice.documents[0].title == f"Statement of {NAME_MARKER}"
    assert choice.documents[0].note == f"{NAME_MARKER} may describe it."
    assert choice.reason == f"{NAME_MARKER}'s own statement comes first."
    (lookup,) = trail.lookups
    assert lookup.tool == "describe_codes"
    assert lookup.arguments["reason"] == f"Check {NAME_MARKER}'s stall code."
    assert lookup.arguments["codes"] == [STALL]


def test_the_comparison_marks_and_finding_scores(tmp_path: Path) -> None:
    out = _build(tmp_path)
    second = _case(out, "XXX26XX002")
    assert second.comparison is not None
    assert second.verdict is not None
    codes = [c.code for c in second.verdict.occurrence]
    agent = [c.code for c in second.comparison.agent_occurrence]
    assert [m.mark for m in second.comparison.agent_occurrence] == occurrence_marks(agent, codes)[0]
    # a score from the closure run carries the run's finding scores
    assert second.comparison.finding_precision_10 == 0.4
    assert second.comparison.finding_recall_10 == 0.3
    later = _case(out, "XXX26XX007")
    assert later.comparison is not None
    assert later.comparison.finding_recall_10 == 0.25
    assert later.comparison.finding_precision_10 == 0.5
    assert later.verdict is not None
    assert later.verdict.cause == f"{NAME_MARKER} failed to maintain control."


def test_an_unreachable_case_has_the_unreachable_sentence(tmp_path: Path) -> None:
    case = _case(_build(tmp_path), "XXX26XX008")
    assert case.facts is None
    assert case.not_coded is not None
    assert case.not_coded.kind == "unreachable"
    assert case.not_coded.sentence == NOT_CODED_SENTENCES["unreachable"]
    assert case.took_days == 57
    assert case.aircraft.category is None


def test_occurrence_marks() -> None:
    assert occurrence_marks(["552230", "552090"], ["552090", "551230"]) == (
        ["not_in_other", "other_place"],
        ["other_place", "not_in_other"],
    )
    same = occurrence_marks(["552090", "551230"], ["552090", "551230"])
    assert same == (["same_place", "same_place"], ["same_place", "same_place"])


@pytest.mark.parametrize(
    ("changes", "later", "expected"),
    [
        ({"outcome": "not coded", "scored": False}, None, "not_coded"),
        ({"scored": False, "top1": None, "top3": None, "abstained": None}, None, "awaiting_ntsb"),
        ({"abstained": True, "top1": False, "top3": False}, None, "abstained"),
        ({"top1": True, "top3": True}, None, "same_first"),
        ({"top1": False, "top3": True}, None, "same_codes_other_order"),
        ({"top1": False, "top3": False}, None, "different"),
        ({"scored": False, "top1": None, "top3": None}, "top1", "same_first"),
        ({"scored": False, "top1": None, "top3": None}, "top3", "same_codes_other_order"),
        ({"scored": False, "top1": None, "top3": None}, "none", "different"),
        ({"scored": False, "top1": None, "top3": None}, "abstained", "abstained"),
    ],
)
def test_grade(changes: dict[str, Any], later: str | None, expected: str) -> None:
    record = _record("XXX26XX001", date(2026, 10, 9), **changes)
    score = None
    if later is not None:
        score = _later("XXX26XX001", raw=_raw("XXX26XX001", date(2026, 8, 1)), top1=later == "top1")
        score = score.model_copy(
            update={"top3": later in {"top1", "top3"}, "abstained": later == "abstained"}
        )
    assert grade(record, score) == expected


def _strings(value: object, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every string value (path, text) and every key (path, key) in a JSON value."""
    if isinstance(value, Mapping):
        for key, inner in value.items():
            yield (*path, "<key>"), str(key)
            yield from _strings(inner, (*path, str(key)))
    elif isinstance(value, list):
        for inner in value:
            yield from _strings(inner, path)
    elif isinstance(value, str):
        yield path, value


def _violations(files: Mapping[str, object]) -> list[str]:
    found: list[str] = []
    for name, data in files.items():
        for path, text in _strings(data):
            low_text = text.lower()  # a name in capitals is still the name (item A9)
            found.extend(
                f"{name}: {bad!r} in {path}" for bad in FORBIDDEN if bad.lower() in low_text
            )
            if path and path[-1] == "<key>":
                low = text.lower()
                if any(part in low for part in FORBIDDEN_KEY_PARTS):
                    found.append(f"{name}: key {text!r}")
                allowed = path[:-1] in {("stamp",), ("withheld",)}
                if low == "model" and not allowed:
                    found.append(f"{name}: key 'model' at {path}")
    return found


def _all_files(out: Path) -> dict[str, object]:
    return {str(p.relative_to(out)): json.loads(p.read_text()) for p in sorted(out.rglob("*.json"))}


def test_the_export_never_holds_what_the_specification_forbids(tmp_path: Path) -> None:
    out = _build(tmp_path)
    files = _all_files(out)
    assert len(files) == 9
    assert _violations(files) == []
    everything = "".join(p.read_text() for p in out.rglob("*.json"))
    assert NAME_MARKER in everything
    assert "Statement of [name]" in everything


def test_the_never_holds_check_can_fail() -> None:
    planted: dict[str, object] = {
        "a.json": {"x": [{"note": "see N123XX"}], "registration": "n", "stamp": {"model": "m"}},
        "b.json": {"trail": {"model": "m"}, "payload_fingerprint": "f", "c": "Invented Owner"},
        "c.json": {"documents": [{"title": "Letter from INVENTED OWNER"}]},
        "d.json": {"beliefs": [{"account": "The second aircraft, n456yy, was parked."}]},
    }
    found = _violations(planted)
    assert any("c.json" in f and "Invented Owner" in f for f in found)  # capitals (item A9)
    assert any("d.json" in f and "N456YY" in f for f in found)
    assert any("N123XX" in f for f in found)
    assert any("'registration'" in f for f in found)
    assert any("'payload_fingerprint'" in f for f in found)
    assert any("'model' at" in f for f in found)
    assert any("Invented Owner" in f for f in found)
    assert not any("stamp" in f for f in found)


def test_a_stale_case_file_is_removed_from_the_output_folder(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "cases").mkdir(parents=True)
    (out / "cases" / "OLD26XX999.json").write_text("{}")
    _build(tmp_path)
    assert not (out / "cases" / "OLD26XX999.json").exists()


class _FakeStore:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def closures(self) -> list[Closure]:
        return [
            Closure(
                mkey=n,
                ntsb_number=f"XXX26XX{n:03d}",
                event_date="2026-08-01",
                closure_run=n,
                closed_on=day,
                closed_as="Completed",
            )
            for n, day in (
                (1, "2026-10-09"),
                (2, "2026-10-09"),
                (3, "2026-10-08"),
                (7, "2026-09-20"),  # before the queue's declared start
            )
        ]

    def watched_mkeys(self, *, today: str) -> list[int]:
        self.asked.append(today)
        return [1, 4, 5, 6]  # mkey 1 closed: it is not an open case

    def documents_recorded(self, mkey: int) -> int:
        return 0 if mkey == 6 else 2


def test_the_store_gives_counts_only(tmp_path: Path) -> None:
    store = _FakeStore()
    out = build_export(
        _mirror(tmp_path),
        tmp_path / "out",
        store=cast(Store, store),
        today=TODAY,
        commit="c",
        now=NOW,
    )
    counts = BoardIndex.model_validate_json((out / "index.json").read_text()).counts
    assert store.asked == ["2026-10-12"]
    assert counts.open_watched == 3
    assert counts.open_with_docket == 2
    assert counts.closures_per_night == {date(2026, 10, 8): 1, date(2026, 10, 9): 2}
    # the per-night counts reconcile with the queue's own selection
    queued = build_queue(cast(Store, store).closures(), frozenset())
    assert sum(counts.closures_per_night.values()) == len(queued) == 3
    assert _violations(_all_files(out)) == []


def test_a_mirror_with_no_runs_writes_an_empty_board(tmp_path: Path) -> None:
    mirror = tmp_path / "empty"
    mirror.mkdir()
    out = build_export(mirror, tmp_path / "out", store=None, today=TODAY, commit="c", now=NOW)
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    assert index.rows == ()
    assert index.counts.coded == 0
    assert index.stamp.model == "openai/gpt-6-luna"


def test_a_refinement_is_folded_into_the_answer_it_refines() -> None:
    from ntsb_probable_cause.live.board import _beliefs  # noqa: PLC0415
    from ntsb_probable_cause.live.names import CaseNames  # noqa: PLC0415
    from ntsb_probable_cause.scoring.codes import load_tables  # noqa: PLC0415

    answer = _hypothesis(STALL, account="Before refining.")
    refined = _hypothesis(LOC_FLIGHT, account="After refining for Invented Owner.")
    steps = (
        _step("X", answer).model_copy(update={"tool": "checkpoint:h0"}),
        _step("X", answer).model_copy(update={"tool": "checkpoint:answer"}),
        _step("X", refined).model_copy(update={"tool": "checkpoint:refine"}),
    )
    result: CaseResult = _result("X", steps=steps)
    calls = [_call("X", "answer", 0, cost_usd=0.01), _call("X", "refine", 1, cost_usd=0.005)]
    beliefs = _beliefs(result, calls, CaseNames(owner_operator=("Invented Owner",)), load_tables())
    assert [b.kind for b in beliefs] == ["h0", "answer"]
    assert beliefs[1].first.code == LOC_FLIGHT
    assert beliefs[1].changed
    assert beliefs[1].cost_usd == 0.015
    assert beliefs[1].account == f"After refining for {NAME_MARKER}."


def _one_run(tmp_path: Path, specs: Sequence[Any]) -> Path:
    mirror = tmp_path / "mirror"
    _write_run(mirror, "20261009T040000Z-abc-live-C", specs)
    return mirror


def _refused(mirror: Path, out: Path) -> str:
    with pytest.raises(ConfigurationError) as caught:
        build_export(mirror, out, store=None, today=TODAY, commit="c", now=NOW)
    assert not out.exists() or not list(out.rglob("*.json"))
    assert not [p for p in out.parent.iterdir() if p.name.startswith(".")]  # no temp folder left
    return str(caught.value)


def test_an_abstained_case_whose_codes_have_not_arrived_is_abstained(tmp_path: Path) -> None:
    """Ellery's abstain is known at coding, so it outranks waiting for the NTSB (spec 10.3)."""
    ev = date(2026, 8, 1)
    record = _record("XXX26XX001", date(2026, 10, 9), scored=False, top1=None, top3=None)
    assert record.abstained is False
    unscored = record.model_copy(update={"abstained": None})
    mirror = _one_run(
        tmp_path,
        [(unscored, _no_codes(_raw("XXX26XX001", ev)), _hypothesis(OTHER, abstain=True))],
    )
    out = _build(tmp_path, mirror)
    case = _case(out, "XXX26XX001")
    assert case.grade == "abstained"
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    assert index.counts.awaiting_ntsb == 0
    # the same case answered, not abstained, still waits
    waiting = _one_run(
        tmp_path / "w", [(unscored, _no_codes(_raw("XXX26XX001", ev)), _hypothesis(OTHER))]
    )
    assert _case(_build(tmp_path / "w", waiting), "XXX26XX001").grade == "awaiting_ntsb"


def test_grade_takes_the_answers_abstain_flag_over_the_record() -> None:
    record = _record("XXX26XX001", date(2026, 10, 9), scored=False, top1=None, top3=None)
    assert grade(record, None, abstained=True) == "abstained"
    assert grade(record, None, abstained=False) == "awaiting_ntsb"
    scored = _record("XXX26XX001", date(2026, 10, 9), top1=True)
    assert grade(scored, None, abstained=True) == "abstained"
    failed = _record("XXX26XX001", date(2026, 10, 9), outcome="not coded", scored=False)
    assert grade(failed, None, abstained=True) == "not_coded"


def test_a_version_1_record_in_the_mirror_is_refused(tmp_path: Path) -> None:
    v2 = _record("XXX26XX001", date(2026, 10, 9))
    fields = {
        k: v
        for k, v in v2.model_dump().items()
        if k in ClosureRecordV1.model_fields and k != "format"
    }
    v1 = ClosureRecordV1(**fields)
    mirror = _one_run(tmp_path, [(v1, _raw("XXX26XX001", date(2026, 8, 1)), _hypothesis(STALL))])
    message = _refused(mirror, tmp_path / "out")
    assert "version 1" in message
    assert "XXX26XX001" not in message


def test_a_run_with_no_inputs_file_is_refused_with_counts_only(tmp_path: Path) -> None:
    mirror = _mirror(tmp_path)
    (mirror / "runs" / "20261009T040000Z-abc-live-C" / INPUTS_FILE).unlink()
    message = _refused(mirror, tmp_path / "out")
    assert "7 cases: 7 no inputs file" in message
    assert "XXX26XX" not in message


def test_a_case_with_no_raw_record_is_refused(tmp_path: Path) -> None:
    ev = date(2026, 8, 1)
    mirror = _one_run(
        tmp_path,
        [
            (_record("XXX26XX001", date(2026, 10, 9)), _raw("XXX26XX001", ev), _hypothesis(STALL)),
            (_record("XXX26XX002", date(2026, 10, 8)), None, _hypothesis(STALL)),
        ],
    )
    message = _refused(mirror, tmp_path / "out")
    assert "1 cases: 1 no raw record" in message
    assert "XXX26XX" not in message


def test_a_coded_record_with_no_result_is_refused(tmp_path: Path) -> None:
    mirror = _mirror(tmp_path)
    folder = mirror / "runs" / "20261009T040000Z-abc-live-C"
    (folder / CASES_FILE).write_text("")
    message = _refused(mirror, tmp_path / "out")
    assert "coded with no result" in message
    assert "XXX26XX" not in message


def test_a_record_the_split_refuses_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mirror = _mirror(tmp_path)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise LeakageError("a case's text, which must not be quoted")

    monkeypatch.setattr("ntsb_probable_cause.live.board.split_record", refuse)
    message = _refused(mirror, tmp_path / "out")
    assert "refused by the split" in message
    assert "must not be quoted" not in message


def test_a_failed_build_leaves_the_previous_export_intact(tmp_path: Path) -> None:
    mirror = _mirror(tmp_path)
    out = _build(tmp_path, mirror)
    before = {p.name: p.read_text() for p in out.rglob("*.json")}
    (out / "keep.txt").write_text("not ours")
    (mirror / "runs" / "20261009T040000Z-abc-live-C" / INPUTS_FILE).unlink()
    with pytest.raises(ConfigurationError):
        build_export(mirror, out, store=None, today=TODAY, commit="c", now=NOW)
    assert {p.name: p.read_text() for p in out.rglob("*.json")} == before
    assert (out / "keep.txt").read_text() == "not ours"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_the_trail_total_is_every_calls_cost_even_a_claimed_by_no_part(tmp_path: Path) -> None:
    """A choice step whose calls were all refused still has its cost counted."""
    from ntsb_probable_cause.live.board import _trail  # noqa: PLC0415
    from ntsb_probable_cause.live.names import CaseNames  # noqa: PLC0415
    from ntsb_probable_cause.scoring.codes import load_tables  # noqa: PLC0415

    hypothesis = _hypothesis(STALL)
    steps = (
        _step("X", hypothesis).model_copy(update={"tool": "checkpoint:h0"}),
        _step("X", hypothesis).model_copy(update={"tool": "checkpoint:answer"}),
    )
    result: CaseResult = _result("X", steps=steps)
    calls = [
        _call("X", "h0", 0, cost_usd=0.01),
        _call("X", "choice1", 1, tool=None, protocol_error="bad", cost_usd=0.02),
        _call("X", "coding", 2, tool="submit_answer", cost_usd=0.03),
        _call("X", "coding", 3, tool=None, protocol_error="bad", cost_usd=0.04),
    ]
    record = _record("X", date(2026, 10, 9))
    trail = _trail(record, result, calls, CaseNames(owner_operator=()), load_tables(), frozenset())
    assert trail.total_usd == 0.1
    assert round(sum(b.cost_usd for b in trail.beliefs), 6) == 0.1  # nothing else claims a cost


def test_a_planted_name_and_registration_never_reach_the_export(tmp_path: Path) -> None:
    out = _build(tmp_path)
    first = _case(out, "XXX26XX001")
    assert first.trail is not None
    assert first.answer is not None
    answer_belief = first.trail.beliefs[-1]
    assert answer_belief.account == (
        f"{NAME_MARKER} flew {NAME_MARKER} low past {NAME_MARKER}; the N1 gauge read low."
    )
    assert answer_belief.cause == f"{NAME_MARKER} lost control of {NAME_MARKER}."
    assert first.answer.cause == f"{NAME_MARKER} lost control of {NAME_MARKER}."
    # the NTSB's cause at closure
    assert first.verdict is not None
    assert first.verdict.cause == f"{NAME_MARKER} in {NAME_MARKER} failed to maintain control."
    everything = "".join(p.read_text() for p in out.rglob("*.json"))
    assert "Invented Owner" not in everything
    assert "N123XX" not in everything
    assert "n456yy" not in everything.lower()
    assert "the N1 gauge read low" in everything  # a registration under 3 characters is kept
    third = _case(out, "XXX26XX003")
    assert third.trail is not None
    titles = [d.title for c in third.trail.read_choices for d in c.documents]
    assert "Letter from [name]" in titles


def test_a_registration_in_a_title_is_replaced(tmp_path: Path) -> None:
    ev = date(2026, 8, 1)
    record = _record("XXX26XX001", date(2026, 10, 9)).model_copy(
        update={
            "documents": (
                DocumentLine(position=1, title="Records for N123XX", status="read", ellery="read"),
            )
        }
    )
    mirror = _one_run(tmp_path, [(record, _raw("XXX26XX001", ev), _hypothesis(STALL))])
    text = "".join(p.read_text() for p in _build(tmp_path, mirror).rglob("*.json"))
    assert "N123XX" not in text
    assert "Records for [name]" in text


def test_the_closure_time_finding_scores_reach_the_comparison(tmp_path: Path) -> None:
    out = _build(tmp_path)
    for number in ("XXX26XX001", "XXX26XX002", "XXX26XX003", "XXX26XX004"):
        comparison = _case(out, number).comparison
        assert comparison is not None
        assert (comparison.finding_precision_10, comparison.finding_recall_10) == (0.4, 0.3)


def _refusable(raw: dict[str, Any]) -> dict[str, Any]:
    """``raw`` with the NTSB's cause copied into an evidence field: the split really refuses it."""
    leaky = copy.deepcopy(raw)
    leaky["aircrafts"][0]["aircraftModel"] = leaky["narratives"][0]["probableCause"]
    with pytest.raises(LeakageError):
        split_record(leaky, exclude=frozenset({EvidenceRole.PRELIM_NARRATIVE}))
    return leaky


def test_a_not_coded_leak_case_exports_with_no_verdict(tmp_path: Path) -> None:
    ev = date(2026, 8, 1)
    record = _record(
        "XXX26XX001",
        date(2026, 10, 9),
        outcome="not coded",
        failure="leak: a document held the cause",
        scored=False,
        top1=None,
        top3=None,
    )
    mirror = _one_run(tmp_path, [(record, _refusable(_raw("XXX26XX001", ev)), None)])
    out = _build(tmp_path, mirror)
    case = _case(out, "XXX26XX001")
    assert case.grade == "not_coded"
    assert case.verdict is None
    assert case.comparison is None
    assert case.not_coded is not None
    assert case.not_coded.sentence == NOT_CODED_SENTENCES["leak"]
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    assert index.rows[0].ntsb_first is None


def test_a_coded_case_the_split_really_refuses_fails_closed(tmp_path: Path) -> None:
    ev = date(2026, 8, 1)
    mirror = _one_run(
        tmp_path,
        [
            (
                _record("XXX26XX001", date(2026, 10, 9)),
                _refusable(_raw("XXX26XX001", ev)),
                _hypothesis(STALL),
            )
        ],
    )
    message = _refused(mirror, tmp_path / "out")
    assert "1 raw record refused by the split" in message


def test_a_failed_move_puts_the_previous_export_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil  # noqa: PLC0415

    mirror = _mirror(tmp_path)
    out = _build(tmp_path, mirror)
    before = {p.relative_to(out).as_posix(): p.read_text() for p in out.rglob("*.json")}
    real = shutil.move
    calls = {"n": 0}

    def flaky(src: str | Path, dst: str | Path) -> object:
        calls["n"] += 1
        if calls["n"] == 4:  # the new index.json, after cases/ was swapped
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr("ntsb_probable_cause.live.board.shutil.move", flaky)
    with pytest.raises(OSError, match="disk full"):
        build_export(mirror, out, store=None, today=TODAY, commit="other", now=NOW)
    monkeypatch.undo()
    assert {p.relative_to(out).as_posix(): p.read_text() for p in out.rglob("*.json")} == before
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_the_key_and_the_page_counts_reach_the_export(tmp_path: Path) -> None:
    out = _build(tmp_path)
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    rows = {r.case_number: r for r in index.rows}
    assert rows["XXX26XX001"].mkey == 7  # the closure record's key (``_closure`` gives 7)
    assert _case(out, "XXX26XX001").mkey == 7
    # a case settled unreachable carries the key its closure was kept with
    assert rows["XXX26XX008"].mkey == 8
    assert _case(out, "XXX26XX008").mkey == 8
    (choice,) = _case(out, "XXX26XX001").trail.read_choices  # type: ignore[union-attr]
    assert [d.pages for d in choice.documents] == [4, 17, None]


def _with_backfill(mirror: Path, case_ids: tuple[str, ...]) -> None:
    folder = next((mirror / "runs").iterdir())
    # The sink recognises a live run by its run record.
    write_jsonl(folder / "run.jsonl", [_run_record()])
    (folder / "backfill.json").write_text(
        Backfill(
            fixed_on=date(2026, 10, 1), case_ids=case_ids, sha256=backfill_digest(case_ids)
        ).model_dump_json()
    )


def test_a_backfill_sets_launched_on_and_each_rows_flag_and_is_not_exported(
    tmp_path: Path,
) -> None:
    mirror = _mirror(tmp_path)
    _with_backfill(mirror, ("XXX26XX001", "XXX26XX008", "XXX26XX999"))
    out = _build(tmp_path, mirror)
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    assert index.stamp.launched_on == date(2026, 10, 1)
    flags = {r.case_number: r.backfilled for r in index.rows}
    assert flags["XXX26XX001"] is True
    assert flags["XXX26XX008"] is True
    assert flags["XXX26XX002"] is False
    assert "XXX26XX999" not in flags  # the list is used for the flag only
    assert "XXX26XX999" not in "".join(p.read_text() for p in out.rglob("*.json"))


def test_with_no_backfill_launched_on_and_the_flags_are_none(tmp_path: Path) -> None:
    out = _build(tmp_path)
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    assert index.stamp.launched_on is None
    assert {r.backfilled for r in index.rows} == {None}


def test_not_offered_reasons_follow_the_readers_status(tmp_path: Path) -> None:
    statuses = (
        ("read", "read"),
        ("read", "skipped"),
        ("unreadable: scan", None),
        ("unreadable: not a pdf", None),
        ("skipped: photo-only", None),
        ("fetch failed", None),
        ("read", None),  # readable and never on offer: left out by the prompt ceiling
    )
    lines = tuple(
        DocumentLine(position=n, title=f"Doc {n}", status=status, ellery=ellery, pages=n)
        for n, (status, ellery) in enumerate(statuses, start=1)
    )
    ev = date(2026, 8, 1)
    mirror = _one_run(
        tmp_path,
        [
            (
                _record("XXX26XX001", date(2026, 10, 9), documents=lines),
                _raw("XXX26XX001", ev),
                _hypothesis(STALL),
            )
        ],
    )
    out = _build(tmp_path, mirror)
    (choice,) = _case(out, "XXX26XX001").trail.read_choices  # type: ignore[union-attr]
    got = [(d.decision, d.not_offered_reason, d.pages) for d in choice.documents]
    assert got == [
        ("read", None, 1),
        ("skipped", None, 2),
        ("scan_only", None, 3),
        ("not_offered", "not_pdf", 4),
        ("not_offered", "photo_only", 5),
        ("not_offered", "fetch_failed", 6),
        ("not_offered", "over_size_limit", 7),
    ]


def test_a_document_read_at_the_first_choice_is_already_read_at_the_second(
    tmp_path: Path,
) -> None:
    """Item A7: never ``not_offered`` with no reason (the S5 contract)."""
    lines = (
        DocumentLine(position=1, title="Doc 1", status="read", ellery="read"),
        DocumentLine(position=2, title="Doc 2", status="read", ellery="read"),
        DocumentLine(position=3, title="Doc 3", status="read", ellery="skipped"),
    )
    case_id = "XXX26XX001"
    second = {
        "decisions": [
            {"document": 2, "read": True, "expected_effect": "More detail."},
            {"document": 3, "read": False, "expected_effect": "Not needed."},
        ],
        "reason": "One more document.",
    }
    first = {
        "decisions": [
            {"document": 1, "read": True, "expected_effect": "The key facts."},
            {"document": 2, "read": False, "expected_effect": "Later, if needed."},
            {"document": 3, "read": False, "expected_effect": "Not needed."},
        ],
        "reason": "The first document first.",
    }
    mirror = _one_run(
        tmp_path,
        [
            (
                _record(case_id, date(2026, 10, 9), documents=lines),
                _raw(case_id, date(2026, 8, 1)),
                _hypothesis(STALL),
            )
        ],
    )
    folder = next((mirror / "runs").iterdir())
    calls = [
        _call(case_id, "h0", 0, tool="record_hypothesis"),
        _call(case_id, "choice1", 1, tool="choose_documents", arguments=first, offered=(1, 2, 3)),
        _call(case_id, "choice2", 2, tool="choose_documents", arguments=second, offered=(2, 3)),
        _call(case_id, "coding", 3, tool="submit_answer"),
    ]
    write_jsonl(folder / "trail.jsonl", calls)
    one, two = _case(_build(tmp_path, mirror), case_id).trail.read_choices  # type: ignore[union-attr]
    assert [(d.decision, d.not_offered_reason) for d in one.documents] == [
        ("read", None),
        ("skipped", None),
        ("skipped", None),
    ]
    assert [(d.decision, d.not_offered_reason) for d in two.documents] == [
        ("not_offered", "already_read"),
        ("read", None),
        ("skipped", None),
    ]


def test_a_corrupt_spec_in_the_mirror_is_refused_with_no_path(tmp_path: Path) -> None:
    mirror = _mirror(tmp_path)
    folder = next((mirror / "runs").iterdir())
    (folder / "run.jsonl").unlink()  # a run with no record yet is told by its spec alone
    (folder / "spec.json").write_text("{not json")
    message = _refused(mirror, tmp_path / "out")
    assert "unreadable" in message
    assert str(tmp_path) not in message


def test_every_docket_status_has_a_not_offered_answer() -> None:
    assert set(_NOT_OFFERED) | {"read", _SCAN_ONLY} == set(get_args(Status))
    # Item A7: the reader's three reasons, and the two the read choices give.
    reasons = {*_NOT_OFFERED.values(), "already_read", "over_size_limit"}
    assert reasons == set(get_args(NotOfferedReason))


@pytest.mark.parametrize("run_file", ["absent", "unfinished"])
def test_a_run_folder_whose_run_record_is_not_finished_is_not_exported(
    tmp_path: Path, run_file: str
) -> None:
    """Item A3: ``run.jsonl`` is the commit point, so a half-pulled run is never on the board."""
    ev = date(2026, 8, 1)
    mirror = _one_run(
        tmp_path,
        [(_record("XXX26XX001", date(2026, 10, 9)), _raw("XXX26XX001", ev), _hypothesis(STALL))],
    )
    folder = next((mirror / "runs").iterdir())
    if run_file == "absent":
        (folder / "run.jsonl").unlink()
    else:
        write_jsonl(folder / "run.jsonl", [_run_record().model_copy(update={"finished": None})])
    out = _build(tmp_path, mirror)
    index = BoardIndex.model_validate_json((out / "index.json").read_text())
    assert index.rows == ()
    assert not (out / "cases" / "XXX26XX001.json").exists()


def test_a_missing_word_list_refuses_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item A10: the title rule cannot run without its word list, so nothing is written."""
    monkeypatch.setattr(board, "known_title_words", lambda: (frozenset(), False))
    out = tmp_path / "out"
    with pytest.raises(ConfigurationError, match="word list"):
        _build(tmp_path)
    assert not (out / "index.json").exists()
