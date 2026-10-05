"""The noise-floor pair under the claim's rule (S3.2 Task 9).

Status
    Live measurement for S3.2 (spec §7.3), free: reads two finished ``dev-400`` arm C run folders
    and makes no model call. Counts only (decision 0024). Its output is
    ``docs/results/s32-noise-dev.txt`` (``make s32-noise RUNS="<a> <b>"``). It decides nothing.
    It shows how wide two identical loop runs differ when read the way the held-out claim reads
    arms: the width a real difference has to clear.

Why
    S3.1 read the pair on the cases both runs scored (``scripts/s3_noise_floor.py``). The claim
    reads every case: a guard refusal removes a case from both runs, and every other failure
    counts as wrong (``scoring/claims.py``, spec §7.3). The same pair, read that way, gives the
    noise floor the claim's own rule has.

What it prints
    The cases in each run, the guard refusals removed from both, and the failures counted wrong
    in each run. Then, for occurrence top-1, top-3 and finding recall@10, and for all cases, the
    fatal cases and the non-fatal cases: the paired difference a minus b with its 95% bootstrap
    interval and the cases it rests on (``claims.paired``), and beside it the same difference on
    the cases both runs answered (``claims.both_answered``). Differences are in points.

Usage
    uv run python -m scripts.s32_noise RUN_A RUN_B [--out PATH]
"""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final, get_args

from ntsb_probable_cause.scoring import claims
from ntsb_probable_cause.scoring.claims import Metric, Paired
from ntsb_probable_cause.scoring.records import CaseResult
from scripts._s3_runs import load_runs, refuse, write_result

PROG: Final = "s32_noise"
_NAMES: Final[dict[str, str]] = {
    "top1": "occurrence top-1",
    "top3": "occurrence top-3",
    "recall10": "finding recall@10",
}
_NONE_LEFT: Final = "no case is left to pair"


def _points(d: Paired) -> str:
    return f"{d.mean * 100:+.1f} points [{d.low * 100:+.1f}, {d.high * 100:+.1f}], n={d.n}"


def _only(cases: Sequence[CaseResult], ids: set[str]) -> list[CaseResult]:
    return [c for c in cases if c.case_id in ids]


def reading(a: Sequence[CaseResult], b: Sequence[CaseResult], metric: Metric, label: str) -> str:
    """One line: the paired difference and the both-answered one, for one slice and metric."""
    try:
        paired = _points(claims.paired(a, b, metric))
    except ValueError:
        return f"{_NAMES[metric]}, {label}: {_NONE_LEFT}"
    try:
        beside = f"both answered {_points(claims.both_answered(a, b, metric))}"
    except ValueError:
        beside = f"both answered: {_NONE_LEFT}"
    return f"{_NAMES[metric]}, {label}: a - b = {paired}; {beside}"


def noise_lines(a: Sequence[CaseResult], b: Sequence[CaseResult]) -> list[str]:
    """The whole report for a pair of runs over the same cases."""
    refused = {c.case_id for c in (*a, *b) if claims.is_guard_refusal(c)}
    kept_a, kept_b = (_only(r, {c.case_id for c in r} - refused) for r in (a, b))
    wrong = [sum(claims.answered(c) is None for c in kept) for kept in (kept_a, kept_b)]
    lines = [
        f"cases: run a {len(a)}, run b {len(b)}",
        f"guard refusals removed from both runs: {len(refused)}",
        f"failures counted wrong: run a {wrong[0]}, run b {wrong[1]}",
        f"cases kept: {len(kept_a)}",
    ]
    fatal = {c.case_id for c in a if c.fatal}
    everyone = {c.case_id for c in a}
    slices = (("all", everyone), ("fatal", fatal), ("non-fatal", everyone - fatal))
    for metric in get_args(Metric):
        for label, ids in slices:
            lines.append(reading(_only(a, ids), _only(b, ids), metric, label))
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the noise-floor pair under the claim's rule."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("runs", nargs=2, metavar="RUN_ID", help="two finished dev-400 arm C runs")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    first, second = load_runs(PROG, args.runs)
    if {c.case_id for c in first.cases} != {c.case_id for c in second.cases}:
        refuse(PROG, "the two runs do not cover the same cases")
    text = "\n".join(
        [
            "S3.2 noise floor under the claim's rule (scripts/s32_noise.py; spec §7.3)",
            "Counts only: no case number. Differences are run a minus run b, in points, with the "
            "95% bootstrap interval and the cases they rest on.",
            f"run a = {first.record.run_id}",
            f"run b = {second.record.run_id}",
            *noise_lines(first.cases, second.cases),
        ]
    )
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
