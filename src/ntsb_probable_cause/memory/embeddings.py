"""Embeddings through OpenRouter, and a cache of the vectors (decision 0213).

The embedding lookup ranks lessons by how close each lesson's text lies to a case's cause
sentence. This module only turns texts into vectors: it reads no case record, and the texts it
is given are the snapshot's lessons and the NTSB's cause sentences, both development data. It
writes no spend row; ``scripts/memory_embed.py`` costs each reply and writes the rows.

The reply's shape is the one the shape probe saved (``tests/fixtures/openrouter/embeddings``):
``{"data": [{"index": i, "embedding": [...]}], "usage": {"prompt_tokens": n, "cost": x}}``, with
leading whitespace before the JSON and, in ``model``, the provider's own name for the model.
"""

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, Self

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError, ModelError

EMBEDDINGS_PATH: Final = "/api/v1/embeddings"
RETRY_STATUSES: Final = frozenset({429, 500, 502, 503, 504})
RETRY_SECONDS: Final = 2.0
TIMEOUT_SECONDS: Final = 120.0
_USER_AGENT: Final = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"


@dataclass(frozen=True)
class EmbeddingReply:
    """One reply's vectors, in input order, and what it says it used.

    Attributes:
        vectors: one vector per input text, in input order.
        prompt_tokens: the reply's ``usage.prompt_tokens``, if it reports one.
        cost_usd: the reply's own ``usage.cost``, if it reports one.
    """

    vectors: tuple[tuple[float, ...], ...]
    prompt_tokens: int | None
    cost_usd: float | None


def _vectors(body: object, wanted: int) -> tuple[tuple[float, ...], ...]:
    """The reply's vectors in input order.

    Raises:
        ModelError: not one vector per input, each index once, all numbers, of one length.
    """
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or len(data) != wanted:
        raise ModelError(f"the embeddings reply does not hold {wanted} vector(s)")
    by_index: dict[int, tuple[float, ...]] = {}
    for item in data:
        index = item.get("index") if isinstance(item, dict) else None
        vector = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(index, int) or not isinstance(vector, list) or not vector:
            raise ModelError("an embeddings reply item has no index or no vector")
        if not all(isinstance(x, int | float) and not isinstance(x, bool) for x in vector):
            raise ModelError("an embeddings reply vector holds something other than numbers")
        by_index[index] = tuple(float(x) for x in vector)
    if sorted(by_index) != list(range(wanted)):
        raise ModelError("the embeddings reply does not give each index once")
    if len({len(v) for v in by_index.values()}) != 1:
        raise ModelError("the embeddings reply's vectors are not of one length")
    return tuple(by_index[i] for i in range(wanted))


def _usage(body: object) -> tuple[int | None, float | None]:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None, None
    tokens, cost = usage.get("prompt_tokens"), usage.get("cost")
    return (
        tokens if isinstance(tokens, int) else None,
        float(cost) if isinstance(cost, int | float) else None,
    )


class EmbeddingClient:
    """Embeds texts through OpenRouter, with one retry on a busy or failed provider."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = sources.OPENROUTER_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": _USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            transport=transport,
        )
        self._sleep = sleep

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP connection."""
        self._http.close()

    def embed(self, model: str, texts: Sequence[str]) -> EmbeddingReply:
        """One request for ``texts``; their vectors in input order.

        A 429, a 5xx in ``RETRY_STATUSES`` or a transport error is retried once, after
        ``RETRY_SECONDS``. No message names the key or a text.

        Raises:
            ModelError: the request failed after its retry, or the reply is malformed.
        """
        payload = {"model": model, "input": list(texts)}
        for attempt in range(2):
            try:
                response = self._http.post(EMBEDDINGS_PATH, json=payload)
            except httpx.TransportError as exc:
                if attempt == 0:
                    self._sleep(RETRY_SECONDS)
                    continue
                raise ModelError(
                    f"embeddings request to {model} failed: {type(exc).__name__}"
                ) from None
            if response.status_code in RETRY_STATUSES and attempt == 0:
                self._sleep(RETRY_SECONDS)
                continue
            if response.status_code != httpx.codes.OK:
                raise ModelError(
                    f"embeddings request to {model} failed: status {response.status_code}"
                )
            try:
                body: object = json.loads(response.content)
            except ValueError:
                raise ModelError(f"the embeddings reply from {model} is not JSON") from None
            tokens, cost = _usage(body)
            return EmbeddingReply(_vectors(body, len(texts)), tokens, cost)
        raise AssertionError(
            "unreachable: the second attempt returns or raises"
        )  # pragma: no cover


def text_key(text: str) -> str:
    """The cache key of a text: the SHA-256 hex digest of its UTF-8 bytes."""
    return hashlib.sha256(text.encode()).hexdigest()


class VectorCache:
    """One JSONL file per model: ``{"key": ..., "vector": [...]}`` rows; appended, never rewritten.

    A row holds the text's key, never the text. Every vector in one file has one length.
    """

    def __init__(self, folder: Path, model: str) -> None:
        self._path = folder / f"{model.replace('/', '-')}.jsonl"
        self._vectors: dict[str, tuple[float, ...]] = {}
        if self._path.exists():
            for line in self._path.read_text().splitlines():
                row = json.loads(line)
                self._vectors[row["key"]] = tuple(row["vector"])

    def get(self, text: str) -> tuple[float, ...] | None:
        """The cached vector of ``text``, or None."""
        return self._vectors.get(text_key(text))

    def put(self, text: str, vector: Sequence[float]) -> None:
        """Append ``text``'s vector.

        Raises:
            ConfigurationError: the vector's length differs from the file's.
        """
        lengths = {len(v) for v in self._vectors.values()}
        if lengths and len(vector) not in lengths:
            raise ConfigurationError(
                f"a vector of length {len(vector)} does not fit {self._path.name}, "
                f"whose vectors are of length {next(iter(lengths))}"
            )
        key = text_key(text)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as out:
            out.write(json.dumps({"key": key, "vector": list(vector)}) + "\n")
        self._vectors[key] = tuple(vector)
