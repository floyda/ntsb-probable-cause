"""The learner's prompts and the coding test's system text (decisions 0200-0204). Offline."""

from ntsb_probable_cause.memory import prompts
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring.codes import load_tables

TABLES = load_tables()
CASE = LearningCase(
    "ERA09LA123",
    2009,
    "The pilot's failure to maintain directional control.",
    ("552230", "552470"),
    (),
)


def test_a_rendered_case_carries_codes_with_labels_and_no_case_number() -> None:
    text = prompts.render_case(CASE, "K1", TABLES)
    assert "552230" in text
    assert TABLES.events["230"] in text
    assert "ERA09LA123" not in text


def test_the_apply_question_carries_only_the_cause() -> None:
    text = prompts.apply_user(CASE.cause)
    assert CASE.cause in text
    assert "552230" not in text
    assert "ERA09LA123" not in text


def test_the_propose_system_text_forbids_numbers_names_and_places() -> None:
    lowered = prompts.SYSTEM_PROPOSE.lower()
    assert "no digits" in lowered
    assert "names" in lowered
    assert "places" in lowered


def test_the_placeholders_are_filled_at_import() -> None:
    for text in (prompts.SYSTEM_PROPOSE, prompts.SYSTEM_REVISE):
        assert "{allowed}" not in text
        assert "{max_new}" not in text
    assert f"at most {prompts.MAX_NEW_PER_CALL} new" in prompts.SYSTEM_PROPOSE


def test_the_coding_system_adds_the_memory_only_when_given() -> None:
    lesson = Lesson(
        lesson_id="L001",
        kind="convention",
        statement="the NTSB codes it so",
        scope="a scope",
        predicts=Prediction(first_occurrence=("552230",)),
        written_in=2009,
    )
    guidance = ("r3-loc-stall", "r6-aircraft-control")
    without = prompts.coding_system(TABLES, guidance, None)
    with_memory = prompts.coding_system(
        TABLES, guidance, Memory(name="m", periods=(2009,), lessons=(lesson,))
    )
    assert prompts.MEMORY_HEADING not in without
    assert with_memory.startswith(without)
    assert prompts.MEMORY_HEADING in with_memory
    assert without.startswith(prompts.CODING_PREFACE)


def test_the_learner_prompts_state_a_codes_shape() -> None:
    # Plan Deviations, 2026-10-16: without this the first 2009 propose run wrote finding codes
    # for categories and copied labels into the code fields.
    for system in (prompts.SYSTEM_PROPOSE, prompts.SYSTEM_REVISE):
        assert "first six digits" in system
        assert "no labels" in system
