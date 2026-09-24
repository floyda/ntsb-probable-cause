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
# unguarded_images: an image sent in v3 whose page's transcription failed (0082).
MarkKind = Literal["analysis_sentence", "narrative_coverage", "unguarded_images"]


class CaseMark(BaseModel):
    """One mark: its kind, and how many sentences, documents or images it counts."""

    model_config = ConfigDict(frozen=True)
    kind: MarkKind
    count: int
