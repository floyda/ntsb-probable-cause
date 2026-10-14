"""One live morning: code the queued closed cases with the frozen agent (S3.3 spec 3 to 8).

``run_morning`` is library code. Every outside effect (the clock, the store, the spend counter,
the sink, the three client factories, the commit, the lockfile checksum and the prompt-version
label) comes in through :class:`MorningDeps`, so a test replaces each with a fake. The order is
fixed: label, store, the recorder's run, a resume, the daily limit, the caps, the queue, the
backfill, the fetches, the run, the closure records, the cleanup.

The raw records of a run go to ``<runs_dir>/live-pending-inputs.jsonl`` before ``AgentRunner``
makes its folder (it creates the folder itself), and move to ``<run folder>/inputs.jsonl``
afterwards, so a resume reads back exactly the records the run began with, in order.
"""

import contextlib
import hashlib
import json
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Final

from ntsb_probable_cause.agent import loop as agent_loop
from ntsb_probable_cause.agent import run as agent_run
from ntsb_probable_cause.agent.run import GUIDANCE, AgentRunner
from ntsb_probable_cause.agent.schemas import Without
from ntsb_probable_cause.agent.version import VERSION_1, prompt_version
from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.live.closure import CASES_FILE, RUN_FILE, Prepared, build_records
from ntsb_probable_cause.live.fetch import FetchError, fetch_record, prefetch_docket
from ntsb_probable_cause.live.local import LIVE_SAMPLE
from ntsb_probable_cause.live.queue import (
    DAILY_LIMIT,
    QueuedCase,
    backfill_digest,
    build_queue,
    todays_take,
)
from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    INPUTS_FILE,
    MANIFEST_FILE,
    Backfill,
    ClosureRecord,
    failure_kind,
)
from ntsb_probable_cause.live.seams import ResultSink, SpendCounter, StoreSource
from ntsb_probable_cause.model.client import ModelClient, ModelSettings
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner, CachedDocketReader, RunSpec
from ntsb_probable_cause.scoring.samples import seen_pairs
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.sources import LUNA_6, TRAINING_CUTOFFS, ReasoningEffort
from ntsb_probable_cause.store import Store

LIVE_CAP_USD: Final = 0.30  # decision 163
MONTHLY_CAP_USD: Final = 5.0  # decision 163
# Estimate for the caps' projections (decision 0165: the standard price is about twice batch per
# token, and large dockets cost more). It feeds the reservation's projection only.
EXPECTED_COST_PER_CASE_USD: Final = 0.04

# Pinned here, not read from library defaults: a development edit of those must not move live
# runs off the model (decisions 0073, 0084, 0156). The `+t` fingerprint does not hash them.
MODEL_ID: Final = LUNA_6.model_id  # a named price entry, so DEFAULT_MODEL cannot move it
REASONING_EFFORT: Final[ReasoningEffort] = "medium"
MAX_OUTPUT_TOKENS: Final = 8000
WITHOUT: Final[frozenset[Without]] = frozenset()  # no tool ablation in a live run
# What `+t` cannot see (S3.3 final review, A2): settings that change what Ellery receives or how
# it is asked without being text in a request. Version 1 as S3.2 froze it; `run_morning` compares
# these with the code's current values before the store is opened or a model is called, and refuses
# on any difference. The two hashes are of `scoring/tables/coding_stats_s3.json` and `items.csv`,
# unchanged since `fd6053f`. A deliberate change is a new version (decision 0156, item 4), not an
# edit of this table. The model is spelled in `sources.py` only (a test keeps it so), so it is
# pinned by that named price entry; `test_g_the_run_spec` holds the id's text.
VERSION_1_SETTINGS: Final[Mapping[str, object]] = {
    "stats": "s3",
    "max_coding_calls": 6,
    "without": [],
    "pass_reasoning": False,
    "temperature": 0.0,
    "model": LUNA_6.model_id,
    "reasoning_effort": "medium",
    "max_output_tokens": 8000,
    "cap_usd": 0.3,
    "price_variant": "standard",
    "sync": True,
    "exclusions": ["prelim_narrative"],
    "evidence_version": "v1",
    "coding_stats_s3_sha256": "aa29bf42fba3dcd3672159464d41c2f106ba45cf3314b08ff22ec21231b47800",
    "items_csv_sha256": "3d42c7a3511e759c51238ee8275023a4c7eee16a98aa94e674f56120caf1bdb4",
}
PENDING_BACKFILL_FILE: Final = "live-pending-backfill.json"
PENDING_INPUTS_FILE: Final = "live-pending-inputs.jsonl"
REFUSALS_FILE: Final = "live-refusals.jsonl"
MORNING_COUNTS_FILE: Final = "live-morning-counts.jsonl"
MORNING_COUNTS_FORMAT: Final = "live-morning/1"
_SIDE_SUFFIXES: Final = ("-wal", "-shm")


def live_spec(budget_usd: float) -> RunSpec:
    """The spec of every live run: version 1's settings, the month's budget as given."""
    return RunSpec(
        sample=LIVE_SAMPLE,
        arm="C",
        evidence_version="v1",
        exclusions=frozenset({EvidenceRole.PRELIM_NARRATIVE}),
        model=MODEL_ID,
        reasoning_effort=REASONING_EFFORT,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        price_variant="standard",
        cap_usd=LIVE_CAP_USD,
        budget_usd=budget_usd,
        sync=True,
        expected_cost_per_case_usd=EXPECTED_COST_PER_CASE_USD,
        guidance=GUIDANCE,
    )


def _table_sha256(name: str) -> str:
    data = resources.files("ntsb_probable_cause.scoring").joinpath("tables", name).read_bytes()
    return hashlib.sha256(data).hexdigest()


def current_settings() -> dict[str, Any]:
    """The values the code would run a morning with, under :data:`VERSION_1_SETTINGS`' keys."""
    spec = live_spec(0.0)
    return {
        "stats": agent_run.STATS,
        "max_coding_calls": agent_run.MAX_CODING_CALLS,
        "without": sorted(WITHOUT),
        "pass_reasoning": agent_loop.PASS_REASONING,
        "temperature": ModelSettings().temperature,
        "model": spec.model,
        "reasoning_effort": spec.reasoning_effort,
        "max_output_tokens": spec.max_output_tokens,
        "cap_usd": spec.cap_usd,
        "price_variant": spec.price_variant,
        "sync": spec.sync,
        "exclusions": sorted(spec.exclusions),
        "evidence_version": spec.evidence_version,
        "coding_stats_s3_sha256": _table_sha256("coding_stats_s3.json"),
        "items_csv_sha256": _table_sha256("items.csv"),
    }


def settings_differences() -> list[str]:
    """The names of the settings whose current value is not version 1's; empty when all match."""
    now = current_settings()
    names = set(VERSION_1_SETTINGS) | set(now)
    return sorted(n for n in names if VERSION_1_SETTINGS.get(n) != now.get(n))


@dataclass(frozen=True)
class MorningDeps:
    """Everything the morning touches outside itself; a test gives a fake for each."""

    settings: Settings
    now: Callable[[], datetime]
    store: StoreSource
    spend: SpendCounter
    sink: ResultSink
    ntsb: Callable[[], NtsbClient]
    docket: Callable[[], DocketClient]
    models: Callable[[], tuple[ModelClient, BatchRunner | None]]
    commit: Callable[[], tuple[str, bool]]
    uv_lock_sha256: Callable[[], str]
    label: Callable[[], str] = lambda: prompt_version(GUIDANCE)


@dataclass(frozen=True)
class MorningSummary:
    """What a morning did, in counts; it names no case."""

    run_id: str | None
    coded: int
    not_coded: dict[str, int]  # reason -> count
    returned: int  # failed before seen, back in the queue
    queued: int  # left after this morning
    cost_usd: float
    billed_usd: float | None
    minutes: float
    freed_bytes: int
    warnings: tuple[str, ...]


def run_morning(
    deps: MorningDeps, *, dry_run: bool = False, limit: int | None = None
) -> MorningSummary:
    """Run one live morning.

    Args:
        deps: the outside world, as fakes or the deployed versions.
        dry_run: open the store, build the queue and fetch the first case and its docket, then
            print what a morning would do; no model is called and no run folder is written.
        limit: take at most this many cases (never more than the day's room).

    Returns:
        The morning's counts.

    Raises:
        ConfigurationError: the prompt-version label is not version 1, a setting is not version
            1's (:data:`VERSION_1_SETTINGS`), the recorder has not
            finished a run today, or an unfinished live run cannot be resumed.
        BudgetError: the month's live spend plus this morning's projection passes the cap.
    """
    began = deps.now()
    refusals = _Refusals(deps, enabled=not dry_run)
    label = deps.label()
    if label != VERSION_1:
        refusals.add("label")
        raise ConfigurationError(
            f"the agent's prompt version is {label}, not the frozen {VERSION_1}: a live "
            "morning runs version 1 only (decision 0161)"
        )
    differing = settings_differences()
    if differing:
        refusals.add("settings")
        raise ConfigurationError(
            f"these settings are not version 1's: {', '.join(differing)}. A live morning runs "
            "version 1 only (decisions 0156, 0161)"
        )
    settings = deps.settings
    live, development = settings.live_docket_dir.resolve(), settings.docket_dir.resolve()
    if live == development or live.is_relative_to(development) or development.is_relative_to(live):
        # Resolved, so a symlink to the same folder counts. One folder inside the other would
        # mix open-case documents with the development cache just as well.
        refusals.add("docket-folders")
        raise ConfigurationError(
            "live_docket_dir must differ from docket_dir, and neither may sit inside the other"
        )
    morning = _Morning(deps, deps.store.open(), began, refusals, dry_run=dry_run, limit=limit)
    try:
        return morning.run()
    finally:
        if not morning.interrupted:  # an interrupted run keeps its cache and store for a resume
            deps.store.discard()


class _Refusals:
    """Appends one ``{"at", "reason"}`` row per refusal, never a case id (for Task 10)."""

    def __init__(self, deps: MorningDeps, *, enabled: bool) -> None:
        self._deps = deps
        self._enabled = enabled

    def add(self, reason: str) -> None:
        if not self._enabled:
            return
        runs_dir = self._deps.settings.runs_dir
        runs_dir.mkdir(parents=True, exist_ok=True)
        row = {"at": self._deps.now().astimezone(UTC).isoformat(), "reason": reason}
        with (runs_dir / REFUSALS_FILE).open("a") as handle:
            handle.write(json.dumps(row) + "\n")


class _Morning:
    def __init__(  # noqa: PLR0913 -- one morning's seams and flags.
        self,
        deps: MorningDeps,
        store: Store,
        began: datetime,
        refusals: _Refusals,
        *,
        dry_run: bool,
        limit: int | None,
    ) -> None:
        self.deps = deps
        self.store = store
        self.began = began
        self.refusals = refusals
        self.dry_run = dry_run
        self.limit = limit
        self.today: date = began.astimezone(UTC).date()
        self.runs_dir = deps.settings.runs_dir
        self.warnings: list[str] = []
        self.interrupted = False
        self.lock_sha = ""

    # --- the order of a morning ---

    def run(self) -> MorningSummary:
        self.lock_sha = self.deps.uv_lock_sha256()  # read with the other checks, before any run
        if not self.dry_run:
            self._complete_unrecorded()
        if not self.store.run_finished_on(self.today):
            self.refusals.add("recorder-unfinished")
            raise ConfigurationError(
                f"the recorder has not finished a run on {self.today}: the store is not "
                "tonight's, so no case is coded"
            )
        unfinished = self.deps.sink.unfinished_run()
        if unfinished is not None:
            return self._resume(unfinished)
        coded_today = self.deps.sink.coded_on(self.today)
        room = DAILY_LIMIT - coded_today
        if room <= 0:
            self.refusals.add("daily-limit")
            self.warnings.append(f"the day's limit of {DAILY_LIMIT} cases is reached")
            return self._summary(None, [], returned=0, queued=0, record=None, freed=0)
        n = room if self.limit is None else min(room, self.limit)
        self._check_cap(n)
        done = self.deps.sink.done_case_ids()
        queue = build_queue(self.store.closures(), done)
        take = todays_take(queue, coded_today)[:n]
        if self.dry_run:
            return self._dry_run(queue, take)
        self._pin_backfill(queue)
        fetched, returned = self._fetch(take)
        if not fetched:
            summary = self._summary(
                None, [], returned=returned, queued=len(queue), record=None, freed=0
            )
            return self._log_counts(summary, queue_at_start=len(queue), taken=len(take))
        raws = [f.raw for f in fetched]
        self._write_pending(raws)
        return self._execute(
            fetched,
            raws,
            resume=None,
            returned=returned,
            done=done,
            queue_at_start=len(queue),
            taken=len(take),
        )

    def _check_cap(self, n: int, *, resuming: str | None = None) -> None:
        """Refuse before any fetch, folder or call when ``n`` cases do not fit a limit.

        Two limits: the live shadow's own $5 month (decision 163), and the all-purpose monthly
        guard (``monthly_budget_usd``, $40) that ``AgentRunner`` enforces again when it reserves.
        Checking the second here too means a refusal leaves nothing behind: ``AgentRunner`` makes
        its run folder and ``spec.json`` before it reserves, so its own refusal would leave a live
        folder with no ``run.jsonl`` that every later morning would find unfinished.

        Args:
            n: the cases this morning would code.
            resuming: the run being resumed; its own open reservation is not counted against it.

        Raises:
            BudgetError: a limit would be passed.
        """
        projected = self.deps.spend.live_month_usd(self.began) + n * EXPECTED_COST_PER_CASE_USD
        if projected > MONTHLY_CAP_USD:
            self.refusals.add("monthly-cap")
            raise BudgetError(
                f"live spend this month plus {n} cases at ${EXPECTED_COST_PER_CASE_USD} would "
                f"be ${projected:.2f}, past the ${MONTHLY_CAP_USD:.2f} monthly cap (decision 163)"
            )
        spent = month_spent(self.runs_dir, now=self.began)
        reserved = sum(v for k, v in open_reservations(self.runs_dir).items() if k != resuming)
        budget = self.deps.settings.monthly_budget_usd
        guarded = spent + reserved + n * EXPECTED_COST_PER_CASE_USD
        if guarded > budget:
            self.refusals.add("monthly-guard")
            raise BudgetError(
                f"${spent:.2f} spent this month and ${reserved:.2f} reserved by other runs, plus "
                f"{n} cases at ${EXPECTED_COST_PER_CASE_USD}, would be ${guarded:.2f}, past the "
                f"monthly guard of ${budget:.2f}: nothing was fetched and no run was made"
            )

    def _pin_backfill(self, queue: Sequence[QueuedCase]) -> None:
        """Fix the backfill on disk the first time the queue is seen, before anything can fail.

        It waits in ``live-pending-backfill.json`` and moves into the first live run's folder
        beside the inputs; a later morning never recomputes it (decision 0157).
        """
        pending = self.runs_dir / PENDING_BACKFILL_FILE
        if self.deps.sink.backfill() is not None or pending.is_file():
            return
        ids = tuple(sorted(q.case_id for q in queue))
        backfill = Backfill(fixed_on=self.today, case_ids=ids, sha256=backfill_digest(ids))
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        pending.write_text(backfill.model_dump_json() + "\n")

    def _dry_run(self, queue: Sequence[QueuedCase], take: Sequence[QueuedCase]) -> MorningSummary:
        _say(
            f"dry run: {len(queue)} cases queued; a morning would code {len(take)} "
            f"(at most {DAILY_LIMIT} a day)."
        )
        if take:
            fetched, _ = self._fetch(take[:1])
            if fetched:
                n = len(fetched[0].docket.documents)
                _say(f"dry run: fetched the first case's record and its docket ({n} documents).")
            else:
                _say("dry run: the first case could not be fetched.")
        _say("dry run: no model was called and no run folder was written.")
        return self._summary(None, [], returned=0, queued=len(queue), record=None, freed=0)

    def _fetch(self, take: Sequence[QueuedCase]) -> tuple[list[Prepared], int]:
        """Each case's record and docket, in order; a failure returns the case to the queue."""
        fetched: list[Prepared] = []
        returned = 0
        with contextlib.ExitStack() as stack:
            ntsb = stack.enter_context(self.deps.ntsb())
            docket_client = stack.enter_context(self.deps.docket())
            for case in take:
                try:
                    raw = fetch_record(ntsb, case)
                    docket = prefetch_docket(
                        docket_client,
                        case.mkey,
                        known_documents=self.store.documents_recorded(case.mkey),
                    )
                except FetchError:
                    returned += 1
                    continue
                fetched.append(Prepared(case, raw, docket))
        return fetched, returned

    def _prepare(self, raws: Sequence[dict[str, object]]) -> list[Prepared]:
        """Rebuild a run's cases from its inputs, the store's closures and the docket cache."""
        by_id = {q.case_id: q for q in build_queue(self.store.closures(), frozenset())}
        prepared: list[Prepared] = []
        with self.deps.docket() as docket_client:
            for raw in raws:
                case = by_id.get(str(raw["ntsbNumber"]))
                if case is None:
                    raise ConfigurationError("a live run holds a case that is not a closure")
                known = self.store.documents_recorded(case.mkey)
                docket = prefetch_docket(docket_client, case.mkey, known_documents=known)
                prepared.append(Prepared(case, raw, docket))
        return prepared

    # --- inputs and backfill, kept for an exact resume ---

    def _write_pending(self, raws: Sequence[Mapping[str, object]]) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        (self.runs_dir / PENDING_INPUTS_FILE).write_text(
            "".join(json.dumps(raw) + "\n" for raw in raws)
        )

    def _settle_pending(self, folder: Path) -> None:
        """Move the pending inputs and backfill into a live run's folder (or drop stale ones)."""
        for name, target_name in (
            (PENDING_INPUTS_FILE, INPUTS_FILE),
            (PENDING_BACKFILL_FILE, BACKFILL_FILE),
        ):
            pending = self.runs_dir / name
            if not pending.is_file():
                continue
            target = folder / target_name
            held = target_name == BACKFILL_FILE and self.deps.sink.backfill() is not None
            if target.exists() or held:
                pending.unlink()
            else:
                shutil.move(pending, target)

    def _settle_new_live_folder(self, before: set[str], error: BaseException) -> None:
        """After a failed run: the one new live run folder takes the pending files.

        Folders of other kinds (a development run started meanwhile) are never touched. None
        new means the runner failed before it made a folder: the pending files stay.
        """
        new = [n for n in sorted(_folders(self.runs_dir) - before) if _is_live(self.runs_dir / n)]
        if len(new) > 1:
            raise ConfigurationError(
                f"{len(new)} live run folders appeared during the run: the pending files are "
                "not moved into any of them"
            ) from error
        if new:
            self._settle_pending(self.runs_dir / new[0])

    def _resume(self, run_id: str) -> MorningSummary:
        folder = self.runs_dir / run_id
        self._settle_pending(folder)
        inputs = folder / INPUTS_FILE
        if not inputs.is_file():
            raise ConfigurationError(
                f"the unfinished live run {run_id} has no {INPUTS_FILE}, so it cannot be "
                "resumed with the records it began with"
            )
        raws = _read_inputs(inputs)
        if self.deps.sink.backfill() is None and not (folder / BACKFILL_FILE).is_file():
            raise ConfigurationError(
                f"the unfinished live run {run_id} is resumed with no backfill held anywhere: "
                "it is never recomputed from a later queue"
            )
        self._check_cap(len(raws) - len(_answered(folder)), resuming=run_id)
        if self.dry_run:
            _say(f"dry run: a morning would resume the unfinished run with {len(raws)} cases.")
            return self._summary(None, [], returned=0, queued=0, record=None, freed=0)
        prepared = self._prepare(raws)
        done = self.deps.sink.done_case_ids() - {p.case.case_id for p in prepared}
        return self._execute(
            prepared,
            raws,
            resume=run_id,
            returned=0,
            done=done,
            queue_at_start=len(build_queue(self.store.closures(), done)),
            taken=len(prepared),
        )

    def _complete_unrecorded(self) -> None:
        """Write the records of any finished live run that lacks them or its manifest."""
        for name in sorted(_folders(self.runs_dir)):
            folder = self.runs_dir / name
            if _is_live(folder) and _needs_records(folder):
                self._complete(name, None)
                self.warnings.append(f"completed the records of an earlier run, {name}")

    # --- the run ---

    def _execute(  # noqa: PLR0913 -- one run's inputs.
        self,
        prepared: Sequence[Prepared],
        raws: Sequence[dict[str, object]],
        *,
        resume: str | None,
        returned: int,
        done: frozenset[str],
        queue_at_start: int,
        taken: int,
    ) -> MorningSummary:
        deps, settings = self.deps, self.deps.settings
        spec = self._spec()
        if spec.model not in TRAINING_CUTOFFS:
            raise ConfigurationError(f"no recorded training cut-off for {spec.model}")
        client, batch = deps.models()
        with deps.docket() as docket_client:
            runner = AgentRunner(
                client,
                batch=batch,
                tables=load_tables(),
                stats=load_stats(agent_run.STATS),
                seen_pairs=seen_pairs(settings.data_dir / "processed"),
                runs_dir=self.runs_dir,
                month_spent_usd=month_spent(self.runs_dir, now=self.began),
                commit=deps.commit(),
                docket=CachedDocketReader(docket_client, readings=None),
                now=deps.now,
                pass_reasoning=agent_loop.PASS_REASONING,
                without=WITHOUT,
            )
            before = _folders(self.runs_dir)
            try:
                record = runner.run(spec, raws, resume=resume)
            except BaseException as error:
                self.interrupted = True
                self._settle_new_live_folder(before, error)
                raise
        self._settle_pending(self.runs_dir / record.run_id)
        records, freed = self._complete(record.run_id, prepared)
        freed += _store_bytes(self.store.path)
        ran = {p.case.case_id for p in prepared}
        queued = len(build_queue(self.store.closures(), done | ran))
        summary = self._summary(
            record.run_id, records, returned=returned, queued=queued, record=record, freed=freed
        )
        return self._log_counts(summary, queue_at_start=queue_at_start, taken=taken)

    def _log_counts(
        self, summary: MorningSummary, *, queue_at_start: int, taken: int
    ) -> MorningSummary:
        """Append the morning's counts (and its run id, if any); never a case id (Task 10)."""
        if not self.dry_run:
            row = {
                "format": MORNING_COUNTS_FORMAT,
                "at": self.deps.now().astimezone(UTC).isoformat(),
                "run_id": summary.run_id,
                "queue_at_start": queue_at_start,
                "taken": taken,
                "coded": summary.coded,
                "not_coded": sum(summary.not_coded.values()),
                "returned": summary.returned,
                "queued_after": summary.queued,
            }
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            with (self.runs_dir / MORNING_COUNTS_FILE).open("a") as handle:
                handle.write(json.dumps(row) + "\n")
        return summary

    def _complete(
        self, run_id: str, prepared: Sequence[Prepared] | None
    ) -> tuple[list[ClosureRecord], int]:
        """Write a finished run's closure records, backfill and manifest, then clean up."""
        folder = self.runs_dir / run_id
        if prepared is None:
            inputs = folder / INPUTS_FILE
            if not inputs.is_file():
                raise ConfigurationError(f"the finished live run {run_id} has no {INPUTS_FILE}")
            prepared = self._prepare(_read_inputs(inputs))
        records = build_records(folder, prepared, self.lock_sha)
        held = folder / BACKFILL_FILE
        backfill = Backfill.model_validate_json(held.read_text()) if held.is_file() else None
        self.deps.sink.write(run_id, records, backfill)
        return records, self._cleanup(prepared)

    def _spec(self) -> RunSpec:
        return live_spec(self.deps.settings.monthly_budget_usd)

    def _cleanup(self, prepared: Sequence[Prepared]) -> int:
        """Delete the run's cases' cached documents; return the bytes freed."""
        freed = 0
        live = self.deps.settings.live_docket_dir
        for p in prepared:
            folder = live / str(p.case.mkey)
            if folder.is_dir():
                freed += _tree_bytes(folder)
                shutil.rmtree(folder)
        return freed

    def _summary(  # noqa: PLR0913 -- the summary's own fields.
        self,
        run_id: str | None,
        records: Sequence[ClosureRecord],
        *,
        returned: int,
        queued: int,
        record: RunRecord | None,
        freed: int,
    ) -> MorningSummary:
        not_coded: dict[str, int] = {}
        for r in records:
            if r.outcome == "not coded":
                reason = failure_kind(r.failure)
                not_coded[reason] = not_coded.get(reason, 0) + 1
        return MorningSummary(
            run_id=run_id,
            coded=sum(1 for r in records if r.outcome == "coded"),
            not_coded=not_coded,
            returned=returned,
            queued=queued,
            cost_usd=sum(r.cost_usd for r in records),
            billed_usd=None if record is None else record.reported_batch_cost_usd,
            minutes=(self.deps.now() - self.began).total_seconds() / 60,
            freed_bytes=freed,
            warnings=tuple(self.warnings),
        )


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _folders(runs_dir: Path) -> set[str]:
    return {p.name for p in runs_dir.iterdir() if p.is_dir()} if runs_dir.is_dir() else set()


def _is_live(folder: Path) -> bool:
    try:
        loaded = json.loads((folder / "spec.json").read_text())
    except OSError, ValueError:
        return False
    return isinstance(loaded, dict) and loaded.get("sample") == LIVE_SAMPLE


def _needs_records(folder: Path) -> bool:
    """A finished run whose closure records or manifest are missing."""
    path = folder / RUN_FILE
    if not path.is_file():
        return False
    records = read_jsonl(path, RunRecord)
    if not records or records[-1].finished is None:
        return False
    return not (folder / CLOSURES_FILE).is_file() or not (folder / MANIFEST_FILE).is_file()


def _read_inputs(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _answered(folder: Path) -> set[str]:
    """Case ids a run folder holds an answer for (not ``aborted``)."""
    path = folder / CASES_FILE
    if not path.is_file():
        return set()
    results = read_jsonl(path, CaseResult)
    return {r.case_id for r in results if not (r.failure or "").startswith("aborted")}


def _store_bytes(path: Path) -> int:
    names = (path, *(path.with_name(path.name + s) for s in _SIDE_SUFFIXES))
    return sum(p.stat().st_size for p in names if p.is_file())


def _tree_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
