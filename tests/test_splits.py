from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ntsb_probable_cause.splits import Split, split_of


@pytest.mark.parametrize(
    ("event_date", "expected"),
    [
        (date(2019, 12, 31), Split.DEV),
        (date(2020, 1, 1), Split.HELDOUT),
        (date(2023, 12, 31), Split.HELDOUT),
        (date(2024, 1, 1), Split.OPEN),
        (date(2009, 1, 1), Split.DEV),
    ],
)
def test_split_boundaries(event_date: date, expected: Split) -> None:
    assert split_of(event_date) is expected


def test_fiscal_year_case_is_split_by_event_date() -> None:
    # WPR24LA029 occurred on 2023-11-04: its number reads 2024, its split is held-out.
    assert split_of(date(2023, 11, 4)) is Split.HELDOUT


@given(st.dates(min_value=date(1990, 1, 1), max_value=date(2100, 12, 31)))
def test_every_date_has_exactly_the_split_of_its_year(event_date: date) -> None:
    result = split_of(event_date)
    if event_date.year <= 2019:
        assert result is Split.DEV
    elif event_date.year <= 2023:
        assert result is Split.HELDOUT
    else:
        assert result is Split.OPEN
