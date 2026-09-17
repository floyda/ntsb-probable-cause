# TypeSafe's Jev on dev-400: implementation plan

**Spec:** docs/specs/2026-09-17-typesafe-jev-dev400-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from the specification in the **Deviations** section at the end.

**Goal:** Run Jev on the 401 `dev-400` cases with phase and event as two Choice questions, score it with S1's code beside Luna and Gemini, and report accuracy and calibration against readings fixed in the specification.

**Architecture:** A small, strictly typed System One client in `src/ntsb_probable_cause/model/typesafe.py`, tested against the probe's saved replies. One exploratory script, `scripts/exploratory/jev_dev400.py`, with two subcommands: `run` (builds every payload through `runner.case_payload`, asks Jev four cases at a time, appends raw replies under `data/runs/`) and `report` (scores the saved replies with `metrics.score_case` and `metrics.calibration`, reads Luna's and Gemini's saved runs, prints the tables). The report never calls the API, so it can be re-run for free.

**Tech Stack:** Python 3.14, uv, pydantic v2, httpx + respx, pytest (`--disable-socket`), ruff, mypy --strict, import-linter. All already in `pyproject.toml`; no new dependency.

## Global Constraints

- Every payload is built by `scoring/runner.py:case_payload`, which calls `split_record` and `Payload.from_evidence` (decisions 0013, 0016). The request `state` is `payload.text` and nothing else.
- The `model` package may not import `scoring`, `records.split`, `records.synthesis` or `records.verdict` (import-linter, `pyproject.toml`). The client therefore takes plain question dictionaries.
- Where a saved reply under `tests/fixtures/typesafe/` disagrees with this plan, follow the saved reply and log a deviation (0036).
- Tests never reach the network. HTTP is replayed with `respx`.
- `dev-400` only. No held-out case is loaded, sent or scored.
- Hard stop at **$0.50** at the published price (`sources.JEV`). Jev is in preview: cost is reported for comparison only.
- Raw replies stay under `data/runs/`, which is not in git. Only summaries go to `docs/results/`.
- Every reported number comes from the script's output. The report quotes it; it does not retype numbers from memory.
- The API key comes from the environment only: `TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)"` inline on the command. Never print it.
- The repository's `data/` lives in the main checkout, not in this worktree. Every command that reads data sets `NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data` and `NTSB_RUNS_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs`.
- `make check` passes before every commit. Commit messages end with the attribution lines the session gives. Never commit to `main`; the branch is `typesafe-probe`. Do not push or open a pull request.
- Docstrings in Google style on every public symbol; line length 100.
- The code blocks in this plan are correct but not guaranteed formatter-clean. Run `uv run ruff format <new files>` before `make check`, which runs `ruff format --check`. `scripts/exploratory/` is outside ruff, but not outside mypy once a test imports it.

---

## File structure

| path | responsibility |
|---|---|
| `src/ntsb_probable_cause/model/typesafe.py` | Create. Reply types, `request_body`, `parse_reply`, `TypeSafeClient.ask` with retries |
| `tests/test_typesafe_client.py` | Create. Parsing tests on the saved replies; HTTP tests with `respx` |
| `scripts/exploratory/jev_dev400.py` | Create. Questions, composition, per-case scoring, readings, `ask_all`, `run` and `report` subcommands |
| `tests/test_jev_dev400.py` | Create. Tests for the script's pure functions and for `ask_all` with a fake `ask` |
| `docs/results/typesafe-jev-dev400.txt` | Create. The report subcommand's output, as printed |
| `docs/results/typesafe-jev-dev400.md` | Create. The short report for Andy |
| `docs/decisions/0036-typesafe-jev-as-a-declared-experiment.md` | Modify. One dated line under "Probe result" recording the row |

---

### Task 1: System One reply types and request body

**Files:**
- Create: `src/ntsb_probable_cause/model/typesafe.py`
- Test: `tests/test_typesafe_client.py`

**Interfaces:**
- Consumes: `ntsb_probable_cause.model.client.Payload`, `ntsb_probable_cause.errors.ModelError`.
- Produces:
  - `DEFAULT_MODEL: str = "jev-latest"`
  - `class ChoiceAnswer(BaseModel)`: `type: Literal["choice"]`, `choice: str`, `confidence: float`, `probabilities: dict[str, float]`, property `max_probability -> float`
  - `class ScoreAnswer(BaseModel)`: `type`, `score: float`, `confidence: float`, `legend: dict[str, str]`, `probabilities: dict[str, float]`
  - `class NoulAnswer(BaseModel)`: `type`, `noul: float`
  - `class SystemOneUsage(BaseModel)`: `input_tokens: int`, `output_tokens: int`
  - `class SystemOneReply(BaseModel)`: `model: str`, `usage: SystemOneUsage`, `answers: dict[str, ChoiceAnswer | ScoreAnswer | NoulAnswer]`, method `choice(name: str) -> ChoiceAnswer`
  - `def request_body(payload: Payload, questions: Mapping[str, Mapping[str, object]], *, model: str = DEFAULT_MODEL) -> dict[str, object]`
  - `def parse_reply(body: Mapping[str, object]) -> SystemOneReply`

- [x] **Step 1: Write the failing tests**

Create `tests/test_typesafe_client.py`:

```python
"""The System One client, tested on the probe's saved replies (decision 0036). No socket."""

import json
from pathlib import Path
from typing import cast

import pytest

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import (
    NoulAnswer,
    ScoreAnswer,
    parse_reply,
    request_body,
)
from ntsb_probable_cause.records.evidence import Evidence

FIX = Path("tests/fixtures/typesafe")
EVIDENCE = Evidence(case_id="X", docket_url=None, aircraft_make="CESSNA", phase_of_flight="Landing")
QUESTIONS: dict[str, dict[str, object]] = {
    "event": {
        "type": "choice",
        "instructions": "Which event?",
        "criteria": {"000": "Unknown or undetermined", "092": "Hard landing"},
    }
}


def saved_response(name: str) -> dict[str, object]:
    body = json.loads((FIX / f"{name}.json").read_text())
    return cast("dict[str, object]", body["response"])


def test_choice_reply_parses_from_the_saved_response() -> None:
    reply = parse_reply(saved_response("choices"))
    assert reply.model.startswith("jev-")
    assert reply.usage.input_tokens > 0
    event = reply.choice("event")
    assert len(event.probabilities) == 93
    assert event.probabilities[event.choice] == event.max_probability
    assert 0 <= event.confidence <= 1


def test_score_is_the_expected_level_not_an_integer() -> None:
    score = parse_reply(saved_response("choices")).answers["evidence_detail"]
    assert isinstance(score, ScoreAnswer)
    assert set(score.legend) == set(score.probabilities) == {"0", "1", "2"}
    expected = sum(int(level) * p for level, p in score.probabilities.items())
    assert abs(score.score - expected) <= 0.02


def test_noul_reply_is_a_bare_probability() -> None:
    reply = parse_reply(saved_response("nouls"))
    assert len(reply.answers) == 130
    assert all(isinstance(a, NoulAnswer) for a in reply.answers.values())


def test_choice_accessor_refuses_a_missing_or_different_answer() -> None:
    reply = parse_reply(saved_response("nouls"))
    with pytest.raises(ModelError, match="event"):
        reply.choice("event")
    with pytest.raises(ModelError, match="category_010100"):
        reply.choice("category_010100")


def test_an_unexpected_reply_shape_is_a_model_error() -> None:
    with pytest.raises(ModelError, match="reply shape"):
        parse_reply({**saved_response("choices"), "surprise": 1})


def test_request_state_is_the_payload_text_and_nothing_else() -> None:
    payload = Payload.from_evidence(EVIDENCE)
    assert request_body(payload, QUESTIONS) == {
        "state": payload.text,
        "model": "jev-latest",
        "questions": QUESTIONS,
    }


def test_a_request_needs_a_question() -> None:
    with pytest.raises(ValueError, match="question"):
        request_body(Payload.from_evidence(EVIDENCE), {})
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_typesafe_client.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'ntsb_probable_cause.model.typesafe'`

- [x] **Step 3: Write the module**

Create `src/ntsb_probable_cause/model/typesafe.py`:

```python
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_typesafe_client.py -q --no-cov`
Expected: 7 passed.

- [x] **Step 5: Run the full check and commit**

Run: `make check`
Expected: all lint, type and test steps pass; coverage stays at or above 90%.

```bash
git add src/ntsb_probable_cause/model/typesafe.py tests/test_typesafe_client.py docs/plans/2026-09-17-typesafe-jev-dev400.md
git commit -m "Jev: System One reply types and request body, tested on the saved replies"
```

---

### Task 2: The client's request and retry loop

**Files:**
- Modify: `src/ntsb_probable_cause/model/typesafe.py`
- Test: `tests/test_typesafe_client.py`

**Interfaces:**
- Consumes: Task 1's `request_body`, `parse_reply`, `SystemOneReply`, `DEFAULT_MODEL`; `sources.TYPESAFE_SYSTEM_ONE`.
- Produces:
  - `@dataclass(frozen=True) class Exchange`: `reply: SystemOneReply`, `attempts: int`, `retried_statuses: tuple[str, ...]`, `seconds: float`
  - `class TypeSafeClient`: `__init__(self, api_key: str, *, base_url: str, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic, max_attempts: int = 5, backoff_seconds: float = 2.0)`, a context manager, and `ask(self, payload: Payload, questions: Mapping[str, Mapping[str, object]], *, model: str = DEFAULT_MODEL) -> Exchange`. Safe to call from several threads at once.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_typesafe_client.py`. Add `import httpx` and `import respx` to the imports at the top, and add `TypeSafeClient` to the `ntsb_probable_cause.model.typesafe` import.

```python
BASE = "https://api.typesafe.ai"
URL = f"{BASE}/v1/systemone"


@respx.mock
def test_ask_retries_a_rate_limit_then_returns_the_reply() -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=saved_response("choices"))]
    )
    slept: list[float] = []
    ticks = iter([10.0, 12.5])
    payload = Payload.from_evidence(EVIDENCE)
    with TypeSafeClient(
        "k", base_url=BASE, sleep=slept.append, clock=lambda: next(ticks)
    ) as client:
        exchange = client.ask(payload, QUESTIONS)
    assert route.call_count == 2
    assert exchange.attempts == 2
    assert exchange.retried_statuses == ("429",)
    assert exchange.seconds == 2.5
    assert slept == [2.0]
    assert exchange.reply.choice("event").choice
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer k"
    assert json.loads(request.content)["state"] == payload.text


@respx.mock
def test_ask_does_not_retry_a_client_error() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(400, text="bad question"))
    with (
        TypeSafeClient("k", base_url=BASE, sleep=lambda _: None) as client,
        pytest.raises(ModelError, match="400"),
    ):
        client.ask(Payload.from_evidence(EVIDENCE), QUESTIONS)
    assert route.call_count == 1


@respx.mock
def test_ask_gives_up_after_the_last_attempt() -> None:
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    slept: list[float] = []
    with (
        TypeSafeClient("k", base_url=BASE, sleep=slept.append, max_attempts=3) as client,
        pytest.raises(ModelError, match="3 attempts"),
    ):
        client.ask(Payload.from_evidence(EVIDENCE), QUESTIONS)
    assert route.call_count == 3
    assert slept == [2.0, 4.0]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_typesafe_client.py -q --no-cov`
Expected: FAIL with `ImportError: cannot import name 'TypeSafeClient'`

- [x] **Step 3: Add the client**

In `src/ntsb_probable_cause/model/typesafe.py`, replace the import block with:

```python
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
```

Below `DEFAULT_MODEL`, add:

```python
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_USER_AGENT = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"
```

At the end of the file, add:

```python
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
        """Send one request; retry rate limits, server errors and transport failures."""
        body = request_body(payload, questions, model=model)
        retried: list[str] = []
        started = self._clock()
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._http.post(sources.TYPESAFE_SYSTEM_ONE, json=body)
            except httpx.TransportError as error:
                status = type(error).__name__
            else:
                if response.is_success:
                    reply = parse_reply(response.json())
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_typesafe_client.py -q --no-cov`
Expected: 10 passed.

- [x] **Step 5: Run the full check and commit**

Run: `make check`
Expected: pass.

```bash
git add src/ntsb_probable_cause/model/typesafe.py tests/test_typesafe_client.py docs/plans/2026-09-17-typesafe-jev-dev400.md
git commit -m "Jev: System One client with retries, replayed with respx"
```

---

### Task 3: Composition, per-case scoring and the fixed readings

**Files:**
- Create: `scripts/exploratory/jev_dev400.py`
- Test: `tests/test_jev_dev400.py`

**Interfaces:**
- Consumes: Task 1's `ChoiceAnswer`, `SystemOneReply`; `scripts.typesafe_probe.choice_questions`; `scoring.hypothesis.Hypothesis`, `OccurrenceGuess`; `scoring.metrics.score_case`, `primary_occurrence`, `calibration`, `wilson`, `CaseScores`; `scoring.records.CaseResult`, `read_jsonl`; `records.verdict.Verdict`; `scoring.codes.CodeTables`.
- Produces (all in `scripts/exploratory/jev_dev400.py`):
  - `QUESTION_NAMES = ("phase", "event")`, `BASELINE_TOP1 = 0.177`
  - `def questions(tables: CodeTables) -> dict[str, dict[str, object]]`
  - `def ranked_pairs(phase: ChoiceAnswer, event: ChoiceAnswer, k: int = 3) -> list[tuple[str, str, float]]`
  - `def jev_hypothesis(reply: SystemOneReply) -> Hypothesis`
  - `@dataclass(frozen=True) class JevCase`: `case_id: str`, `fatal: bool`, `scores: CaseScores`, `event_confidence: float`, `event_top_probability: float`, `top1_probability: float`, `true_occurrence: str | None`, `true_event_probability: float | None`, `top_events: tuple[tuple[str, float], ...]`
  - `def score_jev_case(case_id: str, fatal: bool, reply: SystemOneReply, verdict: Verdict, tables: CodeTables, seen_pairs: AbstractSet[str]) -> JevCase`
  - `@dataclass(frozen=True) class FirstGuess`: `probability: float`, `right: bool`, `top1: bool`
  - `def llm_first_guesses(cases_file: Path) -> dict[str, FirstGuess]`
  - `def calibration_reading(confidences: Sequence[float], correct: Sequence[bool]) -> str` returning `"calibrated"`, `"not calibrated"` or `"inconclusive"`
  - `def accuracy_reading(top1: Sequence[bool]) -> str` returning `"above the baseline"` or `"not above the baseline"`
  - `def calibration_block(title: str, confidences: Sequence[float], correct: Sequence[bool]) -> str`

- [x] **Step 1: Write the failing tests**

Create `tests/test_jev_dev400.py`:

```python
"""The Jev dev-400 script's pure parts (docs/specs/2026-09-17-typesafe-jev-dev400-design.md)."""

import json
from pathlib import Path

from scripts.exploratory.jev_dev400 import (
    accuracy_reading,
    calibration_reading,
    jev_hypothesis,
    llm_first_guesses,
    questions,
    ranked_pairs,
    score_jev_case,
)

from ntsb_probable_cause.model.typesafe import ChoiceAnswer, SystemOneReply, SystemOneUsage
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, StepRecord, write_jsonl

TABLES = load_tables()


def _choice(probabilities: dict[str, float], confidence: float = 0.5) -> ChoiceAnswer:
    best = max(probabilities, key=probabilities.__getitem__)
    return ChoiceAnswer(
        type="choice", choice=best, confidence=confidence, probabilities=probabilities
    )


def _reply(phase: dict[str, float], event: dict[str, float]) -> SystemOneReply:
    return SystemOneReply(
        model="jev-1.13.0",
        usage=SystemOneUsage(input_tokens=10, output_tokens=5),
        answers={"phase": _choice(phase), "event": _choice(event, confidence=0.4)},
    )


def test_questions_are_the_probes_phase_and_event_only() -> None:
    asked = questions(TABLES)
    assert set(asked) == {"phase", "event"}
    assert len(asked["phase"]["criteria"]) == 47  # type: ignore[arg-type]
    assert len(asked["event"]["criteria"]) == 93  # type: ignore[arg-type]


def test_pairs_rank_by_joint_probability_then_code() -> None:
    phase = _choice({"550": 0.6, "500": 0.4})
    event = _choice({"092": 0.5, "000": 0.5, "240": 0.0})
    assert ranked_pairs(phase, event) == [
        ("550", "000", 0.3),
        ("550", "092", 0.3),
        ("500", "000", 0.2),
    ]


def test_jev_answer_scores_like_any_hypothesis() -> None:
    reply = _reply({"550": 0.9, "500": 0.1}, {"092": 0.7, "000": 0.3})
    hypothesis = jev_hypothesis(reply)
    assert hypothesis.occurrence_codes(TABLES) == ("550092", "550000", "500092")
    assert hypothesis.abstain is False
    assert abs(hypothesis.confidence - 0.63) < 1e-9
    verdict = Verdict(
        probable_cause=None,
        occurrence_codes=("550092",),
        finding_codes=(),
        finding_codes_in_cause=(),
    )
    case = score_jev_case("X1", True, reply, verdict, TABLES, frozenset({"550092"}))
    assert case.scores.occurrence_top1
    assert case.scores.event_match
    assert not case.scores.pair_unseen
    assert case.event_confidence == 0.4
    assert case.event_top_probability == 0.7
    assert case.true_event_probability == 0.7
    assert case.top_events == (("092", 0.7), ("000", 0.3))


def test_a_ruled_out_true_event_has_probability_zero() -> None:
    reply = _reply({"550": 1.0}, {"092": 1.0})
    verdict = Verdict(
        probable_cause=None, occurrence_codes=("550000",), finding_codes=(),
        finding_codes_in_cause=(),
    )
    case = score_jev_case("X2", False, reply, verdict, TABLES, frozenset())
    assert not case.scores.occurrence_top1
    assert case.true_event_probability == 0.0
    assert case.true_occurrence == "550000"


def test_calibration_readings_follow_the_spec_thresholds() -> None:
    stated = [0.9] * 50
    assert calibration_reading(stated, [True] * 45 + [False] * 5) == "calibrated"
    assert calibration_reading(stated, [True] * 41 + [False] * 9) == "inconclusive"
    assert calibration_reading(stated, [True] * 25 + [False] * 25) == "not calibrated"


def test_one_bin_of_twenty_far_off_makes_a_low_error_inconclusive() -> None:
    stated = [0.5] * 20 + [0.05] * 380
    right = [True] * 16 + [False] * 4 + [True] * 19 + [False] * 361
    assert calibration_reading(stated, right) == "inconclusive"


def test_accuracy_reading_uses_the_lower_bound() -> None:
    assert accuracy_reading([True] * 100 + [False] * 301) == "above the baseline"
    assert accuracy_reading([True] * 75 + [False] * 326) == "not above the baseline"


def _llm_case(case_id: str, phase: str, event: str, probability: float, truth: str) -> CaseResult:
    hypothesis = parse_hypothesis(
        json.dumps(
            {
                "evidence_narrative": "",
                "probable_cause": "",
                "lay_explanation": "",
                "confidence": 0.2,
                "abstain": True,
                "evidence_used": [],
                "occurrence": [{"phase": phase, "event": event, "probability": probability}],
                "findings": [],
            }
        ),
        TABLES,
    )
    step = StepRecord.model_validate(
        {
            "case_id": case_id, "step": 0, "arm": "ceiling", "condition": "full", "day": None,
            "tool": "none", "arguments": {}, "reason": "", "expected_effect": "",
            "returned_roles": (), "not_available": (), "payload_fingerprint": "f",
            "hypothesis": hypothesis, "observed_effect": "", "stop_reason": "abstained",
            "model": "m", "price_variant": "batch", "prompt_tokens": 1,
            "completion_tokens": 1, "cost_usd": 0.0, "cumulative_cost_usd": 0.0,
            "commit_sha": "abc1234", "dirty": False,
        }
    )
    scores = CaseScores(
        occurrence_top1=False, occurrence_top3=False, event_match=False, pair_unseen=False,
        finding_precision_10=None, finding_recall_10=None, finding_precision_8=None,
        finding_recall_8=None, finding_precision_6=None, finding_recall_6=None,
        finding_precision_all_10=None, finding_recall_all_10=None, abstained=True,
        confidence=0.2,
    )
    return CaseResult(
        case_id=case_id, split="dev", fatal=False, investigation_class=None,
        report_flavour=None, verdict_occurrence=(truth,), verdict_findings=(),
        verdict_findings_in_cause=(), steps=(step,), scores=scores, cost_usd=0.0,
        failure=None,
    )


def test_llm_first_guess_is_read_whether_or_not_the_model_abstained(tmp_path: Path) -> None:
    cases_file = tmp_path / "cases.jsonl"
    write_jsonl(
        cases_file,
        [
            _llm_case("A", "550", "092", 0.6, "550092"),
            _llm_case("B", "550", "000", 0.3, "550092"),
        ],
    )
    guesses = llm_first_guesses(cases_file)
    assert guesses["A"].probability == 0.6
    assert guesses["A"].right
    assert not guesses["A"].top1
    assert not guesses["B"].right
```

Check the second calibration test by hand before running it: the 0.5 bin has 20 cases, 16 right, so its gap is 0.30, above 0.10. The 0.0–0.1 bin has 380 cases at 0.05 with 19 right, gap 0. The error is 20/400 × 0.30 = 0.015, which is under 0.05, so the large-bin gap alone makes it "inconclusive" (the error is not above 0.10).

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_jev_dev400.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.exploratory.jev_dev400'`. If the error names `scripts.exploratory` itself, add an empty `scripts/exploratory/__init__.py` and log a deviation.

- [x] **Step 3: Write the script's pure parts**

Create `scripts/exploratory/jev_dev400.py`:

```python
"""Jev on dev-400: phase and event as two Choices per case (decision 0036).

Specification: docs/specs/2026-09-17-typesafe-jev-dev400-design.md. Exploratory, so outside
the strict tooling, but every payload is built by ``runner.case_payload`` and so passes
through ``split_record`` and the leakage guard (0013, 0016).

Usage (from the worktree root; data lives in the main checkout):
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
    TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)" \\
        uv run python -m scripts.exploratory.jev_dev400 run [--resume FOLDER]
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
        uv run python -m scripts.exploratory.jev_dev400 report FOLDER [--out PATH]
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.model.typesafe import ChoiceAnswer, SystemOneReply
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import (
    CaseScores,
    calibration,
    primary_occurrence,
    score_case,
    wilson,
)
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from scripts.typesafe_probe import choice_questions

QUESTION_NAMES = ("phase", "event")
# docs/results/s1-baseline.txt: the honest baseline's top-1 on held-out, the bar S1 set.
BASELINE_TOP1 = 0.177
# Spec §5: the calibration thresholds, fixed before the run.
_CALIBRATED_ECE = 0.05
_NOT_CALIBRATED_ECE = 0.10
_MAX_BIN_GAP = 0.10
_MIN_BIN_COUNT = 20


def questions(tables: CodeTables) -> dict[str, dict[str, object]]:
    """Phase and event, worded exactly as the probe worded them."""
    every = choice_questions(tables)
    return {name: every[name] for name in QUESTION_NAMES}


def ranked_pairs(
    phase: ChoiceAnswer, event: ChoiceAnswer, k: int = 3
) -> list[tuple[str, str, float]]:
    """(phase, event, joint probability), highest first, ties broken by code."""
    pairs = [
        (p, e, pp * ep)
        for p, pp in phase.probabilities.items()
        for e, ep in event.probabilities.items()
    ]
    pairs.sort(key=lambda t: (-t[2], t[0], t[1]))
    return pairs[:k]


def jev_hypothesis(reply: SystemOneReply) -> Hypothesis:
    """Jev's answer in S1's shape, so ``score_case`` scores it exactly as it scored Luna."""
    top = ranked_pairs(reply.choice("phase"), reply.choice("event"))
    return Hypothesis(
        evidence_narrative="",
        occurrence=tuple(
            OccurrenceGuess(phase=p, event=e, probability=min(1.0, prob)) for p, e, prob in top
        ),
        findings=(),
        probable_cause="",
        lay_explanation="",
        confidence=min(1.0, top[0][2]),
        abstain=False,
        evidence_used=(),
    )


@dataclass(frozen=True)
class JevCase:
    """One scored case and the numbers the calibration tables need."""

    case_id: str
    fatal: bool
    scores: CaseScores
    event_confidence: float
    event_top_probability: float
    top1_probability: float
    true_occurrence: str | None
    true_event_probability: float | None
    top_events: tuple[tuple[str, float], ...]


def score_jev_case(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
    case_id: str,
    fatal: bool,
    reply: SystemOneReply,
    verdict: Verdict,
    tables: CodeTables,
    seen_pairs: AbstractSet[str],
) -> JevCase:
    """Score one reply with S1's ``score_case`` and keep what calibration needs."""
    hypothesis = jev_hypothesis(reply)
    scores = score_case(hypothesis, verdict, tables, seen_pairs=seen_pairs)
    event = reply.choice("event")
    truth = primary_occurrence(verdict)
    ranked = sorted(event.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
    return JevCase(
        case_id=case_id,
        fatal=fatal,
        scores=scores,
        event_confidence=event.confidence,
        event_top_probability=event.probabilities[hypothesis.occurrence[0].event],
        top1_probability=hypothesis.occurrence[0].probability,
        true_occurrence=truth,
        true_event_probability=event.probabilities.get(truth[3:], 0.0) if truth else None,
        top_events=tuple(ranked[:5]),
    )


@dataclass(frozen=True)
class FirstGuess:
    """An LLM's first occurrence guess: its stated probability and whether it is right."""

    probability: float
    right: bool
    top1: bool


def llm_first_guesses(cases_file: Path) -> dict[str, FirstGuess]:
    """Per case, from a saved S1 run, whether or not the model abstained (spec §4)."""
    out: dict[str, FirstGuess] = {}
    for result in read_jsonl(cases_file, CaseResult):
        if result.scores is None or not result.steps:
            continue
        first = result.steps[-1].hypothesis.occurrence[0]
        truth = result.verdict_occurrence[0] if result.verdict_occurrence else None
        out[result.case_id] = FirstGuess(
            probability=first.probability,
            right=f"{first.phase}{first.event}" == truth,
            top1=result.scores.occurrence_top1,
        )
    return out


def calibration_reading(confidences: Sequence[float], correct: Sequence[bool]) -> str:
    """Spec §5: calibrated, not calibrated, or inconclusive."""
    bins, ece = calibration(confidences, correct)
    worst = max(
        (abs(b.accuracy - b.mean_confidence) for b in bins if b.count >= _MIN_BIN_COUNT),
        default=0.0,
    )
    if ece > _NOT_CALIBRATED_ECE:
        return "not calibrated"
    if ece <= _CALIBRATED_ECE and worst <= _MAX_BIN_GAP:
        return "calibrated"
    return "inconclusive"


def accuracy_reading(top1: Sequence[bool]) -> str:
    """Spec §5: is the lower bound of top-1's 95% interval above the baseline?"""
    low, _ = wilson(sum(top1), len(top1))
    return "above the baseline" if low > BASELINE_TOP1 else "not above the baseline"


def calibration_block(title: str, confidences: Sequence[float], correct: Sequence[bool]) -> str:
    """One reliability table with its expected calibration error."""
    bins, ece = calibration(confidences, correct)
    lines = [
        f"{title}: n={len(confidences)}, expected calibration error {ece:.3f}",
        "  bin        n   mean stated   share right     gap",
    ]
    lines.extend(
        f"  {b.low:.1f}-{b.high:.1f}  {b.count:4d}   {b.mean_confidence:11.3f}   "
        f"{b.accuracy:11.3f}   {b.accuracy - b.mean_confidence:+.3f}"
        for b in bins
        if b.count
    )
    return "\n".join(lines)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_jev_dev400.py -q --no-cov`
Expected: 9 passed. If `test_accuracy_reading_uses_the_lower_bound` fails, print `wilson(100, 401)` and `wilson(75, 401)`: the first lower bound must be above 0.177 and the second below it. Adjust the counts in the test, not the threshold.

- [x] **Step 5: Run the full check and commit**

Run: `make check`
Expected: pass. mypy follows the test's import into the script even though the script is excluded from discovery, so the script must be mypy-clean.

```bash
git add scripts/exploratory/jev_dev400.py tests/test_jev_dev400.py docs/plans/2026-09-17-typesafe-jev-dev400.md
git commit -m "Jev dev-400: composition, per-case scoring and the readings fixed in the spec"
```

---

### Task 4: The run loop, with resume and the cost cap

**Files:**
- Modify: `scripts/exploratory/jev_dev400.py`
- Test: `tests/test_jev_dev400.py`

**Interfaces:**
- Consumes: Task 2's `Exchange`; `ntsb_probable_cause.errors.ModelError`; `model.client.Payload`.
- Produces:
  - `CAP_USD = 0.50`, `CONCURRENCY = 4`, `TOKENS_PER_REQUEST_ESTIMATE = 5_000`
  - `def read_rows(replies: Path) -> list[dict[str, object]]`
  - `def ask_all(replies: Path, cases: Sequence[tuple[str, Payload]], ask: Callable[[Payload], Exchange], *, cap_usd: float, usd_per_token: float, concurrency: int = CONCURRENCY) -> str` returning `"complete"` or `"cap"`

  Each row appended to `replies.jsonl` is one JSON object: `case_id`, `ok` (bool), `error` (str or null), `attempts`, `retried_statuses` (list), `seconds`, `cost_usd`, `reply` (the parsed reply dumped as JSON, or null).

- [x] **Step 1: Write the failing tests**

Append to `tests/test_jev_dev400.py`. Add these imports at the top: `from collections.abc import Callable`, `from ntsb_probable_cause.errors import ModelError`, `from ntsb_probable_cause.model.client import Payload`, `from ntsb_probable_cause.model.typesafe import Exchange, parse_reply`, `from ntsb_probable_cause.records.evidence import Evidence`, and `ask_all`, `read_rows` from the script.

`Payload.from_evidence` does not render `case_id`, which is bookkeeping and not an evidence
role. So each fake case carries its id in the `registration` evidence field
(`records/evidence.py`), and the fake `ask` reads it back from the payload.

```python
SAVED = parse_reply(
    json.loads(Path("tests/fixtures/typesafe/choices.json").read_text())["response"]
)


def _cases(n: int) -> list[tuple[str, Payload]]:
    return [
        (
            f"C{i}",
            Payload.from_evidence(
                Evidence(case_id=f"C{i}", docket_url=None, registration=f"C{i}")
            ),
        )
        for i in range(n)
    ]


def _fake_ask(
    asked: list[str], fail: frozenset[str] = frozenset()
) -> Callable[[Payload], Exchange]:
    def ask(payload: Payload) -> Exchange:
        case_id = str(payload.fields()["registration"])
        asked.append(case_id)
        if case_id in fail:
            raise ModelError("returned 503")
        return Exchange(SAVED, attempts=1, retried_statuses=(), seconds=0.25)

    return ask
```

```python
def test_ask_all_stops_before_the_cap(tmp_path: Path) -> None:
    replies = tmp_path / "replies.jsonl"
    asked: list[str] = []
    # 1e-5 USD per token: the estimate is 0.05 per request. The first four fit under 0.25;
    # they spend 4 x 4,344 x 1e-5 = 0.17376, and two more estimated at 0.10 would pass 0.25.
    reason = ask_all(
        replies, _cases(6), _fake_ask(asked), cap_usd=0.25, usd_per_token=1e-5
    )
    assert reason == "cap"
    assert sorted(asked) == ["C0", "C1", "C2", "C3"]
    rows = read_rows(replies)
    assert len(rows) == 4
    assert all(row["ok"] for row in rows)
    assert abs(sum(float(str(r["cost_usd"])) for r in rows) - 0.17376) < 1e-9


def test_ask_all_resumes_without_asking_again(tmp_path: Path) -> None:
    replies = tmp_path / "replies.jsonl"
    ask_all(replies, _cases(6), _fake_ask([]), cap_usd=0.25, usd_per_token=1e-5)
    asked: list[str] = []
    reason = ask_all(replies, _cases(6), _fake_ask(asked), cap_usd=10.0, usd_per_token=1e-5)
    assert reason == "complete"
    assert sorted(asked) == ["C4", "C5"]


def test_a_failed_case_is_recorded_and_asked_again_on_resume(tmp_path: Path) -> None:
    replies = tmp_path / "replies.jsonl"
    ask_all(
        replies, _cases(2), _fake_ask([], fail=frozenset({"C1"})), cap_usd=1.0,
        usd_per_token=1e-6,
    )
    failed = [row for row in read_rows(replies) if not row["ok"]]
    assert [row["case_id"] for row in failed] == ["C1"]
    assert failed[0]["cost_usd"] == 0.0
    assert "503" in str(failed[0]["error"])
    asked: list[str] = []
    ask_all(replies, _cases(2), _fake_ask(asked), cap_usd=1.0, usd_per_token=1e-6)
    assert asked == ["C1"]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_jev_dev400.py -q --no-cov`
Expected: FAIL with `ImportError: cannot import name 'ask_all'`.

- [x] **Step 3: Add the loop**

In `scripts/exploratory/jev_dev400.py`, add to the imports:

```python
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import Exchange
```

(merge `Exchange` into the existing `ntsb_probable_cause.model.typesafe` import line), and add below `_MIN_BIN_COUNT`:

```python
# Spec §2: the hard stop, four requests at a time, and a per-request estimate above the
# probe's 4,344 input tokens for its phase-event-modifier request.
CAP_USD = 0.50
CONCURRENCY = 4
TOKENS_PER_REQUEST_ESTIMATE = 5_000
```

At the end of the file, add:

```python
def read_rows(replies: Path) -> list[dict[str, object]]:
    """Every row written so far, oldest first; none if the file does not exist yet."""
    if not replies.exists():
        return []
    return [json.loads(line) for line in replies.read_text().splitlines() if line]


def _attempt(case: tuple[str, Payload], ask: Callable[[Payload], Exchange], usd_per_token: float) -> dict[str, object]:
    case_id, payload = case
    try:
        exchange = ask(payload)
    except ModelError as error:
        return {
            "case_id": case_id, "ok": False, "error": str(error), "attempts": None,
            "retried_statuses": [], "seconds": None, "cost_usd": 0.0, "reply": None,
        }
    return {
        "case_id": case_id,
        "ok": True,
        "error": None,
        "attempts": exchange.attempts,
        "retried_statuses": list(exchange.retried_statuses),
        "seconds": round(exchange.seconds, 3),
        "cost_usd": exchange.reply.usage.input_tokens * usd_per_token,
        "reply": exchange.reply.model_dump(mode="json"),
    }


def ask_all(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
    replies: Path,
    cases: Sequence[tuple[str, Payload]],
    ask: Callable[[Payload], Exchange],
    *,
    cap_usd: float,
    usd_per_token: float,
    concurrency: int = CONCURRENCY,
) -> str:
    """Ask every case without an answered row, ``concurrency`` at a time; stop before the cap."""
    rows = read_rows(replies)
    answered = {row["case_id"] for row in rows if row["ok"]}
    spent = sum(float(str(row["cost_usd"])) for row in rows)
    pending = [case for case in cases if case[0] not in answered]
    estimate = TOKENS_PER_REQUEST_ESTIMATE * usd_per_token
    replies.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for start in range(0, len(pending), concurrency):
            chunk = pending[start : start + concurrency]
            if spent + estimate * len(chunk) > cap_usd:
                return "cap"
            new = list(pool.map(lambda case: _attempt(case, ask, usd_per_token), chunk))
            with replies.open("a") as handle:
                handle.writelines(json.dumps(row) + "\n" for row in new)
            spent += sum(float(str(row["cost_usd"])) for row in new)
    return "complete"
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_jev_dev400.py -q --no-cov`
Expected: 12 passed.

- [x] **Step 5: Run the full check and commit**

Run: `make check`
Expected: pass.

```bash
git add scripts/exploratory/jev_dev400.py tests/test_jev_dev400.py docs/plans/2026-09-17-typesafe-jev-dev400.md
git commit -m "Jev dev-400: the run loop, resumable, stopped before the cap"
```

---

### Task 5: The `run` and `report` subcommands

**Files:**
- Modify: `scripts/exploratory/jev_dev400.py`

**Interfaces:**
- Consumes: everything above; `Settings` (`data_dir`, `runs_dir`, `typesafe_base_url`, `require_typesafe_key()`); `samples.sample_ids`, `samples.load_cases`, `samples.seen_pairs`; `runner.case_payload`, `runner.RunSpec`; `ledger.commit_state`; `report.proportion`, `report.fmt_n`; `metrics.paired_difference`; `sources.JEV`; `codes.load_tables`.
- Produces: `def main(argv: Sequence[str]) -> int` and `def build_report(folder: Path, raws: Sequence[Mapping[str, object]], ids: Sequence[str], tables: CodeTables, seen: AbstractSet[str], runs_dir: Path) -> str`.

This task wires the tested parts to real data. It is exercised by the smoke run in Task 6, not by unit tests, because it only reads files and calls the tested functions.

- [ ] **Step 1: Add the imports and constants**

Add to the imports of `scripts/exploratory/jev_dev400.py`:

```python
import argparse
import random
import statistics
import sys
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from ntsb_probable_cause import sources
from ntsb_probable_cause.model.typesafe import DEFAULT_MODEL, TypeSafeClient, parse_reply
from ntsb_probable_cause.scoring import ledger, samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.metrics import paired_difference
from ntsb_probable_cause.scoring.report import fmt_n, proportion
from ntsb_probable_cause.scoring.runner import RunSpec, case_payload
from ntsb_probable_cause.settings import Settings
```

(merge each into the existing import line for the same module), and add below `TOKENS_PER_REQUEST_ESTIMATE`:

```python
SAMPLE = "dev-400"
RUN_SUFFIX = "dev-400-jev"
# Spec §4: the saved S1 runs the Jev row is compared with, case by case.
LLM_RUNS = {
    "Luna": "20260916T032106-179520f-dev-400-ceiling",
    "Gemini": "20260917T060746-c366a04-dev-400-ceiling",
}
EXAMPLE_SEED = 20260917
USD_PER_TOKEN = sources.JEV.input_usd_per_mtok / 1_000_000
```

- [ ] **Step 2: Add the report builder**

```python
def _latest_ok(rows: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    return {str(row["case_id"]): row for row in rows if row["ok"]}


def _pct(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def build_report(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
    folder: Path,
    raws: Sequence[Mapping[str, object]],
    ids: Sequence[str],
    tables: CodeTables,
    seen: AbstractSet[str],
    runs_dir: Path,
) -> str:
    """Every table of spec §4 and both readings of spec §5, from saved files only."""
    rows = read_rows(folder / "replies.jsonl")
    ok = _latest_ok(rows)
    meta = json.loads((folder / "meta.json").read_text())
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases: list[JevCase] = []
    for case_id, raw in zip(ids, raws, strict=True):
        if case_id not in ok:
            continue
        _, _, verdict, _ = case_payload(raw, spec, tables)
        reply = parse_reply(cast("Mapping[str, object]", ok[case_id]["reply"]))
        fatal = raw.get("highestInjuryLevel") == "Fatal"
        cases.append(score_jev_case(case_id, fatal, reply, verdict, tables, seen))
    replies = [parse_reply(cast("Mapping[str, object]", row["reply"])) for row in ok.values()]
    seconds = [float(str(row["seconds"])) for row in ok.values()]
    retried = Counter(s for row in rows for s in cast("list[str]", row["retried_statuses"]))
    input_tokens = sum(r.usage.input_tokens for r in replies)
    out: list[str] = []
    add = out.append

    add(f"run {folder.name}")
    add(f"sample={SAMPLE} requested model={meta['model']} commit={meta['commit']} dirty={meta['dirty']}")
    add(f"model versions in replies: {dict(Counter(r.model for r in replies))}")
    add(f"cases answered {len(ok)} of {len(ids)}; failed rows {sum(1 for r in rows if not r['ok'])}")
    add(f"input tokens {input_tokens}; output tokens {sum(r.usage.output_tokens for r in replies)}")
    add(
        f"cost at the published, self-reported price: ${input_tokens * USD_PER_TOKEN:.4f} "
        f"(${input_tokens * USD_PER_TOKEN / max(1, len(ok)):.6f} per case; preview, comparison only)"
    )
    add(
        f"latency seconds: median {statistics.median(seconds):.2f}, 90th percentile "
        f"{_pct(seconds, 0.9):.2f}, max {max(seconds):.2f}; requests needing a retry "
        f"{sum(1 for r in ok.values() if int(str(r['attempts'])) > 1)}; retried statuses {dict(retried)}"
    )

    add("\nACCURACY (composed top-1 and top-3; S1's score_case)")
    add("| slice | n | top-1 | top-3 | event | pair unseen |")
    add("|---|---|---|---|---|---|")
    for name, members in (
        ("all", cases),
        ("fatal", [c for c in cases if c.fatal]),
        ("non-fatal", [c for c in cases if not c.fatal]),
    ):
        add(
            f"| {name} | {len(members)} "
            f"| {fmt_n(proportion([c.scores.occurrence_top1 for c in members]))} "
            f"| {fmt_n(proportion([c.scores.occurrence_top3 for c in members]))} "
            f"| {fmt_n(proportion([c.scores.event_match for c in members]))} "
            f"| {fmt_n(proportion([c.scores.pair_unseen for c in members]))} |"
        )
    top1 = [c.scores.occurrence_top1 for c in cases]
    add(f"reading (spec §5, bar {BASELINE_TOP1:.1%}): {accuracy_reading(top1)}")

    event_right = [c.scores.event_match for c in cases]
    add("\nCALIBRATION")
    add(calibration_block("(a) Jev event confidence vs event right", [c.event_confidence for c in cases], event_right))
    add(f"reading on (a) (spec §5): {calibration_reading([c.event_confidence for c in cases], event_right)}")
    add(calibration_block("(b) Jev top event probability vs event right", [c.event_top_probability for c in cases], event_right))

    by_id = {c.case_id: c for c in cases}
    guesses = {name: llm_first_guesses(runs_dir / run / "cases.jsonl") for name, run in LLM_RUNS.items()}
    shared = sorted(set(by_id).intersection(*(set(g) for g in guesses.values())))
    add(f"\n(c) first-guess probability vs first guess right, on the {len(shared)} cases all three scored")
    add(calibration_block("(c) Jev top-1 product", [by_id[i].top1_probability for i in shared], [by_id[i].scores.occurrence_top1 for i in shared]))
    for name, g in guesses.items():
        add(calibration_block(f"(c) {name} first guess", [g[i].probability for i in shared], [g[i].right for i in shared]))

    add("\nPAIRED TOP-1 DIFFERENCE (Jev minus model, same cases, bootstrap 95%)")
    for name, g in guesses.items():
        mean, low, high = paired_difference(
            [by_id[i].scores.occurrence_top1 for i in shared], [g[i].top1 for i in shared]
        )
        add(f"- Jev - {name}: {mean:+.1%} [{low:+.1%}, {high:+.1%}] on n={len(shared)}")

    true_p = [c.true_event_probability for c in cases if c.true_event_probability is not None]
    add("\nPROBABILITY ON THE TRUE EVENT")
    add(
        f"median {statistics.median(true_p):.3f}; exactly 0 on "
        f"{sum(1 for p in true_p if p == 0.0)} of {len(true_p)} "
        f"({sum(1 for p in true_p if p == 0.0) / len(true_p):.1%})"
    )

    add(f"\nEXAMPLES (seed {EXAMPLE_SEED}; codes and labels only)")
    for c in random.Random(EXAMPLE_SEED).sample(cases, 5):
        truth = c.true_occurrence or "none"
        label = tables.events.get(truth[3:], "?") if c.true_occurrence else "-"
        add(f"{c.case_id}: true {truth} ({label}); Jev event confidence {c.event_confidence:.2f}")
        for code, p in c.top_events:
            add(f"    {code} {tables.events[code]:<45} {p:.2f}")
    return "\n".join(out) + "\n"
```

- [ ] **Step 3: Add `main`**

```python
def main(argv: Sequence[str]) -> int:
    """``run`` asks Jev; ``report`` scores what was saved."""
    parser = argparse.ArgumentParser(prog="jev_dev400")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--resume", help="an existing run folder name under the runs directory")
    run_cmd.add_argument("--limit", type=int, help="first N cases only (smoke run)")
    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("folder")
    report_cmd.add_argument("--out")
    args = parser.parse_args(argv)

    settings = Settings()
    tables = load_tables()
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids(SAMPLE)
    if args.command == "run" and args.limit is not None:
        ids = ids[: args.limit]
    raws = samples.load_cases(processed, ids)

    if args.command == "report":
        text = build_report(
            settings.runs_dir / args.folder, raws, ids, tables,
            samples.seen_pairs(processed), settings.runs_dir,
        )
        print(text, end="")
        if args.out:
            Path(args.out).write_text(text)
        return 0

    sha, dirty = ledger.commit_state()
    name = args.resume or f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{sha}-{RUN_SUFFIX}"
    folder = settings.runs_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        meta_file.write_text(json.dumps({
            "sample": SAMPLE, "model": DEFAULT_MODEL, "questions": list(QUESTION_NAMES),
            "commit": sha, "dirty": dirty, "started": datetime.now(UTC).isoformat(),
            "cap_usd": CAP_USD, "limit": args.limit,
        }, indent=1))
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases = []
    for case_id, raw in zip(ids, raws, strict=True):
        payload, _, _, evidence = case_payload(raw, spec, tables)
        if evidence.case_id != case_id:
            raise ValueError(f"sample order broken: {case_id} != {evidence.case_id}")
        cases.append((case_id, payload))
    asked = questions(tables)
    with TypeSafeClient(settings.require_typesafe_key(), base_url=settings.typesafe_base_url) as client:
        reason = ask_all(
            folder / "replies.jsonl", cases, lambda p: client.ask(p, asked),
            cap_usd=CAP_USD, usd_per_token=USD_PER_TOKEN,
        )
    rows = read_rows(folder / "replies.jsonl")
    print(
        f"{folder.name}: {reason}; answered {len(_latest_ok(rows))} of {len(ids)}; "
        f"spent ${sum(float(str(r['cost_usd'])) for r in rows):.4f} at the published price"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Check it type-checks and the tests still pass**

Run: `make check`
Expected: pass. Fix any mypy complaint in the script rather than adding `# type: ignore`.

- [ ] **Step 5: Confirm the saved LLM runs load with today's record types**

Run:

```bash
NTSB_RUNS_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs uv run python -c "
from pathlib import Path
from scripts.exploratory.jev_dev400 import LLM_RUNS, llm_first_guesses
root = Path('/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs')
for name, run in LLM_RUNS.items():
    print(name, len(llm_first_guesses(root / run / 'cases.jsonl')))
"
```

Expected: `Luna 401` and `Gemini 401`. A validation error means the saved rows predate a record field: log a deviation and read the two fields needed straight from the JSON instead.

- [ ] **Step 6: Commit**

```bash
git add scripts/exploratory/jev_dev400.py docs/plans/2026-09-17-typesafe-jev-dev400.md
git commit -m "Jev dev-400: run and report subcommands"
```

---

### Task 6: Smoke run, full run, report

**Files:**
- Create: `docs/results/typesafe-jev-dev400.txt`, `docs/results/typesafe-jev-dev400.md`
- Modify: `docs/decisions/0036-typesafe-jev-as-a-declared-experiment.md`

All commands in this task start with this prefix, written here as `$ENV`:

```
NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data NTSB_RUNS_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)"
```

- [ ] **Step 1: Smoke run on the first 8 cases**

This checks the pipeline end to end, not whether the replies are representative. The S1 lesson (0031 point 4) was that the first cases of a sorted file can pass where the rest fail; here that risk is small, because Jev has no output budget to run out of and the probe already answered 130 questions on one state. Read the 8 replies by eye: every row `ok`, 47 phase and 93 event probabilities, a `jev-` model version.

Run: `$ENV uv run python -m scripts.exploratory.jev_dev400 run --limit 8`
Expected: `<folder>: complete; answered 8 of 8; spent $0.000... at the published price`.

Then: `$ENV uv run python -m scripts.exploratory.jev_dev400 report <folder>`
Expected: the report prints without error. The shared-case count in (c) is 8.

- [ ] **Step 2: Full run from a clean tree**

Run `git status --short`; it must be empty, so `meta.json` records `dirty=false`. Leave the ticks for Steps 1 and 2 uncommitted until Step 6, or commit them first. Then:

Run: `$ENV uv run python -m scripts.exploratory.jev_dev400 run`
Expected: `<folder>: complete; answered 401 of 401; ...`. If it stops on `cap` or with failed rows, rerun with `--resume <folder>` once; if failures persist, stop and report them to Andy.

- [ ] **Step 3: Save the report**

Run: `$ENV uv run python -m scripts.exploratory.jev_dev400 report <folder> --out docs/results/typesafe-jev-dev400.txt`
Expected: the file is written; it shows 401 answered and the two readings.

- [ ] **Step 4: Write the short report**

Create `docs/results/typesafe-jev-dev400.md` in simplified technical English. Quote every number from `typesafe-jev-dev400.txt`; do not retype from memory. Sections:
1. **What was run**: the sample, the two questions, the model version from the replies, the commit.
2. **Accuracy**: the top-1 and top-3 rows beside Luna (8.7% and 22.9%) and Gemini (12.5% and 22.9%) from `docs/results/s1-model-comparison-dev.txt`, and the reading against 17.7%.
3. **Calibration**: table (a) and its reading, then what (b) and (c) add. Say plainly whether Jev's confidence can be used as a stopping rule in S3.
4. **How the model behaves**: probability on the true event, the share at exactly 0, the five examples, pair unseen.
5. **Rate limits and latency**: from the header lines.
6. **What this does not show**: findings, abstention, wording, the loop (0022).
7. **Glossary**: calibrated, expected calibration error, top-1, top-3, Choice, state.

- [ ] **Step 5: Record the row in 0036**

Add one line at the end of the "Probe result (2026-09-17)" section of `docs/decisions/0036-typesafe-jev-as-a-declared-experiment.md`:

```markdown
**dev-400 row (2026-09-17).** Run `<folder>`: top-1 <value>, calibration reading "<reading>";
details in `docs/results/typesafe-jev-dev400.md`. The status stays Proposed until the judge
test of point 5 has run.
```

Fill `<folder>`, `<value>` and `<reading>` from `typesafe-jev-dev400.txt`.

- [ ] **Step 6: Check and commit**

Run: `make check` and `uv run python -m scripts.check_docs`
Expected: both pass.

```bash
git add docs/results/typesafe-jev-dev400.txt docs/results/typesafe-jev-dev400.md docs/decisions/0036-typesafe-jev-as-a-declared-experiment.md docs/plans/2026-09-17-typesafe-jev-dev400.md
git commit -m "Jev dev-400: results and the row in decision 0036"
```

---

## Deviations

Task 2: a non-JSON 200 reply raises ModelError, so the run loop records it as a failed case (review fix).

Task 3: no deviations. `scripts.exploratory` imports as a namespace package without an
`__init__.py` (the error the plan anticipated, naming `scripts.exploratory` itself, never
occurred; only the wanted submodule was missing), so no `__init__.py` was added. The script
and test in the brief were used verbatim; `make check` (ruff format --check, ruff check,
import-linter, deptry, vulture, mypy --strict, pytest) passed on the first attempt, including
mypy --strict on the excluded-from-discovery script (followed via the test's import) and the
90% coverage gate (97.80% total). Step 4's brief text says "Expected: 9 passed"; the test file
has 8 test functions and 8 passed — a miscount in the brief's prose, not a code or test defect
(nothing to fix: no hand-computed number in the test bodies was wrong).

Task 4: no code deviations. The script and tests in the brief were used verbatim, including the
fixture's 4,344 input tokens, which matched the cap test's hand-computed arithmetic exactly, so
no expected numbers needed changing. The `pool.map(lambda case: ...)` call type-checked as
written under `mypy --strict`, so the brief's fallback (`functools.partial`) was not needed to
satisfy the type checker; `functools.partial` was used anyway, for readability, since a lambda
capturing two closed-over names read worse than a named partial application — a stylistic
choice, not a fix for a mypy failure. `make check` passed on the first attempt, including the
90% coverage gate (97.80% total). Step 4's brief text says "Expected: 12 passed"; the test file
has 11 test functions after Task 3's 8 plus this task's 3, and 11 passed — the same kind of
prose miscount as Task 3's (nothing to fix: no hand-computed number in the test bodies was
wrong).
