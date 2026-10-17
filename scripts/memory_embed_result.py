"""The embedding lookup's reading and its registered rule, on one sample (decision 0213).

Status
    Live reading, free: reads finished coding-test run folders (``scripts/memory_coding_test.py``)
    and makes no model call. Development only: every run must be on the sample read, the steering
    slice or ``dev-seal-400`` (refused until ``docs/rounds/memory-embed-lookup.md`` is committed),
    and none may be a live run (decision 0024). Counts only: no case number, no cause and no lesson
    text is printed. Output: ``docs/results/memory-embed-lookup-dev.txt`` on the steering slice,
    ``docs/results/memory-embed-confirm-devseal.txt`` on ``dev-seal-400``
    (``make mem-embed-result``).

What it reads
    The sample's tables(a), counts(a) and counts(b) runs, today's cause lookup (``--lookup 5
    --applies RUN``) and the embed lookup (``--lookup 5 --choices RUN``), all on
    ``pilot-2010-recount``. The runs must belong together: the cause-lookup reading's refusal
    (``memory_cause_lookup_result.refuse_unrelated``) for the first four, and the same checks for
    the embed lookup, which must name a choices run. Each case is scored as in the pilot's reading,
    failed cases as wrong (decision 0136).

What it prints
    Per run: the three measures with intervals, ``n`` and failed cases. Paired: the noise,
    counts(b) minus counts(a); embed lookup minus cause lookup, which the rule reads; and, as
    descriptions, each lookup minus counts(a). Lessons per case for both lookups, the embed
    lookup's choices run and model. Then the rule.

Usage
    uv run python -m scripts.memory_embed_result --tables-a RUN --counts-a RUN --counts-b RUN
        --cause-lookup RUN --embed-lookup RUN [--sample S] [--out PATH]
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
from scripts import memory_cause_lookup_result as cause_lookup
from scripts import memory_coding_test
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

PROG: Final = "memory_embed_result"
STEERING: Final = memory_coding_test.SAMPLE
SEAL: Final = memory_coding_test.SEAL_SAMPLE
OUTS: Final = {
    STEERING: Path("docs/results/memory-embed-lookup-dev.txt"),
    SEAL: Path("docs/results/memory-embed-confirm-devseal.txt"),
}
EMBED: Final = "embed-lookup"
# Each label's condition, repeat and snapshot: the cause-lookup test's, less its code lookup, and
# the embed lookup.
LABELS: Final[dict[str, tuple[str, str | None, str | None]]] = {
    **{k: v for k, v in cause_lookup.LABELS.items() if k != "code-lookup"},
    EMBED: ("embed-lookup", None, cause_lookup.SNAPSHOT),
}
RULE_PAIR: Final = "embed lookup - cause lookup, read by the rule"
NOISE_PAIR: Final = "counts(b) - counts(a), the noise"
CHOICE_METHODS: Final = memory_coding_test.CHOICE_METHODS


def embed_rule(looked: Diff3, noise: Diff3) -> tuple[bool, list[str]]:
    """Decision 0213, as registered in docs/rounds/memory-embed-lookup.md.

    ``looked`` is embed lookup minus today's cause lookup; ``noise`` is counts(b) minus counts(a);
    all on one sample. Pass only if the finding gain exceeds the noise on findings, and neither
    occurrence measure falls by more than its own noise: the rule of decisions 0204 and 0210 to
    0212, with today's cause lookup in place of counts(a).
    """
    return stop_rule(looked, noise)


def refuse_unrelated(runs: Mapping[str, RunRead], snapshot_dir: Path) -> None:
    """Refuse runs that do not belong to one embedding-lookup reading; labels only in messages.

    Raises:
        ConfigurationError: the first four runs fail the cause-lookup reading's refusal; or the
            embed lookup is not made from tables(a), names another repeat, snapshot or file hash,
            did not use the registered K and floor, differs from tables(a) in its settings, or
            names no choices run.
    """
    cause_lookup.refuse_unrelated({k: v for k, v in runs.items() if k != EMBED}, snapshot_dir)
    run = runs[EMBED]
    spec, base = run.spec, runs["tables-a"].spec
    if spec.get("repeat") is not None:
        raise ConfigurationError(f"{EMBED} is not the repeat its label names (None)")
    if spec.get("source_run") != runs["tables-a"].folder.name:
        raise ConfigurationError(f"{EMBED} was not made from the tables-a run")
    if spec.get("snapshot") != cause_lookup.SNAPSHOT:
        raise ConfigurationError(f"{EMBED} does not name the snapshot {cause_lookup.SNAPSHOT}")
    path = snapshots.snapshot_path(cause_lookup.SNAPSHOT, snapshot_dir)
    if not path.exists() or spec.get("snapshot_sha256") != snapshots.sha256_of(path):
        raise ConfigurationError(f"{EMBED}'s snapshot hash does not match its file")
    if (
        spec.get("lookup_k") != cause_lookup.K
        or spec.get("lookup_min_applies") != lookup.MIN_APPLIES
    ):
        raise ConfigurationError(
            f"{EMBED} did not use the registered K={cause_lookup.K} and floor {lookup.MIN_APPLIES}"
        )
    differing = [key for key in SAME_SETTINGS if spec.get(key) != base.get(key)]
    if differing:
        raise ConfigurationError(f"{EMBED} differs from tables-a in {', '.join(differing)}")
    if spec.get("lookup_by") not in CHOICE_METHODS or not spec.get("choices_run"):
        raise ConfigurationError(f"the {EMBED} run names no choices run")


def report(
    sample: str, runs: Mapping[str, RunRead], scored: Mapping[str, dict[str, CaseMeasures]]
) -> str:
    """The whole text of the reading."""
    out = [f"coding memory embedding lookup, {sample} (decision 0213); counts only", ""]
    for name, run in runs.items():
        out += [f"{name} ({run.folder.name})", *summary_lines(scored[name], run.failed), ""]
    out.append("paired differences (first minus second, cases in both)")
    pairs = [
        (NOISE_PAIR, "counts-b", "counts-a"),
        (RULE_PAIR, EMBED, "cause-lookup"),
        ("embed lookup - counts(a), a description", EMBED, "counts-a"),
        ("cause lookup - counts(a), a description", "cause-lookup", "counts-a"),
    ]
    diffs: dict[str, Diff3] = {}
    for label, first, second in pairs:
        diffs[label], text = paired(scored[first], scored[second])
        out += [label, text]
    embed = runs[EMBED].spec
    out += [
        "",
        f"cause lookup: {lookup_counts(runs['cause-lookup'].spec)}",
        f"embed lookup: {lookup_counts(embed)}",
        f"embed lookup's choices run: {embed.get('choices_run')} "
        f"({embed.get('embedding_model')}, {embed.get('lookup_by')})",
    ]
    ok, reasons = embed_rule(diffs[RULE_PAIR], diffs[NOISE_PAIR])
    out += ["", *[f"not passed: {reason}" for reason in reasons]]
    out.append(f"rule on {sample}: {'PASS' if ok else 'FAIL'}")
    return "\n".join(out)


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Read the runs and write the result. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    for flag in LABELS:
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--sample", default=STEERING, choices=tuple(OUTS))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        memory_coding_test.refuse_sample(args.sample)
        runs = {
            name: load_run(
                cause_lookup.folder(settings.runs_dir, getattr(args, name.replace("-", "_"))),
                LABELS[name][0],
                args.sample,
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
        text = report(args.sample, runs, scored)
        print(text)
        write_result(PROG, args.out or OUTS[args.sample], text)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
