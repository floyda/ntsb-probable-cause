"""Tests for the night state (S4 Task 7, decision 0175): ``live/state.py``."""

from datetime import date

from ntsb_probable_cause.live.queue import QueuedCase
from ntsb_probable_cause.live.state import ALERT_AT, FINAL_AT, NightState, after_fetches


def _case(n: int) -> QueuedCase:
    return QueuedCase(
        mkey=1000 + n,
        case_id=f"XXX26LA{n:03d}",
        event_date=date(2026, 9, 1),
        closed_on=date(2026, 10, 5),
        closure_run=n,
    )


TAKE = [_case(1), _case(2), _case(3)]
BAD = "XXX26LA001"


def test_the_numbers_are_decision_0175s() -> None:
    assert (ALERT_AT, FINAL_AT) == (3, 7)


def test_a_failure_with_other_cases_fetched_is_counted_without_an_alert() -> None:
    state, kinds = after_fetches(NightState(), TAKE, {BAD}, fetched=2)
    assert state.failures == {BAD: 1}
    assert kinds == []


def test_the_third_counted_failure_alerts_once() -> None:
    state = NightState()
    seen: list[list[str]] = []
    for _ in range(4):
        state, kinds = after_fetches(state, TAKE, {BAD}, fetched=2)
        seen.append(kinds)
    assert seen == [[], [], ["unreachable-3"], []]
    assert state.failures == {BAD: 4}


def test_the_seventh_settles_the_case_as_unreachable() -> None:
    state = NightState(failures={BAD: FINAL_AT - 1})
    state, kinds = after_fetches(state, TAKE, {BAD}, fetched=2)
    assert kinds == ["unreachable-final"]
    assert BAD not in state.failures
    closed = state.unreachable[BAD]
    assert (closed.mkey, closed.event_date, closed.closed_on) == (
        1001,
        date(2026, 9, 1),
        date(2026, 10, 5),
    )


def test_a_night_when_every_fetch_failed_is_an_outage_and_counts_nothing() -> None:
    before = NightState(failures={BAD: 2})
    state, kinds = after_fetches(before, TAKE, {c.case_id for c in TAKE}, fetched=0)
    assert kinds == ["outage"]
    assert state == before


def test_a_case_that_fetched_is_dropped_from_the_counts() -> None:
    before = NightState(failures={BAD: 2, "XXX26LA002": 1})
    state, kinds = after_fetches(before, TAKE, {"XXX26LA002"}, fetched=2)
    assert state.failures == {"XXX26LA002": 2}
    assert kinds == []


def test_an_empty_night_changes_nothing() -> None:
    before = NightState(failures={BAD: 2})
    assert after_fetches(before, [], set(), fetched=0) == (before, [])


def test_two_cases_reaching_a_count_together_raise_one_kind() -> None:
    before = NightState(failures={BAD: 2, "XXX26LA002": 2})
    _, kinds = after_fetches(before, TAKE, {BAD, "XXX26LA002"}, fetched=1)
    assert kinds == ["unreachable-3"]
