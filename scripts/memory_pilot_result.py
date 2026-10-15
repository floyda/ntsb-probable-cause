"""The coding memory pilot's reading and its registered stop rule (decisions 0204, 0207 item 4).

Status
    Live reading for the pilot, free: reads finished coding-test run folders
    (``scripts/memory_coding_test.py``) and makes no model call. Development only: every run must
    be on ``dev-steer-400`` and none may be a live run (decision 0024). Counts only: no case
    number, no cause and no lesson text is printed. Its output is
    ``docs/results/memory-pilot-dev.txt`` (``make mem-pilot-result``).

What it reads
    Two tables runs (a, b), two counts runs (a, b) and the memory runs in period order, each a
    folder under ``NTSB_RUNS_DIR`` (or a path). Each case's answer is scored against the NTSB's
    verdict, built by ``split_record`` and scored with ``score_case`` as ``ntsb-eval`` does. A
    failed case counts as wrong (decision 0136): top-1 and top-3 false, finding recall@10 0.0
    when the verdict flags findings in the cause, else left out.

What it prints
    Per run: occurrence top-1 and top-3 as proportions (Wilson interval) and finding recall@10
    as a mean (bootstrap interval), each with its ``n``, and the failed cases. Paired, on the
    cases both runs have: tables(b) minus tables(a); counts(b) minus counts(a), which is the
    noise; and each memory run minus counts(a). Then the registered stop rule on the last memory
    run (``stop_rule``), the curve, each snapshot's lesson counts, the agreement file's last
    line, and the learner's refusals by category.

Usage
    uv run python -m scripts.memory_pilot_result --tables-a RUN --tables-b RUN --counts-a RUN
        --counts-b RUN --memory RUN [RUN ...] [--learn-runs RUN [RUN ...]] [--out PATH]
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import claude, snapshots
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import metrics, samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.settings import Settings
from scripts._live_fence import refuse_live
from scripts._s3_runs import write_result
from scripts.memory_coding_test import CASES_FILE, SAMPLE, SPEC_FILE, CodingCase

PROG: Final = "memory_pilot_result"
AGREEMENT_FILE: Final = Path("docs/results/memory-agreement-dev.txt")
DEFAULT_OUT: Final = Path("docs/results/memory-pilot-dev.txt")
MEASURES: Final = ("occurrence top-1", "occurrence top-3", "finding recall@10")


@dataclass(frozen=True)
class CaseMeasures:
    """One case's three measures; ``recall10`` is None when the verdict flags no findings."""

    top1: bool
    top3: bool
    recall10: float | None


@dataclass(frozen=True)
class Diff3:
    """Paired point estimates on the three measures, as fractions."""

    top1: float
    top3: float
    recall10: float


def stop_rule(memory: Diff3, noise: Diff3) -> tuple[bool, list[str]]:
    """Decision 0204 item 5, as registered in docs/rounds/memory-pilot.md.

    ``memory`` is memory minus counts(a); ``noise`` is counts(b) minus counts(a). Pass only if the
    finding gain exceeds the noise on findings, and neither occurrence measure falls by more than
    its own noise.
    """
    reasons: list[str] = []
    if not memory.recall10 > abs(noise.recall10):
        reasons.append(
            f"finding recall@10 {memory.recall10:+.3f} is not beyond the noise "
            f"{abs(noise.recall10):.3f}"
        )
    if memory.top1 < -abs(noise.top1):
        reasons.append(f"top-1 {memory.top1:+.3f} falls beyond the noise {abs(noise.top1):.3f}")
    if memory.top3 < -abs(noise.top3):
        reasons.append(f"top-3 {memory.top3:+.3f} falls beyond the noise {abs(noise.top3):.3f}")
    return not reasons, reasons


# Scoring. ----------------------------------------------------------------------------------


def measure_failed(*, flags_findings: bool) -> CaseMeasures:
    """A failed case is wrong (decision 0136); recall counts 0.0 only where findings are flagged."""
    return CaseMeasures(top1=False, top3=False, recall10=0.0 if flags_findings else None)


def measures(
    rows: Sequence[CodingCase],
    verdicts: Mapping[str, Verdict],
    tables: CodeTables,
    seen: frozenset[str],
) -> dict[str, CaseMeasures]:
    """Every case's measures: answered ones through ``score_case``, failed ones as wrong."""
    out: dict[str, CaseMeasures] = {}
    for row in rows:
        verdict = verdicts[row.case_id]
        if row.hypothesis is None:
            out[row.case_id] = measure_failed(flags_findings=bool(verdict.finding_codes_in_cause))
            continue
        score = metrics.score_case(row.hypothesis, verdict, tables, seen_pairs=seen)
        out[row.case_id] = CaseMeasures(
            score.occurrence_top1, score.occurrence_top3, score.finding_recall_10
        )
    return out


def _interval(low: float, high: float) -> str:
    return f"[{low * 100:.1f}%, {high * 100:.1f}%]"


def _proportion(values: Sequence[bool]) -> tuple[float, str, int]:
    n = len(values)
    low, high = metrics.wilson(sum(values), n)
    return (sum(values) / n if n else 0.0), _interval(low, high), n


def summary_lines(got: Mapping[str, CaseMeasures], failed: int) -> list[str]:
    """One run's three measures with their intervals and ``n``, and its failed cases."""
    top1 = _proportion([m.top1 for m in got.values()])
    top3 = _proportion([m.top3 for m in got.values()])
    recalls = [m.recall10 for m in got.values() if m.recall10 is not None]
    mean, low, high = metrics.bootstrap_mean(recalls)
    return [
        f"  occurrence top-1: {top1[0] * 100:.1f}% {top1[1]} n={top1[2]}",
        f"  occurrence top-3: {top3[0] * 100:.1f}% {top3[1]} n={top3[2]}",
        f"  finding recall@10: {mean * 100:.1f}% {_interval(low, high)} n={len(recalls)}",
        f"  failed cases: {failed}",
    ]


def paired(
    first: Mapping[str, CaseMeasures], second: Mapping[str, CaseMeasures]
) -> tuple[Diff3, str]:
    """``first`` minus ``second`` on the cases in both: the three differences and their text."""
    ids = sorted(first.keys() & second.keys())
    lines: list[str] = []
    estimates: list[float] = []
    for name, label in (("top1", MEASURES[0]), ("top3", MEASURES[1])):
        a = [getattr(first[i], name) for i in ids]
        b = [getattr(second[i], name) for i in ids]
        mean, low, high = metrics.paired_difference(a, b)
        estimates.append(mean)
        lines.append(
            f"  {label}: {mean * 100:+.1f} points {_points_interval(low, high)} n={len(ids)}"
        )
    both = [
        (r1 - r2)
        for i in ids
        if (r1 := first[i].recall10) is not None and (r2 := second[i].recall10) is not None
    ]
    mean, low, high = metrics.bootstrap_mean(both)
    estimates.append(mean)
    lines.append(
        f"  {MEASURES[2]}: {mean * 100:+.1f} points {_points_interval(low, high)} n={len(both)}"
    )
    return Diff3(*estimates), "\n".join(lines)


def _points_interval(low: float, high: float) -> str:
    return f"[{low * 100:+.1f}, {high * 100:+.1f}]"


# The learner's refusals. -------------------------------------------------------------------


def refusals_by_category(folders: Sequence[Path]) -> dict[str, int]:
    """Failed learner replies that were refusals, by ``stop_category`` (``none`` when absent).

    Reads each folder's ``calls.jsonl`` (decision 0207 item 4). Counts only.
    """
    counts: Counter[str] = Counter()
    for folder in folders:
        path = folder / claude.CALLS_FILE
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line:
                continue
            reply = claude.Reply.model_validate_json(line)
            if not reply.ok and reply.stop_reason == "refusal":
                counts[reply.stop_category or "none"] += 1
    return dict(sorted(counts.items()))


# Reading run folders. ----------------------------------------------------------------------


@dataclass(frozen=True)
class RunRead:
    """A finished coding-test run: its spec and its rows."""

    folder: Path
    spec: Mapping[str, object]
    rows: tuple[CodingCase, ...]

    @property
    def failed(self) -> int:
        """Cases with no answer."""
        return sum(row.hypothesis is None for row in self.rows)


def load_run(folder: Path) -> RunRead:
    """Read a run after the fence and the sample check.

    Raises:
        SystemExit: a live run (``refuse_live``).
        ConfigurationError: not a finished coding-test run, or a sample other than the steering
            slice.
    """
    refuse_live(PROG, folder)
    try:
        spec = json.loads((folder / SPEC_FILE).read_text())
        rows = tuple(
            CodingCase.model_validate_json(line)
            for line in (folder / CASES_FILE).read_text().splitlines()
            if line
        )
    except (OSError, ValueError) as error:
        raise ConfigurationError(
            f"{folder.name}: not a finished coding-test run ({type(error).__name__})"
        ) from None
    if not isinstance(spec, dict) or spec.get("sample") != SAMPLE:
        raise ConfigurationError(f"{folder.name} is not a {SAMPLE} run: the pilot reads that only")
    return RunRead(folder, spec, rows)


def _folder(runs_dir: Path, name: str) -> Path:
    path = Path(name)
    return path if path.is_dir() else runs_dir / name


def last_line(path: Path) -> str:
    """The agreement file's last non-empty line, or a note that there is none."""
    if not path.exists():
        return f"{path.name}: not found"
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    return lines[-1] if lines else f"{path.name}: empty"


# The report. -------------------------------------------------------------------------------


def snapshot_counts(spec: Mapping[str, object], directory: Path) -> str:
    """A memory run's snapshot: lessons kept and pushed out, from the checked snapshot."""
    name = spec.get("snapshot")
    if not isinstance(name, str):
        return "no snapshot named"
    memory = snapshots.load_checked(name, directory)
    return f"{name}: {len(memory.lessons)} lessons kept, {len(memory.pushed_out)} pushed out"


def report(  # noqa: PLR0913 -- the runs, their scores and the four things the text also names.
    runs: Mapping[str, RunRead],
    scored: Mapping[str, dict[str, CaseMeasures]],
    *,
    memory_ids: Sequence[str],
    learn_runs: Sequence[Path],
    snapshot_dir: Path,
    agreement: Path,
) -> str:
    """The whole text of the reading."""
    out: list[str] = ["coding memory pilot, dev-steer-400 (decision 0204); counts only", ""]
    for name, run in runs.items():
        out += [f"{name} ({run.folder.name})", *summary_lines(scored[name], run.failed), ""]
    out.append("paired differences (first minus second, cases in both)")
    pairs = [
        ("tables(b) - tables(a)", "tables-b", "tables-a"),
        ("counts(b) - counts(a), the noise", "counts-b", "counts-a"),
    ]
    pairs += [(f"{m} - counts(a)", m, "counts-a") for m in memory_ids]
    diffs: dict[str, Diff3] = {}
    for label, first, second in pairs:
        diff, text = paired(scored[first], scored[second])
        diffs[label] = diff
        out += [f"{label}", text]
    out.append("")
    noise = diffs["counts(b) - counts(a), the noise"]
    last = memory_ids[-1]
    ok, reasons = stop_rule(diffs[f"{last} - counts(a)"], noise)
    out.append(f"stop rule on the last memory run ({last}): {'PASS' if ok else 'FAIL'}")
    out += [f"  {reason}" for reason in reasons]
    out += ["", "curve (top-1, top-3, finding recall@10, per cent)"]
    for name in ("tables-a", "counts-a", *memory_ids):
        got = scored[name].values()
        recalls = [m.recall10 for m in got if m.recall10 is not None]
        out.append(
            f"  {name}: {_pct([m.top1 for m in got])}, {_pct([m.top3 for m in got])}, "
            f"{_pct(recalls)}"
        )
    out += ["", "snapshots"]
    out += [f"  {m}: {snapshot_counts(runs[m].spec, snapshot_dir)}" for m in memory_ids]
    out += ["", f"agreement file, last line: {last_line(agreement)}"]
    refusals = refusals_by_category(learn_runs)
    detail = ", ".join(f"{k} {v}" for k, v in refusals.items()) or "none"
    out.append(f"learner refusals by category: {detail}")
    return "\n".join(out)


def _pct(values: Sequence[bool] | Sequence[float]) -> str:
    return f"{sum(values) / len(values) * 100:.1f}" if values else "n/a"


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Read the pilot's runs and write the result.

    Returns:
        0 on success, 1 on a refusal.
    """
    parser = argparse.ArgumentParser(prog=PROG)
    for flag in ("tables-a", "tables-b", "counts-a", "counts-b"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--memory", nargs="+", required=True, help="memory runs in period order")
    parser.add_argument("--learn-runs", nargs="*", default=[])
    parser.add_argument("--agreement", type=Path, default=AGREEMENT_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        names = {
            "tables-a": args.tables_a,
            "tables-b": args.tables_b,
            "counts-a": args.counts_a,
            "counts-b": args.counts_b,
        }
        memory_ids = [f"memory-{i + 1}" for i in range(len(args.memory))]
        names.update(zip(memory_ids, args.memory, strict=True))
        runs = {k: load_run(_folder(settings.runs_dir, v)) for k, v in names.items()}
        processed = settings.data_dir / "processed"
        ids = sorted({row.case_id for run in runs.values() for row in run.rows})
        verdicts = {
            case_id: split_record(raw)[2]
            for case_id, raw in zip(ids, samples.load_cases(processed, ids), strict=True)
        }
        tables, seen = load_tables(), samples.seen_pairs(processed)
        scored = {k: measures(run.rows, verdicts, tables, seen) for k, run in runs.items()}
        text = report(
            runs,
            scored,
            memory_ids=memory_ids,
            learn_runs=[_folder(settings.runs_dir, n) for n in args.learn_runs],
            snapshot_dir=snapshots.SNAPSHOT_DIR,
            agreement=args.agreement,
        )
        print(text)
        write_result(PROG, args.out, text)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
