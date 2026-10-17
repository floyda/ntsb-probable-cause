"""The embeddings client and the vector cache (decision 0213), against the probe's saved replies.

Nothing here calls the network: replies come from ``tests/fixtures/openrouter/embeddings``, saved
by the shape probe (``docs/results/memory-embed-probe.txt``), or are invented to break one rule.
"""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from ntsb_probable_cause.errors import ConfigurationError, ModelError
from ntsb_probable_cause.memory.embeddings import (
    EmbeddingClient,
    VectorCache,
    text_key,
)

FIXTURES = Path("tests/fixtures/openrouter/embeddings")
KEY = "sk-or-secret-test-key"


class Counting(httpx.BaseTransport):
    """Answers with ``reply`` for each request and counts them."""

    def __init__(self, reply: Callable[[httpx.Request], httpx.Response]) -> None:
        self.reply = reply
        self.count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        return self.reply(request)


def _answer(status: int, body: object) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body))


def _saved(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


@pytest.mark.parametrize(
    ("name", "length"),
    [
        ("qwen-qwen3-embedding-8b", 4096),
        ("openai-text-embedding-3-small", 1536),
        ("openai-text-embedding-3-large", 3072),
    ],
)
def test_embed_parses_each_saved_reply(name: str, length: int) -> None:
    # The saved bytes, as sent: OpenRouter pads a reply with leading whitespace while it waits.
    content = _saved(name)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    reply = EmbeddingClient(KEY, transport=transport).embed("any/model", ["a", "b"])
    body = json.loads(content)
    assert [len(v) for v in reply.vectors] == [length, length]
    assert reply.vectors[0] == tuple(body["data"][0]["embedding"])
    assert reply.prompt_tokens == body["usage"]["prompt_tokens"]
    assert reply.cost_usd == body["usage"]["cost"]


def test_embed_sends_the_model_texts_key_and_path() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        data = [{"index": 0, "embedding": [1.0]}]
        return httpx.Response(200, json={"data": data})

    EmbeddingClient(KEY, transport=httpx.MockTransport(answer)).embed("m/x", ["only"])
    (request,) = seen
    assert request.url.path == "/api/v1/embeddings"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert "ntsb-probable-cause" in request.headers["user-agent"]
    assert json.loads(request.content) == {"model": "m/x", "input": ["only"]}


def test_embed_orders_by_index() -> None:
    body = {"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]}
    reply = EmbeddingClient(KEY, transport=_answer(200, body)).embed("m", ["a", "b"])
    assert reply.vectors == ((1.0, 0.0), (0.0, 1.0))


def test_embed_without_usage_reports_none() -> None:
    body = {"data": [{"index": 0, "embedding": [1.0]}]}
    reply = EmbeddingClient(KEY, transport=_answer(200, body)).embed("m", ["a"])
    assert reply.prompt_tokens is None
    assert reply.cost_usd is None


@pytest.mark.parametrize(
    "body",
    [
        {"data": [{"index": 0, "embedding": [1.0]}]},  # too few
        {"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [1.0, 2.0]}]},
        {"data": [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [2.0]}]},  # index
        {"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": ["x"]}]},  # type
        {"data": [{"index": 0, "embedding": []}, {"index": 1, "embedding": []}]},  # empty
        {"error": {"message": "x"}},  # no data
        ["not", "an", "object"],
    ],
)
def test_embed_refuses_a_malformed_reply(body: object) -> None:
    with pytest.raises(ModelError):
        EmbeddingClient(KEY, transport=_answer(200, body)).embed("m", ["a", "b"])


def test_embed_refuses_a_reply_that_is_not_json() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"<html>"))
    with pytest.raises(ModelError):
        EmbeddingClient(KEY, transport=transport).embed("m", ["a"])


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_embed_retries_once_then_fails(status: int) -> None:
    calls = Counting(lambda request: httpx.Response(status, json={}))
    slept: list[float] = []
    with pytest.raises(ModelError):
        EmbeddingClient(KEY, transport=calls, sleep=slept.append).embed("m", ["a"])
    assert calls.count == 2
    assert slept == [2.0]


def test_embed_retries_a_transport_error_and_can_succeed() -> None:
    failed: list[bool] = []

    def answer(request: httpx.Request) -> httpx.Response:
        if not failed:
            failed.append(True)
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    calls = Counting(answer)
    reply = EmbeddingClient(KEY, transport=calls, sleep=lambda s: None).embed("m", ["a"])
    assert reply.vectors == ((1.0,),)
    assert calls.count == 2


def test_embed_does_not_retry_a_client_error() -> None:
    calls = Counting(lambda request: httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(ModelError):
        EmbeddingClient(KEY, transport=calls, sleep=lambda s: None).embed("m", ["a"])
    assert calls.count == 1


def test_no_error_message_holds_the_key() -> None:
    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad key {request.headers['authorization']}")

    with pytest.raises(ModelError) as caught:
        EmbeddingClient(KEY, transport=httpx.MockTransport(echo)).embed("m", ["a"])
    assert KEY not in str(caught.value)


def test_client_is_a_context_manager() -> None:
    with EmbeddingClient(KEY, transport=_answer(200, {})) as client:
        assert isinstance(client, EmbeddingClient)


def test_text_key_is_the_sha256_of_the_text() -> None:
    assert text_key("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert text_key("abc") != text_key("abc ")


def test_cache_round_trip_and_new_text_misses(tmp_path: Path) -> None:
    cache = VectorCache(tmp_path, "m/x")
    cache.put("a", [1.0, 2.0])
    assert VectorCache(tmp_path, "m/x").get("a") == (1.0, 2.0)
    assert VectorCache(tmp_path, "m/x").get("a changed") is None
    assert VectorCache(tmp_path, "m/y").get("a") is None


def test_cache_appends_and_never_rewrites(tmp_path: Path) -> None:
    cache = VectorCache(tmp_path, "m")
    cache.put("loss of control in flight", [1.0, 2.0])
    (path,) = tmp_path.iterdir()
    first = path.read_text()
    cache.put("fuel exhaustion", [3.0, 4.0])
    assert path.read_text().startswith(first)
    assert len(path.read_text().splitlines()) == 2
    assert "fuel" not in path.read_text()  # keys only, never the text


def test_cache_refuses_a_vector_of_another_length(tmp_path: Path) -> None:
    VectorCache(tmp_path, "m").put("a", [1.0, 2.0])
    with pytest.raises(ConfigurationError):
        VectorCache(tmp_path, "m").put("b", [1.0])
