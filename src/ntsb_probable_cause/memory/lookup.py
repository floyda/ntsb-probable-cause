"""The lessons for one case, matched to the model's own first answer (decision 0210).

A script, not a model: a lesson matches when a code it predicts is among the answer's codes. The
query is the answer's occurrence codes and finding categories only; no case text is read here.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final

from ntsb_probable_cause.memory.lessons import Lesson

K: Final = 5
MIN_APPLIES: Final = 10


@dataclass(frozen=True)
class Match:
    """How one lesson matches an answer.

    Attributes:
        exact: predicted first codes among the answer's occurrence codes, plus predicted finding
            categories among the answer's categories.
        event: predicted first codes that are not in the answer but share an event with one of
            its occurrence codes (the same event in another phase, which a split lesson exists to
            settle).
    """

    exact: int
    event: int


def match(lesson: Lesson, occurrence: Collection[str], categories: Collection[str]) -> Match:
    """``lesson`` against an answer's six-digit occurrence codes and finding categories."""
    first = lesson.predicts.first_occurrence
    events = {code[3:] for code in occurrence}
    exact_first = sum(code in occurrence for code in first)
    exact_cats = sum(category in categories for category in lesson.predicts.finding_categories)
    event = sum(code not in occurrence and code[3:] in events for code in first)
    return Match(exact=exact_first + exact_cats, event=event)


def fit(lesson: Lesson) -> float:
    """The share of the cases it applies to that agree with it; 0.0 without support."""
    s = lesson.support
    return s.agrees / s.applies if s is not None and s.applies else 0.0


def lookup(
    lessons: Sequence[Lesson],
    occurrence: Collection[str],
    categories: Collection[str],
    *,
    k: int = K,
    min_applies: int = MIN_APPLIES,
) -> tuple[Lesson, ...]:
    """Up to ``k`` matching lessons that apply to at least ``min_applies`` learning cases.

    Order: most exact matches, then most event matches, then highest fit, then most cases applied
    to, then lesson id, so the same answer always gets the same lessons.
    """

    def rank(item: tuple[Lesson, Match]) -> tuple[int, int, float, int, str]:
        lesson, m = item
        applies = lesson.support.applies if lesson.support is not None else 0
        return (-m.exact, -m.event, -fit(lesson), -applies, lesson.lesson_id)

    eligible = [
        (lesson, match(lesson, occurrence, categories))
        for lesson in lessons
        if lesson.support is not None and lesson.support.applies >= min_applies
    ]
    found = sorted((item for item in eligible if item[1].exact or item[1].event), key=rank)
    return tuple(lesson for lesson, _ in found[:k])
