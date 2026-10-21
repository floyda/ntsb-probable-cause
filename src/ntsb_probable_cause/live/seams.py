"""The three seams the morning run touches the outside world through (spec section 5).

Each has a local version in ``live.local``; the deployed one lives in ``apps/live``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ntsb_probable_cause.live.records import Backfill, ClosureRecord
from ntsb_probable_cause.live.state import NightState
from ntsb_probable_cause.store import Store


class StoreSource(Protocol):
    """Where the recorder's store comes from."""

    def open(self) -> Store:
        """Return a read-only copy of the store."""
        ...

    def discard(self) -> None:
        """Delete the working copy."""
        ...


@dataclass(frozen=True)
class MonthSpend:
    """The live key's spend this calendar month and the limit it is held to (decision 0170)."""

    used_usd: float
    limit_usd: float


class SpendCounter(Protocol):
    """What the live runs have cost."""

    def month(self, now: datetime) -> MonthSpend:
        """This calendar month's live spend and the limit it is held to.

        Raises:
            LiveRefusal: kind ``"key-unreachable"`` when the spend or limit cannot be read.
        """
        ...


class ResultSink(Protocol):
    """Where live results are read back from and written to."""

    def done_case_ids(self) -> frozenset[str]:
        """Case ids coded or not coded in any live run."""
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

    def night_state(self) -> NightState:
        """The state the last night left; an empty one when there is none."""
        ...

    def write_night_state(self, state: NightState) -> None:
        """Replace the carried state."""
        ...
