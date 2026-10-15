"""The pilot's reading and its registered stop rule (decision 0204). Made-up numbers; offline."""

import json
from pathlib import Path

import pytest
from scripts import memory_pilot_result as pr
from scripts.memory_coding_test import CodingCase

from ntsb_probable_cause.memory import claude
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis


def test_a_finding_gain_beyond_the_noise_with_no_harm_passes() -> None:
    noise = pr.Diff3(top1=-0.01, top3=0.02, recall10=0.015)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=0.0, top3=-0.01, recall10=0.03), noise)
    assert ok, reasons


def test_a_finding_gain_inside_the_noise_does_not_pass() -> None:
    noise = pr.Diff3(top1=0.0, top3=0.0, recall10=0.02)
    ok, _ = pr.stop_rule(pr.Diff3(top1=0.05, top3=0.05, recall10=0.02), noise)
    assert not ok


def test_harm_beyond_the_noise_on_top1_fails_even_with_a_finding_gain() -> None:
    noise = pr.Diff3(top1=0.01, top3=0.01, recall10=0.01)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=-0.02, top3=0.0, recall10=0.05), noise)
    assert not ok
    assert any("top-1" in r for r in reasons)


def test_a_failed_case_counts_as_wrong() -> None:
    got = pr.measure_failed(flags_findings=True)
    assert (got.top1, got.top3, got.recall10) == (False, False, 0.0)
    assert pr.measure_failed(flags_findings=False).recall10 is None


def _hypothesis(phase: str, event: str) -> Hypothesis:
    return Hypothesis.model_validate(
        {
            "evidence_narrative": "x",
            "occurrence": [{"phase": phase, "event": event, "probability": 0.6}],
            "findings": [],
            "probable_cause": "x",
            "lay_explanation": "x",
            "confidence": 0.6,
            "abstain": False,
            "evidence_used": [],
        }
    )


def test_measures_scores_answered_cases_and_counts_failed_ones_as_wrong() -> None:
    tables = load_tables()
    code = tables.compose_occurrence("552", "230")
    verdicts = {
        "A": Verdict(
            probable_cause="c",
            occurrence_codes=(code,),
            finding_codes=(),
            finding_codes_in_cause=(),
        ),
        "B": Verdict(
            probable_cause="c",
            occurrence_codes=(code,),
            finding_codes=("0206301544",),
            finding_codes_in_cause=("0206301544",),
        ),
    }
    rows = [
        CodingCase(case_id="A", hypothesis=_hypothesis("552", "230"), failure=None, cost_usd=0.0),
        CodingCase(case_id="B", hypothesis=None, failure="cap", cost_usd=0.0),
    ]
    got = pr.measures(rows, verdicts, tables, frozenset({code}))
    assert (got["A"].top1, got["A"].top3, got["A"].recall10) == (True, True, None)
    assert (got["B"].top1, got["B"].top3, got["B"].recall10) == (False, False, 0.0)


def test_paired_rows_use_only_cases_in_both_runs() -> None:
    a = {
        "1": pr.CaseMeasures(True, True, 0.5),
        "2": pr.CaseMeasures(False, True, None),
        "3": pr.CaseMeasures(True, True, 1.0),
    }
    b = {"1": pr.CaseMeasures(True, False, 1.0), "2": pr.CaseMeasures(True, True, 0.0)}
    diff, text = pr.paired(b, a)
    assert diff.top1 == pytest.approx(0.5)
    assert diff.top3 == pytest.approx(-0.5)
    assert diff.recall10 == pytest.approx(0.5)  # only case 1 has a recall in both
    assert "n=2" in text
    assert "n=1" in text


def test_learner_refusals_are_counted_by_category(tmp_path: Path) -> None:
    def row(key: str, stop: str | None, category: str | None, text: str | None) -> str:
        reply = claude.Reply(
            key=key,
            role="apply",
            model="m",
            effort="low",
            batch=True,
            text=text,
            stop_reason=stop,
            stop_category=category,
            error=None,
            input_tokens=1,
            output_tokens=1,
            cache_write_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
        )
        return reply.model_dump_json()

    folder = tmp_path / "learn"
    folder.mkdir()
    (folder / "calls.jsonl").write_text(
        "\n".join(
            [
                row("1", "refusal", "cyber", None),
                row("2", "refusal", None, None),
                row("3", "refusal", "cyber", None),
                row("4", "max_tokens", None, None),
                row("5", "end_turn", None, "{}"),
            ]
        )
        + "\n"
    )
    assert pr.refusals_by_category([folder]) == {"cyber": 2, "none": 1}
    assert json.loads(json.dumps(pr.refusals_by_category([folder])))
