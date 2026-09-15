"""Run, case and step records, and their JSON-lines I/O (spec §6.4)."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, parse_hypothesis
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    RunRecord,
    StepRecord,
    fingerprint,
    read_jsonl,
    write_jsonl,
)

TABLES = load_tables()


def _hypothesis() -> Hypothesis:
    body = {
        "evidence_narrative": "n",
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": 0.5,
        "abstain": False,
        "evidence_used": [],
        "occurrence": [{"phase": "551", "event": "230", "probability": 0.5}],
        "findings": [],
    }
    return parse_hypothesis(json.dumps(body), TABLES)


def _step(**overrides: object) -> StepRecord:
    fields: dict[str, object] = {
        "case_id": "WPR24LA029",
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
        "payload_fingerprint": "abc123",
        "hypothesis": _hypothesis(),
        "observed_effect": "",
        "stop_reason": "answered",
        "model": "openai/gpt-5.6-luna",
        "price_variant": "sync",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost_usd": 0.001,
        "cumulative_cost_usd": 0.001,
        "commit_sha": "abc1234",
        "dirty": False,
    }
    fields.update(overrides)
    return StepRecord.model_validate(fields)


def test_fingerprint_is_the_sha256_of_the_rendered_payload() -> None:
    evidence = Evidence(case_id="x", docket_url=None, phase_of_flight="Landing")
    payload = Payload.from_evidence(evidence)
    assert fingerprint(payload) == hashlib.sha256(payload.text.encode()).hexdigest()


def test_run_record_round_trips_through_jsonl(tmp_path: Path) -> None:
    run = RunRecord(
        run_id="20260915-0001-abc1234",
        sample="dev-400",
        arm="A",
        exclusions=("registration",),
        includes=(),
        prompt_version="v1",
        model="openai/gpt-5.6-luna",
        price_variant="sync",
        cap_usd=0.5,
        budget_usd=25.0,
        commit_sha="abc1234",
        dirty=False,
        started=datetime(2026, 9, 15, tzinfo=UTC),
    )
    path = tmp_path / "runs.jsonl"
    write_jsonl(path, [run])
    write_jsonl(path, [run])
    assert read_jsonl(path, RunRecord) == [run, run]


def test_step_and_case_result_round_trip_through_jsonl(tmp_path: Path) -> None:
    step = _step()
    result = CaseResult(
        case_id="WPR24LA029",
        split="heldout",
        fatal=False,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=("550000",),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(step,),
        scores=None,
        cost_usd=0.001,
        failure=None,
    )
    path = tmp_path / "results.jsonl"
    write_jsonl(path, [result])
    assert read_jsonl(path, CaseResult) == [result]


def test_records_are_frozen_and_forbid_extra_fields() -> None:
    step = _step()
    with pytest.raises(ValidationError):
        step.step = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _step(unexpected="nope")
