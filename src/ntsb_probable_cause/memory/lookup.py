"""The lessons for one case: by its first answer's codes (0210), or its cause sentence (0211-0214).

A script, not a model. ``lookup`` matches a lesson when a code it predicts is among the model's
first answer's codes; its query is the answer's occurrence codes and finding categories only.
``by_fit`` reads no code: it ranks the lessons the apply step named for the case's cause sentence.
``by_similarity`` reads no code either: it ranks lessons by how close their embedding is to the
cause sentence's (decision 0213); ``by_similarity_fit`` weighs that by fit, and
``by_fit_or_nearest`` fills a case ``by_fit`` leaves empty with the nearest lesson (decision 0214).
No case text is read here.
"""

import math
from collections.abc import Collection, Mapping, Sequence
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


def by_fit(
    lessons: Sequence[Lesson],
    applied: Collection[str],
    *,
    k: int = K,
    min_applies: int = MIN_APPLIES,
) -> tuple[Lesson, ...]:
    """Up to ``k`` of the lessons whose ids are in ``applied``, by fit (decision 0211).

    ``applied`` is what the apply step named for one case's cause sentence. Only lessons that
    apply to at least ``min_applies`` learning cases may be chosen. Order: highest fit, then most
    cases applied to, then lesson id, so the same answer always gets the same lessons.
    """

    def rank(lesson: Lesson) -> tuple[float, int, str]:
        applies = lesson.support.applies if lesson.support is not None else 0
        return (-fit(lesson), -applies, lesson.lesson_id)

    eligible = [
        lesson
        for lesson in lessons
        if lesson.lesson_id in applied
        and lesson.support is not None
        and lesson.support.applies >= min_applies
    ]
    return tuple(sorted(eligible, key=rank)[:k])


def lesson_text(lesson: Lesson) -> str:
    """The text a lesson is embedded as: its statement and scope, never a code (decision 0213)."""
    return f"{lesson.statement} (scope: {lesson.scope})"


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors of one length; 0.0 when either is all zeros."""
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norms if norms else 0.0


def by_similarity(
    lessons: Sequence[Lesson],
    vectors: Mapping[str, Sequence[float]],
    query: Sequence[float],
    *,
    k: int = K,
    min_applies: int = MIN_APPLIES,
) -> tuple[Lesson, ...]:
    """Up to ``k`` eligible lessons closest to ``query`` (decision 0213).

    ``vectors`` maps a lesson id to its embedding; ``query`` is the case's cause sentence's.
    Eligible: at least ``min_applies`` learning cases and a vector. Order: highest cosine, then
    highest fit, then most cases applied to, then lesson id, so the same input always gets the
    same lessons.
    """

    def rank(lesson: Lesson) -> tuple[float, float, int, str]:
        applies = lesson.support.applies if lesson.support is not None else 0
        closeness = cosine(vectors[lesson.lesson_id], query)
        return (-closeness, -fit(lesson), -applies, lesson.lesson_id)

    eligible = [
        lesson
        for lesson in lessons
        if lesson.support is not None
        and lesson.support.applies >= min_applies
        and lesson.lesson_id in vectors
    ]
    return tuple(sorted(eligible, key=rank)[:k])


def by_similarity_fit(
    lessons: Sequence[Lesson],
    vectors: Mapping[str, Sequence[float]],
    query: Sequence[float],
    *,
    k: int = K,
    min_applies: int = MIN_APPLIES,
) -> tuple[Lesson, ...]:
    """Up to ``k`` eligible lessons with the highest cosine x fit (decision 0214).

    As ``by_similarity``, but a lesson close in wording that is rarely right ranks lower. Order:
    highest cosine x fit, then highest fit, then most cases applied to, then lesson id.
    """

    def rank(lesson: Lesson) -> tuple[float, float, int, str]:
        applies = lesson.support.applies if lesson.support is not None else 0
        score = cosine(vectors[lesson.lesson_id], query) * fit(lesson)
        return (-score, -fit(lesson), -applies, lesson.lesson_id)

    eligible = [
        lesson
        for lesson in lessons
        if lesson.support is not None
        and lesson.support.applies >= min_applies
        and lesson.lesson_id in vectors
    ]
    return tuple(sorted(eligible, key=rank)[:k])


def by_fit_or_nearest(  # noqa: PLR0913 -- the case's two queries and the lookup's two settings
    lessons: Sequence[Lesson],
    applied: Collection[str],
    vectors: Mapping[str, Sequence[float]],
    query: Sequence[float] | None,
    *,
    k: int = K,
    min_applies: int = MIN_APPLIES,
) -> tuple[Lesson, ...]:
    """Today's cause lookup (``by_fit``); for a case it gives none, the one nearest lesson (0214).

    ``query`` is the case's cause-sentence vector, or None when it has none: then the case keeps
    no lesson.
    """
    today = by_fit(lessons, applied, k=k, min_applies=min_applies)
    if today or query is None:
        return today
    return by_similarity(lessons, vectors, query, k=1, min_applies=min_applies)
