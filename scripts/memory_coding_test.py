"""The coding test: GPT-6 Luna codes a case from the NTSB's own probable-cause sentence.

Status
    Live tool for the coding memory's pilot (decision 0204), paid on OpenRouter: GPT-6 Luna
    batch, about a cent or less a case. Development only: ``dev-steer-400`` and nothing else in
    this plan. It refuses a dirty tree before anything is read, so every run names a clean
    commit. Its spend rows are kind ``coding-test``: the $40 monthly guard counts them, and so
    does the side track's $10 line (``make mem-spend``, decision 0207).

What it measures
    Coding alone: the reading of the evidence is taken out, so a change in score is the coding's
    (0204 item 1). The payload is the case's probable-cause sentence and nothing else, built by
    ``Payload.for_coding_test``, the declared exception to the request boundary (decision 0205);
    this is the only file that calls it. Three conditions:

    - **tables** (``answer``): arm B's answer, stage 1 then the refinement of the finding items,
      on the coding test's system text (``memory.prompts.coding_system``: the preface, arm B's
      answer text, the code tables and S3's two guidance files).
    - **counts** (``tools``): arm B's fixed coding-tools post-pass (``agent.armb.FixedToolsLoop``,
      unchanged) over a tables run's answers, counting in the ``mem`` statistics (decision 0203).
    - **memory** (``tools --snapshot NAME``): the same, with a checked snapshot appended to the
      system text. Refused until ``docs/rounds/memory-pilot.md`` is committed (0204 item 6).

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
    uv run python -m scripts.memory_coding_test answer --repeat {a,b} [--resume RUN_ID]
    uv run python -m scripts.memory_coding_test tools --source RUN_ID --repeat {a,b}
        [--resume RUN_ID]
    uv run python -m scripts.memory_coding_test tools --source RUN_ID --snapshot NAME
        [--resume RUN_ID]
"""

import argparse
import contextlib
import json
from collections.abc import Callable, Mapping, Sequence
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
from ntsb_probable_cause.memory import prompts, snapshots
from ntsb_probable_cause.memory.lessons import Memory
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
    "refuse_memory_without_registration",
    "refuse_sample",
    "spend_usd",
]

SAMPLE: Final = "dev-steer-400"
GUIDANCE: Final = ("r3-loc-stall", "r6-aircraft-control")
REGISTRATION: Final = Path("docs/rounds/memory-pilot.md")
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

Condition = Literal["tables", "counts", "memory"]
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
    """Refuse every sample but the steering slice, and a statistics pool that holds it.

    Raises:
        ConfigurationError: ``sample`` is not ``dev-steer-400`` (decisions 0203, 0204), or the
            ``mem`` statistics' pool holds it (``coding_stats.refuse_pool_holding``).
    """
    if sample != SAMPLE:
        raise ConfigurationError(
            f"the coding test runs on {SAMPLE} only (decisions 0203, 0204), not {sample}"
        )
    coding_stats.refuse_pool_holding(STATS, sample)


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


# What the test reads. ----------------------------------------------------------------------


def causes(processed: Path) -> dict[str, str | None]:
    """Every steering-slice case's probable-cause sentence, in sample order; None for none.

    The sentence is verdict text, read through ``fields`` from the raw record; it reaches the
    model only through ``Payload.for_coding_test`` (decision 0205).
    """
    ids = samples.sample_ids(SAMPLE)
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
                f"resume with --resume {plan.run_id}"
            )
    answered = sum(1 for row in rows if row.hypothesis is not None)
    print(f"{plan.run_id}: {answered} of {len(rows)} cases answered")
    return 0


def _base_spec(
    condition: Condition, repeat: str | None, commit: tuple[str, bool]
) -> dict[str, object]:
    return {
        "sample": SAMPLE,
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
    """The tables condition on the steering slice: every case with a cause, coded once."""
    refuse_sample(SAMPLE)
    tables = load_tables()
    system = prompts.coding_system(tables, GUIDANCE, None)
    found = causes(_processed(ctx.settings))
    loops = [
        CodingAnswerLoop(case_id, cause, system, tables)
        for case_id, cause in found.items()
        if cause is not None
    ]
    skipped = {case_id: NO_CAUSE for case_id, cause in found.items() if cause is None}
    run_id = args.resume or f"{_stamp(ctx.now())}-{ctx.commit[0]}-{SAMPLE}-mem-tables-{args.repeat}"
    spec = {**_base_spec("tables", args.repeat, ctx.commit), "case_ids": list(found)}
    plan = Plan(run_id, spec, loops, skipped, tuple(found))
    return _run(ctx, plan, resume=args.resume is not None)


def _read_source(folder: Path) -> list[CodingCase]:
    """A tables run's cases, after its spec is checked: refused unless it is one.

    Raises:
        ConfigurationError: no such run, a spec or cases file that cannot be read, or a run that
            is not the tables condition on the steering slice.
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
    refuse_sample(str(spec.get("sample")))
    return rows


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


def _tools_run_id(args: argparse.Namespace) -> str:
    """The derived run's id, from the source, and the repeat or the snapshot.

    Raises:
        ConfigurationError: ``--repeat`` missing without ``--snapshot``, or ``--resume`` not the
            id these arguments give.
    """
    if args.snapshot is None:
        if args.repeat is None:
            raise ConfigurationError("the counts condition needs --repeat a or b")
        run_id = f"{args.source}-counts-{args.repeat}"
    else:
        run_id = f"{args.source}-memory-{args.snapshot}"
    if args.resume is not None and args.resume != run_id:
        raise ConfigurationError(
            f"--resume {args.resume} is not the run these arguments make ({run_id})"
        )
    return run_id


def tools(args: argparse.Namespace, ctx: Context) -> int:
    """The counts condition over a tables run, or the memory condition with ``--snapshot``.

    The memory condition ignores ``--repeat``: one memory run per snapshot and source.
    """
    source = args.source
    run_id = _tools_run_id(args)
    memory: Memory | None = None
    snapshot_sha: str | None = None
    if args.snapshot is not None:
        memory, snapshot_sha = _checked_memory(args.snapshot)
    first = _read_source(ctx.runs_dir / source)
    condition: Condition = "counts" if memory is None else "memory"
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
    system = prompts.coding_system(tables, GUIDANCE, memory)
    found = causes(_processed(ctx.settings))
    loops: list[Loop] = []
    skipped: dict[str, str] = {}
    for row in first:
        cause = found.get(row.case_id)
        if row.hypothesis is None:
            skipped[row.case_id] = SOURCE_FAILED
        elif cause is None:
            skipped[row.case_id] = NO_CAUSE
        else:
            # group=None: no phase-of-flight evidence, so no suggest_codes call (module docstring)
            loops.append(
                FixedToolsLoop(
                    {"ntsbNumber": row.case_id},
                    Payload.for_coding_test(cause),
                    system,
                    row.hypothesis,
                    as_recorded(row.hypothesis),
                    None,
                    config,
                )
            )
    repeat = args.repeat if memory is None else None
    order = [row.case_id for row in first]
    spec = {
        **_base_spec(condition, repeat, ctx.commit),
        "source_run": source,
        "snapshot": args.snapshot,
        "snapshot_sha256": snapshot_sha,
        "suggest_codes": SUGGEST_CODES,
        "case_ids": order,
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
    a.add_argument("--resume", metavar="RUN_ID", help="continue this run's folder")
    t = sub.add_parser("tools", help="the counts condition, or memory with --snapshot")
    t.add_argument("--source", required=True, help="the tables run to start from")
    t.add_argument(
        "--repeat",
        choices=("a", "b"),
        help="the counts run's repeat (required for counts; the memory condition ignores it)",
    )
    t.add_argument("--snapshot", help="a checked memory snapshot's name")
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
