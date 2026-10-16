"""The corrected count's reading (decision 0209). Offline; invented snapshots."""

import pytest
from scripts import memory_recount_report as rr

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support


def _lesson(lid: str, applies: int, agrees: int, first_agrees: int | None = None) -> Lesson:
    return Lesson(
        lesson_id=lid,
        kind="convention",
        statement="the NTSB codes it so",
        scope="a scope",
        predicts=Prediction(first_occurrence=("550240",), finding_categories=("020630", "010100")),
        written_in=2010,
        support=Support(applies=applies, agrees=agrees, first_agrees=first_agrees),
    )


OLD = Memory(
    name="old", periods=(2010,), lessons=(_lesson("L1", 20, 0),), pushed_out=(_lesson("L2", 4, 0),)
)
NEW = Memory(
    name="new",
    periods=(2010,),
    lessons=(_lesson("L1", 20, 12, 15),),
    pushed_out=(_lesson("L2", 4, 3, 3),),
)


def test_the_reading_compares_the_two_rules_on_well_used_lessons() -> None:
    text = rr.report(OLD, NEW)
    assert "lessons that apply to at least 10 learning cases: 1" in text
    assert "median fit, old rule (every listed category flagged): 0%" in text
    assert "median fit, corrected rule (one listed category enough): 60%" in text
    assert "median first-code fit, over the 1 that predict a first code: 75%" in text
    assert "old rule 1, corrected rule 0" in text
    assert "all 2 lessons: 2" in text


def test_snapshots_that_differ_beyond_the_counts_are_refused() -> None:
    other = NEW.model_copy(update={"pushed_out": (_lesson("L2", 5, 3),)})
    with pytest.raises(ConfigurationError, match="L2 differs"):
        rr.refuse_unpaired(OLD, other)
    with pytest.raises(ConfigurationError, match="different lessons"):
        rr.refuse_unpaired(OLD, NEW.model_copy(update={"pushed_out": ()}))
    rr.refuse_unpaired(OLD, NEW)
