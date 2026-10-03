"""How far the NTSB's own cause sentence settles its first occurrence code.

Status
    Exploratory (decision 0059), S3.1 Task 15, free and offline: no model call, no network. It
    decides nothing: not round 1, not the loop. Its definitions and its expectation were
    committed before it existed (commit 700afda, the S3.1 plan's entry "A coding-consistency
    probe, with its definitions committed first"). ``make s3-coding-consistency`` writes its
    output to ``docs/results/s3-coding-consistency-dev.txt``, first on 2026-10-02.

Why
    The precedent probe and its reading page showed that earlier NTSB cases with almost the same
    probable-cause sentence often carry different first occurrence codes. If identical sentences
    are coded differently by the NTSB itself, no coder reading only that sentence can score above
    that ceiling, and a tool that finds earlier cases by their cause sentences has less to offer
    than it first seemed. This measures the ceiling, descriptively. It does not say the NTSB was
    inconsistent: the same sentence can follow accidents whose sequences of events differ.

What it measures
    Cases: the S3 statistics pool as ``scripts/exploratory/s3_precedent_probe.py`` reads it
    (``read_pool_texts``: ``coding_stats``' ``pool_cases`` and ``check_pool`` before any text is
    read, ``STAGES["s3"]``, decisions 0094, 0129), each with a probable-cause text and at least
    one occurrence code.

    Twins: *exact* twins share the same tokens in the same order (``[a-z0-9]+`` on the lower-cased
    text, nothing removed), so case, punctuation and curly or straight apostrophes make no
    difference; *loose* twins share the same set of those tokens less the precedent probe's stop
    words, in any order. A group is two or more cases with the same non-empty key. Each is
    measured over all years and again with the groups formed inside 2009-2014 only and inside
    2015-2019 only (a group needs two members inside the era).

    For each grouping and era: the groups, the cases in them and their share of the era's pool
    cases; the size of the groups (2, 3-5, 6-10, 11 or more); *leave-one-out agreement*, the
    headline, where a case agrees when the commonest value among the other members of its group
    (ties: the smallest value as a string) is its own, over the six-digit first code, its event
    (last three digits) and its phase (first three), with the cases in groups as the
    denominator; and *pairwise agreement* over every pair within a group, with the pairs as the
    denominator. Each count has a 95% Wilson interval, which treats the cases (or pairs) as
    independent although those of one group are not, so it is narrower than the data warrant.

    For exact twins, all years: the ten pairs of first codes that most often disagree within a
    group, as codes and labels. Counts and code labels only in the committed output: no case
    number and no text from any record.

The private file
    The 25 largest exact-twin groups (all years), each with its first member's probable-cause
    text (the first by case id, whitespace collapsed, passed through the attach step's name
    replacements), its size and its first-code counts with labels, go to ``largest-groups.md``
    in a folder under ``NTSB_RUNS_DIR`` (``s3-coding-consistency/<UTC time>/``, or
    ``--groups-out-dir``), never committed. It holds no case number. A folder inside the
    repository outside its git-ignored ``data/`` is refused, before anything is read.

Refusals
    A groups folder inside the repository (outside ``data/``), first. The pool through
    ``check_pool``: a sample case or a non-development case raises ``LeakageError`` before any
    text is read. A processed record that is not the group's first member, or whose text is not
    the pool's, while the private file is built. A second file in the same second, or an existing
    ``largest-groups.md`` in an explicit folder, rather than writing over it.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.exploratory.s3_coding_consistency \
        [--out PATH] [--groups-out-dir DIR]

    Prints the report, then one line: the private file's folder, relative to the runs folder.
"""

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, NoReturn

from scripts.coding_stats import STAGES
from scripts.exploratory import s3_precedent_probe as pp
from scripts.exploratory.s3_precedent_probe import PoolText, share, with_interval
from scripts.s3_trail_pages import (
    check_record,
    clean,
    new_folder,
    occurrence_label,
    refuse_inside_repository,
)

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.settings import Settings

type Grouping = Literal["exact", "loose"]
type Level = Literal["code", "event", "phase"]
type Key = tuple[str, ...] | frozenset[str]

FOLDER: Final = "s3-coding-consistency"
GROUPS_FILE: Final = "largest-groups.md"
GROUPINGS: Final[tuple[Grouping, ...]] = ("exact", "loose")
LEVELS: Final[tuple[Level, ...]] = ("code", "event", "phase")
LEVEL_TEXT: Final[Mapping[Level, str]] = {
    "code": "six-digit first code",
    "event": "event (last three digits)",
    "phase": "phase (first three digits)",
}
GROUPING_TITLE: Final[Mapping[Grouping, str]] = {"exact": "exact twins", "loose": "loose twins"}
LARGEST: Final = 25
TOP_PAIRS: Final = 10
# (name, smallest, largest) of each size bucket of a group; None is no upper end.
BUCKETS: Final[tuple[tuple[str, int, int | None], ...]] = (
    ("2", 2, 2),
    ("3-5", 3, 5),
    ("6-10", 6, 10),
    ("11+", 11, None),
)

# The committed expectation (plan entry "A coding-consistency probe", commit 700afda).
BELOW_PERCENT: Final = 80
EXPECTATION: Final = (
    "Expectation (decides nothing). Leave-one-out agreement on the six-digit first code among "
    "exact twins, all years: below 80%, that is, at least one in five identical cause sentences "
    "coded differently from the majority of its twins."
)


@dataclass(frozen=True)
class Era:
    """A span of event years the groups are formed within; no bounds is every year."""

    name: str
    first: int | None
    last: int | None

    def holds(self, year: int) -> bool:
        """Whether a case with this event year is in the era."""
        return (self.first is None or year >= self.first) and (self.last is None or year <= self.last)


ALL_YEARS: Final = Era("all years", None, None)
ERAS: Final[tuple[Era, ...]] = (ALL_YEARS, Era("2009–2014", 2009, 2014), Era("2015–2019", 2015, 2019))


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_coding_consistency: {message}")


# --- the groups ---


def twin_key(text: str, grouping: Grouping) -> Key:
    """The key twins share: the tokens in order (exact), or the set less stop words (loose).

    Args:
        text: a probable-cause text.
        grouping: ``exact`` or ``loose``.

    Returns:
        The key; empty when the text holds no token the grouping keeps.
    """
    if grouping == "exact":
        return pp.words(text)
    return frozenset(pp.tokens(text))


type Group = tuple[PoolText, ...]


def form_groups(cases: Sequence[PoolText], grouping: Grouping) -> tuple[Group, ...]:
    """Every group of two or more cases with the same non-empty key, members by case id.

    Args:
        cases: the cases to group, in any order.
        grouping: ``exact`` or ``loose``.

    Returns:
        The groups, ordered by their first member's case id.
    """
    by_key: dict[Key, list[PoolText]] = {}
    for case in cases:
        key = twin_key(case.text, grouping)
        if key:
            by_key.setdefault(key, []).append(case)
    groups = [tuple(sorted(members, key=lambda c: c.case_id)) for members in by_key.values()]
    twins = (g for g in groups if len(g) >= 2)
    return tuple(sorted(twins, key=lambda g: g[0].case_id))


def value(first: str, level: Level) -> str:
    """A first occurrence code at one level: the code, its event, or its phase."""
    if level == "code":
        return first
    return first[3:] if level == "event" else first[:3]


# --- the measures ---


def commonest(counts: Mapping[str, int]) -> str | None:
    """The value with the highest count, ties to the smallest value as a string; None if none."""
    return min(counts, key=lambda v: (-counts[v], v)) if counts else None


def leave_one_out(values: Sequence[str]) -> int:
    """How many cases of one group agree with the commonest value among the others.

    Args:
        values: each member's value.

    Returns:
        The number of members whose value is the commonest among the other members' (ties to
        the smallest value as a string).
    """
    counts = Counter(values)
    agreeing = 0
    for own, n in counts.items():
        others = dict(counts)  # the other members: this value's count less the case itself
        others[own] -= 1
        if commonest({v: c for v, c in others.items() if c > 0}) == own:
            agreeing += n
    return agreeing


def pairwise(values: Sequence[str]) -> tuple[int, int]:
    """Agreeing pairs and all pairs, over every unordered pair of one group's members."""
    counts = Counter(values)
    return sum(c * (c - 1) // 2 for c in counts.values()), len(values) * (len(values) - 1) // 2


def bucket(size: int) -> str:
    """The size bucket's name for a group of ``size`` (two or more)."""
    return next(
        name for name, low, high in BUCKETS if size >= low and (high is None or size <= high)
    )


@dataclass(frozen=True)
class Tally:
    """One grouping in one era: its groups, their cases, and every agreement count."""

    groups: int
    cases: int
    pool: int  # the era's pool cases
    sizes: Mapping[str, tuple[int, int]]  # bucket to (groups, cases)
    loo: Mapping[Level, int]  # cases agreeing with the commonest among the others
    agreeing_pairs: Mapping[Level, int]
    pairs: int


def tally(groups: Sequence[Group], pool: int) -> Tally:
    """Every count for ``groups`` formed among ``pool`` cases.

    Args:
        groups: the groups formed in the era.
        pool: how many pool cases the era holds.

    Returns:
        The tally.
    """
    sizes = {name: (0, 0) for name, _low, _high in BUCKETS}
    loo = dict.fromkeys(LEVELS, 0)
    agreeing = dict.fromkeys(LEVELS, 0)
    pairs = 0
    for group in groups:
        n_groups, n_cases = sizes[bucket(len(group))]
        sizes[bucket(len(group))] = (n_groups + 1, n_cases + len(group))
        pairs += len(group) * (len(group) - 1) // 2
        for level in LEVELS:
            values = [value(c.sequence[0], level) for c in group]
            loo[level] += leave_one_out(values)
            agreeing[level] += pairwise(values)[0]
    return Tally(
        len(groups), sum(len(g) for g in groups), pool, sizes, loo, agreeing, pairs
    )


@dataclass(frozen=True)
class Found:
    """One grouping in one era: its groups and its tally."""

    groups: tuple[Group, ...]
    tally: Tally


def analyse(cases: Sequence[PoolText]) -> dict[tuple[Grouping, str], Found]:
    """Form the groups of each grouping within each era, and tally them.

    Args:
        cases: the pool cases that have a text and a first code.

    Returns:
        Each (grouping, era name) to its groups and tally; groups are formed within the era.
    """
    found: dict[tuple[Grouping, str], Found] = {}
    for era in ERAS:
        inside = [c for c in cases if era.holds(c.event_date.year)]
        for grouping in GROUPINGS:
            groups = form_groups(inside, grouping)
            found[(grouping, era.name)] = Found(groups, tally(groups, len(inside)))
    return found


def disagreeing_pairs(groups: Sequence[Group]) -> list[tuple[str, str, int]]:
    """First-code pairs by how many pairs of twins within a group carry them, most first.

    Args:
        groups: the groups.

    Returns:
        ``(code a, code b, pairs)`` with ``a < b`` as strings, the most pairs first, ties by
        ``a`` then ``b``.
    """
    totals: dict[tuple[str, str], int] = {}
    for group in groups:
        counts = Counter(c.sequence[0] for c in group)
        for a in counts:
            for b in counts:
                if a < b:
                    totals[(a, b)] = totals.get((a, b), 0) + counts[a] * counts[b]
    return sorted(
        ((a, b, n) for (a, b), n in totals.items()), key=lambda item: (-item[2], item[0], item[1])
    )


def meets_expectation(agreeing: int, cases: int) -> bool:
    """Whether the headline is below 80%, as integers (no rounding at the edge)."""
    return agreeing * 100 < BELOW_PERCENT * cases


# --- the lines ---


def expectation_lines(found: Tally) -> list[str]:
    """The expectation verbatim, the headline number and whether the expectation is met.

    Args:
        found: exact twins, all years.

    Returns:
        The lines. With no exact twins there is no headline, and the expectation is not tested.
    """
    lines = ["## The expectation (committed in 700afda, before this script existed)", "", EXPECTATION]
    agreeing, cases = found.loo["code"], found.cases
    lines.append(
        "Headline: exact twins, all years, leave-one-out agreement on the six-digit first code: "
        + with_interval(agreeing, cases)
    )
    if not cases:
        lines.append("expectation not tested: no exact twins")
    else:
        lines.append(
            "expectation met" if meets_expectation(agreeing, cases) else "expectation not met"
        )
    return lines


def _agreement(counts: Mapping[Level, int], whole: int) -> list[str]:
    return [f"- {LEVEL_TEXT[level]}: {with_interval(counts[level], whole)}" for level in LEVELS]


def block_lines(grouping: Grouping, era: Era, found: Tally) -> list[str]:
    """One grouping in one era: the groups, their sizes, both agreements.

    Args:
        grouping: ``exact`` or ``loose``.
        era: the era the groups were formed within.
        found: its tally.

    Returns:
        The lines.
    """
    span = "" if era.first is None else f" (groups formed among cases with event years {era.first} to {era.last} only)"
    sizes = "; ".join(
        f"{name}: {n_groups} ({n_cases} cases)" for name, (n_groups, n_cases) in found.sizes.items()
    )
    return [
        f"### {GROUPING_TITLE[grouping]}, {era.name}{span}",
        f"groups: {found.groups}; cases in groups: {share(found.cases, found.pool)} of the "
        "era's pool cases",
        f"group sizes, groups (cases in them): {sizes}",
        f"leave-one-out agreement (denominator: the {found.cases} cases in groups):",
        *_agreement(found.loo, found.cases),
        f"pairwise agreement (denominator: the {found.pairs} pairs within groups):",
        *_agreement(found.agreeing_pairs, found.pairs),
    ]


def pair_lines(groups: Sequence[Group], tables: CodeTables) -> list[str]:
    """The ten first-code pairs that most often disagree within exact-twin groups, all years.

    Args:
        groups: the exact-twin groups, all years.
        tables: the code tables, for labels.

    Returns:
        The lines: codes and labels only.
    """
    pairs = disagreeing_pairs(groups)
    total = sum(n for _a, _b, n in pairs)
    lines = [
        f"## exact twins, all years: the {TOP_PAIRS} first-code pairs that most often disagree",
        "",
        "Each line is a pair of six-digit first codes and how many pairs of twins within a group "
        f"carry one each ({total} disagreeing pairs in all, of "
        f"{sum(len(g) * (len(g) - 1) // 2 for g in groups)} pairs within groups).",
    ]
    if not pairs:
        return [*lines, "none: no pair of twins disagrees on the first code"]
    for rank, (a, b, n) in enumerate(pairs[:TOP_PAIRS], start=1):
        lines.append(
            f"{rank}. {a} {occurrence_label(tables, a)} vs {b} {occurrence_label(tables, b)}: "
            f"{n} pairs"
        )
    return lines


def method_lines(cases: Sequence[PoolText], pool: Mapping[str, int]) -> list[str]:
    """How the pool was built and the twins formed.

    Args:
        cases: the kept pool cases.
        pool: the pool's counts (``statistics pool``, ``no text``, ``no code``).

    Returns:
        The lines.
    """
    years = sorted({c.event_date.year for c in cases})
    span = f"event years {years[0]}-{years[-1]}" if years else "no case"
    return [
        "## Method",
        "",
        f"Pool: the S3 statistics pool, {STAGES[pp.STAGE].built_from}: "
        f"{pool['statistics pool']} cases; kept, each with an NTSB probable-cause text and at "
        f"least one occurrence code: {len(cases)} ({span}); left out: {pool['no text']} with no "
        f"probable-cause text, {pool['no code']} more with no occurrence code.",
        "Exact twins: the same tokens in the same order, a token being a run of [a-z0-9] in the "
        "lower-cased text, no word removed; so case, punctuation and curly or straight "
        "apostrophes make no difference. Loose twins: the same set of those tokens less the "
        f"precedent probe's {len(pp.STOP_WORDS)} stop words, in any order. A group is two or "
        "more cases with the same non-empty key.",
        "Eras: all years; 2009–2014 and 2015–2019, where the groups are formed again among the "
        "cases with an event year in the era (a group needs two members inside it), and the "
        "share is of the era's pool cases.",
        "First code: the case's first occurrence code, the NTSB's defining event; its event is "
        "the last three digits and its phase the first three.",
        "Leave-one-out agreement (the headline): a case agrees when the commonest value among "
        "the other members of its group, ties to the smallest value as a string, is its own. "
        "Denominator: the cases in groups. Pairwise agreement: every unordered pair within a "
        "group, the two values equal. Denominator: the pairs; a large group adds many pairs, so "
        "this figure leans toward the largest groups, and leave-one-out counts every case once.",
        "Intervals: 95% Wilson, treating cases (or pairs) as independent. Cases in one group "
        "share a sentence and pairs share cases, so the intervals are narrower than the data "
        "warrant.",
        "What it does not say: that the NTSB was inconsistent. The same sentence can follow "
        "accidents whose sequences of events differ; it bounds what a coder reading only the "
        "sentence could score.",
    ]


def report(
    found: Mapping[tuple[Grouping, str], Found],
    cases: Sequence[PoolText],
    pool: Mapping[str, int],
    tables: CodeTables,
) -> str:
    """The whole report: the head, the expectation, the method, each grouping and era, the pairs.

    Args:
        found: each grouping's groups and tally in each era (``analyse``).
        cases: the kept pool cases.
        pool: the pool's counts.
        tables: the code tables, for labels.

    Returns:
        The report's text.
    """
    head = "\n".join(
        [
            "S3.1 coding-consistency probe on the development pool "
            "(scripts/exploratory/s3_coding_consistency.py; S3.1 Task 15)",
            "Exploratory (decision 0059): free and offline, no model call; it decides nothing. "
            "How far the NTSB's own probable-cause sentence settles its first occurrence code: "
            "cases whose sentences match word for word (exact twins), or in their words less "
            "common function words (loose twins), compared on the first code the NTSB gave each.",
            "Counts and code labels only: no case number and no text from any record. Every "
            "count is printed with its denominator; agreement with a 95% Wilson interval.",
        ]
    )
    exact_all = found[("exact", ALL_YEARS.name)]
    blocks = [
        head,
        "\n".join(expectation_lines(exact_all.tally)),
        "\n".join(method_lines(cases, pool)),
    ]
    for grouping in GROUPINGS:
        blocks.append(f"## {GROUPING_TITLE[grouping]}")
        blocks += [
            "\n".join(block_lines(grouping, era, found[(grouping, era.name)].tally))
            for era in ERAS
        ]
    blocks.append("\n".join(pair_lines(exact_all.groups, tables)))
    blocks.append(
        f"The {LARGEST} largest exact-twin groups, with their texts and first-code counts, are "
        f"written to {GROUPS_FILE} in a private folder under the runs folder, never committed."
    )
    return "\n\n".join(blocks)


# --- the private file ---


def largest(groups: Sequence[Group], count: int = LARGEST) -> list[Group]:
    """The ``count`` largest groups, ties by the first member's case id."""
    return sorted(groups, key=lambda g: (-len(g), g[0].case_id))[:count]


def groups_markdown(
    chosen: Sequence[Group], raws: Sequence[Mapping[str, object]], tables: CodeTables
) -> str:
    """The private file: each group's text, size and first-code counts. No case number.

    Args:
        chosen: the groups to show, largest first.
        raws: each group's first member's record, in the same order, for the name replacements.
        tables: the code tables, for labels.

    Returns:
        The file's text.
    """
    lines = [
        f"# The {LARGEST} largest exact-twin groups (S3.1 coding-consistency probe)",
        "",
        "Private: this file holds probable-cause text from NTSB records. It is never committed. "
        "It holds no case number. Each group's members share the same words in the same order; "
        "they may differ in case, punctuation and spacing, so the text shown is the first "
        "member's (the first by case id), whitespace collapsed. Owner and operator names the "
        "record holds, and an amateur-built aircraft's make and model, are replaced; other "
        "names are not detected.",
    ]
    if not chosen:
        lines += ["", "No exact-twin group."]
    for rank, (group, raw) in enumerate(zip(chosen, raws, strict=True), start=1):
        counts = sorted(
            Counter(c.sequence[0] for c in group).items(), key=lambda item: (-item[1], item[0])
        )
        lines += [
            "",
            f"## Group {rank}: {len(group)} cases",
            "",
            "> " + " ".join(clean(group[0].text, raw).split()),
            "",
            "First codes:",
            *(f"- {code} {occurrence_label(tables, code)}: {n}" for code, n in counts),
        ]
    return "\n".join(lines) + "\n"


def records(processed: Path, chosen: Sequence[Group]) -> list[Mapping[str, object]]:
    """Each group's first member's record, refused unless it is that case and its text.

    Args:
        processed: the processed folder.
        chosen: the groups to show.

    Returns:
        The records, in ``chosen``'s order.
    """
    if not chosen:
        return []
    firsts = [g[0] for g in chosen]
    raws = samples.load_cases(processed, [c.case_id for c in firsts])
    for case, raw in zip(firsts, raws, strict=True):
        check_record(case.case_id, raw)
        if fields.probable_cause(raw) != case.text:
            _refuse(f"{case.case_id}: the record read for it is not the text the pool read")
    return list(raws)


# --- the command ---


def _relative(folder: Path, runs_dir: Path) -> str:
    """The private folder as printed: under the runs folder, or by its own name."""
    resolved = folder.resolve()
    if resolved.is_relative_to(runs_dir.resolve()):
        return resolved.relative_to(runs_dir.resolve()).as_posix()
    return folder.name


def _now() -> datetime:
    return datetime.now(UTC)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_coding_consistency")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--groups-out-dir",
        type=Path,
        default=None,
        help=f"the private file's folder; default <NTSB_RUNS_DIR>/{FOLDER}/<UTC time>/",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, now: Callable[[], datetime] = _now) -> int:
    """Print, and with ``--out`` also write, the counts; write the private file of groups.

    Args:
        argv: the command line.
        now: the clock, for the default folder's name only.

    Returns:
        0.
    """
    args = _arguments(argv)
    settings = Settings()
    explicit: Path | None = args.groups_out_dir
    refuse_inside_repository(explicit if explicit is not None else settings.runs_dir / FOLDER)
    processed = settings.data_dir / "processed"
    cases, _dates, counts = pp.read_pool_texts(processed)
    tables = load_tables()
    found = analyse(cases)
    text = report(found, cases, counts, tables)
    chosen = largest(found[("exact", ALL_YEARS.name)].groups)
    markdown = groups_markdown(chosen, records(processed, chosen), tables)
    if explicit is None:
        folder = new_folder(settings.runs_dir / FOLDER, now())
    else:
        folder = explicit
        if (folder / GROUPS_FILE).exists():
            _refuse(f"{folder / GROUPS_FILE} already exists; it is never written over")
        folder.mkdir(parents=True, exist_ok=True)
    (folder / GROUPS_FILE).write_text(markdown, encoding="utf-8")
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(_relative(folder, settings.runs_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
