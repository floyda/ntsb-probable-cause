"""One live morning: code the queued closed cases with the frozen agent (S3.3 spec 3 to 8).

``run_morning`` is library code. Every outside effect (the clock, the store, the spend counter,
the sink, the three client factories, the commit, the lockfile checksum and the prompt-version
label) comes in through :class:`MorningDeps`, so a test replaces each with a fake. The order is
fixed: label and settings, docket folders, the live key's spend, the store, the recorder's run,
a resume, the queue, the backfill, the fetches, the run, the closure records, the cleanup, the
night state. The night's size comes from money alone (decision 0170); a refusal is a
:class:`LiveRefusal` with a kind, and nothing that leaves the morning names a case (decision 0024).

The raw records of a run go to ``<runs_dir>/live-pending-inputs.jsonl`` before ``AgentRunner``
makes its folder (it creates the folder itself), and move to ``<run folder>/inputs.jsonl``
afterwards, so a resume reads back exactly the records the run began with, in order.
"""

import contextlib
import dataclasses
import hashlib
import json
import math
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
from ntsb_probable_cause.live.queue import QueuedCase, backfill_digest, build_queue
from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    INPUTS_FILE,
    MANIFEST_FILE,
    Backfill,
    ClosureRecord,
    failure_kind,
)
from ntsb_probable_cause.live.seams import MonthSpend, ResultSink, SpendCounter, StoreSource
from ntsb_probable_cause.live.state import NightState, after_fetches
from ntsb_probable_cause.model.client import ModelClient, ModelSettings
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.scoring.runner import (
    BatchRunner,
    CachedDocketReader,
    RunSpec,
    project_cost,
    refuse_over_budget,
)
from ntsb_probable_cause.scoring.samples import load_seen_pairs
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.sources import LUNA_6, TRAINING_CUTOFFS, ReasoningEffort
from ntsb_probable_cause.store import Closure, Store

LIVE_CAP_USD: Final = 0.30  # decision 0144, a version 1 setting
LIVE_MONTH_CAP_USD: Final = 9.0  # decision 0170
LIVE_MARGIN_USD: Final = 1.0  # kept below the key's own limit (decision 0170)

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
# edit of this table. The model is pinned by name here, a literal (decision 0169); `MODEL_ID`
# is the running side.
VERSION_1_SETTINGS: Final[Mapping[str, object]] = {
    "stats": "s3",
    "max_coding_calls": 6,
    "without": [],
    "pass_reasoning": False,
    "temperature": 0.0,
    # A literal, so an edit of `LUNA_6` cannot pass this check by moving both sides (decision 0169).
    "model": "openai/gpt-6-luna",
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

# Every alert kind a night or a morning can produce, each once (decision 0177; the S4 runbook's
# rows are checked against this list). Before any spend: the first seven are the kinds of a
# ``LiveRefusal``. During the night: ``state.after_fetches``'s kinds, ``money-held-back`` when the
# queue is longer than the money allows, ``fetch-failed`` for a fetch error that stops the
# night, ``awaiting-codes-7`` (``later.overdue``), ``export-failed`` and ``night-crashed``
# (``night.run_night``). Kinds are lower-case words and hyphens: ``cloud.SnsAlerts`` sends no
# other.
ALERT_KINDS: Final = (
    "version-refused",
    "docket-folders",
    "key-unreachable",
    "store-unsound",
    "recorder-not-finished",
    "money-held-back",
    "budget-guard",
    "fetch-failed",
    "outage",
    "unreachable-3",
    "unreachable-final",
    "awaiting-codes-7",
    "export-failed",
    "night-crashed",
)


def cases_tonight(spend: MonthSpend) -> tuple[int, float]:
    """Tonight's number of cases and the room in dollars, by the full-cap rule (decision 0170).

    Every case may run to its $0.30 cap, so no night can pass the key's limit.

    Args:
        spend: this month's spend on the live key and the limit it is held to.

    Returns:
        ``(cases, room)``: ``floor((cap - used) / $0.30)`` cases, ``cap`` being the lower of $9
        and the limit less $1, and the dollars left under ``cap``; neither is ever below 0.
    """
    cap = min(LIVE_MONTH_CAP_USD, spend.limit_usd - LIVE_MARGIN_USD)
    room = max(0.0, cap - spend.used_usd)
    return math.floor(room / LIVE_CAP_USD + 1e-9), room


def live_spec(budget_usd: float) -> RunSpec:
    """The spec of every live run: version 1's settings, the budget as given."""
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
        expected_cost_per_case_usd=LIVE_CAP_USD,
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


class LiveRefusal(ConfigurationError):  # noqa: N818 -- the name the S4 design fixes
    """A night that must not go on, with the kind an alert names (decision 0177).

    ``kind`` is one of ``"version-refused"``, ``"recorder-not-finished"``, ``"store-unsound"``,
    ``"key-unreachable"``, ``"money-held-back"``, ``"budget-guard"`` (the runner's own monthly
    guard, ``Settings.monthly_budget_usd``, checked before any run folder is made) and
    ``"docket-folders"``.

    Raises:
        ValueError: ``kind`` is not in :data:`ALERT_KINDS`.
    """

    def __init__(self, kind: str, message: str) -> None:
        if kind not in ALERT_KINDS:
            raise ValueError(f"{kind!r} is not an alert kind (ALERT_KINDS)")
        super().__init__(message)
        self.kind = kind


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
    # Given the open run folder once its pending inputs and backfill are in it, before the run's
    # first request; returns the observer the sync driver tells before that request and after
    # every reply (``drive.drive_sync``). The cloud night copies the folder to its bucket with
    # it (S4 Task 10). None: no observer.
    on_reply_factory: Callable[[Path], Callable[[], None]] | None = None


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
    held_back: int  # queued past tonight's number of cases, by money
    failures_counted: int = 0  # tonight's failed fetches that counted against a case (0175)


@dataclass(frozen=True)
class NightOutcome:
    """A morning's counts and the kinds of alert it raised; no case id is in either."""

    summary: MorningSummary
    alerts: tuple[str, ...]


def run_morning(
    deps: MorningDeps, *, dry_run: bool = False, limit: int | None = None
) -> NightOutcome:
    """Run one live morning.

    Args:
        deps: the outside world, as fakes or the deployed versions.
        dry_run: open the store, build the queue and fetch the first case and its docket, then
            print what a morning would do; no model is called and no run folder is written.
        limit: take at most this many cases (never more than tonight's number).

    Returns:
        The morning's counts and the kinds of alert it raised.

    Raises:
        LiveRefusal: kind ``version-refused`` (the prompt-version label is not version 1, or a
            setting is not version 1's, :data:`VERSION_1_SETTINGS`), ``docket-folders``,
            ``key-unreachable`` (from the spend counter), ``store-unsound``,
            ``recorder-not-finished``, ``money-held-back`` (an unfinished run needs more than
            the room), or ``budget-guard`` (the run would pass the settings' monthly guard;
            checked before any run folder is made).
        ConfigurationError: an unfinished live run cannot be resumed.
    """
    began = deps.now()
    refusals = _Refusals(deps, enabled=not dry_run)
    try:
        return _run_checked(deps, began, refusals, dry_run=dry_run, limit=limit)
    except LiveRefusal as refusal:
        refusals.add(refusal.kind)
        raise


def _run_checked(
    deps: MorningDeps, began: datetime, refusals: _Refusals, *, dry_run: bool, limit: int | None
) -> NightOutcome:
    label = deps.label()
    if label != VERSION_1:
        raise LiveRefusal(
            "version-refused",
            f"the agent's prompt version is {label}, not the frozen {VERSION_1}: a live "
            "morning runs version 1 only (decision 0161)",
        )
    differing = settings_differences()
    if differing:
        raise LiveRefusal(
            "version-refused",
            f"these settings are not version 1's: {', '.join(differing)}. A live morning runs "
            "version 1 only (decisions 0156, 0161)",
        )
    settings = deps.settings
    live, development = settings.live_docket_dir.resolve(), settings.docket_dir.resolve()
    if live == development or live.is_relative_to(development) or development.is_relative_to(live):
        # Resolved, so a symlink to the same folder counts. One folder inside the other would
        # mix open-case documents with the development cache just as well.
        raise LiveRefusal(
            "docket-folders",
            "live_docket_dir must differ from docket_dir, and neither may sit inside the other",
        )
    spend = deps.spend.month(began)  # before the store is opened; may raise key-unreachable
    morning = _Morning(
        deps, deps.store.open(), began, spend, refusals, dry_run=dry_run, limit=limit
    )
    try:
        return morning.run()
    finally:
        if not morning.interrupted:  # an interrupted run keeps its cache and store for a resume
            deps.store.discard()


class _Refusals:
    """Appends one ``{"at", "kind"}`` row per refusal, never a case id."""

    def __init__(self, deps: MorningDeps, *, enabled: bool) -> None:
        self._deps = deps
        self._enabled = enabled

    def add(self, kind: str) -> None:
        if not self._enabled:
            return
        runs_dir = self._deps.settings.runs_dir
        runs_dir.mkdir(parents=True, exist_ok=True)
        row = {"at": self._deps.now().astimezone(UTC).isoformat(), "kind": kind}
        with (runs_dir / REFUSALS_FILE).open("a") as handle:
            handle.write(json.dumps(row) + "\n")


class _Morning:
    def __init__(  # noqa: PLR0913 -- one morning's seams and flags.
        self,
        deps: MorningDeps,
        store: Store,
        began: datetime,
        spend: MonthSpend,
        refusals: _Refusals,
        *,
        dry_run: bool,
        limit: int | None,
    ) -> None:
        self.deps = deps
        self.store = store
        self.began = began
        self.cases, self.room = cases_tonight(spend)
        self.refusals = refusals
        self.dry_run = dry_run
        self.limit = limit
        self.today: date = began.astimezone(UTC).date()
        self.runs_dir = deps.settings.runs_dir
        self.warnings: list[str] = []
        self.interrupted = False
        self.lock_sha = ""
        self.alerts: list[str] = []
        self.new_state: NightState | None = None

    # --- the order of a morning ---

    def run(self) -> NightOutcome:
        self.lock_sha = self.deps.uv_lock_sha256()  # read with the other checks, before any run
        if not self.dry_run:
            self._complete_unrecorded()
        if not self.store.run_finished_on(self.today):
            raise LiveRefusal(
                "recorder-not-finished",
                f"the recorder has not finished a run on {self.today}: the store is not "
                "tonight's, so no case is coded",
            )
        unfinished = self.deps.sink.unfinished_run()
        if unfinished is not None:
            return self._outcome(self._resume(unfinished))
        state = self.deps.sink.night_state()
        done = self.deps.sink.done_case_ids()
        queue = build_queue(self._closures(), done | state.unreachable.keys())
        held_back = max(0, len(queue) - self.cases)
        if held_back:
            self.alerts.append("money-held-back")
            self.warnings.append(
                f"money holds back {held_back} of {len(queue)} queued cases tonight "
                f"(room ${self.room:.2f})"
            )
        n = self.cases if self.limit is None else min(self.cases, self.limit)
        take = queue[:n]
        if self.dry_run:
            return self._outcome(self._dry_run(queue, take, held_back))
        self._pin_backfill(queue)
        fetched, failed = self._fetch(take)
        self.new_state, kinds = after_fetches(state, take, failed, len(fetched))
        self.alerts.extend(kinds)
        # Written now, before any run: a night killed later keeps tonight's counted failures,
        # and a resume never counts them again (carried ruling 3, Task 7).
        self.deps.sink.write_night_state(self.new_state)
        # A case settled unreachable tonight is final, not returned (carried ruling 2, Task 7).
        returned = len(failed - self.new_state.unreachable.keys())
        counted = 0 if "outage" in kinds else len(failed)
        if not fetched:
            summary = self._summary(
                None, [], returned=returned, queued=len(queue), record=None, freed=0
            )
            summary = dataclasses.replace(summary, held_back=held_back, failures_counted=counted)
            return self._outcome(
                self._log_counts(summary, queue_at_start=len(queue), taken=len(take))
            )
        raws = [f.raw for f in fetched]
        self._write_pending(raws)
        summary = self._execute(
            fetched,
            raws,
            resume=None,
            returned=returned,
            done=done | self.new_state.unreachable.keys(),
            queue_at_start=len(queue),
            taken=len(take),
        )
        return self._outcome(
            dataclasses.replace(summary, held_back=held_back, failures_counted=counted)
        )

    def _outcome(self, summary: MorningSummary) -> NightOutcome:
        return NightOutcome(summary, tuple(dict.fromkeys(self.alerts)))

    def _closures(self) -> list[Closure]:
        """The store's closures; a store that is not sound is a refusal, not a crash."""
        try:
            return self.store.closures()
        except ConfigurationError as error:
            raise LiveRefusal("store-unsound", str(error)) from error

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

    def _dry_run(
        self, queue: Sequence[QueuedCase], take: Sequence[QueuedCase], held_back: int
    ) -> MorningSummary:
        _say(
            f"dry run: {len(queue)} cases queued; a morning would code {len(take)} "
            f"(money allows {self.cases} tonight; {held_back} held back)."
        )
        if take:
            fetched, _ = self._fetch(take[:1])
            if fetched:
                n = len(fetched[0].docket.documents)
                _say(f"dry run: fetched the first case's record and its docket ({n} documents).")
            else:
                _say("dry run: the first case could not be fetched.")
        _say("dry run: no model was called and no run folder was written.")
        summary = self._summary(None, [], returned=0, queued=len(queue), record=None, freed=0)
        return dataclasses.replace(summary, held_back=held_back)

    def _fetch(self, take: Sequence[QueuedCase]) -> tuple[list[Prepared], set[str]]:
        """Each case's record and docket, in order, and the ids whose fetch failed.

        A failed case returns to the queue; ``after_fetches`` decides whether it counts.
        """
        fetched: list[Prepared] = []
        failed: set[str] = set()
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
                    failed.add(case.case_id)
                    continue
                fetched.append(Prepared(case, raw, docket))
        return fetched, failed

    def _prepare(self, raws: Sequence[dict[str, object]]) -> list[Prepared]:
        """Rebuild a run's cases from its inputs, the store's closures and the docket cache."""
        by_id = {q.case_id: q for q in build_queue(self._closures(), frozenset())}
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

    def _new_live_folder(self, before: set[str]) -> Path | None:
        """The one live run folder made since ``before``; None if none was.

        Folders of other kinds (a development run started meanwhile) are never counted.

        Raises:
            ConfigurationError: more than one live run folder appeared.
        """
        new = [n for n in sorted(_folders(self.runs_dir) - before) if _is_live(self.runs_dir / n)]
        if len(new) > 1:
            raise ConfigurationError(
                f"{len(new)} live run folders appeared during the run: the pending files are "
                "not moved into any of them"
            )
        return self.runs_dir / new[0] if new else None

    def _settle_new_live_folder(self, before: set[str], error: BaseException) -> None:
        """After a failed run: the one new live run folder takes the pending files.

        None new means the runner failed before it made a folder: the pending files stay.
        """
        try:
            folder = self._new_live_folder(before)
        except ConfigurationError as many:
            raise many from error
        if folder is not None:
            self._settle_pending(folder)

    def _reply_hook(self, resume: str | None, before: set[str]) -> Callable[[], None] | None:
        """The observer the runner's sync driver tells, built on its first telling.

        The first telling comes before the run's first request. The run folder exists by then
        (the runner made it, or it is the resumed one), so the pending inputs and backfill move
        into it first, and only then is the folder given to ``on_reply_factory``: a resume
        needs those files, so they are in the folder before anything is paid for (S4 Task 10).
        """
        factory = self.deps.on_reply_factory
        if factory is None:
            return None
        built: list[Callable[[], None]] = []

        def hook() -> None:
            if not built:
                folder = self.runs_dir / resume if resume else self._new_live_folder(before)
                if folder is None:
                    raise ConfigurationError("the runner sent a request before it made a folder")
                self._settle_pending(folder)
                built.append(factory(folder))
            built[0]()

        return hook

    def _check_budget(self, spec: RunSpec, cases: int, resume: str | None) -> None:
        """The runner's own monthly guard, asked before it makes a folder (carried ruling 1).

        The rule of ``scoring.runner.reserve_run_budget``: this month's spend, plus every other
        run's open reservation, plus the projection, must fit ``spec.budget_usd``. A refusal
        here leaves no run folder for later nights to resume and trip on.

        Raises:
            LiveRefusal: kind ``budget-guard``.
        """
        reserved = sum(v for k, v in open_reservations(self.runs_dir).items() if k != resume)
        try:
            refuse_over_budget(
                project_cost(spec, cases),
                month_spent(self.runs_dir, now=self.began),
                spec.budget_usd,
                reserved=reserved,
            )
        except BudgetError as error:
            raise LiveRefusal("budget-guard", str(error)) from error

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
        unanswered = len(raws) - len(_answered(folder))
        if unanswered * LIVE_CAP_USD > self.room + 1e-9:
            raise LiveRefusal(
                "money-held-back",
                f"the unfinished run has {unanswered} cases to answer, which at the "
                f"${LIVE_CAP_USD} cap a case needs more than the ${self.room:.2f} left this month",
            )
        if self.dry_run:
            _say(f"dry run: a morning would resume the unfinished run with {len(raws)} cases.")
            return self._summary(None, [], returned=0, queued=0, record=None, freed=0)
        prepared = self._prepare(raws)
        hidden = self.deps.sink.night_state().unreachable.keys()
        done = (self.deps.sink.done_case_ids() | hidden) - {p.case.case_id for p in prepared}
        return self._execute(
            prepared,
            raws,
            resume=run_id,
            returned=0,
            done=done,
            queue_at_start=len(build_queue(self._closures(), done)),
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
        deps = self.deps
        spec = self._spec()
        if spec.model not in TRAINING_CUTOFFS:
            raise ConfigurationError(f"no recorded training cut-off for {spec.model}")
        self._check_budget(spec, len(raws), resume)
        client, batch = deps.models()
        spent = month_spent(self.runs_dir, now=self.began)
        before = _folders(self.runs_dir)
        with deps.docket() as docket_client:
            runner = AgentRunner(
                client,
                batch=batch,
                tables=load_tables(),
                stats=load_stats(agent_run.STATS),
                seen_pairs=load_seen_pairs(),
                runs_dir=self.runs_dir,
                month_spent_usd=spent,
                commit=deps.commit(),
                docket=CachedDocketReader(docket_client, readings=None),
                now=deps.now,
                pass_reasoning=agent_loop.PASS_REASONING,
                without=WITHOUT,
                on_reply=self._reply_hook(resume, before),
            )
            try:
                record = runner.run(spec, raws, resume=resume)
            except BudgetError as error:  # asked above, so a backstop only
                raise LiveRefusal("budget-guard", str(error)) from error
            except BaseException as error:
                self.interrupted = True
                self._settle_new_live_folder(before, error)
                raise
        self._settle_pending(self.runs_dir / record.run_id)
        records, freed = self._complete(record.run_id, prepared)
        freed += _store_bytes(self.store.path)
        ran = {p.case.case_id for p in prepared}
        queued = len(build_queue(self._closures(), done | ran))
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
        # The records take the documents' hashes from the cache, so they are built before
        # _cleanup deletes it. Do not reorder these two.
        records = build_records(folder, prepared, self.lock_sha, self.deps.settings.live_docket_dir)
        held = folder / BACKFILL_FILE
        backfill = Backfill.model_validate_json(held.read_text()) if held.is_file() else None
        self.deps.sink.write(run_id, records, backfill)
        return records, self._cleanup(prepared)

    def _spec(self) -> RunSpec:
        """The run's spec.

        Its budget is the settings' monthly guard, as in S3.3, not tonight's room: the runner
        refuses a resume whose spec differs from the run's first one, and the room changes as the
        month's spend does. The money was decided by :func:`cases_tonight` before any fetch, so
        this is a backstop that the cloud's empty runs folder never reaches.
        """
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
            held_back=0,
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
