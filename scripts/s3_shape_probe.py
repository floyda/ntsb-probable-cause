"""The native-tool shape probe: six checks on GPT-6 Luna, on an invented case (S3.1 Task 4).

Status
    One-shot, paid (cents). Spec §5.5 of ``docs/specs/2026-09-30-s3-agent-loop-design.md``, plan
    ``docs/plans/2026-09-30-s3-1-agent-loop.md`` Task 4. Written and tested offline on
    2026-09-30 (decision 0059's kind: one-shot, not yet run). The controller runs it once, on or
    after 1 October 2026, with ``make s3-shape-probe``, which checks the stage's spend line
    first; that run produces ``docs/results/s3-shape-probe.txt`` and the saved request and
    response pairs ``tests/fixtures/openrouter/s3/*.json``, the agent loop's rule-2 record of
    the response shapes it relies on (the plan's Deviations gives the run's commit and date).
    Rerun only if the provider changes how it answers native tool calls. The result sets no
    bar and tunes nothing. On 2026-10-01, before the paid run, the S3.1 final review added the
    ``armb`` and ``later`` calls and checks 7 and 8, and raised the reservation from $0.05 to
    $0.08.

What it asks
    The loop (Task 8) sends native tool calls, forces a named tool on some steps and requires
    "any tool" on others, and runs on the batch service. Nobody has yet sent this model such a
    conversation, so the probe sends one on an invented case (no real record, no docket), with
    the loop's own system text and all seven tool definitions, first at the standard price and
    then as one-request batches at the batch price:

    1. call 1 forces ``record_hypothesis`` (``parallel_tool_calls`` is false on every call);
    2. call 2 answers call 1's tool call with a tool result and requires any tool;
    3. call 3 answers call 2's tool call and forces ``submit_answer``;
    4. call 2b is call 2 again with call 1's ``reasoning_details`` passed back, run only when
       call 1 returned some.

    Two more calls on each variant send the two request shapes no call above sends, each built
    by the agent's own code on the invented case and independent of the replies above:

    5. call ``armb`` is arm B's tool post-pass (``agent/armb.py``'s ``FixedToolsLoop``): an
       assistant turn the pipeline writes, holding a first answer as its content and four tool
       calls with ids ``fixed-1`` to ``fixed-4``, each answered by its tool's result, then a
       forced ``submit_answer`` (arm B's own system text, S3's statistics);
    6. call ``later`` is a later trigger's opening (``agent/later.py``'s ``opening``): an
       assistant turn with no content calling ``record_hypothesis`` with call id ``"prior"``,
       answered by a tool turn that holds a payload and a tool text, then a forced call. The
       invented case has no docket, so an invented document stands in for the payload of the
       documents read before; the turns are otherwise ``opening``'s own.

    It prints, and with ``--out`` writes, one line per call (flags and numbers only: no reply
    text, no reasoning text), the six checks of spec §5.5, and two more (check 7: arm B's fixed
    turn accepted; check 8: a later trigger's prior turn accepted) as ``check <n>: <answer>``
    lines. What the controller does with the answers is in the plan (Task 4's last step).

Budget
    It reserves ``RESERVE_USD`` against the monthly guard before any call (decision 0083),
    refuses to start without ``OPENROUTER_API_KEY`` or past the guard, stops sending at its own
    cap, writes one ``SpendRecord`` of kind ``probe`` (decision 0131) and settles the
    reservation on every exit path. A batch that has been submitted is billed whether or not it
    is read, and OpenRouter has no cancel: a probe killed while it waits records only what it
    had seen.

Usage:
    uv run python -m scripts.s3_shape_probe [--out PATH] [--fixtures-dir DIR]
"""

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from ntsb_probable_cause import gitinfo, sources
from ntsb_probable_cause.agent import later, schemas, steps, texts
from ntsb_probable_cause.agent.armb import FixedToolsLoop
from ntsb_probable_cause.agent.loop import LoopConfig
from ntsb_probable_cause.agent.trail import Prior
from ntsb_probable_cause.errors import BudgetError, ConfigurationError, ModelError, SchemaError
from ntsb_probable_cause.model.batch import BatchClient, BatchRequest
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    ToolText,
    Turn,
    cost_usd,
)
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.budget import (
    SpendRecord,
    reserve_within_budget,
    settle,
    write_spend,
)
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, load_stats
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, parse_hypothesis
from ntsb_probable_cause.settings import Settings
from scripts.openrouter_probe import redact

Variant = Literal["standard", "batch"]
# The four calls of the chain, then the two request shapes (spec §5.5's checks 7 and 8).
Step = Literal["1", "2", "3", "2b", "armb", "later"]
Shape = Literal["armb", "later"]
SHAPES: tuple[Shape, ...] = ("armb", "later")
# answered: a reply came back. refused: the provider answered the request with a deterministic
# 4xx (not 408 or 429), or a batch failed. error: no usable answer for a reason that says nothing
# about the request (a 5xx, 408 or 429 after the client's retries, a transport error, a batch
# that expired or was cancelled). unfinished: accepted, but no reply was read. not run: skipped.
State = Literal["answered", "refused", "error", "unfinished", "not run"]

VARIANTS: tuple[Variant, ...] = ("standard", "batch")
# The guidance the loop's system text carries (the two S2.7 files kept, decisions 0106, 0117).
GUIDANCE: tuple[str, ...] = ("r3-loc-stall", "r6-aircraft-control")
# What the probe may spend: reserved against the monthly guard, and a stop inside the run. Twelve
# calls (six a variant). Arithmetic from sources.py's prices, not a measurement: a call of at most
# 15,000 prompt tokens and a full 8,000-token reply costs at most $0.0055 at the standard price
# and $0.00275 at the batch price, so twelve cost at most about $0.05; $0.08 leaves room.
RESERVE_USD = 0.08
# The reply budget every run has had since S2.6 (decision 0084); the loop's own is Task 8's.
MAX_OUTPUT_TOKENS = 8000
# A one-request batch took about three minutes in S1; give up on one after an hour.
POLL_SECONDS = 20.0
BATCH_DEADLINE_SECONDS = 3600.0
FIXTURES_DIR = Path("tests/fixtures/openrouter/s3")
SPEND_KIND = "probe"
# The tool result that answers call 2's tool call: fixed text, no counts, no case.
PROBE_RESULT = "The tool ran in a shape probe and returned no counts. Submit your answer now."

_TOOL_NAMES = frozenset(get_args(schemas.ToolName))
_TOKEN = re.compile(r"[a-z_]{1,24}")
_STATUS = re.compile(r"(?:returned|status|failed with) (\d{3})\b")
# A refusal is the provider's deterministic answer to this request: a 4xx other than these two,
# which say "try again" (408 request timeout, 429 rate limit).
_CLIENT_ERRORS = range(400, 500)
_TRY_AGAIN = frozenset({408, 429})
ERROR_NOTE = "provider or transport error, not an answer to the request"
ERROR_TEXT_NOT_SAVED = "provider error text not saved"


# ------------------------------------------------------------------------------------------
# The invented case and the texts the loop would send
# ------------------------------------------------------------------------------------------


def invented_evidence() -> Evidence:
    """A fixed-wing landing accident that never happened: no record, no docket, no real name.

    Every value is made up. The registration cannot be a real one (an FAA number does not
    start with a zero), and the make and model name nobody's aircraft.
    """
    return Evidence(
        case_id="INVENTED-SHAPE-PROBE",
        docket_url=None,
        prelim_narrative=(
            "The single-engine airplane touched down on a dry paved runway, bounced, and "
            "landed hard on the second touchdown. The nose landing gear collapsed and the "
            "airplane slid to a stop on the runway. The pilot reported no injuries."
        ),
        aircraft_make="EXAMPLE AIRCRAFT",
        aircraft_model="EX-100",
        registration="N01234",
        engine_type="Reciprocating",
        pilot_certificates=("Private",),
        pilot_total_hours=350.0,
        pilot_hours_in_type=40.0,
        weather_condition="Visual (VMC)",
        phase_of_flight="Landing",
        injury_level="None",
    )


def invented_payload() -> Payload:
    """The invented case as the loop's first user message would carry it."""
    return Payload.from_evidence(invented_evidence())


def system_text() -> str:
    """The loop's system text: long enough (about 20,000 characters) for the cache to engage."""
    return texts.system_text(load_tables(), GUIDANCE)


# The invented case's answer, in record_hypothesis's shape: a hard landing at touchdown, then the
# nose gear's collapse, with a pilot finding. Codes from the code tables; every sentence says it
# is invented, so none can be an investigator's (or the NTSB's) wording.
_INVENTED_ANSWER = {
    "evidence_narrative": "Invented for the shape probe: a bounce, a hard second touchdown, and "
    "the nose gear's collapse.",
    "occurrence": [
        {"phase": "551", "event": "092", "probability": 0.6},
        {"phase": "551", "event": "094", "probability": 0.2},
    ],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
    "probable_cause": "Invented for the shape probe: a hard landing after a bounced touchdown.",
    "lay_explanation": "Invented for the shape probe: the plane came down too hard.",
    "confidence": 0.6,
    "abstain": False,
    "evidence_used": ["prelim_narrative", "phase_of_flight"],
}
# The document a later trigger re-sends, invented: the case has no docket (the payload's shape is
# the one under test, not its words).
INVENTED_DOCUMENT = (
    "Docket item 1, 1 page.\n[page 1 of 1]\nInvented for the shape probe: the nose landing gear "
    "was bent after the second touchdown."
)


def invented_answer(tables: CodeTables) -> Hypothesis:
    """The invented case's first answer, parsed as the loop parses one (``parse_hypothesis``)."""
    return parse_hypothesis(json.dumps(_INVENTED_ANSWER), tables)


def arm_b_system_text(tables: CodeTables) -> str:
    """Arm B's system text, as ``scoring/runner.py`` composes it with S3's guidance.

    The answer prompt, the code tables (no case number) and the guidance: what arm B's
    post-pass sends.
    """
    return (
        f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables)}{prompt.guidance_block(GUIDANCE)}"
    )


def invented_document_payload() -> Payload:
    """An invented document, as a later trigger's opening re-sends one.

    A ``docket_documents`` payload, through the splitter's evidence renderer, like every payload.
    """
    return Payload.from_evidence(
        Evidence(
            case_id=invented_evidence().case_id,
            docket_url=None,
            docket_documents=(INVENTED_DOCUMENT,),
        )
    )


def arm_b_request(
    variant: Variant, *, tables: CodeTables, stats: CodingStats, payload: Payload
) -> BatchRequest:
    """Arm B's forced answer after its fixed turn, built by ``FixedToolsLoop`` (call ``armb``).

    The turn holds the invented answer as its content and four tool calls (``fixed-1`` to
    ``fixed-4``, the case's group being ``Landing``), each answered by its tool's own text from
    ``stats``; the call forces ``submit_answer``. The loop's cap is the probe's.

    Raises:
        ConfigurationError: the loop built no call (its estimate passed the cap).
    """
    answer = invented_answer(tables)
    config = LoopConfig(
        tables=tables,
        stats=stats,
        guidance=GUIDANCE,
        exclusions=frozenset(),
        cap_usd=RESERVE_USD,
        price_variant=variant,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    raw = {"ntsbNumber": invented_evidence().case_id}
    loop = FixedToolsLoop(
        raw,
        payload,
        arm_b_system_text(tables),
        answer,
        later.as_recorded(answer),
        "Landing",
        config,
    )
    call = loop.next_call()
    if call is None:
        raise ConfigurationError("the arm B loop built no call within the probe's cap")
    return BatchRequest(
        custom_id=f"s3-shape-{variant}-armb",
        payload=call.payload,
        settings=call.settings,
        system=call.system,
        history=call.history,
    )


def later_request(variant: Variant, *, tables: CodeTables, payload: Payload) -> BatchRequest:
    """A later trigger's first call after its opening, built by ``later.opening`` (call ``later``).

    The opening is the invented answer as a ``record_hypothesis`` call (id ``"prior"``, no
    content) and the tool turn that answers it: the prior summary as its tool text and, standing
    in for the documents read before, the invented document as its payload. New structured
    evidence is taken to have arrived, so the call forces ``record_hypothesis`` (H0), with the
    loop's system text and tools.
    """
    prior = Prior(trigger=1, last_hypothesis=invented_answer(tables), reads=(), read=())
    opening = later.opening(
        prior, None, steps.Shelf(), frozenset(), coding=True, new_structured=True
    )
    assistant, result = opening.history
    answered = Turn(
        role="tool",
        tool_call_id=result.tool_call_id,
        payload=invented_document_payload(),
        tool_text=result.tool_text,
    )
    settings = ModelSettings(
        model=sources.DEFAULT_MODEL,
        price_variant=variant,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        tools=schemas.TOOL_DEFINITIONS,
        reasoning_effort=sources.DEFAULT_REASONING_EFFORT,
        tool_choice=steps.tool_choice(opening.step),
        parallel_tool_calls=False,
    )
    return BatchRequest(
        custom_id=f"s3-shape-{variant}-later",
        payload=payload,
        settings=settings,
        system=texts.system_text(tables, GUIDANCE),
        history=(assistant, answered),
    )


def shape_requests(
    *, tables: CodeTables, stats: CodingStats, payload: Payload
) -> dict[str, BatchRequest]:
    """The two shape calls' requests on each variant, by call name (``standard-armb`` ...).

    Built once, before any money moves: nothing in them depends on a reply.
    """
    requests: dict[str, BatchRequest] = {}
    for variant in VARIANTS:
        requests[f"{variant}-armb"] = arm_b_request(
            variant, tables=tables, stats=stats, payload=payload
        )
        requests[f"{variant}-later"] = later_request(variant, tables=tables, payload=payload)
    return requests


def shape_stats() -> CodingStats:
    """S3's statistics, which arm B's post-pass counts in (decision 0129)."""
    return load_stats("s3")


# ------------------------------------------------------------------------------------------
# A client that keeps what it sent and what came back
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Exchange:
    """One HTTP request the client made: as sent, and as it came back (or why it did not)."""

    path: str
    method: str
    body: dict[str, object] | None
    response: dict[str, object] | None
    error: str | None


class RecordingClient(OpenRouterClient):
    """The real client, which also keeps every exchange for the fixtures.

    Everything else (rate limit, retries, the batch client's use of ``request_json``) is the
    parent's, so the probe exercises the code path the loop will use.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = sources.OPENROUTER_BASE_URL,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(api_key, base_url=base_url, sleep=sleep)
        self.exchanges: list[Exchange] = []

    def request_json(
        self,
        path: str,
        *,
        method: str,
        body: dict[str, object] | None = None,
        retry: bool = True,
    ) -> dict[str, object]:
        """The parent's call, recording its body and its response or its error."""
        try:
            response = super().request_json(path, method=method, body=body, retry=retry)
        except ModelError as error:
            self.exchanges.append(Exchange(path, method, body, None, str(error)))
            raise
        self.exchanges.append(Exchange(path, method, body, response, None))
        return response


# ------------------------------------------------------------------------------------------
# What is recorded about one call: flags and numbers, never text
# ------------------------------------------------------------------------------------------


def _token(value: str | None) -> str:
    """A provider's short label (a finish reason, a batch status) if it looks like one."""
    if value is None:
        return "none"
    return value if _TOKEN.fullmatch(value) else "other"


def _safe_tool(name: str) -> str:
    """A tool name if it is one of the loop's seven; the model's own word for it is not kept."""
    return name if name in _TOOL_NAMES else "unknown"


def _status_of(text: str) -> int | None:
    """The HTTP status a ``ModelError`` or a batch result's error text names, if any."""
    found = _STATUS.search(text)
    return int(found.group(1)) if found else None


def _classify(text: str) -> tuple[Literal["refused", "error"], int | None]:
    """Whether a failed call's error text is a refusal or only an error, and its HTTP status.

    Only a deterministic 4xx (not 408 or 429) is a refusal. A 5xx, 408 or 429 after the
    client's retries, or a transport error (no status in the text), says nothing about whether
    the provider would accept the request, so no check may read it as an answer.
    """
    status = _status_of(text)
    if status in _CLIENT_ERRORS and status not in _TRY_AGAIN:
        return "refused", status
    return "error", status


def _number(value: object) -> str:
    return "n/a" if value is None else str(value)


@dataclass(frozen=True)
class CallRecord:
    """Everything the probe keeps about one call; the checks read only this."""

    variant: Variant
    step: Step
    choice: str  # "force record_hypothesis", "force submit_answer" or "required"
    state: State
    note: str = ""  # a short fixed reason for a call that did not run or did not finish
    http_status: int | None = None
    finish_reason: str | None = None
    tool_names: tuple[str, ...] = ()
    arguments_parse: bool | None = None  # None: no tool was called, so nothing to parse
    has_content: bool = False
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    cost_source: str = ""  # "reported", "batch" (the batch's usage.cost) or "priced"
    reasoning_details: bool = False
    seconds: float = 0.0

    @property
    def name(self) -> str:
        """The call's name, which is also its fixture's: ``standard-1`` ... ``batch-2b``."""
        return f"{self.variant}-{self.step}"

    @property
    def accepted(self) -> bool:
        """Whether the provider took the request (a batch that never finished was accepted).

        An ``error`` is neither: nothing says whether the provider took the request.
        """
        return self.state in {"answered", "unfinished"}

    @property
    def called_a_tool(self) -> bool:
        """Whether the reply called any tool at all."""
        return bool(self.tool_names)

    def render(self) -> str:
        """One line of ``key=value`` flags and numbers."""
        if self.state == "not run":
            return f"{self.name}: choice={self.choice} not run ({self.note})"
        accepted = "unknown" if self.state == "error" else "yes" if self.accepted else "no"
        parts = [f"choice={self.choice}", f"accepted={accepted}"]
        if self.http_status is not None:
            parts.append(f"http={self.http_status}")
        if self.state in {"refused", "error", "unfinished"}:
            parts.append(f"({self.note})")
            return f"{self.name}: {' '.join(parts)}"
        cost = "n/a" if self.cost_usd is None else f"${self.cost_usd:.6f}"
        parses = None if self.arguments_parse is None else "yes" if self.arguments_parse else "no"
        parts += [
            f"finish={_number(self.finish_reason)}",
            f"tools={','.join(self.tool_names) or 'none'}",
            f"called={'yes' if self.called_a_tool else 'no'}",
            f"args_parse={_number(parses)}",
            f"content={'yes' if self.has_content else 'no'}",
            f"prompt={_number(self.prompt_tokens)}",
            f"cached={_number(self.cached_tokens)}",
            f"completion={_number(self.completion_tokens)}",
            f"reasoning={_number(self.reasoning_tokens)}",
            f"cost={cost} ({self.cost_source or 'none'})",
            f"reasoning_details={'yes' if self.reasoning_details else 'no'}",
            f"seconds={self.seconds:.1f}",
        ]
        return f"{self.name}: {' '.join(parts)}"


# ------------------------------------------------------------------------------------------
# The conversation
# ------------------------------------------------------------------------------------------


class _BatchTimeoutError(Exception):
    """A batch did not finish within ``BATCH_DEADLINE_SECONDS``."""


@dataclass(frozen=True)
class _Answer:
    record: CallRecord
    reply: ModelReply | None


def _choice_label(choice: str | dict[str, object] | None) -> str:
    """``required``, or ``force <tool>`` for a ``tool_choice`` that names one (``none`` unset)."""
    if choice is None:
        return "none"
    if isinstance(choice, str):
        return choice
    function = choice["function"]
    name = function["name"] if isinstance(function, dict) else "unknown"
    return f"force {name}"


def _follow(answer: _Answer, what: str, text: str) -> tuple[Turn, ...] | str:
    """The turns that answer a reply's tool calls, or the reason there is nothing to answer.

    The first call gets ``text``; any further call in the same reply gets the loop's "only one
    call is run per turn" line, because a tool result is owed for every call id.
    """
    reply = answer.reply
    if reply is None:
        return f"{what} was not answered"
    if not reply.tool_calls:
        return f"{what} returned no tool call"
    assistant = Turn(
        role="assistant",
        content=reply.content,
        tool_calls=reply.tool_calls,
        reasoning_details=reply.reasoning_details,
    )
    results = tuple(
        Turn(
            role="tool",
            tool_call_id=call.call_id,
            tool_text=ToolText.of(text if index == 0 else texts.ONE_CALL),
        )
        for index, call in enumerate(reply.tool_calls)
    )
    return (assistant, *results)


class Probe:
    """Runs the conversation at both price variants and keeps what it saw.

    ``shapes`` holds the two shape calls' requests by call name (``shape_requests``): each
    variant's chain is followed by its ``armb`` and ``later`` calls, which depend on no reply.
    """

    def __init__(  # noqa: PLR0913 -- one seam per thing a test replaces (clock, sleep, output).
        self,
        http: RecordingClient,
        *,
        tables: CodeTables,
        system: str,
        payload: Payload,
        shapes: Mapping[str, BatchRequest],
        fixtures_dir: Path | None = None,
        cap_usd: float = RESERVE_USD,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_record: Callable[[CallRecord], None] = lambda _record: None,
    ) -> None:
        self._http = http
        self._batch = BatchClient(http)
        self._tables = tables
        self._system = system
        self._payload = payload
        self._shapes = dict(shapes)
        self._fixtures_dir = fixtures_dir
        self._cap_usd = cap_usd
        self._clock = clock
        self._sleep = sleep
        self._on_record = on_record
        self.records: list[CallRecord] = []
        self.requests: dict[str, BatchRequest] = {}
        self.spent = 0.0

    @property
    def calls_made(self) -> int:
        """How many calls were sent (a call that was skipped is not one)."""
        return sum(1 for record in self.records if record.state != "not run")

    def run(self) -> tuple[CallRecord, ...]:
        """Run calls 1, 2, 3, 2b, armb and later at the standard price, then at the batch price."""
        for variant in VARIANTS:
            self._chain(variant)
            for shape in SHAPES:
                self._shape(variant, shape)
        return tuple(self.records)

    def _shape(self, variant: Variant, shape: Shape) -> _Answer:
        """One shape call: its request was built before the run, so no reply decides it."""
        request = self._shapes[f"{variant}-{shape}"]
        return self._send(variant, shape, request, _choice_label(request.settings.tool_choice))

    def _chain(self, variant: Variant) -> None:
        first = self._step(variant, "1", (), schemas.force("record_hypothesis"))
        after_first = _follow(first, "call 1", texts.CODE_NOW)
        second = self._step(variant, "2", after_first, schemas.REQUIRED)
        after_second: tuple[Turn, ...] | str
        if isinstance(after_first, str):
            after_second = after_first
        else:
            follow = _follow(second, "call 2", PROBE_RESULT)
            after_second = follow if isinstance(follow, str) else (*after_first, *follow)
        self._step(variant, "3", after_second, schemas.force("submit_answer"))
        passed_back = after_first
        if (
            not isinstance(after_first, str)
            and first.reply is not None
            and not first.reply.reasoning_details
        ):
            passed_back = "call 1 returned no reasoning_details"
        self._step(variant, "2b", passed_back, schemas.REQUIRED, pass_reasoning=True)

    def _step(
        self,
        variant: Variant,
        step: Step,
        history: tuple[Turn, ...] | str,
        choice: str | dict[str, object],
        *,
        pass_reasoning: bool = False,
    ) -> _Answer:
        label = _choice_label(choice)
        if isinstance(history, str):
            return self._finish(_skipped(variant, step, label, history))
        settings = ModelSettings(
            model=sources.DEFAULT_MODEL,
            price_variant=variant,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=schemas.TOOL_DEFINITIONS,
            reasoning_effort=sources.DEFAULT_REASONING_EFFORT,
            tool_choice=choice,
            parallel_tool_calls=False,
            pass_reasoning=pass_reasoning,
        )
        request = BatchRequest(
            custom_id=f"s3-shape-{variant}-{step}",
            payload=self._payload,
            settings=settings,
            system=self._system,
            history=history,
        )
        return self._send(variant, step, request, label)

    def _send(self, variant: Variant, step: Step, request: BatchRequest, label: str) -> _Answer:
        """Send one request at its variant's price, unless the probe's cap is reached."""
        if self.spent >= self._cap_usd:
            reason = f"cost cap reached (${self.spent:.4f} of ${self._cap_usd:.2f})"
            return self._finish(_skipped(variant, step, label, reason))
        self.requests[f"{variant}-{step}"] = request
        if variant == "standard":
            answer = self._send_standard(request, step, label)
        else:
            answer = self._send_batch(request, step, label)
        self.spent += answer.record.cost_usd or 0.0
        return self._finish(answer)

    def _finish(self, answer: _Answer) -> _Answer:
        self.records.append(answer.record)
        self._on_record(answer.record)
        return answer

    # -- the two ways of sending -----------------------------------------------------------

    def _send_standard(self, request: BatchRequest, step: Step, label: str) -> _Answer:
        name = f"standard-{step}"
        blank = CallRecord("standard", step, label, "refused")
        mark = len(self._http.exchanges)
        started = self._clock()
        try:
            reply = self._http.complete(
                request.payload, request.settings, system=request.system, history=request.history
            )
        except ModelError as error:
            seconds = self._clock() - started
            self._save(name, mark)
            made = self._http.exchanges[mark:]
            if made and made[-1].response is not None:  # HTTP was fine; the body was not a reply
                note = "reply is not a chat completion"
                return _Answer(replace(blank, state="unfinished", note=note, seconds=seconds), None)
            refusal = "the provider refused the request"
            return _Answer(_failure(blank, str(error), refusal=refusal, seconds=seconds), None)
        seconds = self._clock() - started
        self._save(name, mark)
        dollars, source = cost_usd(reply, request.settings)
        record = self._answered(blank, reply, dollars=dollars, source=source, seconds=seconds)
        return _Answer(record, reply)

    def _send_batch(self, request: BatchRequest, step: Step, label: str) -> _Answer:
        name = f"batch-{step}"
        blank = CallRecord("batch", step, label, "refused")
        mark = len(self._http.exchanges)
        started = self._clock()
        try:
            batch_id = self._batch.submit([request])
        except ModelError as error:
            self._save(name, mark)
            refusal = "the provider refused the batch"
            seconds = self._clock() - started
            return _Answer(_failure(blank, str(error), refusal=refusal, seconds=seconds), None)
        try:
            polled = self._batch.wait(
                batch_id, every_seconds=POLL_SECONDS, sleep=self._patience(started)
            )
        except (_BatchTimeoutError, ModelError) as error:
            self._save(name, mark)
            note = (
                "batch did not finish within the deadline"
                if isinstance(error, _BatchTimeoutError)
                else "the batch's status could not be read"
            )
            seconds = self._clock() - started
            return _Answer(replace(blank, state="unfinished", note=note, seconds=seconds), None)
        seconds = self._clock() - started
        self._save(name, mark)
        result = polled.results[0] if polled.results else None
        if result is not None and result.reply is not None:
            dollars, source = cost_usd(result.reply, request.settings)
            if source == "priced" and polled.reported_cost_usd is not None:
                dollars, source = polled.reported_cost_usd, "batch"
            record = self._answered(
                blank, result.reply, dollars=dollars, source=source, seconds=seconds
            )
            return _Answer(record, result.reply)
        if result is not None:
            refusal = "the request failed inside the batch"
            failed = _failure(blank, result.error or "", refusal=refusal, seconds=seconds)
            return _Answer(failed, None)
        if polled.status != "completed":
            # A batch that failed was refused as a whole; one that expired or was cancelled
            # was never answered either way.
            state: State = "refused" if polled.status == "failed" else "error"
            note = f"batch {_token(polled.status)}"
            return _Answer(replace(blank, state=state, note=note, seconds=seconds), None)
        note = "the batch completed with no result"
        return _Answer(replace(blank, state="unfinished", note=note, seconds=seconds), None)

    def _patience(self, started: float) -> Callable[[float], None]:
        """The sleep ``BatchClient.wait`` uses between polls: it gives up at the deadline."""

        def sleep(seconds: float) -> None:
            if self._clock() - started > BATCH_DEADLINE_SECONDS:
                raise _BatchTimeoutError
            self._sleep(seconds)

        return sleep

    def _answered(
        self, blank: CallRecord, reply: ModelReply, *, dollars: float, source: str, seconds: float
    ) -> CallRecord:
        """``blank`` (which names the call) filled in from its reply: flags and numbers only."""
        return replace(
            blank,
            state="answered",
            finish_reason=_token(reply.finish_reason),
            tool_names=tuple(_safe_tool(call.name) for call in reply.tool_calls),
            arguments_parse=self._parses(reply) if reply.tool_calls else None,
            has_content=bool(reply.content and reply.content.strip()),
            prompt_tokens=reply.usage.prompt_tokens,
            cached_tokens=reply.usage.cached_tokens,
            completion_tokens=reply.usage.completion_tokens,
            reasoning_tokens=reply.usage.reasoning_tokens,
            cost_usd=dollars,
            cost_source=source,
            reasoning_details=bool(reply.reasoning_details),
            seconds=seconds,
        )

    def _parses(self, reply: ModelReply) -> bool:
        """Whether every tool call's arguments parse with the loop's own parsers (Task 6)."""
        try:
            for call in reply.tool_calls:
                schemas.parse_call(call.name, call.arguments, self._tables)
        except SchemaError:
            return False
        return True

    # -- fixtures --------------------------------------------------------------------------

    def _save(self, name: str, mark: int) -> None:
        """Save the exchanges since ``mark`` as one redacted request/response pair.

        The request is the first exchange's body (for a batch, the submitted batch); the
        response is the last exchange's (for a batch, its final poll), with every ``error`` in
        it replaced by a fixed token and every id blanked by ``redact``. A call that failed
        is saved with its status and a fixed kind, never the provider's text, which
        ``redact`` (it reads key names) cannot clean.
        """
        if self._fixtures_dir is None:
            return
        made = self._http.exchanges[mark:]
        if not made:
            return
        last = made[-1]
        if last.response is not None:
            response: object = redact(_without_error_text(last.response))
        else:
            state, status = _classify(last.error or "")
            response = {"error": {"status": status, "kind": state}}
        self._fixtures_dir.mkdir(parents=True, exist_ok=True)
        pair = {"request": redact(made[0].body), "response": response}
        (self._fixtures_dir / f"{name}.json").write_text(json.dumps(pair, indent=1) + "\n")


def _failure(blank: CallRecord, text: str, *, refusal: str, seconds: float) -> CallRecord:
    """``blank`` marked ``refused`` (with ``refusal`` as its note) or ``error``, from the text."""
    state, status = _classify(text)
    note = refusal if state == "refused" else ERROR_NOTE
    return replace(blank, state=state, note=note, http_status=status, seconds=seconds)


def _without_error_text(value: object) -> object:
    """``value`` with whatever a provider put under an ``error`` key replaced by a fixed token.

    A failed batch's poll and a failed request's result carry the provider's message there;
    ``redact`` blanks ids by key name and cannot tell what a free-text message holds.
    """
    if isinstance(value, dict):
        return {
            key: (
                ERROR_TEXT_NOT_SAVED
                if key == "error" and child is not None
                else _without_error_text(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_without_error_text(child) for child in value]
    return value


def _skipped(variant: Variant, step: Step, label: str, reason: str) -> _Answer:
    return _Answer(CallRecord(variant, step, label, "not run", note=reason), None)


# ------------------------------------------------------------------------------------------
# The six checks of spec §5.5
# ------------------------------------------------------------------------------------------


def _status(record: CallRecord) -> str:
    return f" HTTP {record.http_status}" if record.http_status is not None else ""


def _verdict(flags: Sequence[bool | None]) -> str:
    """``no`` if any measured answer is no; ``yes`` if all are yes; otherwise not measured."""
    if any(flag is False for flag in flags):
        return "no"
    if flags and all(flag is True for flag in flags):
        return "yes"
    return "not measured"


def _accepts(by: dict[str, CallRecord]) -> str:
    """Check 1: strict tool schemas are accepted, read from each variant's call 1."""
    parts: list[str] = []
    flags: list[bool | None] = []
    for variant in VARIANTS:
        record = by.get(f"{variant}-1")
        if record is not None and record.state == "answered":
            parts.append(f"{variant} accepted")
            flags.append(True)
        elif record is not None and record.state == "refused":
            parts.append(f"{variant} refused{_status(record)}")
            flags.append(False)
        else:
            why = "" if record is None else f" (call 1 {record.state}{_status(record)})"
            parts.append(f"{variant} not measured{why}")
            flags.append(None)
    return f"check 1: {_verdict(flags)} ({'; '.join(parts)})"


def _honoured(record: CallRecord | None, forced: str | None) -> bool | None:
    """Whether a call called the tool it was forced to (or any tool, if only required)."""
    if record is None or record.state != "answered":
        return None
    if forced is None:
        return record.called_a_tool
    return record.called_a_tool and all(name == forced for name in record.tool_names)


def _honours(by: dict[str, CallRecord]) -> str:
    """Check 2: a forced tool call and a required tool call are honoured."""
    parts: list[str] = []
    flags: list[bool | None] = []
    for variant in VARIANTS:
        phrases: list[str] = []
        for step, forced in (("1", "record_hypothesis"), ("2", None), ("3", "submit_answer")):
            record = by.get(f"{variant}-{step}")
            label = f"forced {forced}" if forced else "required"
            flag = _honoured(record, forced)
            flags.append(flag)
            if flag is None or record is None:
                phrases.append(f"{label} not measured")
            elif flag:
                phrases.append(f"{label} honoured")
            else:
                called = ", ".join(dict.fromkeys(record.tool_names))
                detail = f"called {called}" if called else "no tool called"
                phrases.append(f"{label} not honoured ({detail})")
        parts.append(f"{variant}: {', '.join(phrases)}")
    return f"check 2: {_verdict(flags)} ({'; '.join(parts)})"


def _multi_turn(by: dict[str, CallRecord]) -> str:
    """Check 3: a multi-turn conversation with tool results works on batch."""
    phrases: list[str] = []
    flags: list[bool | None] = []
    for step in ("2", "3"):
        record = by.get(f"batch-{step}")
        if record is not None and record.state == "answered":
            phrases.append(f"batch-{step} answered")
            flags.append(True)
        elif record is not None and record.state == "refused":
            phrases.append(f"batch-{step} refused{_status(record)}")
            flags.append(False)
        else:
            state = "not measured" if record is None else f"{record.state}{_status(record)}"
            phrases.append(f"batch-{step} {state}")
            flags.append(None)
    return f"check 3: {_verdict(flags)} ({'; '.join(phrases)})"


def _reasoning_of(variant: str, by: dict[str, CallRecord]) -> tuple[str, str]:  # noqa: PLR0911
    """One variant's answer to check 4: ``required``, ``not required`` or ``not measured``."""
    one, two, back = by.get(f"{variant}-1"), by.get(f"{variant}-2"), by.get(f"{variant}-2b")
    if two is None or two.state not in {"answered", "refused"}:
        return (
            "not measured",
            f"call 2 {'not measured' if two is None else two.state + _status(two)}",
        )
    if one is not None and not one.reasoning_details:
        if two.state == "answered":
            return "not required", (
                "call 1 returned no reasoning_details, so none were passed back; call 2 answered"
            )
        return "not measured", (
            f"call 1 returned no reasoning_details and call 2 was refused{_status(two)}, "
            "so the refusal is not about reasoning"
        )
    if two.state == "answered":
        if back is not None and back.state == "answered":
            delta = (
                f" (prompt {back.prompt_tokens - two.prompt_tokens:+d} tokens)"
                if back.prompt_tokens is not None and two.prompt_tokens is not None
                else ""
            )
            return "not required", (
                f"call 2 answered without reasoning_details; passed back, call 2b answered{delta}"
            )
        if back is not None and back.state == "refused":
            return "not required", (
                "call 2 answered without reasoning_details; "
                f"passing them back was refused{_status(back)}"
            )
        state = "did not run" if back is None else f"{back.state}{_status(back)}"
        return "not required", f"call 2 answered without reasoning_details; call 2b {state}"
    if back is not None and back.state == "answered":
        return "required", (
            f"call 2 refused{_status(two)} without reasoning_details, call 2b answered with them"
        )
    return "not measured", "call 2 was refused and call 2b did not answer"


def _reasoning(by: dict[str, CallRecord]) -> str:
    """Check 4: whether the model's reasoning must be passed back between turns."""
    answers = [(variant, *_reasoning_of(variant, by)) for variant in VARIANTS]
    verdicts = {verdict for _, verdict, _ in answers}
    if "required" in verdicts:
        overall = "required"
    elif verdicts == {"not required"}:
        overall = "not required"
    else:
        overall = "not measured"
    return f"check 4: {overall} ({'; '.join(f'{v}: {phrase}' for v, _, phrase in answers)})"


def _reported(records: Sequence[CallRecord]) -> str:
    """Check 5: the cost and cached-token figures each answered response reported."""
    answered = [record for record in records if record.state == "answered"]
    costs = sum(
        1 for r in answered if r.cost_usd is not None and r.cost_source in {"reported", "batch"}
    )
    cached = sum(1 for r in answered if r.cached_tokens is not None)
    total = sum(r.cost_usd or 0.0 for r in records)
    return (
        f"check 5: cost reported on {costs} of {len(answered)} answered calls (a batch call's "
        f"cost is its batch's usage.cost), cached_tokens reported on {cached} of "
        f"{len(answered)}, total ${total:.4f} (per-call figures above)"
    )


def _cache_of(variant: str, by: dict[str, CallRecord]) -> tuple[str, str]:
    """One variant's answer to check 6, from the cached tokens of calls 2 and 3.

    Call 2 follows call 1 with the choice changed from a forced tool to ``required``; call 3
    follows call 2 with it changed back to a forced tool. Whether a hit on either counts as
    "the cache was kept" is the plan's rule: cached tokens above zero.
    """
    two, three = by.get(f"{variant}-2"), by.get(f"{variant}-3")
    if two is None or three is None or two.state != "answered" or three.state != "answered":
        return "not measured", "call 2 or call 3 not answered"
    if two.cached_tokens is None or three.cached_tokens is None:
        return "not measured", "cached_tokens not reported on call 2 or call 3"
    figures = (
        f"call 2 cached {two.cached_tokens} of {two.prompt_tokens} prompt tokens after forced "
        f"to required; call 3 cached {three.cached_tokens} of {three.prompt_tokens} after "
        "required to forced"
    )
    if two.cached_tokens > 0 and three.cached_tokens > 0:
        return "kept", figures
    if two.cached_tokens > 0:
        return "broken", f"broken at call 3 ({figures})"
    if three.cached_tokens > 0:
        return "broken", f"broken at call 2 ({figures})"
    return "no cache seen", (
        f"no cache hit on call 2 or call 3, so forcing cannot be told from no caching ({figures})"
    )


def _cache(by: dict[str, CallRecord]) -> str:
    """Check 6: whether changing ``tool_choice`` between calls keeps the prompt cache."""
    answers = [(variant, *_cache_of(variant, by)) for variant in VARIANTS]
    verdicts = [verdict for _, verdict, _ in answers]
    if "broken" in verdicts:
        overall = "broken"
    elif all(verdict == "kept" for verdict in verdicts):
        overall = "kept"
    elif "no cache seen" in verdicts:
        overall = "no cache seen"
    else:
        overall = "not measured"
    return f"check 6: {overall} ({'; '.join(f'{v}: {phrase}' for v, _, phrase in answers)})"


def _shape_accepted(by: dict[str, CallRecord], shape: Shape, number: int, what: str) -> str:
    """Checks 7 and 8: whether a shape call's request was accepted, read from each variant.

    ``yes`` when every variant answered, ``no`` when any refused, else ``not measured`` (an
    error, a batch that did not finish, a call that did not run). Each variant's phrase adds the
    tool its reply called and whether the arguments parsed: flags only.
    """
    parts: list[str] = []
    flags: list[bool | None] = []
    for variant in VARIANTS:
        record = by.get(f"{variant}-{shape}")
        if record is not None and record.state == "answered":
            called = ", ".join(dict.fromkeys(record.tool_names)) or "no tool"
            parses = "n/a" if record.arguments_parse is None else _yes(record.arguments_parse)
            parts.append(f"{variant} accepted, called {called}, args parse {parses}")
            flags.append(True)
        elif record is not None and record.state == "refused":
            parts.append(f"{variant} refused{_status(record)}")
            flags.append(False)
        else:
            why = "not run" if record is None else f"{record.state}{_status(record)}"
            parts.append(f"{variant} not measured ({why})")
            flags.append(None)
    return f"check {number}: {what} accepted: {_verdict(flags)} ({'; '.join(parts)})"


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def checks(records: Sequence[CallRecord]) -> list[str]:
    """The checks as ``check <n>: <answer>`` lines, derived from the records.

    Checks 1 to 6 are spec §5.5's. Check 7 reads the ``armb`` calls (arm B's fixed turn) and
    check 8 the ``later`` calls (a later trigger's opening): the two request shapes the loop's
    other calls do not send.
    """
    by = {record.name: record for record in records}
    return [
        _accepts(by),
        _honours(by),
        _multi_turn(by),
        _reasoning(by),
        _reported(records),
        _cache(by),
        _shape_accepted(by, "armb", 7, "arm B's fixed turn"),
        _shape_accepted(by, "later", 8, "a later trigger's prior turn"),
    ]


def notes(records: Sequence[CallRecord]) -> list[str]:
    """What the six checks do not say: parallel calls, replies with no tool call, bad arguments."""
    answered = [record for record in records if record.state == "answered"]
    many = [r.name for r in answered if len(r.tool_names) > 1]
    none = [f"{r.name} ({r.choice})" for r in answered if not r.called_a_tool]
    bad = [r.name for r in answered if r.arguments_parse is False]
    return [
        (
            f"note: more than one tool call in one reply despite parallel_tool_calls=false: "
            f"{', '.join(many)}"
            if many
            else "note: parallel_tool_calls=false held on every answered call"
        ),
        (
            f"note: replies that called no tool (the system text still ends its answer prompt "
            f"with 'Reply only with JSON matching the schema'): {', '.join(none)}"
            if none
            else "note: every answered call called a tool"
        ),
        (
            f"note: tool arguments that did not parse with the loop's parsers: {', '.join(bad)}"
            if bad
            else "note: every tool call's arguments parsed with the loop's parsers"
        ),
    ]


def report(records: Sequence[CallRecord], *, header: Sequence[str]) -> str:
    """The results file: a header, one line per call, the eight checks, the notes, the total."""
    total = sum(record.cost_usd or 0.0 for record in records)
    made = sum(1 for record in records if record.state != "not run")
    lines = [
        *header,
        "",
        "calls",
        *(record.render() for record in records),
        "",
        *checks(records),
        "",
        *notes(records),
        "",
        f"total cost ${total:.4f} over {made} calls",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------
# The command
# ------------------------------------------------------------------------------------------


def _write_readme(fixtures_dir: Path, job_id: str, started: datetime) -> None:
    """A note beside the saved pairs, as ``scripts/openrouter_probe.py`` writes one."""
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    (fixtures_dir / "README.md").write_text(
        "# Saved OpenRouter requests and responses: the native-tool shape probe\n\n"
        f"Written by `scripts/s3_shape_probe.py` (job `{job_id}`, {started:%Y-%m-%d}) with model "
        f"`{sources.DEFAULT_MODEL}` (batch: `{sources.DEFAULT_MODEL}:batch`), on an invented case "
        "with no docket. Ids and key material are redacted. `standard-N` is one chat "
        "completion; `batch-N` is a one-request batch (the submitted batch, and its final "
        "poll). Calls 1, 2 and 3 force `record_hypothesis`, require any tool and force "
        "`submit_answer`; `2b` is call 2 with call 1's `reasoning_details` passed back. `armb` "
        "is arm B's forced answer after its fixed turn (a first answer and four tool calls "
        "`fixed-1` to `fixed-4`, each answered); `later` is a later trigger's forced call after "
        "its opening (a `record_hypothesis` call with id `prior`, answered by a payload and a "
        "tool text). A call "
        "that failed holds its HTTP status and a fixed kind (`refused` or `error`) where the "
        "response would be; any error text in a saved poll is replaced by a fixed token, because "
        "provider text cannot be redacted by key. The "
        "answers are in `docs/results/s3-shape-probe.txt` (spec §5.5).\n"
    )


def _header(job_id: str, sha: str, dirty: bool, system: str, payload: Payload) -> list[str]:
    return [
        "S3 native-tool shape probe (spec section 5.5)",
        f"job {job_id}",
        f"commit {sha} ({'uncommitted changes' if dirty else 'clean tree'})",
        f"model {sources.DEFAULT_MODEL}, reasoning {sources.DEFAULT_REASONING_EFFORT}, "
        f"max output tokens {MAX_OUTPUT_TOKENS}",
        f"invented case, no docket: payload {len(payload.text)} characters, system text "
        f"{len(system)} characters, {len(schemas.TOOL_DEFINITIONS)} strict tools",
        "calls armb and later: arm B's fixed turn and a later trigger's opening, built by the "
        "agent's own code on the invented case (checks 7 and 8)",
        f"reserve and cap ${RESERVE_USD:.2f}",
    ]


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Run the probe; print the results and, with ``--out``, write them.

    Refuses (exit 1, before any call) when ``OPENROUTER_API_KEY`` is unset or the monthly guard
    has no room for ``RESERVE_USD``. A refusal by the provider is a result, not a failure: the
    probe exits 0 and the checks say what was refused.
    """
    parser = argparse.ArgumentParser(
        prog="s3_shape_probe", description="The S3.1 native-tool shape probe (spec section 5.5)."
    )
    parser.add_argument("--out", type=Path, default=None, metavar="PATH", help="also write here")
    parser.add_argument(
        "--fixtures-dir", type=Path, default=FIXTURES_DIR, metavar="DIR", help="pairs go here"
    )
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        key = settings.require_openrouter_key()
        started = now()
        sha, dirty = gitinfo.commit_state()
        job_id = f"s3-shape-probe-{started:%Y%m%dT%H%M%S}-{sha}"
        # Everything that can fail for a reason that has nothing to do with money is built
        # before the reservation, so nothing between it and the ``try`` below can leave it open.
        tables = load_tables()
        system = system_text()
        payload = invented_payload()
        shapes = shape_requests(tables=tables, stats=shape_stats(), payload=payload)
        reserve_within_budget(
            settings.runs_dir, job_id, RESERVE_USD, settings.monthly_budget_usd, now=started
        )
    except (ConfigurationError, BudgetError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1

    subject: Probe | None = None
    try:
        with RecordingClient(key, base_url=settings.openrouter_base_url, sleep=sleep) as http:
            subject = Probe(
                http,
                tables=tables,
                system=system,
                payload=payload,
                shapes=shapes,
                fixtures_dir=args.fixtures_dir,
                cap_usd=RESERVE_USD,
                clock=clock,
                sleep=sleep,
                on_record=lambda record: print(record.render(), file=sys.stderr),
            )
            records = subject.run()
        # The results are paid for: they are printed and written before the bookkeeping below,
        # so a failure in it cannot lose them.
        text = report(records, header=_header(job_id, sha, dirty, system, payload))
        print(text)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n")
    finally:
        try:
            if subject is not None and subject.calls_made:
                write_spend(
                    settings.runs_dir,
                    SpendRecord(
                        job_id=job_id,
                        kind=SPEND_KIND,
                        model=sources.DEFAULT_MODEL,
                        started=started,
                        calls=subject.calls_made,
                        cost_usd=subject.spent,
                        commit_sha=sha,
                        dirty=dirty,
                    ),
                )
                _write_readme(args.fixtures_dir, job_id, started)
        finally:
            settle(settings.runs_dir, job_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
