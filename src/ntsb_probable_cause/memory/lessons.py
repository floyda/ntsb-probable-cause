"""Lessons, snapshots of them, and the text a model reads (decision 0201).

A lesson's statement is the learner's words; every number shown with it is written by the
counting step (``curate.count_support``), never by the learner (rule 3).
"""

import math
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from ntsb_probable_cause.scoring.codes import CodeTables

Kind = Literal["convention", "split", "evidence"]
CAP_TOKENS: Final = 6000


class Prediction(BaseModel):
    """What a lesson predicts for a case it applies to, checkable by a script."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    first_occurrence: tuple[str, ...] = ()
    finding_categories: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """True when the lesson predicts nothing a script can check."""
        return not self.first_occurrence and not self.finding_categories


class Support(BaseModel):
    """A lesson's counted support over the learning part seen so far."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    applies: int
    agrees: int
    first_codes: tuple[tuple[str, int], ...] = ()
    # Decision 0209: counted per part from then on; None in the pilot's snapshots, and for a
    # part the lesson does not predict.
    first_agrees: int | None = None
    finding_agrees: int | None = None


class Lesson(BaseModel):
    """One lesson: the learner's statement, its scope, and what it predicts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    lesson_id: str
    kind: Kind
    statement: str
    scope: str
    predicts: Prediction
    written_in: int
    support: Support | None = None
    history: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _predicts_by_kind(self) -> Self:
        first = self.predicts.first_occurrence
        if self.predicts.is_empty():
            raise ValueError(f"{self.lesson_id}: a lesson must predict something")
        if self.kind == "convention" and len(first) > 1:
            raise ValueError(f"{self.lesson_id}: a convention predicts at most one first code")
        if self.kind == "split" and len(first) < 2:  # noqa: PLR2004 -- a split is two or more
            raise ValueError(f"{self.lesson_id}: a split predicts two or more first codes")
        if self.kind == "evidence" and not self.predicts.finding_categories:
            raise ValueError(f"{self.lesson_id}: an evidence lesson names a finding category")
        return self


class Memory(BaseModel):
    """A snapshot: the lessons kept after a period, and those the cap pushed out."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    periods: tuple[int, ...]
    cap_tokens: int = CAP_TOKENS
    lessons: tuple[Lesson, ...] = ()
    pushed_out: tuple[Lesson, ...] = ()


def estimated_tokens(text: str) -> int:
    """The project's estimate: characters over four, rounded up."""
    return math.ceil(len(text) / 4)


def _occurrence_label(code: str, tables: CodeTables) -> str:
    phase = tables.phases.get(code[:3], "?")
    event = tables.events.get(code[3:], "?")
    return f"{code} {phase} / {event}"


def render_lesson(lesson: Lesson, tables: CodeTables) -> str:
    """One lesson as a model reads it: statement, what it predicts, and its counted support."""
    lines = [
        f"- [{lesson.lesson_id}] ({lesson.kind}) {lesson.statement}",
        f"  scope: {lesson.scope}",
    ]
    if lesson.predicts.first_occurrence:
        named = "; ".join(_occurrence_label(c, tables) for c in lesson.predicts.first_occurrence)
        lines.append(f"  first occurrence code: {named}")
    if lesson.predicts.finding_categories:
        named = "; ".join(
            f"{c} {tables.categories.get(c, '?')}" for c in lesson.predicts.finding_categories
        )
        lines.append(f"  finding categories: {named}")
    if lesson.support is not None:
        lines.append(_counted_line(lesson.support))
    return "\n".join(lines)


def _counted_line(s: Support) -> str:
    """The counted support. The pilot's snapshots keep their original line (decision 0209)."""
    seen = ", ".join(f"{code} ({n})" for code, n in s.first_codes)
    if s.first_agrees is None and s.finding_agrees is None:
        counted = f"  counted: applies to {s.applies} learning cases, agrees in {s.agrees}"
    else:
        parts = [f"  counted: applies to {s.applies} learning cases"]
        if s.first_agrees is not None:
            parts.append(f"first code one of those predicted in {s.first_agrees}")
        if s.finding_agrees is not None:
            parts.append(f"at least one listed finding category flagged in {s.finding_agrees}")
        counted = "; ".join(parts)
    return f"{counted}; first codes seen: {seen}" if seen else counted


def render_memory(memory: Memory, tables: CodeTables) -> str:
    """The whole memory, in lesson order, as the coding test and the learner read it."""
    return "\n".join(render_lesson(lesson, tables) for lesson in memory.lessons)


def render_for_apply(memory: Memory) -> str:
    """The apply step's view: ids, statements and scopes only, never codes or counts.

    The apply step judges from a case's cause sentence whether a lesson covers it; showing it
    the predicted codes would let it judge by codes and make agreement circular.
    """
    return "\n".join(
        f"- [{lesson.lesson_id}] {lesson.statement} (scope: {lesson.scope})"
        for lesson in memory.lessons
    )
