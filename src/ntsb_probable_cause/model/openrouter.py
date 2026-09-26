"""The OpenRouter chat-completions client: one implementation of ModelClient (spec §7.2)."""

import time
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Self

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    parse_chat_completion,
)

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_USER_AGENT = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"


def _user_content(payload: Payload) -> str | list[dict[str, object]]:
    """The user message: the text alone, byte for byte as before S2.6, unless images ride too.

    With images, the text (when there is any) comes first, then each image as a ``data:``
    URL -- the chat-completions content-parts form.
    """
    if not payload.images:
        return payload.text
    parts: list[dict[str, object]] = []
    if payload.text:
        parts.append({"type": "text", "text": payload.text})
    parts.extend(
        {"type": "image_url", "image_url": {"url": image.data_url()}} for image in payload.images
    )
    return parts


def request_body(
    payload: Payload, settings: ModelSettings, *, system: str, history: Sequence[Turn]
) -> dict[str, object]:
    """The exact JSON sent for one call. The batch client reuses it per request."""
    messages: list[dict[str, object]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": _user_content(payload)})
    for turn in history:
        if turn.role == "assistant":
            message: dict[str, object] = {"role": "assistant", "content": turn.content}
            if turn.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": c.call_id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in turn.tool_calls
                ]
            messages.append(message)
        else:
            if turn.payload is None:  # pragma: no cover -- Turn's validator refuses this
                raise ModelError("a tool turn without a Payload cannot be sent")
            messages.append(
                {"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.payload.text}
            )
    body: dict[str, object] = {
        "model": settings.model_id(),
        "messages": messages,
        "temperature": settings.temperature,
        "max_tokens": settings.max_output_tokens,
        "usage": {"include": True},
    }
    if settings.json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": settings.schema_name,
                "strict": True,
                "schema": settings.json_schema,
            },
        }
    if settings.tools:
        body["tools"] = list(settings.tools)
    if settings.reasoning_effort is not None:
        body["reasoning"] = {"effort": settings.reasoning_effort}
    return body


class OpenRouterClient:
    """Rate-limited, retrying client. One instance per run."""

    def __init__(  # noqa: PLR0913 -- fixed by the plan's Interfaces block, as for NtsbClient.
        self,
        api_key: str,
        *,
        base_url: str = sources.OPENROUTER_BASE_URL,
        requests_per_minute: int = 60,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": _USER_AGENT},
            timeout=180.0,
            transport=transport,
        )
        self._gap = 60.0 / requests_per_minute
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._requested = False
        self._last_backoff_slept = 0.0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self._http.close()

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        """Send one chat completion and parse the reply."""
        body = request_body(payload, settings, system=system, history=history)
        return parse_chat_completion(
            self.request_json(sources.CHAT_COMPLETIONS, method="POST", body=body)
        )

    def request_json(
        self,
        path: str,
        *,
        method: str,
        body: dict[str, object] | None = None,
        retry: bool = True,
    ) -> dict[str, object]:
        """One retry loop for GET and POST, with the run's rate limit; the batch client uses it too.

        The rate-limit gap is not stacked on top of a retry backoff that already spaced the
        requests: after a backoff sleep of ``b`` seconds, the next gap sleep is ``gap - b`` if
        still positive, otherwise skipped. With no preceding backoff, the full gap applies.

        ``retry=False`` sends exactly once. Use it for any request that is **not idempotent**
        and whose duplicate costs money. A retried chat completion is safe -- the first one
        was billed but we simply pay twice for a reply we then use. A retried batch
        submission is not: a 400-request batch whose response times out after the server
        accepted it gets submitted again, both are billed, and only the second id comes back.
        The first is then invisible to our own accounting, never reused by a resume, and
        **OpenRouter has no cancel endpoint**, so it cannot be stopped. There is no
        idempotency key on this API to make the retry safe, so the retry has to go.
        """
        status: object = None
        attempts = self._max_attempts if retry else 1
        for attempt in range(1, attempts + 1):
            if self._requested:
                remaining_gap = self._gap - self._last_backoff_slept
                if remaining_gap > 0:
                    self._sleep(remaining_gap)
            self._requested = True
            self._last_backoff_slept = 0.0
            try:
                response = self._http.request(method, path, json=body)
            except httpx.TransportError as error:
                status = type(error).__name__
            else:
                if response.is_success:
                    parsed: dict[str, object] = response.json()
                    return parsed
                status = response.status_code
                if response.status_code not in _RETRY_STATUSES:
                    raise ModelError(f"{path} returned {status}: {response.text[:200]}")
            if attempt < attempts:
                backoff = self._backoff * 2 ** (attempt - 1)
                self._sleep(backoff)
                self._last_backoff_slept = backoff
        if not retry:
            raise ModelError(
                f"{path} failed with {status} and was not retried, because a duplicate of "
                f"this request would be billed and could not be cancelled. The request may "
                f"still have been accepted: check the provider for a batch created just now "
                f"before submitting again."
            )
        raise ModelError(f"{path} failed after {attempts} attempts; last status {status}")
