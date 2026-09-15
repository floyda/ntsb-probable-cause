"""What crosses to a model: a Payload rendered only from Evidence (decision 0016)."""

import json
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, final

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import LeakageError, ModelError
from ntsb_probable_cause.fields import WITHHELD_ROLE_NAMES, EvidenceRole
from ntsb_probable_cause.records.evidence import Evidence

_CONSTRUCTION_TOKEN = object()
_EVIDENCE_NAMES = frozenset(role.value for role in EvidenceRole)


@final
class Payload:
    """The exact text a model would receive. Built only by ``Payload.from_evidence``.

    Immutable: ``__setattr__``/``__delattr__`` refuse any change after construction, and
    ``@final`` closes off subclassing, which would otherwise bypass the construction token.
    """

    __slots__ = ("_text",)
    _text: str

    def __init__(self, text: str, *, _token: object) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise TypeError("Payload is built only by Payload.from_evidence")
        object.__setattr__(self, "_text", text)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Payload is immutable: cannot set {name!r}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Payload is immutable: cannot delete {name!r}")

    @classmethod
    def from_evidence(cls, evidence: Evidence) -> Payload:
        """Render non-null, non-excluded evidence roles; never bookkeeping (guard layer 1)."""
        values = {
            role.value: list(value) if isinstance(value, tuple) else value
            for role, value in evidence.role_values().items()
            if value is not None
        }
        keys = set(values)
        if not keys <= _EVIDENCE_NAMES or keys & WITHHELD_ROLE_NAMES:
            offending = (keys - _EVIDENCE_NAMES) | (keys & WITHHELD_ROLE_NAMES)
            raise LeakageError(
                f"{evidence.case_id}: payload keys outside evidence roles: {sorted(offending)}"
            )
        return cls(
            json.dumps(values, indent=1, sort_keys=True, ensure_ascii=False),
            _token=_CONSTRUCTION_TOKEN,
        )

    @property
    def text(self) -> str:
        """The rendered payload."""
        return self._text

    def fields(self) -> dict[str, object]:
        """The payload parsed back into a dictionary."""
        parsed: dict[str, object] = json.loads(self._text)
        return parsed

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Payload) and other._text == self._text

    def __hash__(self) -> int:
        return hash(self._text)


class Usage(BaseModel):
    """Token counts and, when the provider reports it, cost (decision 0030)."""

    model_config = ConfigDict(frozen=True)
    prompt_tokens: int
    completion_tokens: int
    reported_cost_usd: float | None = None


class ToolCall(BaseModel):
    """One tool call the model asked for."""

    model_config = ConfigDict(frozen=True)
    call_id: str
    name: str
    arguments: str


class ModelReply(BaseModel):
    """A chat-completion reply, in the shape of tests/fixtures/openrouter/*.json (rule 2)."""

    model_config = ConfigDict(frozen=True)
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: Usage
    model: str
    response_id: str


class ModelSettings(BaseModel):
    """Per-call model settings. The default model is decision 0031's."""

    model_config = ConfigDict(frozen=True)
    model: str = "openai/gpt-5.6-luna"
    price_variant: Literal["batch", "standard"] = "batch"
    temperature: float = 0.0
    max_output_tokens: int = 2000
    json_schema: dict[str, object] | None = None
    schema_name: str = "hypothesis"
    tools: tuple[dict[str, object], ...] = ()

    def model_id(self) -> str:
        """The provider model id, with the batch suffix when the batch price applies."""
        return f"{self.model}:batch" if self.price_variant == "batch" else self.model


class Turn(BaseModel):
    """One earlier message in a multi-turn exchange (assistant or tool)."""

    model_config = ConfigDict(frozen=True)
    role: Literal["assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


class ModelClient(Protocol):
    """Every model call the product makes goes through one of these (decision 0009)."""

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        """Send one payload (and any prior turns) and return the reply."""
        ...


class RecordingFakeClient:
    """A ModelClient for tests: records what it was sent and replays scripted replies."""

    def __init__(self, replies: Sequence[str] = ("",)) -> None:
        self.payloads: list[Payload] = []
        self.histories: list[tuple[Turn, ...]] = []
        self._replies = tuple(replies) or ("",)

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        """Record the payload and history; return the next reply, repeating the last."""
        self.payloads.append(payload)
        self.histories.append(tuple(history))
        text = self._replies[min(len(self.payloads), len(self._replies)) - 1]
        return ModelReply(
            content=text,
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            model=settings.model_id(),
            response_id="fake",
        )


def _as_mapping(value: object) -> Mapping[str, object]:
    """Narrow an untyped JSON value to a mapping, or raise for the caller to translate."""
    if not isinstance(value, Mapping):
        raise TypeError(f"expected an object, got {type(value).__name__}")
    return value


def _first_choice(body: Mapping[str, object]) -> Mapping[str, object]:
    """Narrow ``body["choices"][0]`` to a mapping, or raise for the caller to translate."""
    choices = body["choices"]
    if not isinstance(choices, Sequence) or isinstance(choices, str | bytes):
        raise TypeError(f"expected a list of choices, got {type(choices).__name__}")
    return _as_mapping(choices[0])


def _as_int(value: object) -> int:
    """Narrow an untyped JSON number to an int, or raise for the caller to translate."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"expected a number, got {type(value).__name__}")
    return int(value)


def _as_float(value: object) -> float:
    """Narrow an untyped JSON number to a float, or raise for the caller to translate."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"expected a number, got {type(value).__name__}")
    return float(value)


def parse_chat_completion(body: Mapping[str, object]) -> ModelReply:
    """Parse a chat-completion body. Field names are those of the saved probe responses."""
    try:
        choice = _first_choice(body)
        message = _as_mapping(choice["message"])
        usage = _as_mapping(body["usage"])
        raw_calls = message.get("tool_calls")
        if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, str | bytes):
            raw_calls = ()
        calls = tuple(
            ToolCall(
                call_id=str(call["id"]),
                name=str(_as_mapping(call["function"])["name"]),
                arguments=str(_as_mapping(call["function"])["arguments"]),
            )
            for call in (_as_mapping(c) for c in raw_calls)
        )
        content = message.get("content")
        finish_reason = choice.get("finish_reason")
        cost = usage.get("cost")
        return ModelReply(
            content=content if content is None else str(content),
            tool_calls=calls,
            finish_reason=finish_reason if finish_reason is None else str(finish_reason),
            usage=Usage(
                prompt_tokens=_as_int(usage["prompt_tokens"]),
                completion_tokens=_as_int(usage["completion_tokens"]),
                reported_cost_usd=_as_float(cost) if cost is not None else None,
            ),
            model=str(body.get("model", "")),
            response_id=str(body.get("id", "")),
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ModelError(f"reply is not a chat completion: {error!r}") from error


def cost_usd(reply: ModelReply, settings: ModelSettings) -> tuple[float, str]:
    """Dollars for one reply, and whether they were reported by the provider or priced here."""
    if reply.usage.reported_cost_usd is not None:
        return reply.usage.reported_cost_usd, "reported"
    price = sources.price_of(settings.model_id())
    dollars = (
        reply.usage.prompt_tokens * price.input_usd_per_mtok
        + reply.usage.completion_tokens * price.output_usd_per_mtok
    ) / 1e6
    return dollars, "priced"
