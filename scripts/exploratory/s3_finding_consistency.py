"""How far the NTSB's own cause sentence settles the findings it flags as cause.

Status
    Exploratory (decision 0059), S3.1 Task 15, free and offline: no model call, no network. It
    decides nothing: not round 1, not the loop. Its definitions and its expectation were
    committed before it existed (commit 211c50e, the S3.1 plan's entry "A finding-consistency
    probe, with its definitions committed first"). ``make s3-finding-consistency`` writes its
    output to ``docs/results/s3-finding-consistency-dev.txt``.

Why
    The coding-consistency probe found that cases whose probable-cause sentences are identical
    word for word share their first occurrence code only about a third of the time. Andy asked
    whether the finding codes the NTSB flagged as in the cause (``inProbableCause``) are more
    consistent with that sentence. If they are, a coder reading the sentence has more to go on
    for findings than for the first occurrence code. This measures it, descriptively. It does not
    say the NTSB was inconsistent: the same sentence can follow accidents whose findings differ.

What it measures
    Cases and groups: exactly the coding-consistency probe's. The S3 statistics pool as
    ``scripts/exploratory/s3_precedent_probe.py`` reads it (``read_pool_texts``, guarded by
    ``check_pool`` before any text or finding is read), each case with a probable-cause text and
    at least one occurrence code; its exact-twin and loose-twin groups (``s3_coding_consistency``'s
    ``analyse``), over all years and with the groups formed again inside 2009-2014 and inside
    2015-2019. Group membership does not depend on findings.

    A case's findings: those flagged as cause (``fields.finding_codes_in_cause``), as a set. A
    *scored* case is a group member with at least one. A member with none is still another
    member's twin (its empty set is a candidate for "the commonest set among the others") but is
    not scored; the cases in groups, the scored and the unscored are printed.

    The predicted set (headline): for a scored case, the commonest flagged-finding set among the
    other members of its group, a set compared whole, ties to the smallest sorted tuple of codes
    (so the empty set, whose tuple is smallest, wins a tie, and then the case has no prediction).
    Measures over the scored cases, for each grouping and era: the mean precision and recall of
    the predicted set against the case's own flagged set at 10, 8 and 6 digits, as
    ``scoring.metrics._precision_recall`` counts them (a precision of None, an empty predicted
    set, is left out of the precision mean and counted); a 95% interval for each mean from the
    project's ``mean_cell``; the share whose own set equals the predicted set whole (Wilson); and,
    beside the occurrence probe, which takes its commonest value at each level, the share whose
    own set holds a code that starts with the commonest flagged value among the other members',
    found at each of 10, 8 and 6 digits separately (the codes cut to that many digits, each other
    member counting each distinct value once, ties to the smallest value as a string at that
    level), so the commonest 8-digit item need not be the item of the commonest 10-digit code.

    The control (no twins): the same measures over the same scored cases, with the predicted set
    the commonest non-empty flagged-finding set of the era's whole pool less the case itself, and
    the commonest value at each level taken from the era's pool less the case itself, each pool
    case counting each distinct value once.

    The expectation is printed verbatim with the headline (exact twins, all years, mean recall
    at 10 digits), whether it was met, and the occurrence probe's figure read from its results
    file at run time. For exact twins, all years, the ten flagged findings that most often appear
    in some members of a group but not in others. Counts, means and code labels only: no case
    number and no text from any record.

Refusals
    The occurrence probe's results file or its headline line missing, before anything is read.
    The pool through ``check_pool``: a sample case or a non-development case raises
    ``LeakageError`` before any text or finding is read.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.exploratory.s3_finding_consistency [--out PATH]

    Prints the report; with ``--out`` also writes it (and a newline) to PATH. The report holds no
    time and no path, so it can be recomputed byte for byte.
"""

import argparse
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Final, NoReturn

from scripts.coding_stats import STAGES
from scripts.exploratory import s3_coding_consistency as cc
from scripts.exploratory import s3_precedent_probe as pp
from scripts.exploratory.s3_coding_consistency import (
    ALL_YEARS,
    ERAS,
    GROUPING_TITLE,
    GROUPINGS,
    Era,
    Group,
    Grouping,
)
from scripts.exploratory.s3_precedent_probe import PoolText, share, with_interval
from scripts.s3_trail_pages import REPOSITORY

from ntsb_probable_cause.scoring.codes import CodeTables, load_tables

# Private by name; used as it is, never re-implemented, so the counts are the scoring's own.
from ntsb_probable_cause.scoring.metrics import _precision_recall
from ntsb_probable_cause.scoring.report import mean_cell
from ntsb_probable_cause.settings import Settings

type Codes = tuple[str, ...]  # a flagged-finding set: sorted, no repeat; compared whole

DIGITS: Final = (10, 8, 6)
TOP_FINDINGS: Final = 10
OCCURRENCE_RESULTS: Final = Path("docs/results/s3-coding-consistency-dev.txt")
_HEADLINE_START: Final = (
    "Headline: exact twins, all years, leave-one-out agreement on the six-digit first code: "
)
_PERCENT: Final = r"\d+(?:\.\d+)?%"
_FIGURE: Final = re.compile(
    rf"^{re.escape(_HEADLINE_START)}(?P<figure>\d+ of \d+ \({_PERCENT}\) \[{_PERCENT}, {_PERCENT}\])$",
    re.MULTILINE,
)
_UNKNOWN: Final = "not in the code tables"

# The committed expectation (plan entry "A finding-consistency probe", commit 211c50e).
ABOVE: Final = Fraction(1, 2)
EXPECTATION: Final = (
    "Expectation (decides nothing). Findings are more consistent than first codes: among exact "
    "twins, all years, the mean recall of the predicted set at 10 digits is above 50%, against "
    "the occurrence probe's 37.5%."
)


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_finding_consistency: {message}")


# --- the occurrence probe's figure ---


def occurrence_figure(results: Path) -> str:
    """The occurrence probe's headline as printed in its results file, read now.

    Args:
        results: the coding-consistency probe's results file.

    Returns:
        The count, the share and the interval, for example ``619 of 1650 (37.5%) [35.2%, 39.9%]``.

    Raises:
        SystemExit: the file is missing, or holds no headline line.
    """
    if not results.is_file():
        _refuse(f"{results} is missing; the occurrence probe's headline is read from it")
    match = _FIGURE.search(results.read_text(encoding="utf-8"))
    if match is None:
        _refuse(f"{results} holds no line starting {_HEADLINE_START!r}")
    return match.group("figure")


# --- the predictors ---


def flagged(case: PoolText) -> Codes:
    """A case's flagged-as-cause findings as a set: sorted, no repeat."""
    return tuple(sorted(set(case.findings)))


def commonest_set(counts: Mapping[Codes, int]) -> Codes | None:
    """The set with the highest count, ties to the smallest sorted tuple; None if no counts.

    The empty set's tuple is the smallest, so it wins a tie.
    """
    return min(counts, key=lambda s: (-counts[s], s)) if counts else None


def _positive[K](counts: Mapping[K, int]) -> dict[K, int]:
    return {key: n for key, n in counts.items() if n > 0}


def twin_sets(sets: Sequence[Codes]) -> dict[Codes, Codes]:
    """For each distinct set in one group, the commonest set among the other members.

    Args:
        sets: each member's flagged set, the empty set of a member with none included.

    Returns:
        Each distinct own set to the commonest set among the other members (ties to the
        smallest sorted tuple); a group of one has no other member and gets the empty set.
    """
    counts = Counter(sets)
    out: dict[Codes, Codes] = {}
    for own in counts:
        others = Counter(counts)  # this set's count less the case itself
        others[own] -= 1
        winner = commonest_set(_positive(others))
        out[own] = () if winner is None else winner
    return out


type Singles = Mapping[int, str | None]  # by digits: the commonest value at that level


def _cut(codes: Codes, digits: int) -> set[str]:
    """The distinct values of a flagged set at one level: its codes cut to ``digits`` digits."""
    return {code[:digits] for code in codes}


def twin_singles(sets: Sequence[Codes]) -> dict[Codes, dict[int, str | None]]:
    """For each distinct set in one group, the commonest flagged value among the others, by level.

    At each of 10, 8 and 6 digits separately, as the occurrence probe takes its commonest value
    at each level: the codes cut to that many digits, each other member counting each distinct
    value once. The commonest 8-digit item need not be the item of the commonest 10-digit code.

    Args:
        sets: each member's flagged set.

    Returns:
        Each distinct own set to, for each of ``DIGITS``, the value held by most of the other
        members (ties to the smallest value as a string at that level); None where no other
        member holds one.
    """
    out: dict[Codes, dict[int, str | None]] = {own: {} for own in set(sets)}
    for digits in DIGITS:
        held = Counter(value for own in sets for value in _cut(own, digits))
        for own, found in out.items():
            others = Counter(held)
            others.subtract(_cut(own, digits))  # the case itself holds each of its values once
            found[digits] = cc.commonest(_positive(others))
    return out


class Control:
    """The era's pool as a predictor that ignores twins, less the case itself each time."""

    def __init__(self, cases: Sequence[PoolText]) -> None:
        """Count the era's non-empty flagged sets, and its values at each level.

        Args:
            cases: the era's pool cases.
        """
        sets = [own for case in cases if (own := flagged(case))]
        self._sets = Counter(sets)
        self._values = {
            digits: Counter(value for own in sets for value in _cut(own, digits))
            for digits in DIGITS
        }
        self._best_set = commonest_set(self._sets)
        self._best_value = {digits: cc.commonest(self._values[digits]) for digits in DIGITS}
        self._without_best_set: Codes | None = None
        self._single_without: dict[tuple[Codes, int], str | None] = {}

    def predicted(self, own: Codes) -> Codes:
        """The commonest non-empty set of the pool less this case; empty if there is none."""
        if own != self._best_set:  # taking a case away only lowers the count of its own set
            return () if self._best_set is None else self._best_set
        if self._without_best_set is None:
            others = Counter(self._sets)
            others[own] -= 1
            self._without_best_set = commonest_set(_positive(others)) or ()
        return self._without_best_set

    def single(self, own: Codes) -> Singles:
        """The commonest flagged value of the pool less this case, at each level.

        Each pool case counts each distinct value once; ties to the smallest value as a string
        at that level; None where the pool holds no value.
        """
        return {digits: self._single(own, digits) for digits in DIGITS}

    def _single(self, own: Codes, digits: int) -> str | None:
        best = self._best_value[digits]
        mine = _cut(own, digits)
        if best not in mine:  # only a case's own values lose a count
            return best
        if (own, digits) not in self._single_without:
            others = Counter(self._values[digits])
            others.subtract(mine)
            self._single_without[(own, digits)] = cc.commonest(_positive(others))
        return self._single_without[(own, digits)]


# --- the measures ---


@dataclass(frozen=True)
class Outcome:
    """One scored case against one predicted set: precision, recall, equality, single finding."""

    precision: Mapping[int, float | None]  # by digits; None when the predicted set is empty
    recall: Mapping[int, float]
    whole: bool
    single: Mapping[int, bool]  # own set holds a code starting with the level's commonest value


def outcome(predicted: Codes, own: Codes, single: Singles) -> Outcome:
    """Score a predicted set and the commonest flagged values against one case's own flagged set.

    Args:
        predicted: the predicted set (empty: no prediction).
        own: the case's own flagged set; not empty, since only scored cases are scored.
        single: for each of ``DIGITS``, the commonest flagged value at that level (None: none).

    Returns:
        The case's precision and recall at each of ``DIGITS`` (``_precision_recall``), whether
        the sets are equal whole, and whether the own set holds a code whose first 10, 8 or 6
        digits equal that level's commonest value.

    Raises:
        ValueError: ``own`` is empty.
    """
    precision: dict[int, float | None] = {}
    recall: dict[int, float] = {}
    for digits in DIGITS:
        p, r = _precision_recall(predicted, own, digits)
        if r is None:
            raise ValueError("a scored case holds at least one flagged finding")
        precision[digits], recall[digits] = p, r
    held = {digits: single[digits] in _cut(own, digits) for digits in DIGITS}
    return Outcome(precision, recall, predicted == own, held)


@dataclass(frozen=True)
class Measures:
    """The measures over one set of scored cases."""

    scored: int
    recall: Mapping[int, tuple[float, ...]]
    precision: Mapping[int, tuple[float, ...]]  # the cases with a prediction only
    no_prediction: int
    whole: int
    single: Mapping[int, int]


def summarise(outcomes: Sequence[Outcome]) -> Measures:
    """Every count and list the report prints, from the scored cases' outcomes."""
    first = DIGITS[0]
    return Measures(
        scored=len(outcomes),
        recall={d: tuple(o.recall[d] for o in outcomes) for d in DIGITS},
        precision={
            d: tuple(p for o in outcomes if (p := o.precision[d]) is not None) for d in DIGITS
        },
        no_prediction=sum(o.precision[first] is None for o in outcomes),
        whole=sum(o.whole for o in outcomes),
        single={d: sum(o.single[d] for o in outcomes) for d in DIGITS},
    )


def twin_outcomes(group: Group) -> list[Outcome]:
    """The scored members of one group against the commonest set among the other members."""
    sets = [flagged(case) for case in group]
    predicted, singles = twin_sets(sets), twin_singles(sets)
    return [outcome(predicted[own], own, singles[own]) for own in sets if own]


def control_outcomes(group: Group, control: Control) -> list[Outcome]:
    """The same scored members against the era's pool less the case itself."""
    return [
        outcome(control.predicted(own), own, control.single(own))
        for own in map(flagged, group)
        if own
    ]


def exact_mean(values: Sequence[float]) -> Fraction:
    """The mean of recall values as an exact fraction.

    Each value is a count over a count, so it is recovered as that fraction; the expectation
    asks whether the mean is strictly above one half, and a float sum cannot say at the edge.
    """
    total = sum((Fraction(v).limit_denominator(10_000) for v in values), Fraction(0))
    return total / len(values)


def meets_expectation(recalls: Sequence[float]) -> bool:
    """Whether the mean recall is strictly above one half; false with no case."""
    return bool(recalls) and exact_mean(recalls) > ABOVE


@dataclass(frozen=True)
class Block:
    """One grouping in one era: its groups, cases, scored cases, and both predictors' measures."""

    groups: int
    cases: int  # in groups
    scored: int
    pool: int  # the era's pool cases
    twins: Measures
    control: Measures


@dataclass(frozen=True)
class Found:
    """One grouping in one era: its groups and its block."""

    groups: tuple[Group, ...]
    block: Block


def analyse(cases: Sequence[PoolText]) -> dict[tuple[Grouping, str], Found]:
    """Both predictors' measures for each grouping within each era.

    Args:
        cases: the pool cases that have a text and a first code, with their flagged findings.

    Returns:
        Each (grouping, era name) to its groups (as the coding-consistency probe forms them)
        and block. The control's pool is the era's cases; the scored cases are the same.
    """
    formed = cc.analyse(cases)
    out: dict[tuple[Grouping, str], Found] = {}
    for era in ERAS:
        inside = [case for case in cases if era.holds(case.event_date.year)]
        control = Control(inside)
        for grouping in GROUPINGS:
            groups = formed[(grouping, era.name)].groups
            twins = [o for group in groups for o in twin_outcomes(group)]
            controls = [o for group in groups for o in control_outcomes(group, control)]
            block = Block(
                groups=len(groups),
                cases=sum(len(group) for group in groups),
                scored=len(twins),
                pool=len(inside),
                twins=summarise(twins),
                control=summarise(controls),
            )
            out[(grouping, era.name)] = Found(groups, block)
    return out


def differing(groups: Sequence[Group]) -> list[tuple[str, int]]:
    """Flagged findings by the groups where some members hold them and some do not.

    Members with no flagged finding count as members that do not hold it.

    Args:
        groups: the groups.

    Returns:
        ``(code, groups)``, the most groups first, ties by code.
    """
    totals: Counter[str] = Counter()
    for group in groups:
        sets = [set(case.findings) for case in group]
        held: set[str] = set().union(*sets)
        everywhere = sets[0].intersection(*sets[1:])
        totals.update(held - everywhere)
    return sorted(totals.items(), key=lambda item: (-item[1], item[0]))


# --- the lines ---


def finding_label(tables: CodeTables, code: str) -> str:
    """``item / modifier`` for a ten-digit finding code, or a note for what is not in the tables."""
    item = tables.items.get(code[:8], _UNKNOWN)
    modifier = tables.modifiers.get(code[8:], _UNKNOWN)
    return f"{item} / {modifier}"


def _groups(n: int) -> str:
    return f"{n} group" if n == 1 else f"{n} groups"


def _mean(values: Sequence[float]) -> str:
    cell = mean_cell(values)
    return f"{cell.value:.1%} [{cell.low:.1%}, {cell.high:.1%}]"


def expectation_lines(found: Block, cited: str) -> list[str]:
    """The expectation verbatim, the headline, whether it is met, and the occurrence figure.

    Args:
        found: exact twins, all years.
        cited: the occurrence probe's headline, read from its results file.

    Returns:
        The lines. With no scored exact-twin case there is no headline and nothing is tested.
    """
    recalls = found.twins.recall[DIGITS[0]]
    lines = ["## The expectation (committed in 211c50e, before this script existed)", "", EXPECTATION]
    if recalls:
        lines.append(
            "Headline: exact twins, all years, mean recall at 10 digits of the predicted set: "
            f"{_mean(recalls)} over {len(recalls)} scored cases"
        )
        lines.append("expectation met" if meets_expectation(recalls) else "expectation not met")
    else:
        lines += [
            "Headline: exact twins, all years: no scored case",
            "expectation not tested: no scored exact-twin case",
        ]
    lines.append(
        f"The occurrence probe's figure, read from {OCCURRENCE_RESULTS.as_posix()}: "
        f"leave-one-out agreement on the six-digit first code among exact twins, all years, {cited}."
    )
    return lines


def measure_lines(heading: str, found: Measures) -> list[str]:
    """One predictor's measures over the scored cases.

    Args:
        heading: what the predicted set is.
        found: the measures.

    Returns:
        The lines.
    """
    lines = [heading]
    if not found.scored:
        return [*lines, "- no scored case"]
    n = found.scored
    for digits in DIGITS:
        lines.append(f"- mean recall at {digits} digits: {_mean(found.recall[digits])} (n = {n})")
    for digits in DIGITS:
        values = found.precision[digits]
        lines.append(
            f"- mean precision at {digits} digits: {_mean(values) if values else 'none'} "
            f"(n = {len(values)} cases with a prediction)"
        )
    lines.append(
        f"- no prediction: {found.no_prediction} of {n} scored cases (an empty predicted set; "
        "left out of the precision means, scored 0 in the recall means)"
    )
    lines.append(f"- own flagged set equals the predicted set whole: {with_interval(found.whole, n)}")
    lines.append(
        "- like-for-like with the occurrence probe: own flagged set holds a code that starts with "
        "the commonest flagged value among the others, found at each digit count"
    )
    lines += [
        f"  - at {digits} digits: {with_interval(found.single[digits], n)}" for digits in DIGITS
    ]
    return lines


def block_lines(grouping: Grouping, era: Era, found: Block) -> list[str]:
    """One grouping in one era: its cases and both predictors' measures.

    Args:
        grouping: ``exact`` or ``loose``.
        era: the era the groups were formed within.
        found: its block.

    Returns:
        The lines.
    """
    span = (
        ""
        if era.first is None
        else f" (groups formed among cases with event years {era.first} to {era.last} only)"
    )
    return [
        f"### {GROUPING_TITLE[grouping]}, {era.name}{span}",
        f"groups: {found.groups}; cases in groups: {share(found.cases, found.pool)} of the era's "
        "pool cases",
        f"scored cases (at least one flagged finding): {found.scored}; unscored cases (none): "
        f"{found.cases - found.scored}",
        *measure_lines(
            "twins: the predicted set is the commonest flagged-finding set among the other "
            "members of the case's group",
            found.twins,
        ),
        *measure_lines(
            "control (no twins): the predicted set is the commonest non-empty flagged-finding "
            "set of the era's whole pool less the case itself",
            found.control,
        ),
    ]


def differing_lines(groups: Sequence[Group], tables: CodeTables) -> list[str]:
    """The ten flagged findings most often held by some members of a group and not by others.

    Args:
        groups: the exact-twin groups, all years.
        tables: the code tables, for labels.

    Returns:
        The lines: codes, labels and group counts only.
    """
    codes = differing(groups)
    lines = [
        f"## exact twins, all years: the {TOP_FINDINGS} flagged findings that most often differ "
        "within a group",
        "",
        "Each line is a ten-digit finding code and the number of groups in which at least one "
        "member has it flagged as cause and at least one other member does not (a member with no "
        f"flagged finding does not); {len(codes)} codes differ in at least one of "
        f"{_groups(len(groups))}.",
    ]
    if not codes:
        return [*lines, "none: no flagged finding differs within a group"]
    for rank, (code, n) in enumerate(codes[:TOP_FINDINGS], start=1):
        lines.append(f"{rank}. {code} {finding_label(tables, code)}: {_groups(n)}")
    return lines


def method_lines(cases: Sequence[PoolText], pool: Mapping[str, int]) -> list[str]:
    """How the pool was built, the groups formed, and each measure counted.

    Args:
        cases: the kept pool cases.
        pool: the pool's counts (``statistics pool``, ``no text``, ``no code``).

    Returns:
        The lines.
    """
    years = sorted({case.event_date.year for case in cases})
    span = f"event years {years[0]}-{years[-1]}" if years else "no case"
    return [
        "## Method",
        "",
        f"Pool: the S3 statistics pool, {STAGES[pp.STAGE].built_from}: "
        f"{pool['statistics pool']} cases; kept, each with an NTSB probable-cause text and at "
        f"least one occurrence code: {len(cases)} ({span}); left out: {pool['no text']} with no "
        f"probable-cause text, {pool['no code']} more with no occurrence code.",
        "Groups: exactly the coding-consistency probe's (its own grouping functions). Exact "
        "twins: the same tokens in the same order, a token being a run of [a-z0-9] in the "
        "lower-cased text. Loose twins: the same set of those tokens less the precedent probe's "
        f"{len(pp.STOP_WORDS)} stop words. A group is two or more cases with the same non-empty "
        "key. Eras: all years; 2009–2014 and 2015–2019, the groups formed again among the cases "
        "with an event year in the era. Group membership does not depend on findings.",
        "Findings: those the NTSB flagged as in the probable cause (inProbableCause), as a set "
        "of ten-digit codes; the same findings the scoring's flagged recall reads. A scored case "
        "is a group member with at least one. A member with none is another member's twin, and "
        "its empty set is a candidate for the commonest set among the others, but it is not "
        "scored; the cases in groups, the scored and the unscored are printed for each grouping "
        "and era.",
        "Predicted set (twins): the commonest flagged-finding set among the other members of "
        "the case's group, a set compared whole. Ties go to the smallest tuple of the set's "
        "sorted codes, so the empty set, whose tuple () is the smallest, wins a tie. Then the "
        "case has no prediction: its recall is 0 and its precision is left out of the precision "
        "mean (counted as 'no prediction').",
        "Control (no twins): the same scored cases, the predicted set the commonest non-empty "
        "flagged-finding set of the era's whole pool (every kept case with a year in the era, "
        "twin or not) less the case itself, ties as above. It shows how much of the result a "
        "common set gives for nothing; the twins' number is read against it.",
        "Precision and recall: ``scoring.metrics._precision_recall`` itself, on the predicted "
        "set and the case's own flagged set, with each code cut to its first 10, 8 or 6 digits "
        "(the finding, its item, its category) and the two cut sets compared. Recall is the "
        "share of the case's own flagged codes the predicted set holds; precision is the share "
        "of the predicted set's codes the case holds. A larger predicted set raises recall and "
        "lowers precision, so both are printed. Each mean is over the scored cases, with the "
        "number behind it.",
        "Equal whole: the predicted set equals the case's own flagged set, ten digits, nothing "
        "more and nothing less.",
        "Like-for-like with the occurrence probe, which takes its commonest value at each level: "
        "at each of 10, 8 and 6 digits separately, the commonest value among the other members "
        "(the flagged codes cut to that many digits, each other member counting each distinct "
        "value once; for the control, each other pool case once; ties to the smallest value as "
        "a string at that level), then whether the case's own flagged set holds a code whose "
        "first 10, 8 or 6 digits equal that level's commonest value. The commonest 8-digit item "
        "need not be the item of the commonest 10-digit code.",
        "Intervals: the means have the project's bootstrap interval (``mean_cell``: 2,000 "
        "resamples over cases, a fixed seed); the shares have a 95% Wilson interval. Both treat "
        "cases as independent, although cases of one group share a sentence and each case's "
        "prediction is made from the others, so the intervals are narrower than the data "
        "warrant.",
        "The expectation is decided on the exact mean (a fraction), not on the printed "
        "rounding: a mean that prints as 50.0% can be above one half.",
        "What it does not say: that the NTSB was inconsistent. The same sentence can follow "
        "accidents whose findings differ; it bounds what a coder reading only the sentence "
        "could score on findings.",
    ]


def report(
    found: Mapping[tuple[Grouping, str], Found],
    cases: Sequence[PoolText],
    pool: Mapping[str, int],
    tables: CodeTables,
    cited: str,
) -> str:
    """The whole report: head, expectation, method, each grouping and era, the differing findings.

    Args:
        found: each grouping's groups and block in each era (``analyse``).
        cases: the kept pool cases.
        pool: the pool's counts.
        tables: the code tables, for labels.
        cited: the occurrence probe's headline, read from its results file.

    Returns:
        The report's text.
    """
    head = "\n".join(
        [
            "S3.1 finding-consistency probe on the development pool "
            "(scripts/exploratory/s3_finding_consistency.py; S3.1 Task 15)",
            "Exploratory (decision 0059): free and offline, no model call; it decides nothing. "
            "How far the NTSB's own probable-cause sentence settles the findings it flagged as "
            "cause: for cases whose sentences match word for word (exact twins), or in their "
            "words less common function words (loose twins), the commonest flagged-finding set "
            "among the other members is scored against the case's own, beside a control that "
            "ignores twins.",
            "Counts, means and code labels only: no case number and no text from any record. "
            "Means with a bootstrap 95% interval, shares with a 95% Wilson interval, each with "
            "its denominator.",
        ]
    )
    exact_all = found[("exact", ALL_YEARS.name)]
    blocks = [
        head,
        "\n".join(expectation_lines(exact_all.block, cited)),
        "\n".join(method_lines(cases, pool)),
    ]
    for grouping in GROUPINGS:
        blocks.append(f"## {GROUPING_TITLE[grouping]}")
        blocks += [
            "\n".join(block_lines(grouping, era, found[(grouping, era.name)].block))
            for era in ERAS
        ]
    blocks.append("\n".join(differing_lines(exact_all.groups, tables)))
    return "\n\n".join(blocks)


# --- the command ---


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_finding_consistency")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, results: Path | None = None) -> int:
    """Print, and with ``--out`` also write, the counts.

    Args:
        argv: the command line.
        results: the coding-consistency probe's results file; default the committed one.

    Returns:
        0.
    """
    args = _arguments(argv)
    cited = occurrence_figure(results if results is not None else REPOSITORY / OCCURRENCE_RESULTS)
    cases, _dates, counts = pp.read_pool_texts(Settings().data_dir / "processed")
    tables = load_tables()
    text = report(analyse(cases), cases, counts, tables, cited)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
