"""The judge: labels for the prose outputs against withheld text (spec §8, decision 0028)."""

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest

from ntsb_probable_cause.errors import BudgetError, SchemaError
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    RecordingFakeClient,
    Turn,
    Usage,
)
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import judge
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores


def _score(*, top1: bool = True) -> CaseScores:
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


GOOD_LABELS = json.dumps(
    {"narrative": "consistent", "cause": "same_cause", "lay": "explains_chosen_codes"}
)

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
    client = RecordingFakeClient([GOOD_LABELS])
    labels, _ = judge.judge_case(client, H, S, V, load_tables())
    assert labels.cause == "same_cause"
    assert client.payloads[0].fields() == {}


def test_judge_case_uses_the_judge_model_and_carries_the_text_as_system() -> None:
    client = RecordingFakeClient([GOOD_LABELS])
    judge.judge_case(client, H, S, V, load_tables())
    assert (
        client.systems[0] == f"{judge.SYSTEM_JUDGE}\n\n{judge.judge_text(H, S, V, load_tables())}"
    )


def test_judge_case_defaults_to_a_generous_output_cap() -> None:
    """Fix round 1, Important 2: 2000, not a magic 200 -- the reply is a few tokens of JSON."""
    captured: list[ModelSettings] = []

    class _Capture:
        def complete(
            self,
            payload: Payload,
            settings: ModelSettings,
            *,
            system: str = "",
            history: Sequence[Turn] = (),
        ) -> ModelReply:
            captured.append(settings)
            return ModelReply(
                content=GOOD_LABELS,
                usage=Usage(prompt_tokens=1, completion_tokens=1),
                model=settings.model_id(),
                response_id="fake",
            )

    judge.judge_case(_Capture(), H, S, V, load_tables())
    assert captured[0].max_output_tokens == 2000
    assert captured[0].model == judge.JUDGE_MODEL


def test_judge_case_retries_once_after_a_truncated_reply() -> None:
    """Fix round 1, Important 2: an empty, ``finish_reason: length`` reply gets one retry."""

    class _TruncatedThenGood:
        def __init__(self) -> None:
            self.calls = 0
            self.systems: list[str] = []

        def complete(
            self,
            payload: Payload,
            settings: ModelSettings,
            *,
            system: str = "",
            history: Sequence[Turn] = (),
        ) -> ModelReply:
            self.systems.append(system)
            self.calls += 1
            usage = Usage(prompt_tokens=10, completion_tokens=0 if self.calls == 1 else 5)
            content = None if self.calls == 1 else GOOD_LABELS
            finish_reason = "length" if self.calls == 1 else "stop"
            return ModelReply(
                content=content,
                finish_reason=finish_reason,
                usage=usage,
                model=settings.model_id(),
                response_id=f"fake-{self.calls}",
            )

    client = _TruncatedThenGood()
    labels, reply = judge.judge_case(client, H, S, V, load_tables())
    assert labels.cause == "same_cause"
    assert client.calls == 2
    assert reply.response_id == "fake-2"
    assert "Your previous reply was rejected" in client.systems[1]


def test_judge_case_raises_after_two_bad_replies() -> None:
    client = RecordingFakeClient(["not json", "still not json"])
    with pytest.raises(SchemaError, match="judge reply is not JudgeLabels"):
        judge.judge_case(client, H, S, V, load_tables())
    assert len(client.payloads) == 2


def test_judge_schema_is_openai_strict_compatible() -> None:
    schema: dict[str, Any] = judge.JUDGE_SCHEMA
    _assert_strict(schema)


def _assert_strict(schema: dict[str, Any]) -> None:
    """Every object node is ``additionalProperties: false`` with every property required;
    ``title``/``default`` never appear anywhere (fix round 1, Important 1)."""

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "title" not in node
            assert "default" not in node
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(schema)


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


def test_judge_run_refuses_over_budget_before_any_call() -> None:
    """Fix round 1, Important 1: judge spend now goes through the same guard as a run."""
    client = RecordingFakeClient([GOOD_LABELS])
    items = [("case1", H, S, V, _score())]
    with pytest.raises(BudgetError):
        judge.judge_run(client, load_tables(), items, budget_usd=0.0001, month_spent_usd=0.0)
    assert client.payloads == []  # refused before the first call, nothing spent


def test_judge_run_prices_each_case_and_writes_rows_incrementally() -> None:
    client = RecordingFakeClient(
        [GOOD_LABELS, GOOD_LABELS], usage=[Usage(prompt_tokens=100, completion_tokens=20)]
    )
    items = [("case1", H, S, V, _score(top1=True)), ("case2", H, S, V, _score(top1=False))]
    rows: list[Mapping[str, object]] = []
    result = judge.judge_run(client, load_tables(), items, on_row=rows.append)
    assert result.case_ids == ("case1", "case2")
    assert [label.cause for label in result.labels] == ["same_cause", "same_cause"]
    assert result.scores[0].occurrence_top1 is True
    assert result.scores[1].occurrence_top1 is False
    assert len(rows) == 2  # one row per case, as it was paid for -- not one write at the end
    assert rows[0]["case_id"] == "case1"
    assert rows[0]["cause"] == "same_cause"
    assert sum(cast(float, r["cost_usd"]) for r in rows) == pytest.approx(result.cost_usd)
    assert result.cost_usd > 0


def test_judge_run_keeps_rows_paid_for_before_a_later_case_fails() -> None:
    """An interrupt/error partway through keeps every already-paid label (fix round 1)."""
    client = RecordingFakeClient(
        [GOOD_LABELS, "not json", "still not json"],
        usage=[Usage(prompt_tokens=100, completion_tokens=20)],
    )
    items = [
        ("case1", H, S, V, _score()),
        ("case2", H, S, V, _score()),  # this one's two replies are both unparsable
    ]
    rows: list[Mapping[str, object]] = []
    with pytest.raises(SchemaError):
        judge.judge_run(client, load_tables(), items, on_row=rows.append)
    assert len(rows) == 1  # case1's row survives even though case2 raised
    assert rows[0]["case_id"] == "case1"


def test_judge_expected_cost_per_case_matches_the_controllers_measurement() -> None:
    assert judge.JUDGE_EXPECTED_COST_PER_CASE_USD == {"batch": 0.0004, "standard": 0.00089}
