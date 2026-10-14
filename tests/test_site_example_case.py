"""Question 1's case on the Path page (S5 step 4b, Task 1): one fixture, as published."""

import json
from pathlib import Path

import pytest
from scripts import site_example_case as sec

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.records.split import split_record

_REPO = Path(__file__).resolve().parents[1]
_FIXTURES = _REPO / "tests/fixtures/records"
_CHOSEN = "ANC09CA020"  # Andy, 2026-10-14


def _raw(case: str) -> dict[str, object]:
    raw: dict[str, object] = json.loads((_FIXTURES / f"{case}.json").read_text())["record"]
    return raw


def test_the_cause_and_codes_are_the_fixtures_own() -> None:
    example = sec.build(_CHOSEN, _FIXTURES)
    _, _, verdict = split_record(_raw(_CHOSEN))
    assert example.cause == verdict.probable_cause
    assert [c.code for c in example.occurrence] == list(verdict.occurrence_codes)
    assert [f.code for f in example.findings] == list(verdict.finding_codes)
    assert {f.code for f in example.findings if f.in_cause} == set(verdict.finding_codes_in_cause)
    assert example.event_date == "2009-02-16"
    assert example.injury == "none"


def test_codes_carry_their_table_labels() -> None:
    example = sec.build(_CHOSEN, _FIXTURES)
    for code in example.occurrence:
        assert " / " in code.label, code
        assert not code.label[0].isdigit()
    for finding in example.findings:
        assert " - " in finding.label, finding


def test_a_fatal_case_is_refused() -> None:
    # Spec §7.4: a non-fatal case keeps the first example gentle.
    with pytest.raises(ConfigurationError, match="fatal"):
        sec.build("ANC10MA068", _FIXTURES)


def test_a_case_outside_the_development_split_is_refused(tmp_path: Path) -> None:
    record = json.loads((_FIXTURES / f"{_CHOSEN}.json").read_text())
    record["record"]["eventDate"] = "2021-02-16"
    (tmp_path / f"{_CHOSEN}.json").write_text(json.dumps(record))
    with pytest.raises(ConfigurationError, match="not a development case"):
        sec.build(_CHOSEN, tmp_path)


def test_the_names_check_flags_a_capitalised_word_inside_a_sentence() -> None:
    assert sec.unexpected_capitals("The pilot's failure. Contributing was the snow.") == []
    assert sec.unexpected_capitals("The NTSB found the pilot's error.") == []
    assert sec.unexpected_capitals("The pilot, Smith, lost control.") == ["Smith"]
    assert sec.unexpected_capitals("The pilot\u2019s error. Contributing was Jones.") == ["Jones"]


def test_the_chosen_cause_passes_the_names_check() -> None:
    example = sec.build(_CHOSEN, _FIXTURES)
    assert sec.unexpected_capitals(example.cause or "") == []


def test_the_committed_file_is_current() -> None:
    committed = json.loads((_REPO / "site/data/example-case.json").read_text())
    assert committed == json.loads(sec.build(_CHOSEN, _FIXTURES).model_dump_json())
