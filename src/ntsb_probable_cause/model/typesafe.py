"""TypeSafe's System One client, for the declared experiment of decision 0036 only.

The wire shape is the one the probe saved under ``tests/fixtures/typesafe/`` (0036, probe
result). Where the vendor's SDK and those replies differ, the replies win. This is not a
``ModelClient``: Jev takes one state and typed questions, not chat messages, and it is not a
product transport (0009).
"""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import Payload

DEFAULT_MODEL = "jev-latest"


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


def request_body(
    payload: Payload,
    questions: Mapping[str, Mapping[str, object]],
    *,
    model: str = DEFAULT_MODEL,
) -> dict[str, object]:
    """The exact JSON sent. The payload text is the only state (decision 0016)."""
    if not questions:
        raise ValueError("a System One request needs at least one question")
    return {
        "state": payload.text,
        "model": model,
        "questions": {name: dict(question) for name, question in questions.items()},
    }


def parse_reply(body: Mapping[str, object]) -> SystemOneReply:
    """Validate a reply against the saved shape; any drift is a ``ModelError``."""
    try:
        return SystemOneReply.model_validate(body)
    except ValidationError as error:
        raise ModelError(
            f"unexpected System One reply shape: {error.error_count()} validation errors"
        ) from error
