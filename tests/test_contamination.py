import json
from datetime import date
from pathlib import Path

from tests.conftest import load_record_fixtures

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
    # dev_400_ids is the one development-split list among the eval id lists (spec §5.3); it
    # gets its own purity test below rather than being asserted held-out here.
    offenders = [
        case
        for name, cases in eval_ids.items()
        if name != "dev_400_ids"
        for case, day in cases.items()
        if _split(day) is not Split.HELDOUT
    ]
    assert offenders == []


def test_s1_samples_are_split_pure_and_disjoint(eval_ids: dict[str, dict[str, str]]) -> None:
    dev = eval_ids.get("dev_400_ids", {})
    held = eval_ids.get("heldout_400_ids", {})
    assert all(split_of(date.fromisoformat(d)) is Split.DEV for d in dev.values())
    assert all(split_of(date.fromisoformat(d)) is Split.HELDOUT for d in held.values())
    assert not set(dev) & set(held)
    fixture_ids = {r["ntsbNumber"] for r in load_record_fixtures()}
    assert not fixture_ids & (set(dev) | set(held))


def test_no_development_fixture_is_an_evaluation_case(
    record_fixtures: list[dict[str, object]], eval_ids: dict[str, dict[str, str]]
) -> None:
    fixture_ids = {str(r["ntsbNumber"]) for r in record_fixtures}
    assert all(not fixture_ids & cases.keys() for cases in eval_ids.values())


def test_case_number_year_would_misclassify_labelled_cases(
    eval_ids: dict[str, dict[str, str]],
) -> None:
    """Why splits never use the case number: its year is the federal fiscal year (M2: 16 of 70).

    Scoped to the spike's original 70 labelled cases (``decidability_ids``, ``leakage_ids``):
    the count is M2's own measurement of that fixed set, not of every S1 sample added since.
    """
    original = ("decidability_ids", "leakage_ids")
    cases = {case: day for name in original for case, day in eval_ids.get(name, {}).items()}
    mismatched = [c for c, day in cases.items() if 2000 + int(c[3:5]) != int(day[:4])]
    assert len(mismatched) == 16
