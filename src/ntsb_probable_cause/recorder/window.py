"""The self-setting month window (spec S2.5 §5.1)."""

import logging
from collections.abc import Callable, Iterable
from datetime import date

from ntsb_probable_cause.data.ingest import Month, months_between
from ntsb_probable_cause.store import Store

_log = logging.getLogger(__name__)

EMPTY_MONTHS_TO_STOP = 12


def _previous(month: Month) -> Month:
    """The month preceding this one."""
    if month.month == 1:
        return Month(month.year - 1, 12)
    return Month(month.year, month.month - 1)


def month_window(store: Store, *, today: date) -> list[Month] | None:
    """The window of months to fetch: from earliest watched case's month to today's month.

    Returns None if no watched case exists (caller must use first_run_window).
    """
    earliest = store.earliest_watched_event_month(today=today.isoformat())
    if earliest is None:
        return None

    today_month = Month(today.year, today.month)
    return months_between(earliest, today_month.label)


def first_run_window(
    fetch_month: Callable[[Month], Iterable[dict[str, object]]],
    *,
    today: date,
    is_watched: Callable[[dict[str, object]], bool],
) -> list[Month]:
    """Walk backwards until 12 consecutive empty months are found.

    Counts consecutive months where no watched record appears, stops when count reaches 12,
    and returns the list oldest-first (including the 12 empty months).
    """
    months: list[Month] = []
    current = Month(today.year, today.month)
    empty_count = 0

    while empty_count < EMPTY_MONTHS_TO_STOP:
        months.append(current)
        records = list(fetch_month(current))
        has_watched = any(is_watched(r) for r in records)

        if has_watched:
            _log.info("Month %s: contains watched record", current.label)
            empty_count = 0
        else:
            _log.info("Month %s: no watched record", current.label)
            empty_count += 1

        current = _previous(current)

    # Return oldest-first (reverse the newest-first list)
    return list(reversed(months))
