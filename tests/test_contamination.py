import json
from datetime import date
from pathlib import Path

from ntsb_probable_cause.splits import Split, split_of


def _split(value: object) -> Split:
    return split_of(date.fromisoformat(str(value)[:10]))


def test_record_fixtures_are_development_split_by_their_own_event_date(
    record_fixtures: list[dict[str, object]],
) -> None:
    offenders = [
        r["ntsbNumber"] for r in record_fixtures if _split(r["eventDate"]) is not Split.DEV
    ]
    assert offenders == []


def test_api_fixture_records_are_development_split() -> None:
    payload = json.loads(Path("tests/fixtures/api/page.json").read_text())
    assert all(_split(r["eventDate"]) is Split.DEV for r in payload["data"])


def test_both_evaluation_lists_are_present(eval_ids: dict[str, dict[str, str]]) -> None:
    assert len(eval_ids["decidability_ids"]) == 40
    assert len(eval_ids["leakage_ids"]) == 30


def test_evaluation_cases_are_held_out_by_event_date(eval_ids: dict[str, dict[str, str]]) -> None:
    offenders = [
        case
        for cases in eval_ids.values()
        for case, day in cases.items()
        if _split(day) is not Split.HELDOUT
    ]
    assert offenders == []


def test_no_development_fixture_is_an_evaluation_case(
    record_fixtures: list[dict[str, object]], eval_ids: dict[str, dict[str, str]]
) -> None:
    fixture_ids = {str(r["ntsbNumber"]) for r in record_fixtures}
    assert all(not fixture_ids & cases.keys() for cases in eval_ids.values())


def test_case_number_year_would_misclassify_labelled_cases(
    eval_ids: dict[str, dict[str, str]],
) -> None:
    """Why splits never use the case number: its year is the federal fiscal year (M2: 16 of 70)."""
    cases = {case: day for listing in eval_ids.values() for case, day in listing.items()}
    mismatched = [c for c, day in cases.items() if 2000 + int(c[3:5]) != int(day[:4])]
    assert len(mismatched) == 16
