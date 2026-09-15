"""Tests for the OpenRouter batch client (submit, poll, collect)."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.batch import BatchClient, BatchRequest
from ntsb_probable_cause.model.client import ModelSettings, Payload, cost_usd
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.records.evidence import Evidence

FIX = json.loads(Path("tests/fixtures/openrouter/batch.json").read_text())
BASE = "https://openrouter.ai/api/beta/batches"
EVIDENCE = Evidence(case_id="X", docket_url=None, aircraft_make="PIPER")


def client() -> BatchClient:
    return BatchClient(OpenRouterClient("k", sleep=lambda _s: None))


def test_submit_sends_one_request_per_case_with_batch_model(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post(BASE).mock(
        return_value=httpx.Response(
            202, json={**FIX["response"], "status": "validating", "results": []}
        )
    )
    reqs = [
        BatchRequest(
            custom_id=f"case-{i}",
            payload=Payload.from_evidence(EVIDENCE),
            settings=ModelSettings(model="openai/gpt-5.6-luna"),
        )
        for i in range(3)
    ]
    batch_id = client().submit(reqs)
    assert batch_id == "redacted"
    sent = json.loads(route.calls[0].request.content)
    assert sent["endpoint"] == "/v1/chat/completions"
    assert sent["model"] == "openai/gpt-5.6-luna:batch"
    assert [r["custom_id"] for r in sent["requests"]] == ["case-0", "case-1", "case-2"]
    assert sent["requests"][0]["body"]["messages"][-1]["role"] == "user"


def test_submit_rejects_mixed_model_ids() -> None:
    reqs = [
        BatchRequest(
            custom_id="a",
            payload=Payload.from_evidence(EVIDENCE),
            settings=ModelSettings(model="openai/gpt-5.6-luna"),
        ),
        BatchRequest(
            custom_id="b",
            payload=Payload.from_evidence(EVIDENCE),
            settings=ModelSettings(model="openai/gpt-5.6-luna", price_variant="standard"),
        ),
    ]
    with pytest.raises(ModelError, match="one model id"):
        client().submit(reqs)


def test_wait_polls_until_terminal_and_parses_results(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/b1").mock(
        side_effect=[
            httpx.Response(200, json={**FIX["response"], "status": "in_progress", "results": []}),
            httpx.Response(200, json=FIX["response"]),
        ]
    )
    sleeps: list[float] = []
    status = client().wait("b1", every_seconds=5.0, sleep=sleeps.append)
    assert status.status == "completed"
    assert sleeps == [5.0]
    assert len(status.results) == len(FIX["response"]["results"])
    ok = [r for r in status.results if r.reply is not None]
    assert ok
    assert ok[0].reply is not None
    assert ok[0].reply.usage.prompt_tokens > 0


def test_poll_reports_batch_level_cost(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/b2").mock(return_value=httpx.Response(200, json=FIX["response"]))
    status = client().poll("b2")
    assert status.reported_cost_usd == FIX["response"]["usage"]["cost"]


def test_poll_handles_a_result_with_no_body(respx_mock: respx.MockRouter) -> None:
    broken = {
        **FIX["response"],
        "results": [
            {
                "id": "redacted",
                "custom_id": "case-broken",
                "response": None,
                "error": {"message": "request timed out"},
            }
        ],
    }
    respx_mock.get(f"{BASE}/b3").mock(return_value=httpx.Response(200, json=broken))
    status = client().poll("b3")
    assert len(status.results) == 1
    result = status.results[0]
    assert result.custom_id == "case-broken"
    assert result.reply is None
    assert result.error is not None
    assert "request timed out" in result.error


def test_reply_parsed_from_batch_has_no_reported_cost_and_prices_at_batch_rate(
    respx_mock: respx.MockRouter,
) -> None:
    """Carried from Task 3's review: the priced branch of cost_usd is untested elsewhere,
    and every batch reply hits it because per-result usage carries no cost key."""
    respx_mock.get(f"{BASE}/b4").mock(return_value=httpx.Response(200, json=FIX["response"]))
    status = client().poll("b4")
    ok = next(r for r in status.results if r.reply is not None)
    assert ok.reply is not None
    assert ok.reply.usage.reported_cost_usd is None
    settings = ModelSettings(model="openai/gpt-5.6-luna")
    dollars, how = cost_usd(ok.reply, settings)
    expected = (
        ok.reply.usage.prompt_tokens * 0.10 / 1e6 + ok.reply.usage.completion_tokens * 0.60 / 1e6
    )
    assert how == "priced"
    assert dollars == pytest.approx(expected)
