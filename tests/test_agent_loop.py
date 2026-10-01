"""Tests for the case loop (S3.1 Task 8): ``agent/loop.py``, ``agent/steps.py``, ``agent/trail.py``.

The loop is driven as the synchronous driver will drive it: ask for the next call, send it to a
``RecordingFakeClient`` scripted with ``ModelReply``s, and hand the reply back. Offline; no model
is called. The numbered classes are the brief's fifteen cases, in its order.
"""

import copy
import dataclasses
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from pydantic import ValidationError
from tests.test_agent_documents import CAUSE, ONE, TWO, _raw, _withheld
from tests.test_attach import _docket as small_docket

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent import loop as loop_module
from ntsb_probable_cause.agent.documents import (
    DocketView,
    answer_payload,
    docket_view,
    listing_payload,
)
from ntsb_probable_cause.agent.loop import CaseLoop, LoopConfig, PendingCall
from ntsb_probable_cause.agent.schemas import REQUIRED, TOOL_DEFINITIONS, definitions, force
from ntsb_probable_cause.agent.steps import Shelf, lists, sanitised, tool_choice, wrong_tool
from ntsb_probable_cause.agent.texts import (
    ANSWER_NOW,
    CHOOSE,
    CHOOSE_AGAIN,
    CODE_NOW,
    NO_DOCUMENTS,
    NONE_READABLE,
    ONE_CALL,
    RECORD_NOW,
    menu,
    read_summary,
    system_text,
)
from ntsb_probable_cause.agent.trail import AgentCall, LoopOutcome, ReadRecord, StepKind
from ntsb_probable_cause.docket.listing import Listing
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import LeakageError, SchemaError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import (
    ModelReply,
    RecordingFakeClient,
    ToolCall,
    Turn,
    Usage,
    cost_usd,
    tool_reply,
)
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
from ntsb_probable_cause.scoring.hypothesis import REFINEMENT_SCHEMA, Hypothesis
from ntsb_probable_cause.scoring.runner import RunSpec, prepare_case

TABLES = load_tables()
STATS = build(
    [
        PoolCase(year=2010, group="Landing", sequence=("552230",), findings=("0206304044",)),
        PoolCase(year=2012, group="Landing", sequence=("552230", "552240")),
        PoolCase(year=2016, group="Maneuvering", sequence=("452240", "452241")),
    ],
    built_from="test",
)
T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)

HYPOTHESIS: dict[str, object] = {
    "evidence_narrative": "The airplane departed the runway during the landing roll.",
    "occurrence": [
        {"phase": "552", "event": "230", "probability": 0.6},
        {"phase": "551", "event": "230", "probability": 0.2},
    ],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.7}],
    "probable_cause": "The pilot's loss of directional control during the landing roll.",
    "lay_explanation": "The plane swerved off the runway after touching down.",
    "confidence": 0.6,
    "abstain": False,
    "evidence_used": ["phase_of_flight", "weather_condition"],
}
REFINED = json.dumps({"items": [{"index": 0, "item8": "02063015"}]})
WHY = {"reason": "check the defining event", "expected_effect": "confirm the first code"}
DOCKET_ROLES = {"docket_listing", "docket_documents"}


def _hyp(**changes: object) -> str:
    return json.dumps({**HYPOTHESIS, **changes})


def _choose(decisions: dict[int, bool]) -> str:
    return json.dumps(
        {
            "decisions": [
                {"document": n, "read": read, "expected_effect": "the engine's condition"}
                for n, read in decisions.items()
            ],
            "reason": "the examination decides between the two",
        }
    )


def _usage_args(*codes: str) -> str:
    return json.dumps({**WHY, "codes": list(codes)})


def _describe(*codes: str) -> str:
    return json.dumps({**WHY, "kind": "occurrence", "codes": list(codes)})


def _suggest(group: str) -> str:
    return json.dumps({**WHY, "phase_group": group})


def _no_call(content: str = "I will record it next.") -> ModelReply:
    return ModelReply(
        content=content,
        usage=Usage(prompt_tokens=0, completion_tokens=0),
        model="f",
        response_id="f",
    )


def _refine_reply(text: str = REFINED, usage: Usage | None = None) -> ModelReply:
    return ModelReply(
        content=text,
        usage=usage or Usage(prompt_tokens=0, completion_tokens=0),
        model="f",
        response_id="f",
    )


def _config(**changes: object) -> LoopConfig:
    base = LoopConfig(
        tables=TABLES,
        stats=STATS,
        guidance=(),
        exclusions=frozenset(),
        cap_usd=1.0,
        price_variant="batch",
        run_id="run-test",
        commit=("abc1234", False),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _view(texts: dict[int, str] | None = None) -> DocketView:
    return docket_view(_raw(), small_docket(texts if texts is not None else {1: ONE, 2: TWO}))


def _drive(
    loop: CaseLoop, replies: Sequence[str | ModelReply]
) -> tuple[RecordingFakeClient, list[PendingCall]]:
    """The synchronous driver in miniature; refuses to ask for more calls than were scripted."""
    client = RecordingFakeClient(replies)
    calls: list[PendingCall] = []
    while call := loop.next_call():
        assert len(calls) < len(replies), "the loop asked for more calls than were scripted"
        sent = T0 + timedelta(seconds=10 * len(calls))
        calls.append(call)
        reply = client.complete(
            call.payload, call.settings, system=call.system, history=call.history
        )
        loop.accept(reply, sent_at=sent, returned_at=sent + timedelta(seconds=3))
    return client, calls


def _tool_turns(history: Sequence[Turn]) -> list[Turn]:
    return [turn for turn in history if turn.role == "tool"]


def _every_call_answered(history: Sequence[Turn]) -> bool:
    answered = {turn.tool_call_id for turn in history if turn.role == "tool"}
    asked = {c.call_id for turn in history if turn.role == "assistant" for c in turn.tool_calls}
    return asked <= answered


HAPPY: list[str | ModelReply] = [
    tool_reply("record_hypothesis", _hyp(), call_id="c1"),
    tool_reply("choose_documents", _choose({1: True, 2: False}), call_id="c2"),
    tool_reply("record_hypothesis", _hyp(), call_id="c3"),
    tool_reply("choose_documents", _choose({2: False}), call_id="c4"),
    tool_reply("occurrence_usage", _usage_args("552230"), call_id="c5"),
    tool_reply("suggest_codes", _suggest("Landing"), call_id="c6"),
    tool_reply("submit_answer", _hyp(), call_id="c7"),
    REFINED,
]


# --------------------------------------------------------------------------------------------
# 1. The happy path
# --------------------------------------------------------------------------------------------


class TestHappyPath:
    def test_steps_tool_choice_and_stop(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, HAPPY)
        assert [c.step for c in calls] == [
            "h0",
            "choice1",
            "h1",
            "choice2",
            "coding",
            "coding",
            "coding",
            "refine",
        ]
        assert [c.settings.tool_choice for c in calls] == [
            force("record_hypothesis"),
            force("choose_documents"),
            force("record_hypothesis"),
            force("choose_documents"),
            REQUIRED,
            REQUIRED,
            REQUIRED,
            None,
        ]
        assert all(c.settings.parallel_tool_calls is False for c in calls[:-1])
        outcome = loop.outcome
        assert outcome.stop_reason == "done"
        assert [kind for kind, _ in outcome.checkpoints] == ["h0", "h1", "answer", "refine"]
        assert outcome.read == (1,)
        assert outcome.skipped == (2,)
        assert outcome.coding_calls == 2
        assert outcome.argument_errors == 0
        assert outcome.answer is not None
        assert outcome.answer.findings[0].item8 == "02063015"
        assert loop.next_call() is None

    def test_the_read_records(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        _drive(loop, HAPPY)
        first, second = loop.outcome.reads
        assert first.step == "choice1"
        assert first.offered == (1, 2)
        assert [(d.document, d.read) for d in first.decisions] == [(1, True), (2, False)]
        assert first.reason == "the examination decides between the two"
        assert (second.step, second.offered) == ("choice2", (2,))

    def test_the_tool_results_follow_the_flow(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        view = _view()
        _, calls = _drive(loop, HAPPY)
        results = _tool_turns(calls[6].history)
        texts = [turn.tool_text.text for turn in results if turn.tool_text is not None]
        assert texts[0] == f"{menu(view.offered, view.not_readable)}\n\n{CHOOSE}"
        assert texts[1] == f"{read_summary((1,), (2,))}\n\n{RECORD_NOW}"
        rest = tuple(f for f in view.offered if f.index == 2)
        assert texts[2] == f"{menu(rest, view.not_readable, already_read=(1,))}\n\n{CHOOSE_AGAIN}"
        assert texts[3] == f"{read_summary((), (2,))}\n\n{CODE_NOW}"
        assert "present:" in texts[4]
        assert "commonest defining events in past Landing" in texts[5]
        assert results[0].payload is not None
        assert set(results[0].payload.fields()) == {"docket_listing"}
        assert results[1].payload is not None
        assert set(results[1].payload.fields()) == {"docket_documents"}
        assert all(turn.payload is None for turn in results[2:])

    def test_refinement_is_the_runners_stage_two(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, HAPPY)
        refine = calls[-1]
        answer = Hypothesis.model_validate_json(_hyp())
        assert refine.system == f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(answer, TABLES)}"
        assert refine.history == (Turn(role="assistant", content=_hyp()),)
        assert refine.settings.json_schema == REFINEMENT_SCHEMA
        assert refine.settings.schema_name == "refinement"
        assert refine.settings.tools == ()
        assert refine.settings.tool_choice is None
        assert refine.payload == answer_payload(_view(), (1,), frozenset())

    def test_settings_carry_the_run_model_and_reply_budget(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config(max_output_tokens=4000))
        _, calls = _drive(loop, HAPPY)
        for call in calls:
            assert call.settings.model == sources.DEFAULT_MODEL
            assert call.settings.price_variant == "batch"
            assert call.settings.reasoning_effort == sources.DEFAULT_REASONING_EFFORT
            assert call.settings.max_output_tokens == 4000


# --------------------------------------------------------------------------------------------
# 2. Append-only
# --------------------------------------------------------------------------------------------


class TestAppendOnly:
    def test_each_history_extends_the_one_before(self) -> None:
        _, calls = _drive(CaseLoop(_raw(), _view(), _config()), HAPPY)
        conversation = calls[:-1]
        for before, after in pairwise(conversation):
            assert after.history[: len(before.history)] == before.history
            assert len(after.history) > len(before.history)

    def test_system_and_tools_are_identical_on_every_call_and_across_cases(
        self, record_fixtures: list[dict[str, object]]
    ) -> None:
        _, first = _drive(CaseLoop(_raw(), _view(), _config()), HAPPY)
        other = next(r for r in record_fixtures if r["ntsbNumber"] != "ANC09CA024")
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        _, second = _drive(CaseLoop(other, None, _config()), replies)
        conversation = [c for c in (*first, *second) if c.step != "refine"]
        assert {c.system for c in conversation} == {system_text(TABLES, ())}
        assert all(c.settings.tools == TOOL_DEFINITIONS for c in conversation)
        assert first[0].payload != second[0].payload


# --------------------------------------------------------------------------------------------
# 3. Where titles and document text may appear
# --------------------------------------------------------------------------------------------

MARK_TITLES = {1: "Quillfeather Examination Notes", 2: "Marrowgate Statement", 3: "Tindleby Form"}
MARK_TEXTS = {
    1: "[page 1 of 3]\nThe zorbling valve was intact.\n",
    2: "[page 1 of 3]\nThe plinkett lever moved freely.\n",
}
MARKERS = (*MARK_TITLES.values(), "zorbling", "plinkett")


def _marked_view() -> DocketView:
    docket = small_docket(MARK_TEXTS)
    entries = tuple(
        e.model_copy(update={"title": MARK_TITLES[e.index]}) for e in docket.listing.entries
    )
    listing = docket.listing.model_copy(update={"entries": entries})
    return docket_view(_raw(), docket.model_copy(update={"listing": listing}))


class TestWhereTextAppears:
    def test_titles_only_in_the_listing_and_text_only_in_documents(self) -> None:
        _, calls = _drive(CaseLoop(_raw(), _marked_view(), _config()), HAPPY)
        for pending in calls:
            assert not any(marker in pending.system for marker in MARKERS)
            if pending.step == "refine":  # a request of its own, in arm B's shape (fix round 1)
                continue
            assert not DOCKET_ROLES & set(pending.payload.fields())
            assert not any(marker in pending.payload.text for marker in MARKERS)
        listing_seen = documents_seen = False
        for turn in calls[6].history:
            for call in turn.tool_calls:
                assert not any(marker in call.arguments for marker in MARKERS)
            if turn.tool_text is not None:
                assert not any(marker in turn.tool_text.text for marker in MARKERS)
            if turn.payload is None:
                continue
            roles = set(turn.payload.fields())
            if roles == {"docket_listing"}:
                listing_seen = True
                assert all(title in turn.payload.text for title in MARK_TITLES.values())
                assert "zorbling" not in turn.payload.text
            else:
                assert roles == {"docket_documents"}
                documents_seen = True
                assert "zorbling" in turn.payload.text
                assert "plinkett" not in turn.payload.text
                assert not any(title in turn.payload.text for title in MARK_TITLES.values())
        assert listing_seen
        assert documents_seen


# --------------------------------------------------------------------------------------------
# 4. Nothing offered
# --------------------------------------------------------------------------------------------


def _unlisted_view() -> DocketView:
    """A docket that lists nothing: its listing page holds no document."""
    empty = Docket(
        mkey=1, listing=Listing(mkey=1, declared_items=0, entries=()), documents=(), texts={}
    )
    return docket_view(_raw(), empty)


def _unreadable_view() -> DocketView:
    """A docket that lists three documents with marker titles, none of which can be read."""
    docket = small_docket({})
    entries = tuple(
        e.model_copy(update={"title": MARK_TITLES[e.index]}) for e in docket.listing.entries
    )
    listing = docket.listing.model_copy(update={"entries": entries})
    return docket_view(_raw(), docket.model_copy(update={"listing": listing}))


ANSWERED: list[str | ModelReply] = [
    tool_reply("record_hypothesis", _hyp(), call_id="c1"),
    tool_reply("submit_answer", _hyp(), call_id="c2"),
    REFINED,
]


class TestNothingOffered:
    @pytest.mark.parametrize("listed", [False, True])
    def test_no_docket_or_an_empty_listing_goes_from_h0_straight_to_coding(
        self, listed: bool
    ) -> None:
        loop = CaseLoop(_raw(), _unlisted_view() if listed else None, _config())
        _, calls = _drive(loop, ANSWERED)
        assert [c.step for c in calls] == ["h0", "coding", "refine"]
        (result,) = _tool_turns(calls[1].history)
        assert result.payload is None
        assert result.tool_text is not None
        assert result.tool_text.text == f"{NO_DOCUMENTS}\n\n{CODE_NOW}"
        assert {row.docket_state for row in loop.outcome.calls} == {"none"}
        assert loop.outcome.reads == ()
        assert calls[-1].payload == calls[0].payload, "the refinement shows no listing"


class TestNoneReadable:
    """Andy, 2026-10-01: a docket that lists documents none of which can be read is still shown.

    Arm B's payload always holds the listing with its titles; arm C sees the same listing at h0
    (decision 0074, equal evidence), then the menu's not-readable lines, ``NONE_READABLE`` and
    the move to coding.
    """

    def test_h0_sends_the_listing_the_unreadable_lines_and_then_coding(self) -> None:
        view = _unreadable_view()
        loop = CaseLoop(_raw(), view, _config())
        _, calls = _drive(loop, ANSWERED)
        assert [c.step for c in calls] == ["h0", "coding", "refine"]
        assert calls[1].settings.tool_choice == REQUIRED
        (result,) = _tool_turns(calls[1].history)
        assert result.payload == listing_payload(view, frozenset())
        assert set(result.payload.fields()) == {"docket_listing"}
        assert all(title in result.payload.text for title in MARK_TITLES.values())
        assert result.tool_text is not None
        assert result.tool_text.text == (
            "Not readable: [1] 3 pages\nNot readable: [2] 3 pages\nNot readable: [3] 3 pages"
            f"\n\n{NONE_READABLE}\n\n{CODE_NOW}"
        )
        menu_lines = menu((), view.not_readable)
        assert result.tool_text.text == f"{menu_lines}\n\n{NONE_READABLE}\n\n{CODE_NOW}"
        assert not any(title in result.tool_text.text for title in MARK_TITLES.values())
        assert NO_DOCUMENTS not in result.tool_text.text
        assert loop.outcome.reads == ()
        assert (loop.outcome.read, loop.outcome.skipped) == ((), ())

    def test_the_first_user_message_still_holds_no_docket_role(self) -> None:
        _, calls = _drive(CaseLoop(_raw(), _unreadable_view(), _config()), ANSWERED)
        for pending in calls[:-1]:
            assert not DOCKET_ROLES & set(pending.payload.fields())
            assert not any(title in pending.payload.text for title in MARK_TITLES.values())

    def test_the_refinement_shows_the_listing_the_agent_saw_and_no_document(self) -> None:
        view = _unreadable_view()
        _, calls = _drive(CaseLoop(_raw(), view, _config()), ANSWERED)
        refine = calls[-1]
        assert refine.step == "refine"
        assert refine.payload == answer_payload(view, (), frozenset())
        assert "docket_listing" in refine.payload.fields()
        assert "docket_documents" not in refine.payload.fields()
        assert all(title in refine.payload.text for title in MARK_TITLES.values())

    @pytest.mark.parametrize("final", [True, False])
    def test_the_docket_state_is_about_arrival_not_readability(self, final: bool) -> None:
        loop = CaseLoop(_raw(), _unreadable_view(), _config(), docket_final=final)
        _drive(loop, ANSWERED)
        assert {row.docket_state for row in loop.outcome.calls} == {"all" if final else "some"}

    def test_without_coding_the_answer_follows(self) -> None:
        view = _unreadable_view()
        loop = CaseLoop(_raw(), view, _config(without=frozenset({"coding"})))
        _, calls = _drive(loop, ANSWERED)
        assert [c.step for c in calls] == ["h0", "answer", "refine"]
        (result,) = _tool_turns(calls[1].history)
        assert result.payload == listing_payload(view, frozenset())
        assert result.tool_text is not None
        assert result.tool_text.text == (
            f"{menu((), view.not_readable)}\n\n{NONE_READABLE}\n\n{ANSWER_NOW}"
        )

    def test_the_listing_arm_c_sends_is_arm_bs_listing(self) -> None:
        """Parity (decision 0074): the listing text and the refinement equal arm B's payload."""
        view = _unreadable_view()
        _, calls = _drive(CaseLoop(_raw(), view, _config()), ANSWERED)
        (result,) = _tool_turns(calls[1].history)
        assert result.payload is not None
        arm_b = prepare_case(
            _raw(), RunSpec(sample="dev-400", arm="B"), TABLES, view.attachment.docket
        )
        assert arm_b.documents_attached == ()
        arm_c_listing = json.loads(result.payload.text)["docket_listing"]
        assert arm_c_listing == json.loads(arm_b.payload.text)["docket_listing"]
        assert calls[-1].payload == arm_b.payload

    def test_a_leak_in_the_listing_ends_the_case_after_h0(self) -> None:
        raw = _withheld(_raw())
        docket = small_docket({})
        first, *rest = docket.listing.entries
        leaky = first.model_copy(update={"title": f"Letter. {CAUSE}"})
        listing = docket.listing.model_copy(update={"entries": (leaky, *rest)})
        view = docket_view(raw, docket.model_copy(update={"listing": listing}))
        loop = CaseLoop(raw, view, _config())
        _, calls = _drive(loop, [tool_reply("record_hypothesis", _hyp())])
        assert [c.step for c in calls] == ["h0"]
        assert loop.outcome.stop_reason == "failed: leak"
        assert loop.next_call() is None


# --------------------------------------------------------------------------------------------
# 5. Choices that read nothing, and nothing left to choose
# --------------------------------------------------------------------------------------------


class TestChoiceBranches:
    def test_choice_one_reads_nothing_so_no_h1(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp(), call_id="c1"),
            tool_reply("choose_documents", _choose({1: False, 2: False}), call_id="c2"),
            tool_reply("choose_documents", _choose({1: False, 2: True}), call_id="c3"),
            tool_reply("record_hypothesis", _hyp(), call_id="c4"),
            tool_reply("submit_answer", _hyp(findings=[]), call_id="c5"),
        ]
        loop = CaseLoop(_raw(), _view(), _config())
        view = _view()
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["h0", "choice1", "choice2", "h2", "coding"]
        second_look = _tool_turns(calls[2].history)[-1]
        assert second_look.payload is None
        assert second_look.tool_text is not None
        assert second_look.tool_text.text == (
            f"{read_summary((), (1, 2))}\n\n{menu(view.offered, view.not_readable)}"
            f"\n\n{CHOOSE_AGAIN}"
        )
        assert loop.outcome.read == (2,)
        assert loop.outcome.skipped == (1,)
        assert [kind for kind, _ in loop.outcome.checkpoints] == ["h0", "h2", "answer"]

    def test_second_look_reads_nothing_so_coding_follows(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp(), call_id="c1"),
            tool_reply("choose_documents", _choose({1: False, 2: False}), call_id="c2"),
            tool_reply("choose_documents", _choose({1: False, 2: False}), call_id="c3"),
            tool_reply("submit_answer", _hyp(findings=[]), call_id="c4"),
        ]
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["h0", "choice1", "choice2", "coding"]
        last = _tool_turns(calls[3].history)[-1]
        assert last.tool_text is not None
        assert last.tool_text.text == f"{read_summary((), (1, 2))}\n\n{CODE_NOW}"
        assert loop.outcome.read == ()
        assert loop.outcome.skipped == (1, 2)

    def test_nothing_left_after_choice_one_so_no_choice_two(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp(), call_id="c1"),
            tool_reply("choose_documents", _choose({1: True, 2: True}), call_id="c2"),
            tool_reply("record_hypothesis", _hyp(), call_id="c3"),
            tool_reply("submit_answer", _hyp(findings=[]), call_id="c4"),
        ]
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["h0", "choice1", "h1", "coding"]
        last = _tool_turns(calls[3].history)[-1]
        assert last.tool_text is not None
        assert last.tool_text.text == CODE_NOW
        documents = _tool_turns(calls[2].history)[-1].payload
        assert documents is not None
        rendered = documents.fields()["docket_documents"]
        assert isinstance(rendered, list)
        assert [item.split(",")[0] for item in rendered] == ["Docket item 1", "Docket item 2"]
        assert loop.outcome.read == (1, 2)


# --------------------------------------------------------------------------------------------
# 6. Replies that break the protocol
# --------------------------------------------------------------------------------------------

BREAKS: dict[str, tuple[int, ModelReply]] = {
    "wrong tool": (0, tool_reply("choose_documents", _choose({1: True, 2: True}), call_id="x")),
    "bad arguments": (0, tool_reply("record_hypothesis", '{"evidence_narrative": 3}', call_id="x")),
    "not json": (0, tool_reply("record_hypothesis", "{not json", call_id="x")),
    "missing decision": (1, tool_reply("choose_documents", _choose({1: True}), call_id="x")),
    "unknown tool": (0, tool_reply("read_everything", "{}", call_id="x")),
}
GOOD_START: list[str | ModelReply] = [
    tool_reply("record_hypothesis", _hyp(), call_id="c1"),
    tool_reply("choose_documents", _choose({1: True, 2: True}), call_id="c2"),
    tool_reply("record_hypothesis", _hyp(), call_id="c3"),
    tool_reply("submit_answer", _hyp(findings=[]), call_id="c4"),
]


class TestProtocolBreaks:
    @pytest.mark.parametrize("kind", sorted(BREAKS))
    def test_answered_not_accepted_and_reissued_once(self, kind: str) -> None:
        at, bad = BREAKS[kind]
        replies = [*GOOD_START[:at], bad, *GOOD_START[at:]]
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, replies)
        assert calls[at + 1].step == calls[at].step
        assert calls[at + 1].settings == calls[at].settings
        answer = _tool_turns(calls[at + 1].history)[-1]
        assert answer.tool_call_id == "x"
        assert answer.tool_text is not None
        assert answer.tool_text.text.startswith("That call was not accepted: ")
        rows = loop.outcome.calls
        assert rows[at].protocol_error is not None
        assert rows[at].arguments == {}
        assert rows[at + 1].retry
        assert not any(row.retry for i, row in enumerate(rows) if i != at + 1)
        assert loop.outcome.stop_reason == "done"
        assert _every_call_answered(calls[-1].history)

    @pytest.mark.parametrize("kind", sorted(BREAKS))
    def test_a_second_break_fails_the_case_at_its_step(self, kind: str) -> None:
        at, bad = BREAKS[kind]
        again = bad.model_copy(
            update={"tool_calls": (bad.tool_calls[0].model_copy(update={"call_id": "y"}),)}
        )
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, [*GOOD_START[:at], bad, again])
        step = calls[at].step
        assert loop.outcome.stop_reason == f"failed: {step}"
        assert loop.outcome.answer is None
        assert len(loop.outcome.calls) == at + 2
        assert _every_call_answered(calls[-1].history)
        assert (loop.outcome.read, loop.outcome.skipped) == ((), ()), "nothing was decided"

    def test_no_tool_call_reissues_the_same_call(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        replies: list[str | ModelReply] = [
            _no_call(),
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        _, calls = _drive(loop, replies)
        assert calls[1] == calls[0]
        assert loop.outcome.calls[0].protocol_error == "no tool call"
        assert loop.outcome.calls[0].tool is None
        assert loop.outcome.calls[1].retry
        assert loop.outcome.stop_reason == "done"

    def test_two_replies_without_a_tool_call_fail_the_step(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        _drive(loop, [_no_call(), _no_call()])
        assert loop.outcome.stop_reason == "failed: h0"

    def test_the_wrong_tool_is_named_and_the_step_tool_given(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, [BREAKS["wrong tool"][1], *GOOD_START])
        text = _tool_turns(calls[1].history)[-1].tool_text
        assert text is not None
        assert "record_hypothesis" in text.text
        assert "not choose_documents" in text.text

    def test_an_unknown_tool_name_is_not_repeated(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, [BREAKS["unknown tool"][1], *GOOD_START])
        text = _tool_turns(calls[1].history)[-1].tool_text
        assert text is not None
        assert "read_everything" not in text.text
        assert "an unknown tool" in text.text

    def test_a_rejected_hypothesis_never_echoes_the_models_values(self) -> None:
        marker = "The pilot report says the quokka switch was off."
        extra = {f"{marker} (a field)": 1}
        bad = tool_reply("record_hypothesis", _hyp(confidence=marker, abstain=marker, **extra))
        loop = CaseLoop(_raw(), None, _config())
        _, calls = _drive(loop, [bad, *GOOD_START[:1], GOOD_START[3]])
        text = _tool_turns(calls[1].history)[-1].tool_text
        assert text is not None
        assert "quokka" not in text.text
        assert text.text == (
            "That call was not accepted: confidence: float_parsing; abstain: bool_parsing; "
            "arguments: extra_forbidden"
        )
        error = loop.outcome.calls[0].protocol_error
        assert error is not None
        assert "quokka" not in error

    def test_a_coding_tool_fault_is_a_break_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fault(*_args: object, **_kwargs: object) -> None:
            raise KeyError("552230")

        monkeypatch.setattr(loop_module, "run_coding_tool", fault)
        loop = CaseLoop(_raw(), None, _config())
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp(), call_id="c1"),
            tool_reply("occurrence_usage", _usage_args("552230"), call_id="c2"),
            tool_reply("occurrence_usage", _usage_args("552230"), call_id="c3"),
        ]
        _, calls = _drive(loop, replies)
        text = _tool_turns(calls[2].history)[-1].tool_text
        assert text is not None
        assert text.text == "That call was not accepted: the tool could not run (KeyError)"
        assert loop.outcome.stop_reason == "failed: coding"
        assert loop.outcome.coding_calls == 0


# --------------------------------------------------------------------------------------------
# 7. Two tool calls in one reply
# --------------------------------------------------------------------------------------------


class TestTwoCallsInOneReply:
    def test_the_first_runs_and_the_second_gets_one_call(self) -> None:
        both = ModelReply(
            content=None,
            tool_calls=(
                ToolCall(call_id="a", name="record_hypothesis", arguments=_hyp()),
                ToolCall(call_id="b", name="describe_codes", arguments=_describe("552230")),
            ),
            finish_reason="tool_calls",
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            model="f",
            response_id="f",
        )
        loop = CaseLoop(_raw(), None, _config())
        _, calls = _drive(loop, [both, tool_reply("submit_answer", _hyp(findings=[]))])
        assistant, first, second = calls[1].history
        assert assistant.tool_calls == both.tool_calls
        assert (first.tool_call_id, second.tool_call_id) == ("a", "b")
        assert first.tool_text is not None
        assert first.tool_text.text == f"{NO_DOCUMENTS}\n\n{CODE_NOW}"
        assert second.tool_text is not None
        assert second.tool_text.text == ONE_CALL
        row = loop.outcome.calls[0]
        assert (row.tool, row.protocol_error) == ("record_hypothesis", None)
        assert not loop.outcome.calls[1].retry
        assert loop.outcome.coding_calls == 0
        assert [kind for kind, _ in loop.outcome.checkpoints] == ["h0", "answer"]


# --------------------------------------------------------------------------------------------
# 8. The coding-call limit
# --------------------------------------------------------------------------------------------


class TestCodingLimit:
    def test_after_six_coding_calls_the_answer_is_forced(self) -> None:
        coding = [
            tool_reply("describe_codes", _describe("552230"), call_id=f"d{i}") for i in range(7)
        ]
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp(), call_id="c1"),
            *coding,
            tool_reply("submit_answer", _hyp(), call_id="c9"),
            REFINED,
        ]
        loop = CaseLoop(_raw(), None, _config())
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls[1:7]] == ["coding"] * 6
        assert all(c.settings.tool_choice == REQUIRED for c in calls[1:7])
        assert calls[7].step == "answer"
        assert calls[7].settings.tool_choice == force("submit_answer")
        assert loop.outcome.calls[7].protocol_error is not None
        assert calls[8].step == "answer"
        assert loop.outcome.calls[8].retry
        assert loop.outcome.coding_calls == 6
        assert loop.outcome.stop_reason == "done"

    def test_the_limit_is_the_configs(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("describe_codes", _describe("552230")),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        loop = CaseLoop(_raw(), None, _config(max_coding_calls=1))
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["h0", "coding", "answer"]


# --------------------------------------------------------------------------------------------
# 9. An argument error is not a protocol break
# --------------------------------------------------------------------------------------------


class TestArgumentErrors:
    def test_an_unknown_code_counts_and_the_case_goes_on(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp(), call_id="c1"),
            tool_reply("occurrence_usage", _usage_args("999999"), call_id="c2"),
            tool_reply("submit_answer", _hyp(findings=[]), call_id="c3"),
        ]
        loop = CaseLoop(_raw(), None, _config())
        _, calls = _drive(loop, replies)
        text = _tool_turns(calls[2].history)[-1].tool_text
        assert text is not None
        assert text.text == "unknown occurrence code: 999999"
        row = loop.outcome.calls[1]
        assert (row.protocol_error, row.argument_errors, row.tool) == (None, 1, "occurrence_usage")
        assert row.arguments == {**WHY, "codes": ["999999"]}
        assert not loop.outcome.calls[2].retry
        assert loop.outcome.argument_errors == 1
        assert loop.outcome.coding_calls == 1


# --------------------------------------------------------------------------------------------
# 10. The per-case cap
# --------------------------------------------------------------------------------------------


def _cap_script(cost: float, *, then: str) -> list[str | ModelReply]:
    """H0, a first coding call costing ``cost``, then ``then``, then an answer."""
    costly = Usage(prompt_tokens=0, completion_tokens=0, reported_cost_usd=cost)
    third = _hyp(findings=[]) if then == "submit_answer" else _usage_args("552230")
    return [
        tool_reply("record_hypothesis", _hyp(findings=[]), call_id="c1"),
        tool_reply("occurrence_usage", _usage_args("552230"), call_id="c2", usage=costly),
        tool_reply(then, third, call_id="c3"),
        tool_reply("submit_answer", _hyp(findings=[]), call_id="c4"),
    ]


def _second_coding_estimate(cap: float) -> float:
    """What the loop estimates for the call after the first coding call, at no cost so far."""
    script = _cap_script(0.0, then="occurrence_usage")
    _, calls = _drive(CaseLoop(_raw(), None, _config(cap_usd=cap)), script)
    assert calls[2].step == "coding"
    return calls[2].estimated_usd


class TestCap:
    def test_the_estimate_is_the_briefs_formula(self) -> None:
        call = CaseLoop(_raw(), None, _config()).next_call()
        assert call is not None
        price = sources.price_of("openai/gpt-6-luna:batch")
        tokens = (len(call.system) + len(call.payload.text) + len(json.dumps(TOOL_DEFINITIONS))) / 4
        expected = (tokens * price.input_usd_per_mtok + 8000 * price.output_usd_per_mtok) / 1e6
        assert call.estimated_usd == pytest.approx(expected)

    def test_coding_that_passes_the_cap_is_forced_to_answer(self) -> None:
        cap = 10.0
        estimate = _second_coding_estimate(cap)
        spent = cap - 1.5 * estimate
        loop = CaseLoop(_raw(), None, _config(cap_usd=cap))
        _, calls = _drive(loop, _cap_script(spent, then="submit_answer")[:3])
        assert [c.step for c in calls] == ["h0", "coding", "answer"]
        assert calls[2].settings.tool_choice == force("submit_answer")
        assert loop.outcome.stop_reason == "done"
        assert loop.outcome.cost_usd == pytest.approx(spent)

    def test_a_case_that_cannot_afford_the_answer_stops_at_the_cap(self) -> None:
        cap = 10.0
        estimate = _second_coding_estimate(cap)
        loop = CaseLoop(_raw(), None, _config(cap_usd=cap))
        _, calls = _drive(loop, _cap_script(cap - 0.5 * estimate, then="submit_answer")[:2])
        assert len(calls) == 2
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "cap"
        assert loop.outcome.answer is None

    def test_the_refinement_is_held_back_before_the_answer(self) -> None:
        """A draft with findings reserves its refinement: the same spend now stops the case."""
        cap = 10.0
        estimate = _second_coding_estimate(cap)
        script = _cap_script(cap - 1.5 * estimate, then="submit_answer")[:3]
        script[0] = tool_reply("record_hypothesis", _hyp(), call_id="c1")
        loop = CaseLoop(_raw(), None, _config(cap_usd=cap))
        _drive(loop, script[:2])
        assert loop.outcome.stop_reason == "cap"

    def test_the_refinement_held_back_counts_the_documents_read(self) -> None:
        """Arm B's refinement payload re-sends what was read; its reserve must count it."""
        big = "[page 1 of 3]\n" + "The wing spar was intact. " * 4000

        def script(cost: float) -> list[str | ModelReply]:
            costly = Usage(prompt_tokens=0, completion_tokens=0, reported_cost_usd=cost)
            return [
                tool_reply("record_hypothesis", _hyp(), call_id="c1"),
                tool_reply("choose_documents", _choose({1: True, 2: False}), call_id="c2"),
                tool_reply("record_hypothesis", _hyp(), call_id="c3"),
                tool_reply("choose_documents", _choose({2: False}), call_id="c4", usage=costly),
                tool_reply("submit_answer", _hyp(), call_id="c5"),
                REFINED,
            ]

        _, probe = _drive(CaseLoop(_raw(), _view({1: big, 2: ONE}), _config()), script(0.0))
        assert [c.step for c in probe[4:]] == ["coding", "refine"]
        answer, refinement = probe[4].estimated_usd, probe[5].estimated_usd
        price = sources.price_of("openai/gpt-6-luna:batch")
        margin = len(big) / 4 * price.input_usd_per_mtok / 1e6
        spent = 1.0 - answer - refinement + margin / 2
        loop = CaseLoop(_raw(), _view({1: big, 2: ONE}), _config())
        _, calls = _drive(loop, script(spent)[:4])
        assert len(calls) == 4
        assert loop.outcome.stop_reason == "cap"

    def test_a_refinement_the_case_cannot_afford_stops_at_the_cap(self) -> None:
        costly = Usage(prompt_tokens=0, completion_tokens=0, reported_cost_usd=0.9995)
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp(), usage=costly),
        ]
        loop = CaseLoop(_raw(), None, _config(cap_usd=1.0))
        _drive(loop, replies)
        assert loop.outcome.stop_reason == "cap"
        assert loop.outcome.answer is None
        assert [kind for kind, _ in loop.outcome.checkpoints] == ["h0", "answer"]

    def test_a_first_call_over_the_cap_stops_before_any_call(self) -> None:
        loop = CaseLoop(_raw(), None, _config(cap_usd=0.0001))
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "cap"
        assert loop.outcome.calls == ()


# --------------------------------------------------------------------------------------------
# 11. Leaks
# --------------------------------------------------------------------------------------------


class TestLeaks:
    def test_a_leak_in_a_chosen_document_ends_the_case(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: ONE, 2: f"[page 1 of 3]\nLetter.\n{CAUSE}\n"}))
        loop = CaseLoop(raw, view, _config())
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp(), call_id="c1"),
            tool_reply("choose_documents", _choose({1: False, 2: True}), call_id="c2"),
            tool_reply("record_hypothesis", _hyp(), call_id="c3"),
        ]
        client, _ = _drive(loop, replies)
        assert len(client.payloads) == 2
        assert loop.next_call() is None
        outcome = loop.outcome
        assert outcome.stop_reason == "failed: leak"
        assert len(outcome.calls) == 2
        row = outcome.calls[1]
        assert row.tool == "choose_documents"
        assert row.arguments == json.loads(_choose({1: False, 2: True}))
        assert (row.result_chars, row.protocol_error) == (0, None)
        (record,) = outcome.reads
        assert record.step == "choice1"
        assert [(d.document, d.read) for d in record.decisions] == [(1, False), (2, True)]
        assert outcome.read == (), "nothing was sent"
        assert outcome.skipped == (1,), "the document chosen to read was not skipped"

    def test_a_leak_in_the_refinement_payload_keeps_the_answer_on_its_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every part was guarded when sent; the one split for the refinement is guarded too."""

        def leak(*_args: object, **_kwargs: object) -> None:
            raise LeakageError("ANC09CA024: docket_documents holds text from probable_cause")

        monkeypatch.setattr(loop_module, "answer_payload", leak)
        loop = CaseLoop(_raw(), _view(), _config())
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({1: True, 2: False})),
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({2: False})),
            tool_reply("submit_answer", _hyp()),
            REFINED,
        ]
        client, _ = _drive(loop, replies)
        assert len(client.payloads) == 5
        assert loop.outcome.stop_reason == "failed: leak"
        row = loop.outcome.calls[4]
        assert (row.tool, row.result_chars) == ("submit_answer", 0)
        assert row.hypothesis == Hypothesis.model_validate_json(_hyp())
        assert row.arguments == row.hypothesis.model_dump(mode="json")
        assert [kind for kind, _ in loop.outcome.checkpoints] == ["h0", "h1", "answer"]
        assert loop.outcome.answer is None

    def test_a_leak_in_the_evidence_stops_before_any_call(self) -> None:
        raw = _withheld(_raw())
        narratives = raw["narratives"]
        assert isinstance(narratives, list)
        narratives[0]["prelimNarrative"] = f"Report. {CAUSE}"
        loop = CaseLoop(raw, None, _config())
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "failed: leak"
        assert loop.outcome.calls == ()
        assert loop.outcome.case_id == "ANC09CA024"

    def test_the_guards_message_is_kept_on_the_outcome(self) -> None:
        """S3.1 Task 10: arm C records a leak as arm B does, ``leak: <the guard's message>``.

        The message names the role, kind and source, never the withheld text (decision 0016).
        """
        raw = _withheld(_raw())
        evidence_leak = copy.deepcopy(raw)
        narratives = evidence_leak["narratives"]
        assert isinstance(narratives, list)
        narratives[0]["prelimNarrative"] = f"Report. {CAUSE}"
        at_start = CaseLoop(evidence_leak, None, _config())
        assert at_start.next_call() is None
        view = docket_view(raw, small_docket({1: ONE, 2: f"[page 1 of 3]\nLetter.\n{CAUSE}\n"}))
        in_a_document = CaseLoop(raw, view, _config())
        _drive(
            in_a_document,
            [
                tool_reply("record_hypothesis", _hyp()),
                tool_reply("choose_documents", _choose({1: False, 2: True})),
            ],
        )
        for loop in (at_start, in_a_document):
            leak = loop.outcome.leak
            assert leak is not None
            assert "probable_cause" in leak
            assert CAUSE not in leak
        done = CaseLoop(_raw(), _view(), _config())
        _drive(done, HAPPY)
        assert done.outcome.leak is None

    def test_a_leak_in_the_listing_ends_the_case_after_h0(self) -> None:
        raw = _withheld(_raw())
        docket = small_docket({1: ONE})
        entry = docket.listing.entries[0].model_copy(update={"title": f"Letter. {CAUSE}"})
        listing = docket.listing.model_copy(
            update={"entries": (entry, *docket.listing.entries[1:])}
        )
        view = docket_view(raw, docket.model_copy(update={"listing": listing}))
        loop = CaseLoop(raw, view, _config())
        client, _ = _drive(loop, [tool_reply("record_hypothesis", _hyp())])
        assert len(client.payloads) == 1
        assert loop.outcome.stop_reason == "failed: leak"
        (row,) = loop.outcome.calls
        assert row.hypothesis == Hypothesis.model_validate_json(_hyp())
        assert row.arguments == row.hypothesis.model_dump(mode="json")
        assert row.result_chars == 0


# --------------------------------------------------------------------------------------------
# The refinement's payload: arm B's shape (fix round 1)
# --------------------------------------------------------------------------------------------


class TestRefinementPayload:
    def test_holds_the_evidence_the_listing_and_the_documents_read(self) -> None:
        _, calls = _drive(CaseLoop(_raw(), _marked_view(), _config()), HAPPY)
        refine = calls[-1]
        assert refine.step == "refine"
        fields = refine.payload.fields()
        assert {"docket_listing", "docket_documents", "aircraft_make"} <= set(fields)
        assert "zorbling" in refine.payload.text
        assert "plinkett" not in refine.payload.text
        assert all(title in refine.payload.text for title in MARK_TITLES.values())
        assert refine.payload == answer_payload(_marked_view(), (1,), frozenset())

    def test_documents_come_in_arm_bs_order(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({1: False, 2: True})),
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({1: True})),
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp()),
            REFINED,
        ]
        loop = CaseLoop(_raw(), _view(), _config())
        _, calls = _drive(loop, replies)
        assert loop.outcome.read == (2, 1)
        assert calls[-1].payload == answer_payload(_view(), (1, 2), frozenset())

    def test_with_no_docket_it_is_the_evidence(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp()),
            REFINED,
        ]
        _, calls = _drive(CaseLoop(_raw(), None, _config()), replies)
        assert calls[-1].step == "refine"
        assert calls[-1].payload == calls[0].payload

    def test_with_nothing_read_it_holds_the_listing_only(self) -> None:
        view = _marked_view()
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({1: False, 2: False})),
            tool_reply("choose_documents", _choose({1: False, 2: False})),
            tool_reply("submit_answer", _hyp()),
            REFINED,
        ]
        _, calls = _drive(CaseLoop(_raw(), view, _config()), replies)
        fields = calls[-1].payload.fields()
        assert "docket_listing" in fields
        assert "docket_documents" not in fields
        assert calls[-1].payload == answer_payload(view, (), frozenset())

    def test_with_nothing_readable_it_holds_the_listing_the_agent_saw(self) -> None:
        """Andy, 2026-10-01: a docket listing only unreadable documents is listed at h0, so the
        refinement shows that listing, as arm B's payload does (it replaces the controller's
        narrowed ruling that such a docket is never listed)."""
        view = _unreadable_view()
        _, calls = _drive(CaseLoop(_raw(), view, _config()), ANSWERED)
        assert [c.step for c in calls] == ["h0", "coding", "refine"]
        assert calls[-1].payload == answer_payload(view, (), frozenset())
        assert all(title in calls[-1].payload.text for title in MARK_TITLES.values())
        assert set(calls[-1].payload.fields()) & DOCKET_ROLES == {"docket_listing"}

    def test_with_an_empty_listing_it_is_the_evidence(self) -> None:
        _, calls = _drive(CaseLoop(_raw(), _unlisted_view(), _config()), ANSWERED)
        assert calls[-1].step == "refine"
        assert calls[-1].payload == calls[0].payload


# --------------------------------------------------------------------------------------------
# 12. A batch item that failed
# --------------------------------------------------------------------------------------------


class TestFailedItems:
    def test_is_reissued_once_then_fails_the_case(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        first = loop.next_call()
        loop.accept(None, error="model: x", sent_at=T0, returned_at=T0, batch_id="b1")
        second = loop.next_call()
        assert second == first
        loop.accept(None, error="model: x", sent_at=T0, returned_at=T0, batch_id="b2")
        assert loop.next_call() is None
        outcome = loop.outcome
        assert outcome.stop_reason == "failed: h0"
        assert [row.retry for row in outcome.calls] == [False, True]
        assert [row.batch_id for row in outcome.calls] == ["b1", "b2"]
        assert all(row.protocol_error == "model: x" for row in outcome.calls)
        assert all(row.cost_usd == 0 and row.prompt_tokens == 0 for row in outcome.calls)

    def test_a_good_reply_after_one_failure_goes_on(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        loop.next_call()
        loop.accept(None, sent_at=T0, returned_at=T0)
        _drive(
            loop,
            [
                tool_reply("record_hypothesis", _hyp()),
                tool_reply("submit_answer", _hyp(findings=[])),
            ],
        )
        assert loop.outcome.stop_reason == "done"
        assert loop.outcome.calls[0].protocol_error == "no reply"
        assert loop.outcome.calls[1].retry


# --------------------------------------------------------------------------------------------
# 13. When refinement is skipped
# --------------------------------------------------------------------------------------------


class TestRefinementSkipped:
    @pytest.mark.parametrize(
        "answer", [_hyp(abstain=True), _hyp(findings=[])], ids=["abstains", "no findings"]
    )
    def test_no_refinement_call(self, answer: str) -> None:
        loop = CaseLoop(_raw(), None, _config())
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", answer),
        ]
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["h0", "coding"]
        assert loop.outcome.stop_reason == "done"
        assert loop.outcome.answer == Hypothesis.model_validate_json(answer)

    def test_a_bad_refinement_is_reissued_with_the_runners_rejection(self) -> None:
        marker = "quokka"
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp()),
            json.dumps({"items": [{"index": 0, "item8": marker}]}),
            REFINED,
        ]
        loop = CaseLoop(_raw(), None, _config())
        _, calls = _drive(loop, replies)
        assert calls[3].system.startswith(calls[2].system)
        assert "\n\nYour previous reply was rejected: " in calls[3].system
        assert marker not in calls[3].system
        assert calls[3].history == calls[2].history
        assert loop.outcome.stop_reason == "done"

    def test_two_bad_refinements_fail_the_case(self) -> None:
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp()),
            "not json",
            json.dumps({"items": [{"index": 5, "item8": "02063015"}]}),
        ]
        loop = CaseLoop(_raw(), None, _config())
        _drive(loop, replies)
        assert loop.outcome.stop_reason == "failed: refine"
        assert loop.outcome.answer is None


# --------------------------------------------------------------------------------------------
# 14. The trail
# --------------------------------------------------------------------------------------------


class TestTrail:
    def test_every_row_has_tokens_cost_times_commit_and_order(self) -> None:
        usage = Usage(
            prompt_tokens=1000, completion_tokens=200, cached_tokens=400, reasoning_tokens=50
        )
        replies = [
            reply.model_copy(update={"usage": usage})
            if isinstance(reply, ModelReply)
            else _refine_reply(reply, usage)
            for reply in HAPPY
        ]
        loop = CaseLoop(_raw(), _marked_view(), _config())
        _, calls = _drive(loop, replies)
        rows = loop.outcome.calls
        assert [row.call_index for row in rows] == list(range(len(HAPPY)))
        for index, (row, call) in enumerate(zip(rows, calls, strict=True)):
            assert (row.run_id, row.case_id, row.trigger) == ("run-test", "ANC09CA024", 1)
            assert (row.commit_sha, row.dirty, row.docket_state) == ("abc1234", False, "all")
            assert (row.prompt_tokens, row.completion_tokens) == (1000, 200)
            assert (row.cached_tokens, row.reasoning_tokens) == (400, 50)
            assert row.cost_usd == cost_usd(replies[index], call.settings)[0] > 0
            assert row.estimated_usd == call.estimated_usd > 0
            assert row.sent_at == T0 + timedelta(seconds=10 * index)
            assert row.returned_at == row.sent_at + timedelta(seconds=3)
            assert row.step == call.step
        assert loop.outcome.cost_usd == pytest.approx(sum(row.cost_usd for row in rows))
        assert rows[-1].tool is None
        assert rows[-1].hypothesis == loop.outcome.answer

    def test_holds_no_tool_result_text_only_its_size(self) -> None:
        loop = CaseLoop(_raw(), _marked_view(), _config())
        _, calls = _drive(loop, HAPPY)
        trail = loop.outcome.model_dump_json()
        for marker in (*MARKERS, CHOOSE, RECORD_NOW, CODE_NOW, "present:", "3 pages"):
            assert marker not in trail
        rows = loop.outcome.calls
        for index in range(6):
            turns = _tool_turns(calls[index + 1].history)[len(_tool_turns(calls[index].history)) :]
            content = [
                "\n\n".join(p.text for p in (t.payload, t.tool_text) if p is not None)
                for t in turns
            ]
            assert rows[index].result_chars == sum(len(c) for c in content) > 0
        assert rows[6].result_chars == rows[7].result_chars == 0

    def test_checkpoints_and_hypotheses(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        _drive(loop, HAPPY)
        rows = loop.outcome.calls
        assert [row.hypothesis is not None for row in rows] == [
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
        ]
        assert rows[1].tool == "choose_documents"
        assert rows[1].arguments["reason"] == "the examination decides between the two"

    def test_records_are_frozen_and_closed(self) -> None:
        record = ReadRecord(step="choice1", offered=(1,), decisions=(), reason="r")
        with pytest.raises(ValidationError):
            record.reason = "other"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            ReadRecord(step="choice1", offered=(1,), decisions=(), reason="r", extra=1)  # type: ignore[call-arg]
        for model in (AgentCall, ReadRecord, LoopOutcome):
            assert model.model_config.get("extra") == "forbid"
            assert model.model_config.get("frozen") is True


# --------------------------------------------------------------------------------------------
# 15. Ablations
# --------------------------------------------------------------------------------------------


class TestAblations:
    def test_without_suggest_codes(self) -> None:
        loop = CaseLoop(_raw(), None, _config(without=frozenset({"suggest_codes"})))
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("suggest_codes", _suggest("Landing")),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        _, calls = _drive(loop, replies)
        assert all(len(c.settings.tools) == 6 for c in calls)
        assert calls[0].settings.tools == definitions(frozenset({"suggest_codes"}))
        error = loop.outcome.calls[1].protocol_error
        assert error is not None
        assert "not suggest_codes" in error
        assert "suggest_codes or" not in error
        assert loop.outcome.calls[2].retry
        assert loop.outcome.coding_calls == 0

    def test_without_coding_forces_the_answer_after_h0(self) -> None:
        loop = CaseLoop(_raw(), None, _config(without=frozenset({"coding"})))
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("submit_answer", _hyp()),
            REFINED,
        ]
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["h0", "answer", "refine"]
        assert all(len(c.settings.tools) == 3 for c in calls[:2])
        assert calls[1].settings.tool_choice == force("submit_answer")
        (result,) = _tool_turns(calls[1].history)
        assert result.tool_text is not None
        assert result.tool_text.text == f"{NO_DOCUMENTS}\n\n{ANSWER_NOW}"

    def test_without_coding_forces_the_answer_after_the_last_hypothesis(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config(without=frozenset({"coding"})))
        replies: list[str | ModelReply] = [
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({1: True, 2: False})),
            tool_reply("record_hypothesis", _hyp()),
            tool_reply("choose_documents", _choose({2: False})),
            tool_reply("submit_answer", _hyp(findings=[])),
        ]
        _, calls = _drive(loop, replies)
        assert [c.step for c in calls] == ["h0", "choice1", "h1", "choice2", "answer"]
        last = _tool_turns(calls[4].history)[-1]
        assert last.tool_text is not None
        assert last.tool_text.text == f"{read_summary((), (2,))}\n\n{ANSWER_NOW}"


# --------------------------------------------------------------------------------------------
# Construction, the step table, idempotence and the carried resolutions
# --------------------------------------------------------------------------------------------


class TestConstruction:
    @pytest.mark.parametrize("role", [EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS])
    def test_refuses_a_view_when_a_docket_role_is_excluded(self, role: EvidenceRole) -> None:
        with pytest.raises(ValueError, match="view=None"):
            CaseLoop(_raw(), _view(), _config(exclusions=frozenset({role})))

    def test_accepts_the_same_exclusion_with_no_view(self) -> None:
        excluded = frozenset({EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS})
        loop = CaseLoop(_raw(), None, _config(exclusions=excluded))
        assert loop.next_call() is not None

    def test_config_defaults(self) -> None:
        config = _config()
        assert (config.max_output_tokens, config.max_coding_calls) == (8000, 6)
        assert (config.pass_reasoning, config.without) == (False, frozenset())
        assert config.model == sources.DEFAULT_MODEL
        assert config.reasoning_effort == sources.DEFAULT_REASONING_EFFORT

    def test_the_trigger_is_recorded(self) -> None:
        loop = CaseLoop(_raw(), None, _config(), trigger=3)
        _drive(
            loop,
            [
                tool_reply("record_hypothesis", _hyp()),
                tool_reply("submit_answer", _hyp(findings=[])),
            ],
        )
        assert {row.trigger for row in loop.outcome.calls} == {3}


class TestStepTable:
    def test_one_table_gives_each_steps_tool_choice(self) -> None:
        assert tool_choice("h0") == tool_choice("h1") == tool_choice("h2")
        assert tool_choice("h0") == force("record_hypothesis")
        assert tool_choice("choice1") == tool_choice("choice2") == force("choose_documents")
        assert tool_choice("coding") == REQUIRED
        assert tool_choice("answer") == force("submit_answer")
        assert tool_choice("refine") is None

    def test_a_wrong_tool_is_answered_with_what_the_step_takes(self) -> None:
        assert wrong_tool(("record_hypothesis",), "submit_answer") == (
            "this step takes record_hypothesis, not submit_answer"
        )
        assert wrong_tool(("describe_codes", "past_findings", "submit_answer"), "hack") == (
            "this step takes describe_codes, past_findings or submit_answer, not an unknown tool"
        )

    def test_the_listing_goes_back_at_h0_whenever_the_docket_lists_something_unread(self) -> None:
        """Andy, 2026-10-01: with a read choice to follow, or with nothing readable at all."""
        readable, scan = _view().offered[0], _view().not_readable[0]
        assert lists("h0", Shelf(rest=(readable,), not_readable=(scan,)))
        assert lists("h0", Shelf(not_readable=(scan,)))
        assert Shelf(not_readable=(scan,)).none_readable
        assert not lists("h0", Shelf())
        assert not lists("h0", Shelf(not_readable=(scan,), read=(1,))), "all read before"
        assert not Shelf(not_readable=(scan,), read=(1,)).none_readable
        assert not Shelf(rest=(readable,)).none_readable
        later_steps: tuple[StepKind, ...] = ("h1", "h2", "choice1", "coding")
        for step in later_steps:
            assert not lists(step, Shelf(rest=(readable,), not_readable=(scan,)))

    def test_sanitised_keeps_a_cause_free_message_and_hides_json(self) -> None:
        assert sanitised(SchemaError("unknown modifier '99'")) == "unknown modifier '99'"
        with pytest.raises(json.JSONDecodeError) as caught:
            json.loads("{quokka")
        error = SchemaError("reply is not a Hypothesis: {quokka")
        error.__cause__ = caught.value
        assert sanitised(error) == "not valid JSON"


class TestDriving:
    def test_next_call_is_idempotent_until_accept(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        first = loop.next_call()
        assert loop.next_call() is first

    def test_accept_with_nothing_pending_is_refused(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        with pytest.raises(RuntimeError, match="no call"):
            loop.accept(tool_reply("record_hypothesis", _hyp()), sent_at=T0, returned_at=T0)

    def test_the_outcome_waits_for_the_case_to_stop(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        with pytest.raises(RuntimeError, match="not stopped"):
            _ = loop.outcome


class TestDriverSeams:
    """What the drivers (Task 9) need from a loop: its case id, its place, and a way to stop it."""

    def test_the_case_id_is_the_ntsb_number(self) -> None:
        assert CaseLoop(_raw(), None, _config()).case_id == "ANC09CA024"

    def test_call_index_counts_every_accepted_reply_failed_ones_included(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        assert loop.call_index == 0
        assert loop.next_call() is not None
        assert loop.call_index == 0  # asking for the call does not move it
        loop.accept(None, error="boom", sent_at=T0, returned_at=T0)
        assert loop.call_index == 1
        assert loop.next_call() is not None  # the same step, re-issued
        loop.accept(tool_reply("record_hypothesis", _hyp()), sent_at=T0, returned_at=T0)
        assert loop.call_index == 2

    def test_stop_ends_a_case_with_a_call_pending_and_keeps_its_trail(self) -> None:
        loop = CaseLoop(_raw(), _view(), _config())
        assert loop.next_call() is not None
        loop.accept(tool_reply("record_hypothesis", _hyp()), sent_at=T0, returned_at=T0)
        assert loop.next_call() is not None  # choice1 is now pending
        loop.stop("failed: rounds")
        assert loop.next_call() is None
        outcome = loop.outcome
        assert outcome.stop_reason == "failed: rounds"
        assert outcome.answer is None
        assert [kind for kind, _ in outcome.checkpoints] == ["h0"]
        assert len(outcome.calls) == 1

    def test_stop_does_not_change_the_reason_of_a_case_that_has_stopped(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        _drive(
            loop,
            [
                tool_reply("record_hypothesis", _hyp()),
                tool_reply("submit_answer", _hyp(findings=[])),
            ],
        )
        loop.stop("failed: rounds")
        assert loop.outcome.stop_reason == "done"
        assert loop.next_call() is None

    def test_stop_before_the_first_call(self) -> None:
        loop = CaseLoop(_raw(), None, _config())
        loop.stop("failed: rounds")
        assert loop.next_call() is None
        assert loop.outcome.calls == ()


class TestReasoning:
    @pytest.mark.parametrize("passed", [False, True])
    def test_assistant_turns_keep_reasoning_and_settings_say_whether_it_goes_back(
        self, passed: bool
    ) -> None:
        details = ({"type": "reasoning.encrypted", "data": "opaque"},)
        first = tool_reply("record_hypothesis", _hyp()).model_copy(
            update={"reasoning_details": details}
        )
        loop = CaseLoop(_raw(), None, _config(pass_reasoning=passed))
        _, calls = _drive(loop, [first, tool_reply("submit_answer", _hyp(findings=[]))])
        assert all(c.settings.pass_reasoning is passed for c in calls)
        assert calls[1].history[0].reasoning_details == details
        with_reasoning = calls[1].estimated_usd
        plain = CaseLoop(_raw(), None, _config(pass_reasoning=passed))
        _, plain_calls = _drive(
            plain,
            [
                tool_reply("record_hypothesis", _hyp()),
                tool_reply("submit_answer", _hyp(findings=[])),
            ],
        )
        assert (with_reasoning > plain_calls[1].estimated_usd) is passed
