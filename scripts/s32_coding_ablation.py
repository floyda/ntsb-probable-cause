"""The coding ablation on ``dev-400`` and prediction 6 (S3.2 Task 11, spec §11 and §12).

Status
    Live measurement for S3.2, free: reads finished ``dev-400`` arm C run folders and makes no
    model call. Counts only (decision 0024). Its output is
    ``docs/results/s32-coding-ablation-dev.txt`` (``make s32-coding-ablation-report RUN=<id>``).
    It is a development reading and decides nothing but prediction 6.
    ``scripts/s32_claims.py`` imports :func:`load_ablation` and :func:`prediction6`, so the
    held-out report scores prediction 6 with the same code.

What it reads
    The loop without its coding tools (``run --arm C --without coding`` on ``dev-400``), against
    each of the two noise-floor runs, which are the same loop with its coding tools. The two
    noise-floor run ids are constants of this script: any other pair is refused. The ablation
    must be a finished, whole ``dev-400`` arm C run whose ``spec.json`` says
    ``without: ["coding"]`` and the same ``agent_prompt_version`` as the noise runs (the same
    loop text).

What it prints
    The provenance of each run, the ablation line, and the format gate of the ablation run
    (``scripts/s3_noise_floor.py``). Then, against each noise run, for occurrence top-1, top-3
    and finding recall@10, overall and for fatal and non-fatal cases, the paired difference
    (ablation minus noise run) with its 95% bootstrap interval and the cases it rests on
    (``claims.paired``: a guard refusal removes a case, any other failure counts as wrong),
    and beside it the same difference on the cases both runs answered
    (``claims.both_answered``). Differences are in points. Last, prediction 6.

Prediction 6 (spec §12)
    "Without coding tools, the loop is worse on top-1 than each noise-floor run, each interval
    wholly below zero." Met when the top of both top-1 intervals is below zero, else not met.

Usage
    uv run python -m scripts.s32_coding_ablation RUN NOISE_A NOISE_B [--out PATH]
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, get_args

from ntsb_probable_cause.scoring import claims, report
from ntsb_probable_cause.scoring.claims import Metric, Paired
from ntsb_probable_cause.scoring.records import CaseResult
from scripts._s3_runs import Run, load_runs, refuse, refuse_unclean_results, write_result
from scripts.s3_noise_floor import format_gate, gate_lines

PROG: Final = "s32_coding_ablation"
NOISE_RUNS: Final = (
    "20261001T201506-fd6053f-dev-400-C",
    "20261001T201648-fd6053f-dev-400-C",
)
METRIC_NAMES: Final[dict[str, str]] = {
    "top1": "occurrence top-1",
    "top3": "occurrence top-3",
    "recall10": "finding recall@10",
}
# Everything but ``without`` (and the cap, which only guards cost, spec §5) must match.
SAME_AS_NOISE: Final = (
    "agent_prompt_version",
    "model",
    "reasoning_effort",
    "max_output_tokens",
    "guidance",
    "stats",
)
NONE_LEFT: Final = "no case is left to pair"


@dataclass(frozen=True)
class Prediction6:
    """Prediction 6 read from the two top-1 differences (ablation minus each noise run)."""

    met: bool
    top1: tuple[Paired, ...]


def points(d: Paired) -> str:
    """A paired difference in points with its interval and the cases it rests on."""
    return f"{d.mean * 100:+.1f} points [{d.low * 100:+.1f}, {d.high * 100:+.1f}], n={d.n}"


def _only(cases: Sequence[CaseResult], ids: set[str]) -> list[CaseResult]:
    return [c for c in cases if c.case_id in ids]


def pair_line(
    first: Sequence[CaseResult],
    second: Sequence[CaseResult],
    metric: Metric,
    label: str,
    names: str,
) -> str:
    """One line: ``first`` minus ``second`` and the both-answered reading, for one slice."""
    head = f"{METRIC_NAMES[metric]}, {label}: {names} = "
    try:
        paired = points(claims.paired(first, second, metric))
    except ValueError:
        return head.removesuffix(f"{names} = ") + NONE_LEFT
    try:
        beside = f"both answered {points(claims.both_answered(first, second, metric))}"
    except ValueError:
        beside = f"both answered: {NONE_LEFT}"
    return f"{head}{paired}; {beside}"


def slice_lines(first: Sequence[CaseResult], second: Sequence[CaseResult], names: str) -> list[str]:
    """Every metric, overall and for fatal and non-fatal cases (the first run's flag)."""
    everyone = {c.case_id for c in first}
    fatal = {c.case_id for c in first if c.fatal}
    slices = (("all", everyone), ("fatal", fatal), ("non-fatal", everyone - fatal))
    return [
        pair_line(_only(first, ids), _only(second, ids), metric, label, names)
        for metric in get_args(Metric)
        for label, ids in slices
    ]


def load_ablation(prog: str, ablation_id: str, noise_ids: Sequence[str]) -> tuple[Run, list[Run]]:
    """Refuse what must be refused, then read the ablation run and the two noise-floor runs.

    Args:
        prog: the calling script's name, put first in a refusal.
        ablation_id: a finished arm C ``dev-400`` run with ``without: ["coding"]``.
        noise_ids: the two noise-floor run ids (:data:`NOISE_RUNS`, in either order).

    Raises:
        SystemExit: the noise runs are not the noise-floor pair; any ``_s3_runs`` refusal
            applies; the ablation's ``spec.json`` does not say ``without: ["coding"]``, or names
            another loop text than the noise runs.
    """
    if sorted(noise_ids) != sorted(NOISE_RUNS):
        refuse(prog, "the noise runs must be the two noise-floor runs named in scripts/" + PROG)
    if ablation_id in noise_ids:
        refuse(prog, "the ablation run is also named as a noise run")
    (ablation,) = load_runs(prog, [ablation_id])
    noise = load_runs(prog, list(noise_ids))
    if ablation.spec.get("without") != ["coding"]:
        refuse(
            prog,
            f"{ablation_id}: spec.json says without={ablation.spec.get('without')!r}, "
            "not ['coding']: it is not the coding ablation",
        )
    for run in noise:
        for key in SAME_AS_NOISE:
            if run.spec.get(key) != ablation.spec.get(key):
                refuse(
                    prog,
                    f"{ablation_id} differs from {run.record.run_id} at {key!r}: the ablation "
                    "must be the same loop, model and settings as the noise runs",
                )
    return ablation, noise


def prediction6(
    ablation: Sequence[CaseResult], noise: Sequence[Sequence[CaseResult]]
) -> Prediction6:
    """Prediction 6: the top of each top-1 difference (ablation minus a noise run) is below 0.

    Raises:
        ValueError: a run does not cover the ablation's cases, or no case is left to pair.
    """
    diffs = tuple(claims.paired(ablation, run, "top1") for run in noise)
    return Prediction6(all(d.high < 0 for d in diffs), diffs)


def prediction6_line(result: Prediction6, name: str = "prediction 6") -> str:
    """The prediction's line: ``met`` or ``not met`` with the intervals it was read from."""
    figures = "; ".join(
        f"noise run {label}: {points(d)}" for label, d in zip("ab", result.top1, strict=False)
    )
    return (
        f"{name}: {'met' if result.met else 'not met'} -- the loop without its coding "
        f"tools is worse on top-1 than each noise-floor run, each interval wholly below zero "
        f"(ablation minus noise run; {figures})"
    )


def report_lines(ablation: Run, noise: Sequence[Run]) -> list[str]:
    """The whole report."""
    lines = [
        "S3.2 coding ablation on dev-400 (scripts/s32_coding_ablation.py; spec §11, §12)",
        "Counts only: no case number. Differences are ablation minus noise run, in points, with "
        "the 95% bootstrap interval and the cases they rest on. A guard refusal removes the "
        "case; every other failure counts as wrong (spec §7.3).",
        "",
        report.provenance(ablation.record).rstrip(),
        "ablation: without=coding "
        f"agent_prompt_version={ablation.spec.get('agent_prompt_version')} "
        f"cap_usd={ablation.record.cap_usd}",
        *(report.provenance(run.record).rstrip() for run in noise),
        *gate_lines("ablation", format_gate(ablation.cases, ablation.calls)),
    ]
    for label, run in zip("ab", noise, strict=False):
        lines += ["", f"against {run.record.run_id} (noise run {label}):"]
        lines += slice_lines(ablation.cases, run.cases, "ablation - noise")
    lines += ["", prediction6_line(prediction6(ablation.cases, [r.cases for r in noise]))]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the coding ablation and prediction 6."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("run", help="the finished dev-400 arm C run with --without coding")
    parser.add_argument("noise", nargs=2, metavar="NOISE", help="the two noise-floor run ids")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if args.out is not None:
        refuse_unclean_results(PROG, Path(args.out))
    ablation, noise = load_ablation(PROG, args.run, args.noise)
    try:
        text = "\n".join(report_lines(ablation, noise))
    except ValueError as error:
        refuse(PROG, str(error))
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
