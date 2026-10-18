"""The steering reading of decision 0214: four embed-lookup coding runs, one rule, one winner.

Status
    Live reading, free: reads finished coding-test run folders (``scripts/memory_coding_test.py``)
    and makes no model call. The steering slice only; refused until
    ``docs/rounds/memory-embed-coding.md`` is committed; never a live run (decision 0024). Counts
    only: no case number, no cause and no lesson text is printed. Output:
    ``docs/results/memory-embed-coding-dev.txt`` (``make mem-embed-coding-result``); its last line,
    ``winner: <candidate>`` or ``winner: none``, is what ``dev-seal-400`` confirms
    (``memory_embed.steering_winner``).

What it reads
    The steering tables(a), counts(a), counts(b) and today's cause-lookup runs, and one
    embed-lookup run (``tools --lookup 5 --choices RUN``) for each of decision 0214's four
    candidates over ``openai/text-embedding-3-large``: no more, no fewer, none twice. Each embed
    lookup must belong with the four as ``memory_embed_result.refuse_unrelated`` requires.

What it prints
    Per run: the three measures with intervals, ``n`` and failed cases. Paired: the noise; for
    each candidate, its embed lookup minus today's cause lookup, read by 0213's rule
    (``memory_embed_result.embed_rule``), with its lessons a case and choices run. Then
    ``selection_rule`` and the winner.

Usage
    uv run python -m scripts.memory_embed_coding_result --tables-a RUN --counts-a RUN
        --counts-b RUN --cause-lookup RUN --embed-lookups RUN RUN RUN RUN [--out PATH]
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
from scripts import memory_coding_test, memory_embed, memory_embed_choices
from scripts import memory_embed_result as embed_result
from scripts._s3_runs import write_result
from scripts.memory_lookup_result import lookup_counts
from scripts.memory_pilot_result import (
    CaseMeasures,
    Diff3,
    RunRead,
    load_run,
    measures,
    paired,
    refuse_unequal_cases,
    summary_lines,
)

PROG: Final = "memory_embed_coding_result"
SAMPLE: Final = memory_coding_test.SAMPLE
OUT: Final = memory_embed.STEERING_READING
BASE: Final = ("tables-a", "counts-a", "counts-b", "cause-lookup")
EMBED: Final = embed_result.EMBED
ORDER: Final = tuple(
    memory_embed.candidate_name(method, memory_embed_choices.MODEL)
    for method in memory_embed_choices.METHODS
)
NONE: Final = "none"


def selection_rule(results: Mapping[str, tuple[bool, Diff3]]) -> str | None:
    """Decision 0214, as registered in docs/rounds/memory-embed-coding.md.

    Each candidate is read by decision 0213's rule against today's cause lookup. Of those that
    pass, the one with the largest finding gain goes forward; an exact tie goes to the earlier in
    the order embedding, pick, fit, fill. None passing gives none.
    """
    passed = [
        (-looked.recall10, ORDER.index(name), name) for name, (ok, looked) in results.items() if ok
    ]
    return min(passed)[2] if passed else None


def _candidate(run: RunRead) -> str:
    return memory_embed.candidate_name(
        str(run.spec.get("lookup_by")), str(run.spec.get("embedding_model"))
    )


def refuse_other_candidates(embeds: Sequence[RunRead]) -> dict[str, RunRead]:
    """The embed-lookup runs by candidate, refused unless they are the four registered ones.

    Raises:
        ConfigurationError: a candidate named twice, or the set is not decision 0214's four.
    """
    by_name = {_candidate(run): run for run in embeds}
    if len(by_name) != len(embeds) or set(by_name) != set(ORDER):
        raise ConfigurationError(
            "the steering reading reads one embed-lookup run of each of decision 0214's four "
            f"candidates ({', '.join(ORDER)}); given: {', '.join(sorted(map(_candidate, embeds)))}"
        )
    return {name: by_name[name] for name in ORDER}


def report(
    base: Mapping[str, RunRead],
    embeds: Mapping[str, RunRead],
    scored: Mapping[str, dict[str, CaseMeasures]],
) -> str:
    """The whole text of the reading."""
    out = [f"coding memory embedding lookups, {SAMPLE} (decision 0214); counts only", ""]
    for name, run in base.items():
        out += [f"{name} ({run.folder.name})", *summary_lines(scored[name], run.failed), ""]
    for name, run in embeds.items():
        out += [f"{name} ({run.folder.name})", *summary_lines(scored[name], run.failed), ""]
    noise, text = paired(scored["counts-b"], scored["counts-a"])
    out += [
        "paired differences (first minus second, cases in both)",
        embed_result.NOISE_PAIR,
        text,
        "",
        f"cause lookup: {lookup_counts(base['cause-lookup'].spec)}",
    ]
    results: dict[str, tuple[bool, Diff3]] = {}
    for name, run in embeds.items():
        looked, text = paired(scored[name], scored["cause-lookup"])
        ok, reasons = embed_result.embed_rule(looked, noise)
        results[name] = (ok, looked)
        out += [
            "",
            f"{name} - cause lookup, read by 0213's rule",
            text,
            f"  lessons: {lookup_counts(run.spec)}; choices run: {run.spec.get('choices_run')}",
            *[f"  not passed: {reason}" for reason in reasons],
            f"  {name}: {'PASS' if ok else 'FAIL'}",
        ]
    winner = selection_rule(results)
    out += ["", f"winner: {winner or NONE}"]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Read the runs and write the reading. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    for flag in BASE:
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--embed-lookups", nargs="+", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        memory_embed_choices.refuse_without_registration()
        memory_coding_test.refuse_sample(SAMPLE)

        def read(name: str, label: str) -> RunRead:
            return load_run(
                cause_lookup.folder(settings.runs_dir, name),
                embed_result.LABELS[label][0],
                SAMPLE,
            )

        base = {label: read(getattr(args, label.replace("-", "_")), label) for label in BASE}
        embeds = refuse_other_candidates([read(name, EMBED) for name in args.embed_lookups])
        for run in embeds.values():
            group = {**base, EMBED: run}
            refuse_unequal_cases(group)
            embed_result.refuse_unrelated(group, snapshots.SNAPSHOT_DIR)
        everything = {**base, **embeds}
        processed = settings.data_dir / "processed"
        ids = sorted({row.case_id for run in everything.values() for row in run.rows})
        try:
            raws = samples.load_cases(processed, ids)
        except ValueError:
            raise ConfigurationError(
                f"some of the {len(ids)} cases are not in {processed / 'cases.parquet'}"
            ) from None
        verdicts = {case_id: split_record(raw)[2] for case_id, raw in zip(ids, raws, strict=True)}
        tables, seen = load_tables(), samples.seen_pairs(processed)
        scored = {k: measures(run.rows, verdicts, tables, seen) for k, run in everything.items()}
        text = report(base, embeds, scored)
        print(text)
        write_result(PROG, args.out or OUT, text)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
