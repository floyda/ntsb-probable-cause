import copy
import json
from typing import cast

import pydantic
import pytest

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import WITHHELD_ROLE_NAMES, EvidenceRole
from ntsb_probable_cause.records.evidence import BOOKKEEPING_FIELDS, Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.records import RunRecord, StepRecord


def test_evidence_schema_is_exactly_the_evidence_roles_plus_bookkeeping() -> None:
    names = set(Evidence.model_fields)
    assert names == {r.value for r in EvidenceRole} | BOOKKEEPING_FIELDS
    assert not names & WITHHELD_ROLE_NAMES


def test_evidence_rejects_extra_attributes() -> None:
    with pytest.raises(pydantic.ValidationError):
        Evidence(case_id="X", docket_url=None, probable_cause="leak")  # type: ignore[call-arg]


def test_split_matches_field_extractors_on_every_fixture(
    record_fixtures: list[dict[str, object]],
) -> None:
    for raw in record_fixtures:
        evidence, synthesis, verdict = split_record(raw)
        assert evidence.case_id == raw["ntsbNumber"]
        assert evidence.docket_url == f"https://data.ntsb.gov/Docket?ProjectID={raw['mKey']}"
        assert evidence.role_values() == {f.role: f.extract(raw) for f in fields.EVIDENCE_FIELDS}
        assert synthesis.factual_narrative == fields.factual_narrative(raw)
        assert synthesis.analysis_narrative == fields.analysis_narrative(raw)
        assert verdict.probable_cause == fields.probable_cause(raw)
        assert verdict.occurrence_codes == fields.occurrence_codes(raw)
        assert verdict.finding_codes == fields.finding_codes(raw)


def test_every_fixture_has_withheld_content_to_protect(
    record_fixtures: list[dict[str, object]],
) -> None:
    for raw in record_fixtures:
        _, synthesis, verdict = split_record(raw)
        assert verdict.probable_cause
        assert verdict.occurrence_codes
        assert synthesis.analysis_narrative or synthesis.factual_narrative


def test_exclude_removes_a_role_for_ablation(record_fixtures: list[dict[str, object]]) -> None:
    raw = record_fixtures[0]
    evidence, _, _ = split_record(raw, exclude=frozenset({EvidenceRole.REGISTRATION}))
    assert evidence.registration is None
    assert EvidenceRole.REGISTRATION not in evidence.role_values()
    assert evidence.case_id == raw["ntsbNumber"]
    assert evidence.docket_url == f"https://data.ntsb.gov/Docket?ProjectID={raw['mKey']}"


def test_missing_case_number_is_rejected() -> None:
    with pytest.raises(ValueError, match="ntsbNumber"):
        split_record({})


def test_verdict_carries_flagged_findings(record_fixtures: list[dict[str, object]]) -> None:
    for raw in record_fixtures:
        _, _, verdict = split_record(raw)
        assert set(verdict.finding_codes_in_cause) <= set(verdict.finding_codes)
        aircrafts = cast("list[dict[str, object]]", raw["aircrafts"])
        findings = cast("list[dict[str, object]]", aircrafts[0]["findings"])
        ordered = sorted(findings, key=lambda f: cast("int", f.get("findingNumber") or 0))
        flagged = [f["findingCode"] for f in ordered if f.get("inProbableCause")]
        assert list(verdict.finding_codes_in_cause) == flagged


def test_tripwire_fires_when_a_record_carries_withheld_text_in_evidence(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = copy.deepcopy(record_fixtures[0])
    narratives = cast("list[dict[str, object]]", raw["narratives"])
    probable_cause = cast("str", narratives[0]["probableCause"])
    narratives[0]["prelimNarrative"] = probable_cause
    with pytest.raises(LeakageError, match="probable_cause") as exc_info:
        split_record(raw)
    message = str(exc_info.value)
    assert probable_cause.lower() not in message.lower()
    assert exc_info.value.leaks


GOOD = json.dumps(
    {
        "evidence_narrative": "n",
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": 0.7,
        "abstain": False,
        "evidence_used": ["phase_of_flight"],
        "occurrence": [{"phase": "552", "event": "230", "probability": 0.7}],
        "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
    }
)


def test_step_record_document_fields_default_empty(run_record: RunRecord) -> None:
    hypothesis = parse_hypothesis(GOOD, load_tables())
    step = StepRecord(
        case_id="X",
        step=0,
        arm="B",
        condition="full",
        day=None,
        tool="docket",
        arguments={"documents": [1, 2]},
        reason="",
        expected_effect="",
        returned_roles=(),
        not_available=("3: unreadable: scan",),
        payload_fingerprint="f",
        hypothesis=hypothesis,
        observed_effect="",
        stop_reason="answered",
        model="m",
        price_variant="batch",
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=0.0,
        cumulative_cost_usd=0.0,
        commit_sha="abc",
        dirty=False,
    )
    assert step.documents_attached == ()
    assert step.documents_not_read == ()
