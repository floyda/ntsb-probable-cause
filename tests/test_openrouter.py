import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import (
    ModelSettings,
    Payload,
    Turn,
    cost_usd,
    parse_chat_completion,
)
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.records.evidence import Evidence

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
        json_schema={"type": "object"}, schema_name="mini", price_variant="standard"
    )
    history = (
        Turn(
            role="assistant",
            tool_calls=(
                saved_tool_call := parse_chat_completion(saved_response("tool_call")).tool_calls
            ),
        ),
        Turn(role="tool", tool_call_id=saved_tool_call[0].call_id, content="{}"),
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


def test_client_retries_then_raises(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(URL).mock(return_value=httpx.Response(503, text="down"))
    sleeps: list[float] = []
    client = OpenRouterClient("k", sleep=sleeps.append, max_attempts=3, backoff_seconds=1.0)
    with pytest.raises(ModelError, match="3 attempts"):
        client.complete(Payload.from_evidence(EVIDENCE), ModelSettings())
    assert sleeps.count(1.0) == 1
    assert sleeps.count(2.0) == 1


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
