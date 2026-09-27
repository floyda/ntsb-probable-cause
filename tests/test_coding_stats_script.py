"""scripts/coding_stats.py: the pool, and the contamination guard (decision 0094)."""

import pytest
from scripts import coding_stats as cs

from ntsb_probable_cause.errors import LeakageError

Row = tuple[str, str, str, str, dict[str, object]]


def _row(  # noqa: PLR0913, PLR0917 -- one row of the fixture table, one argument per column
    case: str, date: str, split: str, klass: str, codes: tuple[str, ...], group: str
) -> Row:
    events: list[dict[str, object]] = [
        {
            "eventCode": code,
            "isDefiningEvent": i == 0,
            "sequenceNumber": i + 1,
            "cicttPhaseSOEGroup": group,
        }
        for i, code in enumerate(codes)
    ]
    return case, date, split, klass, {"aircrafts": [{"events": events}]}


ROWS = [
    _row("POOL1", "2011-05-01", "dev", "C", ("552300",), "Landing"),
    _row("POOL2", "2016-05-01", "dev", "F", ("452240", "452241"), "Maneuvering"),
    _row("DEV400", "2012-01-01", "dev", "C", ("552300",), "Landing"),
    _row("OTHERCLASS", "2012-01-01", "dev", "I", ("552300",), "Landing"),
    _row("HELD", "2021-01-01", "heldout", "C", ("552300",), "Landing"),
    _row("OPEN", "2025-01-01", "open", "C", ("552300",), "Landing"),
]


def test_pool_keeps_dev_classes_c_f_l_outside_the_samples() -> None:
    cases, ids = cs.pool_cases(ROWS, excluded=frozenset({"DEV400"}))
    assert ids == ["POOL1", "POOL2"]
    assert [c.sequence for c in cases] == [("552300",), ("452240", "452241")]
    assert cases[1].group == "Maneuvering"


def test_check_pool_refuses_a_sample_case_or_a_non_development_case() -> None:
    cs.check_pool(["POOL1"], excluded=frozenset({"DEV400"}), splits={"POOL1": "dev"})
    with pytest.raises(LeakageError, match="DEV400"):
        cs.check_pool(["DEV400"], excluded=frozenset({"DEV400"}), splits={"DEV400": "dev"})
    with pytest.raises(LeakageError, match="HELD"):
        cs.check_pool(["HELD"], excluded=frozenset(), splits={"HELD": "heldout"})


def test_report_prints_counts_and_both_halves_without_case_numbers() -> None:
    cases, _ids = cs.pool_cases(ROWS, excluded=frozenset({"DEV400"}))
    stats = cs.build(cases, built_from="test")
    text = cs.report(stats)
    assert "2009-2014: 1 cases; 2015-2019: 1 cases" in text
    assert "POOL" not in text
