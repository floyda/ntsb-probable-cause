"""Fit the confidence curve on the noise-floor runs and freeze it (S3.2 Task 9).

Status
    Live measurement for S3.2 (spec §8.2, decision 0126), free: reads two finished ``dev-400``
    arm C run folders and makes no model call. Counts only (decision 0024). Its output is
    ``docs/results/s32-calibration-dev.txt`` (``make s32-calibration RUNS="<a> <b>"``), and it
    writes ``src/ntsb_probable_cause/scoring/tables/calibration_s3.json``. It decides the two
    numbers of the curve that the held-out reading will load, and nothing else.

Why
    The model's stated confidence barely sorts right from wrong (spec §8.1). Code turns it into
    the confidence shown: a logistic curve with two numbers, fitted once, here, on development
    runs, and frozen before any held-out run. The file is committed with the results file that
    printed it.

What it fits
    The scored answers of both runs pooled (``claims.answered(case)`` is not None; a failed or
    refused case has no answer). ``stated`` is the confidence the model stated
    (``scores.confidence``). ``right`` is ``scores.occurrence_top1``, which is False for a case
    the model abstained on: top-1 counts an abstention as a miss, and so does the curve
    (Task 7). ``calibration.fit`` finds the intercept and slope.

Two refusals
    The curve file must not exist: the curve is frozen, and a second fit would move it. Pass
    ``--refit`` to replace it on purpose. A curve that does not rise is refused by
    ``calibration.check_rising`` before anything is written (spec §8.2: "always rising").

What it prints
    The two numbers and the number of answers; the fitted chance at stated 0.1, 0.3, 0.5, 0.7
    and 0.9; for the four bands of stated confidence S3.1 used, the answers, the share right
    and the curve's mean fitted value; and how many answers fall below ``ABSTAIN_BELOW`` once
    the curve is applied (spec §8.4).

Usage
    uv run python -m scripts.s32_calibration RUN_A RUN_B [--out PATH] [--curve PATH] [--refit]
"""

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Final

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.scoring import calibration, claims
from ntsb_probable_cause.scoring.calibration import ABSTAIN_BELOW, CURVE_FILE, Curve
from ntsb_probable_cause.scoring.metrics import CaseScores
from scripts._s3_runs import load_runs, refuse, write_result
from scripts.s3_noise_floor import BANDS

PROG: Final = "s32_calibration"
CURVE_PATH: Final = Path(calibration.__file__).parent / "tables" / CURVE_FILE
_STATED: Final = (0.1, 0.3, 0.5, 0.7, 0.9)


def report_lines(curve: Curve, answers: Sequence[CaseScores], runs: Sequence[str]) -> list[str]:
    """The results file: the numbers, the curve at five points, the bands, the abstain count."""
    lines = [
        "S3.2 confidence curve (scripts/s32_calibration.py; spec §8.2, decision 0126)",
        "Counts only: no case number. Fitted on the scored answers of both runs pooled; an "
        "abstained answer is counted wrong, as top-1 counts it.",
        *(f"run {label} = {run_id}" for label, run_id in zip("ab", runs, strict=False)),
        f"intercept {curve.intercept:.4f}, slope {curve.slope:.4f}",
        f"answers pooled: {len(answers)}",
        "fitted chance the first occurrence code is right, by stated confidence:",
        *(f"- stated {x}: {curve.p(x):.3f}" for x in _STATED),
        "by band of stated confidence: answers, share right, and the curve's mean fitted value:",
    ]
    for low, high, name in BANDS:
        band = [s for s in answers if low <= s.confidence < high]
        if not band:
            lines.append(f"- {name}: no answers")
            continue
        right = sum(s.occurrence_top1 for s in band)
        mean = sum(curve.p(s.confidence) for s in band) / len(band)
        lines.append(
            f"- {name}: {len(band)} answers, right {right} ({right / len(band):.1%}), "
            f"mean fitted {mean:.3f}"
        )
    below = sum(calibration.abstains(curve.p(s.confidence)) for s in answers)
    lines.append(
        f"answers whose fitted chance is below {ABSTAIN_BELOW} (the loop would abstain): "
        f"{below} of {len(answers)} ({below / len(answers):.1%})"
    )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Fit the curve, print the results, write the curve file and (with ``--out``) the results."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("runs", nargs=2, metavar="RUN_ID", help="the two noise-floor run ids")
    parser.add_argument("--out", default=None)
    parser.add_argument("--curve", default=str(CURVE_PATH), help="where the curve file goes")
    parser.add_argument("--refit", action="store_true", help="replace an existing curve file")
    args = parser.parse_args(argv)
    curve_path = Path(args.curve)
    if curve_path.exists() and not args.refit:
        refuse(PROG, f"{curve_path} exists: the curve is frozen; pass --refit to replace it")
    runs = load_runs(PROG, args.runs)
    answers = [s for run in runs for case in run.cases if (s := claims.answered(case)) is not None]
    try:
        curve = calibration.fit(
            [s.confidence for s in answers], [s.occurrence_top1 for s in answers]
        )
        calibration.check_rising(curve)
    except ValueError as error:
        refuse(PROG, f"no curve written: {error}")
    text = "\n".join(report_lines(curve, answers, args.runs))
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text, own_curve=True)
    stored = {
        "intercept": curve.intercept,
        "slope": curve.slope,
        "n": len(answers),
        "runs": list(args.runs),
        "commit": gitinfo.commit_state()[0],
        "fitted": date.today().isoformat(),
    }
    curve_path.parent.mkdir(parents=True, exist_ok=True)
    curve_path.write_text(json.dumps(stored, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
