"""Arm C in the harness: the agent loop's run folders, budget, drivers, scores and records.

S3.1 Task 10 (spec §8). ``AgentRunner`` is to the loop what ``scoring.runner.Runner`` is to arms
A, B and the ceiling: it refuses what must not run, makes or adopts the run folder, reserves the
budget, builds one ``CaseLoop`` per case, puts them through a driver (``drive_sync`` or
``drive_batch``, which replay what the folder holds, so a resume is the same call), scores each
answer against the verdict, and writes the records.

An arm C run folder holds the same files as an arm B run, read by the same report code:

- ``spec.json``: the spec, plus every setting the loop depends on that ``RunSpec`` does not hold
  (the agent's prompt version, the statistics file, the round, the tool ablation, the round and
  coding-call limits, whether reasoning is passed back), so a resume with any of them changed
  is refused;
- ``cases.jsonl`` and ``steps.jsonl``: one ``CaseResult`` per case, one ``StepRecord`` per
  checkpoint (``h0``, ``h1``, ``h2``, ``answer``, ``refine``);
- ``run.jsonl``: the ``RunRecord``, ``arm="C"``;
- and three of its own: ``replies.jsonl`` and ``rounds.jsonl`` (the drivers', what a resume
  replays) and ``trail.jsonl`` (one ``AgentCall`` per model call: sizes and counts, never a
  document's text).

Nothing in the library imports this module (an import-linter contract); ``apps/eval`` does.
"""

import contextlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypedDict

from ntsb_probable_cause.agent import texts
from ntsb_probable_cause.agent.documents import DocketView, case_marks, docket_view
from ntsb_probable_cause.agent.drive import (
    REPLIES_FILE,
    ROUNDS_FILE,
    RoundRow,
    drive_batch,
    drive_sync,
)
from ntsb_probable_cause.agent.loop import PASS_REASONING, CaseLoop, LoopConfig
from ntsb_probable_cause.agent.schemas import ChooseDocuments, Without
from ntsb_probable_cause.agent.trail import AgentCall, LoopOutcome
from ntsb_probable_cause.docket.attach import DOCKET_KEY
from ntsb_probable_cause.errors import BatchCancelledError, ConfigurationError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import ModelClient, Payload
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.budget import settle
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, StatsName
from ntsb_probable_cause.scoring.ledger import append_row, refuse_if_heldout_and_dirty
from ntsb_probable_cause.scoring.metrics import score_case
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    RunRecord,
    StepRecord,
    fingerprint,
    write_jsonl,
)
from ntsb_probable_cause.scoring.runner import (
    RUN_FILE,
    BatchRunner,
    DocketReader,
    RunSpec,
    case_identity,
    leaked_case,
    refuse_sync_resume,
    refuse_sync_with_batch_price,
    refuse_unnamed_reading,
    refuse_unresumable,
    reserve_run_budget,
    set_aside_aborted_outputs,
    spec_json,
    write_spec_json,
)

TRAIL_FILE: Final = "trail.jsonl"
# S3's coding guidance (spec §20, Andy 2026-09-30): every arm C run reads S2.7's two kept rounds,
# unchanged, unless a registered tuning round (Task 13) changes them.
GUIDANCE: Final[tuple[str, ...]] = ("r3-loc-stall", "r6-aircraft-control")
# The per-case cap arm C starts at (spec §8.2): the learning probe's $0.15. ``run --arm C``
# defaults ``--cap-usd`` to it; S3.2 fixes the cap before any comparison run.
CAP_USD: Final = 0.15
MAX_ROUNDS: Final = 40
MAX_CODING_CALLS: Final = 6
# The statistics file every S3 run's tools count in (decision 0129); ``run --arm C`` loads it.
STATS: Final[StatsName] = "s3"
# S2.7's sealed sample, used once on 2026-09-29 (decision 0095). Its registration is committed, so
# ``refuse_sealed`` lets it through, and S3's pool leaves it out, so ``refuse_pool_holding`` does
# too: arm C and arm B's tool post-pass refuse it themselves, so it is never read again.
USED_ONCE: Final = "dev-seal-400"
_DOCKET_ROLES: Final = frozenset({EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS})
_ARM: Final = "C"


@dataclass(frozen=True)
class _Case:
    """One case of the run: its record, its docket view, and its loop.

    ``loop`` is None, and ``leak`` holds the guard's error, when preparing the docket leaked.
    """

    raw: Mapping[str, object]
    view: DocketView | None
    loop: CaseLoop | None
    leak: LeakageError | None = None


class AgentRunner:
    """Runs arm C over raw records and writes the records an arm B run writes, plus the trail.

    Args:
        client: the model client, for ``--sync`` runs.
        batch: the batch client, for every other run.
        tables: the code tables the answer chooses from.
        stats: the statistics pool the coding tools count in (``load_stats("s3")``).
        seen_pairs: the development split's primary occurrence codes (``pair_unseen``).
        runs_dir: the runs directory.
        month_spent_usd: the month's spend measured before the run (a floor; re-read under the
            budget lock).
        commit: the commit SHA and whether the tree had uncommitted changes (0018, 0033).
        docket: where each case's docket is read from; v1 only. None only for a run that
            excludes a docket role.
        now: the clock; the only source of times.
        round_number: a registered tuning round (Task 13); it may change the guidance, and it is
            recorded in the prompt version and ``spec.json``.
        pass_reasoning: whether assistant turns' reasoning goes back to the model
            (``loop.PASS_REASONING`` by default, which the shape probe's check 4 decides, spec
            §5.5; ``run --arm C`` passes that constant).
        without: the tool ablation (spec §7.2).
        max_rounds: the most batch rounds the run may take.
        ledger_path: the held-out ledger; a held-out run needs it, as ``Runner``'s does.
    """

    def __init__(  # noqa: PLR0913 -- the plan's interface, plus the loop settings it records.
        self,
        client: ModelClient,
        *,
        batch: BatchRunner | None,
        tables: CodeTables,
        stats: CodingStats,
        seen_pairs: frozenset[str],
        runs_dir: Path,
        month_spent_usd: float,
        commit: tuple[str, bool],
        docket: DocketReader | None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        round_number: int | None = None,
        pass_reasoning: bool = PASS_REASONING,
        without: frozenset[Without] = frozenset(),
        max_rounds: int = MAX_ROUNDS,
        ledger_path: Path | None = None,
    ) -> None:
        self._client = client
        self._batch = batch
        self._tables = tables
        self._stats = stats
        self._seen = seen_pairs
        self._runs_dir = runs_dir
        self._spent = month_spent_usd
        self._sha, self._dirty = commit
        self._docket = docket
        self._now = now
        self._round = round_number
        self._pass_reasoning = pass_reasoning
        self._without = without
        self._max_rounds = max_rounds
        self._ledger = ledger_path

    def run(
        self,
        spec: RunSpec,
        raws: Sequence[Mapping[str, object]],
        *,
        resume: str | None = None,
    ) -> RunRecord:
        """Run every case, write the records, and append the ledger for a held-out sample.

        On any exception once the budget is reserved (a batch cancelled, a process
        interrupted, anything), every case still running is stopped ``aborted: <error>`` and
        the records are written with ``finished=None`` before the exception is re-raised, so
        the spend so far is never invisible to the next run's budget check; the reservation is
        settled either way. A cancelled batch is re-raised with the run id to resume.

        Args:
            spec: what varies between runs; ``arm`` must be ``"C"``.
            raws: the raw records, in order.
            resume: a run id to continue (0032): the folder is adopted, its ``spec.json`` must
                equal this run's, and the drivers replay the replies it holds, so no call is
                paid for twice.

        Returns:
            The run's ``RunRecord``, also written to ``run.jsonl``.

        Raises:
            ConfigurationError: a refusal (see ``_refuse``), a folder that cannot be resumed, a
                record with no ``mKey``, or a docket whose own key is not the record's.
            BudgetError: the projected cost does not fit the month's budget.
            BatchCancelledError: a batch was cancelled; the message names the run to resume.
        """
        self._refuse(spec)
        refuse_sync_resume(spec, resume)
        started = self._now()
        case_ids = [str(raw["ntsbNumber"]) for raw in raws]
        extra = self._recorded(spec)
        if resume is None:
            run_id = f"{started:%Y%m%dT%H%M%S}-{self._sha}-{spec.sample}-{_ARM}"
            folder = self._runs_dir / run_id
            try:
                folder.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                raise ConfigurationError(
                    f"run folder {run_id} already exists: another run with this id was started "
                    "in the same second at the same commit and sample. Wait a second and start "
                    f"again, or pass --resume {run_id} to continue that run."
                ) from None
            write_spec_json(
                folder,
                spec,
                commit_sha=self._sha,
                dirty=self._dirty,
                case_ids=case_ids,
                extra=extra,
            )
        else:
            run_id = resume
            folder = self._runs_dir / run_id
            current = spec_json(
                spec, commit_sha=self._sha, dirty=self._dirty, case_ids=case_ids, extra=extra
            )
            refuse_unresumable(folder, current)  # it refuses a finished run first
        reserve_run_budget(self._runs_dir, spec, run_id, len(raws), started, spent=self._spent)
        try:
            self._log(
                lambda: (
                    f"run {run_id} {'RESUMED' if resume else 'FRESH'} sample={spec.sample} "
                    f"arm={_ARM} cases={len(raws)} model={spec.model} "
                    f"price={spec.price_variant} cap=${spec.cap_usd:.2f}"
                )
            )
            config = self._config(spec, run_id)
            cases: list[_Case] = []
            try:
                for raw in raws:
                    cases.append(self._prepare(raw, spec, config))
                self._drive(spec, [c.loop for c in cases if c.loop is not None], folder)
            except BaseException as error:
                for case in cases:
                    if case.loop is not None:
                        case.loop.stop(f"aborted: {error}")
                self._write(
                    spec,
                    folder,
                    run_id,
                    started=started,
                    cases=cases,
                    finished=None,
                    resumed=resume is not None,
                )
                if isinstance(error, BatchCancelledError):
                    raise BatchCancelledError(
                        f"{error} The records so far are written. Resume run {run_id} with the "
                        f"same command and --resume {run_id}."
                    ) from error
                raise
            record = self._write(
                spec,
                folder,
                run_id,
                started=started,
                cases=cases,
                finished=self._now(),
                resumed=resume is not None,
            )
        finally:
            settle(self._runs_dir, run_id)
        if spec.sample.startswith("heldout") and self._ledger is not None:
            append_row(self._ledger, record, str(folder / "cases.jsonl"))
        return record

    # --- before anything is made ---

    def _refuse(self, spec: RunSpec) -> None:
        """Every refusal that needs no folder, before any folder, reservation or call."""
        if spec.arm != _ARM:
            raise ConfigurationError(
                f"AgentRunner runs arm C only; arm {spec.arm} is run by scoring.runner.Runner"
            )
        if spec.sample == USED_ONCE:
            raise ConfigurationError(
                f"{USED_ONCE} is the sealed development sample S2.7 used once (decision 0095): "
                "it is never read again, so arm C does not run on it"
            )
        refuse_if_heldout_and_dirty(spec.sample, self._dirty)
        refuse_sync_with_batch_price(spec)
        if spec.evidence_version != "v1":
            raise ConfigurationError(
                f"arm C reads evidence version v1 only (spec §11): {spec.evidence_version} is "
                "refused"
            )
        refuse_unnamed_reading(spec)
        if spec.include_case_number:
            raise ConfigurationError(
                "arm C never sends the case number: the case-number probe is for arms A, B and "
                "the ceiling"
            )
        if self._round is None and spec.guidance != GUIDANCE:
            raise ConfigurationError(
                f"arm C reads the guidance {', '.join(GUIDANCE)} (spec §20); other guidance "
                f"({', '.join(spec.guidance) or 'none'}) needs a registered tuning round"
            )
        if not spec.exclusions & _DOCKET_ROLES:
            if self._docket is None:
                raise ConfigurationError("arm C needs a docket reader (it reads the docket cache)")
            if self._docket.version != "v1":
                raise ConfigurationError(
                    f"arm C needs a v1 docket reader; this one reads {self._docket.version} "
                    "evidence (decision 0076)"
                )
        if not spec.sync and self._batch is None:
            raise ConfigurationError("a batch client is required for a non-sync run")
        if spec.sample.startswith("heldout") and self._ledger is None:
            raise ConfigurationError(
                f"{spec.sample}: a held-out run is listed in the held-out ledger; pass its path"
            )

    def _recorded(self, spec: RunSpec) -> dict[str, object]:
        """The loop's settings ``spec.json`` records beside the spec (a resume compares them)."""
        recorded: dict[str, object] = {
            "agent_prompt_version": texts.prompt_version(spec.guidance, self._round),
            "stats": STATS,
            "max_rounds": self._max_rounds,
            "max_coding_calls": MAX_CODING_CALLS,
            "without": sorted(self._without),
            "pass_reasoning": self._pass_reasoning,
        }
        if self._round is not None:
            recorded["round"] = self._round
        return recorded

    def _config(self, spec: RunSpec, run_id: str) -> LoopConfig:
        return LoopConfig(
            tables=self._tables,
            stats=self._stats,
            guidance=spec.guidance,
            exclusions=spec.exclusions,
            cap_usd=spec.cap_usd,
            price_variant=spec.price_variant,
            max_output_tokens=spec.max_output_tokens,
            max_coding_calls=MAX_CODING_CALLS,
            pass_reasoning=self._pass_reasoning,
            without=self._without,
            run_id=run_id,
            commit=(self._sha, self._dirty),
            model=spec.model,
            reasoning_effort=spec.reasoning_effort,
        )

    # --- the cases ---

    def _prepare(self, raw: Mapping[str, object], spec: RunSpec, config: LoopConfig) -> _Case:
        """A case's docket view and its fresh loop; a leak in preparing the docket fails it alone.

        The docket is read at v1 when no docket role is excluded (a run that excludes one reads
        none, and its loop is given no view).
        """
        case_id = str(raw.get("ntsbNumber"))
        view: DocketView | None = None
        if self._docket is not None and not spec.exclusions & _DOCKET_ROLES:
            mkey = raw.get("mKey")
            if not isinstance(mkey, int):
                raise ConfigurationError(f"{case_id}: no mKey, so no docket")
            docket = self._docket.read(mkey)
            # The pairing guard: the docket's own key must be the record's. The view below is
            # built from this same record, so its case number could never differ; the docket
            # the reader returned can (a cache or reader that answers for another key).
            if docket.mkey != mkey:
                raise ConfigurationError(
                    f"the docket read for {case_id} is docket {docket.mkey}, not its own "
                    f"{mkey}: a case's loop is given its own docket only"
                )
            try:
                view = docket_view(raw, docket)
            except LeakageError as error:
                return _Case(raw, None, None, error)
        return _Case(raw, view, CaseLoop(raw, view, config))

    def _drive(self, spec: RunSpec, loops: Sequence[CaseLoop], folder: Path) -> None:
        """Put the loops through their driver; the driver replays what the folder holds first.

        The loops are fresh: a resume is the same call (the plan's Task 9 Deviations).
        """
        if spec.sync:
            drive_sync(loops, self._client, folder=folder, now=self._now)
            return
        if self._batch is None:  # refused up front; kept for the type checker
            raise ConfigurationError("a batch client is required for a non-sync run")
        drive_batch(
            loops,
            self._batch,
            folder=folder,
            now=self._now,
            max_rounds=self._max_rounds,
            on_round=self._log_round,
        )

    def _result(self, case: _Case, spec: RunSpec) -> CaseResult:
        """One case's result: scored when the loop answered, failed with its stop reason if not.

        A case whose refinement could not run (the cap, or a failed refinement call) is not
        scored, though its answer is in its steps: arm B never scores a case whose stage 2
        could not run either (``Runner._fail_case`` for a failed stage 2, and a case over the
        cap fails ``cap`` before any call), so the two arms' scored cases mean the same.
        """
        raw = case.raw
        if case.loop is None:  # preparing the docket leaked; no call was made
            return leaked_case(raw, case.leak or LeakageError("the guard refused the docket"))
        outcome = case.loop.outcome
        if outcome.stop_reason == "failed: leak":
            return _leaked(
                raw, outcome, LeakageError(outcome.leak or "the guard refused a payload")
            )
        record = {key: value for key, value in raw.items() if key != DOCKET_KEY}
        try:
            evidence, _, verdict = split_record(record, exclude=spec.exclusions)
            marks, share = case_marks(case.view, raw, outcome.read, spec.exclusions)
        except LeakageError as error:  # the same splits the loop's payloads passed; fail closed
            return _leaked(raw, outcome, error)
        case_id = str(raw["ntsbNumber"])
        answer = outcome.answer
        scores = (
            score_case(answer, verdict, self._tables, seen_pairs=self._seen)
            if answer is not None
            else None
        )
        return CaseResult(
            case_id=case_id,
            **case_identity(raw, verdict, case_id),
            steps=self._steps(case_id, outcome, case.view, Payload.from_evidence(evidence), spec),
            scores=scores,
            cost_usd=outcome.cost_usd,
            failure=None if outcome.stop_reason == "done" else outcome.stop_reason,
            documents_not_read=_not_read(case.view, outcome),
            marks=marks,
            narrative_share=share,
            **_replies(outcome.calls),
        )

    def _steps(
        self,
        case_id: str,
        outcome: LoopOutcome,
        view: DocketView | None,
        evidence: Payload,
        spec: RunSpec,
    ) -> tuple[StepRecord, ...]:
        """One ``StepRecord`` per checkpoint, over the calls since the one before.

        Each says what the agent had been sent by then: the evidence roles, the listing once the
        first hypothesis was answered with it, and the documents read so far. Calls after the
        last checkpoint (a failed refinement, say) are in the case's cost, not in a step.
        """
        roles = sorted(evidence.fields())
        not_available = (
            () if view is None else tuple(f"{f.index}: {f.status}" for f in view.not_readable)
        )
        listed = view is not None and view.listed
        last = len(outcome.checkpoints) - 1
        steps: list[StepRecord] = []
        since: list[AgentCall] = []
        cumulative = 0.0
        listing = False
        chosen: set[int] = set()
        for call in outcome.calls:
            since.append(call)
            if call.hypothesis is not None:
                number = len(steps)
                kind, hypothesis = outcome.checkpoints[number]
                read = [i for i in outcome.read if i in chosen]
                seen = {*roles, *(["docket_listing"] if listing else [])}
                seen |= {"docket_documents"} if read else set()
                cost = sum(c.cost_usd for c in since)
                cumulative += cost
                steps.append(
                    StepRecord(
                        case_id=case_id,
                        step=number,
                        arm=_ARM,
                        condition="full",
                        day=None,
                        tool=f"checkpoint:{kind}",
                        arguments={},
                        reason="",
                        expected_effect="",
                        returned_roles=tuple(sorted(seen)),
                        not_available=not_available,
                        documents_attached=_attached(view, read),
                        payload_fingerprint=fingerprint(evidence),
                        hypothesis=hypothesis,
                        observed_effect="",
                        stop_reason=_stop_reason(outcome, final=number == last),
                        model=spec.model,
                        price_variant=spec.price_variant,
                        prompt_tokens=sum(c.prompt_tokens for c in since),
                        completion_tokens=sum(c.completion_tokens for c in since),
                        reasoning_tokens=_reasoning(since),
                        **_replies(since),
                        cost_usd=cost,
                        cumulative_cost_usd=cumulative,
                        commit_sha=self._sha,
                        dirty=self._dirty,
                    )
                )
                since = []
            if call.step == "h0" and call.hypothesis is not None and listed:
                # The listing went back as the first hypothesis's result, readable documents or
                # not (Andy, 2026-10-01).
                listing = True
            if call.tool == "choose_documents" and call.protocol_error is None:
                choice = ChooseDocuments.model_validate(call.arguments)
                chosen |= {d.document for d in choice.decisions if d.read}
        return tuple(steps)

    # --- the records ---

    def _write(  # noqa: PLR0913 -- the run's identity and its cases, then whether it finished.
        self,
        spec: RunSpec,
        folder: Path,
        run_id: str,
        *,
        started: datetime,
        cases: Sequence[_Case],
        finished: datetime | None,
        resumed: bool,
    ) -> RunRecord:
        """Write the cases, steps, trail and run record; a resume sets the dead run's aside first.

        The set-aside happens a moment before the new files are written, as ``Runner`` does,
        and what the superseded ``run.jsonl`` reported is a floor under this record's cost.
        """
        floor = _set_aside(folder) if resumed else 0.0
        results = [self._result(case, spec) for case in cases]
        write_jsonl(folder / "cases.jsonl", results)
        write_jsonl(folder / "steps.jsonl", (s for r in results for s in r.steps))
        write_jsonl(
            folder / TRAIL_FILE,
            (call for case in cases if case.loop is not None for call in case.loop.outcome.calls),
        )
        costs = round_costs(folder)
        record = RunRecord(
            run_id=run_id,
            sample=spec.sample,
            arm=_ARM,
            evidence_version=spec.evidence_version,
            exclusions=tuple(sorted(e.value for e in spec.exclusions)),
            includes=(),
            prompt_version=texts.prompt_version(spec.guidance, self._round),
            guidance=spec.guidance,
            guidance_sha256=prompt.guidance_sha256(spec.guidance),
            model=spec.model,
            reasoning_effort=spec.reasoning_effort,
            price_variant=spec.price_variant,
            cap_usd=spec.cap_usd,
            budget_usd=spec.budget_usd,
            max_output_tokens=spec.max_output_tokens,
            commit_sha=self._sha,
            dirty=self._dirty,
            started=started,
            finished=finished,
            batch_ids=costs.batch_ids,
            cases=len(results),
            cost_usd=max(sum(r.cost_usd for r in results) + costs.dead_usd, floor),
            reported_batch_cost_usd=costs.reported_usd,
        )
        write_jsonl(folder / RUN_FILE, [record])
        return record

    # --- the run log ---

    def _log(self, body: Callable[[], str]) -> None:
        """One line to stderr, the wall clock first; a logging failure never kills a run."""
        log_line(self._now, body)

    def _log_round(self, row: RoundRow, running: int) -> None:
        """A round as it goes out (or is waited on again) and as it ends: counts and ids only."""
        self._log(lambda: round_line(row, running))


def log_line(now: Callable[[], datetime], body: Callable[[], str]) -> None:
    """One line to stderr, the wall clock first; a logging failure never kills a run.

    ``body`` is called inside the guard, so a line that cannot even be built is dropped too. Arm
    C's runner and arm B's tool post-pass (``agent/armb.py``) log through here.
    """
    with contextlib.suppress(Exception):
        sys.stderr.write(f"{now():%H:%M:%S}Z {body()}\n")


def round_line(row: RoundRow, running: int) -> str:
    """A batch round as it goes out (or is waited on again) and as it ends: counts and ids only.

    E.g. ``round 3 sent b3: 12 calls; 12 cases running`` and
    ``round 3 completed b3: cost $0.1250; 9 cases running``.
    """
    if row.status is None:
        return (
            f"round {row.round} sent {row.batch_id}: {len(row.custom_ids)} calls; "
            f"{running} cases running"
        )
    cost = "not reported" if row.reported_cost_usd is None else f"${row.reported_cost_usd:.4f}"
    return f"round {row.round} {row.status} {row.batch_id}: cost {cost}; {running} cases running"


@dataclass(frozen=True)
class RoundCosts:
    """What a run folder's batch rounds say about its cost.

    Attributes:
        batch_ids: every round's batch id, in round order.
        dead_usd: what the finished rounds no reply came from (dead, cancelled or lost) reported.
            No case prices those replies, so a run's cost carries it, as ``Runner``'s
            ``dead_cost`` does.
        reported_usd: the rounds' reported costs summed; None when there were no rounds or any
            round reported none.
    """

    batch_ids: tuple[str, ...]
    dead_usd: float
    reported_usd: float | None


def round_costs(folder: Path) -> RoundCosts:
    """The batch ids and round costs a run folder's ``rounds.jsonl`` and ``replies.jsonl`` hold.

    A damaged line is passed over (``_rounds``): read on an abort path too, what is readable
    still counts. A folder with no rounds (a sync run) has no batch ids and no dead cost.
    """
    rounds = _rounds(folder)
    replied = _replied_batches(folder)
    dead = sum(
        r.reported_cost_usd
        for r in rounds
        if r.finished_at is not None
        and r.batch_id not in replied
        and r.reported_cost_usd is not None
    )
    reported = (
        None
        if not rounds or any(r.reported_cost_usd is None for r in rounds)
        else sum(r.reported_cost_usd or 0.0 for r in rounds)
    )
    return RoundCosts(tuple(r.batch_id for r in rounds), dead, reported)


def _leaked(raw: Mapping[str, object], outcome: LoopOutcome, error: LeakageError) -> CaseResult:
    """Arm B's leaked record, with what the case's calls before the trip cost.

    No steps, no scores, no documents not read and no marks, as arm B's; the trail keeps which
    document was chosen. The cost and replies are kept: unlike arm B's, arm C's leak can come
    after calls were paid for, and spend is never left out of a run's record.
    """
    return leaked_case(raw, error).model_copy(
        update={"cost_usd": outcome.cost_usd, **_replies(outcome.calls)}
    )


class _Replies(TypedDict):
    """The per-reply tuples of a ``CaseResult`` or a ``StepRecord``, typed for ``**``."""

    reply_completion_tokens: tuple[int, ...]
    reply_reasoning_tokens: tuple[int | None, ...]
    reply_finish_reasons: tuple[str | None, ...]


def _replies(calls: Sequence[AgentCall]) -> _Replies:
    """The per-reply tuples ``CaseResult`` and ``StepRecord`` carry: one entry per model call.

    A call that failed (no reply) has 0 completion tokens and no reasoning or finish reason.
    """
    return {
        "reply_completion_tokens": tuple(c.completion_tokens for c in calls),
        "reply_reasoning_tokens": tuple(c.reasoning_tokens for c in calls),
        "reply_finish_reasons": tuple(c.finish_reason for c in calls),
    }


def _reasoning(calls: Sequence[AgentCall]) -> int | None:
    """The reasoning tokens over the calls, or None when no call reported any."""
    if all(c.reasoning_tokens is None for c in calls):
        return None
    return sum(c.reasoning_tokens or 0 for c in calls)


def _stop_reason(outcome: LoopOutcome, *, final: bool) -> str:
    """How a checkpoint ended the case: only the last says, and only for an answer or the cap."""
    if not final:
        return ""
    if outcome.stop_reason == "done" and outcome.answer is not None:
        return "abstained" if outcome.answer.abstain else "answered"
    return "cap" if outcome.stop_reason == "cap" else ""


def _attached(view: DocketView | None, read: Sequence[int]) -> tuple[str, ...]:
    """The documents read, in arm B's format: ``index: category, N tokens``."""
    if view is None:
        return ()
    docket = view.attachment.docket
    return tuple(
        f"{i}: {docket.record(i).category}, {docket.record(i).estimated_tokens} tokens"
        for i in read
    )


def _not_read(view: DocketView | None, outcome: LoopOutcome) -> tuple[str, ...]:
    """The offered documents never read, each ``skipped`` or ``undecided``.

    ``skipped``: the agent chose not to read it. ``undecided``: the case ended before the agent
    chose (the cap, a failure). ``report``'s unread line counts both.
    """
    if view is None:
        return ()
    skipped = set(outcome.skipped)
    return tuple(
        f"{f.index}: {'skipped' if f.index in skipped else 'undecided'}"
        for f in view.offered
        if f.index not in outcome.read
    )


def _rounds(folder: Path) -> list[RoundRow]:
    """The last row of each round, in round order; a damaged line is passed over.

    Read on the abort path too, where the driver may have stopped on a damaged file: what is
    readable still counts, and the error the run stopped with is the one re-raised.
    """
    latest: dict[int, RoundRow] = {}
    for line in _lines(folder / ROUNDS_FILE):
        with contextlib.suppress(ValueError):
            row = RoundRow.model_validate_json(line)
            latest[row.round] = row
    return [latest[n] for n in sorted(latest)]


def _replied_batches(folder: Path) -> set[str]:
    """Every batch a reply was written from (``replies.jsonl``); damaged lines passed over."""
    batches: set[str] = set()
    for line in _lines(folder / REPLIES_FILE):
        with contextlib.suppress(ValueError):
            row = json.loads(line)
            batch_id = row.get("batch_id") if isinstance(row, dict) else None
            if isinstance(batch_id, str):
                batches.add(batch_id)
    return batches


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line] if path.is_file() else []


def _set_aside(folder: Path) -> float:
    """The dead run's result files and its trail, renamed; the cost its ``run.jsonl`` reported.

    ``set_aside_aborted_outputs`` renames the three files the runner writes; the trail is
    renamed the same way, since it too is re-derived in full from the replies.
    """
    floor = set_aside_aborted_outputs(folder)
    trail = folder / TRAIL_FILE
    if trail.is_file():
        attempt = 1
        while (target := folder / f"trail.aborted-{attempt}.jsonl").exists():
            attempt += 1
        trail.rename(target)
    return floor
