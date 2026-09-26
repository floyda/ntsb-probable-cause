"""Marks: notes on a case kept in logs and results, never in the agent's text (S2.6 §4.4).

A mark says a case belongs to a group that is scored separately beside every result. It is
never written into evidence text: a marker there would tell the agent the NTSB leaned on
that text, which hints at the answer, and a live case -- whose report is not yet written --
could never carry one.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# analysis_sentence: a docket document shares sentences with the analysis narrative (0077).
# narrative_coverage: one document holds at least half the factual narrative (0078).
# Decision 0082's third kind, unguarded_images, belongs to v3's pictures, which are not built
# (0090); it is added with them (S2.6 final review, I2).
MarkKind = Literal["analysis_sentence", "narrative_coverage"]


class CaseMark(BaseModel):
    """One mark: its kind, and how many sentences or documents it counts."""

    model_config = ConfigDict(frozen=True)
    kind: MarkKind
    count: int
