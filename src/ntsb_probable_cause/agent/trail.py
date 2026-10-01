"""The trail of one case: a row per model call, the read choices, and how the case ended.

S3.1 Task 8 (spec §8.3; decision 0021 item 2). A row names the tool the reply called, its parsed
arguments and the size of the tool result sent back, never that result's text: a document's
title or text reaches the trail only as a count of characters. The hypothesis is kept at each
checkpoint, so the trail can be scored step by step (0021).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

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
    """

    step: Literal["choice1", "choice2"]
    offered: tuple[int, ...]
    decisions: tuple[DocumentDecision, ...]
    reason: str


class LoopOutcome(_Record):
    """How one case's trigger ended, with its whole trail.

    Attributes:
        case_id: the case's NTSB number.
        stop_reason: ``done``, ``cap``, ``failed: <step>`` or ``failed: leak`` (spec §4.4).
        checkpoints: each hypothesis in order, named by its step (``h0``, ``h1``, ``h2``,
            ``answer``, ``refine``).
        answer: the final answer, refined when refinement ran; None unless the case is done.
        reads: the read choices, in order.
        read: the listing indices read (sent to the model), in the order they were read.
        skipped: the offered documents the agent chose to skip and never read, in offer order.
        coding_calls: the coding tools run.
        argument_errors: the argument errors the coding tools counted, in all.
        cost_usd: the case's cost, summed over every reply.
        calls: one row per model call.
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
