"""The board/1 export builder, from invented run folders (S4 Task 11; decisions 0173, 0180, 0182).

No development or live data: every record is a redacted development fixture with invented values
planted in it, and every run folder is made here. The never-holds test reads every string and
every key of every exported file.
"""

import copy
import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from tests.test_live_later import _closure, _raw_with_codes, _step
from tests.test_live_morning import _call, _result, _scores

from ntsb_probable_cause.live.board import (
    build_export,
    grade,
    occurrence_marks,
    write_export,
)
from ntsb_probable_cause.live.closure import CASES_FILE
from ntsb_probable_cause.live.export import NOT_CODED_SENTENCES, BoardIndex, CaseFile
from ntsb_probable_cause.live.later import LaterScore
from ntsb_probable_cause.live.names import NAME_MARKER
from ntsb_probable_cause.live.records import (
    CLOSURES_FILE,
    INPUTS_FILE,
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
    aircraft["ownerOperators"] = [
        {
            "registeredOwner": "Invented Owner",
            "operatorName": "Invented Owner",
            "flightOperationType": "Personal",
        }
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
        DocumentLine(position=1, title="Statement of Smithers", status="read", ellery="read"),
        DocumentLine(position=2, title="Weather data", status="read", ellery="skipped"),
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
        _call(case_id, "answer", 4, tool="submit_answer", cost_usd=0.006),
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
        results.append(_result(record.case_id, steps=steps, scores=_scores(record.top1 is True)))
        calls.extend(_calls(record.case_id))
    write_jsonl(folder / CASES_FILE, results)
    write_jsonl(folder / "trail.jsonl", calls)
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
            _raw("XXX26XX001", ev),
            _hypothesis(LOC_FLIGHT, OTHER, cause="Invented Owner lost control."),
        ),
        (
            _record("XXX26XX002", date(2026, 10, 8), top1=False, top3=True),
            _raw("XXX26XX002", ev, amateur=True),
            _hypothesis(OTHER, LOC_FLIGHT),
        ),
        (
            _record("XXX26XX003", date(2026, 10, 7), top1=False, top3=False),
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
    # a score from the closure run carries the run's finding scores (None in the invented run)
    assert second.comparison.finding_recall_10 is None
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
            found.extend(f"{name}: {bad!r} in {path}" for bad in FORBIDDEN if bad in text)
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
    }
    found = _violations(planted)
    assert any("N123XX" in f for f in found)
    assert any("'registration'" in f for f in found)
    assert any("'payload_fingerprint'" in f for f in found)
    assert any("'model' at" in f for f in found)
    assert any("Invented Owner" in f for f in found)
    assert not any("stamp" in f for f in found)


def test_a_version_1_run_is_included_with_its_event_date_from_its_inputs(
    tmp_path: Path,
) -> None:
    mirror = tmp_path / "mirror"
    ev = date(2026, 9, 1)
    v2 = _record("XXX26XX001", date(2026, 10, 9))
    v1_fields = {
        k: v
        for k, v in v2.model_dump().items()
        if k in ClosureRecordV1.model_fields and k != "format"
    }
    v1 = ClosureRecordV1(**{**v1_fields, "case_id": "XXX26XX002", "closed_on": date(2026, 9, 30)})
    v1_lost = ClosureRecordV1(**{**v1_fields, "case_id": "XXX26XX003"})
    _write_run(
        mirror,
        "20260930T040000Z-abc-live-C",
        [
            (v1, _raw("XXX26XX002", ev), _hypothesis(STALL)),
            (v1_lost, None, _hypothesis(STALL)),
        ],
    )
    report = write_export(mirror, tmp_path / "out", store=None, today=TODAY, commit="c", now=NOW)
    assert (report.cases, report.skipped_no_event_date) == (1, 1)
    case = _case(tmp_path / "out", "XXX26XX002")
    assert case.took_days == 29
    assert case.withheld is not None
    assert case.withheld.replied_models == ()  # a version 1 trail holds no replying model
    assert case.grade == "same_first"


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
            for n, day in ((1, "2026-10-09"), (2, "2026-10-09"), (3, "2026-10-08"))
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
