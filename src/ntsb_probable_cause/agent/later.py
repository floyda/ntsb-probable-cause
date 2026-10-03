"""A later trigger's start: the earlier triggers' work as its first two turns (S3.1 Task 11).

Spec §4.3; decision 0122 item 5. A later trigger of a case opens with one answered call: the
earlier triggers' last hypothesis as a ``record_hypothesis`` call (id ``"prior"``), whose result
re-sends every document read before, in full, through the split and the guard
(``agent/documents.py``), with a summary of the agent's earlier read and skip decisions and its
reasons (``texts.prior_summary``). The earlier conversation itself is not replayed: its stale
replies mislead, and it grows without limit (0122, Why 3).

When new structured evidence arrived, H0 follows that call as on a first trigger. When it did
not, that call stands for H0 (the last hypothesis already used everything the case held): its
result also carries what H0's would, the listing and the menu of every unread document, or the
move to coding when nothing is left to choose. When the docket lists documents none of which can
be read, H0's result is the listing, the menu's not-readable lines and ``NONE_READABLE`` before
the move to coding (Andy, 2026-10-01), and so is this call's.

``CaseLoop`` calls :func:`check_prior` before it builds anything and :func:`opening` once its own
state is set. Nothing here keeps state or calls a model.
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from ntsb_probable_cause.agent import steps
from ntsb_probable_cause.agent.documents import DocketView, docket_payload, documents_payload
from ntsb_probable_cause.agent.texts import prior_summary
from ntsb_probable_cause.agent.trail import Prior, StepKind
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import Payload, ToolCall, Turn
from ntsb_probable_cause.model.tool_text import ToolText
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

# The call id of the opening call: the earlier triggers' last hypothesis.
PRIOR_CALL_ID: Final = "prior"


@dataclass(frozen=True)
class Opening:
    """A later trigger's first two turns, and the step the loop takes up after them.

    Attributes:
        history: the assistant turn that calls ``record_hypothesis``, and the tool turn that
            answers it.
        step: ``h0`` when H0 is formed again; otherwise the step after H0 (``choice1``, or
            ``coding`` or ``answer`` when nothing is left to choose).
    """

    history: tuple[Turn, Turn]
    step: StepKind


def check_prior(
    offered: Collection[int], trigger: int, prior: Prior | None, *, new_structured: bool
) -> None:
    """Refuse a trigger that cannot start from its prior.

    Args:
        offered: the listing indices the trigger's docket view offers (none without a view).
        trigger: the trigger's number.
        prior: the earlier triggers' work, or None on a first trigger.
        new_structured: whether new structured evidence arrived since the prior.

    Raises:
        ValueError: ``new_structured=False`` with no prior (a first trigger forms H0); a prior
            whose trigger is not before this one; or a document read before that the view no
            longer offers, which could not be re-sent.
    """
    if prior is None:
        if not new_structured:
            raise ValueError("a first trigger forms H0: new_structured=False needs a prior")
        return
    if trigger <= prior.trigger:
        raise ValueError("a later trigger comes after the trigger its prior covers")
    if not set(offered).issuperset(prior.read):
        raise ValueError("the docket view must offer every document read before")


def opening(  # noqa: PLR0913 -- the prior, the docket, its shelf, the run: all the loop knows.
    prior: Prior,
    view: DocketView | None,
    shelf: steps.Shelf,
    exclusions: frozenset[EvidenceRole],
    *,
    coding: bool,
    new_structured: bool,
) -> Opening:
    """The two turns a later trigger's conversation starts with, after the evidence.

    Args:
        prior: the earlier triggers' work, checked by :func:`check_prior`.
        view: the docket, or None when there is none or it lists nothing.
        shelf: the documents now, those read before counted as read.
        exclusions: the run's excluded evidence roles.
        coding: whether the run has a coding step.
        new_structured: whether new structured evidence arrived; if not, the call stands for H0.

    Returns:
        The two turns and the step that follows them. The tool turn's payload holds the
        documents read before (with the listing when a read choice follows, or when every
        listed document is unreadable and no H0 is formed), or is None when there is neither:
        the summary then goes alone, never beside an empty payload.

    Raises:
        LeakageError: the guard found withheld text in a document read before or the listing.
    """
    text = prior_summary(prior)
    step: StepKind = "h0"
    listed = False
    if not new_structured:
        step, after = steps.after_hypothesis("h0", shelf, coding)
        text = f"{text}\n\n{after}"
        listed = steps.lists("h0", shelf)  # what H0's result would carry (Andy, 2026-10-01)
    payload: Payload | None = None
    if listed or prior.read:
        if view is None:  # check_prior refuses a prior whose documents are not on offer
            raise RuntimeError("documents to re-send, with no docket on offer")
        build = docket_payload if listed else documents_payload
        payload = build(view, prior.read, exclusions)
    call = ToolCall(
        call_id=PRIOR_CALL_ID,
        name="record_hypothesis",
        arguments=as_recorded(prior.last_hypothesis),
    )
    result = Turn(
        role="tool", tool_call_id=call.call_id, payload=payload, tool_text=ToolText.of(text)
    )
    return Opening(history=(Turn(role="assistant", tool_calls=(call,)), result), step=step)


def as_recorded(hypothesis: Hypothesis) -> str:
    """A hypothesis as ``record_hypothesis`` arguments: the tool's own shape, with no ``item8``.

    The refinement's items are stage 2's (``scoring/hypothesis.py``, ``HYPOTHESIS_SCHEMA``), so a
    refined answer is recorded as the answer it refined.
    """
    return hypothesis.model_dump_json(exclude={"findings": {"__all__": {"item8"}}})
