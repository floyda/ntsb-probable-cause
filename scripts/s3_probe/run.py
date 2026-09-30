"""scripts/s3_probe/run.py: the ``run`` command -- the per-case loop over real model calls.

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

Reads ``<data_dir>/probes/s3-probe/cases.json`` (Task 1's ``select``) and runs every listed
``dev-400`` case through :func:`scripts.s3_probe.loop.run_case` on a thread pool, one
:class:`~ntsb_probable_cause.model.openrouter.OpenRouterClient` per worker thread (the
``transcribe_all`` pattern in ``docket/transcribe.py``, also used by
``scoring/preparation.py``'s ``run_preparation``). Every finished case's trail is appended to
``trails.jsonl`` as it completes, so a crash keeps whatever finished; a ``SpendRecord`` is
written every five finished cases and once more for the remainder
(``scoring/budget.py``, kind ``"probe"`` since decision 0131; the 2026-09-29 jobs were written
as ``"inventory"``, the closest kind then allowed, and ``scripts/relabel_probe_spend.py``
relabels them). The run reserves ``RUN_CAP_USD`` against the monthly budget (decision
0083, $40) before it starts and settles that reservation in a ``finally``, exactly as
``run_preparation`` does for its own jobs.

Everything that can fail for a reason that has nothing to do with money -- a malformed
``cases.json``, a missing ``OPENROUTER_API_KEY`` -- is made to fail *before* the reservation is
made (``run_preparation``'s own "built before the reservation" fix, fix round 1, I2): a
reservation is never left open with nothing left in the function to settle it, because nothing
between the reservation and the ``finally`` that settles it can raise for a reason unrelated to
the run itself. A single case's own failure (a transport error ``run_case`` cannot recover
from) never aborts the run either: it is caught, counted, and printed as
``"failed: exception <type>"`` with no case number, and every other case still runs. The last
``SpendRecord`` reconciles to ``RunBudget.spent`` exactly (not to the sum of the trails it
happens to have on hand), so a call that was paid for by a case that then failed -- and so
never produced a trail of its own -- is never money the run drops on the floor. If any case
failed, ``cmd_run`` still finishes normally (settles, writes the final ``probe.json``, prints
the summary) and returns 1 rather than 0.

``--dry-run`` runs the identical path against :class:`DryRunClient`, which returns
schema-valid, zero-cost replies with no model call, no API key and no OpenRouter account: it
writes trails under the job folder but nothing at all to ``runs_dir`` (no reservation, no
spend rows). The controller runs it on the real selected cases before any paid run.
"""

import json
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from ntsb_probable_cause import gitinfo, sources
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    Usage,
)
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.budget import (
    SpendRecord,
    reserve_within_budget,
    settle,
    write_spend,
)
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, load_stats
from ntsb_probable_cause.scoring.records import write_jsonl
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.scoring.samples import seen_pairs as seen_pairs_of
from ntsb_probable_cause.settings import Settings
from scripts.s3_probe.budget import CASE_CAP_USD, MAX_OUTPUT_TOKENS, RUN_CAP_USD, RunBudget
from scripts.s3_probe.cases import CELLS, MKEY_FIELD, SELECTION_SEED, docket_reader
from scripts.s3_probe.loop import run_case
from scripts.s3_probe.prompts import GUIDANCE
from scripts.s3_probe.trail import CaseTrail

CASES_RELATIVE = Path("probes/s3-probe/cases.json")
PROBE_ROOT = Path("probes/s3-probe")
SPEND_KIND = "probe"  # decision 0131; the three 2026-09-29 jobs wrote "inventory" (relabelled).
CHUNK = 5
_RECONCILE_EPSILON_USD = 1e-9  # a float rounding sliver, never a real dollar


# ------------------------------------------------------------------------------------------
# Loading the selected cases
# ------------------------------------------------------------------------------------------


def _cells(settings: Settings) -> dict[str, dict[str, bool]]:
    """The case-ID -> cell mapping ``select`` wrote; refused if the file is absent."""
    path = settings.data_dir / CASES_RELATIVE
    if not path.is_file():
        raise ConfigurationError(
            f"{path} is missing; run `python -m scripts.s3_probe select` first"
        )
    return cast("dict[str, dict[str, bool]]", json.loads(path.read_text()))


def _validate_cells(cells: Mapping[str, object]) -> None:
    """Refuse a malformed ``cases.json`` before it can raise later, mid-reservation.

    ``_cell_counts`` reads ``v["fatal"]``/``v["has_scan"]`` unchecked; without this, a
    corrupted or hand-edited ``cases.json`` would raise ``KeyError`` from inside the
    reservation's ``try`` block, a config problem the reservation guard was never meant to
    pay for.
    """
    for case_id, cell in cells.items():
        if (
            not isinstance(cell, Mapping)
            or not isinstance(cell.get("fatal"), bool)
            or not isinstance(cell.get("has_scan"), bool)
        ):
            raise ConfigurationError(
                f"{case_id}: malformed cell in cases.json (need boolean 'fatal' and 'has_scan')"
            )


def _refuse_outside_dev_400(ids: Sequence[str]) -> None:
    """Refuse before any model call if a case is not in ``dev-400`` (constraints.md)."""
    dev_ids = frozenset(sample_ids("dev-400"))
    outside = sorted(set(ids) - dev_ids)
    if outside:
        raise ValueError(f"not in dev-400: {outside}")


def _items(
    settings: Settings, ids: Sequence[str]
) -> list[tuple[str, Mapping[str, object], Docket]]:
    """Every selected case's raw record and v2 docket, from the cache only."""
    raws = load_cases(settings.data_dir / "processed", ids)
    reader = docket_reader(settings)
    items: list[tuple[str, Mapping[str, object], Docket]] = []
    for case_id, raw in zip(ids, raws, strict=True):
        mkey = raw.get(MKEY_FIELD)
        if not isinstance(mkey, int):
            raise ConfigurationError(f"{case_id}: no {MKEY_FIELD!r} on the raw record")
        items.append((case_id, raw, reader.read(mkey)))
    return items


# ------------------------------------------------------------------------------------------
# DryRunClient: schema-valid, zero-cost, no key needed
# ------------------------------------------------------------------------------------------


class DryRunClient:
    """A ``ModelClient`` returning schema-valid canned replies, chosen by ``schema_name``.

    Every hypothesis reply carries no findings, so the refinement step is always skipped
    (``"not run: no findings"``) -- keeping the dry run simple rather than also fabricating a
    finding category and a matching item. A read-choice reply marks the first offered index
    read and every other one unread, reading the offered indices straight from the menu lines
    in the system text (the numbers ``prompts.menu`` writes, one per line, ``"N: ... pages"``)
    rather than tracking state of its own. A coding-check reply is always ``done``, so the
    checks make no tool call. Used only by ``--dry-run``: it spends nothing and needs no
    OpenRouter key.
    """

    def __init__(self, tables: CodeTables) -> None:
        """Pick one valid phase and event code, fixed for the client's lifetime."""
        self._phase = min(tables.phases)
        self._event = min(tables.events)

    def __enter__(self) -> DryRunClient:
        """Usable as a context manager, like the real client (Task 5's one-per-worker pattern)."""
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None = None,
        _value: BaseException | None = None,
        _tb: object = None,
    ) -> None:
        """Nothing to close."""
        return None

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        """One canned reply, priced at zero."""
        return ModelReply(
            content=self._reply(settings.schema_name, system),
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            model=settings.model,
            response_id="dry-run",
        )

    def _reply(self, schema_name: str, system: str) -> str:
        if schema_name == "hypothesis":
            return self._hypothesis()
        if schema_name == "read_choice":
            return self._read_choice(system)
        if schema_name == "coding_action":
            return self._coding_action()
        if schema_name == "refinement":
            return self._refinement()
        raise ValueError(f"the dry-run client has no reply for schema {schema_name!r}")

    def _hypothesis(self) -> str:
        return json.dumps(
            {
                "evidence_narrative": "Dry run: no evidence was read.",
                "occurrence": [{"phase": self._phase, "event": self._event, "probability": 0.5}],
                "findings": [],
                "probable_cause": "Dry run: no probable cause was formed.",
                "lay_explanation": "Dry run: no explanation was formed.",
                "confidence": 0.0,
                "abstain": False,
                "evidence_used": [],
            }
        )

    def _read_choice(self, system: str) -> str:
        offered = sorted({int(m.group(1)) for m in _MENU_LINE.finditer(system)})
        first = offered[0] if offered else None
        documents = [
            {"index": i, "read": i == first, "expected_effect": "dry run: nothing expected"}
            for i in offered
        ]
        return json.dumps({"documents": documents, "reason": "dry run: no real choice made"})

    def _coding_action(self) -> str:
        return json.dumps(
            {
                "done": True,
                "tool": None,
                "kind": None,
                "codes": [],
                "reason": "dry run: no checks made",
                "expected_effect": "dry run: nothing expected",
                "top3": [{"phase": self._phase, "event": self._event, "probability": 0.5}],
            }
        )

    def _refinement(self) -> str:
        # Never reached: every hypothesis above has empty findings, so refine is always
        # skipped. Kept for completeness, so an unexpected refine call still gets a valid
        # (empty) reply rather than an unhandled schema name.
        return json.dumps({"items": []})


# One of ``prompts.menu``'s offered-document lines, e.g. "3: 2 pages, 2 readable, about 8
# tokens, born-digital" or "...transcribed pages: 2". The "Already read:" and "Not available
# to read:" lines do not start with a digit, so neither matches.
_MENU_LINE = re.compile(r"^(\d+): \d+ pages,", re.MULTILINE)


# ------------------------------------------------------------------------------------------
# Client factories
# ------------------------------------------------------------------------------------------


def _openrouter_factory(settings: Settings) -> Callable[[ExitStack], Callable[[], ModelClient]]:
    """One ``OpenRouterClient`` per worker thread, closed when the run's exit stack unwinds."""
    key = settings.require_openrouter_key()

    def per_run(stack: ExitStack) -> Callable[[], ModelClient]:
        def make() -> ModelClient:
            return stack.enter_context(OpenRouterClient(key, base_url=settings.openrouter_base_url))

        return make

    return per_run


def _dry_run_factory(tables: CodeTables) -> Callable[[ExitStack], Callable[[], ModelClient]]:
    """One ``DryRunClient`` per worker thread; needs no key and closes to nothing."""

    def per_run(stack: ExitStack) -> Callable[[], ModelClient]:
        def make() -> ModelClient:
            return stack.enter_context(DryRunClient(tables))

        return make

    return per_run


# ------------------------------------------------------------------------------------------
# The case loop
# ------------------------------------------------------------------------------------------


def _run_cases(  # noqa: PLR0913 -- one seam per collaborator, as run_case's own signature.
    items: Sequence[tuple[str, Mapping[str, object], Docket]],
    client_factory: Callable[[], ModelClient],
    *,
    tables: CodeTables,
    stats: CodingStats,
    seen: frozenset[str],
    run_budget: RunBudget,
    workers: int,
    on_finished: Callable[[CaseTrail], None],
    on_failed: Callable[[BaseException], None],
) -> tuple[int, int]:
    """Run every item on a pool of ``workers`` threads; return ``(not_started, failed)``.

    Each finished trail is handed to ``on_finished`` in completion order, immediately -- the
    caller appends it to ``trails.jsonl`` and counts it towards the next spend chunk. Once a
    trail's ``stop_reason`` is ``"run_cap"``, every future not yet started is cancelled and
    counted as "not started"; a case already running when the run cap is hit is still awaited
    and reported -- a paid-for case is never silently dropped (the ``transcribe_all`` pattern
    in ``docket/transcribe.py``).

    A case that raises (a transport error ``run_case`` itself could not recover from) never
    aborts the run: its exception is caught, handed to ``on_failed``, and counted in
    ``failed`` -- every other case, whether already finished, still running, or not yet
    started, is unaffected. Whatever money that case's own successful calls already spent is
    still in ``run_budget.spent``; reconciling that against what the caller's spend rows
    actually cover is the caller's job (``cmd_run``'s final ``SpendRecord``), not this
    function's.
    """
    local = threading.local()

    def work(item: tuple[str, Mapping[str, object], Docket]) -> CaseTrail:
        client = getattr(local, "client", None)
        if client is None:
            client = local.client = client_factory()
        _case_id, raw, docket = item
        return run_case(
            raw,
            docket,
            client=client,
            tables=tables,
            stats=stats,
            seen_pairs=seen,
            budget=run_budget,
        )

    handled: set[int] = set()
    failed = 0

    def take(future: Future[CaseTrail]) -> bool:
        """Report one future's outcome; ``True`` only when it ends the run (``run_cap``)."""
        nonlocal failed
        handled.add(id(future))
        try:
            trail = future.result()
        except Exception as error:
            failed += 1
            on_failed(error)
            return False
        on_finished(trail)
        return trail.stop_reason == "run_cap"

    pool = ThreadPoolExecutor(max_workers=workers)
    futures: list[Future[CaseTrail]] = [pool.submit(work, item) for item in items]
    try:
        pending = set(futures)
        stopped = False
        while pending and not stopped:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                if take(future):
                    stopped = True
        if stopped:
            for future in pending:
                future.cancel()
    finally:
        # `wait=True` blocks until every future still running finishes (cancelled ones end
        # at once); anything that slipped past the loop above -- started just before it could
        # be cancelled, or finished during shutdown -- is folded in here, so a paid-for case
        # is never left unreported.
        pool.shutdown(wait=True, cancel_futures=True)
        for future in futures:
            if id(future) in handled or future.cancelled():
                continue
            take(future)
    not_started = sum(1 for future in futures if future.cancelled())
    return not_started, failed


# ------------------------------------------------------------------------------------------
# probe.json
# ------------------------------------------------------------------------------------------


def _cell_counts(cells: Mapping[str, Mapping[str, bool]]) -> dict[str, int]:
    """Per-cell counts of the *whole* selection in ``cases.json``, in ``CELLS`` order."""
    counts: dict[str, int] = {}
    for fatal, scan in CELLS:
        key = f"fatal={fatal} has_scan={scan}"
        counts[key] = sum(
            1 for v in cells.values() if v["fatal"] is fatal and v["has_scan"] is scan
        )
    return counts


@dataclass(frozen=True)
class _RunMeta:
    """Everything ``probe.json`` records about how a run was made, fixed once at the start."""

    job_id: str
    sha: str
    dirty: bool
    prompt_version: str
    guidance: Sequence[str]
    case_cap_usd: float
    run_cap_usd: float
    selection_seed: int
    per_cell: Mapping[str, int]
    cases_selected: int
    cases_run: int
    started: datetime


def _probe_json(meta: _RunMeta, *, finished: datetime | None = None) -> dict[str, Any]:
    """Everything Task 6 needs to know about how a run was made, as one JSON object."""
    body: dict[str, Any] = {
        "job_id": meta.job_id,
        "commit_sha": meta.sha,
        "dirty": meta.dirty,
        "model": sources.DEFAULT_MODEL,
        "price_variant": "standard",
        "reasoning_effort": sources.DEFAULT_REASONING_EFFORT,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "prompt_version": meta.prompt_version,
        "guidance": list(meta.guidance),
        "case_cap_usd": meta.case_cap_usd,
        "run_cap_usd": meta.run_cap_usd,
        "selection_seed": meta.selection_seed,
        "per_cell_counts": dict(meta.per_cell),
        "cases_selected": meta.cases_selected,
        "cases_run": meta.cases_run,
        "started": meta.started.isoformat(),
    }
    if finished is not None:
        body["finished"] = finished.isoformat()
    return body


def _write_probe(path: Path, meta: _RunMeta, *, finished: datetime | None = None) -> None:
    """Write (or rewrite) ``probe.json``."""
    text = json.dumps(_probe_json(meta, finished=finished), indent=2, sort_keys=True) + "\n"
    path.write_text(text)


# ------------------------------------------------------------------------------------------
# The command
# ------------------------------------------------------------------------------------------


def cmd_run(
    settings: Settings,
    *,
    limit: int | None,
    workers: int,
    dry_run: bool,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Run the selected ``dev-400`` cases through the eight-step loop.

    Refuses (before any model call, and before any reservation) if ``cases.json`` is absent
    or malformed, if a case it names is not in ``dev-400``, or -- for a paid run -- if
    ``OPENROUTER_API_KEY`` is unset. Then, for a paid run, refuses if the monthly budget has
    no room for ``RUN_CAP_USD``. Everything from that reservation onward -- the job folder,
    ``probe.json``, the pool -- runs inside one ``try``/``finally`` that settles the
    reservation whatever happens (`run_preparation`'s "built before the reservation" fix,
    applied here to a second seam it did not have: a case's own failure). Writes
    ``trails.jsonl`` and ``probe.json`` under ``<data_dir>/probes/s3-probe/<job_id>/``; a paid
    run also writes ``spend.jsonl`` under ``runs_dir/<job_id>/``. Prints one line per finished
    or failed case: index, stop reason (or ``"failed: exception <type>"``), cost -- never a
    case number.

    Returns:
        0 if every case finished without raising, 1 if any case failed.
    """
    cells = _cells(settings)
    _validate_cells(cells)
    ids = tuple(sorted(cells))
    _refuse_outside_dev_400(ids)
    run_ids = ids[:limit] if limit is not None else ids

    tables = load_tables()
    stats = load_stats()
    seen = seen_pairs_of(settings.data_dir / "processed")
    items = _items(settings, run_ids)

    started = now()
    sha, dirty = gitinfo.commit_state()
    job_id = f"s3-probe-{started:%Y%m%dT%H%M%S}-{sha}"
    meta = _RunMeta(
        job_id=job_id,
        sha=sha,
        dirty=dirty,
        prompt_version=prompt.PROMPT_VERSION,
        guidance=GUIDANCE,
        case_cap_usd=CASE_CAP_USD,
        run_cap_usd=RUN_CAP_USD,
        selection_seed=SELECTION_SEED,
        per_cell=_cell_counts(cells),
        cases_selected=len(cells),
        cases_run=len(run_ids),
        started=started,
    )
    # Built (and, for OpenRouter, its key checked) before the reservation: a missing key must
    # refuse here, not after a reservation nothing left in this function would ever settle.
    client_factory_builder = _dry_run_factory(tables) if dry_run else _openrouter_factory(settings)

    if not dry_run:
        reserve_within_budget(
            settings.runs_dir, job_id, RUN_CAP_USD, settings.monthly_budget_usd, now=started
        )
    job_dir = settings.data_dir / PROBE_ROOT / job_id
    # Declared before the reservation's try/finally, and checked for None inside it: a
    # failure as early as `job_dir.mkdir` must still settle the reservation, even though
    # `accounting` (which owns the last spend row) was never built to flush.
    accounting: _Accounting | None = None
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        _write_probe(job_dir / "probe.json", meta)
        run_budget = RunBudget()
        accounting = _Accounting(
            settings, meta, job_dir / "trails.jsonl", len(run_ids), run_budget, dry_run=dry_run
        )
        with ExitStack() as stack:
            not_started, failed = _run_cases(
                items,
                client_factory_builder(stack),
                tables=tables,
                stats=stats,
                seen=seen,
                run_budget=run_budget,
                workers=workers,
                on_finished=accounting.on_finished,
                on_failed=accounting.on_failed,
            )
    finally:
        if not dry_run:
            if accounting is not None:
                accounting.flush_final()
            settle(settings.runs_dir, job_id)

    _write_probe(job_dir / "probe.json", meta, finished=now())
    print(
        f"{len(accounting.finished)} cases finished, {failed} failed, "
        f"{not_started} not started; wrote {job_dir}"
    )
    return 1 if failed else 0


class _Accounting:
    """Every finished or failed case's bookkeeping: the trail file, the print line, spend.

    One instance per run, built after the job folder exists and before the pool starts.
    ``flush_final`` reconciles the last spend row to ``run_budget.spent`` exactly -- not to
    the sum of the trails on hand -- so a call billed to a case that then failed (and so
    produced no trail of its own) is still counted (Task 5 review, fix round 1, finding 2).
    """

    def __init__(  # noqa: PLR0913 -- one seam per fact a spend row or the trail file needs.
        self,
        settings: Settings,
        meta: _RunMeta,
        trails_path: Path,
        total: int,
        run_budget: RunBudget,
        *,
        dry_run: bool,
    ) -> None:
        """Hold what every callback needs; nothing here talks to the pool."""
        self._settings = settings
        self._meta = meta
        self._trails_path = trails_path
        self._total = total
        self._run_budget = run_budget
        self._dry_run = dry_run
        self._lock = threading.Lock()
        self._chunk: list[CaseTrail] = []
        self._written_usd = 0.0
        self._processed = 0
        self.finished: list[CaseTrail] = []

    def on_finished(self, trail: CaseTrail) -> None:
        """Record one finished case: its trail line, the print line, and its spend chunk."""
        with self._lock:
            write_jsonl(self._trails_path, [trail])
            self.finished.append(trail)
            self._chunk.append(trail)
            self._processed += 1
            print(f"{self._processed}/{self._total} {trail.stop_reason} ${trail.cost_usd:.4f}")
            if not self._dry_run and len(self._chunk) >= CHUNK:
                self._flush_periodic()

    def on_failed(self, error: BaseException) -> None:
        """Record one failed case: no trail (there is none), a print line, no case number."""
        with self._lock:
            self._processed += 1
            print(f"{self._processed}/{self._total} failed: exception {type(error).__name__}")

    def _flush_periodic(self) -> None:
        """A chunk of finished cases: its own calls and cost, known exactly from the trails."""
        amount = sum(t.cost_usd for t in self._chunk)
        self._write_row(calls=sum(len(t.calls) for t in self._chunk), cost=amount)
        self._written_usd += amount
        self._chunk.clear()

    def flush_final(self) -> None:
        """The remainder, reconciled to ``run_budget.spent`` -- including any orphaned cost."""
        with self._lock:
            remainder = self._run_budget.spent - self._written_usd
            if not self._chunk and remainder < _RECONCILE_EPSILON_USD:
                return
            cost = max(remainder, 0.0)  # a float rounding sliver never writes a negative row
            self._write_row(calls=sum(len(t.calls) for t in self._chunk), cost=cost)
            self._written_usd += cost
            self._chunk.clear()

    def _write_row(self, *, calls: int, cost: float) -> None:
        write_spend(
            self._settings.runs_dir,
            SpendRecord(
                job_id=self._meta.job_id,
                kind=SPEND_KIND,
                model=sources.DEFAULT_MODEL,
                started=self._meta.started,
                calls=calls,
                cost_usd=cost,
                commit_sha=self._meta.sha,
                dirty=self._meta.dirty,
            ),
        )
