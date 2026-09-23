"""Tests for scripts/change_feed_probe.py (Task 11; fix round 1 adds format signatures and
the confirmed-key counts, IMPORTANT 8/CRITICAL 1)."""

from collections import Counter

from scripts.change_feed_probe import feed_timestamp_signatures, format_signature, report, shape_of


def test_shape_of_records_sorted_type_names_per_key() -> None:
    rows: list[dict[str, object]] = [
        {"mkey": 1, "mode": "Aviation", "eventDate": "2026-01-01", "stepId": None},
        {"mkey": 2, "mode": "Railroad", "eventDate": None, "stepId": "S1"},
    ]
    shape = shape_of(rows)
    assert shape["mkey"] == ["int"]
    assert shape["mode"] == ["str"]
    assert shape["eventDate"] == ["NoneType", "str"]
    assert shape["stepId"] == ["NoneType", "str"]


def test_shape_of_handles_mixed_int_and_none() -> None:
    rows: list[dict[str, object]] = [{"stepNumber": 3}, {"stepNumber": None}, {"stepNumber": 7}]
    assert shape_of(rows) == {"stepNumber": ["NoneType", "int"]}


def test_shape_of_never_holds_a_value_only_key_names_and_types() -> None:
    """No value from a row -- only key names and Python type names -- ever appears in the shape."""
    rows: list[dict[str, object]] = [{"ntsbNumber": "DCA26FA001MKEY999999"}]
    shape = shape_of(rows)
    assert shape == {"ntsbNumber": ["str"]}
    assert "DCA26FA001MKEY999999" not in str(shape)


def test_shape_of_empty_rows_gives_empty_shape() -> None:
    assert shape_of([]) == {}


def test_format_signature_masks_every_digit() -> None:
    assert format_signature("2026-09-22T14:03:00.123") == "dddd-dd-ddTdd:dd:dd.ddd"
    assert format_signature("2026-09-22T14:03:00Z") == "dddd-dd-ddTdd:dd:ddZ"
    assert format_signature("no digits here") == "no digits here"


def test_feed_timestamp_signatures_deduplicates_and_ignores_non_string() -> None:
    rows: list[dict[str, object]] = [
        {"lastChangeDateTimeUtc": "2026-01-01T00:00:00"},
        {"lastChangeDateTimeUtc": "2026-09-22T14:03:00"},  # same signature, deduplicated
        {"lastChangeDateTimeUtc": None},  # ignored: not a string
        {},  # ignored: key missing
    ]
    assert feed_timestamp_signatures(rows) == ["dddd-dd-ddTdd:dd:dd"]


def test_feed_timestamp_signatures_never_holds_a_value() -> None:
    rows: list[dict[str, object]] = [{"lastChangeDateTimeUtc": "2026-01-01T00:00:00"}]
    signatures = feed_timestamp_signatures(rows)
    assert "2026-01-01T00:00:00" not in signatures
    assert signatures == ["dddd-dd-ddTdd:dd:dd"]


def test_report_prints_counts_types_and_signatures_only() -> None:
    shape = {"mkey": ["int"], "mode": ["str"]}
    text = report(
        shape=shape,
        mode_counts=Counter({"Aviation": 3, "Railroad": 1}),
        case_closed_counts=Counter({"True": 2, "False": 2}),
        step_id_counts=Counter({"S1": 4}),
        timestamp_signatures=["dddd-dd-ddTdd:dd:dd"],
        row_count=4,
        fixture_written=True,
    )
    assert "row count: 4" in text
    assert "keys: 2" in text
    assert "mkey: int" in text
    assert "mode: str" in text
    # mode/caseClosed/stepId counts are category names, not case data (decision 0024).
    assert "Aviation: 3" in text
    assert "True: 2" in text
    assert "S1: 4" in text
    assert "dddd-dd-ddTdd:dd:dd" in text
    assert "fixture written: True" in text


def test_report_with_no_rows_states_no_data_and_refused_fixture() -> None:
    text = report(
        shape={},
        mode_counts=Counter(),
        case_closed_counts=Counter(),
        step_id_counts=Counter(),
        timestamp_signatures=[],
        row_count=0,
        fixture_written=False,
    )
    assert "row count: 0" in text
    assert "mode counts:\n  no data" in text
    assert "caseClosed counts:\n  no data" in text
    assert "stepId counts:\n  no data" in text
    assert "fixture written: False (refused -- the response held no rows)" in text
