"""Tests for arm B's fixed tool post-pass (S3.1 Task 12): ``agent/armb.py`` and ``ntsb-eval tools``.

The source arm B run is made by ``scoring.runner.Runner`` itself, synchronously, on four fixture
records: ANC09CA024 with a two-document docket and ANC09CA020 with none (both answered and
refined), ANC09CA027 (its answer fails twice) and ANC09LA022 (it abstains). The post-pass then
runs on that folder with scripted replies, so what it sends can be compared byte for byte with
what the runner sent. Offline; no model is called.
"""

import copy
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from apps.eval.__main__ import main, resolve_latest
from tests.boundary import assert_requests_clean
from tests.conftest import load_record_fixtures
from tests.test_agent_documents import ANALYSIS, CAUSE, FACTUAL, ONE, TWO, _raw, _withheld
from tests.test_agent_drive import Clock, ScriptedClient, _answers, _ended, _KilledError, _script
from tests.test_agent_loop import (
    HYPOTHESIS,
    REFINED,
    STATS,
    T0,
    TABLES,
    _config,
    _hyp,
    _refine_reply,
)
from tests.test_agent_run import Dockets
from tests.test_attach import _docket as small_docket
from tests.test_eval_app import GOOD, REFINE, _eval_env, _factory, _StubDocketReader
from tests.test_occurrence_misses import _case
from tests.test_runner import FakeBatchClient

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent import armb
from ntsb_probable_cause.agent import loop as agent_loop
from ntsb_probable_cause.agent.armb import (
    EXPECTED_COST_PER_CASE_USD,
    FIXED,
    PAYLOAD_CHANGED,
    TOOL,
    FixedToolsLoop,
    phase_group,
    tools_id,
    tools_run,
)
from ntsb_probable_cause.agent.later import as_recorded
from ntsb_probable_cause.agent.run import GUIDANCE, TRAIL_FILE
from ntsb_probable_cause.agent.schemas import definitions, force, parse_call
from ntsb_probable_cause.agent.texts import not_accepted
from ntsb_probable_cause.agent.tools import (
    ToolResult,
    describe_codes,
    occurrence_usage,
    past_findings,
    run_coding_tool,
    suggest_codes,
)
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.listing import Listing
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import (
    BatchCancelledError,
    BudgetError,
    ConfigurationError,
)
from ntsb_probable_cause.model.batch import BatchRequest
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    RecordingFakeClient,
    Turn,
    Usage,
    tool_reply,
)
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.budget import open_reservations
from ntsb_probable_cause.scoring.coding_stats import NO_GROUP, StatsName
from ntsb_probable_cause.scoring.hypothesis import REFINEMENT_SCHEMA, Hypothesis, parse_hypothesis
from ntsb_probable_cause.scoring.metrics import score_case
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    RunRecord,
    read_jsonl,
    write_jsonl,
)
from ntsb_probable_cause.scoring.runner import Prepared, Runner, RunSpec, prepare_case

A, B, C, D = "ANC09CA024", "ANC09CA020", "ANC09CA027", "ANC09LA022"
SEEN = frozenset({"552230"})
NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
TOP3 = ["552230", "551230", "552090"]
THREE = Hypothesis.model_validate(
    {
        **HYPOTHESIS,
        "occurrence": [
            {"phase": "552", "event": "230", "probability": 0.5},
            {"phase": "551", "event": "230", "probability": 0.2},
            {"phase": "552", "event": "090", "probability": 0.1},
        ],
    }
)
# The forced answer for A puts 551230 first: the source's answer (552230 first) is right on top-1
# for ANC09CA024, this one is not, so a derived score that changed shows it was re-scored.
FORCED = _hyp(
    occurrence=[
        {"phase": "551", "event": "230", "probability": 0.5},
        {"phase": "552", "event": "230", "probability": 0.3},
    ]
)
NAMES = ["describe_codes", "occurrence_usage", "past_findings", "suggest_codes"]
WITHHELD = [
    ("factual narrative", FACTUAL),
    ("analysis narrative", ANALYSIS),
    ("probable cause", CAUSE),
]


def _fixture(case_id: str) -> dict[str, object]:
    return copy.deepcopy(next(r for r in load_record_fixtures() if r["ntsbNumber"] == case_id))


RAWS = tuple(_fixture(c) for c in (A, B, C, D))


def _mkey(raw: Mapping[str, object]) -> int:
    mkey = raw["mKey"]
    assert isinstance(mkey, int)
    return mkey


def _dockets(raws: Sequence[Mapping[str, object]] = RAWS, a: Docket | None = None) -> Dockets:
    """The first case's docket holds two documents (``a`` replaces it); the others hold none."""
    by_mkey = {_mkey(raw): small_docket({}) for raw in raws}
    by_mkey[_mkey(raws[0])] = a if a is not None else small_docket({1: ONE, 2: TWO})
    return Dockets(by_mkey)


SOURCE_REPLIES: list[str | ModelReply] = [
    _hyp(),
    REFINED,
    _hyp(),
    REFINED,
    "not json",  # C's answer fails, and its retry
    "not json",
    _hyp(abstain=True, findings=[]),  # D abstains: no refinement
]
SOURCE_USAGE = [Usage(prompt_tokens=2000, completion_tokens=30, reported_cost_usd=0.5)]


def _source(
    runs: Path,
    *,
    raws: Sequence[dict[str, object]] = RAWS,
    replies: Sequence[str | ModelReply] = tuple(SOURCE_REPLIES),
    docket: Dockets | None = None,
) -> tuple[Path, RecordingFakeClient]:
    """A finished arm B run on dev-400, as the runner writes it, at a fixed clock and commit."""
    client = RecordingFakeClient(replies, usage=SOURCE_USAGE)
    runner = Runner(
        client,
        batch=None,
        tables=TABLES,
        seen_pairs=SEEN,
        runs_dir=runs,
        ledger_path=runs.parent / "ledger.md",
        month_spent_usd=0.0,
        commit=("abc1234", False),
        now=lambda: NOW,
        docket=docket if docket is not None else _dockets(raws),
    )
    spec = RunSpec(
        sample="dev-400",
        arm="B",
        sync=True,
        price_variant="standard",
        guidance=GUIDANCE,
        expected_cost_per_case_usd=0.01,
    )
    record = runner.run(spec, raws)
    return runs / record.run_id, client


def _costed(text: str, cost: float) -> ModelReply:
    return _refine_reply(
        text, Usage(prompt_tokens=1000, completion_tokens=10, reported_cost_usd=cost)
    )


def _submit(arguments: str, cost: float = 0.0, call_id: str = "s1") -> ModelReply:
    usage = Usage(
        prompt_tokens=1500, completion_tokens=40, reported_cost_usd=cost, reasoning_tokens=5
    )
    return tool_reply("submit_answer", arguments, call_id=call_id, usage=usage)


# The post-pass's replies, as drive_sync asks for them: A's two calls, then B's.
POST: list[str | ModelReply] = [
    _submit(FORCED, 0.001),
    _costed(REFINED, 0.002),
    _submit(_hyp(), 0.003, call_id="s2"),
    _costed(REFINED, 0.004),
]
POST_COST = 0.001 + 0.002 + 0.003 + 0.004


def _post(  # noqa: PLR0913 -- every parameter is a seam a test needs.
    runs: Path,
    source: Path,
    *,
    client: ModelClient | None = None,
    batch: FakeBatchClient | None = None,
    sync: bool = True,
    docket: Dockets | None = None,
    raws: Sequence[dict[str, object]] = RAWS,
    budget: float = 40.0,
    stats_name: StatsName = "s3",
) -> RunRecord:
    return tools_run(
        source,
        {str(raw["ntsbNumber"]): raw for raw in raws},
        client=client if client is not None else RecordingFakeClient(POST),
        batch=batch,
        docket=docket if docket is not None else _dockets(raws),
        tables=TABLES,
        stats=STATS,
        stats_name=stats_name,
        seen_pairs=SEEN,
        runs_dir=runs,
        budget_usd=budget,
        commit=("def5678", True),
        sync=sync,
        now=Clock(),
    )


def _cases(folder: Path) -> dict[str, CaseResult]:
    return {c.case_id: c for c in read_jsonl(folder / "cases.jsonl", CaseResult)}


def _record(folder: Path) -> RunRecord:
    (record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    return record


def _arm_b(raw: dict[str, object] | None = None) -> Prepared:
    """Arm B's payload and system for one case, as the runner prepares them."""
    spec = RunSpec(sample="dev-400", arm="B", guidance=GUIDANCE)
    return prepare_case(raw or _raw(), spec, TABLES, small_docket({1: ONE, 2: TWO}))


def _loop(
    answer: Hypothesis = THREE,
    group: str | None = "Landing",
    *,
    prepared: Prepared | None = None,
    **changes: object,
) -> FixedToolsLoop:
    arm_b = prepared if prepared is not None else _arm_b()
    return FixedToolsLoop(
        _raw(), arm_b.payload, arm_b.system, answer, as_recorded(answer), group, _config(**changes)
    )


def _drive(loop: FixedToolsLoop, replies: Sequence[str | ModelReply]) -> RecordingFakeClient:
    """The synchronous driver in miniature; refuses to ask for more calls than were scripted."""
    client = RecordingFakeClient(replies)
    while call := loop.next_call():
        assert len(client.payloads) < len(replies), "more calls than were scripted"
        reply = client.complete(
            call.payload, call.settings, system=call.system, history=call.history
        )
        loop.accept(reply, sent_at=NOW, returned_at=NOW)
    return client


def _requests(client: RecordingFakeClient) -> list[BatchRequest]:
    return [
        BatchRequest(custom_id=f"sync-{n}", payload=p, settings=s, system=y, history=h)
        for n, (p, s, y, h) in enumerate(
            zip(client.payloads, client.settings, client.systems, client.histories, strict=True)
        )
    ]


# --------------------------------------------------------------------------------------------
# The loop: the pipeline's own turn, then the forced answer and the refinement
# --------------------------------------------------------------------------------------------


class TestTheFixedTurn:
    def test_it_holds_exactly_the_four_calls_in_order_on_the_answers_top_three(self) -> None:
        call = _loop().next_call()
        assert call is not None
        turn = call.history[0]
        assert turn.role == "assistant"
        assert turn.content == as_recorded(THREE)  # the first answer, in the tool's own shape
        assert [c.name for c in turn.tool_calls] == NAMES
        why = {"reason": FIXED, "expected_effect": FIXED}
        assert [json.loads(c.arguments) for c in turn.tool_calls] == [
            {**why, "kind": "occurrence", "codes": TOP3},
            {**why, "codes": TOP3},
            {**why, "occurrence": "552230"},
            {**why, "phase_group": "Landing"},
        ]
        assert FIXED == "fixed pipeline"
        for c in turn.tool_calls:  # each is a call the agent itself could have made
            parse_call(c.name, c.arguments, TABLES)

    def test_every_call_is_answered_by_its_tools_own_text_in_order(self) -> None:
        call = _loop().next_call()
        assert call is not None
        turn, *results = call.history
        assert [r.role for r in results] == ["tool"] * 4
        assert [r.tool_call_id for r in results] == [c.call_id for c in turn.tool_calls]
        assert len({c.call_id for c in turn.tool_calls}) == 4
        assert all(r.payload is None for r in results)  # codes and counts only
        texts = [r.tool_text.text for r in results if r.tool_text is not None]
        assert texts == [
            describe_codes(TABLES, "occurrence", TOP3).text,
            occurrence_usage(TABLES, STATS, TOP3).text,
            past_findings(TABLES, STATS, "552230").text,
            suggest_codes(TABLES, STATS, "Landing").text,
        ]

    def test_an_answer_with_one_code_gets_it_alone(self) -> None:
        one = Hypothesis.model_validate(HYPOTHESIS).model_copy(
            update={"occurrence": THREE.occurrence[:1]}
        )
        call = _loop(one).next_call()
        assert call is not None
        arguments = [json.loads(c.arguments) for c in call.history[0].tool_calls]
        assert [a.get("codes") for a in arguments[:2]] == [["552230"], ["552230"]]
        assert arguments[2]["occurrence"] == "552230"

    @pytest.mark.parametrize("group", [None, NO_GROUP, "Hovering"])
    def test_a_case_with_no_phase_group_makes_no_suggest_codes_call(
        self, group: str | None
    ) -> None:
        call = _loop(group=group).next_call()
        assert call is not None
        turn = call.history[0]
        assert [c.name for c in turn.tool_calls] == NAMES[:3]
        assert len(call.history) == 4  # three calls, three results

    def test_suggest_codes_is_called_on_the_cases_own_group(self) -> None:
        call = _loop(group="Takeoff").next_call()
        assert call is not None
        suggest = call.history[0].tool_calls[3]
        assert json.loads(suggest.arguments)["phase_group"] == "Takeoff"
        assert call.history[4].tool_text is not None
        assert call.history[4].tool_text.text == suggest_codes(TABLES, STATS, "Takeoff").text

    def test_the_phase_group_is_the_evidence_value_when_the_statistics_know_it(self) -> None:
        assert phase_group("Landing") == "Landing"
        assert phase_group("UncontrolledDescent") == "UncontrolledDescent"
        assert phase_group(None) == NO_GROUP
        assert phase_group("Hovering") == NO_GROUP

    def test_the_calls_are_recorded_with_their_result_sizes(self) -> None:
        loop = _loop()
        assert [(c.tool, c.argument_errors) for c in loop.fixed_calls] == [(n, 0) for n in NAMES]
        call = loop.next_call()
        assert call is not None
        sizes = [len(r.tool_text.text) for r in call.history[1:] if r.tool_text is not None]
        assert [c.result_chars for c in loop.fixed_calls] == sizes
        assert loop.fixed_calls[0].arguments == json.loads(call.history[0].tool_calls[0].arguments)
        assert loop.fixed_calls[0].record() == {
            "tool": "describe_codes",
            "arguments": loop.fixed_calls[0].arguments,
            "result_chars": sizes[0],
            "argument_errors": 0,
        }

    def test_a_tools_argument_errors_are_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(armb, "run_coding_tool", lambda *_a, **_k: ToolResult("odd", 2))
        loop = _loop()
        _drive(loop, [_submit(_hyp(abstain=True, findings=[]))])
        assert loop.outcome.argument_errors == 8
        assert loop.outcome.coding_calls == 4


class TestTheForcedAnswer:
    def test_it_is_forced_with_every_tool_defined_and_one_call_at_a_time(self) -> None:
        arm_b = _arm_b()
        loop = _loop(prepared=arm_b, price_variant="standard")
        call = loop.next_call()
        assert call is not None
        assert call.step == "answer"
        assert call.payload == arm_b.payload
        assert call.system == arm_b.system
        assert call.settings.tools == definitions()
        assert call.settings.tool_choice == force("submit_answer")
        assert call.settings.parallel_tool_calls is False
        assert call.settings.json_schema is None
        assert call.settings.price_variant == "standard"
        assert (call.settings.reasoning_effort, call.settings.max_output_tokens) == ("medium", 8000)
        assert loop.next_call() is call  # idempotent until accepted

    def test_the_refinement_is_the_runners_stage_two_on_the_forced_answer(self) -> None:
        arm_b = _arm_b()
        loop = _loop(prepared=arm_b)
        client = _drive(loop, [_submit(FORCED), REFINED])
        answer = parse_hypothesis(FORCED, TABLES)
        assert client.payloads[1] == arm_b.payload
        assert client.systems[1] == (
            f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(answer, TABLES)}"
        )
        assert client.histories[1] == (Turn(role="assistant", content=FORCED),)
        assert client.settings[1].json_schema == REFINEMENT_SCHEMA
        assert client.settings[1].schema_name == "refinement"
        assert (client.settings[1].tools, client.settings[1].tool_choice) == ((), None)
        outcome = loop.outcome
        assert outcome.stop_reason == "done"
        assert outcome.answer is not None
        assert outcome.answer.findings[0].item8 == "02063015"
        assert [kind for kind, _ in outcome.checkpoints] == ["answer", "refine"]
        assert outcome.checkpoints[0][1] == answer

    def test_an_answer_that_abstains_or_has_no_findings_is_not_refined(self) -> None:
        for arguments in (_hyp(abstain=True, findings=[]), _hyp(findings=[])):
            loop = _loop()
            client = _drive(loop, [_submit(arguments)])
            assert len(client.payloads) == 1
            assert loop.outcome.stop_reason == "done"
            assert loop.outcome.answer == parse_hypothesis(arguments, TABLES)

    def test_each_model_call_is_one_trail_row(self) -> None:
        loop = _loop()
        _drive(loop, [_submit(_hyp(), 0.003), _costed(REFINED, 0.002)])
        calls = loop.outcome.calls
        assert [(c.call_index, c.step, c.retry, c.tool) for c in calls] == [
            (0, "answer", False, "submit_answer"),
            (1, "refine", False, None),
        ]
        assert {(c.trigger, c.docket_state, c.run_id) for c in calls} == {(1, "all", "run-test")}
        assert calls[0].hypothesis == parse_hypothesis(_hyp(), TABLES)
        assert calls[0].arguments == parse_hypothesis(_hyp(), TABLES).model_dump(mode="json")
        assert calls[1].hypothesis == loop.outcome.answer
        assert [c.cost_usd for c in calls] == pytest.approx([0.003, 0.002])
        assert loop.outcome.cost_usd == pytest.approx(0.005)
        assert all(c.estimated_usd > 0 for c in calls)
        assert {(c.commit_sha, c.dirty) for c in calls} == {("abc1234", False)}
        assert (loop.outcome.coding_calls, loop.outcome.argument_errors) == (4, 0)
        assert (loop.outcome.reads, loop.outcome.read, loop.outcome.skipped) == ((), (), ())

    def test_the_docket_state_is_all_when_arm_b_attached_no_document_but_listed_some(self) -> None:
        """Arrival, not readability (spec §9; Andy, 2026-10-01), as arm C records it."""
        spec = RunSpec(sample="dev-400", arm="B", guidance=GUIDANCE)
        bare = prepare_case(_raw(), spec, TABLES, small_docket({}))
        assert "docket_listing" in bare.payload.fields()
        assert "docket_documents" not in bare.payload.fields()
        loop = _loop(prepared=bare)
        _drive(loop, [_submit(_hyp(findings=[]))])
        assert {c.docket_state for c in loop.outcome.calls} == {"all"}

    def test_the_docket_state_is_none_when_the_docket_lists_nothing(self) -> None:
        spec = RunSpec(sample="dev-400", arm="B", guidance=GUIDANCE)
        empty = Docket(
            mkey=1, listing=Listing(mkey=1, declared_items=0, entries=()), documents=(), texts={}
        )
        bare = prepare_case(_raw(), spec, TABLES, empty)
        assert "docket_listing" not in bare.payload.fields()
        loop = _loop(prepared=bare)
        _drive(loop, [_submit(_hyp(findings=[]))])
        assert {c.docket_state for c in loop.outcome.calls} == {"none"}


class TestProtocolBreaks:
    def test_a_reply_with_no_tool_call_is_sent_again_unchanged_then_fails(self) -> None:
        loop = _loop()
        silent = ModelReply(
            content="thinking",
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            model="f",
            response_id="f",
        )
        client = _drive(loop, [silent, silent])
        assert client.histories[0] == client.histories[1]
        assert loop.outcome.stop_reason == "failed: answer"
        assert [(c.retry, c.protocol_error) for c in loop.outcome.calls] == [
            (False, "no tool call"),
            (True, "no tool call"),
        ]

    def test_a_wrong_tool_is_answered_with_why_and_the_answer_retried_once(self) -> None:
        loop = _loop()
        wrong = tool_reply("describe_codes", json.dumps({"x": 1}), call_id="w1")
        client = _drive(loop, [wrong, _submit(_hyp(findings=[]))])
        assert loop.outcome.stop_reason == "done"
        history = client.histories[1]
        assert history[:5] == client.histories[0]
        assistant, result = history[5:]
        assert assistant.tool_calls == wrong.tool_calls
        assert result.tool_call_id == "w1"
        refusal = "this step takes submit_answer, not describe_codes"
        assert result.tool_text is not None
        assert result.tool_text.text == not_accepted(refusal)
        first, second = loop.outcome.calls
        assert (first.tool, first.protocol_error, first.retry) == ("describe_codes", refusal, False)
        assert first.result_chars == len(not_accepted(refusal))
        assert (second.retry, second.protocol_error) == (True, None)

    def test_an_answer_the_tables_refuse_fails_after_one_retry_and_says_why(self) -> None:
        loop = _loop()
        bad = _hyp(occurrence=[{"phase": "999", "event": "999", "probability": 0.5}])
        _drive(loop, [_submit(bad), _submit(bad)])
        assert loop.outcome.stop_reason == "failed: answer"
        assert loop.outcome.answer is None
        errors = [c.protocol_error for c in loop.outcome.calls]
        assert errors == ["unknown phase prefix '999'"] * 2

    def test_a_refinement_that_fails_twice_fails_the_case_and_names_the_rejection(self) -> None:
        loop = _loop()
        client = _drive(loop, [_submit(_hyp()), "nope", "nope"])
        assert loop.outcome.stop_reason == "failed: refine"
        assert loop.outcome.answer is None
        assert "Your previous reply was rejected: not valid JSON" in client.systems[2]
        assert "rejected" not in client.systems[1]

    def test_an_answer_asked_twice_leaves_the_refinement_its_own_retry(self) -> None:
        loop = _loop()
        silent = ModelReply(
            content=None,
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            model="f",
            response_id="f",
        )
        _drive(loop, [silent, _submit(_hyp()), "nope", REFINED])
        assert loop.outcome.stop_reason == "done"
        assert [(c.step, c.retry) for c in loop.outcome.calls] == [
            ("answer", False),
            ("answer", True),
            ("refine", False),
            ("refine", True),
        ]

    def test_a_failed_call_is_issued_again_once(self) -> None:
        loop = _loop()
        for _ in range(2):
            call = loop.next_call()
            assert call is not None
            loop.accept(None, error="boom", sent_at=NOW, returned_at=NOW)
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "failed: answer"
        assert [c.protocol_error for c in loop.outcome.calls] == ["boom", "boom"]
        assert loop.outcome.cost_usd == 0.0


class TestCapAndDriverSeams:
    def test_a_case_that_cannot_afford_its_answer_and_refinement_stops_at_the_cap(self) -> None:
        loop = _loop(cap_usd=1e-6)
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "cap"
        assert loop.outcome.calls == ()

    def test_the_answers_call_holds_room_for_the_refinement(self) -> None:
        answer_only = _loop().next_call()
        assert answer_only is not None
        loop = _loop(cap_usd=answer_only.estimated_usd * 1.01)  # the answer fits, not both
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "cap"
        no_findings = THREE.model_copy(update={"findings": ()})
        nothing_held = _loop(no_findings, cap_usd=answer_only.estimated_usd * 1.01)
        assert nothing_held.next_call() is not None  # no refinement to hold room for

    def test_a_refinement_the_case_can_no_longer_afford_stops_at_the_cap(self) -> None:
        """The room held before the answer is the first answer's refinement; the forced answer is
        the same answer here, so the room held is exactly what the refinement then needs."""
        first = parse_hypothesis(_hyp(), TABLES)
        probe = _loop(first)
        answer = probe.next_call()
        assert answer is not None
        probe.accept(_submit(as_recorded(first)), sent_at=NOW, returned_at=NOW)
        refinement = probe.next_call()
        assert refinement is not None
        loop = _loop(first, cap_usd=answer.estimated_usd + refinement.estimated_usd)
        _drive(loop, [_submit(as_recorded(first), cost=answer.estimated_usd * 1.5)])
        assert loop.outcome.stop_reason == "cap"
        assert loop.outcome.answer is None
        assert [c.step for c in loop.outcome.calls] == ["answer"]

    def test_stop_drops_the_pending_call_and_keeps_the_first_reason(self) -> None:
        loop = _loop()
        assert loop.case_id == A
        assert loop.call_index == 0
        with pytest.raises(RuntimeError, match="has not stopped"):
            _ = loop.outcome
        with pytest.raises(RuntimeError, match="no call pending"):
            loop.accept(None, sent_at=NOW, returned_at=NOW)
        assert loop.next_call() is not None
        loop.stop("aborted: x")
        loop.stop("later")
        assert loop.next_call() is None
        assert loop.outcome.stop_reason == "aborted: x"

    def test_the_call_index_counts_the_replies_taken(self) -> None:
        loop = _loop()
        _drive(loop, [_submit(_hyp()), REFINED])
        assert loop.call_index == 2


# --------------------------------------------------------------------------------------------
# The post-pass over a finished run
# --------------------------------------------------------------------------------------------


class TestTheDerivedRun:
    def test_a_sync_post_pass_writes_the_derived_runs_files_and_record(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        record = _post(runs, source, budget=39.5)
        folder = runs / record.run_id
        assert record.run_id == tools_id(source.name) == f"{source.name}-tools"
        assert record.started == T0 + timedelta(seconds=1)  # the clock's first reading
        assert record.budget_usd == 39.5
        for name in ("cases.jsonl", TRAIL_FILE, "run.jsonl", "replies.jsonl"):
            assert (folder / name).is_file(), name
        assert not (folder / "rounds.jsonl").exists()
        assert _record(folder) == record
        original = _record(source)
        assert (record.arm, record.sample, record.evidence_version) == ("B", "dev-400", "v1")
        assert record.prompt_version == f"{original.prompt_version}+tools-s3"
        assert (record.guidance, record.guidance_sha256) == (
            original.guidance,
            original.guidance_sha256,
        )
        assert (record.model, record.cap_usd) == (original.model, original.cap_usd)
        assert record.price_variant == "standard"
        assert (record.commit_sha, record.dirty) == ("def5678", True)  # the post-pass's, not
        assert (original.commit_sha, original.dirty) == ("abc1234", False)  # the source's
        assert record.finished is not None
        assert record.cases == 4
        assert (record.batch_ids, record.reported_batch_cost_usd) == ((), None)
        assert record.cost_usd == pytest.approx(POST_COST)  # its own cost, not the source's
        assert original.cost_usd == pytest.approx(3.5)

    def test_unscored_and_abstaining_source_cases_are_copied_through_unchanged(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        record = _post(runs, source)
        before, after = _cases(source), _cases(runs / record.run_id)
        assert list(after) == [A, B, C, D]
        failure = before[C].failure
        assert failure is not None
        assert failure.startswith("schema:")
        assert after[C] == before[C]
        assert before[D].steps[-1].hypothesis.abstain
        assert after[D] == before[D]

    def test_an_answered_case_gains_one_step_and_is_scored_on_the_forced_answer(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        record = _post(runs, source)
        before, after = _cases(source)[A], _cases(runs / record.run_id)[A]
        assert after.steps[:-1] == before.steps
        step = after.steps[-1]
        assert (step.tool, step.step, step.arm) == (TOOL, before.steps[-1].step + 1, "B")
        assert TOOL == "fixed_tools"
        answer = parse_hypothesis(FORCED, TABLES)
        assert step.hypothesis.occurrence == answer.occurrence
        assert step.hypothesis.findings[0].item8 == "02063015"
        _, _, verdict = split_record(RAWS[0])
        assert after.scores == score_case(step.hypothesis, verdict, TABLES, seen_pairs=SEEN)
        assert before.scores is not None
        assert after.scores is not None
        assert (before.scores.occurrence_top1, after.scores.occurrence_top1) == (True, False)
        assert after.failure is None
        calls = step.arguments["calls"]
        assert isinstance(calls, list)
        assert [c["tool"] for c in calls] == NAMES
        assert (step.reason, step.expected_effect, step.stop_reason) == (FIXED, FIXED, "answered")
        assert step.payload_fingerprint == before.steps[0].payload_fingerprint
        assert step.documents_attached == before.steps[0].documents_attached
        assert step.returned_roles == before.steps[0].returned_roles
        assert (step.commit_sha, step.price_variant) == ("def5678", "standard")
        assert step.cost_usd == pytest.approx(0.003)
        assert step.cumulative_cost_usd == pytest.approx(
            before.steps[-1].cumulative_cost_usd + 0.003
        )
        assert after.cost_usd == pytest.approx(before.cost_usd + 0.003)
        assert after.reply_completion_tokens == (*before.reply_completion_tokens, 40, 10)
        assert after.reply_reasoning_tokens == (*before.reply_reasoning_tokens, 5, None)
        assert after.reply_finish_reasons == (*before.reply_finish_reasons, "tool_calls", None)
        assert step.reply_completion_tokens == (40, 10)
        assert (step.reply_reasoning_tokens, step.reply_finish_reasons) == (
            (5, None),
            ("tool_calls", None),
        )
        assert (step.prompt_tokens, step.completion_tokens, step.reasoning_tokens) == (2500, 50, 5)
        assert (step.not_available, step.documents_not_read) == (
            before.steps[0].not_available,
            before.steps[0].documents_not_read,
        )
        assert (step.model, step.dirty) == ("openai/gpt-6-luna", True)

    def test_the_trail_holds_every_post_pass_call(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        record = _post(runs, source)
        trail = read_jsonl(runs / record.run_id / TRAIL_FILE, AgentCall)
        assert [(c.case_id, c.call_index, c.step) for c in trail] == [
            (A, 0, "answer"),
            (A, 1, "refine"),
            (B, 0, "answer"),
            (B, 1, "refine"),
        ]
        assert {c.run_id for c in trail} == {record.run_id}
        assert {(c.commit_sha, c.dirty, c.batch_id) for c in trail} == {("def5678", True, None)}
        # B's docket lists three unreadable documents: arm B attached none, but the listing
        # arrived, so its state is "all" (arrival, not readability; Andy, 2026-10-01).
        assert [c.docket_state for c in trail] == ["all", "all", "all", "all"]

    def test_the_payload_and_system_are_the_ones_the_runner_sent(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, runner_client = _source(runs)
        client = RecordingFakeClient([_submit(_hyp()), REFINED, _submit(_hyp()), REFINED])
        _post(runs, source, client=client)
        # Calls 0-1 are A's (answer, refinement), 2-3 are B's, in both runs.
        for n in range(4):
            assert client.payloads[n].text == runner_client.payloads[n].text, n
        assert "crankshaft" in client.payloads[0].text  # A's documents are in it
        a_answer = _cases(source)[A].steps[-1].hypothesis
        assert client.histories[0][0].content == as_recorded(a_answer)  # the source's answer
        assert client.systems[0] == runner_client.systems[0]
        assert client.systems[2] == runner_client.systems[2]
        assert prompt.guidance_block(GUIDANCE).strip() in client.systems[0]
        # The refinement is exactly the runner's stage 2 for the same answer.
        for n in (1, 3):
            assert client.systems[n] == runner_client.systems[n]
            assert client.histories[n] == runner_client.histories[n]
            assert client.settings[n] == runner_client.settings[n]

    def test_the_calls_carry_the_source_runs_model_reasoning_reply_budget_and_cap(
        self, tmp_path: Path
    ) -> None:
        """The rebuilt spec is the source's (it decides the payload), and so are the calls."""
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        settings = {
            "model": "openai/gpt-5.6-luna",
            "reasoning_effort": "low",
            "max_output_tokens": 4000,
            "price_variant": "batch",
            "cap_usd": 0.07,
        }
        variant = _variant(source, "20261001T000001-abc1234-dev-400-B", **settings)
        pre = armb.preflight(variant, runs)
        assert pre.spec == RunSpec(
            sample="dev-400",
            arm="B",
            model="openai/gpt-5.6-luna",
            reasoning_effort="low",
            max_output_tokens=4000,
            price_variant="batch",
            cap_usd=0.07,
            guidance=GUIDANCE,
        )
        assert pre.run_id == tools_id(variant.name)
        client = RecordingFakeClient(POST)
        record = _post(runs, variant, client=client)
        assert {(s.model, s.reasoning_effort, s.max_output_tokens) for s in client.settings} == {
            ("openai/gpt-5.6-luna", "low", 4000)
        }
        assert {s.price_variant for s in client.settings} == {"standard"}  # a sync post-pass
        assert record.cap_usd == 0.07
        after = _cases(runs / record.run_id)
        assert (after[A].failure, after[B].failure) == (None, None)  # both payloads unchanged

    @pytest.mark.parametrize("passed", [False, True])
    def test_run_arm_c_reads_the_one_pass_reasoning_setting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passed: bool
    ) -> None:
        """The post-pass's half of ``tests/test_eval_app.py``'s test of the same name: arm B's
        calls pass reasoning back exactly when ``loop.PASS_REASONING`` (arm C's setting) says."""
        assert agent_loop.PASS_REASONING is False  # until the shape probe's check 4 says
        monkeypatch.setattr(agent_loop, "PASS_REASONING", passed)
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        client = RecordingFakeClient(POST)
        _post(runs, source, client=client)
        assert {s.pass_reasoning for s in client.settings} == {passed}

    def test_a_forced_answer_that_abstains_is_scored_as_an_abstention(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        client = RecordingFakeClient([*POST[:2], _submit(_hyp(abstain=True, findings=[]))])
        record = _post(runs, source, client=client)
        b = _cases(runs / record.run_id)[B]
        assert b.steps[-1].stop_reason == "abstained"
        assert b.scores is not None
        assert b.scores.abstained
        assert len(client.payloads) == 3  # no refinement for B

    def test_a_document_the_source_run_left_out_at_the_cap_is_left_out_again(
        self, tmp_path: Path
    ) -> None:
        """The rebuilt payload is the source's, so its documents not read are too."""
        runs = tmp_path / "runs"
        big = f"[page 1 of 3]\n{'The cylinder was scored. ' * 40_000}\n"
        dockets = _dockets(a=small_docket({1: ONE, 2: big}))
        source, _ = _source(runs, docket=dockets)
        before = _cases(source)[A]
        assert before.steps[0].documents_not_read == (f"2: cap, {len(big) // 4} tokens",)
        record = _post(runs, source, docket=dockets)
        after = _cases(runs / record.run_id)[A]
        assert after.failure is None  # the same payload: at the batch price both would fit
        step = after.steps[-1]
        assert step.tool == TOOL
        assert step.documents_not_read == before.steps[0].documents_not_read
        assert step.documents_attached == before.steps[0].documents_attached

    def test_a_sample_the_s3_pool_leaves_out_is_not_refused(self, tmp_path: Path) -> None:
        """S2.7's pool holds dev-seal-s3-400; S3's does not, and the post-pass counts in S3's."""
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        run_id = "20261001T000001-abc1234-dev-seal-s3-400-B"
        variant = _variant(source, run_id, sample="dev-seal-s3-400")
        assert armb.preflight(variant, runs).spec.sample == "dev-seal-s3-400"

    def test_the_source_runs_cap_binds_the_post_pass_calls(self, tmp_path: Path) -> None:
        """At a cap no call fits, B (no documents, so its payload is unchanged) stops at the cap
        before any call; A's payload loses its documents to that cap, so it is not the one sent."""
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        variant = _variant(source, "20261001T000001-abc1234-dev-400-B", cap_usd=1e-6)
        client = ScriptedClient([])
        record = _post(runs, variant, client=client)
        after = _cases(runs / record.run_id)
        assert client.calls == 0
        assert (after[A].failure, after[B].failure) == (PAYLOAD_CHANGED, "cap")

    def test_a_docket_changed_since_the_source_run_fails_the_case_before_any_call(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        client = RecordingFakeClient([_submit(_hyp(), 0.003), _costed(REFINED, 0.004)])
        record = _post(runs, source, client=client, docket=_dockets(a=small_docket({1: ONE})))
        before, after = _cases(source), _cases(runs / record.run_id)
        assert len(client.payloads) == 2  # B's calls only
        assert after[A] == before[A].model_copy(update={"scores": None, "failure": PAYLOAD_CHANGED})
        assert PAYLOAD_CHANGED.startswith("payload: ")
        assert after[B].failure is None
        assert record.cost_usd == pytest.approx(0.007)

    def test_a_leak_found_while_preparing_fails_that_case_only(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        raws = (_withheld(RAWS[0]), *RAWS[1:])
        leaky = small_docket({1: ONE, 2: f"[page 1 of 3]\nLetter.\n{CAUSE}\n"})
        client = RecordingFakeClient([_submit(_hyp()), REFINED])
        record = _post(runs, source, client=client, raws=raws, docket=_dockets(raws, a=leaky))
        after = _cases(runs / record.run_id)
        failure = after[A].failure
        assert failure is not None
        assert failure.startswith("leak: ")
        assert CAUSE not in failure
        assert after[A].scores is None
        assert after[B].failure is None
        assert len(client.payloads) == 2

    def test_a_failed_post_pass_keeps_the_source_steps_and_adds_its_spend(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        client = RecordingFakeClient(
            [_submit(_hyp(), 0.001), _costed("nope", 0.002), _costed("nope", 0.004), *POST[2:]]
        )
        record = _post(runs, source, client=client)
        before, after = _cases(source)[A], _cases(runs / record.run_id)[A]
        assert (after.failure, after.scores, after.steps) == ("failed: refine", None, before.steps)
        assert after.cost_usd == pytest.approx(before.cost_usd + 0.007)
        assert after.reply_completion_tokens == (*before.reply_completion_tokens, 40, 10, 10)
        assert record.cost_usd == pytest.approx(0.007 + 0.003 + 0.004)

    def test_a_source_with_no_answered_case_makes_no_call(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        raws = (RAWS[2], RAWS[3])
        source, _ = _source(runs, raws=raws, replies=SOURCE_REPLIES[4:])
        client = ScriptedClient([])
        record = _post(runs, source, client=client, raws=raws, docket=_dockets(raws))
        assert client.calls == 0
        assert (record.cases, record.cost_usd, record.finished is not None) == (2, 0.0, True)


# --------------------------------------------------------------------------------------------
# Refusals, before anything is reserved or written
# --------------------------------------------------------------------------------------------


def _variant(source: Path, run_id: str, **changes: object) -> Path:
    """A copy of the source run under another id, its record changed."""
    folder = source.parent / run_id
    folder.mkdir()
    (folder / "cases.jsonl").write_text((source / "cases.jsonl").read_text())
    write_jsonl(
        folder / "run.jsonl", [_record(source).model_copy(update={"run_id": run_id, **changes})]
    )
    return folder


def _assert_refused(runs: Path, source: Path, match: str, **post: object) -> None:
    client = ScriptedClient([])
    before = {p.name for p in runs.iterdir()}
    with pytest.raises(ConfigurationError, match=match):
        _post(runs, source, client=client, **post)  # type: ignore[arg-type]
    assert client.calls == 0
    assert {p.name for p in runs.iterdir()} == before  # no derived folder
    assert open_reservations(runs) == {}


class TestRefusals:
    @pytest.mark.parametrize(
        ("suffix", "changes", "match"),
        [
            ("heldout-400-B", {"sample": "heldout-400"}, "development"),
            ("dev-400-A", {"arm": "A"}, "development"),
            ("dev-400-B-unfinished", {"finished": None}, "finished"),
            ("dev-400-B-check-luna", {}, "stacked"),
            ("dev-400-B-tools", {}, "tools post-pass"),
            ("dev-400-B-excl", {"exclusions": ("phase_of_flight",)}, "ablation"),
            ("dev-400-B-incl", {"includes": ("case_number",)}, "ablation"),
            ("dev-400-B-v2", {"evidence_version": "v2"}, "v1"),
            ("dev-40-B", {"sample": "dev-40"}, "statistics"),
            ("dev-400-B-price", {"price_variant": "sync"}, "price variant"),
            ("dev-400-B-effort", {"reasoning_effort": "lots"}, "reasoning"),
        ],
    )
    def test_a_source_that_is_not_a_plain_finished_development_arm_b_run_is_refused(
        self, tmp_path: Path, suffix: str, changes: dict[str, object], match: str
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        variant = _variant(source, f"20261001T000000-abc1234-{suffix}", **changes)
        _assert_refused(runs, variant, match)

    def test_the_sample_s27_used_once_is_refused_before_any_docket_is_read(
        self, tmp_path: Path
    ) -> None:
        """dev-seal-400 was used once (decision 0095); its registration being committed, and S3's
        pool leaving it out, do not open it again."""
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        variant = _variant(source, "20261001T000000-abc1234-dev-seal-400-B", sample="dev-seal-400")
        dockets = _dockets()
        _assert_refused(runs, variant, "dev-seal-400.*decision 0095", docket=dockets)
        assert dockets.reads == []

    def test_a_derived_folder_that_exists_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        (runs / tools_id(source.name)).mkdir()
        _assert_refused(runs, source, "exists")

    def test_a_missing_source_folder_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        runs.mkdir()
        _assert_refused(runs, runs / "no-such-run", "no-such-run")

    def test_a_v2_docket_reader_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        reader = _dockets()
        reader.version = "v2"
        _assert_refused(runs, source, "v1", docket=reader)

    def test_a_batch_post_pass_with_no_batch_client_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        _assert_refused(runs, source, "batch client", sync=False)

    def test_a_missing_record_for_an_answered_case_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        _assert_refused(runs, source, f"no record for {B}", raws=(RAWS[0], RAWS[2], RAWS[3]))

    def test_a_record_with_no_mkey_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        keyless = copy.deepcopy(RAWS[0])
        del keyless["mKey"]
        raws = (keyless, *RAWS[1:])
        _assert_refused(runs, source, f"{A}: no mKey", raws=raws, docket=_dockets())

    def test_a_record_of_another_case_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        client = ScriptedClient([])
        swapped = {A: RAWS[1], B: RAWS[0], C: RAWS[2], D: RAWS[3]}
        with pytest.raises(ConfigurationError, match=f"the record given for {A} is {B}"):
            tools_run(
                source,
                swapped,
                client=client,
                batch=None,
                docket=_dockets(),
                tables=TABLES,
                stats=STATS,
                stats_name="s3",
                seen_pairs=SEEN,
                runs_dir=runs,
                budget_usd=40.0,
                commit=("d", False),
                sync=True,
            )
        assert client.calls == 0

    def test_statistics_other_than_s3s_are_refused_before_any_docket_is_read(
        self, tmp_path: Path
    ) -> None:
        """Decision 0129 item 4: the post-pass's tools count in S3's file, and the derived run's
        ``+tools-<name>`` names the file passed in; another name is refused, not relabelled."""
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        dockets = _dockets()
        _assert_refused(runs, source, "S3's statistics", stats_name="s27", docket=dockets)
        assert dockets.reads == []

    @pytest.mark.parametrize(
        "guidance",
        [(), ("r3-loc-stall",), ("r6-aircraft-control", "r3-loc-stall")],
    )
    def test_a_source_with_other_guidance_than_s3s_is_refused(
        self, tmp_path: Path, guidance: tuple[str, ...]
    ) -> None:
        """Spec §7.1 part 1: arm B's pipeline starts from S2.7's answer with the two kept
        guidance files, in their order; any other source is refused before any docket is read."""
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        variant = _variant(
            source,
            "20261001T000000-abc1234-dev-400-B",
            guidance=guidance,
            guidance_sha256=prompt.guidance_sha256(guidance),
        )
        dockets = _dockets()
        _assert_refused(runs, variant, "S3's guidance", docket=dockets)
        assert dockets.reads == []


# --------------------------------------------------------------------------------------------
# Budget, aborts, batch rounds and the cancelled batch
# --------------------------------------------------------------------------------------------


class _WatchingClient(RecordingFakeClient):
    """Answers as scripted, and looks at the open reservations on every call."""

    def __init__(self, replies: Sequence[str | ModelReply], runs_dir: Path) -> None:
        super().__init__(replies)
        self.runs_dir = runs_dir
        self.seen: list[dict[str, float]] = []

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        self.seen.append(open_reservations(self.runs_dir))
        return super().complete(payload, settings, system=system, history=history)


class TestBudget:
    def test_four_tenths_of_a_cent_a_case_is_reserved_during_the_pass_and_settled_after(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        client = _WatchingClient(POST, runs)
        record = _post(runs, source, client=client)
        assert EXPECTED_COST_PER_CASE_USD == 0.004
        assert len(client.seen) == 4
        assert all(seen == {record.run_id: pytest.approx(4 * 0.004)} for seen in client.seen)
        assert open_reservations(runs) == {}

    def test_an_over_budget_post_pass_is_refused_before_any_call_or_folder(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)  # it spent $3.50 this month
        client = ScriptedClient([])
        with pytest.raises(BudgetError, match="exceeds"):
            _post(runs, source, client=client, budget=3.51)
        assert client.calls == 0
        assert not (runs / tools_id(source.name)).exists()
        assert open_reservations(runs) == {}

    def test_a_post_pass_that_dies_writes_its_spend_and_settles(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        replies = _script([tool_reply("submit_answer", _hyp()), REFINED])
        client = ScriptedClient(replies, die_at=2)
        with pytest.raises(_KilledError):
            _post(runs, source, client=client)
        folder = runs / tools_id(source.name)
        record = _record(folder)
        assert record.finished is None
        assert record.cost_usd == pytest.approx(0.0011)  # the answer was paid for
        after = _cases(folder)
        assert (after[A].failure, after[B].failure) == ("aborted: ", "aborted: ")
        assert after[C] == _cases(source)[C]
        assert open_reservations(runs) == {}


def _batch_scripts() -> dict[str, list[ModelReply | None]]:
    return {
        A: _script([tool_reply("submit_answer", FORCED), REFINED]),
        B: _script([tool_reply("submit_answer", _hyp()), REFINED]),
    }


class TestBatch:
    def test_a_batch_post_pass_writes_the_same_cases_as_a_sync_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        runs = tmp_path / "batch"
        source, _ = _source(runs)
        fake = FakeBatchClient(handlers=[_answers(_batch_scripts())] * 2)
        capsys.readouterr()
        record = _post(runs, source, client=ScriptedClient([]), batch=fake, sync=False)
        captured = capsys.readouterr()
        assert captured.out == ""
        lines = captured.err.splitlines()
        assert len(lines) == 5
        assert f"tools {record.run_id} source={source.name}" in lines[0]
        assert "cases=4 answered=2" in lines[0]
        assert "stats=s3" in lines[0]
        assert "round 1 sent b1: 2 calls; 2 cases running" in lines[1]
        assert "round 2 completed b2: cost $0.5000; 0 cases running" in lines[4]
        for text in (A, B, C, D, "crankshaft"):
            assert text not in captured.err  # counts and ids of batches only
        assert record.batch_ids == ("b1", "b2")
        assert record.reported_batch_cost_usd == pytest.approx(1.0)
        assert record.cost_usd == pytest.approx(2 * (0.0011 + 0.0022))
        assert record.price_variant == "batch"
        assert [len(batch) for batch in fake.submitted] == [2, 2]
        assert {r.settings.price_variant for batch in fake.submitted for r in batch} == {"batch"}
        trail = read_jsonl(runs / record.run_id / TRAIL_FILE, AgentCall)
        assert [(c.batch_id, c.cached_tokens) for c in trail] == [
            ("b1", 500),
            ("b2", 501),
            ("b1", 500),
            ("b2", 501),
        ]
        sync_runs = tmp_path / "sync"
        sync_source, _ = _source(sync_runs)
        sync_record = _post(sync_runs, sync_source)
        batch_cases = _cases(runs / record.run_id)
        sync_cases = _cases(sync_runs / sync_record.run_id)
        assert [(c.scores, c.failure) for c in batch_cases.values()] == [
            (c.scores, c.failure) for c in sync_cases.values()
        ]

    def test_a_dead_round_is_counted_in_the_cost_and_the_batch_ids(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        fake = FakeBatchClient(
            handlers=[_ended("expired", cost=0.125), *[_answers(_batch_scripts())] * 2]
        )
        record = _post(runs, source, client=ScriptedClient([]), batch=fake, sync=False)
        assert record.batch_ids == ("b1", "b2", "b3")
        assert record.cost_usd == pytest.approx(2 * (0.0011 + 0.0022) + 0.125)

    def test_a_cancelled_batch_writes_the_records_settles_and_says_what_to_do(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        source, _ = _source(runs)
        fake = FakeBatchClient(
            handlers=[_answers(_batch_scripts()), _ended("cancelled", cost=0.0625)]
        )
        with pytest.raises(BatchCancelledError) as caught:
            _post(runs, source, client=ScriptedClient([]), batch=fake, sync=False)
        run_id = tools_id(source.name)
        message = str(caught.value)
        assert f"batch b2 of {run_id} was cancelled" in message
        assert "not resumed" in message
        for case_id in (A, B, C, D):
            assert case_id not in message
        record = _record(runs / run_id)
        assert record.finished is None
        assert record.batch_ids == ("b1", "b2")
        assert record.cost_usd == pytest.approx(2 * 0.0011 + 0.0625)
        assert {c.failure for c in _cases(runs / run_id).values() if c.case_id in (A, B)} == {
            f"aborted: {caught.value.__cause__}"
        }
        assert open_reservations(runs) == {}


class TestBoundary:
    def _requests(self, tmp_path: Path) -> list[BatchRequest]:
        runs = tmp_path / "runs"
        raws = (_withheld(RAWS[0]), *RAWS[1:])
        source, _ = _source(runs, raws=raws)
        fake = FakeBatchClient(handlers=[_answers(_batch_scripts())] * 2)
        _post(runs, source, client=ScriptedClient([]), batch=fake, sync=False, raws=raws)
        return [request for batch in fake.submitted for request in batch]

    def test_no_withheld_text_reaches_any_request(self, tmp_path: Path) -> None:
        requests = self._requests(tmp_path)
        assert any(r.history and r.history[0].tool_calls for r in requests)
        assert_requests_clean(requests, WITHHELD)

    def test_the_check_reads_the_fixed_turns_calls_and_results(self, tmp_path: Path) -> None:
        """The check can fail on what the post-pass adds: its tool calls and its tool texts."""
        requests = self._requests(tmp_path)
        with pytest.raises(AssertionError, match="tool call"):
            assert_requests_clean(requests, [("marker", FIXED)])
        with pytest.raises(AssertionError, match="tool text"):
            assert_requests_clean(requests, [("marker", "The five commonest defining events")])

    def test_the_check_fails_on_withheld_text_in_a_tool_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation test: a tool text that carried the probable cause must be caught."""

        def leaky(*args: object, **kwargs: object) -> ToolResult:
            result = run_coding_tool(*args, **kwargs)  # type: ignore[arg-type]
            return ToolResult(f"{result.text}\n{CAUSE}", result.argument_errors)

        monkeypatch.setattr(armb, "run_coding_tool", leaky)
        with pytest.raises(AssertionError, match=r"^tripwire: probable cause .* tool text"):
            assert_requests_clean(self._requests(tmp_path), WITHHELD)


# --------------------------------------------------------------------------------------------
# The command: ntsb-eval tools, then check on its derived run
# --------------------------------------------------------------------------------------------


def _tools_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> tuple[str, Path]:
    monkeypatch.setattr("apps.eval.__main__.CachedDocketReader", _StubDocketReader)
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
    _, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    argv = ["run", "--arm", "B", "--sample", "dev-400", "--sync", "--price-variant", "standard"]
    argv += [flag for name in GUIDANCE for flag in ("--guidance", name)]  # S3's (spec §7.1)
    assert main(argv, client_factory=_factory(RecordingFakeClient([GOOD, REFINE]))) == 0
    (source,) = [p.name for p in runs_dir.iterdir() if p.is_dir()]
    return source, runs_dir


class TestCommand:
    def test_tools_then_check_gives_arm_bs_full_pipeline(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_fixtures: list[dict[str, object]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, runs = _tools_env(tmp_path, monkeypatch, record_fixtures)
        client = RecordingFakeClient([tool_reply("submit_answer", GOOD), REFINE])
        capsys.readouterr()
        assert main(["tools", source, "--sync"], client_factory=_factory(client)) == 0
        derived = tools_id(source)
        assert f"tools {derived}: 1 cases, $" in capsys.readouterr().out
        assert len(client.payloads) == 2
        assert "crankshaft" in client.payloads[0].text  # the stubbed docket, read again
        (case,) = _cases(runs / derived).values()
        assert case.steps[-1].tool == TOOL

        # The tools counted in S3's statistics, so the check must too (decision 0129 item 4):
        # S2.7's default is refused before anything is written, named or not.
        for flags in ([], ["--stats", "s27"]):
            assert main(["check", derived, "--way", "rule", *flags]) == 1
            assert "--stats s3, not s27" in capsys.readouterr().err
            assert not (runs / f"{derived}-check-rule").exists()
        assert main(["check", derived, "--way", "rule", "--stats", "s3"]) == 0
        checked = runs / f"{derived}-check-rule"
        (case,) = _cases(checked).values()
        assert [s.tool for s in case.steps][-2:] == [TOOL, "ordering_check"]
        # Both post-passes name the statistics they counted in.
        assert _record(checked).prompt_version.endswith("+tools-s3+check-rule-s3")

        assert main(["check", f"{derived}-check-rule", "--way", "rule", "--stats", "s3"]) == 1
        assert "stacked" in capsys.readouterr().err

        def boom(_settings: object) -> tuple[ModelClient, None]:
            raise AssertionError("no client may be built for a refused post-pass")

        for run_id, words in [
            (f"{derived}-check-rule", "stacked"),
            (derived, "tools post-pass"),
            (source, "exists"),  # run once per source run
        ]:
            assert main(["tools", run_id, "--sync"], client_factory=boom) == 1
            assert words in capsys.readouterr().err
        # The source reads S3's guidance, so --latest takes none of the folders: not the source
        # (a guided run is not arm B's plain run), and no derived run stands in for it.
        with pytest.raises(SystemExit, match="no completed run found"):
            resolve_latest(runs, "B", "dev-400")

    def test_tools_runs_in_batch_by_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_fixtures: list[dict[str, object]],
    ) -> None:
        source, runs = _tools_env(tmp_path, monkeypatch, record_fixtures)
        case_id = str(record_fixtures[0]["ntsbNumber"])
        scripts = {case_id: _script([tool_reply("submit_answer", GOOD), REFINE])}
        fake = FakeBatchClient(handlers=[_answers(scripts)] * 2)
        assert main(["tools", source], client_factory=_factory(ScriptedClient([]), fake)) == 0
        assert len(fake.submitted) == 2
        assert _record(runs / tools_id(source)).batch_ids == ("b1", "b2")

    def test_tools_over_budget_exits_one_line_and_holds_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_fixtures: list[dict[str, object]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, runs = _tools_env(tmp_path, monkeypatch, record_fixtures)
        client = ScriptedClient([])
        argv = ["tools", source, "--sync", "--budget-usd", "0.00001"]
        assert main(argv, client_factory=_factory(client)) == 1
        err = capsys.readouterr().err
        assert "tools:" in err
        assert "budget" in err
        assert "Traceback" not in err
        assert client.calls == 0
        assert open_reservations(runs) == {}
        assert not (runs / tools_id(source)).exists()

    @pytest.mark.parametrize(
        ("sample", "match"),
        [("heldout-400", "development"), ("dev-seal-s3-400", "sealed")],
    )
    def test_tools_refuses_before_any_client_is_built(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        sample: str,
        match: str,
    ) -> None:
        runs = tmp_path / "runs"
        monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
        run_id = f"20260926T000000-abc1234-{sample}-B"
        when = datetime(2026, 9, 26, tzinfo=UTC)
        record = RunRecord(
            run_id=run_id,
            sample=sample,
            arm="B",
            exclusions=(),
            includes=(),
            prompt_version="s1-v6",
            guidance=GUIDANCE,  # S3's, so the refusal tested is the sample's own
            model="openai/gpt-6-luna",
            price_variant="batch",
            cap_usd=0.05,
            budget_usd=40.0,
            commit_sha="abc1234",
            dirty=False,
            started=when,
            finished=when,
            cases=1,
        )
        write_jsonl(runs / run_id / "run.jsonl", [record])
        write_jsonl(runs / run_id / "cases.jsonl", [_case("c1", ("552240",), ("552241",))])

        def boom(_settings: object) -> tuple[ModelClient, None]:
            raise AssertionError("no client may be built for a refused post-pass")

        assert main(["tools", run_id], client_factory=boom) == 1
        assert match in capsys.readouterr().err


def test_resolve_latest_skips_a_real_tools_post_pass_by_its_record(tmp_path: Path) -> None:
    """A derived run records arm B, the sample and its source's prompt, with ``+tools-s3``.

    The post-pass runs on S3's guidance only (spec §7.1), so the guidance rule alone would skip
    its derived run. Here both records are made unguided after the pass, so no guidance rule can
    tell them apart. Moved under a newer name the glob ``*-<sample>-<arm>`` takes, with its
    record's id made to match, only the ``+tools-`` in its prompt version tells the derived run
    apart, and it is still skipped.
    """
    runs = tmp_path / "runs"
    raws = (RAWS[1],)
    source, _ = _source(runs, raws=raws, replies=[_hyp(), REFINED])
    client = RecordingFakeClient([_submit(_hyp()), REFINED])
    derived = _post(runs, source, client=client, raws=raws, docket=_dockets(raws))
    assert derived.finished is not None
    unguided: dict[str, object] = {"guidance": (), "guidance_sha256": None}
    plain = _record(source).model_copy(update=unguided)
    (source / "run.jsonl").write_text(plain.model_dump_json() + "\n")  # an unguided arm B run
    assert resolve_latest(runs, "B", "dev-400") == source.name
    moved = runs / "20261001T090001-abc1234-dev-400-B"  # newer, and the glob's shape
    (runs / derived.run_id).rename(moved)
    assert resolve_latest(runs, "B", "dev-400") == source.name  # its record names another id
    (moved / "run.jsonl").write_text(
        derived.model_copy(update={"run_id": moved.name, **unguided}).model_dump_json() + "\n"
    )
    assert resolve_latest(runs, "B", "dev-400") == source.name  # its prompt says +tools-s3


def test_the_makefile_target_checks_the_stage_line_then_runs_the_post_pass() -> None:
    text = Path("Makefile").read_text()
    block = text.split("\ns3-armb-tools:\n", 1)[1].split("\n\n", 1)[0]
    recipe = [line.strip() for line in block.splitlines() if line.startswith("\t")]
    assert recipe[1:] == [
        "uv run python -m scripts.stage_spend --stage s3 --estimate 0.80",
        "uv run ntsb-eval tools $(RUN)",
    ]
    assert recipe[0].startswith("$(if $(RUN),,$(error RUN is required")
