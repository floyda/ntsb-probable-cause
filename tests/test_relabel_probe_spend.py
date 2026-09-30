"""scripts/relabel_probe_spend.py: the one-shot relabel of the learning probe's rows (0131)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import relabel_probe_spend as rps

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.budget import (
    RELABEL_FILE,
    SPEND_FILE,
    SpendRecord,
    month_spent,
    write_spend,
)
from ntsb_probable_cause.scoring.records import read_jsonl

NOW = datetime(2026, 9, 30, tzinfo=UTC)
JOB = rps.JOBS[0]


def _row(job_id: str, cost: float, *, kind: str = "inventory", calls: int = 7) -> SpendRecord:
    return SpendRecord.model_validate(
        {
            "job_id": job_id,
            "kind": kind,
            "model": "openai/gpt-6-luna",
            "started": datetime(2026, 9, 29, 12, 21, tzinfo=UTC),
            "calls": calls,
            "cost_usd": cost,
            "commit_sha": "64b8cee",
            "dirty": False,
        }
    )


def _seed(
    runs_dir: Path, job_id: str, costs: tuple[float, ...], *, kind: str = "inventory"
) -> None:
    for cost in costs:
        write_spend(runs_dir, _row(job_id, cost, kind=kind))


def _seed_all(runs_dir: Path) -> None:
    for job_id, costs in zip(rps.JOBS, ((0.0692,), (0.3, 0.2542), (0.2861, 0.286)), strict=True):
        _seed(runs_dir, job_id, costs)


def _snapshot(runs_dir: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(runs_dir)): path.read_bytes()
        for path in sorted(runs_dir.rglob("*"))
        if path.is_file()
    }


def test_the_three_jobs_are_decision_0131s() -> None:
    assert rps.JOBS == (
        "s3-probe-20260929T122117-64b8cee",
        "s3-probe-20260929T123038-64b8cee",
        "s3-probe-20260929T130538-551c884",
    )


def test_relabel_keeps_the_original_rows_and_relabels_the_rest(tmp_path: Path) -> None:
    _seed(tmp_path, JOB, (0.3, 0.2542))
    original = (tmp_path / JOB / SPEND_FILE).read_text()

    rows, total = rps.relabel(tmp_path, JOB)

    assert rows == 2
    assert total == pytest.approx(0.5542)
    kept = tmp_path / JOB / RELABEL_FILE
    assert kept.read_text() == original  # as written at the time, byte for byte
    before = read_jsonl(kept, SpendRecord)
    after = read_jsonl(tmp_path / JOB / SPEND_FILE, SpendRecord)
    assert {row.kind for row in before} == {"inventory"}
    assert {row.kind for row in after} == {"probe"}
    # Every other field is unchanged, row for row.
    assert [row.model_dump(exclude={"kind"}) for row in after] == [
        row.model_dump(exclude={"kind"}) for row in before
    ]
    assert sum(row.cost_usd for row in after) == sum(row.cost_usd for row in before)
    assert not list((tmp_path / JOB).glob("*tmp*"))


def test_month_spent_is_unchanged_by_the_relabel_and_nothing_is_counted_twice(
    tmp_path: Path,
) -> None:
    _seed_all(tmp_path)
    before = month_spent(tmp_path, now=NOW)
    assert before == pytest.approx(0.0692 + 0.5542 + 0.5721)

    for job_id in rps.JOBS:
        rps.relabel(tmp_path, job_id)

    assert month_spent(tmp_path, now=NOW) == pytest.approx(before)
    assert len(list(tmp_path.glob(f"*/{RELABEL_FILE}"))) == 3


def test_a_second_relabel_refuses_and_changes_nothing(tmp_path: Path) -> None:
    _seed(tmp_path, JOB, (0.3,))
    rps.relabel(tmp_path, JOB)
    snapshot = _snapshot(tmp_path)
    with pytest.raises(ConfigurationError, match=JOB):
        rps.relabel(tmp_path, JOB)
    assert _snapshot(tmp_path) == snapshot


def test_a_row_that_is_not_inventory_refuses_and_changes_nothing(tmp_path: Path) -> None:
    _seed(tmp_path, JOB, (0.3,))
    write_spend(tmp_path, _row(JOB, 0.1, kind="transcription"))
    snapshot = _snapshot(tmp_path)
    with pytest.raises(ConfigurationError, match="inventory"):
        rps.relabel(tmp_path, JOB)
    assert _snapshot(tmp_path) == snapshot


def test_a_job_with_no_folder_or_no_spend_file_is_an_error_naming_the_job(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=JOB):
        rps.relabel(tmp_path, JOB)
    (tmp_path / JOB).mkdir()
    with pytest.raises(ConfigurationError, match=JOB):
        rps.relabel(tmp_path, JOB)
    assert _snapshot(tmp_path) == {}


def test_a_total_that_changes_is_refused_before_the_original_is_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rewrite is read back and its total checked before anything is renamed."""
    _seed(tmp_path, JOB, (0.3, 0.2))
    snapshot = _snapshot(tmp_path)

    def _short(path: Path, model: type[SpendRecord]) -> list[SpendRecord]:
        rows = read_jsonl(path, model)
        return rows[:-1] if path.name != SPEND_FILE else rows

    monkeypatch.setattr(rps, "read_jsonl", _short)
    with pytest.raises(ConfigurationError, match="total"):
        rps.relabel(tmp_path, JOB)
    assert _snapshot(tmp_path) == snapshot


def test_main_relabels_every_job_and_prints_one_line_each(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_all(tmp_path)
    assert rps.main(["--runs-dir", str(tmp_path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0] == f"relabelled {rps.JOBS[0]}: 1 rows, $0.0692"
    assert lines[1] == f"relabelled {rps.JOBS[1]}: 2 rows, $0.5542"
    assert lines[2] == f"relabelled {rps.JOBS[2]}: 2 rows, $0.5721"
    for job_id in rps.JOBS:
        rows = read_jsonl(tmp_path / job_id / SPEND_FILE, SpendRecord)
        assert {row.kind for row in rows} == {"probe"}


def test_a_dry_run_reports_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_all(tmp_path)
    snapshot = _snapshot(tmp_path)
    assert rps.main(["--runs-dir", str(tmp_path), "--dry-run"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f"would relabel {rps.JOBS[0]}: 1 rows, $0.0692",
        f"would relabel {rps.JOBS[1]}: 2 rows, $0.5542",
        f"would relabel {rps.JOBS[2]}: 2 rows, $0.5721",
    ]
    assert _snapshot(tmp_path) == snapshot


def test_main_checks_every_job_before_it_changes_any(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One job that cannot be relabelled leaves every job as it was."""
    _seed(tmp_path, rps.JOBS[0], (0.0692,))
    _seed(tmp_path, rps.JOBS[1], (0.5542,))
    _seed(tmp_path, rps.JOBS[2], (0.5721,), kind="transcription")
    snapshot = _snapshot(tmp_path)
    assert rps.main(["--runs-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert rps.JOBS[2] in captured.err
    assert captured.out == ""
    assert _snapshot(tmp_path) == snapshot


def test_main_refuses_a_missing_job_folder_naming_the_job(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(tmp_path, rps.JOBS[0], (0.0692,))
    snapshot = _snapshot(tmp_path)
    assert rps.main(["--runs-dir", str(tmp_path), "--dry-run"]) == 1
    assert rps.JOBS[1] in capsys.readouterr().err
    assert _snapshot(tmp_path) == snapshot


def test_main_defaults_to_the_settings_runs_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    _seed_all(tmp_path)
    assert rps.main(["--dry-run"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 3
