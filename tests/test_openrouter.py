import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.batch import BatchClient, BatchRequest
from ntsb_probable_cause.model.client import (
    ModelSettings,
    PageImage,
    Payload,
    ToolCall,
    ToolText,
    Turn,
    cost_usd,
    parse_chat_completion,
)
from ntsb_probable_cause.model.openrouter import OpenRouterClient, request_body
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record

FIX = Path("tests/fixtures/openrouter")
URL = "https://openrouter.ai/api/v1/chat/completions"
EVIDENCE = Evidence(case_id="X", docket_url=None, aircraft_make="CESSNA", phase_of_flight="Landing")


def saved(name: str) -> dict[str, object]:
    return cast("dict[str, object]", json.loads((FIX / f"{name}.json").read_text()))


def saved_response(name: str) -> Mapping[str, object]:
    return cast("Mapping[str, object]", saved(name)["response"])


def test_parse_structured_reply_from_saved_response() -> None:
    reply = parse_chat_completion(saved_response("structured"))
    assert reply.content
    assert json.loads(reply.content)["phase"]
    assert reply.tool_calls == ()
    assert reply.usage.prompt_tokens > 0
    assert reply.usage.completion_tokens > 0
    assert reply.response_id == "redacted"


def test_parse_tool_call_reply_from_saved_response() -> None:
    reply = parse_chat_completion(saved_response("tool_call"))
    assert reply.tool_calls[0].name == "get_weather"
    assert json.loads(reply.tool_calls[0].arguments) == {}


def test_parse_two_turn_reply_from_saved_response() -> None:
    reply = parse_chat_completion(saved_response("two_turn"))
    assert reply.content is not None


def test_parse_reads_reasoning_tokens_from_completion_tokens_details() -> None:
    """S2.6 Task 9A: GPT-6 Luna's reasoning tokens count against the reply budget."""
    reply = parse_chat_completion(saved_response("structured"))
    assert reply.usage.reasoning_tokens == 161


def test_parse_reasoning_tokens_is_none_without_completion_tokens_details() -> None:
    body = dict(saved_response("structured"))
    usage = dict(cast("Mapping[str, object]", body["usage"]))
    del usage["completion_tokens_details"]
    body["usage"] = usage
    reply = parse_chat_completion(body)
    assert reply.usage.reasoning_tokens is None


def test_cost_uses_reported_cost_when_present_else_price_table() -> None:
    reply = parse_chat_completion(saved_response("structured"))
    settings = ModelSettings(model="openai/gpt-5.6-luna", price_variant="standard")
    dollars, how = cost_usd(reply, settings)
    if reply.usage.reported_cost_usd is not None:
        assert how == "reported"
        assert dollars == reply.usage.reported_cost_usd
    else:
        expected = (
            reply.usage.prompt_tokens * 0.20 / 1e6 + reply.usage.completion_tokens * 1.20 / 1e6
        )
        assert how == "priced"
        assert dollars == pytest.approx(expected)


def test_model_id_appends_batch_suffix() -> None:
    assert ModelSettings(model="openai/gpt-5.6-luna").model_id() == "openai/gpt-5.6-luna:batch"
    assert (
        ModelSettings(model="openai/gpt-5.6-luna", price_variant="standard").model_id()
        == "openai/gpt-5.6-luna"
    )


def test_client_sends_schema_system_and_history(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json=saved_response("two_turn"))
    )
    client = OpenRouterClient("or-key", sleep=lambda _s: None)
    settings = ModelSettings(
        model="openai/gpt-5.6-luna",
        json_schema={"type": "object"},
        schema_name="mini",
        price_variant="standard",
    )
    history = (
        Turn(
            role="assistant",
            tool_calls=(
                saved_tool_call := parse_chat_completion(saved_response("tool_call")).tool_calls
            ),
        ),
        Turn(
            role="tool",
            tool_call_id=saved_tool_call[0].call_id,
            payload=Payload.from_evidence(EVIDENCE),
        ),
    )
    client.complete(Payload.from_evidence(EVIDENCE), settings, system="SYS", history=history)
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "openai/gpt-5.6-luna"
    assert sent["messages"][0] == {"role": "system", "content": "SYS"}
    assert sent["messages"][1]["role"] == "user"
    assert "CESSNA" in sent["messages"][1]["content"]
    assert sent["messages"][2]["role"] == "assistant"
    assert sent["messages"][3]["role"] == "tool"
    assert sent["response_format"]["json_schema"]["name"] == "mini"
    assert sent["temperature"] == 0
    assert route.calls[0].request.headers["authorization"] == "Bearer or-key"


def test_request_body_renders_a_tool_turn_from_its_payload(
    record_fixtures: list[dict[str, object]],
) -> None:
    evidence, _, _ = split_record(record_fixtures[0])
    payload = Payload.from_evidence(evidence)
    history = (
        Turn(
            role="assistant",
            content=None,
            tool_calls=(ToolCall(call_id="c1", name="list_docket", arguments="{}"),),
        ),
        Turn(role="tool", tool_call_id="c1", payload=payload),
    )
    body = request_body(payload, ModelSettings(), system="s", history=history)
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": payload.text}


def test_client_retries_then_raises(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(URL).mock(return_value=httpx.Response(503, text="down"))
    sleeps: list[float] = []
    client = OpenRouterClient("k", sleep=sleeps.append, max_attempts=3, backoff_seconds=1.0)
    with pytest.raises(ModelError, match="3 attempts"):
        client.complete(Payload.from_evidence(EVIDENCE), ModelSettings())
    assert sleeps.count(1.0) == 1
    assert sleeps.count(2.0) == 1


def test_request_json_sends_once_when_retry_is_off(respx_mock: respx.MockRouter) -> None:
    """A non-idempotent request is sent exactly once, however retryable the failure looks.

    The failure this prevents: a batch submission the server accepted, whose response then
    times out, is posted again. Both batches are billed, only the second id is returned, and
    OpenRouter has no cancel endpoint.
    """
    route = respx_mock.post("https://openrouter.ai/api/beta/batches").mock(
        return_value=httpx.Response(503, text="down")
    )
    sleeps: list[float] = []
    client = OpenRouterClient("k", sleep=sleeps.append, max_attempts=5, backoff_seconds=1.0)
    with pytest.raises(ModelError, match="was not retried"):
        client.request_json("/api/beta/batches", method="POST", body={}, retry=False)
    assert route.call_count == 1
    assert sleeps == []


def test_batch_submit_is_never_retried(respx_mock: respx.MockRouter) -> None:
    """The real call path: BatchClient.submit must not retry, whatever the client allows."""
    route = respx_mock.post("https://openrouter.ai/api/beta/batches").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    client = OpenRouterClient("k", sleep=lambda _s: None, max_attempts=5)
    with pytest.raises(ModelError, match="was not retried"):
        BatchClient(client).submit(
            [
                BatchRequest(
                    custom_id="c1",
                    payload=Payload.from_evidence(EVIDENCE),
                    settings=ModelSettings(),
                )
            ]
        )
    assert route.call_count == 1


def test_client_does_not_retry_a_400(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(URL).mock(return_value=httpx.Response(400, text="bad schema"))
    with pytest.raises(ModelError, match="400"):
        OpenRouterClient("k", sleep=lambda _s: None).complete(
            Payload.from_evidence(EVIDENCE), ModelSettings()
        )


def test_client_applies_rate_limit_gap_between_successful_calls(
    respx_mock: respx.MockRouter,
) -> None:
    """Deviation resolution: the per-request rate-limit gap still applies between two successes."""
    respx_mock.post(URL).mock(return_value=httpx.Response(200, json=saved_response("structured")))
    sleeps: list[float] = []
    client = OpenRouterClient("k", sleep=sleeps.append, requests_per_minute=60)
    client.complete(Payload.from_evidence(EVIDENCE), ModelSettings())
    client.complete(Payload.from_evidence(EVIDENCE), ModelSettings())
    assert sleeps.count(1.0) == 1


def test_request_body_states_the_reasoning_level_when_set(
    record_fixtures: list[dict[str, object]],
) -> None:
    """S2.4 spec §4.1: the agent's level is stated, never left to the provider's default."""
    evidence, _, _ = split_record(record_fixtures[0])
    payload = Payload.from_evidence(evidence)
    settings = ModelSettings(reasoning_effort="medium")
    body = request_body(payload, settings, system="s", history=())
    assert body["reasoning"] == {"effort": "medium"}


def test_request_body_sends_no_reasoning_key_when_unset(
    record_fixtures: list[dict[str, object]],
) -> None:
    """The judge's calls (no level set) are byte-for-byte what they were before S2.4."""
    evidence, _, _ = split_record(record_fixtures[0])
    payload = Payload.from_evidence(evidence)
    body = request_body(payload, ModelSettings(), system="s", history=())
    assert "reasoning" not in body


def test_request_body_sends_image_parts_after_the_text() -> None:
    image = PageImage(media_type="image/jpeg", data=b"\xff\xd8jpeg")
    body = request_body(
        Payload.for_page(image, text_layer="typed words"),
        ModelSettings(model="google/gemini-3.1-flash-lite", price_variant="standard"),
        system="instruction",
        history=(),
    )
    assert body["messages"] == [
        {"role": "system", "content": "instruction"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "typed words"},
                {"type": "image_url", "image_url": {"url": image.data_url()}},
            ],
        },
    ]


def test_an_image_page_with_no_text_layer_sends_the_image_alone() -> None:
    image = PageImage(media_type="image/jpeg", data=b"\xff\xd8jpeg")
    body = request_body(Payload.for_page(image), ModelSettings(), system="s", history=())
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["content"] == [{"type": "image_url", "image_url": {"url": image.data_url()}}]


# --- S3.1 Task 3: the seam for native tools -----------------------------------------------------


def test_parse_reads_cached_tokens_from_prompt_tokens_details() -> None:
    reply = parse_chat_completion(saved_response("tool_call"))
    assert reply.usage.cached_tokens == 0


def test_parse_cached_tokens_is_none_without_prompt_tokens_details() -> None:
    body = dict(saved_response("tool_call"))
    usage = dict(cast("Mapping[str, object]", body["usage"]))
    del usage["prompt_tokens_details"]
    body["usage"] = usage
    assert parse_chat_completion(body).usage.cached_tokens is None


def test_parse_cached_tokens_is_none_when_the_details_omit_it() -> None:
    body = dict(saved_response("tool_call"))
    usage = dict(cast("Mapping[str, object]", body["usage"]))
    usage["prompt_tokens_details"] = {"audio_tokens": 0}
    body["usage"] = usage
    assert parse_chat_completion(body).usage.cached_tokens is None


def test_parse_reads_reasoning_details_from_the_saved_response() -> None:
    reply = parse_chat_completion(saved_response("structured"))
    assert reply.reasoning_details
    assert all(isinstance(detail, dict) for detail in reply.reasoning_details)
    assert reply.reasoning_details[0]["type"] == "reasoning.summary"


def test_parse_reasoning_details_is_empty_when_absent_or_null() -> None:
    absent = parse_chat_completion(saved_response("tool_call"))
    assert absent.reasoning_details == ()
    body = json.loads(json.dumps(saved_response("structured")))
    body["choices"][0]["message"]["reasoning_details"] = None
    assert parse_chat_completion(body).reasoning_details == ()


def test_parse_refuses_reasoning_details_that_are_not_objects() -> None:
    body = json.loads(json.dumps(saved_response("structured")))
    body["choices"][0]["message"]["reasoning_details"] = ["not an object"]
    with pytest.raises(ModelError, match="chat completion"):
        parse_chat_completion(body)


def test_request_body_sends_no_tool_keys_unless_set(
    record_fixtures: list[dict[str, object]],
) -> None:
    """A run that sets neither new field sends exactly the keys it sent before S3.1."""
    evidence, _, _ = split_record(record_fixtures[0])
    body = request_body(Payload.from_evidence(evidence), ModelSettings(), system="s", history=())
    assert set(body) == {"model", "messages", "temperature", "max_tokens", "usage"}


def test_request_body_states_tool_choice_and_parallel_tool_calls_when_set(
    record_fixtures: list[dict[str, object]],
) -> None:
    evidence, _, _ = split_record(record_fixtures[0])
    payload = Payload.from_evidence(evidence)
    forced = {"type": "function", "function": {"name": "submit_answer"}}
    body = request_body(
        payload,
        ModelSettings(tool_choice=forced, parallel_tool_calls=False),
        system="s",
        history=(),
    )
    assert body["tool_choice"] == forced
    assert body["parallel_tool_calls"] is False
    body = request_body(
        payload,
        ModelSettings(tool_choice="required", parallel_tool_calls=True),
        system="s",
        history=(),
    )
    assert body["tool_choice"] == "required"
    assert body["parallel_tool_calls"] is True


def _tool_history(tool_turn: Turn) -> tuple[Turn, ...]:
    return (
        Turn(
            role="assistant",
            content=None,
            tool_calls=(ToolCall(call_id="c1", name="look_up", arguments="{}"),),
        ),
        tool_turn,
    )


def test_a_tool_turn_with_a_payload_and_tool_text_renders_both_in_order() -> None:
    payload = Payload.from_evidence(EVIDENCE)
    turn = Turn(
        role="tool", tool_call_id="c1", payload=payload, tool_text=ToolText.of("2 codes listed")
    )
    body = request_body(payload, ModelSettings(), system="s", history=_tool_history(turn))
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": payload.text + "\n\n" + "2 codes listed",
    }


def test_a_tool_turn_with_only_tool_text_renders_it() -> None:
    turn = Turn(role="tool", tool_call_id="c1", tool_text=ToolText.of("2 codes listed"))
    body = request_body(
        Payload.from_evidence(EVIDENCE), ModelSettings(), system="s", history=_tool_history(turn)
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "2 codes listed"}


def test_reasoning_details_are_sent_back_only_with_pass_reasoning() -> None:
    details = ({"type": "reasoning.summary", "summary": "the gear was down"},)
    history = (
        Turn(
            role="assistant",
            content=None,
            tool_calls=(ToolCall(call_id="c1", name="look_up", arguments="{}"),),
            reasoning_details=details,
        ),
        Turn(role="tool", tool_call_id="c1", tool_text=ToolText.of("ok")),
    )
    payload = Payload.from_evidence(EVIDENCE)
    off = request_body(payload, ModelSettings(), system="s", history=history)
    on = request_body(payload, ModelSettings(pass_reasoning=True), system="s", history=history)
    off_messages = off["messages"]
    on_messages = on["messages"]
    assert isinstance(off_messages, list)
    assert isinstance(on_messages, list)
    assert "reasoning_details" not in off_messages[2]
    assert on_messages[2]["reasoning_details"] == list(details)


def test_pass_reasoning_adds_nothing_to_a_turn_without_reasoning_details() -> None:
    history = (Turn(role="assistant", content="earlier answer"),)
    body = request_body(
        Payload.from_evidence(EVIDENCE),
        ModelSettings(pass_reasoning=True),
        system="",
        history=history,
    )
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[-1] == {"role": "assistant", "content": "earlier answer"}


def test_batch_submit_carries_the_tool_keys_and_tool_turns(
    respx_mock: respx.MockRouter,
) -> None:
    """``BatchClient.submit`` reuses ``request_body``, so the new keys ride in every request."""
    route = respx_mock.post("https://openrouter.ai/api/beta/batches").mock(
        return_value=httpx.Response(202, json={"id": "b-tools", "status": "validating"})
    )
    forced = {"type": "function", "function": {"name": "submit_answer"}}
    details = ({"type": "reasoning.summary", "summary": "s"},)
    history = (
        Turn(
            role="assistant",
            content=None,
            tool_calls=(ToolCall(call_id="c1", name="look_up", arguments="{}"),),
            reasoning_details=details,
        ),
        Turn(role="tool", tool_call_id="c1", tool_text=ToolText.of("ok")),
    )
    BatchClient(OpenRouterClient("k", sleep=lambda _s: None)).submit(
        [
            BatchRequest(
                custom_id="case-1",
                payload=Payload.from_evidence(EVIDENCE),
                settings=ModelSettings(
                    tool_choice=forced,
                    parallel_tool_calls=False,
                    pass_reasoning=True,
                    tools=({"type": "function", "function": {"name": "submit_answer"}},),
                ),
                history=history,
            )
        ]
    )
    sent = json.loads(route.calls[0].request.content)["requests"][0]["body"]
    assert sent["tool_choice"] == forced
    assert sent["parallel_tool_calls"] is False
    assert sent["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": "ok"}
    assert sent["messages"][-2]["reasoning_details"] == list(details)
