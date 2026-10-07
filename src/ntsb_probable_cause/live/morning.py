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
import json
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Final

from ntsb_probable_cause.agent import loop as agent_loop
from ntsb_probable_cause.agent import run as agent_run
from ntsb_probable_cause.agent.run import GUIDANCE, AgentRunner
from ntsb_probable_cause.agent.schemas import ChooseDocuments
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.agent.version import VERSION_1, prompt_version
from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.live.fetch import FetchError, fetch_record, prefetch_docket, prelim_present
from ntsb_probable_cause.live.local import LIVE_SAMPLE
from ntsb_probable_cause.live.queue import (
    DAILY_LIMIT,
    QueuedCase,
    backfill_digest,
    build_queue,
    todays_take,
    waited_days,
)
from ntsb_probable_cause.live.records import INPUTS_FILE, Backfill, ClosureRecord, DocumentLine
from ntsb_probable_cause.live.seams import ResultSink, SpendCounter, StoreSource
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.scoring.budget import month_spent
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner, CachedDocketReader, RunSpec
from ntsb_probable_cause.scoring.samples import seen_pairs
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.sources import TRAINING_CUTOFFS
from ntsb_probable_cause.store import Store

LIVE_CAP_USD: Final = 0.30  # decision 163
MONTHLY_CAP_USD: Final = 5.0  # decision 163
EXPECTED_COST_PER_CASE_USD: Final = 0.015  # estimate, spec section 9; the reservation's projection
LATE_START_UTC: Final = time(9, 0)  # spec section 4: warn after this

PENDING_INPUTS_FILE: Final = "live-pending-inputs.jsonl"
REFUSALS_FILE: Final = "live-refusals.jsonl"
_CHOICE_STEPS: Final = frozenset({"choice1", "choice2"})
_SIDE_SUFFIXES: Final = ("-wal", "-shm")


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


@dataclass(frozen=True)
class _Fetched:
    case: QueuedCase
    raw: dict[str, object]
    docket: Docket


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
        ConfigurationError: the prompt-version label is not version 1, the recorder has not
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
    settings = deps.settings
    if settings.live_docket_dir.resolve() == settings.docket_dir.resolve():
        raise ConfigurationError("live_docket_dir must differ from docket_dir")
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
        if began.astimezone(UTC).time() > LATE_START_UTC:
            self.warnings.append(f"started after {LATE_START_UTC:%H:%M} UTC")

    # --- the order of a morning ---

    def run(self) -> MorningSummary:
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
        projected = self.deps.spend.live_month_usd(self.began) + n * EXPECTED_COST_PER_CASE_USD
        if projected > MONTHLY_CAP_USD:
            self.refusals.add("monthly-cap")
            raise BudgetError(
                f"live spend this month plus {n} cases at ${EXPECTED_COST_PER_CASE_USD} would "
                f"be ${projected:.2f}, past the ${MONTHLY_CAP_USD:.2f} monthly cap (decision 163)"
            )
        done = self.deps.sink.done_case_ids()
        queue = build_queue(self.store.closures(), done)
        take = todays_take(queue, coded_today)[:n]
        if self.dry_run:
            return self._dry_run(queue, take)
        backfill = self._backfill(queue)
        fetched, returned = self._fetch(take)
        if not fetched:
            return self._summary(
                None, [], returned=returned, queued=len(queue), record=None, freed=0
            )
        raws = [f.raw for f in fetched]
        self._write_pending(raws)
        return self._execute(
            fetched, raws, resume=None, backfill=backfill, returned=returned, done=done
        )

    def _backfill(self, queue: Sequence[QueuedCase]) -> Backfill | None:
        """The whole queue as it stands, on the first morning only."""
        if self.deps.sink.backfill() is not None:
            return None
        ids = tuple(sorted(q.case_id for q in queue))
        return Backfill(fixed_on=self.today, case_ids=ids, sha256=backfill_digest(ids))

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

    def _fetch(self, take: Sequence[QueuedCase]) -> tuple[list[_Fetched], int]:
        """Each case's record and docket, in order; a failure returns the case to the queue."""
        fetched: list[_Fetched] = []
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
                fetched.append(_Fetched(case, raw, docket))
        return fetched, returned

    # --- inputs, for an exact resume ---

    def _write_pending(self, raws: Sequence[Mapping[str, object]]) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        (self.runs_dir / PENDING_INPUTS_FILE).write_text(
            "".join(json.dumps(raw) + "\n" for raw in raws)
        )

    def _settle_pending(self, folder: Path) -> None:
        """Move the pending inputs into the run's folder (or drop a stale copy)."""
        pending = self.runs_dir / PENDING_INPUTS_FILE
        if not pending.is_file():
            return
        target = folder / INPUTS_FILE
        if target.exists():
            pending.unlink()
        else:
            shutil.move(pending, target)

    def _resume(self, run_id: str) -> MorningSummary:
        folder = self.runs_dir / run_id
        self._settle_pending(folder)
        inputs = folder / INPUTS_FILE
        if not inputs.is_file():
            raise ConfigurationError(
                f"the unfinished live run {run_id} has no {INPUTS_FILE}, so it cannot be "
                "resumed with the records it began with"
            )
        raws = [json.loads(line) for line in inputs.read_text().splitlines() if line.strip()]
        if self.dry_run:
            _say(f"dry run: a morning would resume the unfinished run with {len(raws)} cases.")
            return self._summary(None, [], returned=0, queued=0, record=None, freed=0)
        closures = self.store.closures()
        by_id = {q.case_id: q for q in build_queue(closures, frozenset())}
        fetched: list[_Fetched] = []
        with self.deps.docket() as docket_client:
            for raw in raws:
                case = by_id.get(str(raw["ntsbNumber"]))
                if case is None:
                    raise ConfigurationError(f"the unfinished run {run_id} holds a case not closed")
                known = self.store.documents_recorded(case.mkey)
                docket = prefetch_docket(docket_client, case.mkey, known_documents=known)
                fetched.append(_Fetched(case, raw, docket))
        done = self.deps.sink.done_case_ids() - {f.case.case_id for f in fetched}
        backfill = self._backfill(build_queue(closures, done))
        return self._execute(fetched, raws, resume=run_id, backfill=backfill, returned=0, done=done)

    # --- the run ---

    def _execute(  # noqa: PLR0913 -- the morning's state, passed on once.
        self,
        fetched: Sequence[_Fetched],
        raws: Sequence[dict[str, object]],
        *,
        resume: str | None,
        backfill: Backfill | None,
        returned: int,
        done: frozenset[str],
    ) -> MorningSummary:
        deps, settings = self.deps, self.deps.settings
        spec = self._spec()
        cutoff = TRAINING_CUTOFFS.get(spec.model)
        if cutoff is None:
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
            )
            before = _folders(self.runs_dir)
            try:
                record = runner.run(spec, raws, resume=resume)
            except BaseException:
                self.interrupted = True
                for name in sorted(_folders(self.runs_dir) - before):
                    self._settle_pending(self.runs_dir / name)
                raise
        self._settle_pending(self.runs_dir / record.run_id)
        records = self._records(record, fetched, deps.uv_lock_sha256())
        deps.sink.write(record.run_id, records, backfill)
        freed = self._cleanup(fetched)
        ran = {f.case.case_id for f in fetched}
        queued = len(build_queue(self.store.closures(), done | ran))
        return self._summary(
            record.run_id, records, returned=returned, queued=queued, record=record, freed=freed
        )

    def _spec(self) -> RunSpec:
        return RunSpec(
            sample=LIVE_SAMPLE,
            arm="C",
            evidence_version="v1",
            exclusions=frozenset({EvidenceRole.PRELIM_NARRATIVE}),
            price_variant="batch",
            cap_usd=LIVE_CAP_USD,
            budget_usd=self.deps.settings.monthly_budget_usd,
            sync=False,
            expected_cost_per_case_usd=EXPECTED_COST_PER_CASE_USD,
            guidance=GUIDANCE,
        )

    # --- the records ---

    def _records(
        self, record: RunRecord, fetched: Sequence[_Fetched], lock_sha: str
    ) -> list[ClosureRecord]:
        folder = self.runs_dir / record.run_id
        results = {r.case_id: r for r in read_jsonl(folder / "cases.jsonl", CaseResult)}
        trail = folder / agent_run.TRAIL_FILE
        calls = read_jsonl(trail, AgentCall) if trail.is_file() else []
        cutoff = TRAINING_CUTOFFS[record.model]
        out: list[ClosureRecord] = []
        for f in fetched:
            case_calls = [c for c in calls if c.case_id == f.case.case_id]
            result = results.get(f.case.case_id)
            scored = result is not None and bool(result.verdict_occurrence)
            scores = result.scores if scored and result is not None else None
            failure = "missing result" if result is None else result.failure
            out.append(
                ClosureRecord(
                    case_id=f.case.case_id,
                    mkey=f.case.mkey,
                    closed_on=f.case.closed_on,
                    closure_run=f.case.closure_run,
                    waited_days=waited_days(f.case, record.started.astimezone(UTC).date()),
                    first_sent=min((c.sent_at for c in case_calls), default=None),
                    last_returned=max((c.returned_at for c in case_calls), default=None),
                    commit_sha=record.commit_sha,
                    dirty=record.dirty,
                    prompt_version=record.prompt_version,
                    price_variant="batch" if record.price_variant == "batch" else "standard",
                    model=record.model,
                    reasoning_effort=record.reasoning_effort,
                    training_cutoff=cutoff.day,
                    training_cutoff_source=cutoff.source,
                    uv_lock_sha256=lock_sha,
                    documents=_document_lines(f.docket, case_calls),
                    prelim_present=prelim_present(f.raw),
                    outcome="not coded" if failure else "coded",
                    failure=failure,
                    marks=() if result is None else tuple(m.kind for m in result.marks),
                    scored=scored,
                    top1=None if scores is None else scores.occurrence_top1,
                    top3=None if scores is None else scores.occurrence_top3,
                    abstained=None if scores is None else scores.abstained,
                    cost_usd=0.0 if result is None else result.cost_usd,
                )
            )
        return out

    def _cleanup(self, fetched: Sequence[_Fetched]) -> int:
        """Delete the run's cases' cached documents and the store work copy; count the bytes."""
        freed = 0
        live = self.deps.settings.live_docket_dir
        for f in fetched:
            folder = live / str(f.case.mkey)
            if folder.is_dir():
                freed += _tree_bytes(folder)
                shutil.rmtree(folder)
        path = self.store.path
        for candidate in (path, *(path.with_name(path.name + s) for s in _SIDE_SUFFIXES)):
            if candidate.is_file():
                freed += candidate.stat().st_size
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
                reason = (r.failure or "unknown").split(":", 1)[0]
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


def _document_lines(docket: Docket, calls: Sequence[AgentCall]) -> tuple[DocumentLine, ...]:
    """Each document's status, and what the agent decided: read, skipped, or never on offer."""
    offered: set[int] = set()
    read: set[int] = set()
    for call in calls:
        if call.step not in _CHOICE_STEPS or call.protocol_error is not None:
            continue
        offered.update(call.offered)
        choice = ChooseDocuments.model_validate(call.arguments)
        read.update(d.document for d in choice.decisions if d.read and d.document in call.offered)
    return tuple(
        DocumentLine(
            position=d.entry.index,
            title=d.entry.title,
            status=d.status,
            ellery=("read" if d.entry.index in read else "skipped")
            if d.entry.index in offered
            else None,
        )
        for d in docket.documents
    )


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _folders(runs_dir: Path) -> set[str]:
    return {p.name for p in runs_dir.iterdir() if p.is_dir()} if runs_dir.is_dir() else set()


def _tree_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
