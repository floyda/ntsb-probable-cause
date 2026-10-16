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


def test_counts_per_part_replace_the_single_agreement_count() -> None:
    # Decision 0209: a recounted lesson shows how often each part it predicts held.
    support = ls.Support(
        applies=41, agrees=20, first_codes=((FIRST, 29),), first_agrees=29, finding_agrees=25
    )
    text = ls.render_lesson(
        _lesson(
            kind="split",
            predicts=ls.Prediction(
                first_occurrence=(FIRST, OTHER_FIRST), finding_categories=(CATEGORY,)
            ),
            support=support,
        ),
        TABLES,
    )
    assert "applies to 41 learning cases" in text
    assert "first code one of those predicted in 29" in text
    assert "at least one listed finding category flagged in 25" in text
    assert "agrees in" not in text


def test_a_part_the_lesson_does_not_predict_has_no_count_line() -> None:
    support = ls.Support(applies=10, agrees=7, first_agrees=7)
    text = ls.render_lesson(_lesson(support=support), TABLES)
    assert "first code one of those predicted in 7" in text
    assert "finding category" not in text.split("counted:")[1]


def test_the_pilots_snapshots_render_as_they_were_read() -> None:
    # A support with no per-part counts is a pilot snapshot's: its line is unchanged.
    support = ls.Support(applies=41, agrees=33, first_codes=((FIRST, 29),))
    line = ls.render_lesson(_lesson(support=support), TABLES).splitlines()[-1]
    assert (
        line
        == f"  counted: applies to 41 learning cases, agrees in 33; first codes seen: {FIRST} (29)"
    )


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
