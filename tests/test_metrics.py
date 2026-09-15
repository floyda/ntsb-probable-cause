"""Per-case and per-step metrics, and the intervals they carry (spec §4)."""

import json

import pytest

from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import metrics
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, parse_hypothesis

T = load_tables()
VERDICT = Verdict(
    probable_cause="x",
    occurrence_codes=("552230", "553000"),
    finding_codes=("0206304044", "0102256099", "0500000000"),
    finding_codes_in_cause=("0206304044", "0102256099"),
)


def hyp(
    occ: list[tuple[str, str, float]],
    findings: list[tuple[str, str, str | None]],
    conf: float = 0.5,
    abstain: bool = False,
) -> Hypothesis:
    """Build a Hypothesis from short tuples; attach stage-2 items via with_items."""
    body = {
        "evidence_narrative": "n",
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": conf,
        "abstain": abstain,
        "evidence_used": [],
        "occurrence": [{"phase": p, "event": e, "probability": pr} for p, e, pr in occ],
        "findings": [
            {"category6": c[:6], "modifier": m, "probability": 0.5} for c, m, _ in findings
        ],
    }
    h = parse_hypothesis(json.dumps(body), T)
    return h.with_items({i: item for i, (_, _, item) in enumerate(findings) if item})


def test_score_case_by_hand() -> None:
    h = hyp(
        [("551", "230", 0.5), ("552", "230", 0.3)],
        [("02063040", "44", "02063040"), ("03013010", "99", "03013010")],
    )
    s = metrics.score_case(h, VERDICT, T, seen_pairs={"551230", "552230"})
    assert s.occurrence_top1 is False
    assert s.occurrence_top3 is True
    assert s.event_match is True
    assert s.pair_unseen is False
    # flagged: 0206304044, 0102256099; model: 0206304044, 0301301099
    assert s.finding_precision_10 == 0.5
    assert s.finding_recall_10 == 0.5
    assert s.finding_precision_6 == 0.5
    assert s.finding_recall_6 == 0.5
    # against all three findings: precision 1/2, recall 1/3
    assert s.finding_precision_all_10 == 0.5
    assert s.finding_recall_all_10 == pytest.approx(1 / 3)


def test_abstained_case_scores_zero_on_accuracy() -> None:
    h = hyp([("552", "230", 0.9)], [], abstain=True)
    s = metrics.score_case(h, VERDICT, T, seen_pairs=set())
    assert s.abstained
    assert not s.occurrence_top1
    assert s.pair_unseen is True


def test_trail_scores_by_hand() -> None:
    steps = [
        hyp([("551", "230", 0.5)], []),  # p(true)=0
        hyp([("552", "230", 0.4), ("551", "230", 0.4)], []),  # p(true)=0.4
        hyp([("552", "230", 0.7)], []),  # p(true)=0.7
    ]
    scored = metrics.score_trail(steps, VERDICT, T, seen_pairs={"551230", "552230"})
    assert [s.prob_on_true for s in scored] == [0.0, 0.4, 0.7]
    assert [round(s.information_gain, 6) for s in scored] == [0.0, 0.4, pytest.approx(0.3)]
    # movement step 1 -> 2: before {551230:.5, other:.5}; after {552230:.4, 551230:.4, other:.2}
    # TV = 0.5 * (|0-.4| + |.5-.4| + |.5-.2|) = 0.5 * 0.8 = 0.4
    assert scored[1].movement == pytest.approx(0.4)
    assert scored[0].movement == 0.0


def test_wilson_matches_published_value() -> None:
    low, high = metrics.wilson(23, 40)
    assert (round(low, 3), round(high, 3)) == (0.422, 0.715)


def test_paired_difference_is_zero_for_identical_runs_and_positive_when_a_wins() -> None:
    a = [True] * 30 + [False] * 10
    mean, low, high = metrics.paired_difference(a, a)
    assert (mean, low, high) == (0.0, 0.0, 0.0)
    b = [True] * 20 + [False] * 20
    mean, low, high = metrics.paired_difference(a, b)
    assert mean == pytest.approx(0.25)
    assert low > 0


def test_calibration_by_hand() -> None:
    conf = [0.95, 0.95, 0.15, 0.15]
    right = [True, False, False, False]
    bins, ece = metrics.calibration(conf, right, bins=10)
    top = next(b for b in bins if b.count and b.low >= 0.9)
    assert top.accuracy == 0.5
    assert top.mean_confidence == 0.95
    # ece = (2/4)*|0.95-0.5| + (2/4)*|0.15-0| = 0.225 + 0.075
    assert ece == pytest.approx(0.30)


def test_stated_versus_actual() -> None:
    agreement, chance = metrics.stated_versus_actual(
        ["confirmed", "weakened", "unchanged", "confirmed"], [0.2, -0.1, 0.0, -0.3]
    )
    assert agreement == 0.75
    assert 0 < chance < 1
