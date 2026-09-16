"""Report tables, slices, comparisons and the threshold rule (spec §4, §6.3, §9).

Every number a human reads comes from here: proportions and means carry an interval and a
count (spec §4.3), tables are sliced fatal/non-fatal then by class then by flavour (§4.4),
and the stopping threshold is read off a curve, not chosen (§9).
"""

import json
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import baseline
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.metrics import (
    CaseScores,
    bootstrap_mean,
    paired_difference,
    wilson,
)
from ntsb_probable_cause.scoring.records import CaseResult
from ntsb_probable_cause.splits import Split


@dataclass(frozen=True)
class Cell:
    """One reported number: its value, its 95% interval and the count behind it (spec §4.3)."""

    value: float
    low: float
    high: float
    n: int


def proportion(flags: Sequence[bool]) -> Cell:
    """A proportion with its Wilson 95% interval."""
    n = len(flags)
    successes = sum(1 for f in flags if f)
    low, high = wilson(successes, n)
    return Cell(value=successes / n if n else 0.0, low=low, high=high, n=n)


def mean_cell(values: Sequence[float]) -> Cell:
    """A mean with its bootstrap 95% interval."""
    value, low, high = bootstrap_mean(list(values))
    return Cell(value=value, low=low, high=high, n=len(values))


def slices(results: Sequence[CaseResult]) -> dict[str, list[CaseResult]]:
    """Slice a result set: all, fatal/non-fatal, class C/F/L, then one per flavour seen.

    Order matters (spec §4.4): fatal/non-fatal first, class second, flavour last, for
    context only. A slice with no members is still yielded except for flavours, which are
    only listed when at least one case carries them.
    """
    out: dict[str, list[CaseResult]] = {
        "all": list(results),
        "fatal": [r for r in results if r.fatal],
        "non-fatal": [r for r in results if not r.fatal],
    }
    for cls in ("C", "F", "L"):
        out[f"class {cls}"] = [r for r in results if r.investigation_class == cls]
    flavours: list[str] = []
    for r in results:
        if r.report_flavour is not None and r.report_flavour not in flavours:
            flavours.append(r.report_flavour)
    for flavour in flavours:
        out[f"flavour {flavour}"] = [r for r in results if r.report_flavour == flavour]
    return out


def weighted_headline(
    results: Sequence[CaseResult],
    *,
    fatal_share: float = 727 / 4241,
    resamples: int = 2000,
    seed: int = 20260914,
) -> Cell:
    """The all-cases top-1 headline, weighted by the held-out fatal share (spec §5.2).

    The interval is a bootstrap over the two slices' per-case flags, resampled within each
    stratum and recombined with the same weights on every draw, so it reflects both strata's
    sampling error rather than treating the weighted mean as a single flat proportion.
    """
    fatal = [r.scores.occurrence_top1 for r in results if r.scores is not None and r.fatal]
    non_fatal = [r.scores.occurrence_top1 for r in results if r.scores is not None and not r.fatal]
    n = len(fatal) + len(non_fatal)
    if not fatal or not non_fatal:
        # Nothing to weight: fall back to the plain proportion of whichever stratum exists.
        return proportion(fatal + non_fatal)
    value = fatal_share * (sum(fatal) / len(fatal)) + (1 - fatal_share) * (
        sum(non_fatal) / len(non_fatal)
    )
    rng = random.Random(seed)  # noqa: S311 -- statistics, not security
    means = sorted(
        fatal_share * (sum(rng.choice(fatal) for _ in fatal) / len(fatal))
        + (1 - fatal_share) * (sum(rng.choice(non_fatal) for _ in non_fatal) / len(non_fatal))
        for _ in range(resamples)
    )
    low, high = means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]
    return Cell(value=value, low=low, high=high, n=n)


def _diff_line(label: str, a: Sequence[bool], b: Sequence[bool]) -> str:
    mean, low, high = paired_difference(a, b)
    return f"- {label}: {mean:+.1%} [{low:+.1%}, {high:+.1%}] on n={len(a)} cases"


def compare(a: Sequence[CaseResult], b: Sequence[CaseResult]) -> str:
    """Paired differences (spec §4.3) on the shared case ids: top-1, top-3, recall@10."""
    by_a = {r.case_id: r.scores for r in a if r.scores is not None}
    by_b = {r.case_id: r.scores for r in b if r.scores is not None}
    ids = sorted(set(by_a) & set(by_b))
    lines = [f"paired difference (a - b) on {len(ids)} shared, scored cases:"]
    lines.append(
        _diff_line(
            "occurrence top-1",
            [by_a[i].occurrence_top1 for i in ids],
            [by_b[i].occurrence_top1 for i in ids],
        )
    )
    lines.append(
        _diff_line(
            "occurrence top-3",
            [by_a[i].occurrence_top3 for i in ids],
            [by_b[i].occurrence_top3 for i in ids],
        )
    )
    pairs = [(by_a[i].finding_recall_10, by_b[i].finding_recall_10) for i in ids]
    scored_pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if scored_pairs:
        mean, low, high = bootstrap_mean([x - y for x, y in scored_pairs])
        lines.append(
            f"- finding recall@10: {mean:+.1%} [{low:+.1%}, {high:+.1%}] "
            f"on n={len(scored_pairs)} cases"
        )
    else:
        lines.append("- finding recall@10: no shared cases have a truth finding set")
    return "\n".join(lines)


_THRESHOLDS = tuple(i / 20 for i in range(1, 20))


def threshold_curve(results: Sequence[CaseResult]) -> list[tuple[float, float]]:
    """The stopping-threshold curve (spec §9): mean of +1/-1/0 for each candidate *t*."""
    scored = [r.scores for r in results if r.scores is not None]
    curve: list[tuple[float, float]] = []
    for t in _THRESHOLDS:
        total = 0.0
        for s in scored:
            if s.abstained or s.confidence < t:
                continue
            total += 1.0 if s.occurrence_top1 else -1.0
        curve.append((round(t, 2), total / len(scored) if scored else 0.0))
    return curve


def choose_threshold(results: Sequence[CaseResult]) -> float:
    """The smallest *t* reaching the curve's maximum mean score (spec §9)."""
    curve = threshold_curve(results)
    best = max(v for _, v in curve)
    return next(t for t, v in curve if v == best)


def fmt(cell: Cell) -> str:
    """``57.5% [42.1, 71.5]``."""
    return f"{cell.value:.1%} [{cell.low:.1%}, {cell.high:.1%}]"


def _column(scored: Sequence[CaseResult], pick: Callable[[CaseScores], float | None]) -> Cell:
    values = [v for r in scored if r.scores is not None and (v := pick(r.scores)) is not None]
    return mean_cell(values)


def summarise(results: Sequence[CaseResult], *, floor: Mapping[str, float] | None = None) -> str:
    """Markdown tables: per slice, every §4.1 column with n and its 95% interval."""
    head = (
        "| slice | n | top-1 | top-3 | event | pair unseen | abstain | answered top-1 | "
        "finding P@10 | R@10 | P@8 | R@8 | P@6 | R@6 | R@10 all | failed | cost/case USD |"
    )
    lines = [head, "|" + "---|" * 17]
    for name, rows in slices(results).items():
        scored = [r for r in rows if r.scores is not None]
        if not scored:
            continue
        s = [r.scores for r in scored if r.scores is not None]
        answered = [x for x in s if not x.abstained]
        cells = [
            fmt(proportion([x.occurrence_top1 for x in s])),
            fmt(proportion([x.occurrence_top3 for x in s])),
            fmt(proportion([x.event_match for x in s])),
            fmt(proportion([x.pair_unseen for x in s])),
            fmt(proportion([x.abstained for x in s])),
            fmt(proportion([x.occurrence_top1 for x in answered])) if answered else "-",
            fmt(_column(scored, lambda x: x.finding_precision_10)),
            fmt(_column(scored, lambda x: x.finding_recall_10)),
            fmt(_column(scored, lambda x: x.finding_precision_8)),
            fmt(_column(scored, lambda x: x.finding_recall_8)),
            fmt(_column(scored, lambda x: x.finding_precision_6)),
            fmt(_column(scored, lambda x: x.finding_recall_6)),
            fmt(_column(scored, lambda x: x.finding_recall_all_10)),
            f"{sum(1 for r in rows if r.failure)} of {len(rows)}",
            f"{sum(r.cost_usd for r in rows) / len(rows):.4f}",
        ]
        lines.append(f"| {name} | {len(scored)} | " + " | ".join(cells) + " |")
    if floor:
        lines.append("\nBaseline floor: " + ", ".join(f"{k} {v:.1%}" for k, v in floor.items()))
    return "\n".join(lines)


def _raws_of_split(processed: Path, split: Split) -> list[dict[str, object]]:
    """Every raw record of one split, read directly from the processed file."""
    table = pq.read_table(processed / "cases.parquet", columns=["split", "raw_json"])
    return [
        json.loads(r)
        for s, r in zip(table["split"].to_pylist(), table["raw_json"].to_pylist(), strict=True)
        if s == split.value
    ]


def _finding_pr(
    predicted: Sequence[str], truth: Sequence[str], digits: int
) -> tuple[float | None, float | None]:
    p = {c[:digits] for c in predicted}
    t = {c[:digits] for c in truth}
    precision = len(p & t) / len(p) if p else None
    recall = len(p & t) / len(t) if t else None
    return precision, recall


@dataclass(frozen=True)
class _BaselineScores:
    """One baseline model, scored on one set of raw records, at every digit width."""

    top1: Cell
    top3: Cell
    precision: dict[int, Cell]
    recall: dict[int, Cell]
    precision_all: dict[int, Cell]
    recall_all: dict[int, Cell]


_DIGITS = (10, 8, 6)


def _score_baseline(
    model: baseline.BaselineModel, raws: Sequence[Mapping[str, object]]
) -> _BaselineScores:
    top1: list[bool] = []
    top3: list[bool] = []
    precision: dict[int, list[float]] = {d: [] for d in _DIGITS}
    recall: dict[int, list[float]] = {d: [] for d in _DIGITS}
    precision_all: dict[int, list[float]] = {d: [] for d in _DIGITS}
    recall_all: dict[int, list[float]] = {d: [] for d in _DIGITS}
    for raw in raws:
        truth_codes = fields.occurrence_codes(raw)
        truth = truth_codes[0] if truth_codes else None
        occ, findings = baseline.predict(model, raw)
        top1.append(truth is not None and bool(occ) and occ[0] == truth)
        top3.append(truth is not None and truth in occ)
        flagged = fields.finding_codes_in_cause(raw)
        every = fields.finding_codes(raw)
        for d in _DIGITS:
            p, r = _finding_pr(findings, flagged, d)
            if p is not None:
                precision[d].append(p)
            if r is not None:
                recall[d].append(r)
            pa, ra = _finding_pr(findings, every, d)
            if pa is not None:
                precision_all[d].append(pa)
            if ra is not None:
                recall_all[d].append(ra)
    return _BaselineScores(
        top1=proportion(top1),
        top3=proportion(top3),
        precision={d: mean_cell(v) for d, v in precision.items()},
        recall={d: mean_cell(v) for d, v in recall.items()},
        precision_all={d: mean_cell(v) for d, v in precision_all.items()},
        recall_all={d: mean_cell(v) for d, v in recall_all.items()},
    )


def _finding_lines(scores: _BaselineScores) -> list[str]:
    return [
        f"  finding@{d}: precision(flagged) {fmt(scores.precision[d])}, "
        f"recall(flagged) {fmt(scores.recall[d])}, precision(all) {fmt(scores.precision_all[d])}, "
        f"recall(all) {fmt(scores.recall_all[d])}"
        for d in _DIGITS
    ]


def baseline_report(processed: Path, sample_ids: Sequence[str] | None, tables: CodeTables) -> str:
    """Reproduce the spike's baseline and report the dev-fitted floor (spec §6.3).

    ``tables`` is accepted for interface symmetry with the model-scoring commands; the
    baseline predicts already-composed codes directly from the raw record and needs no code
    composition, so it is unused here.
    """
    del tables
    heldout = _raws_of_split(processed, Split.HELDOUT)
    by_id = {str(raw["ntsbNumber"]): raw for raw in heldout}
    rows = [
        (str(raw["ntsbNumber"]), codes[0])
        for raw in heldout
        if (codes := fields.occurrence_codes(raw))
    ]
    drawn_ids = baseline.stratified_draw(rows, min(1000, len(rows)), seed=7)
    repro_raws = [by_id[i] for i in drawn_ids]
    repro_model = baseline.fit(repro_raws)
    repro = _score_baseline(repro_model, repro_raws)

    dev = _raws_of_split(processed, Split.DEV)
    honest_model = baseline.fit(dev)
    honest_all = _score_baseline(honest_model, heldout)

    lines = [
        "## Baseline (spec §6.3)",
        "",
        f"Reproduction (seed 7, in-sample fit, n={len(repro_raws)}): "
        f"top-1 {fmt(repro.top1)}, top-3 {fmt(repro.top3)}, "
        f"finding precision@10 (all findings) {fmt(repro.precision_all[10])}, "
        f"recall@10 (all findings) {fmt(repro.recall_all[10])}. "
        "Spike (1,000-case draw): top-1 16.2%, top-3 32.2%, precision 17.0%, recall 19.0%.",
        "",
        f"Honest baseline (fit on development, scored on all held-out, n={len(heldout)}): "
        f"top-1 {fmt(honest_all.top1)}, top-3 {fmt(honest_all.top3)}",
        *_finding_lines(honest_all),
    ]
    if sample_ids is not None:
        sample_raws = [by_id[i] for i in sample_ids if i in by_id]
        sample_scores = _score_baseline(honest_model, sample_raws)
        lines += [
            "",
            f"Honest baseline on the given sample (n={len(sample_raws)}): "
            f"top-1 {fmt(sample_scores.top1)}, top-3 {fmt(sample_scores.top3)}",
            *_finding_lines(sample_scores),
        ]
    return "\n".join(lines)
