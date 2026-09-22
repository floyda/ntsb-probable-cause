"""The self-setting month window (spec S2.5, Task 6)."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from ntsb_probable_cause.data.ingest import Month
from ntsb_probable_cause.recorder.window import first_run_window, month_window
from ntsb_probable_cause.store import CaseRow, Store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = Store(tmp_path / "r.sqlite")
    opened.migrate()
    yield opened
    opened.close()


def _case(mkey: int, event_date: str, status: str) -> CaseRow:
    """Helper to build a test case."""
    return CaseRow(
        mkey=mkey,
        ntsb_number=f"TST{mkey:05d}",
        event_date=event_date,
        regulation="091",
        status=status,
        first_seen_run=1,
        last_seen_run=1,
        last_case_run=1,
        last_docket_run=None,
        watch_until=None,
    )


def test_window_starts_at_earliest_watched_case(store: Store) -> None:
    store.upsert_case(_case(1, "2022-03-15", "Ongoing"))
    store.upsert_case(_case(2, "2026-08-01", "Ongoing"))
    months = month_window(store, today=date(2026, 9, 22))
    assert months is not None
    assert months[0].label == "2022-03"
    assert months[-1].label == "2026-09"


def test_window_is_none_on_an_empty_store(store: Store) -> None:
    assert month_window(store, today=date(2026, 9, 22)) is None


def test_first_run_walks_back_until_twelve_empty_months() -> None:
    watched_months = {"2026-09", "2026-05", "2025-11"}

    def fetch(month: Month) -> list[dict[str, object]]:
        return [{"m": month.label}] if month.label in watched_months else []

    months = first_run_window(fetch, today=date(2026, 9, 22), is_watched=lambda _r: True)
    # 2025-11 minus twelve empty months = 2024-11
    assert months[0].label == "2024-11"
    assert months[-1].label == "2026-09"


def test_edge_case_current_month_watched_with_12_empty_after() -> None:
    """When current month itself holds a watched record and 12 empty months follow."""
    watched_months = {"2026-09"}

    def fetch(month: Month) -> list[dict[str, object]]:
        return [{"m": month.label}] if month.label in watched_months else []

    months = first_run_window(fetch, today=date(2026, 9, 22), is_watched=lambda _r: True)
    # Should walk back 12 empty months from 2026-09 and include the current month
    assert months[0].label == "2025-09"
    assert months[-1].label == "2026-09"
