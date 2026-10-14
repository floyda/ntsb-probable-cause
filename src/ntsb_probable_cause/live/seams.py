"""The three seams the morning run touches the outside world through (spec section 5).

Each has a local version in ``live.local``; the deployed one lives in ``apps/live``.
"""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from ntsb_probable_cause.live.records import Backfill, ClosureRecord
from ntsb_probable_cause.store import Store


class StoreSource(Protocol):
    """Where the recorder's store comes from."""

    def open(self) -> Store:
        """Return a read-only copy of the store."""
        ...

    def discard(self) -> None:
        """Delete the working copy."""
        ...


class SpendCounter(Protocol):
    """What the live runs have cost."""

    def live_month_usd(self, now: datetime) -> float:
        """Spend of live runs started in the calendar month of ``now``."""
        ...


class ResultSink(Protocol):
    """Where live results are read back from and written to."""

    def done_case_ids(self) -> frozenset[str]:
        """Case ids coded or not coded in any live run."""
        ...

    def coded_on(self, day: date) -> int:
        """Cases in live runs started on that UTC day."""
        ...

    def unfinished_run(self) -> str | None:
        """A live run whose record is not finished, if any."""
        ...

    def backfill(self) -> Backfill | None:
        """The backfill record, if a live run holds one."""
        ...

    def write(
        self, run_id: str, records: Sequence[ClosureRecord], backfill: Backfill | None
    ) -> None:
        """Write the closures, then the backfill, then the manifest."""
        ...
