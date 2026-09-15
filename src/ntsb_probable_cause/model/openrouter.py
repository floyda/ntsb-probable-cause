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


def request_body(
    payload: Payload, settings: ModelSettings, *, system: str, history: Sequence[Turn]
) -> dict[str, object]:
    """The exact JSON sent for one call. The batch client reuses it per request."""
    messages: list[dict[str, object]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": payload.text})
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
            messages.append(
                {"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.content}
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
        self, path: str, *, method: str, body: dict[str, object] | None = None
    ) -> dict[str, object]:
        """One retry loop for GET and POST, with the run's rate limit; the batch client uses it too.

        The rate-limit gap is not stacked on top of a retry backoff that already spaced the
        requests: after a backoff sleep of ``b`` seconds, the next gap sleep is ``gap - b`` if
        still positive, otherwise skipped. With no preceding backoff, the full gap applies.
        """
        status: object = None
        for attempt in range(1, self._max_attempts + 1):
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
            if attempt < self._max_attempts:
                backoff = self._backoff * 2 ** (attempt - 1)
                self._sleep(backoff)
                self._last_backoff_slept = backoff
        raise ModelError(f"{path} failed after {self._max_attempts} attempts; last status {status}")
