"""OpenRouter's batch service: submit, poll, collect (spec §7.2, read 2026-09-15)."""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import BatchNotFoundError, ConfigurationError, ModelError
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    parse_chat_completion,
)
from ntsb_probable_cause.model.openrouter import OpenRouterClient, request_body

TERMINAL = frozenset({"completed", "failed", "expired", "cancelled"})
_HTTP_OK_MIN = 200
_HTTP_OK_MAX = 300


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


@dataclass(frozen=True)
class BatchCounts:
    """The provider's ``request_counts``, as last polled.

    Each field is ``None`` when the provider's payload did not say -- distinct from ``0``,
    which the provider does report once it has started work (``0/401`` means nothing done
    yet; no counts at all means the provider gave none, e.g. before the batch is queued).
    """

    total: int | None
    completed: int | None
    failed: int | None


class BatchStatus(BaseModel):
    """A batch as last polled."""

    model_config = ConfigDict(frozen=True)
    batch_id: str
    status: str
    results: tuple[BatchResult, ...]
    reported_cost_usd: float | None
    counts: BatchCounts = Field(default_factory=lambda: BatchCounts(None, None, None))


def _as_mapping(value: object) -> Mapping[str, object]:
    """Narrow an untyped JSON value to a mapping, or raise for the caller to translate."""
    if not isinstance(value, Mapping):
        raise TypeError(f"expected an object, got {type(value).__name__}")
    return value


def _as_int(value: object) -> int | None:
    """Narrow an untyped JSON value to an ``int``, or ``None`` if it isn't one.

    Never raises: a provider that sends a non-integer count (a string, a float, absent
    entirely) yields "unknown", the same as a missing ``request_counts`` block, rather than
    aborting the poll (brief: "must not raise").
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_sequence(value: object) -> Sequence[object]:
    """Narrow an untyped JSON value to a sequence of items, defaulting to empty."""
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise TypeError(f"expected a list, got {type(value).__name__}")
    return value


def _result_from_item(item: Mapping[str, object]) -> BatchResult:
    """Parse one entry of ``results``: a reply on success, an error string otherwise.

    Never raises: a non-2xx ``status_code``, a malformed body, or a body that fails
    ``parse_chat_completion`` (e.g. an error payload with no ``choices``) all become
    ``BatchResult(reply=None, error=...)`` instead of propagating out of ``poll``/``wait`` and
    aborting the rest of the batch.
    """
    custom_id = str(item["custom_id"])
    response = item.get("response")
    if not isinstance(response, Mapping):
        return BatchResult(
            custom_id=custom_id, reply=None, error=str(item.get("error") or response)
        )

    status_code = response.get("status_code")
    body = response.get("body")
    if isinstance(status_code, int) and not (_HTTP_OK_MIN <= status_code < _HTTP_OK_MAX):
        excerpt = json.dumps(body)[:200] if body is not None else str(item.get("error"))
        return BatchResult(
            custom_id=custom_id, reply=None, error=f"status {status_code}: {excerpt}"
        )
    if not isinstance(body, Mapping):
        return BatchResult(
            custom_id=custom_id, reply=None, error=str(item.get("error") or response)
        )
    try:
        return BatchResult(custom_id=custom_id, reply=parse_chat_completion(body), error=None)
    except ModelError as error:
        return BatchResult(custom_id=custom_id, reply=None, error=str(error))


class BatchClient:
    """Submit many requests at the batch price and collect them when done."""

    def __init__(self, http: OpenRouterClient) -> None:
        self._http = http

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        """Submit one batch. Every request must share a model id."""
        if any(request.payload.images for request in requests):
            # https://openrouter.ai/docs/batch-quickstart, read 2026-09-24: "Image parts must be
            # public http(s) URLs. Base64 and data: URI images are rejected on every provider."
            raise ConfigurationError(
                "images cannot go through the batch service: OpenRouter rejects base64 and "
                "data: images in a batch. Send image requests synchronously (S2.6, decision W1)."
            )
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
        # Never retried: a duplicate batch is billed in full and cannot be cancelled, and
        # only the second id would come back, leaving the first invisible to `month_spent`
        # and unreachable by a resume. See `request_json`'s note.
        submitted = self._http.request_json(sources.BATCHES, method="POST", body=body, retry=False)
        return str(submitted["id"])

    def poll(self, batch_id: str) -> BatchStatus:
        """Read the batch's current status and any results."""
        raw = self._http.request_json(f"{sources.BATCHES}/{batch_id}", method="GET")
        results = tuple(
            _result_from_item(_as_mapping(item)) for item in _as_sequence(raw.get("results"))
        )
        usage = raw.get("usage")
        cost = _as_mapping(usage).get("cost") if isinstance(usage, Mapping) else None
        counts_raw = raw.get("request_counts")
        counts_map = _as_mapping(counts_raw) if isinstance(counts_raw, Mapping) else {}
        counts = BatchCounts(
            total=_as_int(counts_map.get("total")),
            completed=_as_int(counts_map.get("completed")),
            failed=_as_int(counts_map.get("failed")),
        )
        return BatchStatus(
            batch_id=batch_id,
            status=str(raw.get("status")),
            results=results,
            reported_cost_usd=float(cost) if isinstance(cost, int | float) else None,
            counts=counts,
        )

    def wait(  # noqa: PLR0913 -- every parameter is a seam a test needs (see the docstring).
        self,
        batch_id: str,
        *,
        every_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        on_status: Callable[[BatchStatus], None] = lambda _s: None,
        not_found_grace_seconds: float = 120.0,
        now: Callable[[], float] = time.monotonic,
    ) -> BatchStatus:
        """Poll until the batch is terminal.

        A batch id that was just returned by ``submit`` can 404 on the very first poll:
        OpenRouter needs a short time before a newly submitted batch is readable through
        the GET endpoint, and the same 404 can also appear later, briefly, as a provider
        blip (observed 2026-09-16: ``ModelError: /api/beta/batches/<id> returned 404:
        {"error":{"message":"Batch job <id> not found.","code":404}}`` on the first poll of
        a batch already recorded in ``batches.jsonl``). A 404 is tolerated for up to
        ``not_found_grace_seconds`` -- sleeping and retrying rather than raising -- starting
        from the first 404 seen; a poll that succeeds (any status, terminal or not) clears
        the window, so a later blip gets its own fresh grace period. Only once the window
        elapses without a successful poll does this raise ``BatchNotFoundError`` (a
        ``ModelError`` subclass, so existing ``except ModelError`` callers are unaffected)
        naming the batch id. Every other status behaviour (the ``TERMINAL`` set,
        ``expired``/``failed`` raising via ``_result_from_item`` on the caller's next step,
        per-result error handling) is unchanged.
        """
        not_found_deadline: float | None = None
        while True:
            try:
                status = self.poll(batch_id)
            except ModelError as error:
                if "returned 404" not in str(error):
                    raise
                if not_found_deadline is None:
                    not_found_deadline = now() + not_found_grace_seconds
                if now() >= not_found_deadline:
                    raise BatchNotFoundError(
                        f"batch {batch_id}: still not found after "
                        f"{not_found_grace_seconds:.0f}s: {error}"
                    ) from error
                sleep(every_seconds)
                continue
            not_found_deadline = None
            on_status(status)
            if status.status in TERMINAL:
                return status
            sleep(every_seconds)
