"""The recount of decision 0209: rebuilding a run's apply answers and counting them again.

Offline: invented lessons and cases; the request key is a stand-in for the real one, built from
the memory text the apply step reads, as the real key is.
"""

import hashlib
import json
from pathlib import Path

import pytest
from scripts import memory_recount as mr

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, render_for_apply
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.memory.prompts import ApplyReply
from ntsb_probable_cause.scoring.codes import load_tables

TABLES = load_tables()
FIRST = "550240"
FLAGGED = TABLES.compose_finding("02063000", "44")


def _lesson(
    lid: str, statement: str = "the NTSB codes it so", cats: tuple[str, ...] = ()
) -> Lesson:
    return Lesson(
        lesson_id=lid,
        kind="convention",
        statement=statement,
        scope="a scope",
        predicts=Prediction(first_occurrence=(FIRST,), finding_categories=cats),
        written_in=2010,
    )


def _case(case_id: str) -> LearningCase:
    return LearningCase(case_id, 2010, f"cause of {case_id}", (FIRST,), (FLAGGED,))


def _key(memory: Memory, case: LearningCase) -> str:
    return hashlib.sha256(f"{render_for_apply(memory)}|{case.cause}".encode()).hexdigest()


CASES = [_case("A"), _case("B")]
# The draft held L1 to L4. L1 was revised, L3 dropped by a check before the final apply, and L4
# retired as unused after it: the final apply read L1 (revised), L2 and L4.
DRAFT = Memory(
    name="draft",
    periods=(2010,),
    lessons=(_lesson("L1"), _lesson("L2")),
    pushed_out=(_lesson("L3"), _lesson("L4")),
)
FINAL = Memory(
    name="pilot-x",
    periods=(2010,),
    lessons=(_lesson("L1", "the NTSB codes it so, revised", cats=("020630", "010100")),),
    pushed_out=(_lesson("L2"),),
)
SENT = Memory(
    name="draft",
    periods=(2010,),
    lessons=(FINAL.lessons[0], _lesson("L2"), _lesson("L4")),
)
SAVED = {
    _key(SENT, CASES[0]): ApplyReply(applies=["L1", "L4", "L9"]).model_dump_json(),
    _key(SENT, CASES[1]): ApplyReply(applies=["L1", "L2"]).model_dump_json(),
}


def test_the_rebuilt_text_is_the_one_the_final_apply_read() -> None:
    assert mr.final_apply_memory(DRAFT, FINAL, "L4") == SENT.model_copy(update={"name": "draft"})


def test_the_retired_lesson_is_found_and_unknown_ids_are_dropped() -> None:
    applies, extra = mr.rebuild_applies(DRAFT, FINAL, CASES, _key, SAVED)
    assert extra == "L4"
    assert applies == {"A": frozenset({"L1", "L4"}), "B": frozenset({"L1", "L2"})}


def test_a_rebuild_that_misses_any_saved_key_is_refused() -> None:
    partial = dict(list(SAVED.items())[:1])
    with pytest.raises(ConfigurationError, match="cannot be recovered"):
        mr.rebuild_applies(DRAFT, FINAL, CASES, _key, partial)


def test_the_recount_uses_the_corrected_rule_and_retires_unused_lessons() -> None:
    applies, _ = mr.rebuild_applies(DRAFT, FINAL, CASES, _key, SAVED)
    memory = mr.recount(FINAL, "pilot-x-recount", CASES, applies)
    by_id = {lesson.lesson_id: lesson for lesson in (*memory.lessons, *memory.pushed_out)}
    assert set(by_id) == {"L1", "L2"}  # L4 is not in the snapshot's lessons; none is unused
    s1 = by_id["L1"].support
    assert s1 is not None
    # Under the old rule L1 agreed with no case: 010100 is never flagged. Now both agree.
    assert (s1.applies, s1.agrees, s1.first_agrees, s1.finding_agrees) == (2, 2, 2, 2)
    assert memory.name == "pilot-x-recount"
    assert memory.cap_tokens == FINAL.cap_tokens


def test_a_recount_over_other_cases_than_the_finish_step_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="no finished finish step"):
        mr.refuse_other_cases(tmp_path, 2)
    (tmp_path / "finish.json").write_text(json.dumps({"applied_cases": 3}))
    with pytest.raises(ConfigurationError, match="applied to 3 cases"):
        mr.refuse_other_cases(tmp_path, 2)
    mr.refuse_other_cases(tmp_path, 3)


def test_saved_answers_are_read_and_checked_against_the_snapshot(tmp_path: Path) -> None:
    stored = tmp_path / "applies.json"
    stored.write_text(json.dumps({"A": ["L1"], "B": ["L1", "L2"]}))
    applies, how = mr._answers(tmp_path, DRAFT, FINAL, CASES)
    assert applies == {"A": frozenset({"L1"}), "B": frozenset({"L1", "L2"})}
    assert how == "read from applies.json"
    stored.write_text(json.dumps({"A": ["L1"], "B": ["L7"]}))
    with pytest.raises(ConfigurationError, match="names lessons"):
        mr._answers(tmp_path, DRAFT, FINAL, CASES)
    stored.write_text(json.dumps({"A": ["L1"]}))
    with pytest.raises(ConfigurationError, match="other cases"):
        mr._answers(tmp_path, DRAFT, FINAL, CASES)
