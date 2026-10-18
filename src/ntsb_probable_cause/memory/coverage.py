"""Lesson coverage: how often a lookup's lessons agree with the NTSB's codes (decision 0213).

A script, not a model. A chosen lesson agrees with a case by the learner's own support test
(``curate.agrees``, decision 0209): on each part the lesson predicts, the case's codes match. Hit
rate is the share of cases where at least one chosen lesson agrees; precision is the share of the
lessons handed out that agree. It reads verdict codes for scoring only, and no case text.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ntsb_probable_cause import fields
from ntsb_probable_cause.memory import curate
from ntsb_probable_cause.memory.lessons import Lesson
from ntsb_probable_cause.memory.pool import LearningCase


@dataclass(frozen=True)
class Coverage:
    """One lookup's lesson coverage over a sample.

    Attributes:
        hits: case id to whether at least one chosen lesson agrees.
        handed_out: lessons handed out over every scored case.
        agreeing: of those, the ones that agree.
    """

    hits: dict[str, bool]
    handed_out: int
    agreeing: int

    @property
    def hit_rate(self) -> float:
        """The share of scored cases with a lesson that agrees; 0.0 with no case."""
        return sum(self.hits.values()) / len(self.hits) if self.hits else 0.0

    @property
    def precision(self) -> float:
        """The share of handed-out lessons that agree; 0.0 when none was handed out."""
        return self.agreeing / self.handed_out if self.handed_out else 0.0


def coverage(chosen: Mapping[str, Sequence[Lesson]], cases: Mapping[str, LearningCase]) -> Coverage:
    """Score ``chosen`` on the cases in ``cases``; a case missing from ``chosen`` has no lesson."""
    hits: dict[str, bool] = {}
    handed = agreeing = 0
    for case_id, case in cases.items():
        lessons = chosen.get(case_id, ())
        agree = [curate.agrees(lesson, case) for lesson in lessons]
        hits[case_id] = any(agree)
        handed += len(lessons)
        agreeing += sum(agree)
    return Coverage(hits, handed, agreeing)


def part_coverage(
    chosen: Mapping[str, Sequence[Lesson]], cases: Mapping[str, LearningCase]
) -> tuple[Coverage, Coverage]:
    """``chosen`` scored on each part apart: the first-code part, then the finding part.

    A lesson counts on a part only if it predicts that part (``curate.first_agrees``,
    ``curate.finding_agrees``); ``coverage`` needs every predicted part at once (decision 0214).
    """
    parts = (
        (curate.first_agrees, "first_occurrence"),
        (curate.finding_agrees, "finding_categories"),
    )
    out: list[Coverage] = []
    for agrees, field in parts:
        hits: dict[str, bool] = {}
        handed = agreeing = 0
        for case_id, case in cases.items():
            lessons = [x for x in chosen.get(case_id, ()) if getattr(x.predicts, field)]
            agree = [agrees(lesson, case) for lesson in lessons]
            hits[case_id] = any(agree)
            handed += len(lessons)
            agreeing += sum(agree)
        out.append(Coverage(hits, handed, agreeing))
    return out[0], out[1]


def verdict_cases(
    ids: Sequence[str], raws: Sequence[Mapping[str, object]]
) -> tuple[dict[str, LearningCase], int]:
    """The cases to score, from their raw records, and how many were left out.

    A case with no occurrence code is left out: ``curate.first_agrees`` reads the first code. Its
    year is not read by the agreement test and is set to 0.
    """
    found: dict[str, LearningCase] = {}
    for case_id, raw in zip(ids, raws, strict=True):
        occurrence = fields.occurrence_codes(raw)
        if occurrence:
            cause = fields.probable_cause(raw) or ""
            found[case_id] = LearningCase(
                case_id, 0, cause, occurrence, fields.finding_codes_in_cause(raw)
            )
    return found, len(ids) - len(found)
