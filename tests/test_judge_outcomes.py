"""scripts/judge_outcomes.py: the four outcomes and their movement (decision 0099)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import judge_outcomes as jo
from tests.test_occurrence_misses import _SCORES, _case  # the shared CaseResult builders

from ntsb_probable_cause.scoring.judge import JudgeLabels


def _labels(narrative: str, cause: str = "related") -> JudgeLabels:
    return JudgeLabels(narrative=narrative, cause=cause, lay="does_not")


@pytest.mark.parametrize(
    ("top1", "narrative", "expected"),
    [
        (True, "contradicts", "right"),
        (False, "consistent", "understood, miscoded"),
        (False, "less_detailed", "thin evidence"),
        (False, "contradicts", "misread"),
        (False, "adds_unsupported_facts", "misread"),
    ],
)
def test_outcome(top1: bool, narrative: str, expected: str) -> None:
    assert jo.outcome(top1, narrative) == expected


def test_read_labels_reads_judge_rows(tmp_path: Path) -> None:
    rows = [
        {
            "case_id": "C1",
            "cost_usd": 0.001,
            "narrative": "consistent",
            "cause": "same_cause",
            "lay": "does_not",
        }
    ]
    (tmp_path / "judge.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert jo.read_labels(tmp_path) == {"C1": _labels("consistent", "same_cause")}


def test_movement_counts_cases_whose_outcome_changed() -> None:
    a: dict[str, jo.Outcome] = {"C1": "misread", "C2": "right", "C3": "thin evidence"}
    b: dict[str, jo.Outcome] = {"C1": "understood, miscoded", "C2": "right"}
    assert jo.movement(a, b) == (1, 2)


def test_shares_says_unvalidated_and_splits_fatal() -> None:
    right = _case("C1", ("452240",), ("452240",)).model_copy(
        update={"fatal": True, "scores": replace(_SCORES, occurrence_top1=True)}
    )
    wrong = _case("C2", ("452240",), ("452241",))
    cases = [right, wrong]
    labels = {"C1": _labels("consistent"), "C2": _labels("contradicts")}
    outs = jo.outcomes(cases, labels)
    assert outs == {"C1": "right", "C2": "misread"}
    text = jo.shares("B-v1", cases, outs, labels, status="unvalidated")
    assert "unvalidated" in text
    assert "misread: 1 of 2" in text
    assert "fatal (1 cases):" in text
