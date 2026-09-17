"""Experiment 1: does Jev's stated confidence gate to a usably better subset? No API calls.

Re-scores the saved run at
``data/runs/20260917T182646-adda233-dev-400-jev`` (docs/results/typesafe-jev-dev400.md), the
401-case unconditioned dev-400 run, at five candidate thresholds. Nothing here calls the
model: every row was already paid for and saved by ``scripts/exploratory/jev_dev400.py``, and
this module only reads ``replies.jsonl`` back and re-scores it with the same
``score_jev_case`` the original report used. The per-case verdict still comes from
``runner.case_payload`` (``split_record`` and the leakage guard, 0013/0016), so the only new
code here is the threshold table and its fixed reading.

Usage (from the worktree root; data lives in the main checkout):
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
        uv run python -m scripts.exploratory.jev_followups.confidence_gating \\
            report 20260917T182646-adda233-dev-400-jev [--out PATH]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ntsb_probable_cause.model.typesafe import parse_reply
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.report import Cell, fmt_n, proportion
from ntsb_probable_cause.scoring.runner import RunSpec, case_payload
from ntsb_probable_cause.settings import Settings
from scripts.exploratory.jev_dev400 import SAMPLE, JevCase, read_rows, score_jev_case

# Decision-relevant thresholds (vendor guidance: "act above 0.5, do not act below").
THRESHOLDS: tuple[float, ...] = (0.3, 0.4, 0.5, 0.6, 0.7)
# Fixed in advance (spec of this follow-up): double the overall composed top-1 (9.7%,
# docs/results/typesafe-jev-dev400.md §2), and at least a quarter of cases still answered.
GATING_MIN_TOP1 = 2 * 0.097
GATING_MIN_ANSWERED_SHARE = 0.25
USEFUL_READING = "confidence gating is useful"
NOT_USEFUL_READING = "confidence carries no usable gating signal on this task"


def load_cases(
    folder: Path,
    ids: Sequence[str],
    raws: Sequence[Mapping[str, object]],
    tables: CodeTables,
    seen: frozenset[str],
) -> list[JevCase]:
    """Every already-answered case of the saved run, scored exactly as the original report did."""
    rows = read_rows(folder / "replies.jsonl")
    ok = {row["case_id"]: row for row in rows if row["ok"]}
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases: list[JevCase] = []
    for case_id, raw in zip(ids, raws, strict=True):
        if case_id not in ok:
            continue
        _, _, verdict, _ = case_payload(raw, spec, tables)
        reply = parse_reply(cast("Mapping[str, object]", ok[case_id]["reply"]))
        fatal = raw.get("highestInjuryLevel") == "Fatal"
        cases.append(score_jev_case(case_id, fatal, reply, verdict, tables, seen))
    return cases


@dataclass(frozen=True)
class GateRow:
    """One threshold's row: the share answered, and both slices' accuracy."""

    t: float
    answered_share: Cell
    answered_top1: Cell
    answered_event: Cell
    below_top1: Cell
    below_event: Cell


def gating_table(cases: Sequence[JevCase], thresholds: Sequence[float] = THRESHOLDS) -> list[GateRow]:
    """One row per threshold: composed top-1 and event accuracy, above and below it."""
    rows: list[GateRow] = []
    for t in thresholds:
        answered = [c for c in cases if c.event_confidence >= t]
        below = [c for c in cases if c.event_confidence < t]
        rows.append(
            GateRow(
                t=t,
                answered_share=proportion([c.event_confidence >= t for c in cases]),
                answered_top1=proportion([c.scores.occurrence_top1 for c in answered]),
                answered_event=proportion([c.scores.event_match for c in answered]),
                below_top1=proportion([c.scores.occurrence_top1 for c in below]),
                below_event=proportion([c.scores.event_match for c in below]),
            )
        )
    return rows


def gating_reading(rows: Sequence[GateRow]) -> str:
    """Fixed reading: useful if some threshold clears both bars at once."""
    for row in rows:
        if (
            row.answered_top1.n > 0
            and row.answered_top1.value >= GATING_MIN_TOP1
            and row.answered_share.value >= GATING_MIN_ANSWERED_SHARE
        ):
            return USEFUL_READING
    return NOT_USEFUL_READING


def build_report(
    folder: Path,
    raws: Sequence[Mapping[str, object]],
    ids: Sequence[str],
    tables: CodeTables,
    seen: frozenset[str],
) -> str:
    """The one table and its fixed reading, from the saved run only."""
    cases = load_cases(folder, ids, raws, tables, seen)
    rows = gating_table(cases)
    out = [
        f"experiment 1: confidence gating (no API calls) -- source run {folder.name}",
        f"n={len(cases)} answered cases of {len(ids)} in the sample",
        f"reading bars: composed top-1 >= {GATING_MIN_TOP1:.1%} "
        f"(double the overall 9.7%), answered share >= {GATING_MIN_ANSWERED_SHARE:.0%}",
        "",
        "| t | share >= t | top-1 (>= t) | event (>= t) | top-1 (< t) | event (< t) |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        out.append(
            f"| {row.t:.1f} | {fmt_n(row.answered_share)} | {fmt_n(row.answered_top1)} "
            f"| {fmt_n(row.answered_event)} | {fmt_n(row.below_top1)} | {fmt_n(row.below_event)} |"
        )
    out.append(f"\nreading (fixed in advance): {gating_reading(rows)}")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str]) -> int:
    """``report`` is the only command: this experiment makes no model calls."""
    parser = argparse.ArgumentParser(prog="confidence_gating")
    sub = parser.add_subparsers(dest="command", required=True)
    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("folder")
    report_cmd.add_argument("--out")
    args = parser.parse_args(argv)

    settings = Settings()
    tables = load_tables()
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids(SAMPLE)
    raws = samples.load_cases(processed, ids)
    seen = samples.seen_pairs(processed)

    text = build_report(settings.runs_dir / args.folder, raws, ids, tables, seen)
    print(text, end="")
    if args.out:
        Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
