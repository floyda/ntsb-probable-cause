"""The judge: labels for the prose outputs against withheld text (spec §8, decision 0028)."""

import json
from typing import Any

import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.model.client import RecordingFakeClient
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import judge
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores

H = parse_hypothesis(
    json.dumps(
        {
            "evidence_narrative": "The airplane ran off the runway.",
            "probable_cause": "Loss of directional control.",
            "lay_explanation": "It swerved.",
            "confidence": 0.5,
            "abstain": False,
            "evidence_used": [],
            "occurrence": [{"phase": "552", "event": "230", "probability": 0.5}],
            "findings": [{"category6": "020630", "modifier": "44", "probability": 0.5}],
        }
    ),
    load_tables(),
)
S = Synthesis(
    factual_narrative="The pilot reported a gust during the landing roll.",
    analysis_narrative=None,
)
V = Verdict(
    probable_cause="The pilot's failure to maintain directional control.",
    occurrence_codes=("552230",),
    finding_codes=("0206304044",),
    finding_codes_in_cause=("0206304044",),
)


def test_judge_text_holds_the_withheld_narrative_and_cause() -> None:
    text = judge.judge_text(H, S, V, load_tables())
    assert "gust during the landing roll" in text
    assert "failure to maintain directional control" in text


def test_judge_case_parses_labels_and_sends_empty_payload() -> None:
    client = RecordingFakeClient(
        [
            json.dumps(
                {"narrative": "consistent", "cause": "same_cause", "lay": "explains_chosen_codes"}
            )
        ]
    )
    labels, _ = judge.judge_case(client, H, S, V, load_tables())
    assert labels.cause == "same_cause"
    assert client.payloads[0].fields() == {}


def test_judge_case_uses_the_judge_model_and_carries_the_text_as_system() -> None:
    client = RecordingFakeClient(
        [
            json.dumps(
                {"narrative": "consistent", "cause": "same_cause", "lay": "explains_chosen_codes"}
            )
        ]
    )
    judge.judge_case(client, H, S, V, load_tables())
    assert (
        client.systems[0] == f"{judge.SYSTEM_JUDGE}\n\n{judge.judge_text(H, S, V, load_tables())}"
    )


def test_judge_case_raises_schema_error_on_a_bad_reply() -> None:
    client = RecordingFakeClient(["not json"])
    with pytest.raises(SchemaError, match="judge reply is not JudgeLabels"):
        judge.judge_case(client, H, S, V, load_tables())


def test_judge_schema_is_openai_strict_compatible() -> None:
    schema: dict[str, Any] = judge.JUDGE_SCHEMA
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_agreement_table_counts_by_cause_label_and_top1() -> None:
    def score(top1: bool) -> CaseScores:
        return CaseScores(
            occurrence_top1=top1,
            occurrence_top3=top1,
            event_match=top1,
            pair_unseen=False,
            finding_precision_10=None,
            finding_recall_10=None,
            finding_precision_8=None,
            finding_recall_8=None,
            finding_precision_6=None,
            finding_recall_6=None,
            finding_precision_all_10=None,
            finding_recall_all_10=None,
            abstained=False,
            confidence=0.5,
        )

    labels = [
        judge.JudgeLabels(narrative="consistent", cause="same_cause", lay="explains_chosen_codes"),
        judge.JudgeLabels(narrative="consistent", cause="same_cause", lay="explains_chosen_codes"),
        judge.JudgeLabels(narrative="contradicts", cause="different", lay="does_not"),
    ]
    scores = [score(True), score(False), score(False)]
    table = judge.agreement_table(labels, scores)
    assert table == {
        "same_cause": {"top1_right": 1, "top1_wrong": 1},
        "different": {"top1_right": 0, "top1_wrong": 1},
    }


def test_pick_disagreements_is_seeded_and_bounded() -> None:
    def score(top1: bool) -> CaseScores:
        return CaseScores(
            occurrence_top1=top1,
            occurrence_top3=top1,
            event_match=top1,
            pair_unseen=False,
            finding_precision_10=None,
            finding_recall_10=None,
            finding_precision_8=None,
            finding_recall_8=None,
            finding_precision_6=None,
            finding_recall_6=None,
            finding_precision_all_10=None,
            finding_recall_all_10=None,
            abstained=False,
            confidence=0.5,
        )

    case_ids = [f"case{i}" for i in range(10)]
    labels = [
        judge.JudgeLabels(narrative="consistent", cause="same_cause", lay="explains_chosen_codes")
        for _ in range(10)
    ]
    scores = [score(i % 2 == 0) for i in range(10)]
    picked = judge.pick_disagreements(case_ids, labels, scores, n=2, seed=1)
    assert len(picked) == 2
    assert picked == sorted(picked)
    assert set(picked) <= set(case_ids)
