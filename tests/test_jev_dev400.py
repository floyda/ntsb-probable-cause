"""The Jev dev-400 script's pure parts (docs/specs/2026-09-17-typesafe-jev-dev400-design.md)."""

import json
from pathlib import Path

from scripts.exploratory.jev_dev400 import (
    accuracy_reading,
    calibration_reading,
    jev_hypothesis,
    llm_first_guesses,
    questions,
    ranked_pairs,
    score_jev_case,
)

from ntsb_probable_cause.model.typesafe import ChoiceAnswer, SystemOneReply, SystemOneUsage
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, StepRecord, write_jsonl

TABLES = load_tables()


def _choice(probabilities: dict[str, float], confidence: float = 0.5) -> ChoiceAnswer:
    best = max(probabilities, key=probabilities.__getitem__)
    return ChoiceAnswer(
        type="choice", choice=best, confidence=confidence, probabilities=probabilities
    )


def _reply(phase: dict[str, float], event: dict[str, float]) -> SystemOneReply:
    return SystemOneReply(
        model="jev-1.13.0",
        usage=SystemOneUsage(input_tokens=10, output_tokens=5),
        answers={"phase": _choice(phase), "event": _choice(event, confidence=0.4)},
    )


def test_questions_are_the_probes_phase_and_event_only() -> None:
    asked = questions(TABLES)
    assert set(asked) == {"phase", "event"}
    assert len(asked["phase"]["criteria"]) == 47  # type: ignore[arg-type]
    assert len(asked["event"]["criteria"]) == 93  # type: ignore[arg-type]


def test_pairs_rank_by_joint_probability_then_code() -> None:
    phase = _choice({"550": 0.6, "500": 0.4})
    event = _choice({"092": 0.5, "000": 0.5, "240": 0.0})
    assert ranked_pairs(phase, event) == [
        ("550", "000", 0.3),
        ("550", "092", 0.3),
        ("500", "000", 0.2),
    ]


def test_jev_answer_scores_like_any_hypothesis() -> None:
    reply = _reply({"550": 0.9, "500": 0.1}, {"092": 0.7, "000": 0.3})
    hypothesis = jev_hypothesis(reply)
    assert hypothesis.occurrence_codes(TABLES) == ("550092", "550000", "500092")
    assert hypothesis.abstain is False
    assert abs(hypothesis.confidence - 0.63) < 1e-9
    verdict = Verdict(
        probable_cause=None,
        occurrence_codes=("550092",),
        finding_codes=(),
        finding_codes_in_cause=(),
    )
    case = score_jev_case("X1", True, reply, verdict, TABLES, frozenset({"550092"}))
    assert case.scores.occurrence_top1
    assert case.scores.event_match
    assert not case.scores.pair_unseen
    assert case.event_confidence == 0.4
    assert case.event_top_probability == 0.7
    assert case.true_event_probability == 0.7
    assert case.top_events == (("092", 0.7), ("000", 0.3))


def test_a_ruled_out_true_event_has_probability_zero() -> None:
    reply = _reply({"550": 1.0}, {"092": 1.0})
    verdict = Verdict(
        probable_cause=None,
        occurrence_codes=("550000",),
        finding_codes=(),
        finding_codes_in_cause=(),
    )
    case = score_jev_case("X2", False, reply, verdict, TABLES, frozenset())
    assert not case.scores.occurrence_top1
    assert case.true_event_probability == 0.0
    assert case.true_occurrence == "550000"


def test_calibration_readings_follow_the_spec_thresholds() -> None:
    stated = [0.9] * 50
    assert calibration_reading(stated, [True] * 45 + [False] * 5) == "calibrated"
    assert calibration_reading(stated, [True] * 41 + [False] * 9) == "inconclusive"
    assert calibration_reading(stated, [True] * 25 + [False] * 25) == "not calibrated"


def test_one_bin_of_twenty_far_off_makes_a_low_error_inconclusive() -> None:
    stated = [0.5] * 20 + [0.05] * 380
    right = [True] * 16 + [False] * 4 + [True] * 19 + [False] * 361
    assert calibration_reading(stated, right) == "inconclusive"


def test_accuracy_reading_uses_the_lower_bound() -> None:
    assert accuracy_reading([True] * 100 + [False] * 301) == "above the baseline"
    assert accuracy_reading([True] * 75 + [False] * 326) == "not above the baseline"


def _llm_case(case_id: str, phase: str, event: str, probability: float, truth: str) -> CaseResult:
    hypothesis = parse_hypothesis(
        json.dumps(
            {
                "evidence_narrative": "",
                "probable_cause": "",
                "lay_explanation": "",
                "confidence": 0.2,
                "abstain": True,
                "evidence_used": [],
                "occurrence": [{"phase": phase, "event": event, "probability": probability}],
                "findings": [],
            }
        ),
        TABLES,
    )
    step = StepRecord.model_validate(
        {
            "case_id": case_id,
            "step": 0,
            "arm": "ceiling",
            "condition": "full",
            "day": None,
            "tool": "none",
            "arguments": {},
            "reason": "",
            "expected_effect": "",
            "returned_roles": (),
            "not_available": (),
            "payload_fingerprint": "f",
            "hypothesis": hypothesis,
            "observed_effect": "",
            "stop_reason": "abstained",
            "model": "m",
            "price_variant": "batch",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cost_usd": 0.0,
            "cumulative_cost_usd": 0.0,
            "commit_sha": "abc1234",
            "dirty": False,
        }
    )
    scores = CaseScores(
        occurrence_top1=False,
        occurrence_top3=False,
        event_match=False,
        pair_unseen=False,
        finding_precision_10=None,
        finding_recall_10=None,
        finding_precision_8=None,
        finding_recall_8=None,
        finding_precision_6=None,
        finding_recall_6=None,
        finding_precision_all_10=None,
        finding_recall_all_10=None,
        abstained=True,
        confidence=0.2,
    )
    return CaseResult(
        case_id=case_id,
        split="dev",
        fatal=False,
        investigation_class=None,
        report_flavour=None,
        verdict_occurrence=(truth,),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(step,),
        scores=scores,
        cost_usd=0.0,
        failure=None,
    )


def test_llm_first_guess_is_read_whether_or_not_the_model_abstained(tmp_path: Path) -> None:
    cases_file = tmp_path / "cases.jsonl"
    write_jsonl(
        cases_file,
        [
            _llm_case("A", "550", "092", 0.6, "550092"),
            _llm_case("B", "550", "000", 0.3, "550092"),
        ],
    )
    guesses = llm_first_guesses(cases_file)
    assert guesses["A"].probability == 0.6
    assert guesses["A"].right
    assert not guesses["A"].top1
    assert not guesses["B"].right
