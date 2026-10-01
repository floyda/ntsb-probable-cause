"""The trail of one case: a row per model call, the read choices, and how the case ended.

S3.1 Task 8 (spec §8.3; decision 0021 item 2). A row names the tool the reply called, its parsed
arguments and the size of the tool result sent back, never that result's text: a document's
title or text reaches the trail only as a count of characters. The hypothesis is kept at each
checkpoint, so the trail can be scored step by step (0021).

S3.1 Task 11 (spec §4.3; decision 0122 item 5): a later trigger of a case starts from a
``Prior``, the earlier triggers' work as listing indices, the agent's own decisions and reasons,
and its last hypothesis, made from the last trigger's outcome by :func:`prior_of`.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ntsb_probable_cause.agent.schemas import DocumentDecision
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

StepKind = Literal["h0", "choice1", "h1", "choice2", "h2", "coding", "answer", "refine"]
DocketState = Literal["none", "some", "all"]


class _Record(BaseModel):
    """Base of every trail record: no extra fields, no change once written."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class AgentCall(_Record):
    """One model call of a case, and what the loop did with its reply.

    Attributes:
        run_id: the run the call belongs to.
        case_id: the case's NTSB number.
        trigger: which trigger of the case (1 in evaluation, spec §4.1).
        docket_state: the docket the trigger saw: none, some or all (spec §9).
        call_index: the call's place in the case, from 0, in the order the calls were made.
        step: the step the call was made for.
        retry: whether the call re-issued a step whose first call failed.
        tool: the first tool the reply called; None when it called none, and on refinement.
        arguments: that call's parsed arguments; ``{}`` when they did not parse.
        protocol_error: why the reply was not accepted (sanitised: field names and error types,
            never the model's values), or the error a failed batch item carried; None when
            accepted.
        result_chars: the characters of the tool results sent back for this reply; 0 if none.
        argument_errors: the argument errors a coding tool counted (an unknown code, say).
        hypothesis: the hypothesis the call recorded, submitted or refined, when it did.
        prompt_tokens: the reply's prompt tokens.
        cached_tokens: the prompt tokens the provider served from its cache, when reported.
        completion_tokens: the reply's completion tokens.
        reasoning_tokens: the completion tokens spent on reasoning, when reported.
        finish_reason: why the provider stopped the reply.
        cost_usd: the reply's cost (``cost_usd``); 0 when there was no reply.
        estimated_usd: the loop's estimate of the call before it was sent.
        sent_at: when the call was sent.
        returned_at: when its reply (or failure) came back.
        batch_id: the batch the call went in, if any.
        commit_sha: the commit that ran the call (0018).
        dirty: whether the tree had uncommitted changes (0033).
    """

    run_id: str
    case_id: str
    trigger: int
    docket_state: DocketState
    call_index: int
    step: StepKind
    retry: bool
    tool: str | None
    arguments: dict[str, object]
    protocol_error: str | None
    result_chars: int
    argument_errors: int
    hypothesis: Hypothesis | None
    prompt_tokens: int
    cached_tokens: int | None
    completion_tokens: int
    reasoning_tokens: int | None
    finish_reason: str | None
    cost_usd: float
    estimated_usd: float
    sent_at: datetime
    returned_at: datetime
    batch_id: str | None
    commit_sha: str
    dirty: bool


class ReadRecord(_Record):
    """One read choice: what was on offer, the decision on each document, and why.

    Attributes:
        step: the first read choice or the second look.
        offered: the listing indices on offer, in offer order.
        decisions: the agent's decision on each, as it gave them.
        reason: the agent's reason for the choice as a whole.
        trigger: the trigger the choice was made on (1 in evaluation; Task 11).
    """

    step: Literal["choice1", "choice2"]
    offered: tuple[int, ...]
    decisions: tuple[DocumentDecision, ...]
    reason: str
    trigger: int = 1


class Prior(_Record):
    """What a later trigger of a case starts from: the earlier triggers' work (spec §4.3).

    It holds listing indices, the agent's own decisions with their reasons, trigger numbers and
    a hypothesis, never a title or document text: the documents read are re-sent from the docket
    through the split and the guard (``agent/documents.py``), not kept here.

    Attributes:
        trigger: the last trigger it covers.
        last_hypothesis: the last hypothesis recorded on any of those triggers.
        reads: every read choice made on them, in order, each naming its trigger.
        read: the listing indices read on them, in the order they were read; exactly the
            documents the read choices chose to read.

    Raises:
        ValidationError: ``read`` is not exactly the documents ``reads`` chose to read, or a read
            choice names a trigger after ``trigger``.
    """

    trigger: int = Field(ge=1)
    last_hypothesis: Hypothesis
    reads: tuple[ReadRecord, ...]
    read: tuple[int, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        """The summary says what was read: it must be what was sent, and no more."""
        chosen = [d.document for record in self.reads for d in record.decisions if d.read]
        if sorted(chosen) != sorted(self.read):
            raise ValueError("read must be exactly the documents the read choices chose to read")
        if any(record.trigger > self.trigger for record in self.reads):
            raise ValueError("a read choice names a trigger after the prior's own")
        return self


class LoopOutcome(_Record):
    """How one case's trigger ended, with its whole trail.

    Attributes:
        case_id: the case's NTSB number.
        stop_reason: ``done``, ``cap``, ``failed: <step>`` or ``failed: leak`` (spec §4.4).
        checkpoints: each hypothesis in order, named by its step (``h0``, ``h1``, ``h2``,
            ``answer``, ``refine``).
        answer: the final answer, refined when refinement ran; None unless the case is done.
        reads: this trigger's read choices, in order.
        read: the listing indices this trigger's choices read (sent to the model), in the order
            they were read. Documents read on earlier triggers, re-sent in full, are in
            ``prior.read``.
        skipped: the offered documents the agent chose to skip and never read, in offer order.
        coding_calls: the coding tools run.
        argument_errors: the argument errors the coding tools counted, in all.
        cost_usd: the case's cost, summed over every reply.
        calls: one row per model call.
        leak: the guard's message when the case stopped ``failed: leak``, else None. It names
            the role, kind and source of the withheld text, never the text itself (decision
            0016); arm C's case result records it as arm B's does (S3.1 Task 10).
        prior: the earlier triggers this one started from; None on a first trigger (Task 11).
    """

    case_id: str
    stop_reason: str
    checkpoints: tuple[tuple[StepKind, Hypothesis], ...]
    answer: Hypothesis | None
    reads: tuple[ReadRecord, ...]
    read: tuple[int, ...]
    skipped: tuple[int, ...]
    coding_calls: int
    argument_errors: int
    cost_usd: float
    calls: tuple[AgentCall, ...]
    leak: str | None = None
    prior: Prior | None = None


def prior_of(outcome: LoopOutcome, trigger: int) -> Prior:
    """The prior the next trigger of a case starts from, once trigger ``trigger`` has ended.

    The outcome's own prior is carried forward, so the result covers every trigger so far: its
    read choices and documents read come first, then this trigger's. The last hypothesis is this
    trigger's last checkpoint (the refined answer, when refinement ran), or the earlier one when
    this trigger recorded none.

    Args:
        outcome: how trigger ``trigger`` of the case ended.
        trigger: the trigger the outcome is from; every call row carries it.

    Returns:
        The prior.

    Raises:
        ValueError: the outcome stopped on a leak (a document it chose was never sent, and the
            next trigger would send it again); its calls name another trigger; ``trigger`` is
            not after the outcome's own prior; or no trigger so far recorded a hypothesis.
    """
    if outcome.stop_reason == "failed: leak":
        raise ValueError("a trigger that stopped on a leak gives no prior")
    if any(call.trigger != trigger for call in outcome.calls):
        raise ValueError(f"the outcome's calls are not from trigger {trigger}")
    earlier = outcome.prior
    if earlier is not None and trigger <= earlier.trigger:
        raise ValueError("a trigger comes after the trigger its own prior covers")
    if outcome.checkpoints:
        last = outcome.checkpoints[-1][1]
    elif earlier is not None:
        last = earlier.last_hypothesis
    else:
        raise ValueError("no hypothesis was recorded on this trigger or before it")
    return Prior(
        trigger=trigger,
        last_hypothesis=last,
        reads=outcome.reads if earlier is None else (*earlier.reads, *outcome.reads),
        read=outcome.read if earlier is None else (*earlier.read, *outcome.read),
    )
