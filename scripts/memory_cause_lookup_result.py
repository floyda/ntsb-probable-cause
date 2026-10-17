"""The cause-lookup test's reading and its registered rule (decision 0211).

Status
    Live reading, free: reads finished coding-test run folders (``scripts/memory_coding_test.py``)
    and makes no model call. Development only: every run must be on ``dev-steer-400`` and none may
    be a live run (decision 0024). Counts only: no case number, no cause and no lesson text is
    printed. Its output is ``docs/results/memory-cause-lookup-dev.txt`` (``make
    mem-cause-lookup-result``).

What it reads
    The pilot's tables(a), counts(a) and counts(b) runs; the code lookup of decision 0210
    (``--lookup 5`` on ``pilot-2010-recount``), for comparison only; and the cause lookup
    (``--lookup 5 --applies RUN`` on the same snapshot). The runs must belong together, as in
    ``memory_lookup_result``: made from tables(a), the registered repeats, snapshot, file hash, K
    and support floor, the same settings; the cause lookup must name an apply run. Each case is
    scored as in the pilot's reading, failed cases as wrong (decision 0136).

What it prints
    Per run: the three measures with intervals, ``n`` and failed cases. Paired: the noise,
    counts(b) minus counts(a); cause lookup minus counts(a), which the rule reads; code lookup
    minus counts(a); and cause lookup minus code lookup. Each lookup's lessons per case and the
    distinct lessons it used. Then the rule.

Usage
    uv run python -m scripts.memory_cause_lookup_result --tables-a RUN --counts-a RUN
        --counts-b RUN --code-lookup RUN --cause-lookup RUN [--out PATH]
"""

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import lookup, snapshots
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.settings import Settings
from scripts._s3_runs import write_result
from scripts.memory_lookup_result import SAME_SETTINGS, lookup_counts
from scripts.memory_pilot_result import (
    CaseMeasures,
    Diff3,
    RunRead,
    load_run,
    measures,
    paired,
    refuse_unequal_cases,
    stop_rule,
    summary_lines,
)

PROG: Final = "memory_cause_lookup_result"
DEFAULT_OUT: Final = Path("docs/results/memory-cause-lookup-dev.txt")
SNAPSHOT: Final = "pilot-2010-recount"
K: Final = 5
# Each label's condition, repeat and snapshot (None where the run names none).
LABELS: Final[dict[str, tuple[str, str | None, str | None]]] = {
    "tables-a": ("tables", "a", None),
    "counts-a": ("counts", "a", None),
    "counts-b": ("counts", "b", None),
    "code-lookup": ("lookup", None, SNAPSHOT),
    "cause-lookup": ("cause-lookup", None, SNAPSHOT),
}
RULE_PAIR: Final = "cause lookup - counts(a), read by the rule"
NOISE_PAIR: Final = "counts(b) - counts(a), the noise"


def cause_lookup_rule(looked: Diff3, noise: Diff3) -> tuple[bool, list[str]]:
    """Decision 0211, as registered in docs/rounds/memory-cause-lookup.md.

    ``looked`` is cause lookup minus counts(a); ``noise`` is counts(b) minus counts(a). Pass only
    if the finding gain exceeds the noise on findings, and neither occurrence measure falls by
    more than its own noise: the rule of decisions 0204 and 0210, read on the cause-lookup run.
    """
    return stop_rule(looked, noise)


def refuse_unrelated(runs: Mapping[str, RunRead], snapshot_dir: Path) -> None:
    """Refuse runs that do not belong to one cause-lookup test; the message names labels only.

    Raises:
        ConfigurationError: a run's repeat or snapshot is not its label's, a run after tables(a)
            was not made from it, a snapshot hash does not match its file, a run's settings
            differ from tables(a)'s, a lookup did not use the registered K and support floor, or
            the cause lookup names no apply run.
    """
    tables_a = runs["tables-a"].folder.name
    base = runs["tables-a"].spec
    for name, run in runs.items():
        _condition, repeat, snapshot = LABELS[name]
        if run.spec.get("repeat") != repeat:
            raise ConfigurationError(f"{name} is not the repeat its label names ({repeat})")
        if name != "tables-a" and run.spec.get("source_run") != tables_a:
            raise ConfigurationError(f"{name} was not made from the tables-a run")
        if run.spec.get("snapshot") != snapshot:
            raise ConfigurationError(f"{name} does not name the snapshot {snapshot}")
        if snapshot is not None:
            path = snapshots.snapshot_path(snapshot, snapshot_dir)
            if not path.exists() or run.spec.get("snapshot_sha256") != snapshots.sha256_of(path):
                raise ConfigurationError(f"{name}'s snapshot hash does not match its file")
            if (
                run.spec.get("lookup_k") != K
                or run.spec.get("lookup_min_applies") != lookup.MIN_APPLIES
            ):
                raise ConfigurationError(
                    f"{name} did not use the registered K={K} and floor {lookup.MIN_APPLIES}"
                )
        differing = [key for key in SAME_SETTINGS if run.spec.get(key) != base.get(key)]
        if differing:
            raise ConfigurationError(f"{name} differs from tables-a in {', '.join(differing)}")
    cause = runs["cause-lookup"].spec
    if cause.get("lookup_by") != "cause" or not cause.get("apply_run"):
        raise ConfigurationError("the cause-lookup run names no apply run")


def report(runs: Mapping[str, RunRead], scored: Mapping[str, dict[str, CaseMeasures]]) -> str:
    """The whole text of the reading."""
    out = ["coding memory cause-lookup test, dev-steer-400 (decision 0211); counts only", ""]
    for name, run in runs.items():
        out += [f"{name} ({run.folder.name})", *summary_lines(scored[name], run.failed), ""]
    out.append("paired differences (first minus second, cases in both)")
    pairs = [
        (NOISE_PAIR, "counts-b", "counts-a"),
        (RULE_PAIR, "cause-lookup", "counts-a"),
        ("code lookup - counts(a), as decision 0210 read it", "code-lookup", "counts-a"),
        ("cause lookup - code lookup", "cause-lookup", "code-lookup"),
    ]
    diffs: dict[str, Diff3] = {}
    for label, first, second in pairs:
        diffs[label], text = paired(scored[first], scored[second])
        out += [label, text]
    out += [
        "",
        f"code lookup: {lookup_counts(runs['code-lookup'].spec)}",
        f"cause lookup: {lookup_counts(runs['cause-lookup'].spec)}",
        f"cause lookup's apply run: {runs['cause-lookup'].spec.get('apply_run')}",
    ]
    ok, reasons = cause_lookup_rule(diffs[RULE_PAIR], diffs[NOISE_PAIR])
    out += ["", *[f"not passed: {reason}" for reason in reasons]]
    out.append(f"rule on the cause-lookup run: {'PASS' if ok else 'FAIL'}")
    return "\n".join(out)


def folder(runs_dir: Path, name: str) -> Path:
    """A run folder given as a path, or by name under the runs directory."""
    path = Path(name)
    return path if path.is_dir() else runs_dir / name


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Read the cause-lookup test's runs and write the result. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    for flag in LABELS:
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        runs = {
            name: load_run(
                folder(settings.runs_dir, getattr(args, name.replace("-", "_"))), LABELS[name][0]
            )
            for name in LABELS
        }
        refuse_unequal_cases(runs)
        refuse_unrelated(runs, snapshots.SNAPSHOT_DIR)
        processed = settings.data_dir / "processed"
        ids = sorted({row.case_id for run in runs.values() for row in run.rows})
        try:
            raws = samples.load_cases(processed, ids)
        except ValueError:
            raise ConfigurationError(
                f"some of the {len(ids)} cases are not in {processed / 'cases.parquet'}"
            ) from None
        verdicts = {case_id: split_record(raw)[2] for case_id, raw in zip(ids, raws, strict=True)}
        tables, seen = load_tables(), samples.seen_pairs(processed)
        scored = {k: measures(run.rows, verdicts, tables, seen) for k, run in runs.items()}
        text = report(runs, scored)
        print(text)
        write_result(PROG, args.out, text)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
