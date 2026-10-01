import ast
import inspect
import json

import pytest
from pydantic import ValidationError

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model import client as model_client
from ntsb_probable_cause.model import tool_text as tool_text_module
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    PageImage,
    Payload,
    RecordingFakeClient,
    ToolCall,
    ToolText,
    Turn,
    Usage,
    cost_usd,
    tool_reply,
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


def test_the_agent_payload_takes_no_images() -> None:
    """S2.6 final review, I2: the tripwire cannot screen a picture, so the one payload
    assembler takes evidence alone; images reach a model only through ``for_page``."""
    assert list(inspect.signature(Payload.from_evidence).parameters) == ["evidence"]


# --- S3.1 Task 3: the seam for native tools -----------------------------------------------------


def test_new_settings_and_usage_fields_default_to_off() -> None:
    settings = ModelSettings()
    assert settings.tool_choice is None
    assert settings.parallel_tool_calls is None
    assert settings.pass_reasoning is False
    assert Usage(prompt_tokens=1, completion_tokens=1).cached_tokens is None


def test_a_reply_has_no_reasoning_details_unless_given() -> None:
    reply = ModelReply(
        content="x",
        usage=Usage(prompt_tokens=1, completion_tokens=1),
        model="m",
        response_id="r",
    )
    assert reply.reasoning_details == ()


def test_tool_text_is_built_only_by_of() -> None:
    text = ToolText.of("3 results; codes 130100, 130200")
    assert text.text == "3 results; codes 130100, 130200"
    assert text == ToolText.of("3 results; codes 130100, 130200")
    assert text != ToolText.of("other")
    assert hash(text) == hash(ToolText.of("3 results; codes 130100, 130200"))
    with pytest.raises(TypeError, match=r"ToolText\.of"):
        ToolText("free text", _token=object())


def test_tool_text_is_immutable_after_construction() -> None:
    text = ToolText.of("fixed")
    with pytest.raises(AttributeError):
        text._text = "tampered"
    with pytest.raises(AttributeError):
        del text._text


def test_tool_text_cannot_be_made_from_a_payload_or_evidence() -> None:
    """Tool text is non-evidence: nothing the split produced may be wrapped as tool text."""
    with pytest.raises(TypeError, match="str"):
        ToolText.of(Payload.from_evidence(EVIDENCE))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="str"):
        ToolText.of(EVIDENCE)  # type: ignore[arg-type]


def test_the_two_construction_tokens_are_not_interchangeable() -> None:
    """A Payload cannot be made with ToolText's token, nor ToolText with Payload's."""
    with pytest.raises(TypeError, match="from_evidence"):
        Payload("text", _token=tool_text_module._TOOL_TEXT_TOKEN)
    with pytest.raises(TypeError, match=r"ToolText\.of"):
        ToolText("text", _token=model_client._CONSTRUCTION_TOKEN)


def test_tool_text_lives_apart_from_the_records_and_is_re_exported() -> None:
    """S3.1 Task 10: one class, defined in ``model.tool_text``, importable from both modules.

    ``model.tool_text`` imports nothing from the library, so the agent's tools reach no case
    record through it; ``model.client`` re-exports the same class for every earlier import.
    """
    assert model_client.ToolText is tool_text_module.ToolText
    assert ToolText.__module__ == "ntsb_probable_cause.model.tool_text"
    tree = ast.parse(inspect.getsource(tool_text_module))
    imported = [
        name
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
    ]
    assert imported == ["typing"]


def test_a_payload_cannot_be_made_from_tool_text() -> None:
    tool_text = ToolText.of("numbers only")
    with pytest.raises(TypeError, match="from_evidence"):
        Payload(tool_text, _token=object())  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        Payload.from_evidence(tool_text)  # type: ignore[arg-type]


def test_tool_turn_carries_tool_text_alone() -> None:
    turn = Turn(role="tool", tool_call_id="c1", tool_text=ToolText.of("ok"))
    assert turn.payload is None
    assert turn.tool_text is not None
    assert turn.content is None


def test_tool_turn_carries_a_payload_and_tool_text(
    record_fixtures: list[dict[str, object]],
) -> None:
    turn = Turn(
        role="tool",
        tool_call_id="c1",
        payload=_payload(record_fixtures),
        tool_text=ToolText.of("ok"),
    )
    assert turn.payload is not None
    assert turn.tool_text is not None


def test_tool_turn_without_a_call_id_is_refused(record_fixtures: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError, match="tool_call_id"):
        Turn(role="tool", tool_text=ToolText.of("ok"))
    with pytest.raises(ValidationError, match="tool_call_id"):
        Turn(role="tool", payload=_payload(record_fixtures))


def test_tool_turn_with_tool_text_still_refuses_plain_content() -> None:
    with pytest.raises(ValidationError, match="never as text"):
        Turn(role="tool", tool_call_id="c1", content="text", tool_text=ToolText.of("ok"))


def test_assistant_turn_refuses_tool_text() -> None:
    with pytest.raises(ValidationError, match="assistant"):
        Turn(role="assistant", content="ok", tool_text=ToolText.of("ok"))


def test_tool_turn_refuses_reasoning_details() -> None:
    """Reasoning belongs to the model's own turn; on a tool turn it would be dropped unseen."""
    with pytest.raises(ValidationError, match="reasoning"):
        Turn(
            role="tool",
            tool_call_id="c1",
            tool_text=ToolText.of("ok"),
            reasoning_details=({"type": "reasoning.summary"},),
        )


def test_assistant_turn_carries_reasoning_details() -> None:
    turn = Turn(role="assistant", reasoning_details=({"type": "reasoning.summary"},))
    assert turn.reasoning_details == ({"type": "reasoning.summary"},)


def test_fake_returns_a_scripted_reply_unchanged() -> None:
    scripted = tool_reply("record_hypothesis", '{"a": 1}')
    client = RecordingFakeClient(replies=(scripted, "text"))
    payload = Payload.from_evidence(EVIDENCE)
    first = client.complete(payload, ModelSettings())
    second = client.complete(payload, ModelSettings())
    assert first is scripted
    assert first.tool_calls == (
        ToolCall(call_id="c1", name="record_hypothesis", arguments='{"a": 1}'),
    )
    assert first.finish_reason == "tool_calls"
    assert first.content is None
    assert second.content == "text"
    assert second.tool_calls == ()


def test_fake_repeats_the_last_scripted_reply() -> None:
    scripted = tool_reply("submit_answer", "{}", call_id="c9")
    client = RecordingFakeClient(replies=(scripted,))
    payload = Payload.from_evidence(EVIDENCE)
    replies = [client.complete(payload, ModelSettings()) for _ in range(2)]
    assert replies == [scripted, scripted]


def test_tool_reply_takes_a_call_id_and_usage() -> None:
    usage = Usage(prompt_tokens=10, completion_tokens=2, cached_tokens=4)
    reply = tool_reply("f", "{}", call_id="zz", usage=usage)
    assert reply.tool_calls[0].call_id == "zz"
    assert reply.usage == usage
    assert tool_reply("f", "{}").usage == Usage(prompt_tokens=0, completion_tokens=0)


def test_cached_tokens_are_recorded_not_priced() -> None:
    """Until a measured cached price exists, cost is what it was: cached tokens change nothing."""
    settings = ModelSettings(price_variant="standard")

    def reply_with(cached: int | None) -> ModelReply:
        return ModelReply(
            content="x",
            usage=Usage(prompt_tokens=1000, completion_tokens=100, cached_tokens=cached),
            model="m",
            response_id="r",
        )

    assert cost_usd(reply_with(800), settings) == cost_usd(reply_with(None), settings)
    assert cost_usd(reply_with(800), settings)[1] == "priced"
