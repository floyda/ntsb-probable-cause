"""The coding memory's lesson format (decision 0201). Offline; made-up lessons."""

import pytest
from pydantic import ValidationError

from ntsb_probable_cause.memory import lessons as ls
from ntsb_probable_cause.scoring.codes import load_tables

TABLES = load_tables()
# Real codes: phase 550 (Landing) and event 240 (Loss of control in flight) compose to 550240;
# phase 500 (Approach) composes with the same event; 010100 is a finding category.
FIRST = "550240"
OTHER_FIRST = "500240"
CATEGORY = "010100"


def _lesson(**changes: object) -> ls.Lesson:
    base: dict[str, object] = {
        "lesson_id": "L001",
        "kind": "convention",
        "statement": "when the pilot stalls on approach, the NTSB codes loss of control first",
        "scope": "stall or spin during approach or landing",
        "predicts": ls.Prediction(first_occurrence=(FIRST,)),
        "written_in": 2009,
    }
    base.update(changes)
    return ls.Lesson.model_validate(base)


def test_the_chosen_codes_compose_in_the_real_tables() -> None:
    assert TABLES.compose_occurrence(FIRST[:3], FIRST[3:]) == FIRST
    assert TABLES.compose_occurrence(OTHER_FIRST[:3], OTHER_FIRST[3:]) == OTHER_FIRST
    assert CATEGORY in TABLES.categories


def test_a_convention_predicts_at_most_one_first_code() -> None:
    with pytest.raises(ValidationError):
        _lesson(predicts=ls.Prediction(first_occurrence=(FIRST, OTHER_FIRST)))


def test_a_split_predicts_two_or_more_first_codes() -> None:
    with pytest.raises(ValidationError):
        _lesson(kind="split", predicts=ls.Prediction(first_occurrence=(FIRST,)))
    _lesson(kind="split", predicts=ls.Prediction(first_occurrence=(FIRST, OTHER_FIRST)))


def test_an_evidence_lesson_names_a_finding_category() -> None:
    with pytest.raises(ValidationError):
        _lesson(kind="evidence", predicts=ls.Prediction())
    _lesson(kind="evidence", predicts=ls.Prediction(finding_categories=(CATEGORY,)))


def test_a_lesson_must_predict_something() -> None:
    with pytest.raises(ValidationError):
        _lesson(predicts=ls.Prediction())


def test_tokens_are_characters_over_four_rounded_up() -> None:
    assert ls.estimated_tokens("") == 0
    assert ls.estimated_tokens("abcde") == 2


def test_the_rendered_lesson_carries_counted_numbers_and_labels() -> None:
    lesson = _lesson(support=ls.Support(applies=41, agrees=33, first_codes=((FIRST, 29),)))
    text = ls.render_lesson(lesson, TABLES)
    assert lesson.statement in text
    assert FIRST in text
    assert "applies to 41" in text
    assert "agrees in 33" in text
    assert "Landing" in text
    assert "Loss of control in flight" in text


def test_the_rendered_memory_holds_every_lesson_within_the_cap() -> None:
    memory = ls.Memory(name="pilot-2009", periods=(2009,), lessons=(_lesson(),))
    assert "L001" in ls.render_memory(memory, TABLES)
    assert memory.cap_tokens == ls.CAP_TOKENS


def test_the_apply_view_names_ids_statements_and_scopes_but_no_codes() -> None:
    memory = ls.Memory(name="pilot-2009", periods=(2009,), lessons=(_lesson(),))
    text = ls.render_for_apply(memory)
    assert "L001" in text
    assert "approach" in text
    assert FIRST not in text
