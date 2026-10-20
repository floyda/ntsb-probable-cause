"""What a live night carries to the next: counted fetch failures and settled cases (decision 0175).

A case whose record or docket fetch fails is not seen, so it returns to the queue. A failure
counts against the case only on a night when other cases fetched; a night when every fetch
failed is an outage and counts against none. After ``ALERT_AT`` counted failures an alert kind is
returned; after ``FINAL_AT`` the case is settled as unreachable and is not queued again.

This module holds counts and the facts of a closure (its key and two dates), never a case's text.
The case ids that key its dictionaries stay in the sink; only alert kinds leave the morning
(decision 0024).
"""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from datetime import date
from typing import Final, Literal

from pydantic import BaseModel

from ntsb_probable_cause.live.queue import QueuedCase

ALERT_AT: Final = 3  # decision 0175
FINAL_AT: Final = 7


class Closed(BaseModel, frozen=True):
    """A closure's facts, kept for a case settled unreachable."""

    mkey: int
    event_date: date
    closed_on: date


class NightState(BaseModel, frozen=True):
    """Carried from night to night: counted fetch failures and the cases settled unreachable."""

    format: Literal["live-state/1"] = "live-state/1"
    failures: dict[str, int] = {}  # case id -> counted failed nights
    unreachable: dict[str, Closed] = {}  # case id -> its closure facts


def after_fetches(
    state: NightState, take: Sequence[QueuedCase], failed: AbstractSet[str], fetched: int
) -> tuple[NightState, list[str]]:
    """Count tonight's failures and settle cases at ``FINAL_AT``; return the alerts' kinds.

    A failure counts only when ``fetched`` is above 0 (another case fetched); otherwise the night
    is an outage: nothing counts and the kinds are ``["outage"]``. A case reaching ``ALERT_AT``
    adds ``"unreachable-3"``; reaching ``FINAL_AT`` moves it to ``unreachable`` and adds
    ``"unreachable-final"``. A case that fetched is removed from ``failures``.

    Args:
        state: the state the night began with.
        take: the cases the night tried to fetch.
        failed: the ids among ``take`` whose fetch failed.
        fetched: how many cases fetched.

    Returns:
        The new state and the alert kinds, each at most once, in the order they arose.
    """
    if failed and fetched == 0:
        return state, ["outage"]
    failures = dict(state.failures)
    unreachable = dict(state.unreachable)
    kinds: list[str] = []
    for case in take:
        if case.case_id not in failed:
            failures.pop(case.case_id, None)
            continue
        count = failures.get(case.case_id, 0) + 1
        if count >= FINAL_AT:
            failures.pop(case.case_id, None)
            unreachable[case.case_id] = Closed(
                mkey=case.mkey, event_date=case.event_date, closed_on=case.closed_on
            )
            kind = "unreachable-final"
        else:
            failures[case.case_id] = count
            kind = "unreachable-3" if count == ALERT_AT else ""
        if kind and kind not in kinds:
            kinds.append(kind)
    return NightState(failures=failures, unreachable=unreachable), kinds
