"""Every number decision 0106 and Round 6's note cite, from committed code (final review I2+M2).

Status
    Live for S2.7, free: reads finished, checked ``dev-400`` arm B run folders under
    ``NTSB_RUNS_DIR``; counts only. Writes ``docs/results/s27-round-comparisons-dev.txt``.

Why
    Decision 0106's argument for overriding the do-no-harm rule (S2.7's Round 6, a finding
    round) rests on a table of numbers the final whole-branch review found labelled "ad-hoc
    counts" in both ``docs/decisions/0106-round-6-kept-by-override.md`` and Round 6's own note
    (``docs/rounds/s27-round-6.md``) -- produced by no committed script (final review,
    Important 2). CLAUDE.md's promise is "measured rather than asserted", and an override of a
    pre-registered stop rule is the claim a reader will check first, so this script reproduces
    every one of those numbers from the checked run folders decision 0098's registrations
    already name: each run's own checked top-1 and finding recall@10, Round 6 paired against
    Round 3 (the reference), Round 4, Round 5 and the repeat, and decision 0105 item 4's
    supplement line for Round 6 against Round 3.

    Counts only: no case id or title is read from a run folder into this script's output.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.round_comparisons [--out PATH]
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.scoring.metrics import bootstrap_mean
from ntsb_probable_cause.scoring.records import CaseResult
from scripts import round_result as rr

# The checked (`-check-luna`) run ids the final-fix brief names verbatim.
B_V1 = "20260926T082427-d19aafa-dev-400-B-check-luna"
REPEAT = "20260927T111202-fbab38a-dev-400-B-check-luna"
ROUND2 = "20260928T110233-2402e72-dev-400-B-check-luna"
ROUND3 = "20260928T144353-031e97e-dev-400-B-check-luna"
ROUND4 = "20260928T165443-1c9ecdf-dev-400-B-check-luna"
ROUND5 = "20260928T210719-c590e44-dev-400-B-check-luna"
ROUND6 = "20260929T053953-674c92e-dev-400-B-check-luna"

# Every checked run's own score (decision 0106's table and Round 6's note both quote these).
RUNS: tuple[tuple[str, str], ...] = (
    ("B-v1", B_V1),
    ("the repeat", REPEAT),
    ("Round 2", ROUND2),
    ("Round 3", ROUND3),
    ("Round 4", ROUND4),
    ("Round 5", ROUND5),
    ("Round 6", ROUND6),
)
# Decision 0106's table: Round 6 paired against each of these (Round 3 is also the reference
# Round 6's own registered reading, in docs/rounds/s27-round-6.md, was read against).
PAIRED_AGAINST: tuple[tuple[str, str], ...] = (
    ("Round 3 (reference)", ROUND3),
    ("Round 4", ROUND4),
    ("Round 5", ROUND5),
    ("the repeat", REPEAT),
)


def _own_line(label: str, run_id: str, cases: Sequence[CaseResult]) -> str:
    top1 = list(rr._top1(cases).values())
    recall = list(rr._recall(cases).values())
    top1_mean, top1_low, top1_high = bootstrap_mean(top1)
    recall_mean, recall_low, recall_high = bootstrap_mean(recall)
    return (
        f"- {label} ({run_id}): top-1 {top1_mean:.1%} [{top1_low:.1%}, {top1_high:.1%}] "
        f"n={len(top1)}; finding recall@10 {recall_mean:.1%} [{recall_low:.1%}, "
        f"{recall_high:.1%}] n={len(recall)}"
    )


def _against_line(label: str, run: Sequence[CaseResult], other: Sequence[CaseResult]) -> str:
    top1 = rr.diff(rr._top1(run), rr._top1(other))
    recall = rr.diff(rr._recall(run), rr._recall(other))
    return f"- {label}: top-1 {rr._fmt(top1)}; finding recall@10 {rr._fmt(recall)}"


def build() -> str:
    """Every number this file exists to check, read fresh from the named run folders."""
    loaded = {run_id: rr._load(run_id) for _label, run_id in RUNS}
    round6 = loaded[ROUND6]
    lines = [
        "S2.7 round comparisons (scripts/round_comparisons.py; counts only, decisions "
        "0098, 0105, 0106)",
        "",
        "## Each run's own checked score",
        *(_own_line(label, run_id, loaded[run_id]) for label, run_id in RUNS),
        "",
        "## Round 6 paired against",
        *(_against_line(label, round6, loaded[run_id]) for label, run_id in PAIRED_AGAINST),
        "",
        "## Decision 0105 item 4 supplement (Round 6 against Round 3)",
        rr.supplement_line(round6, loaded[ROUND3]),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the comparisons; with ``--out``, also write them to a file."""
    parser = argparse.ArgumentParser(prog="round_comparisons")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    text = build()
    print(text)
    if args.out is not None:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
