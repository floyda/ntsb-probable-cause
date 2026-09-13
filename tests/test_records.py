import copy
from typing import cast

import pydantic
import pytest

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import WITHHELD_ROLE_NAMES, EvidenceRole
from ntsb_probable_cause.records.evidence import BOOKKEEPING_FIELDS, Evidence
from ntsb_probable_cause.records.split import split_record


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
    evidence, _, _ = split_record(
        record_fixtures[0], exclude=frozenset({EvidenceRole.REGISTRATION})
    )
    assert evidence.registration is None
    assert EvidenceRole.REGISTRATION not in evidence.role_values()


def test_missing_case_number_is_rejected() -> None:
    with pytest.raises(ValueError, match="ntsbNumber"):
        split_record({})


def test_tripwire_fires_when_a_record_carries_withheld_text_in_evidence(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = copy.deepcopy(record_fixtures[0])
    narratives = cast("list[dict[str, object]]", raw["narratives"])
    narratives[0]["prelimNarrative"] = narratives[0]["probableCause"]
    with pytest.raises(LeakageError, match="probable_cause"):
        split_record(raw)
