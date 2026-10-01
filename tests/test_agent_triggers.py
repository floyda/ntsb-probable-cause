"""Tests for later triggers (S3.1 Task 11): ``Prior``, ``prior_of``, ``prior_summary`` and the loop.

A later trigger of a case starts from the earlier ones (spec §4.3; decision 0122 item 5): every
document read so far is re-sent in full, the agent's earlier read and skip decisions are
summarised with its reasons, every unread document is offered again, and H0 is formed again only
when new structured evidence arrived. No S3.1 evaluation run uses this; S3.3 does. The loop is
driven as in ``tests/test_agent_loop.py``; offline, no model is called.
"""

import json
from collections.abc import Sequence
from itertools import pairwise

import pytest
from pydantic import ValidationError
from tests.boundary import assert_requests_clean
from tests.test_agent_documents import ANALYSIS, CAUSE, FACTUAL, ONE, TWO, _raw, _withheld
from tests.test_agent_loop import (
    REFINED,
    TABLES,
    _choose,
    _config,
    _drive,
    _every_call_answered,
    _hyp,
    _no_call,
    _tool_turns,
)
from tests.test_attach import _docket as small_docket

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent import later as later_module
from ntsb_probable_cause.agent.documents import (
    DocketView,
    answer_payload,
    docket_payload,
    docket_view,
    documents_payload,
    evidence_payload,
    listing_payload,
)
from ntsb_probable_cause.agent.loop import CaseLoop, PendingCall
from ntsb_probable_cause.agent.schemas import REQUIRED, DocumentDecision, force, parse_call
from ntsb_probable_cause.agent.steps import Shelf
from ntsb_probable_cause.agent.texts import (
    ALL_READ,
    ANSWER_NOW,
    CHOOSE,
    CODE_NOW,
    NO_DOCUMENTS,
    NONE_READABLE,
    menu,
    prior_summary,
)
from ntsb_probable_cause.agent.trail import LoopOutcome, Prior, ReadRecord, prior_of
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.batch import BatchRequest
from ntsb_probable_cause.model.client import (
    ModelReply,
    Payload,
    RecordingFakeClient,
    Turn,
    tool_reply,
)
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

# The document that arrives between the two triggers: docket item 3, readable from trigger 2.
THREE = "[page 1 of 3]\nThe propeller blades showed chordwise scratching.\n"
TITLES = (
    "Powerplant Examination Report",
    "Party Submission - engine manufacturer",
    "Pilot Operator Report 6120",
)
NONE: frozenset[EvidenceRole] = frozenset()

# Trigger 1: read document 1, skip document 2 at both choices, code, answer, refine.
FIRST: list[str | ModelReply] = [
    tool_reply("record_hypothesis", _hyp(), call_id="c1"),
    tool_reply("choose_documents", _choose({1: True, 2: False}), call_id="c2"),
    tool_reply("record_hypothesis", _hyp(), call_id="c3"),
    tool_reply("choose_documents", _choose({2: False}), call_id="c4"),
    tool_reply("submit_answer", _hyp(), call_id="c5"),
    REFINED,
]
# Trigger 2, after document 3 arrived (offered smallest first: 3, then 2).
LATER: list[str | ModelReply] = [
    tool_reply("choose_documents", _choose({3: True, 2: False}), call_id="d1"),
    tool_reply("record_hypothesis", _hyp(confidence=0.7), call_id="d2"),
    tool_reply("choose_documents", _choose({2: False}), call_id="d3"),
    tool_reply("submit_answer", _hyp(confidence=0.7), call_id="d4"),
    REFINED,
]
LATER_WITH_H0: list[str | ModelReply] = [
    tool_reply("record_hypothesis", _hyp(confidence=0.5), call_id="d0"),
    *LATER,
]


def _first_view() -> DocketView:
    return docket_view(_raw(), small_docket({1: ONE, 2: TWO}))


def _later_view(raw: dict[str, object] | None = None) -> DocketView:
    return docket_view(raw or _raw(), small_docket({1: ONE, 2: TWO, 3: THREE}))


def _first_outcome() -> LoopOutcome:
    loop = CaseLoop(_raw(), _first_view(), _config())
    _drive(loop, FIRST)
    assert loop.outcome.stop_reason == "done"
    return loop.outcome


def _prior() -> Prior:
    return prior_of(_first_outcome(), 1)


def _decided(read: Sequence[int], skipped: Sequence[int], *, trigger: int = 1) -> ReadRecord:
    decisions = tuple(
        DocumentDecision(document=n, read=n in read, expected_effect=f"effect {n}")
        for n in (*read, *skipped)
    )
    return ReadRecord(
        step="choice1",
        offered=tuple(sorted((*read, *skipped))),
        decisions=decisions,
        reason="a reason",
        trigger=trigger,
    )


def _prior_reading(read: Sequence[int], skipped: Sequence[int] = ()) -> Prior:
    """A prior made by hand: one read choice on trigger 1 that read ``read``."""
    reads = (_decided(read, skipped),) if read or skipped else ()
    return Prior(
        trigger=1,
        last_hypothesis=Hypothesis.model_validate_json(_hyp()),
        reads=reads,
        read=tuple(read),
    )


def _later(
    replies: Sequence[str | ModelReply],
    *,
    new_structured: bool,
    view: DocketView | None = None,
    prior: Prior | None = None,
    **keywords: object,
) -> tuple[CaseLoop, RecordingFakeClient, list[PendingCall]]:
    loop = CaseLoop(
        _raw(),
        _later_view() if view is None else view,
        _config(),
        trigger=2,
        prior=_prior() if prior is None else prior,
        new_structured=new_structured,
        **keywords,  # type: ignore[arg-type]
    )
    client, calls = _drive(loop, replies)
    return loop, client, calls


def _opening(call: PendingCall) -> tuple[Turn, Turn]:
    assistant, result, *_ = call.history
    return assistant, result


def _documents(payload: Payload | None) -> list[str]:
    assert payload is not None
    rendered = payload.fields()["docket_documents"]
    assert isinstance(rendered, list)
    return [str(item) for item in rendered]


# --------------------------------------------------------------------------------------------
# The first request of a later trigger
# --------------------------------------------------------------------------------------------


class TestTheOpening:
    @pytest.mark.parametrize("new_structured", [True, False])
    def test_holds_every_document_read_before_in_full_and_the_summary(
        self, new_structured: bool
    ) -> None:
        prior = _prior()
        replies = LATER_WITH_H0 if new_structured else LATER
        _, _, calls = _later(replies, new_structured=new_structured, prior=prior)
        assistant, result = _opening(calls[0])
        assert result.payload is not None
        (document,) = _documents(result.payload)
        assert document.endswith(ONE), "document 1, read on trigger 1, is re-sent word for word"
        assert "chordwise" not in result.payload.text, "nothing unread is sent"
        assert result.tool_text is not None
        assert result.tool_text.text.startswith(prior_summary(prior))
        assert calls[0].payload == evidence_payload(_raw(), NONE), "the evidence present now"
        assert assistant.tool_calls[0].call_id == "prior"

    def test_is_one_record_hypothesis_call_answered_by_one_tool_turn(self) -> None:
        prior = _prior()
        _, _, calls = _later(LATER_WITH_H0, new_structured=True, prior=prior)
        assistant, result = _opening(calls[0])
        assert assistant.role == "assistant"
        assert assistant.content is None
        assert assistant.reasoning_details == ()
        (call,) = assistant.tool_calls
        assert (call.call_id, call.name) == ("prior", "record_hypothesis")
        assert (result.role, result.tool_call_id) == ("tool", "prior")
        assert result.payload == documents_payload(_later_view(), (1,), NONE)
        assert result.tool_text is not None
        assert result.tool_text.text == prior_summary(prior)

    def test_the_call_records_the_last_hypothesis_in_the_tools_own_shape(self) -> None:
        """The refined answer is the last hypothesis; the call carries it without its items."""
        prior = _prior()
        assert prior.last_hypothesis.findings[0].item8 == "02063015"
        _, _, calls = _later(LATER, new_structured=False, prior=prior)
        (call,) = _opening(calls[0])[0].tool_calls
        assert "item8" not in call.arguments
        recorded = parse_call("record_hypothesis", call.arguments, TABLES)
        assert recorded == Hypothesis.model_validate_json(_hyp()), "the answer, before its items"

    def test_with_nothing_read_before_the_summary_goes_alone(self) -> None:
        """No empty ``{}`` payload: the summary is the tool turn's only part."""
        prior = _prior_reading((), (1, 2))
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({1: False, 3: False, 2: False})),
            tool_reply("choose_documents", _choose({1: False, 3: False, 2: False})),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        _, _, calls = _later(replies, new_structured=True, prior=prior)
        _, result = _opening(calls[0])
        assert result.payload is None
        assert result.tool_text is not None
        assert result.tool_text.text == prior_summary(prior)

    def test_without_new_structured_evidence_it_carries_the_listing_and_the_menu(self) -> None:
        prior = _prior()
        view = _later_view()
        _, _, calls = _later(LATER, new_structured=False, prior=prior)
        _, result = _opening(calls[0])
        assert result.payload == docket_payload(view, (1,), NONE)
        assert result.payload is not None
        assert set(result.payload.fields()) == {"docket_listing", "docket_documents"}
        assert all(title in result.payload.text for title in TITLES)
        rest = tuple(f for f in view.offered if f.index != 1)
        assert [f.index for f in rest] == [3, 2]
        assert result.tool_text is not None
        assert result.tool_text.text == (
            f"{prior_summary(prior)}\n\n"
            f"{menu(rest, view.not_readable, already_read=(1,))}\n\n{CHOOSE}"
        )

    def test_without_new_structured_evidence_and_nothing_read_it_carries_the_listing(
        self,
    ) -> None:
        prior = _prior_reading((), (1, 2))
        replies: list[str | ModelReply] = [
            tool_reply("choose_documents", _choose({1: False, 3: False, 2: False})),
            tool_reply("choose_documents", _choose({1: False, 3: False, 2: False})),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        _, _, calls = _later(replies, new_structured=False, prior=prior)
        _, result = _opening(calls[0])
        assert result.payload == listing_payload(_later_view(), NONE)
        assert result.payload == docket_payload(_later_view(), (), NONE)


# --------------------------------------------------------------------------------------------
# What is offered again, and whether H0 is formed again
# --------------------------------------------------------------------------------------------


class TestOfferedAgain:
    def test_a_document_skipped_before_is_offered_again(self) -> None:
        loop, _, calls = _later(LATER, new_structured=False)
        assert calls[0].step == "choice1"
        first, second = loop.outcome.reads
        assert first.offered == (3, 2), "document 2, skipped on trigger 1, is offered again"
        assert second.offered == (2,)
        assert loop.outcome.read == (3,)
        assert loop.outcome.skipped == (2,)

    def test_a_document_read_before_is_not_offered_again(self) -> None:
        bad = tool_reply("choose_documents", _choose({1: True, 3: True, 2: False}), call_id="x")
        loop, _, calls = _later([bad, *LATER], new_structured=False)
        error = loop.outcome.calls[0].protocol_error
        assert error is not None
        assert "not offered [1]" in error
        assert calls[1].step == "choice1"
        assert loop.outcome.calls[1].retry

    def test_without_new_structured_evidence_no_h0_call_is_made(self) -> None:
        loop, _, calls = _later(LATER, new_structured=False)
        assert [c.step for c in calls] == ["choice1", "h1", "choice2", "coding", "refine"]
        assert calls[0].settings.tool_choice == force("choose_documents")
        assert [kind for kind, _ in loop.outcome.checkpoints] == ["h1", "answer", "refine"]
        assert loop.outcome.stop_reason == "done"

    def test_with_new_structured_evidence_h0_is_formed_again(self) -> None:
        loop, _, calls = _later(LATER_WITH_H0, new_structured=True)
        assert [c.step for c in calls] == ["h0", "choice1", "h1", "choice2", "coding", "refine"]
        assert calls[0].settings.tool_choice == force("record_hypothesis")
        assert [kind for kind, _ in loop.outcome.checkpoints] == ["h0", "h1", "answer", "refine"]
        view = _later_view()
        listing = _tool_turns(calls[1].history)[-1]
        assert listing.payload == listing_payload(view, NONE)
        rest = tuple(f for f in view.offered if f.index != 1)
        assert listing.tool_text is not None
        assert listing.tool_text.text == (
            f"{menu(rest, view.not_readable, already_read=(1,))}\n\n{CHOOSE}"
        )

    def test_the_read_choices_name_their_trigger(self) -> None:
        assert {record.trigger for record in _first_outcome().reads} == {1}
        loop, _, _ = _later(LATER, new_structured=False)
        assert {record.trigger for record in loop.outcome.reads} == {2}

    def test_the_outcome_keeps_its_prior_and_this_triggers_reads_apart(self) -> None:
        prior = _prior()
        loop, _, _ = _later(LATER, new_structured=False, prior=prior)
        assert loop.outcome.prior == prior
        assert loop.outcome.read == (3,), "what this trigger's choices read"
        assert _first_outcome().prior is None


# --------------------------------------------------------------------------------------------
# A trigger with nothing new to choose
# --------------------------------------------------------------------------------------------


class TestNothingNew:
    def test_with_everything_read_and_no_new_structured_evidence_it_goes_straight_to_coding(
        self,
    ) -> None:
        prior = _prior_reading((1, 2))
        replies: list[str | ModelReply] = [tool_reply("submit_answer", _hyp()), REFINED]
        view = _first_view()
        loop, _, calls = _later(replies, new_structured=False, prior=prior, view=view)
        assert [c.step for c in calls] == ["coding", "refine"]
        assert calls[0].settings.tool_choice == REQUIRED
        _, result = _opening(calls[0])
        assert result.payload == documents_payload(view, (1, 2), NONE)
        assert result.tool_text is not None
        assert result.tool_text.text == f"{prior_summary(prior)}\n\n{ALL_READ}\n\n{CODE_NOW}"
        assert loop.outcome.reads == ()
        assert [kind for kind, _ in loop.outcome.checkpoints] == ["answer", "refine"]
        assert calls[1].payload == answer_payload(view, (1, 2), NONE)

    def test_with_no_docket_and_no_new_structured_evidence_it_goes_straight_to_coding(
        self,
    ) -> None:
        prior = _prior_reading(())
        replies: list[str | ModelReply] = [tool_reply("submit_answer", _hyp(findings=[]))]
        loop = CaseLoop(_raw(), None, _config(), trigger=2, prior=prior, new_structured=False)
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["coding"]
        _, result = _opening(calls[0])
        assert result.payload is None
        assert result.tool_text is not None
        assert result.tool_text.text == f"{prior_summary(prior)}\n\n{NO_DOCUMENTS}\n\n{CODE_NOW}"
        assert loop.outcome.stop_reason == "done"

    def test_with_nothing_readable_and_no_new_structured_evidence_it_sends_the_listing(
        self,
    ) -> None:
        """H0's result for a docket listing only unreadable documents (Andy, 2026-10-01): the
        opening call stands for H0, so its result carries the listing, the not-readable lines
        and ``NONE_READABLE`` before the move to coding."""
        prior = _prior_reading(())
        view = docket_view(_raw(), small_docket({}))
        replies: list[str | ModelReply] = [tool_reply("submit_answer", _hyp()), REFINED]
        loop, _, calls = _later(replies, new_structured=False, prior=prior, view=view)
        assert [c.step for c in calls] == ["coding", "refine"]
        _, result = _opening(calls[0])
        assert result.payload == docket_payload(view, (), NONE)
        assert result.payload == listing_payload(view, NONE)
        assert all(title in result.payload.text for title in TITLES)
        assert result.tool_text is not None
        assert result.tool_text.text == (
            f"{prior_summary(prior)}\n\n{menu((), view.not_readable)}\n\n{NONE_READABLE}"
            f"\n\n{CODE_NOW}"
        )
        assert calls[1].payload == answer_payload(view, (), NONE)
        assert {row.docket_state for row in loop.outcome.calls} == {"all"}

    def test_with_nothing_readable_and_new_structured_evidence_h0_sends_the_listing(
        self,
    ) -> None:
        prior = _prior_reading(())
        view = docket_view(_raw(), small_docket({}))
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        loop, _, calls = _later(
            replies, new_structured=True, prior=prior, view=view, docket_final=False
        )
        assert [c.step for c in calls] == ["h0", "coding"]
        _, opening = _opening(calls[0])
        assert opening.payload is None, "nothing was read before, and H0 follows"
        after_h0 = _tool_turns(calls[1].history)[-1]
        assert after_h0.payload == listing_payload(view, NONE)
        assert after_h0.tool_text is not None
        assert after_h0.tool_text.text == (
            f"{menu((), view.not_readable)}\n\n{NONE_READABLE}\n\n{CODE_NOW}"
        )
        assert {row.docket_state for row in loop.outcome.calls} == {"some"}

    def test_without_coding_tools_it_goes_straight_to_the_answer(self) -> None:
        prior = _prior_reading((1, 2))
        loop = CaseLoop(
            _raw(),
            _first_view(),
            _config(without=frozenset({"coding"})),
            trigger=2,
            prior=prior,
            new_structured=False,
        )
        _, calls = _drive(loop, [tool_reply("submit_answer", _hyp(findings=[]))])
        assert [c.step for c in calls] == ["answer"]
        _, result = _opening(calls[0])
        assert result.tool_text is not None
        assert result.tool_text.text.endswith(f"\n\n{ALL_READ}\n\n{ANSWER_NOW}")

    def test_with_new_structured_evidence_h0_then_coding_says_everything_was_read(self) -> None:
        prior = _prior_reading((1, 2))
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        _, _, calls = _later(replies, new_structured=True, prior=prior, view=_first_view())
        assert [c.step for c in calls] == ["h0", "coding"]
        after_h0 = _tool_turns(calls[1].history)[-1]
        assert after_h0.payload is None
        assert after_h0.tool_text is not None
        assert after_h0.tool_text.text == f"{ALL_READ}\n\n{CODE_NOW}"


# --------------------------------------------------------------------------------------------
# The docket state and the trigger, per trigger
# --------------------------------------------------------------------------------------------


class TestDocketState:
    def test_is_recorded_per_trigger(self) -> None:
        assert {row.docket_state for row in _first_outcome().calls} == {"all"}
        loop, _, _ = _later(LATER, new_structured=False, docket_final=False)
        assert {row.docket_state for row in loop.outcome.calls} == {"some"}
        assert {row.trigger for row in loop.outcome.calls} == {2}
        final, _, _ = _later(LATER, new_structured=False)
        assert {row.docket_state for row in final.outcome.calls} == {"all"}

    @pytest.mark.parametrize("docket_final", [True, False])
    def test_is_none_when_nothing_is_offered(self, docket_final: bool) -> None:
        loop = CaseLoop(
            _raw(),
            None,
            _config(),
            trigger=2,
            prior=_prior_reading(()),
            docket_final=docket_final,
        )
        _drive(
            loop,
            [
                tool_reply("record_hypothesis", _hyp()),
                tool_reply("submit_answer", _hyp(findings=[])),
            ],
        )
        assert {row.docket_state for row in loop.outcome.calls} == {"none"}

    def test_a_first_trigger_may_see_some_of_the_docket(self) -> None:
        """The docket state is the input's, not the prior's (spec §4.1)."""
        loop = CaseLoop(_raw(), _first_view(), _config(), docket_final=False)
        _drive(loop, FIRST)
        assert {row.docket_state for row in loop.outcome.calls} == {"some"}


# --------------------------------------------------------------------------------------------
# The loop's invariants on a later trigger
# --------------------------------------------------------------------------------------------


class TestInvariants:
    @pytest.mark.parametrize("new_structured", [True, False])
    def test_the_conversation_is_append_only_from_the_opening(self, new_structured: bool) -> None:
        replies = LATER_WITH_H0 if new_structured else LATER
        _, _, calls = _later(replies, new_structured=new_structured)
        conversation = [c for c in calls if c.step != "refine"]
        opening = conversation[0].history[:2]
        for before, after in pairwise(conversation):
            assert after.history[: len(before.history)] == before.history
            assert len(after.history) > len(before.history)
        assert all(c.history[:2] == opening for c in conversation)
        assert _every_call_answered(conversation[-1].history)
        assert len({c.system for c in conversation}) == 1

    def test_next_call_is_idempotent(self) -> None:
        loop = CaseLoop(_raw(), _later_view(), _config(), trigger=2, prior=_prior())
        first = loop.next_call()
        assert first is not None
        assert loop.next_call() is first

    def test_the_estimate_counts_the_opening(self) -> None:
        loop = CaseLoop(
            _raw(), _later_view(), _config(), trigger=2, prior=_prior(), new_structured=False
        )
        call = loop.next_call()
        assert call is not None
        price = sources.price_of("openai/gpt-6-luna:batch")
        assistant, result = _opening(call)
        assert result.payload is not None
        assert result.tool_text is not None
        opening = sum(len(c.name) + len(c.arguments) for c in assistant.tool_calls)
        opening += len(f"{result.payload.text}\n\n{result.tool_text.text}")
        chars = (
            len(call.system) + len(call.payload.text) + len(json.dumps(list(call.settings.tools)))
        )
        expected = (
            (chars + opening) / 4 * price.input_usd_per_mtok + 8000 * price.output_usd_per_mtok
        ) / 1e6
        assert call.estimated_usd == pytest.approx(expected)

    def test_a_large_document_read_before_can_put_the_trigger_over_the_cap(self) -> None:
        big = "[page 1 of 3]\n" + "The wing spar was intact. " * 24000
        view = docket_view(_raw(), small_docket({1: big, 2: TWO}))
        prior = _prior_reading((1,), (2,))
        roomy = CaseLoop(_raw(), view, _config(), trigger=2, prior=prior).next_call()
        plain = CaseLoop(_raw(), view, _config()).next_call()
        assert roomy is not None
        assert plain is not None
        assert roomy.estimated_usd > 2 * plain.estimated_usd
        cap = (roomy.estimated_usd + 2 * plain.estimated_usd) / 2
        assert CaseLoop(_raw(), view, _config(cap_usd=cap)).next_call() is not None
        later = CaseLoop(_raw(), view, _config(cap_usd=cap), trigger=2, prior=prior)
        assert later.next_call() is None
        assert later.outcome.stop_reason == "cap"
        assert later.outcome.calls == ()

    def test_the_last_hypothesis_is_the_draft_whose_refinement_is_held_back(self) -> None:
        """With findings, the earlier hypothesis would be refined: its reserve counts at once."""

        def first(prior: Prior, cap: float) -> PendingCall | None:
            loop = CaseLoop(
                _raw(),
                _first_view(),
                _config(cap_usd=cap),
                trigger=2,
                prior=prior,
                new_structured=False,
            )
            return loop.next_call()

        with_findings = _prior_reading((1, 2))
        without = with_findings.model_copy(
            update={"last_hypothesis": Hypothesis.model_validate_json(_hyp(findings=[]))}
        )
        roomy = first(with_findings, 1.0)
        assert roomy is not None
        assert roomy.step == "coding"
        cap = 2 * roomy.estimated_usd + 1e-9
        plain = first(without, cap)
        assert plain is not None
        assert plain.step == "coding", "no findings, nothing to refine: coding fits"
        held = first(with_findings, cap)
        assert held is None or held.step == "answer", "the refinement's reserve forces the answer"

    def test_the_refinement_holds_every_document_read_on_any_trigger(self) -> None:
        _, _, calls = _later(LATER, new_structured=False)
        refine = calls[-1]
        assert refine.step == "refine"
        assert refine.payload == answer_payload(_later_view(), (1, 3), NONE)

    def test_the_trail_holds_no_tool_result_text(self) -> None:
        loop, _, calls = _later(LATER, new_structured=False)
        trail = loop.outcome.model_dump_json()
        rows = json.dumps([row.model_dump(mode="json") for row in loop.outcome.calls])
        summary = prior_summary(_prior())
        for marker in ("crankshaft", "chordwise", "engine manufacturer", *TITLES, CHOOSE):
            assert marker not in trail
        for marker in (summary.splitlines()[0], "You expected", "attached above"):
            assert marker not in trail
            assert marker not in rows
        opening = _opening(calls[0])[1]
        assert opening.tool_text is not None
        assert loop.outcome.calls[0].result_chars > 0
        assert loop.outcome.calls[0].arguments == json.loads(_choose({3: True, 2: False}))


# --------------------------------------------------------------------------------------------
# Leaks: the opening goes through the split and the guard
# --------------------------------------------------------------------------------------------


LEAKY = f"[page 1 of 3]\nLetter.\n{CAUSE}\n"


class TestLeaks:
    @pytest.mark.parametrize("new_structured", [True, False])
    def test_a_document_read_before_that_now_leaks_ends_the_case_with_no_call(
        self, new_structured: bool
    ) -> None:
        """The case's probable cause is published between the triggers; the re-send trips."""
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: ONE, 2: LEAKY}))
        prior = _prior_reading((2,), (1,))
        loop = CaseLoop(raw, view, _config(), trigger=2, prior=prior, new_structured=new_structured)
        assert loop.next_call() is None
        outcome = loop.outcome
        assert outcome.stop_reason == "failed: leak"
        assert outcome.calls == ()
        assert outcome.leak is not None
        assert "probable_cause" in outcome.leak
        assert CAUSE not in outcome.leak

    def test_the_same_documents_on_the_first_trigger_are_not_a_leak(self) -> None:
        """The control: before the cause existed, document 2 was ordinary evidence."""
        view = docket_view(_raw(), small_docket({1: ONE, 2: LEAKY}))
        assert documents_payload(view, (2,), NONE).text

    def test_a_leak_in_the_listing_without_new_structured_evidence_ends_the_case(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def leak(*_args: object, **_kwargs: object) -> None:
            raise LeakageError("ANC09CA024: docket_listing holds text from probable_cause")

        monkeypatch.setattr(later_module, "docket_payload", leak)
        loop = CaseLoop(
            _raw(), _later_view(), _config(), trigger=2, prior=_prior(), new_structured=False
        )
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "failed: leak"


# --------------------------------------------------------------------------------------------
# The boundary: every request of a later trigger is clean
# --------------------------------------------------------------------------------------------


def _requests(client: RecordingFakeClient) -> list[BatchRequest]:
    return [
        BatchRequest(
            custom_id=f"sync-{n}",
            payload=payload,
            settings=settings,
            system=system,
            history=history,
        )
        for n, (payload, settings, system, history) in enumerate(
            zip(client.payloads, client.settings, client.systems, client.histories, strict=True)
        )
    ]


WITHHELD = [
    ("factual narrative", FACTUAL),
    ("analysis narrative", ANALYSIS),
    ("probable cause", CAUSE),
]


class TestBoundary:
    @pytest.mark.parametrize("new_structured", [True, False])
    def test_a_later_trigger_sends_no_withheld_text(self, new_structured: bool) -> None:
        raw = _withheld(_raw())
        loop = CaseLoop(
            raw,
            _later_view(raw),
            _config(),
            trigger=2,
            prior=_prior(),
            new_structured=new_structured,
        )
        client, _ = _drive(loop, LATER_WITH_H0 if new_structured else LATER)
        assert loop.outcome.stop_reason == "done"
        requests = _requests(client)
        assert all(r.history[0].tool_calls[0].call_id == "prior" for r in requests[:-1])
        assert_requests_clean(requests, WITHHELD)

    def test_the_check_fails_on_withheld_text_in_the_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation test: a summary that carried the probable cause must be caught."""
        original = prior_summary

        def leaky(prior: Prior) -> str:
            return f"{original(prior)}\n{CAUSE}"

        monkeypatch.setattr(later_module, "prior_summary", leaky)
        raw = _withheld(_raw())
        loop = CaseLoop(
            raw, _later_view(raw), _config(), trigger=2, prior=_prior(), new_structured=False
        )
        client, _ = _drive(loop, LATER)
        with pytest.raises(AssertionError, match=r"^tripwire: probable cause .* tool text"):
            assert_requests_clean(_requests(client), WITHHELD)


# --------------------------------------------------------------------------------------------
# prior_of: what the next trigger starts from
# --------------------------------------------------------------------------------------------


class TestPriorOf:
    def test_after_a_first_trigger(self) -> None:
        outcome = _first_outcome()
        prior = prior_of(outcome, 1)
        assert prior.trigger == 1
        assert prior.last_hypothesis == outcome.checkpoints[-1][1]
        assert prior.last_hypothesis == outcome.answer
        assert prior.reads == outcome.reads
        assert prior.read == (1,)

    def test_carries_the_earlier_triggers_forward(self) -> None:
        first = _prior()
        loop, _, _ = _later(LATER, new_structured=False, prior=first)
        second = prior_of(loop.outcome, 2)
        assert second.trigger == 2
        assert second.read == (1, 3)
        assert second.reads == (*first.reads, *loop.outcome.reads)
        assert [r.trigger for r in second.reads] == [1, 1, 2, 2]
        assert second.last_hypothesis == loop.outcome.answer
        assert second.last_hypothesis.confidence == 0.7

    def test_a_third_trigger_re_sends_what_both_earlier_ones_read(self) -> None:
        loop, _, _ = _later(LATER, new_structured=False)
        second = prior_of(loop.outcome, 2)
        third = CaseLoop(
            _raw(), _later_view(), _config(), trigger=3, prior=second, new_structured=False
        )
        call = third.next_call()
        assert call is not None
        assert call.step == "choice1"
        _, result = _opening(call)
        assert result.payload == docket_payload(_later_view(), (1, 3), NONE)
        documents = _documents(result.payload)
        assert documents[0].endswith(ONE)
        assert documents[1].endswith(THREE)
        assert result.tool_text is not None
        assert "Trigger 1, first read choice." in result.tool_text.text
        assert "Trigger 2, second look." in result.tool_text.text

    def test_a_trigger_that_recorded_no_hypothesis_keeps_the_earlier_one(self) -> None:
        bad = tool_reply("choose_documents", _choose({3: True}), call_id="x")
        again = tool_reply("choose_documents", _choose({3: True}), call_id="y")
        first = _prior()
        loop, _, _ = _later([bad, again], new_structured=False, prior=first)
        assert loop.outcome.stop_reason == "failed: choice1"
        second = prior_of(loop.outcome, 2)
        assert second.last_hypothesis == first.last_hypothesis
        assert (second.reads, second.read) == (first.reads, first.read)

    def test_refuses_a_trigger_that_stopped_on_a_leak(self) -> None:
        raw = _withheld(_raw())
        loop = CaseLoop(raw, docket_view(raw, small_docket({1: ONE, 2: LEAKY})), _config())
        _drive(
            loop,
            [
                tool_reply("record_hypothesis", _hyp()),
                tool_reply("choose_documents", _choose({1: False, 2: True})),
            ],
        )
        assert loop.outcome.stop_reason == "failed: leak"
        with pytest.raises(ValueError, match="leak"):
            prior_of(loop.outcome, 1)

    def test_refuses_when_no_hypothesis_was_ever_recorded(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        _drive(loop, [_no_call(), _no_call()])
        with pytest.raises(ValueError, match="no hypothesis"):
            prior_of(loop.outcome, 1)

    def test_refuses_a_trigger_number_its_calls_do_not_carry(self) -> None:
        with pytest.raises(ValueError, match="trigger 2"):
            prior_of(_first_outcome(), 2)

    def test_refuses_a_trigger_number_not_after_the_outcomes_own_prior(self) -> None:
        loop = CaseLoop(_raw(), _later_view(), _config(cap_usd=0.0001), trigger=2, prior=_prior())
        assert loop.next_call() is None
        with pytest.raises(ValueError, match="after"):
            prior_of(loop.outcome, 1)


class TestPrior:
    def test_refuses_documents_read_that_no_choice_read(self) -> None:
        with pytest.raises(ValidationError, match="read"):
            Prior(
                trigger=1,
                last_hypothesis=Hypothesis.model_validate_json(_hyp()),
                reads=(_decided((1,), (2,)),),
                read=(1, 2),
            )

    def test_refuses_a_choice_to_read_whose_document_was_not_read(self) -> None:
        with pytest.raises(ValidationError, match="read"):
            Prior(
                trigger=1,
                last_hypothesis=Hypothesis.model_validate_json(_hyp()),
                reads=(_decided((1, 2), ()),),
                read=(1,),
            )

    def test_refuses_a_choice_from_a_later_trigger(self) -> None:
        with pytest.raises(ValidationError, match="trigger"):
            Prior(
                trigger=1,
                last_hypothesis=Hypothesis.model_validate_json(_hyp()),
                reads=(_decided((1,), (), trigger=2),),
                read=(1,),
            )

    def test_is_frozen_and_closed(self) -> None:
        prior = _prior_reading((1,))
        with pytest.raises(ValidationError):
            prior.trigger = 2  # type: ignore[misc]
        assert Prior.model_config.get("extra") == "forbid"
        assert Prior.model_config.get("frozen") is True

    def test_a_read_record_defaults_to_the_first_trigger(self) -> None:
        record = ReadRecord(step="choice1", offered=(1,), decisions=(), reason="r")
        assert record.trigger == 1


class TestConstruction:
    def test_refuses_a_trigger_that_is_not_after_its_prior(self) -> None:
        with pytest.raises(ValueError, match="after"):
            CaseLoop(_raw(), _later_view(), _config(), trigger=1, prior=_prior())

    def test_refuses_skipping_h0_with_no_prior(self) -> None:
        with pytest.raises(ValueError, match="prior"):
            CaseLoop(_raw(), _later_view(), _config(), new_structured=False)

    @pytest.mark.parametrize("view", ["none", "other"])
    def test_refuses_a_view_that_no_longer_offers_a_document_read_before(self, view: str) -> None:
        docket = None if view == "none" else docket_view(_raw(), small_docket({2: TWO}))
        with pytest.raises(ValueError, match="read before"):
            CaseLoop(_raw(), docket, _config(), trigger=2, prior=_prior())

    def test_the_opening_alone_refuses_documents_with_no_docket(self) -> None:
        """``check_prior`` stops this before the loop gets here; the opening refuses it too."""
        with pytest.raises(RuntimeError, match="no docket"):
            later_module.opening(_prior(), None, Shelf(), NONE, coding=True, new_structured=True)
        assert later_module.PRIOR_CALL_ID == "prior"


# --------------------------------------------------------------------------------------------
# The texts: the summary and the payload a later trigger opens with
# --------------------------------------------------------------------------------------------


class TestPriorSummary:
    def test_is_indices_decisions_reasons_and_triggers(self) -> None:
        assert prior_summary(_prior()) == "\n".join(
            [
                "You have worked on this case before. Each time new evidence arrived was a "
                "trigger; this is a later one.",
                "The record_hypothesis call above is the last hypothesis you recorded.",
                "Documents you read, attached above in full: [1].",
                "Trigger 1, first read choice. Your reason: the examination decides between "
                "the two",
                "[1] read. You expected: the engine's condition",
                "[2] skipped. You expected: the engine's condition",
                "Trigger 1, second look. Your reason: the examination decides between the two",
                "[2] skipped. You expected: the engine's condition",
            ]
        )

    def test_says_none_when_nothing_was_read_or_chosen(self) -> None:
        text = prior_summary(_prior_reading(()))
        assert text.splitlines()[2:] == ["Documents you read: none.", "Read choices: none."]

    def test_holds_no_title_and_no_document_text(self) -> None:
        text = prior_summary(_prior())
        for marker in (*TITLES, "crankshaft", "engine manufacturer", "Docket item"):
            assert marker not in text
        assert text.isascii()

    def test_all_read_is_a_fixed_string(self) -> None:
        assert ALL_READ == "Every docket document on offer has been read; none is left to choose."
        assert type(ALL_READ) is str


class TestDocketPayload:
    def test_holds_the_listing_and_the_documents_named_and_nothing_else(self) -> None:
        view = _later_view()
        payload = docket_payload(view, (3,), NONE)
        assert set(payload.fields()) == {"docket_listing", "docket_documents"}
        assert all(title in payload.text for title in TITLES)
        (document,) = _documents(payload)
        assert document.endswith(THREE)
        assert "crankshaft" not in payload.text

    def test_a_leak_in_a_document_raises(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: ONE, 2: LEAKY}))
        with pytest.raises(LeakageError):
            docket_payload(view, (2,), NONE)

    def test_an_excluded_role_is_left_out(self) -> None:
        view = _later_view()
        payload = docket_payload(view, (3,), frozenset({EvidenceRole.DOCKET_LISTING}))
        assert set(payload.fields()) == {"docket_documents"}
