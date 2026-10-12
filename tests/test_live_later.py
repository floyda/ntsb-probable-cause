"""Later scores from invented run folders and a redacted development record (decision 0174)."""

import copy
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import load_record_fixtures
from tests.test_live_closure import _run as _run_record
from tests.test_live_morning import _result

from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.live.closure import CASES_FILE, RUN_FILE
from ntsb_probable_cause.live.later import (
    _EXCLUSIONS,
    AWAIT_ALERT_NIGHTS,
    Awaiting,
    awaiting,
    overdue,
    score_later,
)
from ntsb_probable_cause.live.morning import live_spec
from ntsb_probable_cause.live.records import CLOSURES_FILE, ClosureRecord
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import score_case
from ntsb_probable_cause.scoring.records import StepRecord, write_jsonl
from ntsb_probable_cause.scoring.samples import load_seen_pairs

TODAY = date(2026, 10, 20)


def _raw_with_codes() -> dict[str, Any]:
    for raw in load_record_fixtures():
        if split_record(raw)[2].occurrence_codes:
            return copy.deepcopy(dict(raw))
    raise AssertionError("no fixture with codes")


def _hypothesis(code: str) -> Hypothesis:
    return Hypothesis(
        evidence_narrative="n",
        occurrence=(OccurrenceGuess(phase=code[:3], event=code[3:], probability=0.5),),
        findings=(),
        probable_cause="p",
        lay_explanation="l",
        confidence=0.5,
        abstain=False,
        evidence_used=(),
    )


def _step(case_id: str, hypothesis: Hypothesis) -> StepRecord:
    return StepRecord(
        case_id=case_id,
        step=0,
        arm="C",
        condition="full",
        day=None,
        tool="answer",
        arguments={},
        reason="",
        expected_effect="",
        returned_roles=(),
        not_available=(),
        payload_fingerprint="f",
        hypothesis=hypothesis,
        observed_effect="",
        stop_reason="answered",
        model="m",
        price_variant="standard",
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=0.0,
        cumulative_cost_usd=0.0,
        commit_sha="abc",
        dirty=False,
    )


def _closure(case_id: str, **changes: Any) -> ClosureRecord:
    base: dict[str, Any] = {
        "case_id": case_id,
        "mkey": 7,
        "closed_on": date(2026, 10, 1),
        "closure_run": 1,
        "waited_days": 0,
        "first_sent": datetime(2026, 10, 13, 1, tzinfo=UTC),
        "last_returned": datetime(2026, 10, 13, 2, tzinfo=UTC),
        "commit_sha": "abc",
        "dirty": False,
        "prompt_version": "v",
        "price_variant": "standard",
        "model": "m",
        "reasoning_effort": None,
        "training_cutoff": date(2025, 1, 1),
        "training_cutoff_source": "s",
        "uv_lock_sha256": "0" * 64,
        "documents": (),
        "prelim_present": False,
        "outcome": "coded",
        "failure": None,
        "marks": (),
        "scored": False,
        "top1": None,
        "top3": None,
        "abstained": None,
        "cost_usd": 0.0,
        "event_date": date(2026, 9, 1),
        "listing_sha256": None,
        "request_sha256s": (),
        "replied_models": (),
        "providers": (),
    }
    return ClosureRecord(**{**base, **changes})


def _folder(tmp_path: Path, records: list[ClosureRecord], with_steps: bool = True) -> Path:
    folder = tmp_path / "run"
    folder.mkdir(exist_ok=True)
    (folder / CLOSURES_FILE).write_text("".join(r.model_dump_json() + "\n" for r in records))
    steps = (_step("X", _hypothesis("452240")),) if with_steps else ()
    write_jsonl(
        folder / CASES_FILE, [_result(r.case_id, steps=steps, scores=None) for r in records]
    )
    write_jsonl(folder / RUN_FILE, [_run_record()])  # finished: the commit point (item A3)
    return folder


def _case(coded_on: date = date(2026, 10, 13)) -> Awaiting:
    return Awaiting(
        case_id="X",
        mkey=7,
        event_date=date(2026, 9, 1),
        closed_on=date(2026, 10, 1),
        coded_on=coded_on,
        answer=_hypothesis("452240"),
    )


def test_awaiting_finds_a_coded_unscored_case(tmp_path: Path) -> None:
    folder = _folder(tmp_path, [_closure("X")])
    (found,) = awaiting([folder], set())
    assert (found.case_id, found.mkey, found.event_date) == ("X", 7, date(2026, 9, 1))
    assert found.coded_on == date(2026, 10, 13)
    assert found.answer.occurrence[0].phase == "452"


def test_awaiting_leaves_out_scored_covered_not_coded_and_stepless(tmp_path: Path) -> None:
    records = [
        _closure("A", scored=True, top1=True, top3=True, abstained=False),
        _closure("B"),
        _closure("C", outcome="not coded", failure="schema"),
    ]
    folder = _folder(tmp_path, records)
    assert awaiting([folder], {"B"}) == []
    assert awaiting([_folder(tmp_path, [_closure("D")], with_steps=False)], set()) == []


def test_awaiting_skips_version_1_records_and_empty_folders(tmp_path: Path) -> None:
    folder = _folder(tmp_path, [_closure("X")])
    v1 = _closure("X").model_dump(mode="json")
    for key in ("event_date", "listing_sha256", "request_sha256s", "replied_models", "providers"):
        del v1[key]
    v1["format"] = "live-closure/1"
    (folder / CLOSURES_FILE).write_text(json.dumps(v1) + "\n")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert awaiting([empty, folder], set()) == []


def test_awaiting_counts_a_case_once_across_folders(tmp_path: Path) -> None:
    one = _folder(tmp_path, [_closure("X")])
    two = tmp_path / "run2"
    two.mkdir()
    for name in (CLOSURES_FILE, CASES_FILE, RUN_FILE):
        (two / name).write_text((one / name).read_text())
    assert len(awaiting([one, two], set())) == 1


def test_no_codes_gives_none() -> None:
    raw = _raw_with_codes()
    raw["aircrafts"][0]["events"] = []
    assert score_later(raw, _case(), TODAY) is None


def test_a_later_score_equals_the_score_at_coding_and_hashes_the_record() -> None:
    raw = _raw_with_codes()
    case = _case()
    later = score_later(raw, case, TODAY)
    assert later is not None
    verdict = split_record(raw)[2]
    expected = score_case(case.answer, verdict, load_tables(), seen_pairs=load_seen_pairs())
    assert later.top1 == expected.occurrence_top1
    assert later.top3 == expected.occurrence_top3
    assert later.abstained == expected.abstained
    assert later.finding_recall_10 == expected.finding_recall_10
    assert later.finding_precision_10 == expected.finding_precision_10
    assert later.verdict_occurrence == verdict.occurrence_codes
    assert later.verdict_findings_in_cause == verdict.finding_codes_in_cause
    assert later.ntsb_cause == verdict.probable_cause
    assert later.scored_on == TODAY
    changed = copy.deepcopy(raw)
    changed["aircrafts"][0]["events"][0]["eventCode"] = "999999"
    other = score_later(changed, case, TODAY)
    assert other is not None
    assert other.record_sha256 != later.record_sha256


def test_overdue_counts_seven_nights_not_six() -> None:
    seven = _case(date(2026, 10, 20 - AWAIT_ALERT_NIGHTS))
    six = _case(date(2026, 10, 20 - AWAIT_ALERT_NIGHTS + 1))
    assert overdue([seven, six], TODAY) == 1


def test_a_case_scored_in_another_folder_is_not_awaiting(tmp_path: Path) -> None:
    one = _folder(tmp_path, [_closure("X")])
    two = tmp_path / "run2"
    two.mkdir()
    done = _closure("X", scored=True, top1=True, top3=True, abstained=False)
    (two / CLOSURES_FILE).write_text(done.model_dump_json() + "\n")
    (two / CASES_FILE).write_text((one / CASES_FILE).read_text())
    (two / RUN_FILE).write_text((one / RUN_FILE).read_text())
    assert awaiting([one, two], set()) == []
    assert awaiting([two, one], set()) == []


def test_a_case_with_a_later_not_coded_line_is_not_awaiting(tmp_path: Path) -> None:
    folder = _folder(tmp_path, [_closure("X"), _closure("X", outcome="not coded", failure="x")])
    assert awaiting([folder], set()) == []


def test_a_case_with_no_coding_time_is_skipped(tmp_path: Path) -> None:
    folder = _folder(tmp_path, [_closure("X", first_sent=None, last_returned=None)])
    assert awaiting([folder], set()) == []
    only_sent = _folder(tmp_path, [_closure("X", last_returned=None)])
    assert awaiting([only_sent], set())[0].coded_on == date(2026, 10, 13)


def test_the_split_exclusions_are_the_live_runs() -> None:
    assert _EXCLUSIONS == live_spec(1.0).exclusions == frozenset({EvidenceRole.PRELIM_NARRATIVE})


@pytest.mark.parametrize("run_file", ["absent", "unfinished"])
def test_a_folder_whose_run_record_is_not_finished_is_never_read(
    tmp_path: Path, run_file: str
) -> None:
    """Item A3: ``run.jsonl`` is the commit point; any other folder is a run still to resume."""
    folder = _folder(tmp_path, [_closure("X")])
    if run_file == "absent":
        (folder / RUN_FILE).unlink()
    else:
        write_jsonl(folder / RUN_FILE, [_run_record().model_copy(update={"finished": None})])
    assert awaiting([folder], set()) == []
