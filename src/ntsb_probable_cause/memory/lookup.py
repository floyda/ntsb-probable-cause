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
    """How one lesson matches an answer; each part counts once, however many codes it lists.

    Attributes:
        exact: 1 if any predicted first code is among the answer's occurrence codes, plus 1 if any
            predicted finding category is among the answer's categories (a lesson's categories are
            alternatives, decision 0209, so a long list does not outrank a short one).
        first: 1 if any predicted first code is among the answer's occurrence codes, else 0 (the
            first-code part of ``exact``, which breaks ties ahead of a finding category).
        event: 1 if no predicted first code is in the answer but one shares an event with one of
            its occurrence codes (the same event in another phase, which a split lesson exists to
            settle); else 0.
    """

    exact: int
    first: int
    event: int


def match(lesson: Lesson, occurrence: Collection[str], categories: Collection[str]) -> Match:
    """``lesson`` against an answer's six-digit occurrence codes and finding categories."""
    first = lesson.predicts.first_occurrence
    events = {code[3:] for code in occurrence}
    by_first = any(code in occurrence for code in first)
    by_category = any(category in categories for category in lesson.predicts.finding_categories)
    by_event = not by_first and any(code[3:] in events for code in first)
    return Match(exact=int(by_first) + int(by_category), first=int(by_first), event=int(by_event))


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

    A lesson matches by an exact part or by an event alone (``Match``). Order: most exact parts
    (first code, finding category), then a first-code match ahead of a category match, then an
    event match, then highest fit, then most cases applied to, then lesson id, so the same answer
    always gets the same lessons.
    """

    def rank(item: tuple[Lesson, Match]) -> tuple[int, int, int, float, int, str]:
        lesson, m = item
        applies = lesson.support.applies if lesson.support is not None else 0
        return (-m.exact, -m.first, -m.event, -fit(lesson), -applies, lesson.lesson_id)

    eligible = [
        (lesson, match(lesson, occurrence, categories))
        for lesson in lessons
        if lesson.support is not None and lesson.support.applies >= min_applies
    ]
    found = sorted((item for item in eligible if item[1].exact or item[1].event), key=rank)
    return tuple(lesson for lesson, _ in found[:k])
