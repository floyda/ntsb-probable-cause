"""The lookup's reach reading (decision 0210). Offline; invented answers and lessons."""

from scripts import memory_lookup_reach as rch

from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

TABLES = load_tables()


def _answer(phase: str, event: str) -> Hypothesis:
    return Hypothesis.model_validate(
        {
            "evidence_narrative": "x",
            "occurrence": [{"phase": phase, "event": event, "probability": 0.9}],
            "findings": [{"category6": "020630", "modifier": "44", "probability": 0.5}],
            "probable_cause": "x",
            "lay_explanation": "x",
            "confidence": 0.5,
            "abstain": False,
            "evidence_used": [],
        }
    )


def _lesson(lid: str, first: str, applies: int) -> Lesson:
    return Lesson(
        lesson_id=lid,
        kind="convention",
        statement="the NTSB codes it so",
        scope="a scope",
        predicts=Prediction(first_occurrence=(first,)),
        written_in=2010,
        support=Support(applies=applies, agrees=applies // 2),
    )


def test_the_reach_counts_cases_lessons_and_first_code_misses() -> None:
    memory = Memory(
        name="m",
        periods=(2010,),
        lessons=(_lesson("L1", "550240", 30),),
        pushed_out=(_lesson("L2", "552230", 5),),  # below the floor
    )
    text = rch.report([_answer("550", "240"), _answer("552", "230")], memory, TABLES, "t")
    assert "the lookup may choose: 1" in text
    assert "with 1 to 4: 1; with none: 1" in text
    assert "distinct lessons used: 1" in text
    assert "predicts the answer's first code: 1; of them, given none: 0" in text
