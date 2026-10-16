"""How far the lookup reaches on a tables run's answers, before any lookup run (decision 0210).

Status
    Live reading, free, local: reads a finished tables run's answers and a checked snapshot, and
    makes no call. It reads no verdict and no score: only the answers' codes, as the lookup does.
    Counts only. Its output is ``docs/results/memory-lookup-reach-dev.txt`` (``make
    mem-lookup-reach``).

What it prints
    The lessons the support floor lets the lookup choose; the cases with an answer; how many get
    K lessons, fewer, or none; the distinct lessons used; the mean estimated tokens of lessons a
    case, beside the capped note's; and, of the cases where some lesson the lookup may choose
    predicts the answer's first code, how many get none.

Usage
    uv run python -m scripts.memory_lookup_reach --source RUN --snapshot NAME [--out PATH]
"""

import argparse
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import lookup, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, estimated_tokens, render_lesson
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.settings import Settings
from scripts._s3_runs import write_result
from scripts.memory_pilot_result import load_run

PROG: Final = "memory_lookup_reach"
DEFAULT_OUT: Final = Path("docs/results/memory-lookup-reach-dev.txt")


def _tokens(lessons: Sequence[Lesson], tables: CodeTables) -> int:
    return sum(estimated_tokens(render_lesson(lesson, tables)) + 1 for lesson in lessons)


def report(answers: Sequence[Hypothesis], memory: Memory, tables: CodeTables, name: str) -> str:
    """The whole text of the reading."""
    pool = (*memory.lessons, *memory.pushed_out)
    eligible = [
        x for x in pool if x.support is not None and x.support.applies >= lookup.MIN_APPLIES
    ]
    sizes: list[int] = []
    tokens: list[int] = []
    used: set[str] = set()
    with_first = missed_first = 0
    for answer in answers:
        occurrence = answer.occurrence_codes(tables)
        got = lookup.lookup(pool, occurrence, {g.category6 for g in answer.findings})
        sizes.append(len(got))
        tokens.append(_tokens(got, tables))
        used |= {x.lesson_id for x in got}
        if any(occurrence[0] in x.predicts.first_occurrence for x in eligible):
            with_first += 1
            missed_first += not any(occurrence[0] in x.predicts.first_occurrence for x in got)
    k = lookup.K
    return "\n".join(
        [
            f"lookup reach on {name}'s answers, {memory.name}, K={k}, floor {lookup.MIN_APPLIES} "
            "(decision 0210); counts only",
            "",
            f"lessons in the snapshot: {len(pool)}; the lookup may choose: {len(eligible)}",
            f"cases with an answer: {len(answers)}",
            f"  with {k} lessons: {sum(n == k for n in sizes)}; with 1 to {k - 1}: "
            f"{sum(0 < n < k for n in sizes)}; with none: {sum(n == 0 for n in sizes)}",
            f"distinct lessons used: {len(used)}",
            f"mean estimated tokens of lessons a case: {statistics.mean(tokens):.0f}; "
            f"the capped note: {_tokens(memory.lessons, tables)}",
            f"cases where a lesson the lookup may choose predicts the answer's first code: "
            f"{with_first}; of them, given none: {missed_first}",
        ]
    )


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Read the answers and the snapshot, and write the result. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--source", required=True, help="the tables run")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        run = load_run(settings.runs_dir / args.source, "tables")
        memory = snapshots.load_checked(args.snapshot, snapshots.SNAPSHOT_DIR)
        answers = [row.hypothesis for row in run.rows if row.hypothesis is not None]
        text = report(answers, memory, load_tables(), "tables(a)")
        print(text)
        write_result(PROG, args.out, text)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
