"""scripts/s3_probe/trail.py: the per-case trail record the loop writes and the report reads.

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

One frozen :class:`CaseTrail` per case, written as one JSON line of ``trails.jsonl`` (Task 5)
and read back by the report (Task 6). A trail holds numbers, the agent's own replies
(hypotheses, reasons, expected effects), coding-tool result text (code labels and pool counts
only), codes and scores. It never holds docket text or a record field: the documents are
described by their measured facts alone (``constraints.md``, "Per-case trail record").
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.docket.classify import Kind
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from scripts.s3_probe.prompts import DocumentChoice

# The phases a call can belong to, in flow order ("The flow for one case", steps 1-8).
Phase = Literal["h0", "choice1", "h1", "choice2", "h2", "h_all", "coding", "final", "refine"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TrailDocument(_Frozen):
    """One docket document's measured facts, and whether the agent could be offered it."""

    index: int
    kind: Kind | None
    pages: int
    readable_pages: int
    estimated_tokens: int
    transcribed_pages: int
    attachable: bool


class CallRecord(_Frozen):
    """One model call: what it cost and how it ended. ``parse_retry`` marks the one retry."""

    phase: Phase
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None
    cost_usd: float
    estimated_usd: float
    seconds: float
    finish_reason: str | None
    parse_retry: bool


class ReadChoiceRecord(_Frozen):
    """One read-choice step: what was offered, the decision per document, and the reason."""

    offered: tuple[int, ...]
    documents: tuple[DocumentChoice, ...]
    reason: str

    @property
    def chosen(self) -> tuple[int, ...]:
        """The indices the agent chose to read, in listing order."""
        return tuple(sorted(d.index for d in self.documents if d.read))


class StageScores(_Frozen):
    """One stage's scores. ``finding_recall_10`` is set on the refined answer alone."""

    occurrence_top1: bool
    occurrence_top3: bool
    finding_recall_10: float | None = None


class Stage(_Frozen):
    """One hypothesis stage: the hypothesis (or ``None``), why it is absent or copied, scores.

    ``note`` is ``None`` when the stage's own call produced the hypothesis. Otherwise it says
    why not: ``"skipped: nothing chosen"`` (a copy of the stage before, no call),
    ``"not needed"``, ``"not run: cap"``, ``"not run: abstained"``, ``"failed: parse"`` or
    ``"failed: leak"`` (H_all alone: a side comparison that does not end the case), or
    ``"not reached"`` when the case stopped first.
    """

    hypothesis: Hypothesis | None
    note: str | None
    # H_all's failure detail: the parser's last error (about the agent's own reply) on
    # "failed: parse", the guard's message on "failed: leak". None otherwise.
    detail: str | None = None
    scores: StageScores | None


NOT_REACHED = Stage(hypothesis=None, note="not reached", scores=None)


class CodingStep(_Frozen):
    """One coding-check reply: the tool call it asked for (or ``done``), and the result."""

    done: bool
    tool: str | None
    kind: str | None
    codes: tuple[str, ...]
    reason: str
    expected_effect: str
    # Recorded as given: may repeat a code or sum above 1 (the parser does not refuse that).
    top3: tuple[OccurrenceGuess, ...]
    result_text: str | None
    result_chars: int
    argument_errors: int


# "done", "max_calls" or "coding_cap" (the case answered; the coding checks ended on done, six
# tool calls, or the reserve for the answer), "cap" (the case cap refused a call on the answer's
# own path), "run_cap", or "failed: <phase>" / "failed: leak".
StopReason = str


class CaseTrail(_Frozen):
    """Everything one case did, in the order it did it; counts and the agent's own words."""

    case_id: str
    fatal: bool
    has_scan: bool
    documents: tuple[TrailDocument, ...]
    calls: tuple[CallRecord, ...]
    choice1: ReadChoiceRecord | None
    choice1_note: str | None
    choice2: ReadChoiceRecord | None
    choice2_note: str | None
    h0: Stage
    h1: Stage
    h2: Stage
    h_all: Stage
    final: Stage
    refined: Stage
    coding_steps: tuple[CodingStep, ...]
    # The pool's top choice among the final top-3 (highest ``defining_n``, ties to the lowest
    # code), and whether the final top-1 follows it. ``None`` when there is no final answer.
    pool_top: str | None
    follows_pool: bool | None
    true_primary: str | None
    true_in_arguments: bool | None
    # The verdict's flagged finding codes (``Verdict.finding_codes_in_cause``, ten digits each):
    # what the readable trail shows beside the agent's own findings. Empty when the verdict was
    # never reached (a leak at the very first split). Added for Task 6's readable trails, which
    # show the true primary occurrence *and* flagged findings with labels -- the plan's own
    # "Per-case trail record" section named only the primary occurrence, so this is a deviation,
    # logged in the plan's Deviations.
    true_findings: tuple[str, ...]
    # The guard's message whenever it refused a payload (role, kind and source -- never withheld
    # text): with ``stop_reason="failed: leak"`` it ended the case; with ``h_all.note ==
    # "failed: leak"`` it refused only the side comparison.
    leak: str | None
    # The parser's last error on ``failed: <phase>``: about the agent's own reply.
    failure: str | None
    # How the coding checks ended: "done", "max_calls", "cap" (no room left for another call and
    # the answer), or None when they were not reached.
    coding_stop: str | None
    stop_reason: StopReason
    cost_usd: float
