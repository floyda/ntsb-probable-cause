"""The held-out ledger and the commit state every run records (decisions 0018, 0026)."""

from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.scoring.records import RunRecord

# Re-exported so every existing caller -- and every test that monkeypatches
# ``ntsb_probable_cause.scoring.ledger.commit_state`` -- keeps working unchanged (S2.5 Task 9;
# see ``gitinfo.py`` for why the implementation moved).
__all__ = ["append_row", "commit_state", "refuse_if_heldout_and_dirty", "results_ref"]

_INTRO = "# Held-out ledger\n\nEvery run that touched a held-out sample (decision 0026).\n"
_VERSIONED_TABLE = (
    "| date | sample | arm | evidence | exclusions | includes | model | commit | cost USD "
    "| results |\n|---|---|---|---|---|---|---|---|---|---|\n"
)
_VERSIONED_SECTION = (
    "\n## From S2.6: with the evidence version (decision 0076)\n\n"
    "Every row above this table read the docket at evidence version v1.\n\n" + _VERSIONED_TABLE
)


def refuse_if_heldout_and_dirty(sample: str, dirty: bool) -> None:
    """A held-out run from a dirty tree is refused."""
    if sample.startswith("heldout") and dirty:
        raise ConfigurationError(
            f"{sample}: refusing to run with uncommitted changes; commit first"
        )


def results_ref(results_file: str) -> str:
    """The ledger's reference to a results file: ``<run folder>/<file name>``.

    Never an absolute path. The ledger is committed, so an absolute path would write the
    machine that happened to run the evaluation into the repository -- the first rows here
    recorded ``/Users/<name>/...`` -- and would be wrong for every later reader, whose
    ``NTSB_RUNS_DIR`` is somewhere else. The run folder's name is the run id, which is
    unique, so the folder and file name together locate the file under whatever runs
    directory is in use. Normalising here rather than at the call sites means no caller
    can reintroduce an absolute path.
    """
    path = Path(results_file)
    return f"{path.parent.name}/{path.name}" if path.parent.name else path.name


def append_row(ledger: Path, run: RunRecord, results_file: str) -> None:
    """Append one row, writing the header on first use.

    Or the versioned table once, for an old ledger that has none yet (decision 0076).
    """
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.write_text(_INTRO + "\n" + _VERSIONED_TABLE)
    elif "| evidence |" not in ledger.read_text():
        with ledger.open("a") as handle:
            handle.write(_VERSIONED_SECTION)
    with ledger.open("a") as handle:
        handle.write(
            f"| {run.started.date()} | {run.sample} | {run.arm} | {run.evidence_version} | "
            f"{','.join(run.exclusions) or '-'} | {','.join(run.includes) or '-'} | "
            f"{run.model} | {run.commit_sha}{'*' if run.dirty else ''} | "
            f"{run.cost_usd:.2f} | {results_ref(results_file)} |\n"
        )
