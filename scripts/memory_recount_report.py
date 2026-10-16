"""What the corrected count changed: a snapshot against its recount (decision 0209).

Status
    Live reading, free, local: reads two committed snapshots and makes no call. Counts only: no
    lesson text. Its output is ``docs/results/memory-recount-dev.txt`` (``make
    mem-recount-report``). The numbers decisions 0209 and 0210 cite come from it.

What it reads
    The old snapshot (counted by the rule before decision 0209) and its recount (the same lesson
    texts, support counted by the corrected rule over the same apply answers). It refuses a pair
    whose lesson ids, texts or cases applied to differ, so the two differ only in the rule.

What it prints
    The lessons' sizes; for the lessons that apply to at least 10 learning cases, the median fit
    under each rule, the median first-code fit, and how many disagree more than they agree under
    each rule (the revision test, read on the final support); and, for each snapshot, the lessons
    the cap keeps and the finding categories they name, beside those all lessons name.

Usage
    uv run python -m scripts.memory_recount_report --old pilot-2010 --new pilot-2010-recount
        [--out PATH]
"""

import argparse
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import curate, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Support, estimated_tokens
from ntsb_probable_cause.scoring.codes import load_tables
from scripts._s3_runs import write_result

PROG: Final = "memory_recount_report"
DEFAULT_OUT: Final = Path("docs/results/memory-recount-dev.txt")
WELL_USED: Final = 10


def _all(memory: Memory) -> dict[str, Lesson]:
    return {lesson.lesson_id: lesson for lesson in (*memory.lessons, *memory.pushed_out)}


def _support(lesson: Lesson) -> Support:
    if lesson.support is None:
        raise ConfigurationError(f"{lesson.lesson_id} has no counted support")
    return lesson.support


def refuse_unpaired(old: Memory, new: Memory) -> None:
    """Refuse two snapshots that differ in anything but the agreement counts.

    Raises:
        ConfigurationError: different lesson ids, statements, scopes, predictions, or cases
            applied to; the message names counts only.
    """
    a, b = _all(old), _all(new)
    if a.keys() != b.keys():
        raise ConfigurationError(f"the snapshots hold different lessons ({len(a)} and {len(b)})")
    for lid, lesson in a.items():
        other = b[lid]
        same_text = (lesson.statement, lesson.scope, lesson.predicts) == (
            other.statement,
            other.scope,
            other.predicts,
        )
        if not same_text or _support(lesson).applies != _support(other).applies:
            raise ConfigurationError(f"{lid} differs in text or in the cases it applies to")


def _fit(agrees: int, applies: int) -> float:
    return agrees / applies


def _median_pct(values: Sequence[float]) -> str:
    return f"{statistics.median(values) * 100:.0f}%" if values else "n/a"


def _categories(lessons: Sequence[Lesson]) -> int:
    return len({c for lesson in lessons for c in lesson.predicts.finding_categories})


def report(old: Memory, new: Memory) -> str:
    """The whole text of the reading."""
    tables = load_tables()
    lessons = list(_all(old).values())
    sizes = [estimated_tokens(curate.render_lesson(lesson, tables)) for lesson in lessons]
    kept_sizes = [estimated_tokens(curate.render_lesson(lesson, tables)) for lesson in old.lessons]
    recounted = _all(new)
    well = [lesson for lesson in lessons if _support(lesson).applies >= WELL_USED]
    old_fit = [_fit(_support(x).agrees, _support(x).applies) for x in well]
    new_fit = [_fit(_support(recounted[x.lesson_id]).agrees, _support(x).applies) for x in well]
    first_fit = [
        _fit(first, _support(x).applies)
        for x in well
        if (first := _support(recounted[x.lesson_id]).first_agrees) is not None
    ]
    cats = [len(x.predicts.finding_categories) for x in well]
    out = [
        f"corrected count, {old.name} against {new.name} (decision 0209); counts only",
        "",
        f"lessons: {len(lessons)}; estimated tokens, all lessons: {sum(sizes)}",
        f"median estimated tokens of a lesson the cap kept in {old.name}: "
        f"{statistics.median(kept_sizes):.0f}",
        "",
        f"lessons that apply to at least {WELL_USED} learning cases: {len(well)}",
        f"  median fit, old rule (every listed category flagged): {_median_pct(old_fit)}",
        f"  median fit, corrected rule (one listed category enough): {_median_pct(new_fit)}",
        f"  median first-code fit, over the {len(first_fit)} that predict a first code: "
        f"{_median_pct(first_fit)}",
        f"  finding categories named: median {statistics.median(cats):.0f}, largest {max(cats)}",
        "  disagree more than agree on the final support (the revision test): "
        f"old rule {sum(curate.needs_revision(_support(x)) for x in well)}, corrected rule "
        f"{sum(curate.needs_revision(_support(recounted[x.lesson_id])) for x in well)}",
        "",
        "finding categories named",
        f"  all {len(lessons)} lessons: {_categories(lessons)}",
    ]
    for memory in (old, new):
        out.append(
            f"  the {len(memory.lessons)} lessons the cap keeps in {memory.name}: "
            f"{_categories(memory.lessons)}"
        )
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    """Read the two snapshots and write the result. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--old", required=True, help="the snapshot counted by the old rule")
    parser.add_argument("--new", required=True, help="its recount")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        old = snapshots.load_checked(args.old, snapshots.SNAPSHOT_DIR)
        new = snapshots.load_checked(args.new, snapshots.SNAPSHOT_DIR)
        refuse_unpaired(old, new)
        text = report(old, new)
        print(text)
        write_result(PROG, args.out, text)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
