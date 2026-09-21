"""The System One client, tested on the probe's saved replies (decision 0060). No socket."""

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import (
    NoulAnswer,
    ScoreAnswer,
    TypeSafeClient,
    parse_reply,
    request_body,
)
from ntsb_probable_cause.records.evidence import Evidence

FIX = Path("tests/fixtures/typesafe")
EVIDENCE = Evidence(case_id="X", docket_url=None, aircraft_make="CESSNA", phase_of_flight="Landing")
QUESTIONS: dict[str, dict[str, object]] = {
    "event": {
        "type": "choice",
        "instructions": "Which event?",
        "criteria": {"000": "Unknown or undetermined", "092": "Hard landing"},
    }
}


def saved_response(name: str) -> dict[str, object]:
    body = json.loads((FIX / f"{name}.json").read_text())
    return cast("dict[str, object]", body["response"])


def test_choice_reply_parses_from_the_saved_response() -> None:
    reply = parse_reply(saved_response("choices"))
    assert reply.model.startswith("jev-")
    assert reply.usage.input_tokens > 0
    event = reply.choice("event")
    assert len(event.probabilities) == 93
    assert event.probabilities[event.choice] == event.max_probability
    assert 0 <= event.confidence <= 1


def test_score_is_the_expected_level_not_an_integer() -> None:
    score = parse_reply(saved_response("choices")).answers["evidence_detail"]
    assert isinstance(score, ScoreAnswer)
    assert set(score.legend) == set(score.probabilities) == {"0", "1", "2"}
    expected = sum(int(level) * p for level, p in score.probabilities.items())
    assert abs(score.score - expected) <= 0.02


def test_noul_reply_is_a_bare_probability() -> None:
    reply = parse_reply(saved_response("nouls"))
    assert len(reply.answers) == 130
    assert all(isinstance(a, NoulAnswer) for a in reply.answers.values())


def test_choice_accessor_refuses_a_missing_or_different_answer() -> None:
    reply = parse_reply(saved_response("nouls"))
    with pytest.raises(ModelError, match="event"):
        reply.choice("event")
    with pytest.raises(ModelError, match="category_010100"):
        reply.choice("category_010100")


def test_an_unexpected_reply_shape_is_a_model_error() -> None:
    with pytest.raises(ModelError, match="reply shape"):
        parse_reply({**saved_response("choices"), "surprise": 1})


def test_request_state_is_the_payload_text_and_nothing_else() -> None:
    payload = Payload.from_evidence(EVIDENCE)
    assert request_body(payload, QUESTIONS) == {
        "state": payload.text,
        "model": "jev-latest",
        "questions": QUESTIONS,
    }


def test_a_request_needs_a_question() -> None:
    with pytest.raises(ValueError, match="question"):
        request_body(Payload.from_evidence(EVIDENCE), {})


BASE = "https://api.typesafe.ai"
URL = f"{BASE}/v1/systemone"


@respx.mock
def test_ask_retries_a_rate_limit_then_returns_the_reply() -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=saved_response("choices"))]
    )
    slept: list[float] = []
    ticks = iter([10.0, 12.5])
    payload = Payload.from_evidence(EVIDENCE)
    with TypeSafeClient(
        "k", base_url=BASE, sleep=slept.append, clock=lambda: next(ticks)
    ) as client:
        exchange = client.ask(payload, QUESTIONS)
    assert route.call_count == 2
    assert exchange.attempts == 2
    assert exchange.retried_statuses == ("429",)
    assert exchange.seconds == 2.5
    assert slept == [2.0]
    assert exchange.reply.choice("event").choice
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer k"
    assert json.loads(request.content)["state"] == payload.text


@respx.mock
def test_ask_does_not_retry_a_client_error() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(400, text="bad question"))
    with (
        TypeSafeClient("k", base_url=BASE, sleep=lambda _: None) as client,
        pytest.raises(ModelError, match="400"),
    ):
        client.ask(Payload.from_evidence(EVIDENCE), QUESTIONS)
    assert route.call_count == 1


@respx.mock
def test_ask_gives_up_after_the_last_attempt() -> None:
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    slept: list[float] = []
    with (
        TypeSafeClient("k", base_url=BASE, sleep=slept.append, max_attempts=3) as client,
        pytest.raises(ModelError, match="3 attempts"),
    ):
        client.ask(Payload.from_evidence(EVIDENCE), QUESTIONS)
    assert route.call_count == 3
    assert slept == [2.0, 4.0]


@respx.mock
def test_ask_raises_model_error_on_non_json_200_reply() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=b"not json"))
    with (
        TypeSafeClient("k", base_url=BASE) as client,
        pytest.raises(ModelError, match="non-JSON"),
    ):
        client.ask(Payload.from_evidence(EVIDENCE), QUESTIONS)
    assert route.call_count == 1
