"""The case loop: one case's conversation with the model, one call at a time (S3.1 Task 8).

``CaseLoop`` never calls a model. ``next_call`` hands out the next call as a ``PendingCall`` and
``accept`` takes its reply, so one object serves the synchronous driver (a call, then its reply)
and the batch driver (a round of calls across many cases, then their replies; Task 9).

The steps (spec §4.2; ``agent/steps.py`` holds the table): ``h0``, a hypothesis before reading;
``choice1``, read or skip for every offered document, then ``h1`` if anything was read;
``choice2``, a second look over what is left, then ``h2`` if anything was read; ``coding``, up
to six coding-tool calls; ``answer``, ``submit_answer`` forced; ``refine``, arm B's second pass
on the finding items, exactly the runner's stage 2.

The conversation is append-only (spec §5.3): every call sends the same system text and tool
definitions, the evidence as the first user message, and each earlier turn unchanged. A tool
result is a ``Turn`` holding a ``Payload`` (the listing, or the documents chosen, each through
``split_record`` and the guard) and a ``ToolText`` (the loop's own words, numbers and codes). A
leak in any payload ends the case ``failed: leak`` before its text is sent.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, cast, get_args

from pydantic import BaseModel

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent import steps
from ntsb_probable_cause.agent.documents import (
    DocketView,
    answer_payload,
    documents_payload,
    evidence_payload,
    listing_payload,
)
from ntsb_probable_cause.agent.schemas import (
    ChooseDocuments,
    CodingToolName,
    Without,
    definitions,
    parse_call,
)
from ntsb_probable_cause.agent.texts import ONE_CALL, not_accepted, system_text
from ntsb_probable_cause.agent.tools import ToolResult, run_coding_tool
from ntsb_probable_cause.agent.trail import AgentCall, LoopOutcome, ReadRecord, StepKind
from ntsb_probable_cause.errors import LeakageError, SchemaError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    ToolCall,
    ToolText,
    Turn,
    Usage,
    cost_usd,
)
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats
from ntsb_probable_cause.scoring.hypothesis import REFINEMENT_SCHEMA, Hypothesis, parse_refinement

_CHARS_PER_TOKEN: Final = 4
_DOCKET_ROLES: Final = frozenset({EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS})
_BEFORE_ANSWER: Final[frozenset[StepKind]] = frozenset(
    {"h0", "choice1", "h1", "choice2", "h2", "coding"}
)
_NO_USAGE: Final = Usage(prompt_tokens=0, completion_tokens=0)


@dataclass(frozen=True)
class PendingCall:
    """One model call the loop wants made; the driver sends it as it is.

    Attributes:
        payload: the first user message: the case's evidence, without its docket.
        settings: the model settings, tools and ``tool_choice`` included.
        system: the system text.
        history: every earlier turn, unchanged (spec §5.3).
        step: the step the call is made for.
        estimated_usd: the loop's estimate of the call's cost, checked against the cap.
    """

    payload: Payload
    settings: ModelSettings
    system: str
    history: tuple[Turn, ...]
    step: StepKind
    estimated_usd: float


@dataclass(frozen=True)
class LoopConfig:
    """A run's settings for the loop: the same for every case of the run.

    Attributes:
        tables: the code tables the answer chooses from.
        stats: the statistics pool the coding tools count in.
        guidance: the coding guidance names, in stacking order.
        exclusions: the run's excluded evidence roles; a docket role means ``view=None``.
        cap_usd: the per-case cost cap (spec §8.2).
        price_variant: batch or standard prices.
        max_output_tokens: the reply budget of every call (decision 0084).
        max_coding_calls: the coding calls before the answer is forced (spec §8.2).
        pass_reasoning: whether assistant turns' ``reasoning_details`` go back to the model
            (the shape probe's check 4 decides; off until it does).
        without: the tool ablations (spec §7.2); the run sends ``definitions(without)``.
        run_id: the run, for the trail.
        commit: the commit SHA and whether the tree was dirty (decisions 0018, 0033).
        model: the model id (decision 0073's by default).
        reasoning_effort: the reasoning level stated on every call (decision 0073).
    """

    tables: CodeTables
    stats: CodingStats
    guidance: tuple[str, ...]
    exclusions: frozenset[EvidenceRole]
    cap_usd: float
    price_variant: Literal["batch", "standard"]
    max_output_tokens: int = 8000
    max_coding_calls: int = 6
    pass_reasoning: bool = False
    without: frozenset[Without] = frozenset()
    run_id: str = ""
    commit: tuple[str, bool] = ("", False)
    model: str = sources.DEFAULT_MODEL
    reasoning_effort: sources.ReasoningEffort | None = sources.DEFAULT_REASONING_EFFORT


class _NotAcceptedError(Exception):
    """A reply the step does not accept. The message holds no model or case text."""


@dataclass(frozen=True)
class _Result:
    """An accepted call: its tool result, or ``text=None`` when the conversation ends there."""

    arguments: dict[str, object]
    text: str | None = None
    payload: Payload | None = None
    hypothesis: Hypothesis | None = None
    argument_errors: int = 0


@dataclass(frozen=True)
class _Seen:
    """What the loop made of one reply: the parts of its trail row the reply decides."""

    tool: str | None = None
    arguments: dict[str, object] = field(default_factory=dict)
    protocol_error: str | None = None
    result_chars: int = 0
    argument_errors: int = 0
    hypothesis: Hypothesis | None = None


class CaseLoop:
    """One trigger of one case, as a state machine of model calls and their replies.

    Args:
        raw: the case record; a ``docket`` key, if it has one, is not sent.
        view: the case's prepared docket, or None when it has none or the run excludes it.
        config: the run's settings.
        trigger: which trigger of the case this is (1 in evaluation, spec §4.1).

    Raises:
        ValueError: a docket role is excluded but a view was passed; pass ``view=None``.
    """

    def __init__(
        self,
        raw: Mapping[str, object],
        view: DocketView | None,
        config: LoopConfig,
        *,
        trigger: int = 1,
    ) -> None:
        if view is not None and config.exclusions & _DOCKET_ROLES:
            raise ValueError("a run that excludes a docket role passes view=None")
        self._config = config
        self._case_id = str(raw.get("ntsbNumber", ""))
        self._trigger = trigger
        self._docket = view if view is not None and view.offered else None
        self._system = system_text(config.tables, config.guidance)
        self._tools = definitions(config.without)
        self._coding: tuple[str, ...] = (
            ()
            if "coding" in config.without or config.max_coding_calls < 1
            else tuple(name for name in get_args(CodingToolName) if name not in config.without)
        )
        self._base = ModelSettings(
            model=config.model,
            price_variant=config.price_variant,
            reasoning_effort=config.reasoning_effort,
            max_output_tokens=config.max_output_tokens,
            pass_reasoning=config.pass_reasoning,
        )
        self._history: tuple[Turn, ...] = ()
        self._step: StepKind = "h0"
        self._retry = False
        self._pending: PendingCall | None = None
        self._stop: str | None = None
        self._spent = 0.0
        self._rows: list[AgentCall] = []
        self._checkpoints: list[tuple[StepKind, Hypothesis]] = []
        self._reads: list[ReadRecord] = []
        self._read: list[int] = []
        self._coding_calls = 0
        self._argument_errors = 0
        self._draft: Hypothesis | None = None
        # The answer to refine: the hypothesis, its JSON as the model wrote it, and the payload.
        self._submitted: tuple[Hypothesis, str, Payload] | None = None
        self._rejected: str | None = None
        self._final: Hypothesis | None = None
        self._evidence: Payload | None = None
        try:
            self._evidence = evidence_payload(raw, config.exclusions)
        except LeakageError:
            self._stop = "failed: leak"

    # --- the driver's side ---

    @property
    def case_id(self) -> str:
        """The case's NTSB number: what a driver names this case's calls by."""
        return self._case_id

    @property
    def call_index(self) -> int:
        """The place of the next call in the case: the replies accepted so far, failures included.

        It is the ``call_index`` the trail row of the pending call will carry.
        """
        return len(self._rows)

    def stop(self, reason: str) -> None:
        """End the case now with ``reason``: the driver's way to stop a case the run has spent.

        A call pending is dropped, never sent. The trail so far is kept, and a case that has
        already stopped keeps the reason it stopped with.
        """
        if self._stop is None:
            self._stop = reason
        self._pending = None

    def next_call(self) -> PendingCall | None:
        """The next call to make, or None once the case has stopped.

        Idempotent until ``accept``: asked twice, it returns the same call. The per-case cap is
        checked here, on the call's estimate (spec §8.2).
        """
        if self._pending is None and self._stop is None:
            self._pending = self._prepare()
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
            reply: the model's reply, or None when the call failed (a batch item that failed):
                the call is then re-issued once, and a second failure stops the case.
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
            seen = self._accept_tool_call(call.step, reply)
        cost = 0.0 if reply is None else cost_usd(reply, call.settings)[0]
        self._spent += cost
        usage = _NO_USAGE if reply is None else reply.usage
        self._rows.append(
            AgentCall(
                run_id=self._config.run_id,
                case_id=self._case_id,
                trigger=self._trigger,
                docket_state="none" if self._docket is None else "all",
                call_index=len(self._rows),
                step=call.step,
                retry=retry,
                tool=seen.tool,
                arguments=seen.arguments,
                protocol_error=seen.protocol_error,
                result_chars=seen.result_chars,
                argument_errors=seen.argument_errors,
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
        """How the case ended, with its whole trail; valid once ``next_call`` returns None.

        Raises:
            RuntimeError: the case has not stopped.
        """
        if self._stop is None:
            raise RuntimeError("the case has not stopped")
        decided = {d.document for read in self._reads for d in read.decisions if not d.read}
        return LoopOutcome(
            case_id=self._case_id,
            stop_reason=self._stop,
            checkpoints=tuple(self._checkpoints),
            answer=self._final,
            reads=tuple(self._reads),
            read=tuple(self._read),
            skipped=tuple(i for i in self._offered() if i in decided and i not in self._read),
            coding_calls=self._coding_calls,
            argument_errors=self._argument_errors,
            cost_usd=self._spent,
            calls=tuple(self._rows),
        )

    # --- building calls ---

    def _prepare(self) -> PendingCall | None:
        """The current step's call after the cap check; None, stopped at ``cap``, if none fits.

        Before the answer, room is held back for an answer call and its refinement. An answer
        call made now would send this call's prompt and tools, so its estimate is this one's.
        If this call and that room do not fit, the answer is forced; if the answer and its
        refinement do not fit either, the case stops at the cap.
        """
        call = self._build(self._step)
        cap = self._config.cap_usd
        refinement = self._refinement_estimate()
        if self._step in _BEFORE_ANSWER and (
            self._spent + 2 * call.estimated_usd + refinement > cap
        ):
            self._step, self._retry = "answer", False
            call = self._build("answer")
        held = refinement if self._step == "answer" else 0.0
        if self._spent + call.estimated_usd + held > cap:
            self._stop = "cap"
            return None
        return call

    def _build(self, step: StepKind) -> PendingCall:
        if step == "refine":
            answer, arguments, payload = self._answer()
            settings = self._refine_settings()
            system = self._refine_system(answer)
            if self._rejected is not None:
                system += f"\n\nYour previous reply was rejected: {self._rejected}"
            history: tuple[Turn, ...] = (Turn(role="assistant", content=arguments),)
        else:
            update = {
                "tools": self._tools,
                "tool_choice": steps.tool_choice(step),
                "parallel_tool_calls": False,
            }
            settings = self._base.model_copy(update=update)
            payload, system, history = self._payload(), self._system, self._history
        return PendingCall(
            payload=payload,
            settings=settings,
            system=system,
            history=history,
            step=step,
            estimated_usd=self._estimate(settings, system, history, len(payload.text)),
        )

    def _estimate(
        self, settings: ModelSettings, system: str, history: tuple[Turn, ...], payload_chars: int
    ) -> float:
        """All the prompt's text at four characters a token, plus a full reply (the brief's)."""
        chars = len(system) + payload_chars + len(json.dumps(list(settings.tools)))
        chars += sum(_turn_chars(turn, with_reasoning=settings.pass_reasoning) for turn in history)
        price = sources.price_of(settings.model_id())
        return (
            chars / _CHARS_PER_TOKEN * price.input_usd_per_mtok
            + settings.max_output_tokens * price.output_usd_per_mtok
        ) / 1e6

    def _refinement_estimate(self) -> float:
        """What refining the latest hypothesis would cost; 0 when it would not be refined.

        Its payload is taken as the evidence plus every payload sent so far (the listing and the
        documents read), which is what arm B's payload shape holds.
        """
        draft = self._draft
        if draft is None or draft.abstain or not draft.findings:
            return 0.0
        history = (Turn(role="assistant", content=draft.model_dump_json()),)
        sent = sum(len(turn.payload.text) for turn in self._history if turn.payload is not None)
        payload_chars = len(self._payload().text) + sent
        system = self._refine_system(draft)
        return self._estimate(self._refine_settings(), system, history, payload_chars)

    def _refine_settings(self) -> ModelSettings:
        return self._base.model_copy(
            update={"json_schema": REFINEMENT_SCHEMA, "schema_name": "refinement"}
        )

    def _refine_system(self, answer: Hypothesis) -> str:
        """The runner's stage-2 system text (``scoring/runner.py``, ``_two_turns``)."""
        return f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(answer, self._config.tables)}"

    def _payload(self) -> Payload:
        if self._evidence is None:  # the constructor stopped the case; nothing is built
            raise RuntimeError("the case has no evidence payload")
        return self._evidence

    def _answer(self) -> tuple[Hypothesis, str, Payload]:
        if self._submitted is None:  # refinement follows an answer, always
            raise RuntimeError("refinement with no answer")
        return self._submitted

    def _answer_evidence(self) -> Payload:
        """The refinement's payload: arm B's shape when documents were offered, else the evidence.

        It never shows what the agent did not see: the listing only when it was offered at h0,
        and only the documents read.
        """
        if self._docket is None:
            return self._payload()
        read = tuple(i for i in self._offered() if i in self._read)  # arm B's order
        return answer_payload(self._docket, read, self._config.exclusions)

    # --- taking replies ---

    def _break(self) -> None:
        """A call that failed: re-issue its step once; a second failure stops the case there."""
        if self._retry:
            self._stop = f"failed: {self._step}"
        else:
            self._retry = True

    def _accept_tool_call(self, step: StepKind, reply: ModelReply) -> _Seen:
        if not reply.tool_calls:
            # No call id to answer: the same call is re-issued, the conversation unchanged.
            self._break()
            return _Seen(protocol_error="no tool call")
        first = reply.tool_calls[0]
        try:
            result = self._run(step, first)
        except _NotAcceptedError as refused:
            chars = self._answer_calls(reply, not_accepted(str(refused)), None)
            self._break()
            return _Seen(tool=first.name, protocol_error=str(refused), result_chars=chars)
        self._retry = False
        chars = 0 if result.text is None else self._answer_calls(reply, result.text, result.payload)
        return _Seen(
            tool=first.name,
            arguments=result.arguments,
            result_chars=chars,
            argument_errors=result.argument_errors,
            hypothesis=result.hypothesis,
        )

    def _answer_calls(self, reply: ModelReply, text: str, payload: Payload | None) -> int:
        """Append the reply, ``text`` for its first call and ``ONE_CALL`` for any other call.

        Every call id gets a result. Returns the results' size in characters.
        """
        first, *extra = reply.tool_calls
        results = (
            Turn(
                role="tool",
                tool_call_id=first.call_id,
                payload=payload,
                tool_text=ToolText.of(text),
            ),
            *(
                Turn(role="tool", tool_call_id=c.call_id, tool_text=ToolText.of(ONE_CALL))
                for c in extra
            ),
        )
        assistant = Turn(
            role="assistant",
            content=reply.content,
            tool_calls=reply.tool_calls,
            reasoning_details=reply.reasoning_details,
        )
        self._history = (*self._history, assistant, *results)
        return sum(_result_chars(turn) for turn in results)

    def _run(self, step: StepKind, call: ToolCall) -> _Result:
        """Check and run one call; ``_NotAcceptedError`` is raised before any state changes.

        A leak in a payload the call's result would carry stops the case ``failed: leak``: the
        result then keeps the parsed arguments and hypothesis for the trail, and has no text.
        """
        options = steps.allowed(step, self._coding)
        if call.name not in options:
            raise _NotAcceptedError(steps.wrong_tool(options, call.name))
        offered = tuple(f.index for f in self._shelf().rest)
        try:
            parsed = parse_call(call.name, call.arguments, self._config.tables, offered)
        except SchemaError as error:
            raise _NotAcceptedError(steps.sanitised(error)) from None
        arguments = parsed.model_dump(mode="json")
        if not isinstance(parsed, Hypothesis | ChooseDocuments):
            tool = self._code(call.name, parsed)
            return _Result(arguments, tool.text, argument_errors=tool.argument_errors)
        hypothesis = parsed if isinstance(parsed, Hypothesis) else None
        try:
            text, payload = (
                self._hypothesis(step, call, parsed)
                if isinstance(parsed, Hypothesis)
                else self._choose(step, parsed)
            )
        except LeakageError:
            self._stop = "failed: leak"
            return _Result(arguments, hypothesis=hypothesis)
        return _Result(arguments, text, payload, hypothesis)

    def _hypothesis(
        self, step: StepKind, call: ToolCall, hypothesis: Hypothesis
    ) -> tuple[str | None, Payload | None]:
        """Record a hypothesis; the tool text and payload that follow (none after the answer)."""
        self._draft = hypothesis
        if call.name == "submit_answer":
            self._checkpoints.append(("answer", hypothesis))
            if hypothesis.abstain or not hypothesis.findings:
                self._final, self._stop = hypothesis, "done"
            else:
                self._submitted = (hypothesis, call.arguments, self._answer_evidence())
                self._step = "refine"
            return None, None
        self._checkpoints.append((step, hypothesis))
        self._step, text = steps.after_hypothesis(step, self._shelf(), bool(self._coding))
        listing = None
        if self._step == "choice1":
            listing = listing_payload(self._view(), self._config.exclusions)
        return text, listing

    def _choose(self, step: StepKind, choice: ChooseDocuments) -> tuple[str, Payload | None]:
        """Record a read choice; the tool text, and the documents read (none if none were)."""
        offered = tuple(f.index for f in self._shelf().rest)
        wanted = {decision.document for decision in choice.decisions if decision.read}
        read = tuple(i for i in offered if i in wanted)
        skipped = tuple(i for i in offered if i not in wanted)
        self._reads.append(
            ReadRecord(
                step="choice1" if step == "choice1" else "choice2",
                offered=offered,
                decisions=choice.decisions,
                reason=choice.reason,
            )
        )
        payload = documents_payload(self._view(), read, self._config.exclusions) if read else None
        self._read.extend(read)  # only once the documents passed the guard
        self._step, text = steps.after_choice(
            step, read, skipped, self._shelf(), bool(self._coding)
        )
        return text, payload

    def _code(self, name: str, arguments: BaseModel) -> ToolResult:
        try:
            result = run_coding_tool(
                cast("CodingToolName", name),
                arguments,
                tables=self._config.tables,
                stats=self._config.stats,
            )
        except Exception as error:
            # A coding tool's fault must not end the run (Task 6 review): the call is not
            # accepted, and a second fault fails the step as any other break does.
            raise _NotAcceptedError(f"the tool could not run ({type(error).__name__})") from None
        self._coding_calls += 1
        self._argument_errors += result.argument_errors
        if self._coding_calls >= self._config.max_coding_calls:
            self._step = "answer"
        return result

    def _accept_refinement(self, reply: ModelReply) -> _Seen:
        answer, _, _ = self._answer()
        try:
            refined = parse_refinement(reply.content or "", self._config.tables, answer)
        except SchemaError as error:
            self._rejected = steps.sanitised(error)
            self._break()
            return _Seen(protocol_error=self._rejected)
        self._checkpoints.append(("refine", refined))
        self._final, self._stop = refined, "done"
        return _Seen(hypothesis=refined)

    # --- documents ---

    def _offered(self) -> tuple[int, ...]:
        return () if self._docket is None else tuple(f.index for f in self._docket.offered)

    def _shelf(self) -> steps.Shelf:
        """The documents now: the offered ones not read yet, the unreadable ones, those read."""
        if self._docket is None:
            return steps.Shelf()
        rest = tuple(f for f in self._docket.offered if f.index not in self._read)
        return steps.Shelf(rest, self._docket.not_readable, tuple(self._read))

    def _view(self) -> DocketView:
        if self._docket is None:  # a payload is built only when documents are on offer
            raise RuntimeError("a docket payload with no documents on offer")
        return self._docket


def _result_chars(turn: Turn) -> int:
    """A tool turn's text as the transport renders it: payload, blank line, tool text."""
    return len(
        "\n\n".join(part.text for part in (turn.payload, turn.tool_text) if part is not None)
    )


def _turn_chars(turn: Turn, *, with_reasoning: bool) -> int:
    """All the text one earlier turn sends: content, tool calls, result, and passed reasoning."""
    chars = len(turn.content or "") + _result_chars(turn)
    chars += sum(len(call.name) + len(call.arguments) for call in turn.tool_calls)
    if with_reasoning and turn.reasoning_details:
        chars += len(json.dumps(list(turn.reasoning_details)))
    return chars
