"""The monthly budget as a reservation under a lock (decision 0045)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import BudgetError
from ntsb_probable_cause.scoring.budget import (
    RESERVATION_FILE,
    SpendRecord,
    budget_lock,
    month_spent,
    open_reservations,
    release,
    reserve,
    reserve_within_budget,
    settle,
    write_spend,
)
from ntsb_probable_cause.scoring.runner import refuse_over_budget

NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_reserve_writes_a_reservation_the_next_run_can_see(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert (tmp_path / "run-1" / RESERVATION_FILE).exists()
    assert open_reservations(tmp_path) == {"run-1": 20.0}


def test_settle_removes_the_reservation(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    settle(tmp_path, "run-1")
    assert open_reservations(tmp_path) == {}
    settle(tmp_path, "run-1")  # idempotent


def test_release_reports_whether_anything_was_open(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert release(tmp_path, "run-1") is True
    assert release(tmp_path, "run-1") is False


def test_second_run_is_refused_when_the_first_reservation_fills_the_budget(tmp_path: Path) -> None:
    """The 2026-09-17 incident: four runs each projected $20 against $25 and all passed."""
    with budget_lock(tmp_path):
        refuse_over_budget(20.0, month_spent(tmp_path, now=NOW), 25.0, reserved=0.0)
        reserve(tmp_path, "run-1", 20.0, now=NOW)
    with budget_lock(tmp_path):
        reserved = sum(open_reservations(tmp_path).values())
        with pytest.raises(BudgetError, match="reserved"):
            refuse_over_budget(20.0, month_spent(tmp_path, now=NOW), 25.0, reserved=reserved)


def test_budget_lock_is_reentrant_across_processes_by_file(tmp_path: Path) -> None:
    """The lock is a file under the runs directory, created on first use."""
    with budget_lock(tmp_path):
        assert (tmp_path / ".budget.lock").exists()


def test_month_spent_ignores_reservations(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert month_spent(tmp_path, now=NOW) == 0.0


def _spend(job_id: str, cost: float, started: datetime) -> SpendRecord:
    return SpendRecord(
        job_id=job_id,
        kind="transcription",
        model="google/gemini-3.1-flash-lite",
        started=started,
        calls=50,
        cost_usd=cost,
        commit_sha="abc1234",
        dirty=False,
    )


def test_month_spent_counts_preparation_spend_rows(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    write_spend(tmp_path, _spend("t1", 0.40, now))
    write_spend(tmp_path, _spend("t1", 0.35, now))
    write_spend(tmp_path, _spend("t0", 9.99, datetime(2026, 9, 30, tzinfo=UTC)))
    assert month_spent(tmp_path, now=now) == pytest.approx(0.75)


def test_reserve_within_budget_refuses_past_the_month(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    write_spend(tmp_path, _spend("t1", 30.0, now))
    with pytest.raises(BudgetError, match=r"exceeds the \$40.00 budget"):
        reserve_within_budget(tmp_path, "t2", 11.0, 40.0, now=now)
    reserve_within_budget(tmp_path, "t2", 9.0, 40.0, now=now)
    assert open_reservations(tmp_path) == {"t2": 9.0}
