"""The lookup test's reading and its registered rule (decision 0210).

Status
    Live reading, free: reads finished coding-test run folders (``scripts/memory_coding_test.py``)
    and makes no model call. Development only: every run must be on ``dev-steer-400`` and none may
    be a live run (decision 0024). Counts only: no case number, no cause and no lesson text is
    printed. Its output is ``docs/results/memory-lookup-dev.txt`` (``make mem-lookup-result``).

What it reads
    The pilot's tables(a), counts(a) and counts(b) runs; the refilled note (the memory condition on
    ``pilot-2010-recount``); the lookup run (``--lookup 5`` on the same snapshot); and, for
    comparison only, the pilot's memory run on ``pilot-2010``. The runs must belong together: every
    run after tables(a) was made from it, the counts runs are repeats a and b, the note and the
    lookup name the registered snapshot and its file's hash, and the lookup used the registered K
    and support floor. Each case is scored as in the pilot's reading (``memory_pilot_result``),
    failed cases as wrong (decision 0136).

What it prints
    Per run: the three measures with intervals, ``n`` and failed cases. Paired: the noise,
    counts(b) minus counts(a); lookup minus counts(a), which the rule reads; the refilled note
    minus counts(a); lookup minus the note; and the pilot's memory run minus counts(a). The
    lookup's lessons per case and the number of distinct lessons it used. Then the rule.

Usage
    uv run python -m scripts.memory_lookup_result --tables-a RUN --counts-a RUN --counts-b RUN
        --note RUN --lookup RUN --pilot-memory RUN [--out PATH]
"""

import argparse
import statistics
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

PROG: Final = "memory_lookup_result"
DEFAULT_OUT: Final = Path("docs/results/memory-lookup-dev.txt")
SNAPSHOT: Final = "pilot-2010-recount"
PILOT_SNAPSHOT: Final = "pilot-2010"
K: Final = 5
# The settings every run must share with tables(a), so the runs differ only in their condition.
SAME_SETTINGS: Final = (
    "model",
    "reasoning_effort",
    "max_output_tokens",
    "price_variant",
    "cap_usd",
    "guidance_sha256",
    "statistics",
)
# Each label's condition, repeat and snapshot (None where the run names none).
LABELS: Final[dict[str, tuple[str, str | None, str | None]]] = {
    "tables-a": ("tables", "a", None),
    "counts-a": ("counts", "a", None),
    "counts-b": ("counts", "b", None),
    "note": ("memory", None, SNAPSHOT),
    "lookup": ("lookup", None, SNAPSHOT),
    "pilot-memory": ("memory", None, PILOT_SNAPSHOT),
}


def lookup_rule(looked: Diff3, noise: Diff3) -> tuple[bool, list[str]]:
    """Decision 0210, as registered in docs/rounds/memory-lookup.md.

    ``looked`` is lookup minus counts(a); ``noise`` is counts(b) minus counts(a). Pass only if the
    finding gain exceeds the noise on findings, and neither occurrence measure falls by more than
    its own noise: the pilot's rule (decision 0204 item 5), read on the lookup run.
    """
    return stop_rule(looked, noise)


def refuse_unrelated(runs: Mapping[str, RunRead], snapshot_dir: Path) -> None:
    """Refuse runs that do not belong to one lookup test; the message names labels only.

    Raises:
        ConfigurationError: a run's repeat or snapshot is not its label's, a run after tables(a)
            was not made from it, a snapshot hash does not match its file, a run's model or
            settings differ from tables(a)'s, or the lookup did not use the registered K and
            support floor.
    """
    tables_a = runs["tables-a"].folder.name
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
    base = runs["tables-a"].spec
    for name, run in runs.items():
        differing = [key for key in SAME_SETTINGS if run.spec.get(key) != base.get(key)]
        if differing:
            raise ConfigurationError(f"{name} differs from tables-a in {', '.join(differing)}")
    spec = runs["lookup"].spec
    if spec.get("lookup_k") != K or spec.get("lookup_min_applies") != lookup.MIN_APPLIES:
        raise ConfigurationError(
            f"the lookup run did not use the registered K={K} and floor {lookup.MIN_APPLIES}"
        )


def lookup_counts(spec: Mapping[str, object]) -> str:
    """Lessons per case in the lookup run, and how many distinct lessons it used."""
    raw = spec.get("lookup_lessons")
    if not isinstance(raw, dict) or not raw:
        return "no lessons recorded"
    per_case = [len(ids) for ids in raw.values()]
    distinct = {lid for ids in raw.values() for lid in ids}
    return (
        f"{len(per_case)} cases sent; mean {statistics.mean(per_case):.2f} lessons a case; "
        f"{sum(n == 0 for n in per_case)} with none; {len(distinct)} distinct lessons used"
    )


def report(runs: Mapping[str, RunRead], scored: Mapping[str, dict[str, CaseMeasures]]) -> str:
    """The whole text of the reading."""
    out = ["coding memory lookup test, dev-steer-400 (decision 0210); counts only", ""]
    for name, run in runs.items():
        out += [f"{name} ({run.folder.name})", *summary_lines(scored[name], run.failed), ""]
    out.append("paired differences (first minus second, cases in both)")
    pairs = [
        ("counts(b) - counts(a), the noise", "counts-b", "counts-a"),
        ("lookup - counts(a), read by the rule", "lookup", "counts-a"),
        ("note - counts(a)", "note", "counts-a"),
        ("lookup - note", "lookup", "note"),
        ("pilot memory - counts(a), as the pilot read it", "pilot-memory", "counts-a"),
    ]
    diffs: dict[str, Diff3] = {}
    for label, first, second in pairs:
        diffs[label], text = paired(scored[first], scored[second])
        out += [label, text]
    out += ["", f"lookup: {lookup_counts(runs['lookup'].spec)}"]
    ok, reasons = lookup_rule(
        diffs["lookup - counts(a), read by the rule"], diffs["counts(b) - counts(a), the noise"]
    )
    out += ["", *[f"not passed: {reason}" for reason in reasons]]
    out.append(f"rule on the lookup run: {'PASS' if ok else 'FAIL'}")
    return "\n".join(out)


def _folder(runs_dir: Path, name: str) -> Path:
    path = Path(name)
    return path if path.is_dir() else runs_dir / name


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Read the lookup test's runs and write the result. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    for flag in LABELS:
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        runs = {
            name: load_run(
                _folder(settings.runs_dir, getattr(args, name.replace("-", "_"))), LABELS[name][0]
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
