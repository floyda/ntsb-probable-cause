"""OpenRouter's batch service: submit, poll, collect (spec §7.2, read 2026-09-15)."""

import time
from collections.abc import Callable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    parse_chat_completion,
)
from ntsb_probable_cause.model.openrouter import OpenRouterClient, request_body

TERMINAL = frozenset({"completed", "failed", "expired", "cancelled"})


class BatchRequest(BaseModel):
    """One request inside a batch."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    custom_id: str
    payload: Payload
    settings: ModelSettings
    system: str = ""
    history: tuple[Turn, ...] = ()


class BatchResult(BaseModel):
    """One result: a parsed reply, or the provider's error text."""

    model_config = ConfigDict(frozen=True)
    custom_id: str
    reply: ModelReply | None
    error: str | None


class BatchStatus(BaseModel):
    """A batch as last polled."""

    model_config = ConfigDict(frozen=True)
    batch_id: str
    status: str
    results: tuple[BatchResult, ...]
    reported_cost_usd: float | None


def _as_mapping(value: object) -> Mapping[str, object]:
    """Narrow an untyped JSON value to a mapping, or raise for the caller to translate."""
    if not isinstance(value, Mapping):
        raise TypeError(f"expected an object, got {type(value).__name__}")
    return value


def _as_sequence(value: object) -> Sequence[object]:
    """Narrow an untyped JSON value to a sequence of items, defaulting to empty."""
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise TypeError(f"expected a list, got {type(value).__name__}")
    return value


def _result_from_item(item: Mapping[str, object]) -> BatchResult:
    """Parse one entry of ``results``: a reply on success, an error string otherwise."""
    custom_id = str(item["custom_id"])
    response = item.get("response")
    body = _as_mapping(response).get("body") if isinstance(response, Mapping) else None
    if isinstance(body, Mapping):
        return BatchResult(custom_id=custom_id, reply=parse_chat_completion(body), error=None)
    return BatchResult(custom_id=custom_id, reply=None, error=str(item.get("error") or response))


class BatchClient:
    """Submit many requests at the batch price and collect them when done."""

    def __init__(self, http: OpenRouterClient) -> None:
        self._http = http

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        """Submit one batch. Every request must share a model id."""
        model_ids = {r.settings.model_id() for r in requests}
        if len(model_ids) != 1:
            raise ModelError(f"a batch needs one model id, got {sorted(model_ids)}")
        body: dict[str, object] = {
            "endpoint": "/v1/chat/completions",
            "model": next(iter(model_ids)),
            "requests": [
                {
                    "custom_id": r.custom_id,
                    "body": request_body(r.payload, r.settings, system=r.system, history=r.history),
                }
                for r in requests
            ],
        }
        submitted = self._http.request_json(sources.BATCHES, method="POST", body=body)
        return str(submitted["id"])

    def poll(self, batch_id: str) -> BatchStatus:
        """Read the batch's current status and any results."""
        raw = self._http.request_json(f"{sources.BATCHES}/{batch_id}", method="GET")
        results = tuple(
            _result_from_item(_as_mapping(item)) for item in _as_sequence(raw.get("results"))
        )
        usage = raw.get("usage")
        cost = _as_mapping(usage).get("cost") if isinstance(usage, Mapping) else None
        return BatchStatus(
            batch_id=batch_id,
            status=str(raw.get("status")),
            results=results,
            reported_cost_usd=float(cost) if isinstance(cost, int | float) else None,
        )

    def wait(
        self,
        batch_id: str,
        *,
        every_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        on_status: Callable[[str], None] = lambda _s: None,
    ) -> BatchStatus:
        """Poll until the batch is terminal."""
        while True:
            status = self.poll(batch_id)
            on_status(status.status)
            if status.status in TERMINAL:
                return status
            sleep(every_seconds)
