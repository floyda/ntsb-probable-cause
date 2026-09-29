"""The sealed sample's result beside dev-400's, and the prediction of decision 0098 item 7.

Status
    Once, at S2.7's end (spec §9), free: reads two run folders (or their derived check
    folders); counts only. Writes docs/results/s27-sealed-dev.txt.

Why
    The sealed sample is the one clean check that guidance written from dev-400 generalises
    (decision 0095). The prediction was written before Round 1 and is published whichever way
    it comes out. Finding recall@10 is printed beside top-1 because S2.7's kept finding round
    (Round 6, decision 0106) moved it.

Usage
    uv run python -m scripts.sealed_report --dev RUN --sealed RUN \
        --misread-moved {yes,no,unvalidated} [--out PATH]
"""

import argparse
import statistics
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.settings import Settings

PREDICTED_LOW, PREDICTED_HIGH = 0.30, 0.36
MAX_DROP_POINTS = 5.0


def prediction_lines(dev_top1: float, sealed_top1: float, misread_moved: bool | None) -> list[str]:
    """Each part of the prediction, scored plainly."""
    met = PREDICTED_LOW <= dev_top1 <= PREDICTED_HIGH
    drop = (dev_top1 - sealed_top1) * 100
    lines = [
        f"top-1 on dev-400 between 30% and 36%: {dev_top1:.1%} -- {'met' if met else 'not met'}",
        f"sealed below dev-400 by less than 5 points: {drop:.1f} points -- "
        f"{'met' if 0 < drop < MAX_DROP_POINTS else 'not met'}",
    ]
    if misread_moved is None:
        lines.append("misread share: not scored (the narrative label was not validated)")
    else:
        verdict = "not met" if misread_moved else "met"
        lines.append(f"misread share did not move beyond label churn: {verdict}")
    return lines


def _scored(run_id: str) -> list[CaseResult]:
    if "heldout" in run_id:
        raise SystemExit(f"sealed_report: {run_id} is a held-out run; development runs only")
    return [
        c
        for c in read_jsonl(Settings().runs_dir / run_id / "cases.jsonl", CaseResult)
        if c.scores is not None and c.steps
    ]


def _line(label: str, run_id: str, cases: Sequence[CaseResult]) -> tuple[str, float]:
    hits = sum(bool(c.scores and c.scores.occurrence_top1) for c in cases)
    n = len(cases)
    top1 = hits / n if n else 0.0
    low, high = wilson(hits, n)
    recalls = [
        c.scores.finding_recall_10
        for c in cases
        if c.scores is not None and c.scores.finding_recall_10 is not None
    ]
    recall = statistics.fmean(recalls) if recalls else 0.0
    return (
        f"{label} ({run_id}): top-1 {top1:.1%} [{low:.1%}, {high:.1%}], {hits} of {n}; "
        f"finding recall@10 {recall:.1%} over {len(recalls)} cases",
        top1,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print both results and the prediction."""
    parser = argparse.ArgumentParser(prog="sealed_report")
    parser.add_argument("--dev", required=True)
    parser.add_argument("--sealed", required=True)
    parser.add_argument("--misread-moved", choices=("yes", "no", "unvalidated"), required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    dev_line, dev = _line("dev-400", args.dev, _scored(args.dev))
    sealed_line, sealed = _line("dev-seal-400", args.sealed, _scored(args.sealed))
    moved = None if args.misread_moved == "unvalidated" else args.misread_moved == "yes"
    text = "\n".join(
        [
            "the sealed sample (scripts/sealed_report.py; counts only, decisions 0095, 0098)",
            dev_line,
            sealed_line,
            "",
            "the prediction (decision 0098 item 7):",
            *prediction_lines(dev, sealed, moved),
        ]
    )
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
