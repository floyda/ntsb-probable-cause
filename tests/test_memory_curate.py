"""Support counts, revision, the cap and model agreement (decisions 0201, 0204). Offline."""

from ntsb_probable_cause.memory import curate
from ntsb_probable_cause.memory.lessons import Lesson, Prediction, Support
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring.codes import load_tables

TABLES = load_tables()
# Real codes from the NTSB tables: a finding under category 020630, one outside it.
FLAGGED_FINDING = TABLES.compose_finding("02063000", "44")
OTHER_FINDING = TABLES.compose_finding("01010000", "00")


def _case(case_id: str, first: str, findings: tuple[str, ...] = ()) -> LearningCase:
    return LearningCase(case_id, 2009, "cause", (first, "600470"), findings)


def _lesson(
    lid: str,
    kind: str = "convention",
    first: tuple[str, ...] = ("550240",),
    cats: tuple[str, ...] = (),
) -> Lesson:
    return Lesson(
        lesson_id=lid,
        kind=kind,
        statement="the NTSB codes it so",
        scope="a scope",
        predicts=Prediction(first_occurrence=first, finding_categories=cats),
        written_in=2009,
    )


def test_a_convention_agrees_when_the_first_code_matches() -> None:
    assert curate.agrees(_lesson("L1"), _case("A", "550240"))
    assert not curate.agrees(_lesson("L1"), _case("A", "551240"))


def test_a_split_agrees_when_the_first_code_is_any_of_its_codes() -> None:
    lesson = _lesson("L2", kind="split", first=("550240", "551240"))
    assert curate.agrees(lesson, _case("A", "551240"))


def test_finding_categories_must_all_be_among_the_flagged_findings() -> None:
    lesson = _lesson("L3", kind="evidence", first=(), cats=("020630",))
    assert curate.agrees(lesson, _case("A", "550240", (FLAGGED_FINDING,)))
    assert not curate.agrees(lesson, _case("A", "550240", (OTHER_FINDING,)))


def test_support_counts_applies_agrees_and_the_commonest_first_codes() -> None:
    cases = [_case("A", "550240"), _case("B", "550240"), _case("C", "551240"), _case("D", "550240")]
    applies = {
        "A": frozenset({"L1"}),
        "B": frozenset({"L1"}),
        "C": frozenset({"L1"}),
        "D": frozenset(),
    }
    s = curate.count_support([_lesson("L1")], cases, applies)["L1"]
    assert (s.applies, s.agrees) == (3, 2)
    assert s.first_codes == (("550240", 2), ("551240", 1))


def test_revision_when_disagreements_outnumber_agreements_and_unused_when_none_apply() -> None:
    assert curate.needs_revision(Support(applies=5, agrees=2))
    assert not curate.needs_revision(Support(applies=4, agrees=2))
    assert curate.unused(Support(applies=0, agrees=0))


def test_the_cap_keeps_the_best_supported_lessons_first() -> None:
    strong = _lesson("L1").model_copy(update={"support": Support(applies=10, agrees=9)})
    weak = _lesson("L2").model_copy(update={"support": Support(applies=10, agrees=3)})
    room = curate.estimated_tokens(curate.render_lesson(strong, TABLES)) + 1  # its line break
    kept, pushed = curate.apply_cap([weak, strong], TABLES, room)
    assert [lesson.lesson_id for lesson in kept] == ["L1"]
    assert [lesson.lesson_id for lesson in pushed] == ["L2"]


def test_agreement_counts_pairs_either_model_marks() -> None:
    a = {"A": frozenset({"L1", "L2"}), "B": frozenset()}
    b = {"A": frozenset({"L1"}), "B": frozenset({"L3"})}
    assert curate.agreement(a, b) == (1, 3)


def test_the_cap_stops_at_the_first_lesson_that_does_not_fit() -> None:
    # Decision 0201 item 5: a lesson enters a full memory only by beating the weakest.
    strong = _lesson("L1").model_copy(
        update={"statement": "the NTSB codes it so " * 20, "support": Support(applies=10, agrees=9)}
    )
    weak = _lesson("L2").model_copy(update={"support": Support(applies=10, agrees=3)})
    small = curate.estimated_tokens(curate.render_lesson(weak, TABLES)) + 1
    big = curate.estimated_tokens(curate.render_lesson(strong, TABLES)) + 1
    assert small < big
    kept, pushed = curate.apply_cap([weak, strong], TABLES, small)  # room for the weak one only
    assert kept == ()
    assert [lesson.lesson_id for lesson in pushed] == ["L1", "L2"]
