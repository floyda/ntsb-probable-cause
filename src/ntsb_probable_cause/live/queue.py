"""The queue of closed cases waiting to be coded (S3.3 spec section 3, decision 0157).

Pure: it takes ``Closure`` values and does no I/O.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date
from typing import Final

from ntsb_probable_cause.store import Closure

DECLARED_START: Final = date(2026, 9, 23)  # decision 0155
DAILY_LIMIT: Final = 50  # decision 0157, raised from 10 by 0167


@dataclass(frozen=True)
class QueuedCase:
    """One closed case waiting to be coded."""

    mkey: int
    case_id: str  # the NTSB number
    event_date: date
    closed_on: date
    closure_run: int


def build_queue(closures: Sequence[Closure], done: AbstractSet[str]) -> list[QueuedCase]:
    """Return the cases to code, oldest closure first.

    Args:
        closures: Every case that really closed.
        done: Case ids already coded (or otherwise settled).

    Returns:
        Cases closed on or after ``DECLARED_START`` and not in ``done``, ordered by
        ``(closure_run, mkey)`` whatever the input order.
    """
    queue = [
        QueuedCase(
            mkey=c.mkey,
            case_id=c.ntsb_number,
            event_date=date.fromisoformat(c.event_date),
            closed_on=date.fromisoformat(c.closed_on),
            closure_run=c.closure_run,
        )
        for c in closures
        if date.fromisoformat(c.closed_on) >= DECLARED_START and c.ntsb_number not in done
    ]
    return sorted(queue, key=lambda q: (q.closure_run, q.mkey))


def todays_take(
    queue: Sequence[QueuedCase], coded_today: int, limit: int = DAILY_LIMIT
) -> list[QueuedCase]:
    """Return the head of the queue that still fits under today's limit."""
    return list(queue[: max(0, limit - coded_today)])


def closures_per_night(closures: Sequence[Closure]) -> dict[date, int]:
    """Count closures by the night (UTC date) they closed on."""
    return dict(Counter(date.fromisoformat(c.closed_on) for c in closures))


def backfill_digest(case_ids: Sequence[str]) -> str:
    """Return the SHA-256 of the sorted ids joined by newlines (order-free)."""
    return hashlib.sha256("\n".join(sorted(case_ids)).encode()).hexdigest()


def waited_days(case: QueuedCase, coded_on: date) -> int:
    """Return whole days between a case's closure and the day it was coded."""
    return (coded_on - case.closed_on).days
