"""The per-case lookup of decision 0210. Offline; invented lessons with real codes."""

from ntsb_probable_cause.memory import lookup as lk
from ntsb_probable_cause.memory.lessons import Lesson, Prediction, Support

# Real codes: event 240 (loss of control in flight) in phases 550 (Landing) and 500 (Approach);
# event 230 in phase 552; finding categories 020630 and 010100.
LANDING_LOC, APPROACH_LOC, OTHER = "550240", "500240", "552230"


def _lesson(
    lid: str,
    first: tuple[str, ...] = (LANDING_LOC,),
    cats: tuple[str, ...] = (),
    applies: int = 20,
    agrees: int = 10,
) -> Lesson:
    kind = "split" if len(first) > 1 else ("evidence" if not first else "convention")
    return Lesson(
        lesson_id=lid,
        kind=kind,
        statement="the NTSB codes it so",
        scope="a scope",
        predicts=Prediction(first_occurrence=first, finding_categories=cats),
        written_in=2010,
        support=Support(applies=applies, agrees=agrees),
    )


def _ids(lessons: tuple[Lesson, ...]) -> list[str]:
    return [lesson.lesson_id for lesson in lessons]


def test_a_lesson_matches_on_a_first_code_or_a_finding_category() -> None:
    by_code = _lesson("L1")
    by_category = _lesson("L2", first=(), cats=("020630",))
    neither = _lesson("L3", first=(OTHER,))
    found = lk.lookup([neither, by_category, by_code], [LANDING_LOC], ["020630"])
    assert sorted(_ids(found)) == ["L1", "L2"]


def test_the_same_event_in_another_phase_matches_below_an_exact_code() -> None:
    other_phase = _lesson("L1", first=(APPROACH_LOC, "552240"))
    exact = _lesson("L2", first=(LANDING_LOC,), agrees=2)
    assert lk.match(other_phase, [LANDING_LOC], []) == lk.Match(exact=0, event=2)
    assert _ids(lk.lookup([other_phase, exact], [LANDING_LOC], [])) == ["L2", "L1"]


def test_more_exact_matches_rank_first_then_fit_then_support_then_id() -> None:
    two = _lesson("L9", cats=("020630",), agrees=1)
    fit_high = _lesson("L5", agrees=18)
    fit_low_big = _lesson("L4", applies=40, agrees=8)
    fit_low_small = _lesson("L3", applies=20, agrees=4)
    tie = _lesson("L2", applies=20, agrees=4)
    found = lk.lookup(
        [tie, fit_low_small, fit_low_big, fit_high, two], [LANDING_LOC], ["020630"], k=5
    )
    assert _ids(found) == ["L9", "L5", "L4", "L2", "L3"]


def test_at_most_k_lessons_and_none_below_the_support_floor() -> None:
    lessons = [_lesson(f"L{i}") for i in range(8)] + [_lesson("L99", applies=9, agrees=9)]
    found = lk.lookup(lessons, [LANDING_LOC], [], k=5, min_applies=10)
    assert len(found) == 5
    assert "L99" not in _ids(found)


def test_an_answer_that_matches_nothing_gets_no_lessons() -> None:
    assert lk.lookup([_lesson("L1")], [OTHER], ["010100"]) == ()


def test_the_registered_defaults() -> None:
    assert (lk.K, lk.MIN_APPLIES) == (5, 10)
