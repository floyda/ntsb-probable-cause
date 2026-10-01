"""The monthly budget: finished spend plus open reservations, under a lock (decision 0045).

A run reserves its projected cost at start and settles it at the end. A run launched a
second later sees the reservation. A run that dies leaves its reservation standing, so the
guard errs towards refusing; ``release`` clears one by hand.
"""

import fcntl
import json
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.errors import BudgetError
from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl, write_jsonl

RESERVATION_FILE = "reservation.json"
LOCK_FILE = ".budget.lock"
SPEND_FILE = "spend.jsonl"
# The original rows of a job whose rows were relabelled (decision 0131 item 3). The budget code
# reads ``*/spend.jsonl`` only, so this copy is kept beside the new rows and is never counted.
RELABEL_FILE = "spend-before-relabel.jsonl"


class SpendRecord(BaseModel):
    """Paid work that is not an evaluation run: evidence preparation (decision 0081).

    A job appends one row per chunk of calls, so a job that dies mid-way has still recorded
    what it spent up to its last chunk. ``probe`` (decision 0131) is paid work that tests a
    shape or a flow and is neither an evaluation run nor evidence preparation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    kind: Literal["inventory", "transcriber-test", "transcription", "probe"]
    model: str
    started: datetime
    calls: int
    cost_usd: float
    commit_sha: str
    dirty: bool


def write_spend(runs_dir: Path, record: SpendRecord) -> None:
    """Append one spend row under the job's own folder in the runs directory."""
    write_jsonl(runs_dir / record.job_id / SPEND_FILE, [record])


# Decision 0135: the run kinds whose spend counts what the provider billed. Arm C's runs, and arm
# B's tool post-pass, a derived arm B run whose prompt version holds this mark (``agent/armb.py``).
BILLED_ARMS = frozenset({"C"})
TOOLS_MARK = "+tools-"


def counts_billed(record: RunRecord) -> bool:
    """Whether a run's spend is the provider's reported total, not the computed price (0135).

    True for S3's own kinds of run (arm C, and arm B's tool post-pass) when every batch round
    reported its cost (``reported_batch_cost_usd`` is not None). A sync run has no rounds, so
    no reported total; nor does a judge pass or an ordering check, which call synchronously.
    No run from before S3 is of these kinds, so none changes what it counts.
    """
    return record.reported_batch_cost_usd is not None and (
        record.arm in BILLED_ARMS or TOOLS_MARK in record.prompt_version
    )


def spent_usd(record: RunRecord) -> float:
    """What one run record counts as spent, in the monthly guard and a stage's spend line.

    The provider's reported total (``reported_batch_cost_usd``) when ``counts_billed``, else the
    computed price (``cost_usd``). The computed price prices every prompt token at the full
    input rate, cached ones too, so it errs high; it stays in the record, and the per-case cap
    keeps using it (decision 0135).
    """
    reported = record.reported_batch_cost_usd
    return reported if reported is not None and counts_billed(record) else record.cost_usd


def month_spent(runs_dir: Path, *, now: datetime) -> float:
    """Cost of every run started in ``now``'s month, aborted runs included.

    A run folder's ``run.jsonl`` may hold more than one ``RunRecord`` (the answering run
    and a judge pass), and every one of them counts, each as ``spent_usd`` says (0135). So does
    every preparation job's spend rows (0081). Reservations are not spend and are not counted
    here.
    """
    if not runs_dir.exists():
        return 0.0
    total = 0.0
    for run_file in sorted(runs_dir.glob("*/run.jsonl")):
        for record in read_jsonl(run_file, RunRecord):
            if record.started.year == now.year and record.started.month == now.month:
                total += spent_usd(record)
    for spend_file in sorted(runs_dir.glob(f"*/{SPEND_FILE}")):
        for spend in read_jsonl(spend_file, SpendRecord):
            if spend.started.year == now.year and spend.started.month == now.month:
                total += spend.cost_usd
    return total


# Recorded commit SHAs are short (``git rev-parse --short``); a stage's commits are full. A
# recorded SHA matches by prefix, and one shorter than this is refused as ambiguous.
MIN_SHA_PREFIX = 4


def in_stage(sha: str, stage_commits: Collection[str]) -> bool:
    """Whether a recorded (short) commit SHA is one of a stage's (full) commits."""
    return len(sha) >= MIN_SHA_PREFIX and any(full.startswith(sha) for full in stage_commits)


def stage_spent(runs_dir: Path, stage_commits: Collection[str]) -> tuple[float, float]:
    """A stage's spend by commit: (evaluation run records, preparation spend rows).

    Counted by commit, not by date, because S2.6 found a date filter caught another stage's
    runs (decision 0098 item 6). A judge pass is a run record (``<run id>-judge``) and counts.
    Each run record counts as ``spent_usd`` says (decision 0135).
    """
    runs = sum(
        spent_usd(record)
        for path in sorted(runs_dir.glob("*/run.jsonl"))
        for record in read_jsonl(path, RunRecord)
        if in_stage(record.commit_sha, stage_commits)
    )
    spend = sum(
        row.cost_usd
        for path in sorted(runs_dir.glob(f"*/{SPEND_FILE}"))
        for row in read_jsonl(path, SpendRecord)
        if in_stage(row.commit_sha, stage_commits)
    )
    return runs, spend


@contextmanager
def budget_lock(runs_dir: Path) -> Iterator[None]:
    """Hold the runs directory's budget lock for the duration of the block."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    with (runs_dir / LOCK_FILE).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def reserve(runs_dir: Path, run_id: str, projected_usd: float, *, now: datetime) -> None:
    """Write the run's projected cost as an open reservation."""
    folder = runs_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RESERVATION_FILE).write_text(
        json.dumps({"projected_usd": projected_usd, "started": now.isoformat()})
    )


def settle(runs_dir: Path, run_id: str) -> None:
    """Remove the run's reservation; its actual cost is in ``run.jsonl`` by now."""
    (runs_dir / run_id / RESERVATION_FILE).unlink(missing_ok=True)


def release(runs_dir: Path, run_id: str) -> bool:
    """Clear a dead run's reservation by hand; True if one was open."""
    path = runs_dir / run_id / RESERVATION_FILE
    if not path.exists():
        return False
    path.unlink()
    return True


def open_reservations(runs_dir: Path) -> dict[str, float]:
    """Every open reservation, run id to projected dollars."""
    if not runs_dir.exists():
        return {}
    found: dict[str, float] = {}
    for path in sorted(runs_dir.glob(f"*/{RESERVATION_FILE}")):
        projected = json.loads(path.read_text()).get("projected_usd")
        if isinstance(projected, int | float):
            found[path.parent.name] = float(projected)
    return found


def reserve_within_budget(
    runs_dir: Path, job_id: str, projected_usd: float, budget_usd: float, *, now: datetime
) -> None:
    """Refuse a preparation job that would take the month past its budget, then reserve it.

    The same rule as an evaluation run's (``runner._reserve_budget``, 0045): spend so far,
    plus every other open reservation, plus this job's projection, must fit the budget.
    """
    with budget_lock(runs_dir):
        spent = month_spent(runs_dir, now=now)
        reserved = sum(v for k, v in open_reservations(runs_dir).items() if k != job_id)
        if spent + reserved + projected_usd > budget_usd:
            raise BudgetError(
                f"projected ${projected_usd:.2f} plus ${spent:.2f} spent and ${reserved:.2f} "
                f"reserved by other runs exceeds the ${budget_usd:.2f} budget"
            )
        reserve(runs_dir, job_id, projected_usd, now=now)
