"""Scores per case and per step, and the intervals they carry (spec §4). Pure functions."""

import random
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from math import sqrt

from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

_SIGN = {"confirmed": 1, "weakened": -1, "unchanged": 0}


@dataclass(frozen=True)
class CaseScores:
    """The §4.1 columns for one case. An abstained case scores False on every accuracy column."""

    occurrence_top1: bool
    occurrence_top3: bool
    event_match: bool
    pair_unseen: bool
    finding_precision_10: float | None
    finding_recall_10: float | None
    finding_precision_8: float | None
    finding_recall_8: float | None
    finding_precision_6: float | None
    finding_recall_6: float | None
    finding_precision_all_10: float | None
    finding_recall_all_10: float | None
    abstained: bool
    confidence: float


def primary_occurrence(verdict: Verdict) -> str | None:
    """The defining event's code: first in the verdict's ordered list."""
    return verdict.occurrence_codes[0] if verdict.occurrence_codes else None


def _precision_recall(
    predicted: Sequence[str], truth: Sequence[str], digits: int
) -> tuple[float | None, float | None]:
    p = {c[:digits] for c in predicted}
    t = {c[:digits] for c in truth}
    precision = len(p & t) / len(p) if p else None
    recall = len(p & t) / len(t) if t else None
    return precision, recall


def score_case(
    hypothesis: Hypothesis, verdict: Verdict, tables: CodeTables, *, seen_pairs: AbstractSet[str]
) -> CaseScores:
    """Score one hypothesis against one verdict."""
    codes = hypothesis.occurrence_codes(tables)
    truth = primary_occurrence(verdict)
    top1 = codes[0]
    answered = not hypothesis.abstain
    predicted = hypothesis.finding_codes(tables) if answered else ()
    p10, r10 = _precision_recall(predicted, verdict.finding_codes_in_cause, 10)
    p8, r8 = _precision_recall(predicted, verdict.finding_codes_in_cause, 8)
    p6, r6 = _precision_recall(predicted, verdict.finding_codes_in_cause, 6)
    pa, ra = _precision_recall(predicted, verdict.finding_codes, 10)
    return CaseScores(
        occurrence_top1=answered and top1 == truth,
        occurrence_top3=answered and truth in codes,
        event_match=answered and truth is not None and top1[3:] == truth[3:],
        pair_unseen=top1 not in seen_pairs,
        finding_precision_10=p10,
        finding_recall_10=r10,
        finding_precision_8=p8,
        finding_recall_8=r8,
        finding_precision_6=p6,
        finding_recall_6=r6,
        finding_precision_all_10=pa,
        finding_recall_all_10=ra,
        abstained=hypothesis.abstain,
        confidence=hypothesis.confidence,
    )


def prob_on_true(hypothesis: Hypothesis, verdict: Verdict, tables: CodeTables) -> float:
    """The probability the hypothesis puts on the primary occurrence code; 0 if unlisted."""
    truth = primary_occurrence(verdict)
    return hypothesis.occurrence_distribution(tables).get(truth or "", 0.0)


def information_gain(
    before: Hypothesis | None, after: Hypothesis, verdict: Verdict, tables: CodeTables
) -> float:
    """Change in probability on the true code caused by one step; the first step's gain is 0."""
    if before is None:
        return 0.0
    return prob_on_true(after, verdict, tables) - prob_on_true(before, verdict, tables)


def movement(before: Hypothesis | None, after: Hypothesis, tables: CodeTables) -> float:
    """Total variation distance between the occurrence distributions before and after a step."""
    if before is None:
        return 0.0
    a, b = before.occurrence_distribution(tables), after.occurrence_distribution(tables)
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


@dataclass(frozen=True)
class StepScores:
    """The §4.2 numbers for one step of a trail."""

    step: int
    scores: CaseScores
    prob_on_true: float
    information_gain: float
    movement: float


def score_trail(
    trail: Sequence[Hypothesis],
    verdict: Verdict,
    tables: CodeTables,
    *,
    seen_pairs: AbstractSet[str],
) -> tuple[StepScores, ...]:
    """Score every step of a trail; a one-shot run is a trail of length one."""
    out: list[StepScores] = []
    before: Hypothesis | None = None
    for k, h in enumerate(trail):
        out.append(
            StepScores(
                step=k,
                scores=score_case(h, verdict, tables, seen_pairs=seen_pairs),
                prob_on_true=prob_on_true(h, verdict, tables),
                information_gain=information_gain(before, h, verdict, tables),
                movement=movement(before, h, tables),
            )
        )
        before = h
    return tuple(out)


def wilson(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def bootstrap_mean(
    values: Sequence[float], *, resamples: int = 2000, seed: int = 20260914
) -> tuple[float, float, float]:
    """Mean with a percentile bootstrap 95% interval over cases."""
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)  # noqa: S311 -- statistics, not security
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(resamples))
    return sum(values) / n, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def paired_difference(
    a: Sequence[bool], b: Sequence[bool], *, resamples: int = 2000, seed: int = 20260914
) -> tuple[float, float, float]:
    """Mean of (a - b) per case with its bootstrap interval; a and b are on the same cases."""
    if len(a) != len(b):
        raise ValueError("paired runs must cover the same cases")
    return bootstrap_mean(
        [float(x) - float(y) for x, y in zip(a, b, strict=True)], resamples=resamples, seed=seed
    )


@dataclass(frozen=True)
class CalibrationBin:
    """One confidence bin."""

    low: float
    high: float
    count: int
    mean_confidence: float
    accuracy: float


def calibration(
    confidences: Sequence[float], correct: Sequence[bool], *, bins: int = 10
) -> tuple[tuple[CalibrationBin, ...], float]:
    """Reliability bins and the expected calibration error."""
    out: list[CalibrationBin] = []
    ece = 0.0
    total = len(confidences)
    for i in range(bins):
        low, high = i / bins, (i + 1) / bins
        members = [
            (c, r)
            for c, r in zip(confidences, correct, strict=True)
            if low <= c < high or (i == bins - 1 and c == 1.0)
        ]
        if not members:
            out.append(CalibrationBin(low, high, 0, 0.0, 0.0))
            continue
        mean_c = sum(c for c, _ in members) / len(members)
        acc = sum(r for _, r in members) / len(members)
        out.append(CalibrationBin(low, high, len(members), mean_c, acc))
        ece += len(members) / total * abs(mean_c - acc)
    return tuple(out), ece


def stated_versus_actual(observed: Sequence[str], gains: Sequence[float]) -> tuple[float, float]:
    """Share of steps where the stated effect matches the sign of the gain, and chance agreement."""
    stated = [_SIGN[o] for o in observed]
    actual = [(g > 0) - (g < 0) for g in gains]
    n = len(stated)
    agreement = sum(s == a for s, a in zip(stated, actual, strict=True)) / n
    chance = sum((stated.count(v) / n) * (actual.count(v) / n) for v in (-1, 0, 1))
    return agreement, chance
