"""scripts/coding_stats.py: the pool, and the contamination guard (decision 0094)."""

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import coding_stats as cs

from ntsb_probable_cause.errors import LeakageError

_SCHEMA = pa.schema(
    [
        ("ntsb_number", pa.string()),
        ("event_date", pa.date32()),
        ("split", pa.string()),
        ("investigation_class", pa.string()),
        ("raw_json", pa.string()),
    ]
)

Row = tuple[str, str, str, str, dict[str, object]]


def _row(  # noqa: PLR0913, PLR0917 -- one row of the fixture table, one argument per column
    case: str,
    date: str,
    split: str,
    klass: str,
    codes: tuple[str, ...],
    group: str,
    findings: tuple[tuple[str, bool], ...] = (),
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
    rows: list[dict[str, object]] = [
        {"findingCode": code, "findingNumber": i + 1, "inProbableCause": cause}
        for i, (code, cause) in enumerate(findings)
    ]
    return case, date, split, klass, {"aircrafts": [{"events": events, "findings": rows}]}


ROWS = [
    _row("POOL1", "2011-05-01", "dev", "C", ("552300",), "Landing"),
    _row(
        "POOL2",
        "2016-05-01",
        "dev",
        "F",
        ("452240", "452241"),
        "Maneuvering",
        (("0206304044", True), ("0303404591", False)),
    ),
    _row("DEV400", "2012-01-01", "dev", "C", ("552300",), "Landing"),
    _row("OTHERCLASS", "2012-01-01", "dev", "I", ("552300",), "Landing"),
    _row("HELD", "2021-01-01", "heldout", "C", ("552300",), "Landing"),
    _row("OPEN", "2025-01-01", "open", "C", ("552300",), "Landing"),
]


def test_processed_rows_parses_raw_json_for_development_rows_only(tmp_path: Path) -> None:
    """Final review, Minor 5: ``pool_cases`` skips a held-out/open row before touching ``raw``
    at all, so ``processed_rows`` must not have parsed its ``raw_json`` either."""
    table = pa.table(
        {
            "ntsb_number": pa.array(["DEV1", "HELD1", "OPEN1"], type=pa.string()),
            "event_date": pa.array(
                [date(2012, 1, 1), date(2021, 1, 1), date(2025, 1, 1)], type=pa.date32()
            ),
            "split": pa.array(["dev", "heldout", "open"], type=pa.string()),
            "investigation_class": pa.array(["C", "C", "C"], type=pa.string()),
            "raw_json": pa.array(
                [json.dumps({"k": "dev"}), json.dumps({"k": "held"}), json.dumps({"k": "open"})],
                type=pa.string(),
            ),
        },
        schema=_SCHEMA,
    )
    processed = tmp_path / "processed"
    processed.mkdir()
    pq.write_table(table, processed / "cases.parquet")
    rows = {case: raw for case, _date, _split, _klass, raw in cs.processed_rows(processed)}
    assert rows["DEV1"] == {"k": "dev"}
    assert rows["HELD1"] == {}
    assert rows["OPEN1"] == {}


def test_pool_keeps_dev_classes_c_f_l_outside_the_samples() -> None:
    cases, ids = cs.pool_cases(ROWS, excluded=frozenset({"DEV400"}))
    assert ids == ["POOL1", "POOL2"]
    assert [c.sequence for c in cases] == [("552300",), ("452240", "452241")]
    assert cases[1].group == "Maneuvering"
    assert cases[1].findings == ("0206304044",)  # flagged in the probable cause only


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
    assert "## flagged findings by defining event" in text
    assert "- 240 Loss of control in flight: 1 cases" in text
    assert "0206304044" in text
