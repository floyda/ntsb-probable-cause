import hashlib
from datetime import date

from ntsb_probable_cause.live.queue import (
    DAILY_LIMIT,
    DECLARED_START,
    QueuedCase,
    backfill_digest,
    build_queue,
    closures_per_night,
    todays_take,
    waited_days,
)
from ntsb_probable_cause.store import Closure


def _closure(mkey: int, closed_on: str = "2026-09-24", run: int = 5) -> Closure:
    return Closure(
        mkey=mkey,
        ntsb_number=f"ERA26LA{mkey:03d}",
        event_date="2026-08-01",
        closure_run=run,
        closed_on=closed_on,
        closed_as="Completed",
    )


def test_constants() -> None:
    assert date(2026, 9, 23) == DECLARED_START
    assert DAILY_LIMIT == 10


def test_build_queue_drops_early_and_done_and_orders_by_run_then_mkey() -> None:
    closures = [
        _closure(9, run=6),
        _closure(3, closed_on="2026-09-22", run=4),
        _closure(7, run=5),
        _closure(2, run=6),
        _closure(1, closed_on="2026-09-23", run=5),
    ]
    queue = build_queue(closures, done={"ERA26LA002"})
    assert [(q.mkey, q.closure_run) for q in queue] == [(1, 5), (7, 5), (9, 6)]
    assert queue[0] == QueuedCase(
        mkey=1,
        case_id="ERA26LA001",
        event_date=date(2026, 8, 1),
        closed_on=date(2026, 9, 23),
        closure_run=5,
    )


def test_build_queue_is_independent_of_input_order() -> None:
    closures = [_closure(m) for m in (5, 1, 9, 3)]
    assert build_queue(closures, set()) == build_queue(closures[::-1], set())


def test_todays_take_forty_on_one_night() -> None:
    queue = build_queue([_closure(m) for m in range(40, 0, -1)], set())
    assert [q.mkey for q in todays_take(queue, 0)] == list(range(1, 11))
    assert todays_take(queue, 10) == []
    assert todays_take(queue, 12) == []
    assert [q.mkey for q in todays_take(queue, 8)] == [1, 2]
    assert [q.mkey for q in todays_take(queue, 0, limit=3)] == [1, 2, 3]


def test_closures_per_night_counts_by_closed_on() -> None:
    counts = closures_per_night([_closure(1), _closure(2), _closure(3, closed_on="2026-09-25")])
    assert counts == {date(2026, 9, 24): 2, date(2026, 9, 25): 1}


def test_backfill_digest_is_order_free_and_sensitive() -> None:
    assert backfill_digest(["b", "a", "c"]) == backfill_digest(["c", "b", "a"])
    assert backfill_digest(["a", "b"]) == hashlib.sha256(b"a\nb").hexdigest()
    assert backfill_digest(["a", "b"]) != backfill_digest(["a", "x"])


def test_waited_days() -> None:
    case = build_queue([_closure(1)], set())[0]
    assert waited_days(case, date(2026, 9, 24)) == 0
    assert waited_days(case, date(2026, 9, 27)) == 3
