"""Arm B's fixed tool post-pass: every coding tool on its own top three, then one more answer.

S3.1 Task 12; spec §7.1; decision 0127. Arm B is the fixed pipeline the loop (arm C) must beat at
equal cost, in four parts: S2.7's answer (a finished arm B run, unchanged), every coding tool on
that answer's top three, one more answer with their results, and S2.7's ordering check. This
module is parts 2 and 3. It runs as a post-pass over the finished run, as the ordering check does
(decision 0096), so part 1 stays byte for byte S2.7's answer. Part 4 is then
``ntsb-eval check <run id>-tools --way luna --stats s3``.

Each scored, non-abstaining case gets arm B's own conversation: its system text and its payload,
rebuilt by ``runner.prepare_case`` and checked against the fingerprint the source run recorded.
Then comes one assistant turn the pipeline writes, not the model: the first answer as its content,
and the coding tools called in a fixed order, each answered by its tool's text:

1. ``describe_codes`` on the answer's occurrence codes (its top three);
2. ``occurrence_usage`` on the same codes, which counts their pairs too;
3. ``past_findings`` on its first code;
4. ``suggest_codes`` on the case's phase-of-flight group, read from its evidence. A case with no
   group the statistics know (``NO_GROUP``) gets no ``suggest_codes`` call: the tool's schema
   takes only the groups (an agent could not make that call either), and S3's pool holds no case
   without a group, so the call could only say there are none.

Every call's ``reason`` and ``expected_effect`` read ``fixed pipeline``. One model call then forces
``submit_answer`` (``parallel_tool_calls`` off), and the refinement follows, exactly the runner's
stage 2. ``FixedToolsLoop`` has the interface the drivers use (``agent/drive.py``), so a post-pass
runs synchronously or in batch rounds, as arm C does, and logs its rounds as arm C does.

The derived run ``<run id>-tools`` holds ``cases.jsonl`` (each answered case's steps are the
source's plus one ``fixed_tools`` step; every other case is copied through unchanged),
``trail.jsonl`` (one ``AgentCall`` per model call; the pipeline's own calls are in the step's
arguments, with their result sizes), the drivers' files, and ``run.jsonl``: arm B, the source's
prompt version with ``+tools-s3`` (the S3 statistics file the tools counted in, decision 0129) and
``+p`` with the agent's text fingerprint (decision 0133), and the post-pass's own cost. A post-pass
is run once per source run and is not resumed.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, cast, get_args

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent import loop as agent_loop
from ntsb_probable_cause.agent.drive import drive_batch, drive_sync
from ntsb_probable_cause.agent.later import as_recorded
from ntsb_probable_cause.agent.loop import LoopConfig, PendingCall, answer_turns, estimate_usd
from ntsb_probable_cause.agent.run import (
    GUIDANCE,
    MAX_ROUNDS,
    STATS,
    TRAIL_FILE,
    USED_ONCE,
    log_line,
    round_costs,
    round_line,
)
from ntsb_probable_cause.agent.schemas import (
    PHASE_GROUPS,
    CodingToolName,
    definitions,
    force,
    parse_call,
)
from ntsb_probable_cause.agent.steps import sanitised, wrong_tool
from ntsb_probable_cause.agent.texts import not_accepted, text_mark
from ntsb_probable_cause.agent.tools import run_coding_tool
from ntsb_probable_cause.agent.trail import AgentCall, DocketState, LoopOutcome, StepKind
from ntsb_probable_cause.errors import (
    BatchCancelledError,
    ConfigurationError,
    LeakageError,
    SchemaError,
)
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    ToolCall,
    Turn,
    Usage,
    cost_usd,
)
from ntsb_probable_cause.model.tool_text import ToolText
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.budget import reserve_within_budget, settle
from ntsb_probable_cause.scoring.checkpass import _refuse_unless_development
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import (
    NO_GROUP,
    CodingStats,
    StatsName,
    refuse_pool_holding,
)
from ntsb_probable_cause.scoring.hypothesis import (
    REFINEMENT_SCHEMA,
    Hypothesis,
    parse_hypothesis,
    parse_refinement,
)
from ntsb_probable_cause.scoring.metrics import score_case
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    RunRecord,
    StepRecord,
    fingerprint,
    read_jsonl,
    write_jsonl,
)
from ntsb_probable_cause.scoring.runner import (
    RUN_FILE,
    BatchRunner,
    DocketReader,
    Prepared,
    RunSpec,
    prepare_case,
)

# The budget guard's projection per case (the plan's Task 12): two calls on arm B's payload at
# GPT-6 Luna's batch price, rounded up. Reserved for every case of the source run.
EXPECTED_COST_PER_CASE_USD: Final = 0.004
# The derived step's tool, and what every fixed call gives as its reason and expected effect.
TOOL: Final = "fixed_tools"
FIXED: Final = "fixed pipeline"
# A case whose rebuilt payload is not the one the source run sent (its docket, or the code that
# renders it, changed since): it fails before any call, since its answer was made on other text.
PAYLOAD_CHANGED: Final = (
    "payload: not the source run's payload (its fingerprint differs; the docket or the code "
    "changed since the source run)"
)
_SUFFIX: Final = "-tools"
_CALL_ID: Final = "fixed"
_CASES_FILE: Final = "cases.jsonl"
_FORCED: Final = "submit_answer"
_PRICES: Final = ("batch", "standard")
_NO_USAGE: Final = Usage(prompt_tokens=0, completion_tokens=0)
_SHOWN: Final = 5  # case ids a refusal names before it counts the rest


def tools_id(run_id: str) -> str:
    """The derived run's id: the source run's, then ``-tools``."""
    return f"{run_id}{_SUFFIX}"


def phase_group(value: str | None) -> str:
    """The group ``suggest_codes`` is called on: the evidence value, if the statistics know it.

    Args:
        value: the case's ``phase_of_flight`` evidence value, from ``split_record``.

    Returns:
        ``value`` when it is one of ``PHASE_GROUPS``, else ``NO_GROUP``.
    """
    if value is not None and value in PHASE_GROUPS:
        return value
    return NO_GROUP


def in_post_pass(case: CaseResult) -> bool:
    """Whether the post-pass answers a source case again: scored, stepped, not abstaining.

    The ordering check's rule (``checkpass.check_run``); every other case is copied through.
    """
    return case.scores is not None and bool(case.steps) and not case.steps[-1].hypothesis.abstain


@dataclass(frozen=True)
class FixedCall:
    """One call of the pipeline's own turn: the tool, its arguments, and what its result held.

    Attributes:
        tool: the coding tool.
        arguments: the call's arguments, as parsed.
        result_chars: the characters of the tool's text sent back.
        argument_errors: the argument errors the tool counted.
    """

    tool: CodingToolName
    arguments: dict[str, object]
    result_chars: int
    argument_errors: int

    def record(self) -> dict[str, object]:
        """The call as the derived step's arguments list it."""
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "result_chars": self.result_chars,
            "argument_errors": self.argument_errors,
        }


@dataclass(frozen=True)
class _Seen:
    """What the loop made of one reply: the parts of its trail row the reply decides."""

    tool: str | None = None
    arguments: dict[str, object] | None = None
    protocol_error: str | None = None
    result_chars: int = 0
    hypothesis: Hypothesis | None = None


def _requests(answer: Hypothesis, group: str | None) -> list[tuple[CodingToolName, str]]:
    """The fixed calls, in order, as the tool name and the arguments' JSON."""
    codes = [g.phase + g.event for g in answer.occurrence][:3]
    why: dict[str, object] = {"reason": FIXED, "expected_effect": FIXED}
    calls: list[tuple[CodingToolName, dict[str, object]]] = [
        ("describe_codes", {**why, "kind": "occurrence", "codes": codes}),
        ("occurrence_usage", {**why, "codes": codes}),
        ("past_findings", {**why, "occurrence": codes[0]}),
    ]
    if group in PHASE_GROUPS:
        calls.append(("suggest_codes", {**why, "phase_group": group}))
    return [(name, json.dumps(arguments)) for name, arguments in calls]


class FixedToolsLoop:
    """One case's arm B post-pass, as a state machine of model calls and their replies.

    The interface the drivers use (``next_call``, ``accept``, ``case_id``, ``call_index``,
    ``stop``) and ``outcome``, as ``CaseLoop`` has them. The pipeline's own turn is built here:
    every call is parsed as the agent's would be (``parse_call``) and run through the agent's
    tools (``run_coding_tool``). A tool's fault raises here, before any call is made.

    Args:
        raw: the case record; only its NTSB number is read.
        payload: arm B's payload for the case (``runner.prepare_case``).
        system: arm B's system text for the case (the same call).
        first_answer: the source run's final answer for the case.
        first_answer_json: that answer as the first turn's content (``later.as_recorded``).
        group: the case's phase-of-flight group (``phase_group``); one the statistics do not know
            gets no ``suggest_codes`` call.
        config: the run's settings; the cap is the source run's per-case cap, applied to the
            post-pass's own calls.
    """

    def __init__(  # noqa: PLR0913, PLR0917 -- the plan's interface (Task 12), positional.
        self,
        raw: Mapping[str, object],
        payload: Payload,
        system: str,
        first_answer: Hypothesis,
        first_answer_json: str,
        group: str | None,
        config: LoopConfig,
    ) -> None:
        self._config = config
        self._case_id = str(raw.get("ntsbNumber", ""))
        self._payload = payload
        self._system = system
        self._first = (first_answer, first_answer_json)
        # The docket state is about arrival, not readability (spec §9; Andy, 2026-10-01): arm B's
        # payload holds the listing whenever the docket lists anything, attached or not.
        listed = EvidenceRole.DOCKET_LISTING.value in payload.fields()
        self._docket_state: DocketState = "all" if listed else "none"
        self._tools = definitions()
        self._base = ModelSettings(
            model=config.model,
            price_variant=config.price_variant,
            reasoning_effort=config.reasoning_effort,
            max_output_tokens=config.max_output_tokens,
            pass_reasoning=config.pass_reasoning,
        )
        calls: list[ToolCall] = []
        results: list[Turn] = []
        fixed: list[FixedCall] = []
        for n, (name, arguments) in enumerate(_requests(first_answer, group), start=1):
            parsed = parse_call(name, arguments, config.tables)
            result = run_coding_tool(name, parsed, tables=config.tables, stats=config.stats)
            call = ToolCall(
                call_id=f"{_CALL_ID}-{n}", name=name, arguments=parsed.model_dump_json()
            )
            calls.append(call)
            results.append(
                Turn(role="tool", tool_call_id=call.call_id, tool_text=ToolText.of(result.text))
            )
            fixed.append(
                FixedCall(
                    name, parsed.model_dump(mode="json"), len(result.text), result.argument_errors
                )
            )
        opening = Turn(role="assistant", content=first_answer_json, tool_calls=tuple(calls))
        self._history: tuple[Turn, ...] = (opening, *results)
        self._fixed = tuple(fixed)
        self._step: Literal["answer", "refine"] = "answer"
        self._retry = False
        self._pending: PendingCall | None = None
        self._stop: str | None = None
        self._spent = 0.0
        self._rows: list[AgentCall] = []
        self._checkpoints: list[tuple[StepKind, Hypothesis]] = []
        # The forced answer to refine, and its JSON as the model wrote it.
        self._submitted: tuple[Hypothesis, str] | None = None
        self._rejected: str | None = None
        self._final: Hypothesis | None = None

    # --- the driver's side ---

    @property
    def case_id(self) -> str:
        """The case's NTSB number: what a driver names this case's calls by."""
        return self._case_id

    @property
    def call_index(self) -> int:
        """The place of the next call in the case: the replies taken so far, failures included."""
        return len(self._rows)

    @property
    def fixed_calls(self) -> tuple[FixedCall, ...]:
        """The pipeline's own calls, in the order the turn holds them."""
        return self._fixed

    def stop(self, reason: str) -> None:
        """End the case now with ``reason``; a pending call is dropped, a first reason kept."""
        if self._stop is None:
            self._stop = reason
        self._pending = None

    def next_call(self) -> PendingCall | None:
        """The next call to make, or None once the case has stopped; the same until accepted.

        The per-case cap is checked here, on the call's estimate. Before the answer, room is held
        for the refinement of the first answer (the only answer there is yet).
        """
        if self._pending is None and self._stop is None:
            call = self._build()
            held = self._refinement_estimate() if self._step == "answer" else 0.0
            if self._spent + call.estimated_usd + held > self._config.cap_usd:
                self._stop = "cap"
            else:
                self._pending = call
        return self._pending

    def accept(
        self,
        reply: ModelReply | None,
        *,
        error: str | None = None,
        sent_at: datetime,
        returned_at: datetime,
        batch_id: str | None = None,
    ) -> None:
        """Take the reply to the pending call, and write its trail row.

        Args:
            reply: the model's reply, or None when the call failed: it is issued again once, and
                a second failure in a row stops the case ``failed: <step>``.
            error: why the call failed, when ``reply`` is None.
            sent_at: when the call was sent.
            returned_at: when the reply, or the failure, came back.
            batch_id: the batch the call went in, if any.

        Raises:
            RuntimeError: no call is pending.
        """
        call = self._pending
        if call is None:
            raise RuntimeError("accept() called with no call pending")
        self._pending = None
        retry = self._retry
        if reply is None:
            seen = _Seen(protocol_error=error or "no reply")
            self._break()
        elif call.step == "refine":
            seen = self._accept_refinement(reply)
        else:
            seen = self._accept_answer(reply)
        cost = 0.0 if reply is None else cost_usd(reply, call.settings)[0]
        self._spent += cost
        usage = _NO_USAGE if reply is None else reply.usage
        self._rows.append(
            AgentCall(
                run_id=self._config.run_id,
                case_id=self._case_id,
                trigger=1,
                docket_state=self._docket_state,
                call_index=len(self._rows),
                step=call.step,
                retry=retry,
                tool=seen.tool,
                arguments=seen.arguments or {},
                protocol_error=seen.protocol_error,
                result_chars=seen.result_chars,
                argument_errors=0,
                hypothesis=seen.hypothesis,
                prompt_tokens=usage.prompt_tokens,
                cached_tokens=usage.cached_tokens,
                completion_tokens=usage.completion_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                finish_reason=None if reply is None else reply.finish_reason,
                cost_usd=cost,
                estimated_usd=call.estimated_usd,
                sent_at=sent_at,
                returned_at=returned_at,
                batch_id=batch_id,
                commit_sha=self._config.commit[0],
                dirty=self._config.commit[1],
            )
        )

    @property
    def outcome(self) -> LoopOutcome:
        """How the case ended, with its trail; valid once ``next_call`` returns None.

        ``coding_calls`` and ``argument_errors`` count the pipeline's own calls; there are no
        read choices.

        Raises:
            RuntimeError: the case has not stopped.
        """
        if self._stop is None:
            raise RuntimeError("the case has not stopped")
        return LoopOutcome(
            case_id=self._case_id,
            stop_reason=self._stop,
            checkpoints=tuple(self._checkpoints),
            answer=self._final,
            reads=(),
            read=(),
            skipped=(),
            coding_calls=len(self._fixed),
            argument_errors=sum(c.argument_errors for c in self._fixed),
            cost_usd=self._spent,
            calls=tuple(self._rows),
        )

    # --- building calls ---

    def _build(self) -> PendingCall:
        if self._step == "refine":
            answer, arguments = self._answer()
            settings = self._refine_settings()
            system = self._refine_system(answer)
            if self._rejected is not None:
                system += f"\n\n{prompt.REJECTED}{self._rejected}"
            history: tuple[Turn, ...] = (Turn(role="assistant", content=arguments),)
        else:
            update = {
                "tools": self._tools,
                "tool_choice": force(_FORCED),
                "parallel_tool_calls": False,
            }
            settings = self._base.model_copy(update=update)
            system, history = self._system, self._history
        return PendingCall(
            payload=self._payload,
            settings=settings,
            system=system,
            history=history,
            step=self._step,
            estimated_usd=estimate_usd(settings, system, history, len(self._payload.text)),
        )

    def _refinement_estimate(self) -> float:
        """What refining the first answer would cost; 0 when it would not be refined."""
        answer, answer_json = self._first
        if answer.abstain or not answer.findings:
            return 0.0
        history = (Turn(role="assistant", content=answer_json),)
        system = self._refine_system(answer)
        return estimate_usd(self._refine_settings(), system, history, len(self._payload.text))

    def _refine_settings(self) -> ModelSettings:
        return self._base.model_copy(
            update={"json_schema": REFINEMENT_SCHEMA, "schema_name": "refinement"}
        )

    def _refine_system(self, answer: Hypothesis) -> str:
        """The runner's stage-2 system text (``scoring/runner.py``, ``_two_turns``)."""
        return f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(answer, self._config.tables)}"

    def _answer(self) -> tuple[Hypothesis, str]:
        if self._submitted is None:  # refinement follows an answer, always
            raise RuntimeError("refinement with no answer")
        return self._submitted

    # --- taking replies ---

    def _break(self) -> None:
        """A call that failed: issue it again once; a second failure stops the case there."""
        if self._retry:
            self._stop = f"failed: {self._step}"
        else:
            self._retry = True

    def _accept_answer(self, reply: ModelReply) -> _Seen:
        """The forced answer: refused and asked again (once) unless it is a valid answer.

        A reply that called no tool is sent again unchanged (there is no call id to answer). A
        call to another tool, or an answer the code tables refuse, is answered with why, as the
        loop answers it, and the answer asked for again.
        """
        if not reply.tool_calls:
            self._break()
            return _Seen(protocol_error="no tool call")
        first = reply.tool_calls[0]
        try:
            answer = self._parse_answer(first)
        except SchemaError as error:
            refusal = sanitised(error)
            turns, chars = answer_turns(reply, not_accepted(refusal))
            self._history = (*self._history, *turns)
            self._break()
            return _Seen(tool=first.name, protocol_error=refusal, result_chars=chars)
        self._retry = False
        self._checkpoints.append(("answer", answer))
        if answer.abstain or not answer.findings:
            self._final, self._stop = answer, "done"
        else:
            self._submitted, self._step = (answer, first.arguments), "refine"
        return _Seen(tool=first.name, arguments=answer.model_dump(mode="json"), hypothesis=answer)

    def _parse_answer(self, call: ToolCall) -> Hypothesis:
        """The call's answer; ``SchemaError`` for another tool, or an answer the tables refuse."""
        if call.name != _FORCED:
            raise SchemaError(wrong_tool((_FORCED,), call.name))
        return parse_hypothesis(call.arguments, self._config.tables)

    def _accept_refinement(self, reply: ModelReply) -> _Seen:
        answer, _ = self._answer()
        try:
            refined = parse_refinement(reply.content or "", self._config.tables, answer)
        except SchemaError as error:
            self._rejected = sanitised(error)
            self._break()
            return _Seen(protocol_error=self._rejected)
        self._checkpoints.append(("refine", refined))
        self._final, self._stop = refined, "done"
        return _Seen(hypothesis=refined)


# --- the post-pass over a finished run ---


@dataclass(frozen=True)
class Preflight:
    """A source run read and checked once, before anything is read, reserved or written.

    Attributes:
        record: the source run's record.
        cases: its cases, in order.
        run_id: the derived run's id.
        spec: the source run's spec, rebuilt: what ``prepare_case`` is called with, so the payload
            is the one the source run sent.
    """

    record: RunRecord
    cases: tuple[CaseResult, ...]
    run_id: str
    spec: RunSpec


def preflight(source: Path, runs_dir: Path) -> Preflight:
    """Read a source run and refuse it unless the post-pass may run on it. Read-only.

    Refused: a folder with no run record; anything the ordering check refuses (not a finished
    development arm B run, a derived check run, a case outside the development split; reused
    from ``checkpass``); a run on ``dev-seal-400``, used once (decision 0095); a tools post-pass
    itself; an ablation (exclusions or includes: arm B's pipeline starts from its plain answer);
    evidence past v1; guidance other than S3's (``run.GUIDANCE``: part 1 is S2.7's answer with
    the two kept guidance files, spec §7.1); a sample S3's statistics pool holds (decision
    0129); a record whose price variant or reasoning level is not one a run can have; and a
    derived folder that already exists.

    Raises:
        ConfigurationError: any refusal above.
    """
    if not (source / RUN_FILE).is_file() or not (source / _CASES_FILE).is_file():
        raise ConfigurationError(f"{source.name}: no run folder with {RUN_FILE} and {_CASES_FILE}")
    record = read_jsonl(source / RUN_FILE, RunRecord)[0]
    cases = tuple(read_jsonl(source / _CASES_FILE, CaseResult))
    _refuse_unless_development(record, cases)
    if record.sample == USED_ONCE:
        raise ConfigurationError(
            f"{record.run_id} is on {USED_ONCE}, the sealed development sample S2.7 used once "
            "(decision 0095): it is never read again, so no post-pass runs on it"
        )
    if record.run_id.endswith(_SUFFIX):
        raise ConfigurationError(f"{record.run_id} is itself a tools post-pass: no stacked passes")
    if record.exclusions or record.includes:
        raise ConfigurationError(
            f"{record.run_id} is an ablation (exclusions={record.exclusions}, "
            f"includes={record.includes}): arm B's pipeline starts from its plain answer "
            "(spec §7.1)"
        )
    if record.evidence_version != "v1":
        raise ConfigurationError(
            f"{record.run_id} read evidence version {record.evidence_version}: arm B's pipeline "
            "reads v1 (spec §7.1)"
        )
    if record.guidance != GUIDANCE:
        raise ConfigurationError(
            f"{record.run_id} read the guidance {', '.join(record.guidance) or 'none'}: arm B's "
            f"pipeline starts from S2.7's answer with S3's guidance {', '.join(GUIDANCE)} "
            "(spec §7.1 part 1)"
        )
    refuse_pool_holding(STATS, record.sample)
    run_id = tools_id(record.run_id)
    if (runs_dir / run_id).exists():
        raise ConfigurationError(
            f"{run_id} exists: the post-pass is run once per source run. If it is a dead pass "
            f"(no finish time in its run.jsonl), move {runs_dir / run_id} aside under another "
            "name, which keeps its spend counted, and run it again"
        )
    return Preflight(record, cases, run_id, _source_spec(record))


def _source_spec(record: RunRecord) -> RunSpec:
    """The source run's spec, as far as ``prepare_case`` reads it (the cap decides the payload)."""
    if record.price_variant not in _PRICES:
        raise ConfigurationError(
            f"{record.run_id} records price variant {record.price_variant!r}, not one of {_PRICES}"
        )
    effort = record.reasoning_effort
    if effort is not None and effort not in get_args(sources.ReasoningEffort):
        raise ConfigurationError(f"{record.run_id} records an unknown reasoning level {effort!r}")
    return RunSpec(
        sample=record.sample,
        arm="B",
        model=record.model,
        reasoning_effort=cast("sources.ReasoningEffort | None", effort),
        max_output_tokens=record.max_output_tokens,
        price_variant=cast("Literal['batch', 'standard']", record.price_variant),
        cap_usd=record.cap_usd,
        guidance=record.guidance,
    )


@dataclass(frozen=True)
class _Case:
    """One source case: copied through, failed before any call, or with its loop.

    ``failure`` is set for a case the post-pass answers but could not start (a leak, a changed
    payload); ``loop`` and ``prepared`` for one it answers.
    """

    source: CaseResult
    loop: FixedToolsLoop | None = None
    prepared: Prepared | None = None
    failure: str | None = None


def tools_run(  # noqa: PLR0913 -- the plan's interface (Task 12).
    source: Path,
    raws: Mapping[str, Mapping[str, object]],
    *,
    client: ModelClient,
    batch: BatchRunner | None,
    docket: DocketReader,
    tables: CodeTables,
    stats: CodingStats,
    stats_name: StatsName,
    seen_pairs: frozenset[str],
    runs_dir: Path,
    budget_usd: float,
    commit: tuple[str, bool],
    sync: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunRecord:
    """Run arm B's fixed tool post-pass over a finished arm B run; write the derived run.

    Every refusal, and every case's preparation (its docket read, its payload rebuilt and
    checked, its loop built), comes before the budget is reserved, so nothing refused leaves a
    folder or a reservation. Then ``len(cases) x EXPECTED_COST_PER_CASE_USD`` is reserved, the
    loops are driven (in batch rounds, or one call at a time with ``sync``), and the records are
    written. On any exception the cases still running stop ``aborted: <error>``, the records are
    written with no finish time, so the spend is counted, and the error is raised again; the
    reservation is settled on every path.

    Args:
        source: the source run's folder.
        raws: the source run's case records, by case id (``samples.load_cases``); one for every
            case the post-pass answers.
        client: the model client, for a ``sync`` post-pass.
        batch: the batch client, for every other post-pass.
        docket: where each case's docket is read from; v1 only.
        tables: the code tables.
        stats: the statistics the tools count in: ``load_stats(stats_name)``.
        stats_name: the name ``stats`` was loaded by; it must be S3's (``STATS``, decision 0129),
            and it is the one the derived run's prompt version records (``+tools-<name>``).
        seen_pairs: the development split's primary occurrence codes (``pair_unseen``).
        runs_dir: the runs directory; the derived run is written beside the source.
        budget_usd: the month's budget.
        commit: the commit SHA and whether the tree was dirty (0018, 0033).
        sync: standard-price calls one at a time instead of batch rounds.
        now: the clock; the only source of times.

    Returns:
        The derived run's record, also written to its ``run.jsonl``.

    Raises:
        ConfigurationError: a refusal (``preflight``; statistics other than S3's; a docket reader
            past v1; no batch client for a batch post-pass; a missing or mismatched record).
        BudgetError: the projection does not fit the month's budget.
        BatchCancelledError: a batch was cancelled; the records are written.
    """
    pre = preflight(source, runs_dir)
    if stats_name != STATS:
        raise ConfigurationError(
            f"arm B's tool post-pass counts in S3's statistics ({STATS}, decision 0129); "
            f"statistics {stats_name} were given"
        )
    if docket.version != "v1":
        raise ConfigurationError(
            f"the post-pass reads v1 evidence; this docket reader reads {docket.version} (0076)"
        )
    if not sync and batch is None:
        raise ConfigurationError("a batch client is required for a post-pass without --sync")
    missing = [c.case_id for c in pre.cases if in_post_pass(c) and c.case_id not in raws]
    if missing:
        more = f" and {len(missing) - _SHOWN} more" if len(missing) > _SHOWN else ""
        raise ConfigurationError(f"no record for {', '.join(missing[:_SHOWN])}{more}")
    config = LoopConfig(
        tables=tables,
        stats=stats,
        guidance=pre.spec.guidance,
        exclusions=frozenset(),
        cap_usd=pre.spec.cap_usd,
        price_variant="standard" if sync else "batch",
        max_output_tokens=pre.spec.max_output_tokens,
        pass_reasoning=agent_loop.PASS_REASONING,  # arm C's setting (``run --arm C`` reads it)
        run_id=pre.run_id,
        commit=commit,
        model=pre.spec.model,
        reasoning_effort=pre.spec.reasoning_effort,
    )
    # The derived run's label is fixed here, before any model call, and written as this one value:
    # an edit to a covered file while a batch is in flight must not make ``run.jsonl`` name text
    # the post-pass never sent (decision 0133).
    label = f"{pre.record.prompt_version}+tools-{stats_name}{text_mark()}"
    cases = [_prepare(case, raws, pre.spec, docket, config) for case in pre.cases]
    loops = [case.loop for case in cases if case.loop is not None]
    folder = runs_dir / pre.run_id
    started = now()
    reserve_within_budget(
        runs_dir, pre.run_id, len(cases) * EXPECTED_COST_PER_CASE_USD, budget_usd, now=started
    )

    def write(finished: datetime | None) -> RunRecord:
        return _write(
            folder,
            pre,
            cases,
            config,
            started=started,
            finished=finished,
            seen_pairs=seen_pairs,
            budget_usd=budget_usd,
            prompt_version=label,
        )

    try:
        log_line(
            now,
            lambda: (
                f"tools {pre.run_id} source={pre.record.run_id} cases={len(cases)} "
                f"answered={len(loops)} model={config.model} price={config.price_variant} "
                f"cap=${config.cap_usd:.2f} stats={stats_name}"
            ),
        )
        try:
            _drive(loops, client, batch, folder, now, sync=sync)
        except BaseException as error:
            for loop in loops:
                loop.stop(f"aborted: {error}")
            write(None)
            if isinstance(error, BatchCancelledError):
                batch_ids = round_costs(folder).batch_ids
                raise BatchCancelledError(
                    f"batch {batch_ids[-1]} of {pre.run_id} was cancelled, so the post-pass stops "
                    "here. Its records so far are written, and its spend counts. A post-pass is "
                    f"not resumed: move {folder} aside under another name and run it again."
                ) from error
            raise
        record = write(now())
    finally:
        settle(runs_dir, pre.run_id)
    return record


def _prepare(
    case: CaseResult,
    raws: Mapping[str, Mapping[str, object]],
    spec: RunSpec,
    docket: DocketReader,
    config: LoopConfig,
) -> _Case:
    """A source case's place in the post-pass: copied through, failed before any call, or a loop.

    The payload is rebuilt with ``prepare_case`` on the source run's spec, so it is arm B's, and
    must have the fingerprint the source run recorded; the phase group is read from the evidence
    that call split.
    """
    if not in_post_pass(case):
        return _Case(case)
    raw = raws[case.case_id]
    if str(raw.get("ntsbNumber")) != case.case_id:
        raise ConfigurationError(f"the record given for {case.case_id} is {raw.get('ntsbNumber')}")
    mkey = raw.get("mKey")
    if not isinstance(mkey, int):
        raise ConfigurationError(f"{case.case_id}: no mKey, so no docket")
    try:
        prepared = prepare_case(raw, spec, config.tables, docket.read(mkey))
    except LeakageError as error:
        return _Case(case, failure=f"leak: {error}")
    if fingerprint(prepared.payload) != case.steps[0].payload_fingerprint:
        return _Case(case, failure=PAYLOAD_CHANGED)
    answer = case.steps[-1].hypothesis
    loop = FixedToolsLoop(
        raw,
        prepared.payload,
        prepared.system,
        answer,
        as_recorded(answer),
        phase_group(prepared.evidence.phase_of_flight),
        config,
    )
    return _Case(case, loop=loop, prepared=prepared)


def _drive(  # noqa: PLR0913 -- the loops, both clients, the folder, the clock and the mode.
    loops: Sequence[FixedToolsLoop],
    client: ModelClient,
    batch: BatchRunner | None,
    folder: Path,
    now: Callable[[], datetime],
    *,
    sync: bool,
) -> None:
    """Put the loops through their driver; batch rounds are logged as arm C's are."""
    if sync:
        drive_sync(loops, client, folder=folder, now=now)
        return
    if batch is None:  # refused up front; kept for the type checker
        raise ConfigurationError("a batch client is required for a post-pass without --sync")
    drive_batch(
        loops,
        batch,
        folder=folder,
        now=now,
        max_rounds=MAX_ROUNDS,
        on_round=lambda row, running, waited: log_line(
            now, lambda: round_line(row, running, waited=waited)
        ),
    )


def _write(  # noqa: PLR0913 -- the run, its cases and settings, then when and what it may spend.
    folder: Path,
    pre: Preflight,
    cases: Sequence[_Case],
    config: LoopConfig,
    *,
    started: datetime,
    finished: datetime | None,
    seen_pairs: frozenset[str],
    budget_usd: float,
    prompt_version: str,
) -> RunRecord:
    """Write the derived run's cases, trail and record; return the record.

    Its cost is the post-pass's own: every reply it took, and any round no reply came from. The
    source's answers were paid for, and counted, in the source run. Its prompt version is the
    label ``tools_run`` fixed at its start: the source's with ``+tools-<stats_name>`` (the
    statistics the tool results counted in) and then ``+p`` and the agent's text fingerprint
    (``texts.text_mark``; decision 0133). The post-pass sends the agent's tool definitions, tool
    results and refusals, so its label follows their text as arm C's does; it is passed in, never
    recomputed, so an edit made while the post-pass ran cannot reach the record.
    """
    results = [_result(case, config, seen_pairs) for case in cases]
    write_jsonl(folder / _CASES_FILE, results)
    outcomes = [case.loop.outcome for case in cases if case.loop is not None]
    write_jsonl(folder / TRAIL_FILE, (call for outcome in outcomes for call in outcome.calls))
    costs = round_costs(folder)
    record = pre.record.model_copy(
        update={
            "run_id": pre.run_id,
            "prompt_version": prompt_version,
            "price_variant": config.price_variant,
            "budget_usd": budget_usd,
            "commit_sha": config.commit[0],
            "dirty": config.commit[1],
            "started": started,
            "finished": finished,
            "batch_ids": costs.batch_ids,
            "cases": len(results),
            "cost_usd": sum(outcome.cost_usd for outcome in outcomes) + costs.dead_usd,
            "reported_batch_cost_usd": costs.reported_usd,
        }
    )
    write_jsonl(folder / RUN_FILE, [record])
    return record


def _result(case: _Case, config: LoopConfig, seen_pairs: frozenset[str]) -> CaseResult:
    """One derived case: the source's, copied, failed, or answered again and re-scored."""
    source = case.source
    if case.failure is not None:
        return _failed(source, case.failure, ())
    if case.loop is None or case.prepared is None:
        return source
    outcome = case.loop.outcome
    if outcome.answer is None:  # stopped before an answer it could refine: not scored (arm B's)
        return _failed(source, outcome.stop_reason, outcome.calls)
    step = _step(source, case.loop, case.prepared, outcome.answer, config)
    scores = score_case(outcome.answer, case.prepared.verdict, config.tables, seen_pairs=seen_pairs)
    return source.model_copy(
        update={
            "steps": (*source.steps, step),
            "scores": scores,
            "failure": None,
            "cost_usd": source.cost_usd + outcome.cost_usd,
            **_replies(source, outcome.calls),
        }
    )


def _failed(source: CaseResult, failure: str, calls: Sequence[AgentCall]) -> CaseResult:
    """A case the post-pass could not answer: the source's steps, no scores, and its spend."""
    return source.model_copy(
        update={
            "scores": None,
            "failure": failure,
            "cost_usd": source.cost_usd + sum(call.cost_usd for call in calls),
            **_replies(source, calls),
        }
    )


def _replies(source: CaseResult, calls: Sequence[AgentCall]) -> dict[str, object]:
    """The case's per-reply tuples, the post-pass's calls after the source's (one per call)."""
    return {
        "reply_completion_tokens": (
            *source.reply_completion_tokens,
            *(c.completion_tokens for c in calls),
        ),
        "reply_reasoning_tokens": (
            *source.reply_reasoning_tokens,
            *(c.reasoning_tokens for c in calls),
        ),
        "reply_finish_reasons": (*source.reply_finish_reasons, *(c.finish_reason for c in calls)),
    }


def _step(
    source: CaseResult,
    loop: FixedToolsLoop,
    prepared: Prepared,
    answer: Hypothesis,
    config: LoopConfig,
) -> StepRecord:
    """The derived ``fixed_tools`` step: what the post-pass sent, answered and cost."""
    last = source.steps[-1]
    outcome = loop.outcome
    calls = outcome.calls
    reasoning = None
    if any(c.reasoning_tokens is not None for c in calls):
        reasoning = sum(c.reasoning_tokens or 0 for c in calls)
    return StepRecord(
        case_id=source.case_id,
        step=last.step + 1,
        arm="B",
        condition="full",
        day=None,
        tool=TOOL,
        arguments={"calls": [call.record() for call in loop.fixed_calls]},
        reason=FIXED,
        expected_effect=FIXED,
        returned_roles=tuple(sorted(prepared.payload.fields())),
        not_available=prepared.not_available,
        documents_attached=prepared.documents_attached,
        documents_not_read=prepared.not_read,
        payload_fingerprint=fingerprint(prepared.payload),
        hypothesis=answer,
        observed_effect="",
        stop_reason="abstained" if answer.abstain else "answered",
        model=config.model,
        price_variant=config.price_variant,
        prompt_tokens=sum(c.prompt_tokens for c in calls),
        completion_tokens=sum(c.completion_tokens for c in calls),
        reasoning_tokens=reasoning,
        reply_completion_tokens=tuple(c.completion_tokens for c in calls),
        reply_reasoning_tokens=tuple(c.reasoning_tokens for c in calls),
        reply_finish_reasons=tuple(c.finish_reason for c in calls),
        cost_usd=outcome.cost_usd,
        cumulative_cost_usd=last.cumulative_cost_usd + outcome.cost_usd,
        commit_sha=config.commit[0],
        dirty=config.commit[1],
    )
