"""What crosses to a model: a Payload rendered only from Evidence (decision 0016)."""

import json
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import WITHHELD_ROLE_NAMES, EvidenceRole
from ntsb_probable_cause.records.evidence import Evidence

_CONSTRUCTION_TOKEN = object()
_EVIDENCE_NAMES = frozenset(role.value for role in EvidenceRole)


class Payload:
    """The exact text a model would receive. Built only by ``Payload.from_evidence``."""

    __slots__ = ("_text",)

    def __init__(self, text: str, *, _token: object) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise TypeError("Payload is built only by Payload.from_evidence")
        self._text = text

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
            raise LeakageError(
                f"{evidence.case_id}: payload keys outside evidence roles: "
                f"{sorted(keys - _EVIDENCE_NAMES)}"
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


class ModelSettings(BaseModel):
    """Per-call model settings. Extended in S1."""

    model_config = ConfigDict(frozen=True)
    model: str = "anthropic/claude-sonnet-5"


class ModelReply(BaseModel):
    """Provisional: S1 defines the real response shape from a saved OpenRouter response (rule 2)."""

    model_config = ConfigDict(frozen=True)
    text: str


class ModelClient(Protocol):
    """Every model call the product makes goes through one of these (decision 0009)."""

    def complete(self, payload: Payload, settings: ModelSettings) -> ModelReply:
        """Send one payload and return the reply."""
        ...


class RecordingFakeClient:
    """A ModelClient for tests: records what it was sent and replays scripted replies."""

    def __init__(self, replies: Sequence[str] = ("",)) -> None:
        self.payloads: list[Payload] = []
        self._replies = tuple(replies) or ("",)

    def complete(self, payload: Payload, settings: ModelSettings) -> ModelReply:
        """Record the payload; return the next reply, repeating the last."""
        self.payloads.append(payload)
        return ModelReply(text=self._replies[min(len(self.payloads), len(self._replies)) - 1])
