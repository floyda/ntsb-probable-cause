"""Where the loop's findings go wrong, and whether the NTSB's choices follow the pool's habits.

Status
    Exploratory (decision 0059), S3.1 Task 15, free and offline: no model call, no network. It
    sets no bar and tunes nothing. Its definitions and its next-step rule were committed before
    it existed (commit ef25347, the S3.1 plan's entry "A 'where the findings go wrong' probe,
    with its definitions and next-step rule committed first"); it applies that rule and prints
    the rule's line at the top. ``make s3-finding-misses`` writes its output to
    ``docs/results/s3-finding-misses-dev.txt``.

Why
    The loop's flagged-finding recall falls from about half at 6 digits (the category) to about
    a third at 8 (the item) and to a little over a quarter at 10 (the modifier), so the item step
    costs more than the modifier step. This asks where the loop's findings are lost, and whether
    the choices the NTSB made at the steps the loop misses are the pool's usual ones: if the
    NTSB's item is its category's commonest item in at least half of the item misses, a "use the
    usual item" step is worth testing offline; if it is not, item choice is case-specific
    judgement, and findings are better reported at the category level beside the full code.

What it measures
    Judged cases, for each run: the ones the findings-from-precedent probe judges
    (``s3_finding_precedent.sort_cases``: scored, not abstained, and with at least one finding
    the NTSB flagged as cause). Unit: each NTSB flagged finding of a judged case, each ten-digit
    code once per case, classed by ``scoring.misses.finding_depth`` against the loop's final
    findings (the last step's answer, ``miss_kinds.scored_answer``; the ten-digit codes of the
    findings that carry an item, which are the findings the harness scores) at the deepest level
    any of them reaches it: exact, item right with the modifier wrong, category right with the
    item wrong, or category missed. Counts and shares (Wilson intervals), overall, by the
    finding's section (its first two digits), and for fatal and non-fatal cases. Pool habits: in
    the S3 statistics pool's flagged findings (``s3_precedent_probe.read_pool_texts``, after
    ``check_pool``; each case counts each distinct ten-digit code once), each category's
    commonest item and each item's commonest modifier, with the share of the findings carrying
    it (ties to the smallest code). For the findings missed at the item step and at the modifier
    step: how often the NTSB's choice, and the loop's, is the pool's commonest one; the ten
    commonest (NTSB, loop) pairs; the ten categories (items) with the most such misses. Beside
    it: the loop's own findings that reach no NTSB flagged finding even at 6 digits, by section.
    Counts, shares and code labels only: no case number and no record text.

Refusals
    The runs through ``s3_precedent_probe.load_run`` (its refusals, and arm C only), a run named
    twice, and ``s3_finding_precedent.sort_cases`` (a judged case whose stored scores hold no
    finding recall). The pool through ``check_pool``: a sample case or a non-development case
    raises ``LeakageError`` before any pool text or finding is read.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.exploratory.s3_finding_misses \
        --runs RUN_A RUN_B [--out PATH]

    Prints the report; with ``--out`` also writes it (and a newline) to PATH. The report holds no
    time and no path, so it can be recomputed byte for byte.
"""

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NoReturn

from scripts.coding_stats import STAGES
from scripts.exploratory import s3_finding_precedent as fp
from scripts.exploratory import s3_precedent_probe as pp
from scripts.miss_kinds import scored_answer

from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.misses import finding_depth
from ntsb_probable_cause.settings import Settings

type Level = Literal[
    "exact",
    "item right, modifier wrong",
    "category right, item wrong",
    "category missed",
]

EXACT: Final[Level] = "exact"
ITEM_RIGHT: Final[Level] = "item right, modifier wrong"
CATEGORY_RIGHT: Final[Level] = "category right, item wrong"
MISSED: Final[Level] = "category missed"
LEVELS: Final[tuple[Level, ...]] = (EXACT, ITEM_RIGHT, CATEGORY_RIGHT, MISSED)

TOP: Final = 10
MIN_FINDINGS: Final = 10  # a category or an item with fewer pool findings is not read for a habit
HIGH_PERCENT: Final = 80
RULE_COMMIT: Final = "ef25347"
SEPARATOR: Final = " — "  # between the parts of a code table label
UNKNOWN: Final = "not in the code tables"

# The committed rule (plan entry "A 'where the findings go wrong' probe, with its definitions and
# next-step rule committed first", commit ef25347), word for word less the entry's bold marks.
RULE: Final = (
    'Next-step rule (Andy, 2026-10-03). On run a: if, among the "category right, item wrong" '
    "findings, the NTSB's item is the pool's commonest item for that category in at least half, "
    'the next step is an offline test of a "use the usual item" step (registered before it is '
    "computed); otherwise item choice is read as case-specific judgement, and findings are "
    "reported at the category level beside the full code. The script applies the rule and "
    "prints which."
)
EXPECTATION: Final = (
    "Expectation (decides nothing). The item step loses more of the loop's findings than the "
    "modifier step, and the NTSB's item is the pool's commonest item in at least half of the "
    "item misses."
)
USE_USUAL: Final = "next: an offline 'use the usual item' test"
CASE_SPECIFIC: Final = (
    "next: item choice read as case-specific; report findings at the category level beside the "
    "full code"
)


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_finding_misses: {message}")


# --- the classes ---


def level_of(predicted: Sequence[str], code: str) -> Level:
    """How deep the loop's findings reach one NTSB flagged finding, by ``finding_depth`` itself.

    Args:
        predicted: the loop's final findings, ten digits each.
        code: one NTSB flagged finding, ten digits.

    Returns:
        ``exact`` if the loop holds the code; else ``item right, modifier wrong`` if a loop
        finding shares its first eight digits; else ``category right, item wrong`` if one shares
        its first six; else ``category missed``.
    """
    depth = finding_depth(predicted, (code,))
    if depth.found:
        return EXACT
    if depth.item_right_modifier_wrong:
        return ITEM_RIGHT
    if depth.category_right_item_wrong:
        return CATEGORY_RIGHT
    return MISSED


@dataclass(frozen=True)
class Flag:
    """One NTSB flagged finding of a judged case, and how far the loop's findings reach it."""

    code: str
    level: Level
    fatal: bool
    loop: tuple[str, ...]  # the loop's final findings in the code's category, ten digits each


@dataclass(frozen=True)
class Habit:
    """The commonest value under one key in the pool, and how many findings carry it."""

    value: str
    count: int
    total: int  # the key's findings
    distinct: int  # the key's different values


def commonest(counts: Mapping[str, int]) -> Habit:
    """The value held most, ties to the smallest code; with its count, the total and the variety."""
    value, count = min(counts.items(), key=lambda held: (-held[1], held[0]))
    return Habit(value, count, sum(counts.values()), len(counts))


def habits(codes: Iterable[str], key: slice, value: slice) -> dict[str, Habit]:
    """For each key, the commonest value among ``codes``; ties go to the smallest value.

    Args:
        codes: ten-digit finding codes, one entry per finding.
        key: the digits that name the key (``[:6]`` the category, ``[:8]`` the item).
        value: the digits that name what is chosen under it (``[:8]`` the item, ``[8:]`` the
            modifier).

    Returns:
        Each key with a finding, and its commonest value.
    """
    held: dict[str, Counter[str]] = {}
    for code in codes:
        held.setdefault(code[key], Counter())[code[value]] += 1
    return {name: commonest(counts) for name, counts in held.items()}


@dataclass(frozen=True)
class Step:
    """One step down the code: the miss it reads, what that miss is keyed on, what is chosen."""

    level: Level
    key: slice
    value: slice
    key_name: str
    key_plural: str
    value_name: str
    key_table: Literal["categories", "items"]
    value_table: Literal["items", "modifiers"]


ITEM: Final = Step(
    CATEGORY_RIGHT,
    slice(0, 6),
    slice(0, 8),
    "category",
    "categories",
    "item",
    "categories",
    "items",
)
MODIFIER: Final = Step(
    ITEM_RIGHT, slice(0, 8), slice(8, 10), "item", "items", "modifier", "items", "modifiers"
)


@dataclass(frozen=True)
class Misses:
    """The findings lost at one step, read against the pool's habit at that step."""

    total: int
    ntsb_usual: int  # the NTSB's choice is the pool's commonest one for its key
    loop_usual: int  # the loop's choice is, in at least one of the loop's findings under the key
    no_habit: int  # the pool holds no finding under the key
    pairs: Mapping[tuple[str, str], int]  # (the NTSB's value, the loop's value), by findings
    keys: Mapping[str, tuple[int, int]]  # by key: misses, and those whose NTSB choice is usual


def read_misses(flags: Sequence[Flag], step: Step, pool: Mapping[str, Habit]) -> Misses:
    """The flagged findings lost at ``step``, and how often each side's choice is the pool's usual.

    The loop's choice for a finding is the value of each of the loop's findings in the same key
    (its category for the item step, its item for the modifier step). A finding whose key holds
    several different loop values counts the loop as usual if any is, and one pair under each.

    Args:
        flags: the NTSB flagged findings of the judged cases, classed.
        step: the item step or the modifier step.
        pool: the pool's commonest value for each key.

    Returns:
        The counts.
    """
    total = ntsb_usual = loop_usual = no_habit = 0
    pairs: Counter[tuple[str, str]] = Counter()
    missed: Counter[str] = Counter()
    usual_by_key: Counter[str] = Counter()
    for flag in flags:
        if flag.level != step.level:
            continue
        total += 1
        key, value = flag.code[step.key], flag.code[step.value]
        loop_values = tuple(dict.fromkeys(p[step.value] for p in flag.loop if p[step.key] == key))
        missed[key] += 1
        habit = pool.get(key)
        if habit is None:
            no_habit += 1
        else:
            if value == habit.value:
                ntsb_usual += 1
                usual_by_key[key] += 1
            if habit.value in loop_values:
                loop_usual += 1
        for loop_value in loop_values:
            pairs[value, loop_value] += 1
    return Misses(
        total,
        ntsb_usual,
        loop_usual,
        no_habit,
        dict(pairs),
        {key: (count, usual_by_key[key]) for key, count in missed.items()},
    )


# --- the pool ---


@dataclass(frozen=True)
class Pool:
    """The S3 statistics pool's flagged findings, and the habits read from them."""

    cases: int  # kept pool cases with at least one flagged finding
    findings: int  # each case's distinct ten-digit flagged codes, added up
    items: Mapping[str, Habit]  # by category: its commonest item
    modifiers: Mapping[str, Habit]  # by item: its commonest modifier


def read_pool(flagged: Iterable[Sequence[str]]) -> Pool:
    """The pool's habits from each kept case's flagged codes; a case counts a code once.

    Args:
        flagged: each kept pool case's flagged-as-cause finding codes, in any order.

    Returns:
        The counts and the two habit maps.
    """
    codes: list[str] = []
    cases = 0
    for found in flagged:
        distinct = sorted(set(found))
        cases += bool(distinct)
        codes += distinct
    return Pool(
        cases,
        len(codes),
        habits(codes, ITEM.key, ITEM.value),
        habits(codes, MODIFIER.key, MODIFIER.value),
    )


@dataclass(frozen=True)
class Summary:
    """How strong the pool's habits are across one kind of key."""

    keys: int
    top: int  # findings carrying their key's commonest value
    findings: int
    big: int  # keys with at least MIN_FINDINGS findings
    high: int  # of those, keys whose commonest value carries at least HIGH_PERCENT of them
    single: int  # of those, keys that hold one value only


def summarise(pool: Mapping[str, Habit]) -> Summary:
    """The findings-weighted share of the commonest value, and how many keys are 80% or more.

    The share is a whole-number comparison (``count * 100 >= total * 80``), so exactly 80% is
    counted.
    """
    big = [habit for habit in pool.values() if habit.total >= MIN_FINDINGS]
    high = [habit for habit in big if habit.count * 100 >= habit.total * HIGH_PERCENT]
    return Summary(
        len(pool),
        sum(habit.count for habit in pool.values()),
        sum(habit.total for habit in pool.values()),
        len(big),
        len(high),
        sum(habit.distinct == 1 for habit in high),
    )


# --- the runs ---


@dataclass(frozen=True)
class RunReading:
    """One run's judged cases read: each flagged finding classed, and the loop's unmatched ones."""

    run_id: str
    split: fp.CaseSplit
    flags: tuple[Flag, ...]
    repeated: int  # flagged codes left out because a case holds the same ten-digit code twice
    loop_by_section: Mapping[str, int]  # the loop's final findings (distinct per case)
    unmatched_by_section: Mapping[str, int]  # of them, reaching no flagged finding at 6 digits
    item: Misses
    modifier: Misses


def read_run(run_id: str, split: fp.CaseSplit, tables: CodeTables, pool: Pool) -> RunReading:
    """Class every NTSB flagged finding of a run's judged cases, and read the two steps.

    Args:
        run_id: the run's id.
        split: its cases, sorted; the judged ones are read.
        tables: the code tables, which compose the loop's ten-digit findings.
        pool: the pool, whose habits the misses are read against.

    Returns:
        The reading.

    Raises:
        ValueError: a judged case has no final answer, which a judged case always has.
    """
    flags: list[Flag] = []
    repeated = 0
    loop_total: Counter[str] = Counter()
    loop_unmatched: Counter[str] = Counter()
    for judged in split.judged:
        answer = scored_answer(judged.case)
        if answer is None:
            raise ValueError("a judged case has a final answer")
        predicted = tuple(dict.fromkeys(answer.finding_codes(tables)))
        own = tuple(dict.fromkeys(judged.own))
        repeated += len(judged.own) - len(own)
        flags += [
            Flag(
                code,
                level_of(predicted, code),
                judged.case.fatal,
                tuple(p for p in predicted if p[:6] == code[:6]),
            )
            for code in own
        ]
        categories = {code[:6] for code in own}
        for code in predicted:
            loop_total[code[:2]] += 1
            if code[:6] not in categories:
                loop_unmatched[code[:2]] += 1
    return RunReading(
        run_id,
        split,
        tuple(flags),
        repeated,
        dict(loop_total),
        dict(loop_unmatched),
        read_misses(flags, ITEM, pool.items),
        read_misses(flags, MODIFIER, pool.modifiers),
    )


# --- the rule ---


def at_least_half(usual: int, total: int) -> bool:
    """Whether ``usual`` is at least half of ``total``; exactly half is, none of none is not."""
    return total > 0 and usual * 2 >= total


def next_step(usual: int, total: int) -> str:
    """The committed rule's line.

    Args:
        usual: item misses whose NTSB item is the pool's commonest for its category.
        total: item misses.

    Returns:
        ``next: an offline 'use the usual item' test`` when the NTSB's item is the commonest in
        at least half of the item misses (``usual * 2 >= total``, so exactly half counts);
        otherwise the case-specific line. With no item miss there is no half to reach, so it is
        the case-specific line.
    """
    return USE_USUAL if at_least_half(usual, total) else CASE_SPECIFIC


def _met(*, yes: bool) -> str:
    return "met" if yes else "not met"


def _label(table: Mapping[str, str], code: str) -> str:
    return f"{code}: {table.get(code, UNKNOWN)}"


def section_labels(tables: CodeTables) -> dict[str, str]:
    """Each section's name as the code tables give it: the first part of a category's label."""
    labels: dict[str, str] = {}
    for code, label in sorted(tables.categories.items()):
        labels.setdefault(code[:2], label.split(SEPARATOR)[0])
    return labels


def _section(labels: Mapping[str, str], code: str) -> str:
    return f"{code} {labels.get(code, UNKNOWN)}"


def rule_lines(results: Sequence[RunReading]) -> list[str]:
    """The committed rule applied on run a, run b's count beside it, and the expectation.

    Args:
        results: run a's and run b's readings.

    Returns:
        The lines, with the rule's line (``next: ...``) among them.
    """
    a, b = results
    lines = [
        f"## The rule (committed in {RULE_COMMIT}, before this script existed)",
        "",
        RULE,
        f'Run a ({a.run_id}): among the {a.item.total} findings classed "{CATEGORY_RIGHT}", the '
        f"NTSB's item is the pool's commonest item for its category in "
        f"{pp.share(a.item.ntsb_usual, a.item.total)}.",
    ]
    if not a.item.total:
        lines.append(
            f'Note: no finding is classed "{CATEGORY_RIGHT}", so there is no half to reach and '
            "the rule's second branch is read."
        )
    lines += [
        f"Run b ({b.run_id}), beside it, decides nothing: the NTSB's item is the pool's "
        f"commonest in {pp.share(b.item.ntsb_usual, b.item.total)}.",
        next_step(a.item.ntsb_usual, a.item.total),
        EXPECTATION,
        f"- the item step loses more of the loop's findings than the modifier step, on run a: "
        f'"{CATEGORY_RIGHT}" {a.item.total} against "{ITEM_RIGHT}" {a.modifier.total}: '
        f"{_met(yes=a.item.total > a.modifier.total)}",
        "- the NTSB's item is the pool's commonest item in at least half of the item misses, on "
        f"run a, {pp.share(a.item.ntsb_usual, a.item.total)}: "
        f"{_met(yes=at_least_half(a.item.ntsb_usual, a.item.total))}",
    ]
    return lines


# --- the lines ---


def method_lines(counts: Mapping[str, int], kept: int, pool: Pool, years: str) -> list[str]:
    """How the findings were classed, the pool read and the misses counted, and what is left out.

    Args:
        counts: the pool's counts (``statistics pool``, ``no text``, ``no code``).
        kept: the pool cases kept.
        pool: the pool's findings and habits.
        years: the kept pool's event years, as a span.

    Returns:
        The lines.
    """
    return [
        "## Method",
        "",
        "Judged cases, for each run: as the findings-from-precedent probe judges them "
        "(`s3_finding_precedent.sort_cases`): scored (not failed: decision 0136 item 1), not "
        "abstained (the final answer's abstain flag is false), and with at least one finding the "
        "NTSB flagged as cause. Each of the run's cases is counted once, in that order: failed, "
        "abstained, no flagged finding, judged.",
        "Unit: each finding the NTSB flagged as cause in a judged case, each ten-digit code once "
        "per case. It is classed one finding at a time by `scoring.misses.finding_depth` against "
        "the loop's final findings, at the deepest level any of them reaches it: exact (all ten "
        f"digits); {ITEM_RIGHT} (the first eight digits, not all ten); {CATEGORY_RIGHT} (the "
        f"first six, not the first eight); {MISSED} (not even the first six). The loop's final "
        "findings are the last step's answer (`miss_kinds.scored_answer`): the ten-digit codes "
        "of its findings that carry an item, each code once, which are the findings the harness "
        "scores.",
        "Shares are over findings, not cases: a case with more flagged findings counts for more, "
        "so the exact share is not the harness's mean per-case recall at 10 digits. The Wilson "
        "95% intervals treat findings as independent, although the findings of one case are "
        "not.",
        "Sections: a finding's first two digits, named as the code tables name them. Personnel "
        "issues' modifiers name who acted; the others' name a state or an effect.",
        f"Pool: the S3 statistics pool, {STAGES[pp.STAGE].built_from}: "
        f"{counts['statistics pool']} cases; kept, each with an NTSB probable-cause text and at "
        f"least one occurrence code: {kept} ({years}); left out: {counts['no text']} with no "
        f"probable-cause text, {counts['no code']} more with no occurrence code. Of the kept "
        f"cases {pool.cases} have at least one finding flagged as cause, holding {pool.findings} "
        "flagged findings, each case counting each distinct ten-digit code once. The judged "
        "cases are `dev-400`'s, which the pool leaves out, so a judged case's findings are never "
        "in the habits they are read against.",
        "Habits: for each category (first six digits) the commonest item (first eight) among "
        "its pool findings, and the share of the category's findings carrying it; for each item "
        "the commonest modifier (last two) and the share of the item's findings carrying it. A "
        "tie goes to the smallest code. An item sits under one category, so the item names the "
        "(category, item) the modifier habit is read under.",
        f'Misses: among the findings classed "{CATEGORY_RIGHT}", whether the NTSB\'s item is the '
        "pool's commonest item for its category, and whether the loop's item is (the loop's "
        "findings in that category; if it has several, the loop counts as using the commonest "
        "item when any of them carries it); a finding whose category holds several different "
        "loop items is counted once under each (NTSB item, loop item) pair. The same for "
        f'"{ITEM_RIGHT}", for the modifier under the item. A category (or an item) the pool '
        "holds no finding in has no commonest value, so neither side's choice can be it; those "
        "findings are counted apart.",
        "Beside: the loop's final findings (each distinct code once per case) whose first six "
        "digits match none of the NTSB's flagged findings of their case. This is against the "
        "flagged findings only, so it is not the trail pages' 'matches no NTSB finding', which "
        "also counts the NTSB's unflagged findings.",
        "The rule is applied above on run a. Everything else is printed and decides nothing.",
    ]


def summary_lines(pool: Pool) -> list[str]:
    """The pool's habits in summary: how strong the commonest item and modifier are."""
    lines = [
        "## The pool's habits",
        "",
        f"Pool findings: {pool.findings} in {pool.cases} cases (each case's distinct ten-digit "
        f"flagged codes).",
    ]
    for step, habit_map in ((ITEM, pool.items), (MODIFIER, pool.modifiers)):
        value, key, plural = step.value_name, step.key_name, step.key_plural
        found = summarise(habit_map)
        lines += [
            "",
            f"The commonest {value} under each {key} ({found.keys} {plural} hold a pool finding):",
            f"- findings-weighted mean of the commonest {value}'s share across {plural}, that is "
            f"the pool's findings carrying their {key}'s commonest {value}: "
            f"{pp.share(found.top, found.findings)}",
            f"- {plural} with at least {MIN_FINDINGS} pool findings: {found.big} of {found.keys}; "
            f"of those, with a commonest {value} carrying at least {HIGH_PERCENT}% of the "
            f"{key}'s findings: {pp.share(found.high, found.big)}, of which {found.single} hold "
            f"one {value} only in the pool",
        ]
    return lines


def class_lines(flags: Sequence[Flag]) -> list[str]:
    """The four classes of a set of flagged findings, each with its count, share and interval."""
    if not flags:
        return ["- no flagged finding"]
    held = Counter(flag.level for flag in flags)
    return [f"- {level}: {pp.with_interval(held[level], len(flags))}" for level in LEVELS]


def _step_lines(
    found: Misses, step: Step, pool: Mapping[str, Habit], tables: CodeTables
) -> list[str]:
    """One step's misses against the pool's habit: the two counts, the pairs and the keys."""
    value, key = step.value_name, step.key_name
    if not found.total:
        return [f'- no finding is classed "{step.level}"']
    value_labels: Mapping[str, str] = getattr(tables, step.value_table)
    key_labels: Mapping[str, str] = getattr(tables, step.key_table)
    lines = [
        f'- findings classed "{step.level}": {found.total}',
        f"- the NTSB's {value} is the pool's commonest {value} for its {key}: "
        f"{pp.with_interval(found.ntsb_usual, found.total)}",
        f"- the loop's {value} is it (any of the loop's findings under the {key} carrying it): "
        f"{pp.with_interval(found.loop_usual, found.total)}",
        f"- the pool holds no finding under the {key}, so neither can be: "
        f"{pp.share(found.no_habit, found.total)}",
        "",
        f"The {TOP} commonest (NTSB {value}, loop {value}) pairs ({len(found.pairs)} different "
        f"pairs, from {found.total} findings; a finding counts once under each different loop "
        f"{value} in its {key}):",
    ]
    ranked_pairs = sorted(found.pairs.items(), key=lambda held: (-held[1], held[0]))[:TOP]
    lines += [
        f"- {count}  {_label(value_labels, theirs)} -> {_label(value_labels, ours)}"
        for (theirs, ours), count in ranked_pairs
    ]
    lines += [
        "",
        f"The {TOP} {step.key_plural} with the most {value} misses ({len(found.keys)} "
        f"{step.key_plural} lose a finding at this step):",
    ]
    ranked_keys = sorted(found.keys.items(), key=lambda held: (-held[1][0], held[0]))[:TOP]
    for name, (misses, usual) in ranked_keys:
        habit = pool.get(name)
        pooled = (
            "the pool holds no finding under it"
            if habit is None
            else f"the pool's commonest {value} is {_label(value_labels, habit.value)}, "
            f"{pp.share(habit.count, habit.total)} of its findings"
        )
        lines.append(
            f"- {misses}  {_label(key_labels, name)}: the NTSB's {value} is the pool's commonest "
            f"in {usual} of them; {pooled}"
        )
    return lines


def beside_lines(reading: RunReading, labels: Mapping[str, str]) -> list[str]:
    """The loop's final findings that reach no NTSB flagged finding even at 6 digits, by section."""
    total = sum(reading.loop_by_section.values())
    unmatched = sum(reading.unmatched_by_section.values())
    lines = [
        "- the loop's final findings in the judged cases (each distinct code once per case) "
        "reaching no NTSB flagged finding of their case even at 6 digits: "
        f"{pp.share(unmatched, total)}"
    ]
    for section, held in sorted(reading.loop_by_section.items()):
        unmatched_here = reading.unmatched_by_section.get(section, 0)
        lines.append(f"- {_section(labels, section)}: {pp.share(unmatched_here, held)}")
    return lines


def run_lines(reading: RunReading, *, letter: str, pool: Pool, tables: CodeTables) -> list[str]:
    """One run: its case counts, the four classes overall and apart, and the two steps' misses.

    Args:
        reading: the run's reading.
        letter: ``a`` or ``b``.
        pool: the pool, for the habits the misses are read against.
        tables: the code tables, for labels.

    Returns:
        The lines.
    """
    split, flags = reading.split, reading.flags
    labels = section_labels(tables)
    note = "" if letter == "a" else ", beside run a; decides nothing"
    cases = len(split.judged)
    deaths = sum(judged.case.fatal for judged in split.judged)
    lines = [
        f"## Run {letter} ({reading.run_id}){note}",
        "",
        fp.count_line(split),
        f"The NTSB's flagged findings of the judged cases: {len(flags)} (each ten-digit code once "
        f"per case; a code flagged twice in one case, left out once: {reading.repeated}).",
        "",
        f"### All judged cases: {len(flags)} flagged findings in {cases} cases",
        *class_lines(flags),
    ]
    for section in sorted({flag.code[:2] for flag in flags}):
        chosen = [flag for flag in flags if flag.code[:2] == section]
        lines += [
            "",
            f"### Section {_section(labels, section)}: {len(chosen)} flagged findings",
            *class_lines(chosen),
        ]
    for title, fatal, count in (
        ("Fatal cases", True, deaths),
        ("Non-fatal cases", False, cases - deaths),
    ):
        chosen = [flag for flag in flags if flag.fatal == fatal]
        lines += [
            "",
            f"### {title}: {len(chosen)} flagged findings in {count} cases",
            *class_lines(chosen),
        ]
    lines += [
        "",
        f"### {CATEGORY_RIGHT}: the NTSB's item against the pool's habit",
        "",
        *_step_lines(reading.item, ITEM, pool.items, tables),
        "",
        f"### {ITEM_RIGHT}: the NTSB's modifier against the pool's habit",
        "",
        *_step_lines(reading.modifier, MODIFIER, pool.modifiers, tables),
        "",
        "### Beside: the loop's own findings that match no NTSB flagged finding at all",
        "",
        *beside_lines(reading, labels),
    ]
    return lines


def report(  # noqa: PLR0913 -- one keyword per piece of the report.
    results: Sequence[RunReading],
    *,
    pool: Pool,
    counts: Mapping[str, int],
    kept: int,
    years: str,
    tables: CodeTables,
) -> str:
    """The whole report: the head, the rule, the method, the pool's habits, run a and run b.

    Args:
        results: run a's and run b's readings.
        pool: the pool's findings and habits.
        counts: the pool's counts (``statistics pool``, ``no text``, ``no code``).
        kept: the pool cases kept.
        years: the kept pool's event years, as a span.
        tables: the code tables.

    Returns:
        The report's text.
    """
    head = [
        "S3.1 where-the-findings-go-wrong probe on dev-400 "
        "(scripts/exploratory/s3_finding_misses.py; S3.1 Task 15)",
        "Exploratory (decision 0059): free and offline, no model call; it sets no bar and tunes "
        "nothing. How far the loop's final findings reach each finding the NTSB flagged as "
        "cause, and whether the NTSB's item and modifier choices follow the pool's habits.",
        "Counts, shares and code labels only: no case number and no record text. Shares have a "
        "Wilson 95% interval, each with its denominator.",
        f"run a = {results[0].run_id}",
        f"run b = {results[1].run_id} (printed beside run a; decides nothing)",
    ]
    blocks = [
        "\n".join(head),
        "\n".join(rule_lines(results)),
        "\n".join(method_lines(counts, kept, pool, years)),
        "\n".join(summary_lines(pool)),
        *(
            "\n".join(run_lines(r, letter="ab"[n], pool=pool, tables=tables))
            for n, r in enumerate(results)
        ),
    ]
    return "\n\n".join(blocks)


# --- the command ---


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_finding_misses")
    parser.add_argument("--runs", nargs=2, required=True, metavar=("RUN_A", "RUN_B"))
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the classes, the habits and the rule's line.

    Args:
        argv: the command line.

    Returns:
        0.
    """
    args = _arguments(argv)
    if args.runs[0] == args.runs[1]:
        _refuse("a run is named twice; run a and run b are two different runs")
    runs = [pp.load_run(run_id) for run_id in args.runs]
    splits = [fp.sort_cases(run.cases) for run in runs]
    texts, _dates, counts = pp.read_pool_texts(Settings().data_dir / "processed")
    tables = load_tables()
    pool = read_pool(case.findings for case in texts)
    results = [
        read_run(run.run_id, split, tables, pool) for run, split in zip(runs, splits, strict=True)
    ]
    years = sorted({case.event_date.year for case in texts})
    text = report(
        results,
        pool=pool,
        counts=counts,
        kept=len(texts),
        years=f"event years {years[0]}-{years[-1]}" if years else "no case",
        tables=tables,
    )
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
