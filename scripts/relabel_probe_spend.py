"""scripts/relabel_probe_spend.py: relabel the learning probe's spend rows from inventory to probe.

Status
    One-shot (S3.1, decision 0131). Run once by the controller, after the ``probe`` spend kind
    is on the branch. Output is three lines, one per job: rows and total cost. No case text
    exists in these rows (a row holds a job id, a model, a time, counts, a cost and a commit).

Why
    The learning probe (pull request #18) wrote its three jobs' rows with the kind
    ``inventory``, the closest kind then allowed; ``inventory`` names S2.6's page inventory, not
    a probe. Decision 0131 adds the kind ``probe`` and relabels those rows. Each job's original
    rows are kept beside the new ones as ``spend-before-relabel.jsonl``. The budget code reads
    ``*/spend.jsonl`` only, so nothing is counted twice and the month's total does not move.

What it refuses
    Before it changes anything it checks every job: its folder and ``spend.jsonl`` exist, the
    kept file does not yet exist (a second run refuses), and every row's kind is ``inventory``.
    One job that fails leaves all three untouched. The rewritten rows are written to a side
    file, read back, and their total cost checked against the original's before either file is
    renamed.

Usage
    uv run python -m scripts.relabel_probe_spend [--runs-dir PATH] [--dry-run]
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.budget import RELABEL_FILE, SPEND_FILE, SpendRecord
from ntsb_probable_cause.scoring.records import read_jsonl, write_jsonl
from ntsb_probable_cause.settings import Settings

# The learning probe's three jobs (decision 0131's table): the smoke run, run 1 and run 2.
JOBS = (
    "s3-probe-20260929T122117-64b8cee",
    "s3-probe-20260929T123038-64b8cee",
    "s3-probe-20260929T130538-551c884",
)
_SIDE_FILE = f"{SPEND_FILE}.relabel-tmp"


def check(runs_dir: Path, job_id: str) -> tuple[SpendRecord, ...]:
    """The job's rows, if the job can be relabelled; changes nothing.

    Raises:
        ConfigurationError: a precondition fails. The message names the job.
    """
    folder = runs_dir / job_id
    spend_file = folder / SPEND_FILE
    if not spend_file.is_file():
        raise ConfigurationError(f"{job_id}: no {SPEND_FILE} under {runs_dir}")
    if (folder / RELABEL_FILE).exists():
        raise ConfigurationError(f"{job_id}: {RELABEL_FILE} exists, so it was relabelled already")
    rows = tuple(read_jsonl(spend_file, SpendRecord))
    other = sorted({row.kind for row in rows} - {"inventory"})
    if other:
        raise ConfigurationError(
            f"{job_id}: every row must have kind inventory; found {', '.join(other)}"
        )
    return rows


def relabel(runs_dir: Path, job_id: str) -> tuple[int, float]:
    """Keep the job's original rows and write them again with kind ``probe``.

    Returns:
        The number of rows and their total cost, which is the same before and after.

    Raises:
        ConfigurationError: a precondition fails, or the rewritten total differs from the
            original's. Nothing is renamed in either case.
    """
    rows = check(runs_dir, job_id)
    folder = runs_dir / job_id
    side = folder / _SIDE_FILE
    side.unlink(missing_ok=True)
    write_jsonl(side, [row.model_copy(update={"kind": "probe"}) for row in rows])
    written = read_jsonl(side, SpendRecord)
    before = sum(row.cost_usd for row in rows)
    after = sum(row.cost_usd for row in written)
    if len(written) != len(rows) or after != before:
        side.unlink()
        raise ConfigurationError(
            f"{job_id}: the rewritten rows' total (${after!r}, {len(written)} rows) differs from "
            f"the original's (${before!r}, {len(rows)} rows); nothing was changed"
        )
    (folder / SPEND_FILE).rename(folder / RELABEL_FILE)
    side.rename(folder / SPEND_FILE)
    return len(rows), after


def main(argv: Sequence[str] | None = None) -> int:
    """Check every job, then relabel each (or, with ``--dry-run``, only report)."""
    parser = argparse.ArgumentParser(prog="relabel_probe_spend")
    parser.add_argument("--runs-dir", type=Path, default=None, metavar="PATH")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    runs_dir: Path = args.runs_dir or Settings().runs_dir
    try:
        checked = {job_id: check(runs_dir, job_id) for job_id in JOBS}
        for job_id in JOBS:
            if args.dry_run:
                rows = checked[job_id]
                total = sum(row.cost_usd for row in rows)
                print(f"would relabel {job_id}: {len(rows)} rows, ${total:.4f}")
            else:
                count, total = relabel(runs_dir, job_id)
                print(f"relabelled {job_id}: {count} rows, ${total:.4f}")
    except ConfigurationError as error:
        print(f"relabel_probe_spend: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
