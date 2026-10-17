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
    assert lk.match(other_phase, [LANDING_LOC], []) == lk.Match(exact=0, first=0, event=1)
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


def test_a_long_list_of_categories_counts_once() -> None:
    # Decision 0209: categories are alternatives, so naming more of them earns no extra rank.
    many = _lesson("L1", first=(OTHER,), cats=("020630", "010100"), agrees=1)
    one = _lesson("L2", first=(OTHER,), cats=("020630",), agrees=15)
    assert lk.match(many, [LANDING_LOC], ["020630", "010100"]) == lk.Match(
        exact=1, first=0, event=0
    )
    assert _ids(lk.lookup([many, one], [LANDING_LOC], ["020630", "010100"])) == ["L2", "L1"]


def test_an_exact_first_code_and_an_event_do_not_add_up() -> None:
    both = _lesson("L1", first=(LANDING_LOC, APPROACH_LOC))
    assert lk.match(both, [LANDING_LOC], []) == lk.Match(exact=1, first=1, event=0)


def test_a_first_code_match_outranks_a_category_match_of_higher_fit() -> None:
    by_category = _lesson("L1", first=(OTHER,), cats=("020630",), agrees=19)
    by_first = _lesson("L2", agrees=2)
    assert _ids(lk.lookup([by_category, by_first], [LANDING_LOC], ["020630"])) == ["L2", "L1"]


def test_at_most_k_lessons_and_none_below_the_support_floor() -> None:
    lessons = [_lesson(f"L{i}") for i in range(8)] + [_lesson("L99", applies=9, agrees=9)]
    found = lk.lookup(lessons, [LANDING_LOC], [], k=5, min_applies=10)
    assert len(found) == 5
    assert "L99" not in _ids(found)


def test_an_answer_that_matches_nothing_gets_no_lessons() -> None:
    assert lk.lookup([_lesson("L1")], [OTHER], ["010100"]) == ()


def test_the_registered_defaults() -> None:
    assert (lk.K, lk.MIN_APPLIES) == (5, 10)


# by_fit (decision 0211): the apply step chose the lessons; the script ranks them. -------------


def test_by_fit_keeps_only_the_applied_lessons_ranked_by_fit_then_support_then_id() -> None:
    high = _lesson("L5", agrees=18)
    big = _lesson("L4", applies=40, agrees=8)
    small = _lesson("L3", applies=20, agrees=4)
    tie = _lesson("L2", applies=20, agrees=4)
    not_named = _lesson("L1", agrees=20)
    found = lk.by_fit([not_named, tie, small, big, high], {"L2", "L3", "L4", "L5"})
    assert _ids(found) == ["L5", "L4", "L2", "L3"]


def test_by_fit_reads_no_code_and_keeps_k_above_the_floor() -> None:
    lessons = [_lesson(f"L{i}", first=(OTHER,), agrees=i) for i in range(1, 8)]
    thin = _lesson("L9", applies=9, agrees=9)
    found = lk.by_fit([*lessons, thin], {x.lesson_id for x in [*lessons, thin]}, k=5)
    assert _ids(found) == ["L7", "L6", "L5", "L4", "L3"]
    assert lk.by_fit([thin], {"L9"}) == ()
    assert lk.by_fit(lessons, set()) == ()


# Decision 0213: the embedding lookup. -------------------------------------------------------


def test_by_similarity_keeps_the_floor_and_orders_by_cosine() -> None:
    lessons = [
        _lesson("L1", applies=20, agrees=10),
        _lesson("L2", applies=9, agrees=9),
        _lesson("L3", applies=30, agrees=3),
    ]
    vectors = {"L1": [1.0, 0.0], "L2": [1.0, 0.0], "L3": [0.6, 0.8]}
    assert _ids(lk.by_similarity(lessons, vectors, [1.0, 0.0])) == ["L1", "L3"]


def test_by_similarity_breaks_ties_by_fit_then_applies_then_id() -> None:
    lessons = [
        _lesson("L2", applies=10, agrees=5),
        _lesson("L1", applies=10, agrees=5),
        _lesson("L4", applies=20, agrees=10),
        _lesson("L3", applies=10, agrees=9),
    ]
    vectors = {lesson.lesson_id: [2.0, 0.0] for lesson in lessons}
    assert _ids(lk.by_similarity(lessons, vectors, [1.0, 0.0])) == ["L3", "L4", "L1", "L2"]


def test_by_similarity_skips_lessons_without_a_vector_and_caps_at_k() -> None:
    lessons = [_lesson(f"L{i}") for i in range(1, 8)]
    vectors = {f"L{i}": [1.0, float(i)] for i in range(1, 7)}
    found = lk.by_similarity(lessons, vectors, [0.0, 1.0])
    assert _ids(found) == ["L6", "L5", "L4", "L3", "L2"]
    assert _ids(lk.by_similarity(lessons, vectors, [0.0, 1.0], k=2)) == ["L6", "L5"]


def test_by_similarity_reads_no_code() -> None:
    by_code = _lesson("L1", first=(LANDING_LOC,))
    other = _lesson("L2", first=(OTHER,))
    vectors = {"L1": [0.0, 1.0], "L2": [1.0, 0.0]}
    assert _ids(lk.by_similarity([by_code, other], vectors, [1.0, 0.1])) == ["L2", "L1"]


def test_cosine_is_direction_only_and_zero_for_a_zero_vector() -> None:
    assert lk.cosine([2.0, 0.0], [5.0, 0.0]) == 1.0
    assert lk.cosine([1.0, 0.0], [0.0, 3.0]) == 0.0
    assert lk.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_lesson_text_is_statement_and_scope() -> None:
    lesson = _lesson("L1")
    assert lk.lesson_text(lesson) == "the NTSB codes it so (scope: a scope)"
