"""The held-out ledger and the commit state every run records (decisions 0018, 0026)."""

import subprocess
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.records import RunRecord

_HEADER = (
    "# Held-out ledger\n\n"
    "Every run that touched a held-out sample (decision 0026).\n\n"
    "| date | sample | arm | exclusions | includes | model | commit | cost USD | results |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
)


def commit_state(repo: Path = Path()) -> tuple[str, bool]:
    """Short SHA and whether the tree has uncommitted changes."""
    sha = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "status", "--porcelain"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sha, bool(status.strip())


def refuse_if_heldout_and_dirty(sample: str, dirty: bool) -> None:
    """A held-out run from a dirty tree is refused."""
    if sample.startswith("heldout") and dirty:
        raise ConfigurationError(
            f"{sample}: refusing to run with uncommitted changes; commit first"
        )


def append_row(ledger: Path, run: RunRecord, results_file: str) -> None:
    """Append one row, writing the header on first use."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.write_text(_HEADER)
    with ledger.open("a") as handle:
        handle.write(
            f"| {run.started.date()} | {run.sample} | {run.arm} | "
            f"{','.join(run.exclusions) or '-'} | {','.join(run.includes) or '-'} | "
            f"{run.model} | {run.commit_sha}{'*' if run.dirty else ''} | "
            f"{run.cost_usd:.2f} | {results_file} |\n"
        )
