"""Counting support, choosing what to revise, the cap, and model agreement (0201, 0204).

Every number a lesson carries is counted here, by a script, over learning-part cases (rule 3).
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from ntsb_probable_cause.memory.lessons import Lesson, Support, estimated_tokens, render_lesson
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring.codes import CodeTables

FIRST_CODES_SHOWN: Final = 3

__all__ = [
    "agreement",
    "agrees",
    "apply_cap",
    "count_support",
    "estimated_tokens",
    "needs_revision",
    "render_lesson",
    "unused",
    "with_support",
]


def agrees(lesson: Lesson, case: LearningCase) -> bool:
    """Whether ``case``'s codes are what ``lesson`` predicts, on every part it predicts."""
    first = lesson.predicts.first_occurrence
    if first and case.occurrence[0] not in first:
        return False
    flagged = {code[:6] for code in case.findings}
    return all(category in flagged for category in lesson.predicts.finding_categories)


def count_support(
    lessons: Sequence[Lesson], cases: Sequence[LearningCase], applies: Mapping[str, frozenset[str]]
) -> dict[str, Support]:
    """Each lesson's applies, agrees and commonest first codes over ``cases``."""
    support: dict[str, Support] = {}
    for lesson in lessons:
        covered = [c for c in cases if lesson.lesson_id in applies.get(c.case_id, frozenset())]
        firsts = Counter(c.occurrence[0] for c in covered)
        top = tuple(sorted(firsts.items(), key=lambda kv: (-kv[1], kv[0]))[:FIRST_CODES_SHOWN])
        support[lesson.lesson_id] = Support(
            applies=len(covered), agrees=sum(agrees(lesson, c) for c in covered), first_codes=top
        )
    return support


def needs_revision(support: Support) -> bool:
    """A lesson that disagrees with more cases than it agrees with goes back to the learner."""
    return support.applies - support.agrees > support.agrees


def unused(support: Support) -> bool:
    """A lesson no case was judged to fall under; it cannot be supported, so it is retired."""
    return support.applies == 0


def with_support(lessons: Sequence[Lesson], support: Mapping[str, Support]) -> tuple[Lesson, ...]:
    """The lessons, each carrying its counted support."""
    return tuple(
        lesson.model_copy(update={"support": support[lesson.lesson_id]}) for lesson in lessons
    )


def apply_cap(
    lessons: Sequence[Lesson], tables: CodeTables, cap_tokens: int
) -> tuple[tuple[Lesson, ...], tuple[Lesson, ...]]:
    """Keep the best-supported lessons that fit in ``cap_tokens``; the rest are pushed out.

    Order: most agreements, then most applies, then lesson id. Each lesson's size is its
    rendered text's estimate (``estimated_tokens``), plus one for its line break.
    """

    def rank(lesson: Lesson) -> tuple[int, int, str]:
        s = lesson.support or Support(applies=0, agrees=0)
        return (-s.agrees, -s.applies, lesson.lesson_id)

    kept: list[Lesson] = []
    pushed: list[Lesson] = []
    used = 0
    for lesson in sorted(lessons, key=rank):
        size = estimated_tokens(render_lesson(lesson, tables)) + 1
        if used + size <= cap_tokens:
            kept.append(lesson)
            used += size
        else:
            pushed.append(lesson)
    return tuple(kept), tuple(pushed)


def agreement(a: Mapping[str, frozenset[str]], b: Mapping[str, frozenset[str]]) -> tuple[int, int]:
    """Case-and-lesson pairs both models mark, and pairs either marks."""
    both = either = 0
    for case_id in a.keys() | b.keys():
        left, right = a.get(case_id, frozenset()), b.get(case_id, frozenset())
        both += len(left & right)
        either += len(left | right)
    return both, either
