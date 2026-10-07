"""The counts-only live report (S3.3 Task 10, spec sections 10 and 11)."""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import scripts.s33_live_report as module
from tests.test_live_morning import _result
from tests.test_live_records import _record

from ntsb_probable_cause.live.local import live_run_folders
from ntsb_probable_cause.live.queue import backfill_digest
from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    Backfill,
    ClosureRecord,
)
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl
from ntsb_probable_cause.store import Closure

report_text = module.report_text
TABLES = load_tables()
TODAY = date(2026, 10, 9)
PATTERN = re.compile(r"[A-Z]{3}\d{2}[A-Z]{2}\d{3}")
GOOD_OCCURRENCE = ("100010",)
GOOD_FINDING = ("0101000001",)

World = tuple[list[Path], list[Closure], list[dict[str, str]]]


def _res(case_id: str, **changes: Any) -> CaseResult:
    changes.setdefault("verdict_occurrence", GOOD_OCCURRENCE)
    changes.setdefault("verdict_findings", GOOD_FINDING)
    return _result(case_id, **changes)


def _run(run_id: str, day: int, *, cost: float, billed: float | None) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        sample="live",
        arm="C",
        exclusions=(),
        includes=(),
        prompt_version="v",
        model="m",
        price_variant="batch",
        cap_usd=0.3,
        budget_usd=40.0,
        commit_sha="abc",
        dirty=False,
        started=datetime(2026, 10, day, 1, tzinfo=UTC),
        finished=datetime(2026, 10, day, 2, tzinfo=UTC),
        cost_usd=cost,
        reported_batch_cost_usd=billed,
    )


def _closure_record(case_id: str, **changes: Any) -> ClosureRecord:
    return _record().model_copy(update={"case_id": case_id, "mkey": 7, **changes})


def _graded(case_id: str, top1: bool, top3: bool, **changes: Any) -> ClosureRecord:
    return _closure_record(case_id, scored=True, top1=top1, top3=top3, abstained=False, **changes)


def _folder(  # noqa: PLR0913 -- a test builder
    runs: Path,
    run_id: str,
    day: int,
    records: list[ClosureRecord],
    *,
    results: list[CaseResult] | None = None,
    cost: float = 0.4,
    billed: float | None = 0.3,
    backfill: Backfill | None = None,
) -> Path:
    folder = runs / run_id
    folder.mkdir(parents=True)
    write_jsonl(folder / "run.jsonl", [_run(run_id, day, cost=cost, billed=billed)])
    write_jsonl(
        folder / "cases.jsonl",
        results if results is not None else [_res(r.case_id) for r in records],
    )
    write_jsonl(folder / CLOSURES_FILE, records)
    if backfill is not None:
        (folder / BACKFILL_FILE).write_text(backfill.model_dump_json() + "\n")
    return folder


def _closures(*days: str) -> list[Closure]:
    return [
        Closure(
            mkey=i,
            ntsb_number=f"ERA26LA{i:03d}",
            event_date="2026-09-01",
            closure_run=i,
            closed_on=day,
        )
        for i, day in enumerate(days, start=1)
    ]


@pytest.fixture
def world(tmp_path: Path) -> World:
    ids = ("ERA26LA001", "ERA26LA002", "ERA26LA003")
    backfill = Backfill(fixed_on=date(2026, 10, 7), case_ids=ids, sha256=backfill_digest(ids))
    first = [
        _graded("ERA26LA001", True, True, waited_days=3),
        _graded("ERA26LA002", False, True, waited_days=5),
        _graded("ERA26LA003", False, False, waited_days=9, prelim_present=False),
    ]
    second = [
        _closure_record(
            "ERA26LA004", outcome="not coded", failure="format: bad json", scored=False
        ),
        _closure_record("ERA26LA005", closed_on=date(2026, 10, 8), waited_days=1),
    ]
    results = [
        _res("ERA26LA004", verdict_occurrence=("999999",), verdict_findings=("0000000099",)),
        _res("ERA26LA005", verdict_occurrence=()),
    ]
    folders = [
        _folder(tmp_path, "20261007-a", 7, first, backfill=backfill),
        _folder(tmp_path, "20261008-b", 8, second, results=results, cost=0.2, billed=None),
    ]
    refusals = [
        {"at": "2026-10-07T00:10:00+00:00", "reason": "daily-limit"},
        {"at": "2026-10-08T00:10:00+00:00", "reason": "daily-limit"},
        {"at": "2026-10-08T00:11:00+00:00", "reason": "monthly-cap"},
    ]
    closures = _closures(
        "2026-09-23", "2026-09-23", "2026-09-25", "2026-10-08", "2026-10-08", "2026-10-08"
    )
    return folders, closures, refusals


def _text(world: World, today: date = TODAY) -> str:
    folders, closures, refusals = world
    return report_text(folders, closures, TABLES, refusals, today=today)


def test_sections_come_in_the_specified_order(world: World) -> None:
    text = _text(world).lower()
    heads = ["mornings", "money", "outcomes", "checks", "backfill", "closures per night"]
    positions = [text.index(f"\n{h}") for h in heads]
    assert positions == sorted(positions)
    assert text.index("\nclosing rule inputs\n") > positions[-1]
    assert text.rstrip().splitlines()[-1].startswith("closing rule:")


def test_mornings_count_runs_cases_and_queue(world: World) -> None:
    text = _text(world)
    assert "runs: 2" in text
    assert "cases per run: 3, 2" in text
    assert "days waited: p50 3, max 9" in text
    assert "queue after each run (as the store stands today): 3, 1" in text
    assert "minutes, first round to last:" in text


def test_money_is_per_case_and_per_month_computed_and_billed(world: World) -> None:
    text = _text(world)
    assert "computed: $0.6000 in all, $0.1200 per case" in text
    assert "billed (1 of 2 runs reported): $0.3000 in all, $0.1000 per case" in text
    assert "2026-10: computed $0.6000, billed $0.3000" in text


def test_outcomes_have_the_three_grades_and_a_wilson_interval(world: World) -> None:
    text = _text(world)
    assert "first code right: 1" in text
    assert "right code in another position: 1" in text
    assert "different: 1" in text
    assert "95% interval for first code right (1 of 3 scored): 6% to 79%" in text
    assert "abstained: 0" in text
    assert "not coded, format: 1" in text


def test_the_new_checks(world: World) -> None:
    text = _text(world)
    assert "preliminary narrative present: 4 of 5" in text
    assert "refusals, daily-limit: 2" in text
    assert "refusals, monthly-cap: 1" in text
    assert "verdict codes missing from the tables, occurrence: 1 code in 1 case" in text
    assert "verdict codes missing from the tables, finding: 1 code in 1 case" in text
    assert "closures without a verdict: 1" in text
    assert "closures as N/A:" in text
    assert "returned to the queue:" in text


def test_the_backfill_is_a_count_and_a_digest(world: World) -> None:
    text = _text(world)
    digest = backfill_digest(("ERA26LA001", "ERA26LA002", "ERA26LA003"))
    assert f"backfill: 3 cases, SHA-256 {digest}" in text
    assert "fixed on 2026-10-07" in text


def test_closures_per_night_from_the_declared_start(world: World) -> None:
    text = _text(world)
    assert "2026-09-23: 2" in text
    assert "2026-09-24: 0" in text
    assert "2026-09-25: 1" in text
    assert "2026-10-08: 3" in text
    assert "2026-09-22" not in text


def test_no_case_id_key_or_held_out_figure(world: World) -> None:
    text = _text(world)
    assert not PATTERN.search(text)
    assert "mkey" not in text.lower()
    assert "heldout" not in text.lower()
    assert "23.5" not in text
    assert "never shown together" in text
    assert "wide" in text


def test_a_failure_text_that_names_a_case_is_cut_to_its_reason(tmp_path: Path) -> None:
    record = _closure_record(
        "ERA26LA001",
        outcome="not coded",
        failure="format: reply for ERA26LA001 held a bad title",
        scored=False,
    )
    folder = _folder(tmp_path, "20261008-b", 8, [record])
    text = report_text([folder], [], TABLES, [], today=TODAY)
    assert not PATTERN.search(text)
    assert "not coded, format: 1" in text


def test_closing_rule_not_met_while_the_backfill_is_draining(world: World) -> None:
    folders, closures, refusals = world
    cases = folders[0] / "cases.jsonl"
    cases.write_text("\n".join(cases.read_text().splitlines()[:2]) + "\n")  # one id undrained
    text = report_text(folders[:1], closures, TABLES, refusals, today=date(2026, 10, 30))
    assert "backfill drained: no" in text
    assert text.rstrip().endswith("closing rule: not met")


def test_closing_rule_met_by_a_fresh_closure(world: World) -> None:
    text = _text(world)
    assert "backfill drained: yes" in text
    assert "fresh closures coded: 1" in text
    assert "days since the first live morning: 2" in text
    assert text.rstrip().endswith("closing rule: met (fresh closure)")


def test_closing_rule_met_by_fourteen_days_with_no_fresh_closure(world: World) -> None:
    folders, closures, refusals = world
    (folders[1] / CLOSURES_FILE).write_text("")
    late = report_text(folders, closures, TABLES, refusals, today=date(2026, 10, 21))
    assert "fresh closures coded: 0" in late
    assert late.rstrip().endswith("closing rule: met (14 days)")
    early = report_text(folders, closures, TABLES, refusals, today=date(2026, 10, 20))
    assert early.rstrip().endswith("closing rule: not met")


def test_an_empty_world_still_reports() -> None:
    text = report_text([], [], TABLES, [], today=TODAY)
    assert "runs: 0" in text
    assert "backfill drained: no" in text
    assert text.rstrip().endswith("closing rule: not met")


def test_live_run_folders_uses_the_recognition_of_the_sink(tmp_path: Path) -> None:
    live = _folder(tmp_path, "weird-name", 7, [])
    dev = tmp_path / "20261007-dev"
    dev.mkdir()
    write_jsonl(
        dev / "run.jsonl",
        [_run("d", 7, cost=1, billed=None).model_copy(update={"sample": "dev-400"})],
    )
    assert live_run_folders(tmp_path) == [live]
    assert live_run_folders(tmp_path / "missing") == []


def test_main_writes_the_file_from_the_folders_the_store_and_the_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    _folder(runs, "20261007-a", 7, [_graded("ERA26LA001", True, True)])
    (runs / "live-refusals.jsonl").write_text(
        json.dumps({"at": "2026-10-07T00:00:00+00:00", "reason": "label"}) + "\n"
    )
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_STORE", str(tmp_path / "store.sqlite"))
    monkeypatch.setattr(module, "_read_closures", lambda settings: _closures("2026-09-24"))
    out = tmp_path / "out.txt"
    assert module.main(["--out", str(out)]) == 0
    written = out.read_text()
    assert "refusals, label: 1" in written
    assert "runs: 1" in written
    assert not PATTERN.search(written)
