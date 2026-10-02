"""Whether the findings of the earlier cases nearest to the loop's cause sentence beat its own.

Status
    Exploratory (decision 0059), S3.1 Task 15, free and offline: no model call, no network. It
    sets no bar and tunes nothing. Its rule was committed before it existed (commit 1c44b9d, the
    S3.1 plan's entry "A findings-from-precedent probe, with its rule committed first"), and it
    applies that rule and prints the word at the top. ``make s3-finding-precedent`` writes its
    output to ``docs/results/s3-finding-precedent-dev.txt``.

Why
    The finding-consistency probe found that NTSB cases with identical cause sentences share most
    of their flagged findings (a mean 74.1% at 10 digits, against 37.5% agreement on first
    occurrence codes), and the loop leads a plain arm B on flagged-finding recall. The precedent
    probe set precedent search aside for occurrence codes: the cause sentence carries the
    findings, not the phase. This asks the findings question directly. If the loop looked up the
    earlier cases whose cause sentences are nearest to the sentence it wrote, would their
    flagged findings beat the findings it chose? A promising result starts the design of a
    findings tool the loop may call. It does not build one.

What it measures
    Judged cases, for each run: the ``dev-400`` cases that were scored (not counted as failed,
    decision 0136 item 1), whose final answer did not abstain, and whose NTSB verdict flags at
    least one finding as cause. Every case of the run is counted once, in that order, as failed,
    abstained, with no flagged finding, or judged. Queries: the final answer's probable cause (the
    headline) and, beside it, its evidence narrative. Search: exactly the precedent probe's
    headline variant (``s3_precedent_probe``: the S3 statistics pool, BM25 over the pool cases
    strictly earlier than the judged case, ties by case id, the five highest-ranked). Three
    predictors turn the five cases' flagged-finding sets into one set: the commonest non-empty
    set (headline), the nearest case's non-empty set, and the findings flagged in two or more of
    the five. Each is scored against the case's own flagged findings at 10, 8 and 6 digits by
    ``scoring.metrics._precision_recall``, beside the loop's own scores as the harness stored
    them, and as a paired difference, predictor less loop, with bootstrap intervals. Counts and
    means only: no case number, no finding code and no text from any record.

Refusals
    The runs through ``s3_precedent_probe.load_run``: a held-out run id; a folder with no
    ``run.jsonl``, or whose record names another run; any sample but ``dev-400`` (held-out, open
    and the sealed samples); a run that has not finished; a case outside the development split; a
    run that is not exactly ``dev-400``'s cases (a ``--limit`` run); any arm but C. Then a run
    named twice. The pool through ``check_pool``: a sample case or a non-development case raises
    ``LeakageError`` before any pool text or finding is read. Then a judged case with no event
    date in the processed file, and a judged case whose stored scores hold no finding recall
    although its verdict flags a finding.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.exploratory.s3_finding_precedent \
        --runs RUN_A RUN_B [--out PATH]

    Prints the report; with ``--out`` also writes it (and a newline) to PATH. The report holds no
    time and no path, so it can be recomputed byte for byte.
"""

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Literal, NoReturn

from scripts.coding_stats import STAGES
from scripts.exploratory import s3_precedent_probe as pp
from scripts.exploratory.s3_precedent_probe import QUERIES, Index, Query
from scripts.miss_kinds import scored_answer
from scripts.s3_case_groups import Run

# _precision_recall is private by name; used as it is, never re-implemented, so the counts are
# the scoring's own.
from ntsb_probable_cause.scoring.metrics import CaseScores, _precision_recall
from ntsb_probable_cause.scoring.records import CaseResult
from ntsb_probable_cause.scoring.report import Cell, mean_cell
from ntsb_probable_cause.settings import Settings

type Flagged = frozenset[str]  # a case's flagged-as-cause finding codes, ten digits each
type Predictor = Literal["commonest set", "nearest", "at least two"]
type Word = Literal["promising", "mixed", "not promising"]

DIGITS: Final = (10, 8, 6)
TWICE: Final = 2
HEADLINE_QUERY: Final[Query] = "probable cause"
HEADLINE_PREDICTOR: Final[Predictor] = "commonest set"
RULE_COMMIT: Final = "1c44b9d"

# The committed rule (plan entry "A findings-from-precedent probe, with its rule committed
# first", commit 1c44b9d), word for word less the entry's bold marks.
RULE: Final = (
    "Rule (Andy, 2026-10-02). Read on run a, the probable-cause query, the headline predictor: "
    "promising if the paired difference in mean recall at 10 digits has its interval above zero "
    "and the paired difference in mean precision at 10 digits does not have its interval below "
    "zero; mixed if the recall difference's interval is above zero and the precision "
    "difference's interval is below zero; not promising otherwise. The script applies the rule "
    "and prints the word. Either result is published as it stands; a promising result starts a "
    "round's design (a findings tool the loop may call), not a tool."
)
EXPECTATION: Final = "Expectation (decides nothing). Promising."

PREDICTOR_MEANINGS: Final[Mapping[Predictor, str]] = {
    "commonest set": (
        "among the five, the commonest non-empty flagged set (a set compared whole); a tie goes "
        "to the set whose first holder is ranked highest; none if all five are empty"
    ),
    "nearest": (
        "the flagged set of the highest-ranked of the five whose set is not empty; none if all "
        "five are empty"
    ),
    "at least two": (
        "the codes flagged in two or more of the five (each case counts a code once); none if no "
        "code is"
    ),
}


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_finding_precedent: {message}")


# --- the predictors ---


def commonest_set(five: Sequence[Flagged]) -> Flagged | None:
    """The commonest non-empty flagged set among the five; a tie goes to its first holder.

    Args:
        five: the five nearest cases' flagged sets, best-ranked first (maybe fewer than five).

    Returns:
        The set held by most of the five, an empty set never counting; among the sets held by
        equally many, the one whose first holder is ranked highest. None if every set is empty.
    """
    counts = Counter(found for found in five if found)
    if not counts:
        return None
    most = max(counts.values())
    return next(found for found in five if found and counts[found] == most)


def nearest(five: Sequence[Flagged]) -> Flagged | None:
    """The flagged set of the highest-ranked of the five whose set is not empty; else None."""
    return next((found for found in five if found), None)


def at_least_two(five: Sequence[Flagged]) -> Flagged | None:
    """The codes flagged in two or more of the five; None if no code is."""
    held = Counter(code for found in five for code in found)
    codes = frozenset(code for code, count in held.items() if count >= TWICE)
    return codes or None


PREDICTORS: Final[tuple[tuple[Predictor, Callable[[Sequence[Flagged]], Flagged | None]], ...]] = (
    ("commonest set", commonest_set),
    ("nearest", nearest),
    ("at least two", at_least_two),
)


# --- the judged cases ---


@dataclass(frozen=True)
class Judged:
    """One judged case: the run's case, the NTSB's flagged findings, the loop's stored scores."""

    case: CaseResult
    recall: Mapping[int, float]  # the loop's, by digits, as the harness stored them
    precision: Mapping[int, float | None]  # None when the loop named no finding

    @property
    def case_id(self) -> str:
        """The case's id."""
        return self.case.case_id

    @property
    def own(self) -> tuple[str, ...]:
        """The NTSB's findings flagged as in the probable cause."""
        return self.case.verdict_findings_in_cause


@dataclass(frozen=True)
class CaseSplit:
    """A run's cases, each counted once: failed, abstained, no flagged finding, or judged."""

    total: int
    failed: int
    abstained: int
    no_flagged: int
    judged: tuple[Judged, ...]


def _stored(case: CaseResult, scores: CaseScores) -> Judged:
    """A judged case with the loop's own recall and precision, read from its stored scores."""
    recall = {10: scores.finding_recall_10, 8: scores.finding_recall_8, 6: scores.finding_recall_6}
    if any(value is None for value in recall.values()):
        _refuse(
            "a judged case's stored scores hold no finding recall, although the NTSB's verdict "
            "flags a finding as cause"
        )
    precision = {
        10: scores.finding_precision_10,
        8: scores.finding_precision_8,
        6: scores.finding_precision_6,
    }
    return Judged(
        case,
        {digits: value for digits, value in recall.items() if value is not None},
        precision,
    )


def sort_cases(cases: Sequence[CaseResult]) -> CaseSplit:
    """Count every case once, in this order, and keep the judged ones.

    A case counted as failed (``miss_kinds.scored_answer``, decision 0136 item 1) is failed,
    whatever else holds of it. Of the rest, one whose final answer abstained is abstained, and one
    whose NTSB verdict flags no finding as cause has no flagged finding. What is left is judged.

    Args:
        cases: one run's cases.

    Returns:
        The counts and the judged cases.
    """
    failed = abstained = no_flagged = 0
    judged: list[Judged] = []
    for case in cases:
        answer = scored_answer(case)
        if answer is None or case.scores is None:
            failed += 1
        elif answer.abstain:
            abstained += 1
        elif not case.verdict_findings_in_cause:
            no_flagged += 1
        else:
            judged.append(_stored(case, case.scores))
    return CaseSplit(len(cases), failed, abstained, no_flagged, tuple(judged))


# --- scoring a predictor ---


@dataclass(frozen=True)
class Scored:
    """One judged case against one predictor's set."""

    recall: Mapping[int, float]  # by digits; 0 when the predictor gave no set
    precision: Mapping[int, float | None]  # by digits; None when the predictor gave no set


def score(predicted: Flagged | None, own: Sequence[str]) -> Scored:
    """A predicted set against a case's own flagged findings at each of 10, 8 and 6 digits.

    ``scoring.metrics._precision_recall`` itself: no set (None) is an empty one, so its recall is
    0 and its precision is None, which the means leave out.

    Args:
        predicted: the predictor's set, or None for none.
        own: the case's own flagged findings; not empty.

    Returns:
        Recall and precision by digits.

    Raises:
        ValueError: ``own`` is empty.
    """
    codes = sorted(predicted) if predicted else []
    recall: dict[int, float] = {}
    precision: dict[int, float | None] = {}
    for digits in DIGITS:
        found_precision, found_recall = _precision_recall(codes, own, digits)
        if found_recall is None:
            raise ValueError("a judged case holds at least one flagged finding")
        precision[digits], recall[digits] = found_precision, found_recall
    return Scored(recall, precision)


def five_sets(
    index: Index, flags: Mapping[str, Flagged], judged: Judged, day: date, query: Query
) -> tuple[Flagged, ...]:
    """The flagged sets of the five nearest earlier cases, best first.

    The precedent probe's headline search: BM25 over the pool cases strictly earlier than ``day``.

    Args:
        index: the pool, indexed.
        flags: each pool case's flagged findings, by case id.
        judged: the judged case.
        day: the judged case's event date.
        query: which of the final answer's two texts is the query.

    Returns:
        Up to five sets, in rank order; none if no earlier case shares a word with the query.

    Raises:
        ValueError: the case has no answer, which a judged case always has.
    """
    text = pp.query_text(judged.case, query)
    if text is None:
        raise ValueError("a judged case has a final answer")
    return tuple(flags[p.case_id] for p in index.search(pp.tokens(text), day, "earlier"))


type Key = tuple[Query, Predictor]


@dataclass(frozen=True)
class RunResult:
    """One run: its id, its case counts, and every predictor's scores on every judged case."""

    run_id: str
    split: CaseSplit
    scored: Mapping[Key, Mapping[str, Scored]]  # by (query, predictor), then case id


def analyse(
    run_id: str,
    split: CaseSplit,
    *,
    index: Index,
    flags: Mapping[str, Flagged],
    days: Mapping[str, date],
) -> RunResult:
    """Search once per judged case and query, then apply and score each predictor.

    Args:
        run_id: the run's id.
        split: its cases, sorted.
        index: the pool, indexed.
        flags: each pool case's flagged findings, by case id.
        days: each judged case's event date.

    Returns:
        The run's scores.
    """
    scored: dict[Key, dict[str, Scored]] = {}
    for query in QUERIES:
        for judged in split.judged:
            five = five_sets(index, flags, judged, days[judged.case_id], query)
            for name, predict in PREDICTORS:
                scored.setdefault((query, name), {})[judged.case_id] = score(
                    predict(five), judged.own
                )
    return RunResult(run_id, split, scored)


# --- the comparison ---


@dataclass(frozen=True)
class Comparison:
    """One predictor against the loop over one set of judged cases."""

    n: int
    recall: Mapping[int, Cell]  # the predictor's mean recall, over all n
    precision: Mapping[int, Cell]  # its mean precision, over the cases with a prediction
    no_prediction: int
    recall_diff: Mapping[int, Cell]  # predictor less loop, over all n
    precision_diff: Mapping[int, Cell]  # over the cases where both precisions are defined
    higher: int  # cases where the predictor's recall at 10 digits is above the loop's
    equal: int
    lower: int


def _paired(predictor: Sequence[float | None], loop: Sequence[float | None]) -> list[float]:
    """Predictor less loop on the cases where both are defined; the two are on the same cases."""
    return [p - q for p, q in zip(predictor, loop, strict=True) if p is not None and q is not None]


def compare(cases: Sequence[Judged], scored: Mapping[str, Scored]) -> Comparison:
    """A predictor's means, and its paired difference from the loop, over ``cases``.

    The paired difference is the mean of (predictor - loop) per case with its bootstrap interval:
    ``scoring.metrics.paired_difference``, which is typed for booleans, so as the project's own
    ``report.compare`` does for recall, ``mean_cell`` (``bootstrap_mean`` and the count) over the
    per-case differences. A precision is left out where it is None, on either side. The cases
    are taken in case-id order, as ``report.compare`` orders its pairs, so that every interval
    (the means and the differences) is what the report would print for the same pairs, whatever
    order the run holds its cases in: a bootstrap resamples by position.

    Args:
        cases: the judged cases of one set (all, fatal or non-fatal), in any order.
        scored: the predictor's scores, by case id.

    Returns:
        The means, the differences and the counts.
    """
    cases = sorted(cases, key=lambda judged: judged.case_id)
    mine = [scored[judged.case_id] for judged in cases]
    recall = {d: [s.recall[d] for s in mine] for d in DIGITS}
    loop_recall = {d: [j.recall[d] for j in cases] for d in DIGITS}
    precision = {d: [s.precision[d] for s in mine] for d in DIGITS}
    loop_precision = {d: [j.precision[d] for j in cases] for d in DIGITS}
    first = DIGITS[0]
    return Comparison(
        n=len(cases),
        recall={d: mean_cell(recall[d]) for d in DIGITS},
        precision={d: mean_cell([p for p in precision[d] if p is not None]) for d in DIGITS},
        no_prediction=sum(p is None for p in precision[first]),
        recall_diff={d: mean_cell(_paired(recall[d], loop_recall[d])) for d in DIGITS},
        precision_diff={d: mean_cell(_paired(precision[d], loop_precision[d])) for d in DIGITS},
        higher=sum(p > q for p, q in zip(recall[first], loop_recall[first], strict=True)),
        equal=sum(p == q for p, q in zip(recall[first], loop_recall[first], strict=True)),
        lower=sum(p < q for p, q in zip(recall[first], loop_recall[first], strict=True)),
    )


@dataclass(frozen=True)
class Own:
    """The loop's own scores over one set of judged cases, as the harness stored them."""

    n: int
    recall: Mapping[int, Cell]
    precision: Mapping[int, Cell]  # over the cases where the loop named a finding


def loop_own(cases: Sequence[Judged]) -> Own:
    """The loop's mean recall and precision at 10, 8 and 6 digits over ``cases``.

    The cases are taken in case-id order, as :func:`compare` takes them.
    """
    cases = sorted(cases, key=lambda judged: judged.case_id)
    return Own(
        n=len(cases),
        recall={d: mean_cell([j.recall[d] for j in cases]) for d in DIGITS},
        precision={
            d: mean_cell([p for j in cases if (p := j.precision[d]) is not None]) for d in DIGITS
        },
    )


def outcome(recall_low: float, precision_high: float | None) -> Word:
    """The committed rule's word from the two intervals' ends.

    Args:
        recall_low: the low end of the recall difference's interval at 10 digits.
        precision_high: the high end of the precision difference's interval at 10 digits; None if
            no case has both precisions, so there is no interval and none is below zero.

    Returns:
        ``promising`` if the recall interval is above zero (its low end is) and the precision
        interval is not below zero (its high end is not); ``mixed`` if the recall interval is
        above zero and the precision interval is below zero; ``not promising`` otherwise. A low
        end of exactly zero is not above zero; a high end of exactly zero is not below it.
    """
    if not recall_low > 0:
        return "not promising"
    if precision_high is not None and precision_high < 0:
        return "mixed"
    return "promising"


# --- the lines ---

SUBSETS: Final[tuple[tuple[str, Callable[[Judged], bool]], ...]] = (
    ("All judged cases", lambda judged: True),
    ("Fatal cases", lambda judged: judged.case.fatal),
    ("Non-fatal cases", lambda judged: not judged.case.fatal),
)


def _pct(cell: Cell) -> str:
    return f"{cell.value:.1%} [{cell.low:.1%}, {cell.high:.1%}]" if cell.n else "none"


def _signed(cell: Cell) -> str:
    return f"{cell.value:+.1%} [{cell.low:+.1%}, {cell.high:+.1%}]" if cell.n else "none"


def _fatal(judged: Sequence[Judged]) -> str:
    deaths = sum(j.case.fatal for j in judged)
    return f"({deaths} fatal, {len(judged) - deaths} non-fatal)"


def rule_lines(results: Sequence[RunResult]) -> list[str]:
    """The committed rule applied on run a, with run b's two differences beside it.

    Args:
        results: run a's and run b's results.

    Returns:
        The lines, ending with the word.
    """
    key = (HEADLINE_QUERY, HEADLINE_PREDICTOR)
    found = [compare(r.split.judged, r.scored[key]) for r in results]
    a, b = found
    first = DIGITS[0]
    word = outcome(
        a.recall_diff[first].low,
        a.precision_diff[first].high if a.precision_diff[first].n else None,
    )
    lines = [
        f"## The rule (committed in {RULE_COMMIT}, before this script existed)",
        "",
        RULE,
        f"Run a ({results[0].run_id}), the probable-cause query, the commonest-set predictor, all "
        f"judged cases ({a.n} of {results[0].split.total} cases):",
        f"- paired difference in mean recall at {first} digits, predictor less loop: "
        f"{_signed(a.recall_diff[first])} (n = {a.recall_diff[first].n} cases)",
        f"- paired difference in mean precision at {first} digits, predictor less loop: "
        f"{_signed(a.precision_diff[first])} (n = {a.precision_diff[first].n} cases where both "
        "precisions are defined)",
        f"- recall at {first} digits against the loop's, case by case: higher in {a.higher}, "
        f"equal in {a.equal}, lower in {a.lower} of {a.n} judged cases",
    ]
    if not a.precision_diff[first].n:
        lines.append(
            "Note: no case has both precisions, so the precision interval is read as not below "
            "zero."
        )
    lines += [
        f"Run b ({results[1].run_id}), beside it, decides nothing: recall difference "
        f"{_signed(b.recall_diff[first])} (n = {b.recall_diff[first].n}); precision difference "
        f"{_signed(b.precision_diff[first])} (n = {b.precision_diff[first].n})",
        f"Outcome: {word}",
        EXPECTATION,
        "The expectation was met." if word == "promising" else "The expectation was not met.",
    ]
    return lines


def method_lines(pool: Mapping[str, int], kept: int, flagged: int, years: str) -> list[str]:
    """How the pool was built and searched, the predictors, the scores and the rule's limits.

    Args:
        pool: the pool's counts (``statistics pool``, ``no text``, ``no code``).
        kept: the pool cases kept.
        flagged: how many of them have at least one flagged finding.
        years: the kept pool's event years, as a span.

    Returns:
        The lines.
    """
    return [
        "## Method",
        "",
        f"Pool: the S3 statistics pool, {STAGES[pp.STAGE].built_from}: "
        f"{pool['statistics pool']} cases; kept, each with an NTSB probable-cause text and at "
        f"least one occurrence code: {kept} ({years}); left out: {pool['no text']} with no "
        f"probable-cause text, {pool['no code']} more with no occurrence code. Of the kept "
        f"cases {flagged} have at least one finding flagged as cause. The judged cases are "
        "`dev-400`'s, which the pool leaves out, so a case is never its own precedent.",
        "Judged cases, for each run: scored (not failed: decision 0136 item 1), not abstained "
        "(the final answer's abstain flag is false), and with at least one finding the NTSB "
        "flagged as cause. Each of the run's cases is counted once, in that order: failed, "
        "abstained, no flagged finding, judged.",
        "Queries: the final answer's probable cause (the headline) and, beside it, its evidence "
        "narrative.",
        f"Search: the precedent probe's headline search, unchanged: BM25 (k1 = {pp.K1}, "
        f"b = {pp.B}) over the lower-cased word tokens of the pool's NTSB probable-cause texts, "
        f"less {len(pp.STOP_WORDS)} English stop words, over the pool cases whose event date is "
        "strictly earlier than the judged case's (N, df and the average length over that set); "
        f"ties by case id; the {pp.TOP} highest-ranked. A pool case sharing no word with the "
        "query is not ranked, so a case may have fewer than five.",
        "Predictors, each turning the five cases' flagged-finding sets (ten-digit codes) into "
        "one set, or none:",
        *(f"- {name}: {meaning}" for name, meaning in PREDICTOR_MEANINGS.items()),
        "Scores: ``scoring.metrics._precision_recall`` on the predicted set and the case's own "
        "flagged set, with each code cut to its first 10, 8 or 6 digits (the finding, its item, "
        "its category). Recall is the share of the case's own flagged findings the predicted set "
        "holds; precision is the share of the predicted set the case holds. A larger set raises "
        "recall and lowers precision, so both are printed. A predictor with none has a recall "
        "of 0, and its precision is left out of the precision mean and counted as 'no "
        "prediction'.",
        "The loop's own: the case's stored scores in the run (finding_recall_10, _8 and _6, and "
        "the matching precisions), as the harness scored its final answer. A precision of None "
        "(the loop named no finding) is left out of its precision mean.",
        "Paired difference: for each case, the predictor's score less the loop's; the mean of "
        "those with a 95% bootstrap interval (the project's: 2,000 resamples over cases, a fixed "
        "seed). Recall is paired on every judged case; precision only where both are defined.",
        "The rule is applied above on run a, the probable-cause query and the commonest-set "
        "predictor, over all judged cases. A low end of exactly zero is not above zero; a high "
        "end of exactly zero is not below it. Everything else is printed and decides nothing.",
        "What the intervals do not say: they treat cases as independent, although cases that "
        "share a sentence share a prediction. The date limit uses the event date, not the date "
        "an earlier verdict was published, so a precedent may have been available to the search "
        "before it was to an investigator; that can only favour the search.",
    ]


def comparison_lines(found: Comparison) -> list[str]:
    """One predictor's means and paired differences over one set of judged cases."""
    if not found.n:
        return ["- no judged case"]
    lines = [
        f"- mean recall at {d} digits: {_pct(found.recall[d])} (n = {found.n}); paired "
        f"difference, predictor less loop: {_signed(found.recall_diff[d])} "
        f"(n = {found.recall_diff[d].n})"
        for d in DIGITS
    ]
    lines += [
        f"- mean precision at {d} digits: {_pct(found.precision[d])} "
        f"(n = {found.precision[d].n} cases with a prediction); paired difference, predictor "
        f"less loop: {_signed(found.precision_diff[d])} "
        f"(n = {found.precision_diff[d].n} cases where both are defined)"
        for d in DIGITS
    ]
    lines.append(
        f"- no prediction: {found.no_prediction} of {found.n} judged cases (recall counted 0, "
        "precision left out)"
    )
    return lines


def own_lines(found: Own) -> list[str]:
    """The loop's own means over one set of judged cases."""
    if not found.n:
        return ["- no judged case"]
    lines = [
        f"- mean recall at {d} digits: {_pct(found.recall[d])} (n = {found.n})" for d in DIGITS
    ]
    lines += [
        f"- mean precision at {d} digits: {_pct(found.precision[d])} "
        f"(n = {found.precision[d].n} cases where the loop named a finding; "
        f"{found.n - found.precision[d].n} left out)"
        for d in DIGITS
    ]
    return lines


def run_lines(result: RunResult, *, letter: str) -> list[str]:
    """One run: its case counts, then each set of judged cases, query and predictor.

    Args:
        result: the run's scores.
        letter: ``a`` or ``b``.

    Returns:
        The lines.
    """
    split = result.split
    note = "" if letter == "a" else ", beside run a; decides nothing"
    lines = [
        f"## Run {letter} ({result.run_id}){note}",
        "",
        f"Cases in the run: {split.total}, each counted once, in this order: failed "
        f"{split.failed}; abstained {split.abstained}; no flagged finding {split.no_flagged}; "
        f"judged {len(split.judged)} {_fatal(split.judged)}.",
    ]
    for title, wanted in SUBSETS:
        cases = [j for j in split.judged if wanted(j)]
        lines += ["", f"### {title}: {len(cases)} judged"]
        lines += ["", "The loop's own findings, from its stored scores:"]
        lines += own_lines(loop_own(cases))
        for query in QUERIES:
            for name, _predict in PREDICTORS:
                headline = query == HEADLINE_QUERY and name == HEADLINE_PREDICTOR
                tag = " (headline)" if headline else ""
                lines += [
                    "",
                    f"{query} query, {name} predictor{tag}:",
                    *comparison_lines(compare(cases, result.scored[(query, name)])),
                ]
    return lines


def report(
    results: Sequence[RunResult], *, pool: Mapping[str, int], kept: int, flagged: int, years: str
) -> str:
    """The whole report: the head, the rule, the method, then run a and run b.

    Args:
        results: run a's and run b's results.
        pool: the pool's counts.
        kept: the pool cases kept.
        flagged: how many of them have at least one flagged finding.
        years: the kept pool's event years, as a span.

    Returns:
        The report's text.
    """
    head = [
        "S3.1 findings-from-precedent probe on dev-400 "
        "(scripts/exploratory/s3_finding_precedent.py; S3.1 Task 15)",
        "Exploratory (decision 0059): free and offline, no model call; it sets no bar and tunes "
        "nothing. Whether the flagged findings of the earlier NTSB cases whose cause sentences "
        "are nearest to the loop's own would beat the findings the loop chose.",
        "Counts and means only: no case number, no finding code and no text from any record. "
        "Means have a bootstrap 95% interval, each with its denominator.",
        f"run a = {results[0].run_id}",
        f"run b = {results[1].run_id} (printed beside run a; decides nothing)",
    ]
    blocks = [
        "\n".join(head),
        "\n".join(rule_lines(results)),
        "\n".join(method_lines(pool, kept, flagged, years)),
        *("\n".join(run_lines(r, letter="ab"[n])) for n, r in enumerate(results)),
    ]
    return "\n\n".join(blocks)


# --- the command ---


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_finding_precedent")
    parser.add_argument("--runs", nargs=2, required=True, metavar=("RUN_A", "RUN_B"))
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def _load(run_id: str) -> tuple[Run, CaseSplit]:
    run = pp.load_run(run_id)
    return run, sort_cases(run.cases)


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the means, the differences and the rule's word.

    Args:
        argv: the command line.

    Returns:
        0.
    """
    args = _arguments(argv)
    if args.runs[0] == args.runs[1]:
        _refuse("a run is named twice; run a and run b are two different runs")
    loaded = [_load(run_id) for run_id in args.runs]
    texts, dates, counts = pp.read_pool_texts(Settings().data_dir / "processed")
    wanted = {j.case_id for _run, split in loaded for j in split.judged}
    absent = sorted(i for i in wanted if i not in dates)
    if absent:
        _refuse(f"{len(absent)} judged case(s) have no event date in the processed file")
    days = {i: date.fromisoformat(dates[i]) for i in wanted}
    index = Index(pp.precedents(texts))
    flags = {case.case_id: frozenset(case.findings) for case in texts}
    results = [
        analyse(run.run_id, split, index=index, flags=flags, days=days) for run, split in loaded
    ]
    years = sorted({case.event_date.year for case in texts})
    text = report(
        results,
        pool=counts,
        kept=len(texts),
        flagged=sum(bool(found) for found in flags.values()),
        years=f"event years {years[0]}-{years[-1]}" if years else "no case",
    )
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
