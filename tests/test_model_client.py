import json

import pytest
from pydantic import ValidationError

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model import client as model_client
from ntsb_probable_cause.model.client import (
    ModelSettings,
    PageImage,
    Payload,
    RecordingFakeClient,
    Turn,
)
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record

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


def test_payload_is_immutable_after_construction() -> None:
    payload = Payload.from_evidence(EVIDENCE)
    with pytest.raises(AttributeError):
        payload._text = "tampered"
    with pytest.raises(AttributeError):
        del payload._text


def test_render_check_error_names_the_offending_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """A role that overlaps a withheld name must be named in the error, not print an empty list.

    Realistic mutation: a name added to a withheld role set collides with an existing evidence
    role. Before the fix, the error's key list was always computed as ``keys - _EVIDENCE_NAMES``,
    which is empty whenever every sent key is already a legitimate evidence role -- exactly this
    case -- so the message printed ``[]`` instead of naming the offending role.
    """
    monkeypatch.setattr(model_client, "WITHHELD_ROLE_NAMES", frozenset({"aircraft_make"}))
    with pytest.raises(LeakageError, match=r"\['aircraft_make'\]"):
        Payload.from_evidence(EVIDENCE)


def test_fake_replays_scripted_replies() -> None:
    client = RecordingFakeClient(replies=("first", "second"))
    payload = Payload.from_evidence(EVIDENCE)
    replies = [client.complete(payload, ModelSettings()).content for _ in range(3)]
    assert replies == ["first", "second", "second"]
    assert client.payloads == [payload, payload, payload]


def _payload(record_fixtures: list[dict[str, object]]) -> Payload:
    evidence, _, _ = split_record(record_fixtures[0])
    return Payload.from_evidence(evidence)


def test_tool_turn_carries_a_payload(record_fixtures: list[dict[str, object]]) -> None:
    turn = Turn(role="tool", tool_call_id="c1", payload=_payload(record_fixtures))
    assert turn.payload is not None
    assert turn.content is None


def test_tool_turn_refuses_plain_text() -> None:
    with pytest.raises(ValidationError, match="Payload"):
        Turn(role="tool", tool_call_id="c1", content="unchecked text")


def test_tool_turn_without_a_payload_is_refused() -> None:
    with pytest.raises(ValidationError, match="Payload"):
        Turn(role="tool", tool_call_id="c1")


def test_assistant_turn_refuses_a_payload(record_fixtures: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError, match="assistant"):
        Turn(role="assistant", content="ok", payload=_payload(record_fixtures))


def test_a_page_payload_carries_one_image_and_only_its_text_layer() -> None:
    image = PageImage(media_type="image/jpeg", data=b"\xff\xd8jpeg")
    plain = Payload.for_page(image)
    mixed = Payload.for_page(image, text_layer="FUEL SELECTOR: BOTH")
    assert plain.images == (image,)
    assert plain.text == ""
    assert mixed.text == "FUEL SELECTOR: BOTH"
    assert image.data_url().startswith("data:image/jpeg;base64,")
    assert plain != mixed


def test_an_evidence_payload_has_no_images_unless_given(
    record_fixtures: list[dict[str, object]],
) -> None:
    evidence, _, _ = split_record(record_fixtures[0])
    assert Payload.from_evidence(evidence).images == ()
