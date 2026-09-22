"""Evaluation splits and corpus filters. Method constants: change only with a decision record."""

from datetime import date
from enum import StrEnum

DEV_MAX_YEAR = 2019
HELDOUT_YEARS = range(2020, 2024)
OPEN_MIN_YEAR = 2024
MIN_EVENT_YEAR = 2009
COMPLETED_STATUS = "Completed"
ONGOING_STATUS = "Ongoing"
GA_REGULATION = "091"


class Split(StrEnum):
    """The three fixed splits, by event year."""

    DEV = "dev"
    HELDOUT = "heldout"
    OPEN = "open"


def split_of(event_date: date) -> Split:
    """Return the split for an event date. Never derive a split from a case number."""
    if event_date.year <= DEV_MAX_YEAR:
        return Split.DEV
    if event_date.year in HELDOUT_YEARS:
        return Split.HELDOUT
    return Split.OPEN
