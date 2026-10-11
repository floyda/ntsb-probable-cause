"""An invented ``board/1`` sample for the public site's development (decision 0173).

Status
    Test support (S4 Task 3). Free. Writes ``tests/fixtures/board/`` from invented values; no
    real case, record or run is read. Case numbers are ``XXX26XX001`` to ``XXX26XX007``: the
    first six one per grade, the seventh a case settled unreachable. Code labels come from the
    real code tables so the site sees realistic labels.

Usage:
    uv run --locked python -m tests.board_sample
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from ntsb_probable_cause.live.export import (
    NOT_CODED_SENTENCES,
    Aircraft,
    Answer,
    Belief,
    BoardIndex,
    BoardRow,
    BuildStamp,
    CaseFile,
    Code,
    CodeMark,
    Comparison,
    Counts,
    DocumentChoice,
    Facts,
    Lookup,
    MarkedCode,
    NotCoded,
    ReadChoice,
    Trail,
    Verdict,
    Withheld,
)
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.sources import TRAINING_CUTOFFS

Decision = Literal["read", "skipped", "scan_only", "not_offered"]
Reason = Literal["not_pdf", "photo_only", "fetch_failed"]

# Values a real source record would hold. The sample must not contain them.
FORBIDDEN: Final = ("N123XX", "Inventedmake", "INV-1", "Invented Owner", "lay explanation marker")

OUT: Final = Path("tests/fixtures/board")
MODEL: Final = "openai/gpt-6-luna"
COMMIT: Final = "a1b2c3d"
PROMPT: Final = "s3-v1+ge17fecdc66ec+tdff9dea78f23"
LAUNCHED_ON: Final = date(2026, 10, 9)
# Cases in the invented launch backfill; every other sample case is not.
BACKFILLED: Final = frozenset(
    {"XXX26XX003", "XXX26XX004", "XXX26XX005", "XXX26XX006", "XXX26XX007"}
)
CODED_AT: Final = datetime(2026, 10, 9, 3, 14, 7, tzinfo=UTC)
_TABLES = load_tables()


def _occ(phase: str, event: str) -> Code:
    """An occurrence code (phase then event) with its label from the real tables."""
    label = f"{_TABLES.phases[phase]} / {_TABLES.events[event]}"
    return Code(code=_TABLES.compose_occurrence(phase, event), label=label)


def _finding(item: str, modifier: str) -> Code:
    """A finding code (item then modifier) with its label from the real tables."""
    label = f"{_TABLES.items[item]} - {_TABLES.modifiers[modifier]}"
    return Code(code=_TABLES.compose_finding(item, modifier), label=label)


def _marks(own: Sequence[Code], other: Sequence[Code]) -> tuple[MarkedCode, ...]:
    other_codes = [c.code for c in other]
    out: list[MarkedCode] = []
    for place, c in enumerate(own):
        mark: CodeMark
        if c.code not in other_codes:
            mark = "not_in_other"
        elif other_codes[place : place + 1] == [c.code]:
            mark = "same_place"
        else:
            mark = "other_place"
        out.append(MarkedCode(code=c.code, label=c.label, mark=mark))
    return tuple(out)


def _comparison(answer: Answer, verdict: Verdict) -> Comparison:
    agent = {c.code for c in answer.findings}
    ntsb = {c.code for c in verdict.findings}
    both = tuple(c for c in answer.findings if c.code in ntsb)
    ntsb_only = tuple(c for c in verdict.findings if c.code not in agent)
    agent_only = tuple(c for c in answer.findings if c.code not in ntsb)
    return Comparison(
        agent_occurrence=_marks(answer.occurrence, verdict.occurrence),
        ntsb_occurrence=_marks(verdict.occurrence, answer.occurrence),
        findings_both=both,
        findings_ntsb_only=ntsb_only,
        findings_agent_only=agent_only,
        finding_precision_10=len(both) / len(answer.findings) if answer.findings else None,
        finding_recall_10=len(both) / len(ntsb) if ntsb else None,
    )


def _belief(  # noqa: PLR0913, PLR0917 -- a flat constructor keeps the sample readable
    kind: str, first: Code, cause: str, account: str, conf: float, changed: bool, cost: float
) -> Belief:
    return Belief.model_validate(
        {
            "kind": kind,
            "first": first,
            "cause": cause,
            "account": account,
            "confidence": conf,
            "changed": changed,
            "cost_usd": cost,
        }
    )


def _trail(
    beliefs: tuple[Belief, ...],
    read_choices: tuple[ReadChoice, ...],
    lookups: tuple[Lookup, ...],
) -> Trail:
    """A trail whose total is the sum of its parts, rounded to four places."""
    total = sum(b.cost_usd for b in beliefs)
    total += sum(r.cost_usd for r in read_choices) + sum(x.cost_usd for x in lookups)
    return Trail(
        beliefs=beliefs, read_choices=read_choices, lookups=lookups, total_usd=round(total, 4)
    )


def _simple_trail(
    first: Code,
    cause: str,
    account: str,
    conf: float,
    docs: Sequence[tuple[str, Decision] | tuple[str, Decision, Reason]] = (),
) -> Trail:
    """A short trail: one read choice over ``docs``, two beliefs, one lookup.

    A document is ``(title, decision)`` or, for a ``not_offered`` one, ``(title, decision,
    reason)``. Each document has a page count of ``2 * position + 1``.
    """
    choices: tuple[ReadChoice, ...] = ()
    if docs:
        documents = tuple(
            DocumentChoice(
                position=n,
                title=title,
                decision=decision,
                note=(
                    "May bear on the cause."
                    if decision == "read"
                    else "Unlikely to change the answer."
                    if decision == "skipped"
                    else None
                ),
                pages=2 * n + 1,
                not_offered_reason=doc[2] if len(doc) == 3 else None,
            )
            for n, doc in enumerate(docs, start=1)
            for title, decision in [doc[:2]]
        )
        choices = (
            ReadChoice(
                step="choice1",
                reason="These documents are the likeliest to show what happened.",
                documents=documents,
                cost_usd=0.0031,
            ),
        )
    return _trail(
        (
            _belief("h0", first, cause, account, conf - 0.1, False, 0.0041),
            _belief("answer", first, cause, account, conf, False, 0.0066),
        ),
        choices,
        (
            Lookup(
                tool="describe_codes",
                arguments={
                    "kind": "occurrence",
                    "codes": [first.code],
                    "reason": "Check the meaning of the first code before answering.",
                    "expected_effect": "Confirms the label matches the evidence read.",
                },
                cost_usd=0.0012,
            ),
        ),
    )


def _withheld() -> Withheld:
    return Withheld(
        coded_at=CODED_AT,
        commit=COMMIT,
        prompt_version=PROMPT,
        model=MODEL,
        replied_models=(MODEL + "-2026-09-30",),
        providers=("ExampleProvider",),
    )


def _cases() -> tuple[CaseFile, ...]:
    """The seven invented cases: six grades, then an unreachable case."""
    stall = _occ("452", "241")
    loc_flight = _occ("452", "240")
    hard = _occ("551", "092")
    loc_ground = _occ("552", "230")
    undershoot = _occ("508", "370")
    fuel = _occ("402", "192")
    power = _occ("402", "342")
    control = _finding("02063040", "11")
    fuel_plan = _finding("02061030", "11")
    fuel_dist = _finding("01022820", "02")
    weather = _finding("02061020", "11")

    # 001 same_first: two read choices, a scan-only document, four beliefs.
    a1 = Answer(
        occurrence=(stall, loc_flight),
        findings=(control, weather),
        cause=(
            "The pilot's failure to maintain airspeed while maneuvering at low altitude, which "
            "resulted in an aerodynamic stall."
        ),
        confidence=0.62,
        abstained=False,
    )
    v1 = Verdict(
        occurrence=(stall, loc_flight),
        findings=(control, fuel_plan),
        cause="The pilot's failure to maintain airspeed during low-altitude maneuvering.",
    )
    docs = ("Pilot statement", "Airworthiness records", "Wreckage examination")
    c1 = CaseFile(
        case_number="XXX26XX001",
        mkey=900101,
        closed_on=date(2026, 10, 9),
        took_days=47,
        aircraft=Aircraft(category="Airplane", engines=1, engine_type="Reciprocating"),
        grade="same_first",
        facts=Facts(
            state="TX",
            kind_of_flight="Personal",
            injury_level="Fatal",
            documents_read=3,
            documents_listed=5,
        ),
        withheld=_withheld(),
        answer=a1,
        verdict=v1,
        comparison=_comparison(a1, v1),
        trail=_trail(
            beliefs=(
                _belief(
                    "h0",
                    loc_flight,
                    "The pilot lost control of the airplane in flight.",
                    "A single-engine airplane was flying at low altitude when it struck the "
                    "ground. The record gives the weather as clear and the flight as personal. "
                    "It does not yet say what the airplane was doing before the impact.",
                    0.35,
                    False,
                    0.0038,
                ),
                _belief(
                    "h1",
                    stall,
                    "The pilot allowed the airplane to stall while maneuvering.",
                    "The pilot's statement and the airworthiness records show no fault in the "
                    "engine or controls. Witnesses saw the airplane bank steeply and slow "
                    "before it descended. The evidence so far points to a stall.",
                    0.5,
                    True,
                    0.0052,
                ),
                _belief(
                    "h2",
                    stall,
                    "The pilot failed to maintain airspeed, and the airplane stalled.",
                    "The wreckage examination found the flight controls connected and the "
                    "engine producing power at impact. The flaps were retracted. The damage "
                    "fits a steep nose-down impact after a stall at low altitude.",
                    0.58,
                    False,
                    0.0049,
                ),
                _belief(
                    "answer",
                    stall,
                    a1.cause,
                    "The airplane was maneuvering at low altitude with a working engine and "
                    "intact controls. Airspeed fell below the stall speed in a steep turn. "
                    "The pilot did not recover before the airplane reached the ground.",
                    0.62,
                    False,
                    0.0071,
                ),
            ),
            read_choices=(
                ReadChoice(
                    step="choice1",
                    reason="The first three documents are the likeliest to show what the "
                    "airplane was doing and whether it was serviceable.",
                    documents=(
                        DocumentChoice(
                            position=1,
                            title=docs[0],
                            decision="read",
                            note="May describe the maneuver before the impact.",
                            pages=4,
                        ),
                        DocumentChoice(
                            position=2,
                            title=docs[1],
                            decision="read",
                            note="Should show whether a mechanical fault is plausible.",
                            pages=12,
                        ),
                        DocumentChoice(
                            position=3,
                            title=docs[2],
                            decision="skipped",
                            note="Likely to repeat what the pilot statement already shows.",
                            pages=20,
                        ),
                        DocumentChoice(
                            position=4,
                            title="Handwritten pilot form",
                            decision="scan_only",
                            note=None,
                            pages=2,
                        ),
                        DocumentChoice(
                            position=5,
                            title="Radar and radio record",
                            decision="skipped",
                            note="Long and unlikely to change the answer.",
                            pages=31,
                        ),
                    ),
                    cost_usd=0.0033,
                ),
                ReadChoice(
                    step="choice2",
                    reason="The records show no fault, so the wreckage examination is the next "
                    "document that can confirm or rule out a mechanical cause.",
                    documents=(
                        DocumentChoice(
                            position=1, title=docs[0], decision="not_offered", note=None, pages=4
                        ),
                        DocumentChoice(
                            position=2, title=docs[1], decision="not_offered", note=None, pages=12
                        ),
                        DocumentChoice(
                            position=3,
                            title=docs[2],
                            decision="read",
                            note="Would show engine power and control continuity at impact.",
                            pages=20,
                        ),
                        DocumentChoice(
                            position=4,
                            title="Handwritten pilot form",
                            decision="scan_only",
                            note=None,
                            pages=2,
                        ),
                        DocumentChoice(
                            position=5,
                            title="Radar and radio record",
                            decision="skipped",
                            note="Still unlikely to change the answer.",
                            pages=31,
                        ),
                    ),
                    cost_usd=0.0029,
                ),
            ),
            lookups=(
                Lookup(
                    tool="describe_codes",
                    arguments={
                        "kind": "occurrence",
                        "codes": [stall.code],
                        "reason": "Check what the stall code covers before using it.",
                        "expected_effect": "Confirms the code fits a stall at low altitude.",
                    },
                    cost_usd=0.0011,
                ),
                Lookup(
                    tool="occurrence_usage",
                    arguments={
                        "codes": [stall.code, loc_flight.code],
                        "reason": "See how often each code is coded first.",
                        "expected_effect": "Decides which code to put first.",
                    },
                    cost_usd=0.0013,
                ),
                Lookup(
                    tool="past_findings",
                    arguments={
                        "occurrence": stall.code,
                        "reason": "See which findings usually follow this code.",
                        "expected_effect": "Suggests the findings to list.",
                    },
                    cost_usd=0.0012,
                ),
                Lookup(
                    tool="suggest_codes",
                    arguments={
                        "phase_group": "Maneuvering",
                        "reason": "See the codes common in this phase of flight.",
                        "expected_effect": "Checks no common code was missed.",
                    },
                    cost_usd=0.0014,
                ),
            ),
        ),
        not_coded=None,
    )

    # 002 same codes, other order.
    a2 = Answer(
        occurrence=(loc_ground, hard),
        findings=(control,),
        cause="The pilot's loss of directional control during the landing roll.",
        confidence=0.55,
        abstained=False,
    )
    v2 = Verdict(
        occurrence=(hard, loc_ground),
        findings=(control, _finding("02063040", "20")),
        cause="The pilot's improper flare, which resulted in a hard landing and a loss of control.",
    )
    c2 = CaseFile(
        case_number="XXX26XX002",
        mkey=900102,
        closed_on=date(2026, 10, 9),
        took_days=61,
        aircraft=Aircraft(category="Airplane", engines=1, engine_type="Reciprocating"),
        grade="same_codes_other_order",
        facts=Facts(
            state="OH",
            kind_of_flight="Instructional",
            injury_level="Serious",
            documents_read=2,
            documents_listed=2,
        ),
        withheld=_withheld(),
        answer=a2,
        verdict=v2,
        comparison=_comparison(a2, v2),
        trail=_simple_trail(
            loc_ground,
            a2.cause,
            "The airplane touched down and then left the runway. The instructor's statement "
            "says the aircraft veered before it reached taxi speed. No mechanical fault is "
            "recorded in the documents read.",
            0.55,
            (("Instructor statement", "read"), ("Airworthiness records", "read")),
        ),
        not_coded=None,
    )

    # 003 different; amateur-built, so category and engines only.
    a3 = Answer(
        occurrence=(undershoot,),
        findings=(weather,),
        cause="The pilot's failure to maintain the glidepath on final approach.",
        confidence=0.41,
        abstained=False,
    )
    v3 = Verdict(
        occurrence=(fuel, power),
        findings=(fuel_plan, fuel_dist),
        cause="The pilot's inadequate fuel planning, which resulted in fuel exhaustion.",
    )
    c3 = CaseFile(
        case_number="XXX26XX003",
        mkey=900103,
        closed_on=date(2026, 10, 7),
        took_days=88,
        aircraft=Aircraft(category="Airplane", engines=1, engine_type=None),
        grade="different",
        facts=Facts(
            state="WA",
            kind_of_flight="Personal",
            injury_level="Fatal",
            documents_read=1,
            documents_listed=5,
        ),
        withheld=_withheld(),
        answer=a3,
        verdict=v3,
        comparison=_comparison(a3, v3),
        trail=_simple_trail(
            undershoot,
            a3.cause,
            "The airplane struck the ground short of the runway during an approach. The "
            "documents read describe the approach path but say little about the fuel on board.",
            0.41,
            (
                ("Pilot statement", "read"),
                ("Wreckage examination", "skipped"),
                ("Weather data", "skipped"),
                ("Photograph log", "not_offered", "photo_only"),
                ("Spreadsheet export", "not_offered", "not_pdf"),
            ),
        ),
        not_coded=None,
    )

    # 004 abstained.
    a4 = Answer(
        occurrence=(loc_flight,),
        findings=(),
        cause="The evidence read does not support a probable cause.",
        confidence=0.12,
        abstained=True,
    )
    v4 = Verdict(
        occurrence=(_occ("402", "341"),),
        findings=(_finding("01022820", "01"),),
        cause="A total loss of engine power due to a fuel system failure.",
    )
    c4 = CaseFile(
        case_number="XXX26XX004",
        mkey=900104,
        closed_on=date(2026, 10, 5),
        took_days=102,
        aircraft=Aircraft(category="Airplane", engines=2, engine_type="Reciprocating"),
        grade="abstained",
        facts=Facts(
            state="FL",
            kind_of_flight="Business",
            injury_level="Fatal",
            documents_read=0,
            documents_listed=1,
        ),
        withheld=_withheld(),
        answer=a4,
        verdict=v4,
        comparison=_comparison(a4, v4),
        trail=_simple_trail(
            loc_flight,
            a4.cause,
            "The record gives a twin-engine airplane that descended during cruise. The docket "
            "holds one document and it could not be read. There is not enough to name a cause.",
            0.12,
            (("Handwritten pilot form", "scan_only"),),
        ),
        not_coded=None,
    )

    # 005 not coded.
    v5 = Verdict(
        occurrence=(_occ("300", "341"),),
        findings=(_finding("01022820", "01"),),
        cause="A total loss of engine power on takeoff.",
    )
    c5 = CaseFile(
        case_number="XXX26XX005",
        mkey=900105,
        closed_on=date(2026, 10, 2),
        took_days=75,
        aircraft=Aircraft(category="Helicopter", engines=1, engine_type="Turbo shaft"),
        grade="not_coded",
        facts=Facts(
            state="CO",
            kind_of_flight="Aerial observation",
            injury_level="Fatal",
            documents_read=0,
            documents_listed=4,
        ),
        withheld=None,
        answer=None,
        verdict=v5,
        comparison=None,
        trail=None,
        not_coded=NotCoded(kind="leak", sentence=NOT_CODED_SENTENCES["leak"]),
    )

    # 006 awaiting the NTSB's codes.
    a6 = Answer(
        occurrence=(power,),
        findings=(fuel_dist,),
        cause="A partial loss of engine power in cruise flight, from a fuel system fault.",
        confidence=0.57,
        abstained=False,
    )
    c6 = CaseFile(
        case_number="XXX26XX006",
        mkey=900106,
        closed_on=date(2026, 9, 29),
        took_days=54,
        aircraft=Aircraft(category="Airplane", engines=1, engine_type="Reciprocating"),
        grade="awaiting_ntsb",
        facts=Facts(
            state="AZ",
            kind_of_flight="Personal",
            injury_level="Minor",
            documents_read=2,
            documents_listed=3,
        ),
        withheld=_withheld(),
        answer=a6,
        verdict=None,
        comparison=None,
        trail=_simple_trail(
            power,
            a6.cause,
            "The airplane landed off the airport after the engine lost power in cruise. The "
            "pilot's statement and the maintenance records both mention fuel selector use.",
            0.57,
            (
                ("Pilot statement", "read"),
                ("Maintenance records", "read"),
                ("Radar data", "not_offered", "fetch_failed"),
            ),
        ),
        not_coded=None,
    )

    # 007 settled unreachable: no record could be read, so there are no facts.
    c7 = CaseFile(
        case_number="XXX26XX007",
        mkey=900107,
        closed_on=date(2026, 10, 1),
        took_days=57,
        aircraft=Aircraft(category=None, engines=None, engine_type=None),
        grade="not_coded",
        facts=None,
        withheld=None,
        answer=None,
        verdict=None,
        comparison=None,
        trail=None,
        not_coded=NotCoded(kind="unreachable", sentence=NOT_CODED_SENTENCES["unreachable"]),
    )
    return (c1, c2, c3, c4, c5, c6, c7)


def _row(case: CaseFile) -> BoardRow:
    answer, verdict = case.answer, case.verdict
    agent_first = (
        answer.occurrence[0]
        if answer is not None and not answer.abstained and answer.occurrence
        else None
    )
    ntsb_first = verdict.occurrence[0] if verdict is not None and verdict.occurrence else None
    return BoardRow(
        case_number=case.case_number,
        mkey=case.mkey,
        closed_on=case.closed_on,
        took_days=case.took_days,
        aircraft=case.aircraft,
        backfilled=case.case_number in BACKFILLED,
        agent_first=agent_first,
        ntsb_first=ntsb_first,
        grade=case.grade,
    )


def _dump(model: BaseModel) -> str:
    return model.model_dump_json(indent=2) + "\n"


def build() -> dict[str, str]:
    """The sample as ``{relative path: JSON text}``."""
    cases = _cases()
    cutoff = TRAINING_CUTOFFS[MODEL]
    rows = sorted((_row(c) for c in cases), key=lambda r: (-r.closed_on.toordinal(), r.case_number))
    index = BoardIndex(
        stamp=BuildStamp(
            built_at=datetime(2026, 10, 10, 6, 0, 0, tzinfo=UTC),
            commit=COMMIT,
            model=MODEL,
            training_cutoff=cutoff.day,
            training_cutoff_source=cutoff.source,
            launched_on=LAUNCHED_ON,
        ),
        counts=Counts(
            open_watched=212,
            open_with_docket=187,
            closures_per_night={
                date(2026, 9, 29): 1,
                date(2026, 10, 1): 1,
                date(2026, 10, 2): 1,
                date(2026, 10, 5): 1,
                date(2026, 10, 7): 1,
                date(2026, 10, 9): 2,
            },
            coded=5,
            not_coded={"leak": 1, "unreachable": 1},
            awaiting_ntsb=1,
        ),
        rows=tuple(rows),
    )
    out = {"index.json": _dump(index)}
    for c in cases:
        out[f"cases/{c.case_number}.json"] = _dump(c)
    return out


def main() -> int:
    """Write the sample under ``tests/fixtures/board/``."""
    for rel, text in build().items():
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
