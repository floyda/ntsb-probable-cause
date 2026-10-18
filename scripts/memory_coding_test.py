"""The coding test: GPT-6 Luna codes a case from the NTSB's own probable-cause sentence.

Status
    Live tool for the coding memory's pilot (decision 0204), paid on OpenRouter: GPT-6 Luna
    batch, about a cent or less a case. Development only: ``dev-steer-400``, and ``dev-400`` for
    the confirmation of decision 0212 (tables, counts and cause lookup only, once
    ``docs/rounds/memory-confirm-dev400.md`` is committed), and ``dev-seal-400`` for decision
    0213's (those and the embed lookup, once ``docs/rounds/memory-embed-lookup.md`` is committed).
    It refuses a dirty tree before
    anything is read, so every run names a clean commit. Its spend rows are kind
    ``coding-test``: the $40 monthly guard counts them, and so does the side track's $10 line
    (``make mem-spend``, decision 0207).

What it measures
    Coding alone: the reading of the evidence is taken out, so a change in score is the coding's
    (0204 item 1). The payload is the case's probable-cause sentence and nothing else, built by
    ``Payload.for_coding_test``, the declared exception to the request boundary (decision 0205);
    this is the only file that calls it. Four conditions:

    - **tables** (``answer``): arm B's answer, stage 1 then the refinement of the finding items,
      on the coding test's system text (``memory.prompts.coding_system``: the preface, arm B's
      answer text, the code tables and S3's two guidance files).
    - **counts** (``tools``): arm B's fixed coding-tools post-pass (``agent.armb.FixedToolsLoop``,
      unchanged) over a tables run's answers, counting in the ``mem`` statistics (decision 0203).
    - **memory** (``tools --snapshot NAME``): the same, with a checked snapshot appended to the
      system text. Refused until ``docs/rounds/memory-pilot.md`` is committed (0204 item 6).
    - **lookup** (``tools --snapshot NAME --lookup K``): the same, with each case's own system
      text: up to K of the snapshot's lessons, kept or pushed out, matched by script to that
      case's first answer (``memory.lookup``, decision 0210). Refused until
      ``docs/rounds/memory-lookup.md`` is committed. The spec records each case's lesson ids.
    - **cause lookup** (``tools --snapshot NAME --lookup K --applies RUN_ID``): the same, but the
      lessons are the best fitting of those the apply step named for the case's cause sentence
      (``scripts/memory_cause_apply.py``, ``lookup.by_fit``, decision 0211). Refused until
      ``docs/rounds/memory-cause-lookup.md`` is committed.
    - **embed lookup** (``tools --snapshot NAME --lookup 5 --choices RUN_ID``): the same, but each
      case's lessons are those a choices run names, in its order (``scripts/memory_coverage.py``:
      embedding search, or the picking call over it; decision 0213). Refused until
      ``docs/rounds/memory-embed-lookup.md`` is committed.

    ``suggest_codes`` is never called in the counts or memory conditions: the coding test has no
    phase-of-flight evidence, so the post-pass is given no group, and both conditions match.

What it writes
    ``<runs>/<run id>/``: ``spec.json``; ``replies.jsonl`` and ``rounds.jsonl`` (the batch driver's
    record, ``agent.drive.drive_batch``); ``cases.jsonl``, one ``CodingCase`` per case (its final
    answer or its failure, and its priced cost); and one ``spend.jsonl`` row. The spend is the
    rounds' reported costs when every round reported one, else the calls' priced costs (decision
    0135), read from the whole folder. Nothing is committed and only counts are printed.

Resume
    A run that dies is continued with ``--resume RUN_ID`` and the arguments it was started with:
    the folder's ``spec.json`` must match them, and ``drive_batch`` replays the replies on disk
    and waits on a round that was sent and never finished, so no answered call is sent again.
    The one spend row is replaced after every attempt, finished or not, so a resume never counts
    a call twice. A run that dies with a round in flight keeps its budget reservation (the round
    may still be billed) until it is resumed or released (``ntsb-eval release``).

Usage
    uv run python -m scripts.memory_coding_test answer --repeat {a,b} [--sample S]
        [--resume RUN_ID]
    uv run python -m scripts.memory_coding_test tools --source RUN_ID --repeat {a,b}
        [--resume RUN_ID]
    uv run python -m scripts.memory_coding_test tools --source RUN_ID --snapshot NAME
        [--resume RUN_ID]
    uv run python -m scripts.memory_coding_test tools --source RUN_ID --snapshot NAME
        --lookup K [--applies RUN_ID | --choices RUN_ID] [--resume RUN_ID]
"""

import argparse
import contextlib
import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import fields, gitinfo, sources
from ntsb_probable_cause.agent.armb import FixedToolsLoop
from ntsb_probable_cause.agent.drive import (
    REPLIES_FILE,
    ROUNDS_FILE,
    ReplyRow,
    RoundRow,
    drive_batch,
)
from ntsb_probable_cause.agent.later import as_recorded
from ntsb_probable_cause.agent.loop import PASS_REASONING, LoopConfig, PendingCall, estimate_usd
from ntsb_probable_cause.agent.run import log_line, round_costs, round_line
from ntsb_probable_cause.agent.steps import sanitised
from ntsb_probable_cause.agent.trail import StepKind
from ntsb_probable_cause.errors import BudgetError, ConfigurationError, ModelError, SchemaError
from ntsb_probable_cause.memory import lookup, prompts, snapshots
from ntsb_probable_cause.memory.claude import SONNET
from ntsb_probable_cause.memory.lessons import Lesson, Memory
from ntsb_probable_cause.model.batch import BatchClient
from ntsb_probable_cause.model.client import ModelReply, ModelSettings, Payload, Turn, cost_usd
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.scoring import budget, coding_stats, prompt, samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import (
    HYPOTHESIS_SCHEMA,
    REFINEMENT_SCHEMA,
    Hypothesis,
    parse_hypothesis,
    parse_refinement,
)
from ntsb_probable_cause.scoring.records import write_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner
from ntsb_probable_cause.settings import Settings
from scripts._live_fence import refuse_live

# ``gitinfo`` is named so the tests can replace its commit checks through this module.
__all__ = [
    "CodingAnswerLoop",
    "CodingCase",
    "causes",
    "gitinfo",
    "main",
    "refuse_cause_lookup_without_registration",
    "refuse_condition",
    "refuse_lookup_without_registration",
    "refuse_memory_without_registration",
    "refuse_sample",
    "spend_usd",
]

SAMPLE: Final = "dev-steer-400"
CONFIRM_SAMPLE: Final = "dev-400"  # decision 0212's confirmation
CONFIRM_REGISTRATION: Final = Path("docs/rounds/memory-confirm-dev400.md")
# The conditions the confirmation registered; the others stay on the steering slice.
CONFIRM_CONDITIONS: Final = frozenset({"tables", "counts", "cause-lookup"})
SEAL_SAMPLE: Final = "dev-seal-400"  # decision 0213's confirmation of the embedding lookup
EMBED_REGISTRATION: Final = Path("docs/rounds/memory-embed-lookup.md")
SEAL_CONDITIONS: Final = frozenset({"tables", "counts", "cause-lookup", "embed-lookup"})
GUIDANCE: Final = ("r3-loc-stall", "r6-aircraft-control")
REGISTRATION: Final = Path("docs/rounds/memory-pilot.md")
LOOKUP_REGISTRATION: Final = Path("docs/rounds/memory-lookup.md")
CAUSE_LOOKUP_REGISTRATION: Final = Path("docs/rounds/memory-cause-lookup.md")
APPLY_SUMMARY_FILE: Final = "apply.json"  # scripts.memory_cause_apply's files (decision 0211)
APPLIES_FILE: Final = "applies.json"
CHOICES_FILE: Final = "choices.json"  # scripts.memory_coverage's files (decision 0213)
CHOICE_SUMMARY_FILE: Final = "choice.json"
CHOICE_METHODS: Final = frozenset({"embedding", "pick", "fit", "fill"})  # 0213, 0214
APPLY_MODEL: Final = SONNET  # the registered applier (decision 0211, its registration's §4)
APPLY_EFFORT: Final = "high"
CAP_USD: Final = 0.05
EXPECTED_USD_PER_CASE: Final = 0.01
STATS: Final = "mem"
MAX_OUTPUT_TOKENS: Final = 8000
REASONING: Final = "medium"
PRICE_VARIANT: Final = "batch"
SUGGEST_CODES: Final = "omitted: no phase-of-flight evidence"
NO_CAUSE: Final = "no cause"
SOURCE_FAILED: Final = "source failed"
DONE: Final = "done"
CAP: Final = "cap"
SPEC_FILE: Final = "spec.json"
CASES_FILE: Final = "cases.jsonl"
_PROG: Final = "memory_coding_test"

Condition = Literal["tables", "counts", "memory", "lookup", "cause-lookup", "embed-lookup"]
BatchFactory = Callable[[Settings], BatchRunner]
Clock = Callable[[], datetime]


class CodingCase(BaseModel):
    """One case of a coding-test run, as ``cases.jsonl`` holds it.

    Attributes:
        case_id: the case's NTSB number.
        hypothesis: the final answer, refined when the refinement ran; None when the case failed.
        failure: why the case has no answer (``no cause``, ``source failed``, ``cap``,
            ``cap: context``, ``failed: <step>``, ``failed: rounds``); None when it has one.
        cost_usd: the case's calls, priced (``model.client.cost_usd``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    hypothesis: Hypothesis | None
    failure: str | None
    cost_usd: float


# The refusals. -----------------------------------------------------------------------------


def refuse_sample(sample: str) -> None:
    """Refuse every sample but the steering slice, a registered ``dev-400`` or ``dev-seal-400``.

    Raises:
        ConfigurationError: ``sample`` is not ``dev-steer-400`` (decisions 0203, 0204), nor
            ``dev-400`` with ``docs/rounds/memory-confirm-dev400.md`` committed (decision 0212),
            nor ``dev-seal-400`` with ``docs/rounds/memory-embed-lookup.md`` committed (decision
            0213); or the ``mem`` statistics' pool holds it (``coding_stats.refuse_pool_holding``).
    """
    gates = {
        CONFIRM_SAMPLE: (CONFIRM_REGISTRATION, "the confirmation's registration (decision 0212)"),
        SEAL_SAMPLE: (EMBED_REGISTRATION, "the embedding lookup's registration (decision 0213)"),
    }
    if sample in gates:
        registration, waits_for = gates[sample]
        if not gitinfo.is_committed(registration):
            raise ConfigurationError(
                f"{registration} is not committed: {sample} waits for {waits_for}"
            )
    elif sample != SAMPLE:
        raise ConfigurationError(
            f"the coding test runs on {SAMPLE}, and on {CONFIRM_SAMPLE} and {SEAL_SAMPLE} once "
            f"registered (decisions 0203, 0204, 0212, 0213), not on {sample}"
        )
    coding_stats.refuse_pool_holding(STATS, sample)


def refuse_condition(sample: str, condition: Condition) -> None:
    """Refuse a condition its confirmation did not register (decisions 0212, 0213).

    Raises:
        ConfigurationError: ``sample`` is ``dev-400`` and ``condition`` is not tables, counts or
            cause lookup; or it is ``dev-seal-400`` and ``condition`` is not one of those or the
            embed lookup.
    """
    allowed = {
        CONFIRM_SAMPLE: (CONFIRM_CONDITIONS, "0212"),
        SEAL_SAMPLE: (SEAL_CONDITIONS, "0213"),
    }
    if sample in allowed and condition not in allowed[sample][0]:
        raise ConfigurationError(
            f"the {condition} condition is not registered on {sample} "
            f"(decision {allowed[sample][1]})"
        )


def refuse_memory_without_registration() -> None:
    """Refuse the memory condition until the pilot's registration is committed.

    Raises:
        ConfigurationError: ``docs/rounds/memory-pilot.md`` is not committed (0204 item 6).
    """
    if not gitinfo.is_committed(REGISTRATION):
        raise ConfigurationError(
            f"{REGISTRATION} is not committed: the memory condition waits for the pilot's "
            "registration (decision 0204 item 6)"
        )


def refuse_lookup_without_registration() -> None:
    """Refuse the lookup condition until its registration is committed.

    Raises:
        ConfigurationError: ``docs/rounds/memory-lookup.md`` is not committed (0210 item 4).
    """
    if not gitinfo.is_committed(LOOKUP_REGISTRATION):
        raise ConfigurationError(
            f"{LOOKUP_REGISTRATION} is not committed: the lookup condition waits for its "
            "registration (decision 0210 item 4)"
        )


def refuse_cause_lookup_without_registration() -> None:
    """Refuse the cause-lookup condition until its registration is committed.

    Raises:
        ConfigurationError: ``docs/rounds/memory-cause-lookup.md`` is not committed (0211 item 4).
    """
    if not gitinfo.is_committed(CAUSE_LOOKUP_REGISTRATION):
        raise ConfigurationError(
            f"{CAUSE_LOOKUP_REGISTRATION} is not committed: the cause-lookup condition waits for "
            "its registration (decision 0211 item 4)"
        )


def refuse_embed_lookup_without_registration() -> None:
    """Refuse the embed-lookup condition until its registration is committed.

    Raises:
        ConfigurationError: ``docs/rounds/memory-embed-lookup.md`` is not committed (0213 item 11).
    """
    if not gitinfo.is_committed(EMBED_REGISTRATION):
        raise ConfigurationError(
            f"{EMBED_REGISTRATION} is not committed: the embed-lookup condition waits for its "
            "registration (decision 0213 item 11)"
        )


# What the test reads. ----------------------------------------------------------------------


def causes(processed: Path, sample: str = SAMPLE) -> dict[str, str | None]:
    """Every case's probable-cause sentence, in ``sample``'s order; None for none.

    The sentence is verdict text, read through ``fields`` from the raw record; it reaches the
    coding model only through ``Payload.for_coding_test`` (decision 0205), and the learner's
    apply step only through ``scripts/memory_cause_apply.py`` (decision 0211).
    """
    ids = samples.sample_ids(sample)
    raws = samples.load_cases(processed, ids)
    return {
        case_id: fields.probable_cause(raw) or None for case_id, raw in zip(ids, raws, strict=True)
    }


def _settings(schema: dict[str, object], name: str) -> ModelSettings:
    return ModelSettings(
        model=sources.DEFAULT_MODEL,
        price_variant=PRICE_VARIANT,
        reasoning_effort=REASONING,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        json_schema=schema,
        schema_name=name,
    )


# The tables condition's loop. --------------------------------------------------------------


class CodingAnswerLoop:
    """One case's tables condition: stage 1, then the refinement, as arm B answers.

    The interface the batch driver uses (``agent.drive.DrivenLoop``). Each stage is retried once
    after a failed call or a reply its parser rejects, with the rejection appended to the system
    text as the runner appends it (``scoring/runner.py``, ``_two_turns``); a second failure in a
    row stops the case ``failed: <step>``. An answer that abstains or has no findings is not
    refined. The steps are named as ``FixedToolsLoop`` names its answer and refinement calls.

    Args:
        case_id: the case's NTSB number.
        cause: the case's probable-cause sentence, the whole payload.
        system: the coding test's system text (``prompts.coding_system``).
        tables: the code tables the answer chooses from.
        cap_usd: the per-case cap, checked on each call's estimate before it is handed out.
    """

    def __init__(
        self, case_id: str, cause: str, system: str, tables: CodeTables, cap_usd: float = CAP_USD
    ) -> None:
        self._case_id = case_id
        self._payload = Payload.for_coding_test(cause)
        self._system = system
        self._tables = tables
        self._cap = cap_usd
        self._step: Literal["answer", "refine"] = "answer"
        self._rejected: str | None = None
        self._retry = False
        self._calls = 0
        self._pending: PendingCall | None = None
        self._stop: str | None = None
        self._spent = 0.0
        # The stage-1 answer to refine, and its reply text as the model wrote it.
        self._first: tuple[Hypothesis, str] | None = None
        self._final: Hypothesis | None = None

    @property
    def case_id(self) -> str:
        """The case's NTSB number."""
        return self._case_id

    @property
    def call_index(self) -> int:
        """The replies taken so far, failures included."""
        return self._calls

    def stop(self, reason: str) -> None:
        """End the case now with ``reason``; a pending call is dropped, a first reason kept."""
        if self._stop is None:
            self._stop = reason
        self._pending = None

    def next_call(self) -> PendingCall | None:
        """The next call, or None once the case has stopped; the same until accepted."""
        if self._pending is None and self._stop is None:
            call = self._build()
            if self._spent + call.estimated_usd > self._cap:
                self._stop = CAP
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
        """Take the reply to the pending call, or its failure (``reply`` None).

        ``error``, the times and the batch id are the driver's record (``replies.jsonl``); the
        loop keeps none of them.

        Raises:
            RuntimeError: no call is pending.
        """
        del error, sent_at, returned_at, batch_id
        call = self._pending
        if call is None:
            raise RuntimeError("accept() called with no call pending")
        self._pending = None
        self._calls += 1
        if reply is None:
            self._break(None)
            return
        self._spent += cost_usd(reply, call.settings)[0]
        text = reply.content or ""
        try:
            if call.step == "answer":
                self._take_answer(parse_hypothesis(text, self._tables), text)
            else:
                self._final, self._stop = (
                    parse_refinement(text, self._tables, self._answer()[0]),
                    DONE,
                )
        except SchemaError as rejected:
            self._break(sanitised(rejected))

    def outcome(self) -> tuple[Hypothesis | None, str | None, str | None, float]:
        """The final answer, its JSON, the failure (None when done) and the priced cost.

        Raises:
            RuntimeError: the case has not stopped.
        """
        if self._stop is None:
            raise RuntimeError("the case has not stopped")
        answer = self._final
        recorded = None if answer is None else answer.model_dump_json()
        return answer, recorded, None if self._stop == DONE else self._stop, self._spent

    def _take_answer(self, answer: Hypothesis, text: str) -> None:
        self._retry, self._rejected = False, None
        if answer.abstain or not answer.findings:
            self._final, self._stop = answer, DONE
        else:
            self._first, self._step = (answer, text), "refine"

    def _break(self, rejected: str | None) -> None:
        """A failed or rejected call: ask once more; a second failure stops the case."""
        if self._retry:
            self._stop = f"failed: {self._step}"
        else:
            self._retry, self._rejected = True, rejected

    def _answer(self) -> tuple[Hypothesis, str]:
        if self._first is None:  # the refinement follows an answer, always
            raise RuntimeError("refinement with no answer")
        return self._first

    def _build(self) -> PendingCall:
        step: StepKind = self._step
        history: tuple[Turn, ...] = ()
        if self._step == "answer":
            settings = _settings(HYPOTHESIS_SCHEMA, "hypothesis")
            system = self._system
        else:
            answer, text = self._answer()
            settings = _settings(REFINEMENT_SCHEMA, "refinement")
            system = f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(answer, self._tables)}"
            history = (Turn(role="assistant", content=text),)
        if self._rejected is not None:
            system = f"{system}\n\n{prompt.REJECTED}{self._rejected}"
        return PendingCall(
            payload=self._payload,
            settings=settings,
            system=system,
            history=history,
            step=step,
            estimated_usd=estimate_usd(settings, system, history, len(self._payload.text)),
        )


# Running a condition. ----------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """What both subcommands share: settings, the batch runner's maker, the clock, the commit."""

    settings: Settings
    batch_factory: BatchFactory
    now: Clock
    commit: tuple[str, bool]

    @property
    def runs_dir(self) -> Path:
        """The runs directory (``NTSB_RUNS_DIR``)."""
        return self.settings.runs_dir


Loop = CodingAnswerLoop | FixedToolsLoop


def _outcome(loop: Loop) -> tuple[Hypothesis | None, str | None, float]:
    """A finished loop's final answer, failure and priced cost, for either kind of loop."""
    if isinstance(loop, CodingAnswerLoop):
        answer, _recorded, failure, cost = loop.outcome()
        return answer, failure, cost
    outcome = loop.outcome
    failure = None if outcome.stop_reason == DONE else outcome.stop_reason
    return outcome.answer, failure, outcome.cost_usd


def _reply_rows(folder: Path) -> list[ReplyRow]:
    """The replies the driver wrote; a damaged line (a killed process) is passed over."""
    path = folder / REPLIES_FILE
    rows: list[ReplyRow] = []
    if path.is_file():
        for line in path.read_text().splitlines():
            with contextlib.suppress(ValueError):
                rows.append(ReplyRow.model_validate_json(line))
    return rows


def spend_usd(folder: Path) -> float:
    """The run's spend: the rounds' reported costs when every round reported one (decision 0135).

    Else every reply priced as the loops price it (``model.client.cost_usd``; only the model id
    in the settings decides the price, and every call of a run has the same one). Read from the
    folder, so a run that died part-way is counted the same way.
    """
    reported = round_costs(folder).reported_usd
    if reported is not None:
        return reported
    pricing = _settings(HYPOTHESIS_SCHEMA, "hypothesis")
    return sum(
        cost_usd(row.reply, pricing)[0] for row in _reply_rows(folder) if row.reply is not None
    )


def _round_open(folder: Path) -> bool:
    """Whether an attempt left a batch round sent and never finished: it may still be billed."""
    path = folder / ROUNDS_FILE
    latest: dict[int, RoundRow] = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            with contextlib.suppress(ValueError):
                row = RoundRow.model_validate_json(line)
                latest[row.round] = row
    return any(row.finished_at is None for row in latest.values())


def _write_spend(ctx: Context, run_id: str, started: datetime) -> None:
    """Replace the run's one spend row with what its folder now says it cost.

    One row per run, rewritten after every attempt (decision 0135's rule, over every round and
    reply the folder holds, earlier attempts included), so a resume never counts a call twice.
    """
    folder = ctx.runs_dir / run_id
    (folder / budget.SPEND_FILE).unlink(missing_ok=True)
    sha, dirty = ctx.commit
    budget.write_spend(
        ctx.runs_dir,
        budget.SpendRecord(
            job_id=run_id,
            kind="coding-test",
            model=sources.DEFAULT_MODEL,
            started=started,
            calls=len(_reply_rows(folder)),
            cost_usd=spend_usd(folder),
            commit_sha=sha,
            dirty=dirty,
        ),
    )


@dataclass(frozen=True)
class Plan:
    """One run: its id, its spec, the loops it drives, and the cases it records but never sends.

    Attributes:
        run_id: the run folder's name.
        spec: what ``spec.json`` holds, less its start time.
        loops: one loop per case that is sent.
        skipped: the cases recorded with a failure and no call, and why.
        order: every case, in the order ``cases.jsonl`` lists them.
    """

    run_id: str
    spec: dict[str, object]
    loops: Sequence[Loop]
    skipped: Mapping[str, str]
    order: Sequence[str]


def _resumed_start(folder: Path, spec: Mapping[str, object]) -> datetime:
    """Check a folder can be resumed with this spec, and return when it was first started.

    Raises:
        ConfigurationError: no such folder or no readable ``spec.json``; a run that finished
            (``cases.jsonl`` exists); or a spec that differs from what the arguments give (the
            differing fields are named).
    """
    try:
        stored = json.loads((folder / SPEC_FILE).read_text())
    except OSError, ValueError:
        raise ConfigurationError(f"{folder.name}: no readable {SPEC_FILE} to resume") from None
    if (folder / CASES_FILE).exists():
        raise ConfigurationError(f"{folder.name} finished: there is nothing to resume")
    if not isinstance(stored, dict) or not isinstance(stored.get("started"), str):
        raise ConfigurationError(f"{folder.name}: {SPEC_FILE} records no start time")
    wanted = json.loads(json.dumps(spec))
    given = {k: v for k, v in stored.items() if k != "started"}
    differ = sorted(k for k in wanted.keys() | given.keys() if wanted.get(k) != given.get(k))
    if differ:
        raise ConfigurationError(
            f"{folder.name} was started with other settings ({', '.join(differ)} differ): "
            "resume it with the arguments and commit it was started with"
        )
    return datetime.fromisoformat(stored["started"])


def _run(ctx: Context, plan: Plan, *, resume: bool) -> int:
    """Reserve, drive every loop in batch rounds, write the cases, then the spend row.

    A fresh run refuses an existing folder. A resume (``--resume``) checks the folder's spec
    against the arguments and calls ``drive_batch`` on the same folder, which replays the replies
    on disk and waits on a round that was sent and never finished, so no answered call is sent
    again. The spend row is rewritten after every attempt, finished or not (``_write_spend``).
    The reservation is settled when the run finishes, or when it stops with no round open; a run
    that dies with a round in flight keeps its reservation, since that round may still be billed,
    until it is resumed (or released by hand, ``ntsb-eval release``).
    """
    folder = ctx.runs_dir / plan.run_id
    if resume:
        started = _resumed_start(folder, plan.spec)
    elif folder.exists():
        raise ConfigurationError(
            f"{plan.run_id} exists: resume it with --resume {plan.run_id}, or move it aside "
            "under another name (its spend stays counted) and run again"
        )
    else:
        started = ctx.now()
    batch = ctx.batch_factory(ctx.settings)
    budget.reserve_within_budget(
        ctx.runs_dir,
        plan.run_id,
        len(plan.loops) * EXPECTED_USD_PER_CASE,
        ctx.settings.monthly_budget_usd,
        now=ctx.now(),
    )
    action = "resuming" if resume else "starting"
    print(f"{plan.run_id}: {action}, {len(plan.loops)} cases to code, {len(plan.skipped)} not sent")

    def on_round(row: RoundRow, running: int, waited: bool) -> None:
        log_line(ctx.now, lambda: round_line(row, running, waited=waited))

    finished = False
    try:
        if not resume:
            spec = {**plan.spec, "started": started.isoformat()}
            (folder / SPEC_FILE).write_text(json.dumps(spec, indent=1))
        drive_batch(plan.loops, batch, folder=folder, now=ctx.now, on_round=on_round)
        by_case = {loop.case_id: loop for loop in plan.loops}
        rows: list[CodingCase] = []
        for case_id in plan.order:
            if case_id in plan.skipped:
                failure: str | None = plan.skipped[case_id]
                final, cost = None, 0.0
            else:
                final, failure, cost = _outcome(by_case[case_id])
            rows.append(
                CodingCase(case_id=case_id, hypothesis=final, failure=failure, cost_usd=cost)
            )
        write_jsonl(folder / CASES_FILE, rows)
        finished = True
    finally:
        _write_spend(ctx, plan.run_id, started)
        if finished or not _round_open(folder):
            budget.settle(ctx.runs_dir, plan.run_id)
        else:
            print(
                f"{plan.run_id}: a batch round is still open, so its reservation is kept; "
                f"resume with --resume {plan.run_id}, or, once the round can no longer be "
                f"billed, free it with uv run ntsb-eval release {plan.run_id}"
            )
    answered = sum(1 for row in rows if row.hypothesis is not None)
    print(f"{plan.run_id}: {answered} of {len(rows)} cases answered")
    return 0


def _base_spec(
    condition: Condition, repeat: str | None, commit: tuple[str, bool], sample: str = SAMPLE
) -> dict[str, object]:
    return {
        "sample": sample,
        "condition": condition,
        "repeat": repeat,
        "model": sources.DEFAULT_MODEL,
        "reasoning_effort": REASONING,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "price_variant": PRICE_VARIANT,
        "cap_usd": CAP_USD,
        "guidance": list(GUIDANCE),
        "guidance_sha256": prompt.guidance_sha256(GUIDANCE),
        "statistics": STATS,
        "commit": commit[0],
        "dirty": commit[1],
    }


def _processed(settings: Settings) -> Path:
    return settings.data_dir / "processed"


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def answer(args: argparse.Namespace, ctx: Context) -> int:
    """The tables condition on the sample: every case with a cause, coded once."""
    sample = args.sample
    refuse_sample(sample)
    tables = load_tables()
    system = prompts.coding_system(tables, GUIDANCE, None)
    found = causes(_processed(ctx.settings), sample)
    loops = [
        CodingAnswerLoop(case_id, cause, system, tables)
        for case_id, cause in found.items()
        if cause is not None
    ]
    skipped = {case_id: NO_CAUSE for case_id, cause in found.items() if cause is None}
    run_id = args.resume or f"{_stamp(ctx.now())}-{ctx.commit[0]}-{sample}-mem-tables-{args.repeat}"
    spec = {**_base_spec("tables", args.repeat, ctx.commit, sample), "case_ids": list(found)}
    plan = Plan(run_id, spec, loops, skipped, tuple(found))
    return _run(ctx, plan, resume=args.resume is not None)


def _read_source(folder: Path) -> tuple[list[CodingCase], str]:
    """A tables run's cases and its sample, after its spec is checked: refused unless it is one.

    Raises:
        ConfigurationError: no such run, a spec or cases file that cannot be read, or a run that
            is not the tables condition on a sample ``refuse_sample`` allows.
    """
    refuse_live(_PROG, folder)
    try:
        spec = json.loads((folder / SPEC_FILE).read_text())
        rows = [
            CodingCase.model_validate_json(line)
            for line in (folder / CASES_FILE).read_text().splitlines()
        ]
    except (OSError, ValueError) as error:
        raise ConfigurationError(
            f"{folder.name}: not a finished coding-test run ({type(error).__name__})"
        ) from None
    if not isinstance(spec, dict) or spec.get("condition") != "tables":
        raise ConfigurationError(f"{folder.name} is not a tables run: the post-pass needs one")
    sample = str(spec.get("sample"))
    refuse_sample(sample)
    return rows, sample


def _checked_memory(name: str) -> tuple[Memory, str]:
    """A checked snapshot with at least one lesson, and its file's hash.

    Raises:
        ConfigurationError: no registration (0204 item 6), a snapshot ``load_checked`` refuses,
            or one with no lessons (its system text would be the counts condition's).
    """
    refuse_memory_without_registration()
    memory = snapshots.load_checked(name, snapshots.SNAPSHOT_DIR)
    if not memory.lessons:
        raise ConfigurationError(
            f"snapshot {name} holds no lessons: the memory condition would be the counts "
            "condition under another name"
        )
    return memory, snapshots.sha256_of(snapshots.snapshot_path(name, snapshots.SNAPSHOT_DIR))


def read_applies(
    folder: Path, snapshot: str, sha: str, sample: str = SAMPLE
) -> dict[str, frozenset[str]]:
    """An apply run's lesson ids per case, refused unless it read this sample and snapshot.

    Raises:
        ConfigurationError: no finished apply run in ``folder``, one on another sample,
            snapshot, snapshot file or applier, or one where more than 2% of the replies failed
            (decision 0211, its registration's §8).
    """
    refuse_live(_PROG, folder)
    try:
        summary = json.loads((folder / APPLY_SUMMARY_FILE).read_text())
        raw = json.loads((folder / APPLIES_FILE).read_text())
    except (OSError, ValueError) as error:
        raise ConfigurationError(
            f"{folder.name}: not a finished apply run ({type(error).__name__})"
        ) from None
    if not isinstance(summary, dict) or not isinstance(raw, dict):
        raise ConfigurationError(f"{folder.name}: not a finished apply run")
    wanted = {
        "sample": sample,
        "snapshot": snapshot,
        "snapshot_sha256": sha,
        "model": APPLY_MODEL,
        "effort": APPLY_EFFORT,
    }
    differing = [key for key, value in wanted.items() if summary.get(key) != value]
    if differing:
        raise ConfigurationError(f"{folder.name} differs in {', '.join(differing)}")
    failed, sent = summary.get("failed"), summary.get("cases_sent")
    if not isinstance(failed, int) or not isinstance(sent, int) or failed * 100 > sent * 2:
        raise ConfigurationError(
            f"{folder.name}: {failed} of {sent} apply replies failed, past the registered 2%"
        )
    return {str(case_id): frozenset(map(str, ids)) for case_id, ids in raw.items()}


def read_choices(
    folder: Path, snapshot: str, sha: str, sample: str, lesson_ids: Collection[str]
) -> tuple[dict[str, tuple[str, ...]], dict[str, object]]:
    """A choices run's lesson ids per case, in order, and its summary (decision 0213).

    Raises:
        ConfigurationError: no readable choices run in ``folder``; one on another sample,
            snapshot, snapshot file, K, support floor or method, or not made from a clean tree;
            an id that is not a lesson of the snapshot; or more than K ids for a case.
    """
    refuse_live(_PROG, folder)
    try:
        summary = json.loads((folder / CHOICE_SUMMARY_FILE).read_text())
        raw = json.loads((folder / CHOICES_FILE).read_text())
        choices = {str(case_id): tuple(map(str, ids)) for case_id, ids in raw.items()}
    except (OSError, ValueError, AttributeError, TypeError) as error:
        raise ConfigurationError(
            f"{folder.name}: not a finished choices run ({type(error).__name__})"
        ) from None
    if not isinstance(summary, dict):
        raise ConfigurationError(f"{folder.name}: not a finished choices run")
    wanted = {
        "sample": sample,
        "snapshot": snapshot,
        "snapshot_sha256": sha,
        "k": lookup.K,
        "min_applies": lookup.MIN_APPLIES,
    }
    differing = [key for key, value in wanted.items() if summary.get(key) != value]
    if summary.get("method") not in CHOICE_METHODS:
        differing.append("method")
    if summary.get("dirty") is not False:
        differing.append("dirty")
    if differing:
        raise ConfigurationError(f"{folder.name} differs in {', '.join(differing)}")
    for ids in choices.values():
        if len(ids) > lookup.K or not set(ids) <= set(lesson_ids):
            raise ConfigurationError(
                f"{folder.name}: a case has more than {lookup.K} ids, or an id the snapshot lacks"
            )
    return choices, summary


def _tools_run_id(args: argparse.Namespace) -> str:
    """The derived run's id, from the source, and the repeat or the snapshot.

    Raises:
        ConfigurationError: ``--repeat`` missing without ``--snapshot``, or ``--resume`` not the
            id these arguments give.
    """
    if args.applies is not None and args.lookup is None:
        raise ConfigurationError("--applies needs --lookup K")
    if args.choices is not None and (args.lookup is None or args.snapshot is None):
        raise ConfigurationError("--choices needs --snapshot and --lookup K")
    if args.choices is not None and args.applies is not None:
        raise ConfigurationError("--choices and --applies are two conditions: name one")
    if args.snapshot is None:
        if args.lookup is not None:
            raise ConfigurationError("the lookup condition needs --snapshot")
        if args.repeat is None:
            raise ConfigurationError("the counts condition needs --repeat a or b")
        run_id = f"{args.source}-counts-{args.repeat}"
    elif args.choices is not None:
        # One run per choices run: its candidate is the tail of its name (decision 0214).
        candidate = str(args.choices).rsplit("-memory-choices-", 1)[-1]
        for sample in (SAMPLE, SEAL_SAMPLE):
            candidate = candidate.removeprefix(f"{sample}-")
        run_id = f"{args.source}-embedlookup{args.lookup}-{args.snapshot}-{candidate}"
    elif args.applies is not None:
        run_id = f"{args.source}-causelookup{args.lookup}-{args.snapshot}"
    elif args.lookup is not None:
        run_id = f"{args.source}-lookup{args.lookup}-{args.snapshot}"
    else:
        run_id = f"{args.source}-memory-{args.snapshot}"
    if args.resume is not None and args.resume != run_id:
        raise ConfigurationError(
            f"--resume {args.resume} is not the run these arguments make ({run_id})"
        )
    return run_id


def _refuse_lookup_args(args: argparse.Namespace) -> None:
    """Refuse a lookup without its registration, or with K below 1 (decisions 0210, 0211)."""
    if args.lookup is None:
        return
    if args.choices is not None:
        refuse_embed_lookup_without_registration()
    elif args.applies is not None:
        refuse_cause_lookup_without_registration()
    else:
        refuse_lookup_without_registration()
    if args.lookup < 1:
        raise ConfigurationError("--lookup must be at least 1")


def _condition(
    memory: Memory | None,
    k: int | None,
    applied: Mapping[str, frozenset[str]] | None,
    chosen: Mapping[str, tuple[str, ...]] | None,
) -> Condition:
    if memory is None:
        return "counts"
    if k is None:
        return "memory"
    if chosen is not None:
        return "embed-lookup"
    return "lookup" if applied is None else "cause-lookup"


def _picked(  # noqa: PLR0913 -- the memory, K, the three ways to choose, and the tables
    memory: Memory,
    k: int,
    applied: Mapping[str, frozenset[str]] | None,
    row: CodingCase,
    tables: CodeTables,
    *,
    chosen: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[Lesson, ...]:
    """One case's lessons: from a choices run, an apply answer, or the first answer's codes.

    ``chosen`` (decision 0213) is a choices run's ids; ``applied`` is the apply step's (0211);
    with neither, the lessons match the first answer's codes (0210).

    Raises:
        ConfigurationError: the apply run has no answer for the case.
    """
    every = (*memory.lessons, *memory.pushed_out)
    if chosen is not None:  # a case the choices run left out reads the counts text (0213)
        by_id = {lesson.lesson_id: lesson for lesson in every}
        return tuple(by_id[lesson_id] for lesson_id in chosen.get(row.case_id, ()))
    if applied is not None:
        if row.case_id not in applied:
            raise ConfigurationError("the apply run has no answer for a case")
        return lookup.by_fit(every, applied[row.case_id], k=k)
    if row.hypothesis is None:  # the caller skips failed sources; nothing to match
        return ()
    return lookup.lookup(
        every,
        row.hypothesis.occurrence_codes(tables),
        {guess.category6 for guess in row.hypothesis.findings},
        k=k,
    )


def tools(args: argparse.Namespace, ctx: Context) -> int:
    """The counts condition, or the memory condition, or the lookup condition.

    Counts runs over a tables run; memory adds ``--snapshot``; lookup adds ``--lookup K``. The
    memory and lookup conditions ignore ``--repeat``: one run per snapshot and source. The lookup
    condition gives each case its own system text: the counts condition's, followed by up to K of
    the snapshot's lessons, kept or pushed out, matched to that case's first answer
    (``memory.lookup``, decision 0210). A case that matches none reads the counts text. With
    ``--applies RUN_ID`` (the cause-lookup condition, decision 0211) the lessons are instead the
    best fitting of those the apply run named for the case's cause sentence (``lookup.by_fit``);
    no code from the first answer chooses them. With ``--choices RUN_ID`` (the embed-lookup
    condition, decision 0213) they are the ids a choices run names for the case, in its order. The
    sample is the source run's; on ``dev-400`` only counts and cause lookup are allowed (decision
    0212), and on ``dev-seal-400`` those and the embed lookup (decision 0213).
    """
    source = args.source
    run_id = _tools_run_id(args)
    memory: Memory | None = None
    snapshot_sha: str | None = None
    _refuse_lookup_args(args)
    if args.snapshot is not None:
        memory, snapshot_sha = _checked_memory(args.snapshot)
    first, sample = _read_source(ctx.runs_dir / source)
    applied: dict[str, frozenset[str]] | None = None
    if args.applies is not None and snapshot_sha is not None:
        applied = read_applies(ctx.runs_dir / args.applies, args.snapshot, snapshot_sha, sample)
    chosen: dict[str, tuple[str, ...]] | None = None
    choice: dict[str, object] = {}
    if args.choices is not None and snapshot_sha is not None and memory is not None:
        every_id = [lesson.lesson_id for lesson in (*memory.lessons, *memory.pushed_out)]
        chosen, choice = read_choices(
            ctx.runs_dir / args.choices, args.snapshot, snapshot_sha, sample, every_id
        )
    condition = _condition(memory, args.lookup, applied, chosen)
    refuse_condition(sample, condition)
    tables = load_tables()
    config = LoopConfig(
        tables=tables,
        stats=coding_stats.load_stats(STATS),
        guidance=GUIDANCE,
        exclusions=frozenset(),
        cap_usd=CAP_USD,
        price_variant=PRICE_VARIANT,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        max_coding_calls=6,
        pass_reasoning=PASS_REASONING,
        without=frozenset(),
        run_id=run_id,
        commit=ctx.commit,
        model=sources.DEFAULT_MODEL,
        reasoning_effort=REASONING,
    )
    system = prompts.coding_system(tables, GUIDANCE, None if args.lookup else memory)
    found = causes(_processed(ctx.settings), sample)
    loops: list[Loop] = []
    skipped: dict[str, str] = {}
    looked_up: dict[str, list[str]] = {}
    for row in first:
        cause = found.get(row.case_id)
        if row.hypothesis is None:
            skipped[row.case_id] = SOURCE_FAILED
        elif cause is None:
            skipped[row.case_id] = NO_CAUSE
        else:
            case_system = system
            if args.lookup is not None and memory is not None:
                picked = _picked(memory, args.lookup, applied, row, tables, chosen=chosen)
                looked_up[row.case_id] = [lesson.lesson_id for lesson in picked]
                case_system = prompts.coding_system(
                    tables, GUIDANCE, memory.model_copy(update={"lessons": picked})
                )
            # group=None: no phase-of-flight evidence, so no suggest_codes call (module docstring)
            loops.append(
                FixedToolsLoop(
                    {"ntsbNumber": row.case_id},
                    Payload.for_coding_test(cause),
                    case_system,
                    row.hypothesis,
                    as_recorded(row.hypothesis),
                    None,
                    config,
                )
            )
    repeat = args.repeat if memory is None else None  # memory and lookup: one run each
    order = [row.case_id for row in first]
    spec = {
        **_base_spec(condition, repeat, ctx.commit, sample),
        "source_run": source,
        "snapshot": args.snapshot,
        "snapshot_sha256": snapshot_sha,
        "suggest_codes": SUGGEST_CODES,
        "case_ids": order,
    }
    if args.lookup is not None:  # only here, so a counts or memory spec is as it was
        spec |= {
            "lookup_k": args.lookup,
            "lookup_min_applies": lookup.MIN_APPLIES,
            "lookup_lessons": looked_up,
        }
    if applied is not None:  # only here, so a code lookup's spec is as it was
        spec |= {"lookup_by": "cause", "apply_run": args.applies}
    if chosen is not None:  # decision 0213
        spec |= {
            "lookup_by": choice.get("method"),
            "choices_run": args.choices,
            "embedding_model": choice.get("model"),
        }
    plan = Plan(run_id, spec, loops, skipped, order)
    return _run(ctx, plan, resume=args.resume is not None)


def _require_clean(dirty: bool) -> None:
    if dirty:
        raise ConfigurationError("the tree has uncommitted changes: commit first")


def _default_batch(settings: Settings) -> BatchRunner:
    """The real OpenRouter batch client, as ``ntsb-eval`` makes it."""
    http = OpenRouterClient(
        settings.require_openrouter_key(), base_url=settings.openrouter_base_url
    )
    return BatchClient(http)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    batch_factory: BatchFactory = _default_batch,
    now: Clock = _utc_now,
) -> int:
    """Run one condition, or resume one.

    Returns:
        0 on success; 1 on a refusal (dirty tree, sample, source, registration, snapshot,
        budget, an existing folder, a resume that does not match) or a batch the provider
        cancelled or lost.
    """
    parser = argparse.ArgumentParser(prog=_PROG)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("answer", help="the tables condition")
    a.add_argument("--repeat", choices=("a", "b"), required=True)
    a.add_argument(
        "--sample",
        choices=(SAMPLE, CONFIRM_SAMPLE, SEAL_SAMPLE),
        default=SAMPLE,
        help=f"{CONFIRM_SAMPLE} for decision 0212's confirmation, {SEAL_SAMPLE} for 0213's",
    )
    a.add_argument("--resume", metavar="RUN_ID", help="continue this run's folder")
    t = sub.add_parser("tools", help="the counts condition, or memory with --snapshot")
    t.add_argument("--source", required=True, help="the tables run to start from")
    t.add_argument(
        "--repeat",
        choices=("a", "b"),
        help="the counts run's repeat (required for counts; the memory condition ignores it)",
    )
    t.add_argument("--snapshot", help="a checked memory snapshot's name")
    t.add_argument(
        "--lookup",
        type=int,
        metavar="K",
        help="the lookup condition: up to K of the snapshot's lessons per case (decision 0210)",
    )
    t.add_argument(
        "--applies",
        metavar="RUN_ID",
        help="with --lookup: choose each case's lessons from this apply run (decision 0211)",
    )
    t.add_argument(
        "--choices",
        metavar="RUN_ID",
        help="with --lookup: each case's lessons from this choices run (decision 0213)",
    )
    t.add_argument("--resume", metavar="RUN_ID", help="continue this run's folder")
    args = parser.parse_args(argv)
    try:
        commit = gitinfo.commit_state()
        _require_clean(commit[1])
        ctx = Context(settings or Settings(), batch_factory, now, commit)
        commands = {"answer": answer, "tools": tools}
        return commands[args.command](args, ctx)
    except (ConfigurationError, BudgetError) as exc:
        print(f"refused: {exc}")
        return 1
    except ModelError as exc:  # a cancelled or lost batch; its spend row is written
        print(f"stopped: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
