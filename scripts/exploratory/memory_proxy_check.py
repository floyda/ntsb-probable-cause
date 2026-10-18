"""What decision 0213's lesson-coverage gate measured, and whether it predicts the coding benefit.

Status
    Exploratory (decision 0059), free and offline: no model call, no network. It sets no bar and
    decides nothing. It records, by script, what the independent review of 0213 found on
    2026-10-18 (decision 0214's context). ``make mem-proxy-check`` writes its output to
    ``docs/results/memory-proxy-check-dev.txt``. Steering slice only; counts only: no case
    number, cause or lesson text.

What it measures
    Over 0213's lookups on ``dev-steer-400`` (today's cause lookup, the three embedding models'
    five nearest, the picking call): lesson coverage as the gate read it (``coverage.coverage``),
    and each part apart (``coverage.part_coverage``: the first-code part, the finding part), with
    the finding part's case hit rate minus today's, paired; the lessons a case and the precision
    at each rank. Then, in today's cause-lookup coding run, finding recall@10 and top-1 against
    counts(a), and the noise, counts(b) against counts(a), in three groups of cases by today's
    lessons: none; some, none agreeing; at least one agreeing. Last, the picking run's spend rows.

Refusals
    The runs through their readers: ``memory_coding_test.read_applies``,
    ``memory_embed.read_vectors``, ``memory_coverage.read_picks``, and the cause-lookup reading's
    ``load_run`` and ``refuse_unrelated`` for the coding runs.

Usage
    uv run python -m scripts.exploratory.memory_proxy_check --applies RUN --embeds RUN RUN RUN
        --picks RUN --tables-a RUN --counts-a RUN --counts-b RUN --cause-lookup RUN [--out PATH]
"""

import argparse
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import coverage, curate, lookup, snapshots
from ntsb_probable_cause.memory.coverage import Coverage
from ntsb_probable_cause.memory.lessons import Lesson
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import budget, metrics, samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.settings import Settings
from scripts import memory_cause_lookup_result as cause_lookup
from scripts import memory_coding_test, memory_coverage, memory_embed
from scripts.memory_pilot_result import CaseMeasures, load_run, measures, paired

PROG: Final = "memory_proxy_check"
SAMPLE: Final = memory_coding_test.SAMPLE
SNAPSHOT: Final = memory_coverage.SNAPSHOT
DEFAULT_OUT: Final = Path("docs/results/memory-proxy-check-dev.txt")
CODING: Final = ("tables-a", "counts-a", "counts-b", "cause-lookup")
NONE_GROUP: Final = "no lesson"
WRONG_GROUP: Final = "lessons, none agreeing"
RIGHT_GROUP: Final = "at least one agreeing"

Chosen = Mapping[str, Sequence[Lesson]]


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}% ({part} of {whole})" if whole else "none handed out"


def part_lines(
    chosen: Chosen, cases: Mapping[str, LearningCase], today: Coverage | None
) -> list[str]:
    """The gate's coverage, each part's, and the finding part's case hit against ``today``'s."""
    whole = coverage.coverage(chosen, cases)
    first, finding = coverage.part_coverage(chosen, cases)
    lines = [
        f"  as the gate read it: hit rate {whole.hit_rate * 100:.1f}%, precision "
        f"{_pct(whole.agreeing, whole.handed_out)}",
        f"  first-code part: case hit {first.hit_rate * 100:.1f}%, precision "
        f"{_pct(first.agreeing, first.handed_out)}",
        f"  finding part: case hit {finding.hit_rate * 100:.1f}%, precision "
        f"{_pct(finding.agreeing, finding.handed_out)}",
    ]
    if today is not None:
        ids = sorted(today.hits.keys() & finding.hits.keys())
        mean, low, high = metrics.paired_difference(
            [finding.hits[i] for i in ids], [today.hits[i] for i in ids]
        )
        lines.append(
            f"  finding-part case hit minus today's: {mean * 100:+.1f} points "
            f"[{low * 100:+.1f}, {high * 100:+.1f}] n={len(ids)}"
        )
    return lines


def rank_lines(chosen: Chosen, cases: Mapping[str, LearningCase]) -> list[str]:
    """Lessons a case, as counts of cases, and the precision at each rank (as the gate read it)."""
    sizes = Counter(len(chosen.get(case_id, ())) for case_id in cases)
    ranks: list[str] = []
    for rank in range(lookup.K):
        agree = [
            curate.agrees(chosen[c][rank], case)
            for c, case in cases.items()
            if len(chosen.get(c, ())) > rank
        ]
        ranks.append(_pct(sum(agree), len(agree)) if agree else "-")
    return [
        "  cases by lessons handed (0 to 5): "
        + ", ".join(str(sizes.get(n, 0)) for n in range(lookup.K + 1)),
        "  precision at rank 1 to 5: " + "; ".join(ranks),
    ]


def groups(today: Chosen, cases: Mapping[str, LearningCase]) -> dict[str, frozenset[str]]:
    """Cases by today's lessons: none; some, none agreeing; at least one agreeing."""
    found: dict[str, set[str]] = {NONE_GROUP: set(), WRONG_GROUP: set(), RIGHT_GROUP: set()}
    for case_id, case in cases.items():
        lessons = today.get(case_id, ())
        if not lessons:
            found[NONE_GROUP].add(case_id)
        elif any(curate.agrees(lesson, case) for lesson in lessons):
            found[RIGHT_GROUP].add(case_id)
        else:
            found[WRONG_GROUP].add(case_id)
    return {name: frozenset(ids) for name, ids in found.items()}


def group_lines(
    by_group: Mapping[str, frozenset[str]], scored: Mapping[str, Mapping[str, CaseMeasures]]
) -> list[str]:
    """Cause lookup minus counts(a), and the noise, in each group (``paired``'s text)."""
    out: list[str] = []
    for name, ids in by_group.items():

        def only(run: str, ids: frozenset[str] = ids) -> dict[str, CaseMeasures]:
            return {k: v for k, v in scored[run].items() if k in ids}

        out.append(f"{name} ({len(ids)} cases)")
        for label, first in (("cause lookup", "cause-lookup"), ("noise, counts(b)", "counts-b")):
            if not ids:
                continue
            _diff, text = paired(only(first), only("counts-a"))
            out += [f" {label} - counts(a):", text]
    return out


def spend_of(folder: Path) -> tuple[float, int, str]:
    """A run folder's spend rows: their total, how many, and their kinds.

    Raises:
        ConfigurationError: no readable spend file in ``folder``.
    """
    try:
        rows = [
            budget.SpendRecord.model_validate_json(line)
            for line in (folder / budget.SPEND_FILE).read_text().splitlines()
            if line
        ]
    except (OSError, ValidationError) as error:
        raise ConfigurationError(
            f"{folder.name}: no readable spend rows ({type(error).__name__})"
        ) from None
    kinds = ", ".join(sorted({row.kind for row in rows}))
    return sum(row.cost_usd for row in rows), len(rows), kinds


def _coding_scores(
    args: argparse.Namespace, settings: Settings
) -> dict[str, dict[str, CaseMeasures]]:
    runs = {
        name: load_run(
            cause_lookup.folder(settings.runs_dir, getattr(args, name.replace("-", "_"))),
            cause_lookup.LABELS[name][0],
            SAMPLE,
        )
        for name in CODING
    }
    cause_lookup.refuse_unrelated(runs, snapshots.SNAPSHOT_DIR)
    processed = settings.data_dir / "processed"
    ids = sorted({row.case_id for run in runs.values() for row in run.rows})
    raws = samples.load_cases(processed, ids)
    verdicts = {case_id: split_record(raw)[2] for case_id, raw in zip(ids, raws, strict=True)}
    tables, seen = load_tables(), samples.seen_pairs(processed)
    return {name: measures(run.rows, verdicts, tables, seen) for name, run in runs.items()}


def reading(args: argparse.Namespace, settings: Settings) -> str:
    """The whole text.

    Raises:
        ConfigurationError: a run its reader refuses (see the module docstring).
    """
    memory = snapshots.load_checked(SNAPSHOT, snapshots.SNAPSHOT_DIR)
    sha = snapshots.sha256_of(snapshots.snapshot_path(SNAPSHOT, snapshots.SNAPSHOT_DIR))
    every = (*memory.lessons, *memory.pushed_out)
    applied = memory_coding_test.read_applies(settings.runs_dir / args.applies, SNAPSHOT, sha)
    embeds = {
        run.model: run
        for run in (
            memory_embed.read_vectors(settings.runs_dir / name, snapshot=SNAPSHOT, sha=sha, sample=SAMPLE)
            for name in args.embeds
        )
    }
    pick, picked = memory_coverage.read_picks(
        settings.runs_dir / args.picks,
        snapshot=SNAPSHOT,
        sha=sha,
        sample=SAMPLE,
        embeds={run.run_id: run for run in embeds.values()},
        lessons={lesson.lesson_id: lesson for lesson in every},
    )
    cases, left_out = memory_coverage.verdict_cases_for(settings.data_dir / "processed", SAMPLE)
    today: dict[str, tuple[Lesson, ...]] = {
        c: lookup.by_fit(every, applied.get(c, frozenset())) for c in cases
    }
    lookups: dict[str, Chosen] = {"today's cause lookup": today}
    for model, run in embeds.items():
        lookups[model] = {
            c: lookup.by_similarity(every, run.lessons, run.cases[c]) for c in cases if c in run.cases
        }
    lookups[f"{memory_embed.PICK_PREFIX}{pick.embed_model}"] = picked
    _first, today_finding = coverage.part_coverage(today, cases)

    out = [
        f"what decision 0213's lesson-coverage gate measured, {SAMPLE}, {SNAPSHOT}, K={lookup.K}, "
        f"floor {lookup.MIN_APPLIES}; exploratory (decision 0059), decides nothing; counts only",
        "",
        f"cases scored: {len(cases)}; left out (no occurrence code): {left_out}",
        "eligible lessons predicting a first code: "
        f"{sum(bool(x.predicts.first_occurrence) for x in every if _eligible(x))}; "
        "finding categories: "
        f"{sum(bool(x.predicts.finding_categories) for x in every if _eligible(x))}; "
        f"of {sum(_eligible(x) for x in every)}",
    ]
    for name, chosen in lookups.items():
        against = None if chosen is today else today_finding
        out += ["", name, *part_lines(chosen, cases, against), *rank_lines(chosen, cases)]
    out += [
        "",
        "does agreement predict the coding benefit? today's cause-lookup coding run, by its lessons",
        "(first minus second, cases in both; failed cases as wrong)",
        *group_lines(groups(today, cases), _coding_scores(args, settings)),
    ]
    cost, rows, kinds = spend_of(settings.runs_dir / args.picks)
    out += [
        "",
        f"the picking run's spend: ${cost:.4f} in {rows} row(s), kind {kinds}",
        f"lessons a case: today's {statistics.mean(len(v) for v in today.values()):.2f}",
    ]
    return "\n".join(out)


def _eligible(lesson: Lesson) -> bool:
    return lesson.support is not None and lesson.support.applies >= lookup.MIN_APPLIES


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Print, and with ``--out`` also write, the reading. 0, or 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--applies", required=True)
    parser.add_argument("--embeds", nargs="+", required=True)
    parser.add_argument("--picks", required=True)
    for name in CODING:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        text = reading(args, settings)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
