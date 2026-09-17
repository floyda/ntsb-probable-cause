"""TypeSafe's System One client, for the declared experiment of decision 0036 only.

The wire shape is the one the probe saved under ``tests/fixtures/typesafe/`` (0036, probe
result). Where the vendor's SDK and those replies differ, the replies win. This is not a
``ModelClient``: Jev takes one state and typed questions, not chat messages, and it is not a
product transport (0009).
"""

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Annotated, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import Payload

DEFAULT_MODEL = "jev-latest"

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_USER_AGENT = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"


class ChoiceAnswer(BaseModel):
    """One label from a list, a probability per label, and a separate confidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["choice"]
    choice: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]

    @property
    def max_probability(self) -> float:
        """The highest label probability; the probe showed it is not ``confidence``."""
        return max(self.probabilities.values())


class ScoreAnswer(BaseModel):
    """A position on an ordered rubric. ``score`` is the expected level, not an integer."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["score"]
    score: float
    confidence: float = Field(ge=0, le=1)
    legend: dict[str, str]
    probabilities: dict[str, float]


class NoulAnswer(BaseModel):
    """The probability that a yes/no claim is true."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)


Answer = Annotated[ChoiceAnswer | ScoreAnswer | NoulAnswer, Field(discriminator="type")]


class SystemOneUsage(BaseModel):
    """Token counts. Output tokens are counted but, per the vendor, not priced."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    input_tokens: int
    output_tokens: int


class SystemOneReply(BaseModel):
    """One System One reply. ``model`` is the resolved version, such as ``jev-1.13.0``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str
    usage: SystemOneUsage
    answers: dict[str, Answer]

    def choice(self, name: str) -> ChoiceAnswer:
        """The Choice answer called ``name``, or raise if there is none."""
        answer = self.answers.get(name)
        if not isinstance(answer, ChoiceAnswer):
            raise ModelError(f"reply has no choice answer named {name!r}")
        return answer


def _body(
    state: str,
    questions: Mapping[str, Mapping[str, object]],
    *,
    model: str,
) -> dict[str, object]:
    """The exact JSON sent, for either a ``Payload`` or a raw state string."""
    if not questions:
        raise ValueError("a System One request needs at least one question")
    return {
        "state": state,
        "model": model,
        "questions": {name: dict(question) for name, question in questions.items()},
    }


def request_body(
    payload: Payload,
    questions: Mapping[str, Mapping[str, object]],
    *,
    model: str = DEFAULT_MODEL,
) -> dict[str, object]:
    """The exact JSON sent. The payload text is the only state (decision 0016)."""
    return _body(payload.text, questions, model=model)


def parse_reply(body: Mapping[str, object]) -> SystemOneReply:
    """Validate a reply against the saved shape; any drift is a ``ModelError``."""
    try:
        return SystemOneReply.model_validate(body)
    except ValidationError as error:
        raise ModelError(
            f"unexpected System One reply shape: {error.error_count()} validation errors"
        ) from error


@dataclass(frozen=True)
class Exchange:
    """One answered request, and what it took to get it (spike question 8)."""

    reply: SystemOneReply
    attempts: int
    retried_statuses: tuple[str, ...]
    seconds: float


class TypeSafeClient:
    """Retrying System One client. ``ask`` may be called from several threads at once."""

    def __init__(  # noqa: PLR0913 -- fixed by the plan's Interfaces block, as for OpenRouterClient.
        self,
        api_key: str,
        *,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": _USER_AGENT},
            timeout=120.0,
            transport=transport,
        )
        self._sleep = sleep
        self._clock = clock
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self._http.close()

    def ask(
        self,
        payload: Payload,
        questions: Mapping[str, Mapping[str, object]],
        *,
        model: str = DEFAULT_MODEL,
    ) -> Exchange:
        """Send one request; the payload text is the only state (decision 0016)."""
        return self.ask_state(payload.text, questions, model=model)

    def ask_state(
        self,
        state: str,
        questions: Mapping[str, Mapping[str, object]],
        *,
        model: str = DEFAULT_MODEL,
    ) -> Exchange:
        """Send one request over a raw state string; retry as ``ask`` does.

        For the conditioned two-call mode only (``scripts/exploratory/jev_dev400.py``): the
        state there is the payload text plus one sentence of the model's own earlier output,
        never a payload built any other way. ``ask`` is the normal path and stays the one
        every other caller uses.
        """
        body = _body(state, questions, model=model)
        retried: list[str] = []
        started = self._clock()
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._http.post(sources.TYPESAFE_SYSTEM_ONE, json=body)
            except httpx.TransportError as error:
                status = type(error).__name__
            else:
                if response.is_success:
                    try:
                        reply_body = response.json()
                    except json.JSONDecodeError as error:
                        raise ModelError(
                            f"{sources.TYPESAFE_SYSTEM_ONE} returned 200 with non-JSON reply"
                        ) from error
                    reply = parse_reply(reply_body)
                    return Exchange(reply, attempt, tuple(retried), self._clock() - started)
                status = str(response.status_code)
                if response.status_code not in _RETRY_STATUSES:
                    raise ModelError(
                        f"{sources.TYPESAFE_SYSTEM_ONE} returned {status}: {response.text[:200]}"
                    )
            retried.append(status)
            if attempt < self._max_attempts:
                self._sleep(self._backoff * 2 ** (attempt - 1))
        raise ModelError(
            f"{sources.TYPESAFE_SYSTEM_ONE} failed after {self._max_attempts} attempts; "
            f"statuses {retried}"
        )
