"""Tests for scripts/change_feed_probe.py (Task 11)."""

from collections import Counter

from scripts.change_feed_probe import report, shape_of


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


def test_report_prints_counts_and_types_only() -> None:
    shape = {"mkey": ["int"], "mode": ["str"]}
    text = report(
        shape=shape,
        mode_counts=Counter({"Aviation": 3, "Railroad": 1}),
        status_counts=Counter({"Ongoing": 2}),
        row_count=4,
    )
    assert "row count: 4" in text
    assert "keys: 2" in text
    assert "mkey: int" in text
    assert "mode: str" in text
    # mode/status counts are category names, not case data (decision 0024) -- fine to print.
    assert "Aviation: 3" in text
    assert "Ongoing: 2" in text


def test_report_with_no_rows_states_no_data() -> None:
    text = report(shape={}, mode_counts=Counter(), status_counts=Counter(), row_count=0)
    assert "row count: 0" in text
    assert "mode counts:\n  no data" in text
    assert "completionStatus counts" in text
