"""The cause lookup's confirmation on ``dev-400``: the reading and its registered rule (0212).

Status
    Live reading, free: reads finished coding-test run folders (``scripts/memory_coding_test.py``)
    and makes no model call. Development only: every run must be on ``dev-400`` and none may be a
    live run (decision 0024). Counts only: no case number, no cause and no lesson text is printed.
    Its output is ``docs/results/memory-confirm-dev400.txt`` (``make mem-confirm-result``).

What it reads
    ``dev-400``'s tables(a), counts(a) and counts(b) runs, and its cause lookup (``--lookup 5
    --applies RUN`` on ``pilot-2010-recount``). The runs must belong together: made from tables(a),
    the registered repeats, snapshot, file hash, K and support floor, the same settings; the cause
    lookup must name an apply run (``memory_cause_lookup_result.refuse_unrelated``). Each case is
    scored as in the pilot's reading, failed cases as wrong (decision 0136).

What it prints
    Per run: the three measures with intervals, ``n`` and failed cases. Paired: the noise,
    counts(b) minus counts(a), and cause lookup minus counts(a), which the rule reads. The cause
    lookup's lessons per case and the distinct lessons it used. Then the rule.

Usage
    uv run python -m scripts.memory_confirm_result --tables-a RUN --counts-a RUN --counts-b RUN
        --cause-lookup RUN [--out PATH]
"""

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import snapshots
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.settings import Settings
from scripts import memory_cause_lookup_result as cause_lookup
from scripts._s3_runs import write_result
from scripts.memory_coding_test import CONFIRM_SAMPLE
from scripts.memory_lookup_result import lookup_counts
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

PROG: Final = "memory_confirm_result"
DEFAULT_OUT: Final = Path("docs/results/memory-confirm-dev400.txt")
# Each label's condition, repeat and snapshot: the cause-lookup test's, less its code lookup, so
# its refusal of runs that do not belong together (``refuse_unrelated``) applies unchanged.
LABELS: Final = {k: v for k, v in cause_lookup.LABELS.items() if k != "code-lookup"}
RULE_PAIR: Final = "cause lookup - counts(a), read by the rule"
NOISE_PAIR: Final = "counts(b) - counts(a), the noise"


def confirm_rule(looked: Diff3, noise: Diff3) -> tuple[bool, list[str]]:
    """Decision 0212, as registered in docs/rounds/memory-confirm-dev400.md.

    ``looked`` is cause lookup minus counts(a) on dev-400; ``noise`` is counts(b) minus counts(a)
    on dev-400. Pass only if the finding gain exceeds the noise on findings, and neither
    occurrence measure falls by more than its own noise: the rule of decisions 0204, 0210 and
    0211, read on dev-400.
    """
    return stop_rule(looked, noise)


def report(runs: Mapping[str, RunRead], scored: Mapping[str, dict[str, CaseMeasures]]) -> str:
    """The whole text of the reading."""
    out = [f"coding memory confirmation, {CONFIRM_SAMPLE} (decision 0212); counts only", ""]
    for name, run in runs.items():
        out += [f"{name} ({run.folder.name})", *summary_lines(scored[name], run.failed), ""]
    out.append("paired differences (first minus second, cases in both)")
    pairs = [(NOISE_PAIR, "counts-b", "counts-a"), (RULE_PAIR, "cause-lookup", "counts-a")]
    diffs: dict[str, Diff3] = {}
    for label, first, second in pairs:
        diffs[label], text = paired(scored[first], scored[second])
        out += [label, text]
    out += [
        "",
        f"cause lookup: {lookup_counts(runs['cause-lookup'].spec)}",
        f"cause lookup's apply run: {runs['cause-lookup'].spec.get('apply_run')}",
    ]
    ok, reasons = confirm_rule(diffs[RULE_PAIR], diffs[NOISE_PAIR])
    out += ["", *[f"not passed: {reason}" for reason in reasons]]
    out.append(f"rule on {CONFIRM_SAMPLE}: {'PASS' if ok else 'FAIL'}")
    return "\n".join(out)


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Read the confirmation's runs and write the result. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    for flag in LABELS:
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        runs = {
            name: load_run(
                cause_lookup.folder(settings.runs_dir, getattr(args, name.replace("-", "_"))),
                LABELS[name][0],
                CONFIRM_SAMPLE,
            )
            for name in LABELS
        }
        refuse_unequal_cases(runs)
        cause_lookup.refuse_unrelated(runs, snapshots.SNAPSHOT_DIR)
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
