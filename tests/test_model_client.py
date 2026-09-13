import json

import pytest

from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import ModelSettings, Payload, RecordingFakeClient
from ntsb_probable_cause.records.evidence import Evidence

EVIDENCE = Evidence(
    case_id="CEN16LA999",
    docket_url="https://data.ntsb.gov/Docket?ProjectID=1",
    aircraft_make="CESSNA",
    pilot_certificates=("Private",),
    pilot_total_hours=250.0,
)


def test_payload_contains_only_non_null_evidence_roles_and_no_bookkeeping() -> None:
    payload = Payload.from_evidence(EVIDENCE)
    assert payload.fields() == {
        "aircraft_make": "CESSNA",
        "pilot_certificates": ["Private"],
        "pilot_total_hours": 250.0,
    }
    assert "CEN16LA999" not in payload.text
    assert "ProjectID" not in payload.text


def test_payload_text_is_deterministic_json() -> None:
    assert Payload.from_evidence(EVIDENCE).text == Payload.from_evidence(EVIDENCE).text
    assert list(json.loads(Payload.from_evidence(EVIDENCE).text)) == sorted(
        json.loads(Payload.from_evidence(EVIDENCE).text)
    )


def test_excluded_roles_are_not_rendered() -> None:
    evidence = EVIDENCE.model_copy(update={"excluded": frozenset({EvidenceRole.AIRCRAFT_MAKE})})
    assert "aircraft_make" not in Payload.from_evidence(evidence).fields()


def test_payload_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError, match="from_evidence"):
        Payload('{"probable_cause": "leak"}', _token=object())


def test_recording_fake_records_payloads_and_replays_replies() -> None:
    client = RecordingFakeClient(replies=("first", "second"))
    payload = Payload.from_evidence(EVIDENCE)
    replies = [client.complete(payload, ModelSettings()).text for _ in range(3)]
    assert replies == ["first", "second", "second"]
    assert client.payloads == [payload, payload, payload]
