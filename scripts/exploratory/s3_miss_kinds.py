"""How the arm C loop misses the NTSB's defining event, counted over one case group.

Status
    Exploratory (decision 0059), S3.1 Task 15, free: for the design of a tuning round. It sets
    no bar and tunes nothing. It reads finished run folders and a ``groups.json`` written by
    ``scripts/s3_case_groups.py``, and makes no model call. ``make s3-miss-kinds`` writes its
    output to ``docs/results/s3-miss-kinds-dev.txt``, first on 2026-10-02 over the two arm C
    noise-floor runs' "always wrong" group. It ports an ad-hoc count run once the same day, and
    corrects it in two places: an abstained answer whose first code is right is its own kind,
    and "NTSB cause undetermined" needs a loop that did not abstain, as the pattern says.

Why
    Before a tuning round is registered, Andy reads where the loop went wrong. The trail pages
    (``scripts/s3_trail_pages.py``) show a few cases; this counts the same kinds and patterns
    over the whole group, so a pattern read on the page can be checked against its size.

What it counts
    Per run given, over the group's cases: each case's kind (exactly one) and its patterns
    (none, one or several, scored cases only), as ``scripts/miss_kinds.py`` classifies them;
    each split into fatal and non-fatal; and the NTSB's first events behind the "generic
    consequence" pattern, each event with its label. Counts only (decision 0024's rule): no
    case number and no text. Every figure has its denominator.

Refusals
    Each run through ``scripts/s3_case_groups.py``'s own checks (``load``): a held-out run id; a
    folder with no ``run.jsonl``, or whose record names another run; any sample but ``dev-400``
    (held-out, open and the sealed samples, a sealed one not yet opened refused as sealed
    first); a run that has not finished; a case outside the development split; a run that is not
    exactly ``dev-400``'s cases. Then: any arm but C; a run named twice. The groups file through
    ``scripts/s3_trail_pages.py``'s own checks (``read_group``): missing, not on ``dev-400``, not
    drawn over every run given, or without arm C groups. Then a group case a run does not hold,
    and a group case whose verdict holds no occurrence code. A named group needs ``--groups``;
    ``--group all`` counts every case of the runs and refuses one.

Usage
    uv run python -m scripts.exploratory.s3_miss_kinds --runs RUN [RUN ...] \
        (--groups PATH --group "always wrong"|"always right"|flipping | --group all) \
        [--out PATH]
"""

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Final, NoReturn

from scripts import s3_case_groups
from scripts.miss_kinds import (
    GENERIC_EVENTS,
    KIND_MEANINGS,
    KINDS,
    LOSS_OF_CONTROL,
    NOT_DETERMINED_FINDING,
    PATTERN_MEANINGS,
    PATTERNS,
    STALL_SPIN,
    UNKNOWN_OCCURRENCE,
    Difference,
    case_difference,
)
from scripts.s3_case_groups import Run
from scripts.s3_trail_pages import read_group

from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.settings import Settings

ARM: Final = "C"
SPLIT: Final = "arm C"
ALL: Final = "all"
GROUPS: Final = ("always wrong", "always right", "flipping")
GENERIC: Final = "generic consequence"
_UNKNOWN: Final = "not in the code tables"


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_miss_kinds: {message}")


# --- the lines ---


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.1%})" if whole else f"{part} of {whole}"


def _split_share(ids: Sequence[str], fatal: Mapping[str, bool], members: AbstractSet[str]) -> str:
    """How many of ``ids`` are members: all, then fatal, then non-fatal, each of its whole."""
    parts = [
        _share(sum(i in members for i in chosen), len(chosen))
        for chosen in (ids, [i for i in ids if fatal[i]], [i for i in ids if not fatal[i]])
    ]
    return f"{parts[0]}; fatal {parts[1]}; non-fatal {parts[2]}"


def _whole(ids: Sequence[str], fatal: Mapping[str, bool], what: str = "cases") -> str:
    deaths = sum(fatal[i] for i in ids)
    return f"{len(ids)} {what} ({deaths} fatal, {len(ids) - deaths} non-fatal)"


def run_lines(run: Run, ids: Sequence[str], tables: CodeTables) -> list[str]:
    """One run's counts over the group: the kinds, the patterns, the generic events.

    Args:
        run: one finished arm C run.
        ids: the group's case ids, every one in the run.
        tables: the code tables, for the events' labels.

    Returns:
        The run's lines.
    """
    cases = {c.case_id: c for c in run.cases}
    fatal = {i: cases[i].fatal for i in ids}
    differences: dict[str, Difference] = {i: case_difference(cases[i]) for i in ids}
    lines = [f"Kinds, of the {_whole(ids, fatal)}:"]
    for kind in KINDS:
        members = {i for i in ids if differences[i].kind == kind}
        lines.append(f"- {kind}: {_split_share(ids, fatal, members)}")
    scored = [i for i in ids if differences[i].kind != "failed or not scored"]
    lines.append(f"Patterns, of the {_whole(scored, fatal, 'scored cases')}:")
    for pattern in PATTERNS:
        members = {i for i in scored if pattern in differences[i].patterns}
        lines.append(f"- {pattern}: {_split_share(scored, fatal, members)}")
    generic = [i for i in scored if GENERIC in differences[i].patterns]
    events = Counter(cases[i].verdict_occurrence[0][3:] for i in generic)
    lines.append(f'The NTSB\'s first events behind "{GENERIC}", of its {len(generic)} cases:')
    for event, count in sorted(events.items(), key=lambda item: (-item[1], item[0])):
        deaths = sum(fatal[i] for i in generic if cases[i].verdict_occurrence[0][3:] == event)
        lines.append(
            f"- {event} {tables.events.get(event, _UNKNOWN)}: {count} "
            f"(fatal {deaths}, non-fatal {count - deaths})"
        )
    if not generic:
        lines.append("- none")
    return lines


def _labels(tables: CodeTables) -> str:
    """The codes the patterns name, each with its label."""
    events = sorted({STALL_SPIN, LOSS_OF_CONTROL, *GENERIC_EVENTS})
    named = [f"event {e} {tables.events.get(e, _UNKNOWN)}" for e in events]
    finding = tables.items.get(NOT_DETERMINED_FINDING[:8], _UNKNOWN).split(" — ")[0]
    occurrence = (
        f"{tables.phases.get(UNKNOWN_OCCURRENCE[:3], _UNKNOWN)} / "
        f"{tables.events.get(UNKNOWN_OCCURRENCE[3:], _UNKNOWN)}"
    )
    named += [
        f"finding {NOT_DETERMINED_FINDING} {finding}",
        f"occurrence {UNKNOWN_OCCURRENCE} {occurrence}",
    ]
    return "Codes named: " + "; ".join(named) + "."


def report(runs: Sequence[Run], ids: Sequence[str], *, cases_line: str, tables: CodeTables) -> str:
    """The whole report: what is counted and how, then each run's counts.

    Args:
        runs: the finished arm C runs, in the order given.
        ids: the group's case ids.
        cases_line: where the cases come from, for the head.
        tables: the code tables.

    Returns:
        The report's text.
    """
    head = [
        "S3.1 miss kinds on dev-400 (scripts/exploratory/s3_miss_kinds.py; S3.1 Task 15)",
        "Exploratory (decision 0059), for the design of a tuning round: it sets no bar and tunes "
        "nothing.",
        "Counts only: no case number and no text. Every figure is printed with its denominator.",
        "The defining event is the NTSB's first occurrence code. The loop's answer is the last "
        "checkpoint of a case not counted as failed (decision 0136 item 1), its codes in the "
        "loop's order. Classified by scripts/miss_kinds.py, as on the trail pages.",
        cases_line,
        *(f"run {n} = {run.run_id}" for n, run in enumerate(runs, 1)),
    ]
    rules = [
        "Kinds (exactly one per case):",
        *(f"- {kind}: {meaning}" for kind, meaning in KIND_MEANINGS.items()),
        "Patterns (none, one or several per scored case; a failed case has none):",
        *(f"- {pattern}: {meaning}" for pattern, meaning in PATTERN_MEANINGS.items()),
        _labels(tables),
    ]
    blocks = ["\n".join(head), "\n".join(rules)]
    blocks += [
        "\n".join([f"## run {n}: {run.run_id}", "", *run_lines(run, ids, tables)])
        for n, run in enumerate(runs, 1)
    ]
    return "\n\n".join(blocks)


# --- reading ---


def _load(run_id: str) -> Run:
    """One finished ``dev-400`` arm C run, through ``s3_case_groups``' own refusals."""
    run = s3_case_groups.load(run_id)
    if run.arm != ARM:
        _refuse(f"{run_id} is arm {run.arm}; miss kinds read arm C runs only")
    return run


def _source(path: Path) -> str:
    """The groups file as the report names it: under the runs folder, or by its name alone."""
    runs_dir = Settings().runs_dir.resolve()
    resolved = path.resolve()
    return (
        resolved.relative_to(runs_dir).as_posix()
        if resolved.is_relative_to(runs_dir)
        else path.name
    )


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_miss_kinds")
    parser.add_argument("--runs", nargs="+", required=True, metavar="RUN_ID")
    parser.add_argument("--groups", type=Path, default=None, help="s3_case_groups' groups.json")
    parser.add_argument("--group", required=True, choices=[*GROUPS, ALL])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.group == ALL and args.groups is not None:
        parser.error("--group all counts every case of the runs and reads no groups file")
    if args.group != ALL and args.groups is None:
        parser.error(f"--group {args.group} needs --groups, the groups.json s3_case_groups wrote")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the counts.

    Args:
        argv: the command line.

    Returns:
        0.
    """
    args = _arguments(argv)
    if len(set(args.runs)) != len(args.runs):
        _refuse("a run is named twice; count each run once")
    runs = [_load(run_id) for run_id in args.runs]
    if args.group == ALL:
        ids: Sequence[str] = sorted(c.case_id for c in runs[0].cases)
        source = "every case of the runs"
    else:
        listed = [
            read_group(args.groups, split=SPLIT, group=args.group, run_id=run.run_id)
            for run in runs
        ]
        ids = listed[0]
        source = f"{SPLIT}, {args.group}, from {_source(args.groups)}"
    for run in runs:
        held = {c.case_id: c for c in run.cases}
        absent = [i for i in ids if i not in held]
        if absent:
            _refuse(f"{run.run_id} does not hold {len(absent)} case(s) of the group")
        if any(not held[i].verdict_occurrence for i in ids):
            _refuse(
                f"{run.run_id}: a case of the group holds no NTSB occurrence code, so no "
                "defining event to compare"
            )
    fatal = {c.case_id: c.fatal for c in runs[0].cases}
    text = report(
        runs, ids, cases_line=f"Cases: {source}: {_whole(ids, fatal)}", tables=load_tables()
    )
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
