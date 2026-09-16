# S1 — Scoring and the evaluation harness: implementation plan

**Spec:** docs/specs/2026-09-14-s1-scoring-and-evaluation-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from the specification in the **Deviations** section at the end.

**Goal:** Build the scoring harness that sets the bars the agent must beat: reproduce the spike's 16.2% baseline, re-measure the one-shot ceiling under code-constrained output on GPT-5.6 Luna, run arm A, prove per-step scoring on a scripted trail, and take the six decisions the roadmap deferred to S1.

**Architecture:** A `scoring` package of pure functions (metrics, codes, samples) around three frozen record types, driven by one `runner` that turns cases into payloads through S0's `split_record` and `Payload`, sends them through the `ModelClient` protocol (an OpenRouter sync client and a batch client, both replayed from saved responses in tests), and writes JSON-lines run records under `data/runs/`. A thin `apps/eval` command wires it. The only module that ever sees withheld text is `scoring/judge.py`.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, httpx + respx, pyarrow, pytest + pytest-socket + hypothesis, ruff, mypy --strict, import-linter (all already in `pyproject.toml`). mdbtools (`brew install mdbtools`) for the one-off code-table build.

## Global Constraints

- Every model call goes through `ModelClient` (0009). Tests never reach the network (`--disable-socket`); HTTP is replayed with `respx` from files under `tests/fixtures/openrouter/`.
- No withheld text or code reaches an answering payload: every payload is built by `split_record` + `Payload.from_evidence`. The judge payload is the one exception and is built only in `scoring/judge.py`.
- Numbers reported anywhere come from a script. Raw data, run outputs and model text never go in git: `data/` is ignored; only summaries go under `docs/results/`.
- Coverage gate `--cov-fail-under=90`, branch coverage. `make check` = ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest.
- Docstrings in Google style on every public symbol (ruff `D`). Line length 100.
- Costs in US dollars; the default budget is $25 (0030). Nothing is tuned on `heldout-*`; every held-out run appends to `docs/results/heldout-ledger.md` and is refused from a dirty tree (0026).
- Commit messages end with the attribution lines the session gives you. Never commit to `main`.
- Where a saved OpenRouter response disagrees with a field name in this plan, follow the saved response and log a deviation.

---

## File structure

| path | responsibility |
|---|---|
| `src/ntsb_probable_cause/settings.py` | + `openrouter_api_key`, `openrouter_base_url`, `runs_dir`, `monthly_budget_usd` |
| `src/ntsb_probable_cause/sources.py` | + Luna, Luna batch, Haiku 4.5 batch prices; OpenRouter endpoints; `price_of(model_id)` |
| `src/ntsb_probable_cause/errors.py` | + `ModelError`, `SchemaError`, `BudgetError` |
| `src/ntsb_probable_cause/model/client.py` | `ModelReply` and `ModelSettings` made real; `Usage`, `ToolCall`; fake gains scripted JSON replies |
| `src/ntsb_probable_cause/model/openrouter.py` | sync chat-completions client, retries, rate limit |
| `src/ntsb_probable_cause/model/batch.py` | batch submit / poll / collect |
| `src/ntsb_probable_cause/records/verdict.py`, `fields.py` | `finding_codes_in_cause` |
| `src/ntsb_probable_cause/scoring/tables/*.csv` | the five code tables, package data, labels only |
| `src/ntsb_probable_cause/scoring/codes.py` | load tables; compose; validate |
| `src/ntsb_probable_cause/scoring/hypothesis.py` | `Hypothesis`, `Refinement`, their JSON schemas, parsing against the tables |
| `src/ntsb_probable_cause/scoring/prompt.py` | system prompts, versioned; the rendered user message |
| `src/ntsb_probable_cause/scoring/metrics.py` | per-case, per-step, intervals, calibration; pure |
| `src/ntsb_probable_cause/scoring/baseline.py` | modal baseline |
| `src/ntsb_probable_cause/scoring/samples.py` | the three samples; arms as exclusion sets; the mask |
| `src/ntsb_probable_cause/scoring/records.py` | `RunRecord`, `StepRecord`, `CaseResult`; JSON-lines I/O |
| `src/ntsb_probable_cause/scoring/ledger.py` | held-out ledger; dirty-tree refusal; commit SHA |
| `src/ntsb_probable_cause/scoring/runner.py` | one run: sync or batch; caps and budget |
| `src/ntsb_probable_cause/scoring/judge.py` | the judge payloads and labels |
| `src/ntsb_probable_cause/scoring/report.py` | tables with counts and intervals; threshold curve |
| `apps/eval/__main__.py` | `ntsb-eval` |
| `scripts/openrouter_probe.py` | the probe; writes the four fixtures |
| `scripts/build_code_tables.py` | tables from `avall.zip` |
| `scripts/draw_samples.py` | `heldout_400_ids.csv`, `dev_400_ids.csv` |
| `scripts/copy_eval_ids.py` | extended: full labelling sheets |

---

### Task 1: Settings, prices, errors

**Files:**
- Modify: `src/ntsb_probable_cause/settings.py`
- Modify: `src/ntsb_probable_cause/sources.py`
- Modify: `src/ntsb_probable_cause/errors.py`
- Modify: `.env.example`
- Test: `tests/test_sources_settings.py`

**Interfaces:**
- Produces: `Settings.openrouter_api_key: SecretStr | None`, `Settings.openrouter_base_url: str`, `Settings.runs_dir: Path`, `Settings.monthly_budget_usd: float`, `Settings.require_openrouter_key() -> str`; `sources.LUNA`, `LUNA_BATCH`, `HAIKU_45_BATCH`, `OPENROUTER_BASE_URL`, `CHAT_COMPLETIONS`, `BATCHES`, `price_of(model_id) -> ModelPrice`; `errors.ModelError`, `SchemaError`, `BudgetError`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_sources_settings.py`:

```python
from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError, NtsbError, ModelError, SchemaError, BudgetError
from ntsb_probable_cause.settings import Settings


def test_openrouter_key_is_required_when_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        Settings(_env_file=None).require_openrouter_key()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert Settings(_env_file=None).require_openrouter_key() == "or-key"


def test_openrouter_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.openrouter_base_url == "https://openrouter.ai"
    assert s.runs_dir == Path("data/runs")
    assert s.monthly_budget_usd == 25.0


def test_price_of_known_and_unknown_model() -> None:
    assert sources.price_of("openai/gpt-5.6-luna:batch") is sources.LUNA_BATCH
    assert sources.LUNA_BATCH.input_usd_per_mtok == 0.10
    assert sources.LUNA_BATCH.output_usd_per_mtok == 0.60
    with pytest.raises(KeyError):
        sources.price_of("nobody/nothing")


def test_new_errors_are_ntsb_errors() -> None:
    for kind in (ModelError, SchemaError, BudgetError):
        assert issubclass(kind, NtsbError)
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_sources_settings.py -v`
Expected: FAIL with `ImportError` / `AttributeError` on the new names.

- [x] **Step 3: Implement**

`settings.py`, inside `Settings`:

```python
    openrouter_api_key: SecretStr | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai"
    runs_dir: Path = Path("data/runs")
    monthly_budget_usd: float = Field(default=25.0, gt=0)

    def require_openrouter_key(self) -> str:
        """Return the OpenRouter key, or raise if it is not set (decision 0009)."""
        if self.openrouter_api_key is None or not self.openrouter_api_key.get_secret_value():
            raise ConfigurationError(
                "OPENROUTER_API_KEY is not set; export it or load it from the password store."
            )
        return self.openrouter_api_key.get_secret_value()
```

`sources.py`, after `SONNET_5_BATCH`:

```python
# https://openrouter.ai/api/v1/models, checked 2026-09-15 (decision 0031). Luna and Luna-pro
# are listed at the same price; the probe picks one and the plan records why.
LUNA = ModelPrice("openai/gpt-5.6-luna", 0.20, 1.20, "OpenRouter models API, 2026-09-15")
LUNA_BATCH = ModelPrice("openai/gpt-5.6-luna:batch", 0.10, 0.60, "OpenRouter models API, 2026-09-15")
HAIKU_45_BATCH = ModelPrice(
    "anthropic/claude-haiku-4.5:batch", 0.50, 2.50, "OpenRouter models API, 2026-09-15"
)

_PRICES = {p.model_id: p for p in (SONNET_5, SONNET_5_BATCH, LUNA, LUNA_BATCH, HAIKU_45_BATCH)}


def price_of(model_id: str) -> ModelPrice:
    """The price entry for a model id; KeyError if the project has not recorded one."""
    return _PRICES[model_id]


# https://openrouter.ai/docs (decision 0009) and https://openrouter.ai/docs/batch-quickstart,
# read 2026-09-15. Confirmed by the saved responses under tests/fixtures/openrouter/.
OPENROUTER_BASE_URL = "https://openrouter.ai"
CHAT_COMPLETIONS = "/api/v1/chat/completions"
BATCHES = "/api/beta/batches"
```

`errors.py`, at the end:

```python
class ModelError(NtsbError):
    """The model provider returned an unusable response after retries."""


class SchemaError(NtsbError):
    """A model reply did not parse as the requested schema, or named a code not in the tables."""


class BudgetError(NtsbError):
    """A run or call would exceed the per-case cap or the monthly budget (decision 0030)."""
```

`.env.example`: confirm `OPENROUTER_API_KEY=` is present; add `NTSB_MONTHLY_BUDGET_USD=25`.

- [x] **Step 4: Run tests and `make check`**

Run: `uv run pytest tests/test_sources_settings.py -v && make check`
Expected: PASS; lint clean.

- [x] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/settings.py src/ntsb_probable_cause/sources.py src/ntsb_probable_cause/errors.py .env.example tests/test_sources_settings.py docs/plans/2026-09-15-s1-scoring-and-evaluation.md
git commit -m "S1: OpenRouter settings, model prices, model errors"
```

---

### Task 2: The probe (Andy runs it; it costs under $1)

**Files:**
- Create: `scripts/openrouter_probe.py`
- Create: `tests/fixtures/openrouter/` (four files, written by the probe)
- Test: `tests/test_openrouter_probe.py` (the redaction helper only)

**Interfaces:**
- Produces: `tests/fixtures/openrouter/structured.json`, `tool_call.json`, `two_turn.json`, `batch.json`; each holds `{"request": {...}, "response": {...}}` with `id` fields replaced by `"redacted"` and no key material. A `README.md` beside them with the date, the model ids and the observed usage fields.

The probe uses `httpx` directly, not the client (which does not exist yet). It builds the payload the only allowed way: `split_record` on a fixture record, `Payload.from_evidence`. It sends a minimal schema (top-1 phase and event as strings, a confidence) — the full Hypothesis schema arrives in Task 6; the probe's job is the response shape, not the task.

- [x] **Step 1: Write the failing test for the redaction helper**

```python
# tests/test_openrouter_probe.py
from scripts.openrouter_probe import redact


def test_redact_replaces_ids_and_keys_recursively() -> None:
    raw = {"id": "gen-123", "usage": {"cost": 0.0001}, "choices": [{"id": "x", "message": {"content": "hi"}}],
           "headers": {"authorization": "Bearer sk-or-abc"}}
    out = redact(raw)
    assert out["id"] == "redacted"
    assert out["choices"][0]["id"] == "redacted"
    assert out["headers"]["authorization"] == "redacted"
    assert out["usage"]["cost"] == 0.0001
```

- [x] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_openrouter_probe.py -v` — Expected: FAIL, module not found.

- [x] **Step 3: Write the probe**

```python
"""One-off probe of OpenRouter's response shapes (spec §7.1). Costs under $1. Needs a key.

Usage:
    uv run python -m scripts.openrouter_probe [--model openai/gpt-5.6-luna] [--cases 10]

Writes tests/fixtures/openrouter/{structured,tool_call,two_turn,batch}.json and README.md.
Every saved response is passed through ``redact`` so no request id or key is committed.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.settings import Settings

OUT = Path("tests/fixtures/openrouter")
FIXTURE = Path("tests/fixtures/records/ANC09CA020.json")
_REDACT_KEYS = frozenset({"id", "authorization", "x-api-key", "api_key", "request_id"})
SYSTEM = (
    "You are an aviation accident analyst. From the evidence, name the phase of flight and the "
    "event that define the accident. Reply only with JSON matching the schema."
)
MINI_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["phase", "event", "confidence"],
    "properties": {
        "phase": {"type": "string"},
        "event": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}
TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Return the recorded weather for the case.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


def redact(value: object) -> object:
    """Replace ids and key material anywhere in a JSON structure."""
    if isinstance(value, dict):
        return {k: ("redacted" if k.lower() in _REDACT_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _payload() -> str:
    record = json.loads(FIXTURE.read_text())["record"]
    evidence, _, _ = split_record(record)
    return Payload.from_evidence(evidence).text


def _post(http: httpx.Client, path: str, body: dict[str, object]) -> Any:
    """POST and return the parsed body; ``Any`` because the shape is what this probe discovers."""
    response = http.post(path, json=body)
    response.raise_for_status()
    return response.json()


def _save(name: str, request: dict[str, object], response: dict[str, object]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps({"request": redact(request), "response": redact(response)}, indent=1) + "\n"
    )
    print(f"saved {OUT / name}.json")


def main(argv: list[str]) -> int:
    """Run the four probes and write the fixtures."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=sources.LUNA.model_id)
    parser.add_argument("--cases", type=int, default=10)
    args = parser.parse_args(argv)
    settings = Settings()
    http = httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.require_openrouter_key()}"},
        timeout=120.0,
    )
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _payload()}]
    structured = {
        "model": args.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 300,
        "usage": {"include": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "mini", "strict": True, "schema": MINI_SCHEMA},
        },
    }
    _save("structured", structured, _post(http, sources.CHAT_COMPLETIONS, structured))

    tool_call = {**structured, "tools": [TOOL], "tool_choice": "required"}
    tool_call.pop("response_format")
    first = _post(http, sources.CHAT_COMPLETIONS, tool_call)
    _save("tool_call", tool_call, first)

    assistant = first["choices"][0]["message"]  # type: ignore[index]
    call_id = assistant["tool_calls"][0]["id"]  # type: ignore[index]
    two_turn = {
        **structured,
        "messages": [
            *messages,
            assistant,
            {"role": "tool", "tool_call_id": call_id, "content": '{"weather_condition": "VMC"}'},
        ],
        "tools": [TOOL],
    }
    _save("two_turn", two_turn, _post(http, sources.CHAT_COMPLETIONS, two_turn))

    batch_model = f"{args.model}:batch"
    body = {
        "endpoint": "/v1/chat/completions",
        "model": batch_model,
        "requests": [
            {"custom_id": f"probe-{i}", "body": {**structured, "model": batch_model}}
            for i in range(args.cases)
        ],
    }
    submitted = _post(http, sources.BATCHES, body)
    batch_id = submitted["id"]
    while True:
        status = http.get(f"{sources.BATCHES}/{batch_id}").json()
        print(f"batch {status.get('status')}")
        if status.get("status") in {"completed", "failed", "expired", "cancelled"}:
            break
        time.sleep(30)
    _save("batch", body, status)

    usage = status.get("usage", {})
    (OUT / "README.md").write_text(
        f"# Saved OpenRouter responses\n\nWritten by `scripts/openrouter_probe.py` on "
        f"{datetime.now(UTC).date()} with model `{args.model}` (batch: `{batch_model}`). "
        f"Ids and key material are redacted. Batch usage block: `{json.dumps(usage)}`.\n"
    )
    print("sync usage:", json.dumps(redact(json.loads((OUT / 'structured.json').read_text())["response"]["usage"])))  # type: ignore[index]
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [x] **Step 4: Run the helper test; run `make check`**

Run: `uv run pytest tests/test_openrouter_probe.py -v && make check` — Expected: PASS.

- [x] **Step 5: Andy runs the probe**

```bash
export OPENROUTER_API_KEY=...   # never in git
uv run python -m scripts.openrouter_probe --model openai/gpt-5.6-luna
uv run python -m scripts.openrouter_probe --model openai/gpt-5.6-luna-pro --cases 10
```

Read the four files. Record in the Deviations section: which usage fields exist (`prompt_tokens`, `completion_tokens`, `cost`?), whether `response_format` was honoured (content is valid JSON matching the mini schema), whether the batch reached `completed` and how long it took, and which Luna variant is chosen, with the reason (both cost the same; prefer the one whose ten replies all parsed; if both, prefer `luna`). Keep only the chosen variant's fixtures.

- [x] **Step 6: Commit the fixtures**

```bash
git add scripts/openrouter_probe.py tests/test_openrouter_probe.py tests/fixtures/openrouter/
git commit -m "S1: OpenRouter probe and saved responses"
```

---

### Task 3: Model types and the sync OpenRouter client

**Files:**
- Modify: `src/ntsb_probable_cause/model/client.py`
- Create: `src/ntsb_probable_cause/model/openrouter.py`
- Test: `tests/test_model_client.py`, `tests/test_openrouter.py`

**Interfaces:**
- Consumes: `tests/fixtures/openrouter/structured.json`, `tool_call.json`, `two_turn.json`.
- Produces:

```python
class Usage(BaseModel):            # frozen
    prompt_tokens: int
    completion_tokens: int
    reported_cost_usd: float | None   # provider's usage.cost, if present

class ToolCall(BaseModel):         # frozen
    call_id: str
    name: str
    arguments: str                  # raw JSON text

class ModelReply(BaseModel):       # frozen
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: Usage
    model: str
    response_id: str

class ModelSettings(BaseModel):    # frozen
    model: str = "openai/gpt-5.6-luna"
    price_variant: Literal["batch", "standard"] = "batch"
    temperature: float = 0.0
    max_output_tokens: int = 2000
    json_schema: dict[str, object] | None = None
    schema_name: str = "hypothesis"
    tools: tuple[dict[str, object], ...] = ()
    def model_id(self) -> str        # appends ":batch" when price_variant == "batch"

class Turn(BaseModel):             # frozen; one prior message for a multi-turn exchange
    role: Literal["assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

class ModelClient(Protocol):
    def complete(self, payload: Payload, settings: ModelSettings, *, system: str = "", history: Sequence[Turn] = ()) -> ModelReply: ...

class RecordingFakeClient:
    def __init__(self, replies: Sequence[str] = ("",)) -> None
    payloads: list[Payload]; histories: list[tuple[Turn, ...]]

def parse_chat_completion(body: Mapping[str, object]) -> ModelReply
def cost_usd(reply: ModelReply, settings: ModelSettings) -> tuple[float, str]   # (dollars, "reported" | "priced")

class OpenRouterClient:            # model/openrouter.py
    def __init__(self, api_key: str, *, base_url: str = sources.OPENROUTER_BASE_URL, requests_per_minute: int = 60, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep, max_attempts: int = 5, backoff_seconds: float = 2.0) -> None
    def complete(...) -> ModelReply          # as the protocol
    def request_body(payload, settings, *, system, history) -> dict[str, object]   # the exact JSON sent; reused by the batch client
```

- [x] **Step 1: Write the failing tests**

```python
# tests/test_openrouter.py
import json
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import ModelSettings, Payload, Turn, cost_usd, parse_chat_completion
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.records.evidence import Evidence

FIX = Path("tests/fixtures/openrouter")
URL = "https://openrouter.ai/api/v1/chat/completions"
EVIDENCE = Evidence(case_id="X", docket_url=None, aircraft_make="CESSNA", phase_of_flight="Landing")


def saved(name: str) -> dict[str, object]:
    return json.loads((FIX / f"{name}.json").read_text())


def test_parse_structured_reply_from_saved_response() -> None:
    reply = parse_chat_completion(saved("structured")["response"])
    assert reply.content and json.loads(reply.content)["phase"]
    assert reply.tool_calls == ()
    assert reply.usage.prompt_tokens > 0 and reply.usage.completion_tokens > 0
    assert reply.response_id == "redacted"


def test_parse_tool_call_reply_from_saved_response() -> None:
    reply = parse_chat_completion(saved("tool_call")["response"])
    assert reply.tool_calls[0].name == "get_weather"
    assert json.loads(reply.tool_calls[0].arguments) == {}


def test_parse_two_turn_reply_from_saved_response() -> None:
    reply = parse_chat_completion(saved("two_turn")["response"])
    assert reply.content is not None


def test_cost_uses_reported_cost_when_present_else_price_table() -> None:
    reply = parse_chat_completion(saved("structured")["response"])
    settings = ModelSettings(model="openai/gpt-5.6-luna", price_variant="standard")
    dollars, how = cost_usd(reply, settings)
    if reply.usage.reported_cost_usd is not None:
        assert how == "reported" and dollars == reply.usage.reported_cost_usd
    else:
        expected = reply.usage.prompt_tokens * 0.20 / 1e6 + reply.usage.completion_tokens * 1.20 / 1e6
        assert how == "priced" and dollars == pytest.approx(expected)


def test_model_id_appends_batch_suffix() -> None:
    assert ModelSettings(model="openai/gpt-5.6-luna").model_id() == "openai/gpt-5.6-luna:batch"
    assert ModelSettings(model="openai/gpt-5.6-luna", price_variant="standard").model_id() == "openai/gpt-5.6-luna"


def test_client_sends_schema_system_and_history(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(URL).mock(return_value=httpx.Response(200, json=saved("two_turn")["response"]))
    client = OpenRouterClient("or-key", sleep=lambda _s: None)
    settings = ModelSettings(json_schema={"type": "object"}, schema_name="mini", price_variant="standard")
    history = (
        Turn(role="assistant", tool_calls=(saved_tool_call := parse_chat_completion(saved("tool_call")["response"]).tool_calls)),
        Turn(role="tool", tool_call_id=saved_tool_call[0].call_id, content="{}"),
    )
    client.complete(Payload.from_evidence(EVIDENCE), settings, system="SYS", history=history)
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "openai/gpt-5.6-luna"
    assert sent["messages"][0] == {"role": "system", "content": "SYS"}
    assert sent["messages"][1]["role"] == "user" and "CESSNA" in sent["messages"][1]["content"]
    assert sent["messages"][2]["role"] == "assistant" and sent["messages"][3]["role"] == "tool"
    assert sent["response_format"]["json_schema"]["name"] == "mini"
    assert sent["temperature"] == 0
    assert route.calls[0].request.headers["authorization"] == "Bearer or-key"


def test_client_retries_then_raises(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(URL).mock(return_value=httpx.Response(503, text="down"))
    sleeps: list[float] = []
    client = OpenRouterClient("k", sleep=sleeps.append, max_attempts=3, backoff_seconds=1.0)
    with pytest.raises(ModelError, match="3 attempts"):
        client.complete(Payload.from_evidence(EVIDENCE), ModelSettings())
    assert sleeps.count(1.0) == 1 and sleeps.count(2.0) == 1


def test_client_does_not_retry_a_400(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(URL).mock(return_value=httpx.Response(400, text="bad schema"))
    with pytest.raises(ModelError, match="400"):
        OpenRouterClient("k", sleep=lambda _s: None).complete(Payload.from_evidence(EVIDENCE), ModelSettings())
```

Also update `tests/test_model_client.py`: replace `RecordingFakeClient()` usages so `test_fake_replays_scripted_replies` asserts `client.complete(payload, ModelSettings()).content == "first"` then `"second"` then `"second"`.

- [x] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_openrouter.py tests/test_model_client.py -v` — Expected: FAIL on imports.

- [x] **Step 3: Implement `model/client.py` changes**

Replace `ModelSettings`, `ModelReply`, `ModelClient`, `RecordingFakeClient` with:

```python
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


def parse_chat_completion(body: Mapping[str, object]) -> ModelReply:
    """Parse a chat-completion body. Field names are those of the saved probe responses."""
    try:
        choice = body["choices"][0]  # type: ignore[index]
        message = choice["message"]
        usage = body["usage"]
        calls = tuple(
            ToolCall(call_id=c["id"], name=c["function"]["name"], arguments=c["function"]["arguments"])
            for c in message.get("tool_calls") or ()
        )
        return ModelReply(
            content=message.get("content"),
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=int(usage["prompt_tokens"]),
                completion_tokens=int(usage["completion_tokens"]),
                reported_cost_usd=float(usage["cost"]) if usage.get("cost") is not None else None,
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
```

Add imports: `from typing import Literal`, `from collections.abc import Mapping`, `from ntsb_probable_cause import sources`, `from ntsb_probable_cause.errors import LeakageError, ModelError`.

- [x] **Step 4: Implement `model/openrouter.py`**

```python
"""The OpenRouter chat-completions client: one implementation of ModelClient (spec §7.2)."""

import json
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
                    {"id": c.call_id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in turn.tool_calls
                ]
            messages.append(message)
        else:
            messages.append({"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.content})
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
            "json_schema": {"name": settings.schema_name, "strict": True, "schema": settings.json_schema},
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

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, _kind: type[BaseException] | None, _value: BaseException | None, _tb: TracebackType | None
    ) -> None:
        self._http.close()

    def complete(
        self, payload: Payload, settings: ModelSettings, *, system: str = "", history: Sequence[Turn] = ()
    ) -> ModelReply:
        """Send one chat completion and parse the reply."""
        body = request_body(payload, settings, system=system, history=history)
        return parse_chat_completion(self.request_json(sources.CHAT_COMPLETIONS, method="POST", body=body))

    def request_json(self, path: str, *, method: str, body: dict[str, object] | None = None) -> dict[str, object]:
        """One retry loop for GET and POST, with the run's rate limit; the batch client uses it too."""
        status: object = None
        for attempt in range(1, self._max_attempts + 1):
            if self._requested:
                self._sleep(self._gap)
            self._requested = True
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
                self._sleep(self._backoff * 2 ** (attempt - 1))
        raise ModelError(f"{path} failed after {self._max_attempts} attempts; last status {status}")
```

`tests/boundary.py` needs no change: `complete(payload, settings)` still works.

- [x] **Step 5: Run tests and `make check`**

Run: `uv run pytest tests/test_openrouter.py tests/test_model_client.py tests/test_boundary.py -v && make check` — Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/model tests/test_openrouter.py tests/test_model_client.py
git commit -m "S1: real ModelReply from saved responses; OpenRouter sync client"
```

---

### Task 4: The batch client

**Files:**
- Create: `src/ntsb_probable_cause/model/batch.py`
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: `OpenRouterClient.request_json`, `request_body`, `parse_chat_completion`, `tests/fixtures/openrouter/batch.json`.
- Produces:

```python
class BatchRequest(BaseModel):   # frozen
    custom_id: str
    payload: Payload             # arbitrary_types_allowed
    settings: ModelSettings
    system: str = ""
    history: tuple[Turn, ...] = ()

class BatchResult(BaseModel):    # frozen
    custom_id: str
    reply: ModelReply | None
    error: str | None

class BatchStatus(BaseModel):    # frozen
    batch_id: str
    status: str                  # validating | in_progress | finalizing | completed | failed | expired | cancelled
    results: tuple[BatchResult, ...]
    reported_cost_usd: float | None

TERMINAL = frozenset({"completed", "failed", "expired", "cancelled"})

class BatchClient:
    def __init__(self, http: OpenRouterClient) -> None
    def submit(self, requests: Sequence[BatchRequest]) -> str            # returns batch id
    def poll(self, batch_id: str) -> BatchStatus
    def wait(self, batch_id: str, *, every_seconds: float = 60.0, sleep: Callable[[float], None] = time.sleep, on_status: Callable[[str], None] = lambda s: None) -> BatchStatus   # until TERMINAL
```

- [x] **Step 1: Write the failing tests**

Implemented as `tests/test_batch.py`, with three additional tests beyond the brief's two (see
the Deviations section): `test_submit_rejects_mixed_model_ids`, `test_poll_reports_batch_level_cost`,
`test_poll_handles_a_result_with_no_body`, and
`test_reply_parsed_from_batch_has_no_reported_cost_and_prices_at_batch_rate` (carried from Task
3's review — the `cost_usd` "priced" branch).

- [x] **Step 2: Run to verify failure** — `uv run pytest tests/test_batch.py -v` → FAIL, module missing.

- [x] **Step 3: Implement**

```python
"""OpenRouter's batch service: submit, poll, collect (spec §7.2, read 2026-09-15)."""

import time
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import ModelReply, ModelSettings, Payload, Turn, parse_chat_completion
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


class BatchClient:
    """Submit many requests at the batch price and collect them when done."""

    def __init__(self, http: OpenRouterClient) -> None:
        self._http = http

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        """Submit one batch. Every request must share a model id."""
        model_ids = {r.settings.model_id() for r in requests}
        if len(model_ids) != 1:
            raise ModelError(f"a batch needs one model id, got {sorted(model_ids)}")
        body = {
            "endpoint": "/v1/chat/completions",
            "model": next(iter(model_ids)),
            "requests": [
                {"custom_id": r.custom_id, "body": request_body(r.payload, r.settings, system=r.system, history=r.history)}
                for r in requests
            ],
        }
        submitted = self._http.request_json(sources.BATCHES, method="POST", body=body)
        return str(submitted["id"])

    def poll(self, batch_id: str) -> BatchStatus:
        """Read the batch's current status and any results."""
        raw = self._http.request_json(f"{sources.BATCHES}/{batch_id}", method="GET")
        results: list[BatchResult] = []
        for item in raw.get("results") or ():  # type: ignore[union-attr]
            response = item.get("response")
            if response and isinstance(response.get("body"), dict):
                results.append(BatchResult(custom_id=str(item["custom_id"]), reply=parse_chat_completion(response["body"]), error=None))
            else:
                results.append(BatchResult(custom_id=str(item["custom_id"]), reply=None, error=str(item.get("error") or response)))
        usage = raw.get("usage") or {}
        cost = usage.get("cost") if isinstance(usage, dict) else None  # type: ignore[union-attr]
        return BatchStatus(
            batch_id=batch_id,
            status=str(raw.get("status")),
            results=tuple(results),
            reported_cost_usd=float(cost) if cost is not None else None,
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
```

If the saved `batch.json` nests results differently (for example a `body` under `response` versus inline), follow the fixture and log a deviation.

The saved `batch.json` nests results as `results[].response.body` (a `body` under `response`),
matching the brief — no deviation needed there. `poll`/`_result_from_item` were implemented with
`isinstance`-narrowing helpers (`_as_mapping`, `_as_sequence`), per Task 3's precedent, instead of
the brief's `# type: ignore[union-attr]` comments.

- [x] **Step 4: Run tests and `make check`** — Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/model/batch.py tests/test_batch.py
git commit -m "S1: batch client — submit, poll, collect"
```

---

### Task 5: The code tables, and `finding_codes_in_cause`

**Files:**
- Create: `scripts/build_code_tables.py`
- Create: `src/ntsb_probable_cause/scoring/__init__.py`, `scoring/codes.py`, `scoring/tables/{phases,events,categories,items,modifiers}.csv`
- Create: `docs/results/s1-code-tables.txt`
- Modify: `src/ntsb_probable_cause/fields.py`, `records/verdict.py`, `records/split.py`, `pyproject.toml` (package data is included by hatchling automatically for files under the package; confirm with `uv build` listing)
- Test: `tests/test_codes.py`, `tests/test_records.py`

**Interfaces:**
- Produces:

```python
# scoring/codes.py
class CodeTables:                       # frozen dataclass, loaded once
    phases: Mapping[str, str]           # "552" -> "Landing-landing roll"
    events: Mapping[str, str]           # "230" -> "Loss of control on ground"
    categories: Mapping[str, str]       # "020630" -> "Personnel issues — Task performance — Use of equip/info"
    items: Mapping[str, str]            # "02063040" -> "... — Aircraft control", with definition appended after " | "
    modifiers: Mapping[str, str]        # "44" -> "Pilot"
    def items_under(self, category6: str) -> Mapping[str, str]
    def compose_occurrence(self, phase: str, event: str) -> str          # raises SchemaError if unknown
    def compose_finding(self, item8: str, modifier: str) -> str          # raises SchemaError if unknown
    def render(self, which: Literal["phases","events","categories","modifiers"]) -> str   # "code  label" lines
def load_tables() -> CodeTables
# fields.py
def finding_codes_in_cause(raw: Raw) -> tuple[str, ...]
# verdict.py
class Verdict: ... finding_codes_in_cause: tuple[str, ...]
```

- [x] **Step 1: Write the failing tests**

```python
# tests/test_codes.py
import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import load_tables


def test_tables_have_the_measured_sizes() -> None:
    t = load_tables()
    assert len(t.phases) >= 43 and len(t.events) == 94
    assert len(t.categories) == 130 and len(t.items) == 1019 and len(t.modifiers) == 73


def test_compose_and_validate() -> None:
    t = load_tables()
    assert t.compose_occurrence("552", "230") == "552230"
    assert t.compose_finding("02063040", "44") == "0206304044"
    with pytest.raises(SchemaError):
        t.compose_occurrence("999", "230")
    with pytest.raises(SchemaError):
        t.compose_finding("02063040", "ZZ")


def test_items_under_a_category_are_its_children_only() -> None:
    t = load_tables()
    children = t.items_under("020630")
    assert children and all(k.startswith("020630") for k in children)


def test_render_lists_code_then_label() -> None:
    line = load_tables().render("modifiers").splitlines()[0]
    code, label = line.split("  ", 1)
    assert len(code) == 2 and label
```

Append to `tests/test_records.py`:

```python
def test_verdict_carries_flagged_findings(record_fixtures: list[dict[str, object]]) -> None:
    for raw in record_fixtures:
        _, _, verdict = split_record(raw)
        assert set(verdict.finding_codes_in_cause) <= set(verdict.finding_codes)
        flagged = [f["findingCode"] for f in raw["aircrafts"][0]["findings"] if f.get("inProbableCause")]  # type: ignore[index]
        assert list(verdict.finding_codes_in_cause) == flagged
```

- [x] **Step 2: Run to verify failure** — FAIL on imports.

- [x] **Step 3: Write `scripts/build_code_tables.py`**

```python
"""Build the code tables from the NTSB data dictionary in avall.zip (spec §3.1, decision 0025).

Usage:
    uv run python -m scripts.build_code_tables ../ntsb-spike/data/raw/avall.zip

Needs mdbtools (`brew install mdbtools`). Writes labels only: five CSVs under
src/ntsb_probable_cause/scoring/tables/ and a summary under docs/results/s1-code-tables.txt.
Phase labels come from the Events_Sequence table's Occurrence_Description, "<phase> <event>",
by stripping the known event meaning from the end.
"""

import csv
import io
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

TABLES = Path("src/ntsb_probable_cause/scoring/tables")
RESULT = Path("docs/results/s1-code-tables.txt")


def export(mdb: str, table: str) -> list[dict[str, str]]:
    """Export one table with mdbtools."""
    out = subprocess.run(["mdb-export", mdb, table], capture_output=True, text=True, check=True).stdout  # noqa: S603,S607
    return list(csv.DictReader(io.StringIO(out)))


def write(name: str, rows: dict[str, str]) -> None:
    """Write code,label sorted by code."""
    TABLES.mkdir(parents=True, exist_ok=True)
    with (TABLES / f"{name}.csv").open("w", newline="") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(["code", "label"])
        w.writerows(sorted(rows.items()))


def main(argv: list[str]) -> int:
    """Build the five tables."""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(argv[0]) as z:
        z.extract("avall.mdb", tmp)
        mdb = f"{tmp}/avall.mdb"
        dictionary = export(mdb, "eADMSPUB_DataDictionary")
        sequence = export(mdb, "Events_Sequence")
    items: dict[str, str] = {}
    definitions: dict[str, str] = {}
    for r in dictionary:
        if r["Table"] == "Findings" and r["Column"] == "findings_code" and r["code_iaids"].endswith("XX"):
            items[r["code_iaids"][:8]] = r["meaning"].replace(" - ", " — ")
            if r.get("Question_Def"):
                definitions[r["code_iaids"][:8]] = r["Question_Def"].strip()
    modifiers = {r["code_iaids"][-2:]: r["meaning"] for r in dictionary if r["Table"] == "Findings" and r["Column"] == "modifier_no"}
    events = {r["code_iaids"][-3:]: r["meaning"] for r in dictionary if r["Table"] == "Events_Sequence" and r["Column"] == "Occurrence_Code"}
    categories = {}
    for code, label in items.items():
        parts = label.split(" — ")
        categories.setdefault(code[:6], " — ".join(parts[:3]))
    phases: Counter[tuple[str, str]] = Counter()
    for r in sequence:
        phase_no, event_no, desc = r["phase_no"], r["eventsoe_no"], r["Occurrence_Description"]
        meaning = events.get(event_no)
        if phase_no and meaning and desc.endswith(meaning):
            phases[(phase_no, desc[: -len(meaning)].strip())] += 1
    phase_labels: dict[str, str] = {}
    for (code, label), _ in phases.most_common():
        phase_labels.setdefault(code, label)
    write("phases", phase_labels)
    write("events", events)
    write("categories", categories)
    write("items", {k: f"{v} | {definitions.get(k, '')}".rstrip(" |") for k, v in items.items()})
    write("modifiers", modifiers)
    RESULT.write_text(
        f"S1 code tables, built {datetime.now(UTC).date()} from {Path(argv[0]).name} by scripts/build_code_tables.py\n"
        f"phases {len(phase_labels)}; events {len(events)}; categories {len(categories)}; items {len(items)}; modifiers {len(modifiers)}\n"
    )
    print(RESULT.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Run it: `uv run python -m scripts.build_code_tables ../ntsb-spike/data/raw/avall.zip`. Check the counts against M10 (events 94, categories 130, items 1019, modifiers 73). Open `phases.csv` and confirm `552` reads "Landing-landing roll" and there are at least 43 rows. Add the corpus check from the spec: extend the script to also load `data/processed/cases.parquet` if present and print codes in use that the tables lack; append that line to the results file.

- [x] **Step 4: Write `scoring/codes.py`**

```python
"""The code tables the model chooses from, and composition of its choices (decision 0025)."""

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

from ntsb_probable_cause.errors import SchemaError

TableName = Literal["phases", "events", "categories", "items", "modifiers"]


@dataclass(frozen=True)
class CodeTables:
    """Five code → label maps, from the NTSB data dictionary."""

    phases: Mapping[str, str]
    events: Mapping[str, str]
    categories: Mapping[str, str]
    items: Mapping[str, str]
    modifiers: Mapping[str, str]

    def items_under(self, category6: str) -> Mapping[str, str]:
        """The eight-digit items whose first six digits are the category."""
        return {k: v for k, v in self.items.items() if k.startswith(category6)}

    def compose_occurrence(self, phase: str, event: str) -> str:
        """Join a phase prefix and an event suffix; both must be in the tables."""
        if phase not in self.phases:
            raise SchemaError(f"unknown phase prefix {phase!r}")
        if event not in self.events:
            raise SchemaError(f"unknown event suffix {event!r}")
        return f"{phase}{event}"

    def compose_finding(self, item8: str, modifier: str) -> str:
        """Join an eight-digit item and a two-digit modifier; both must be in the tables."""
        if item8 not in self.items:
            raise SchemaError(f"unknown finding item {item8!r}")
        if modifier not in self.modifiers:
            raise SchemaError(f"unknown modifier {modifier!r}")
        return f"{item8}{modifier}"

    def render(self, which: TableName) -> str:
        """One line per code, ``code  label``, sorted by code; what the prompt shows."""
        table: Mapping[str, str] = getattr(self, which)
        return "\n".join(f"{code}  {label}" for code, label in sorted(table.items()))


def _read(name: TableName) -> dict[str, str]:
    text = resources.files("ntsb_probable_cause.scoring").joinpath(f"tables/{name}.csv").read_text()
    return {row["code"]: row["label"] for row in csv.DictReader(text.splitlines())}


@cache
def load_tables() -> CodeTables:
    """Load the committed tables once."""
    return CodeTables(
        phases=_read("phases"),
        events=_read("events"),
        categories=_read("categories"),
        items=_read("items"),
        modifiers=_read("modifiers"),
    )
```

`scoring/__init__.py`: `"""Scoring: what the model must answer and how it is marked (S1)."""`.

- [x] **Step 5: Add `finding_codes_in_cause`**

`fields.py`, after `finding_codes`:

```python
def finding_codes_in_cause(raw: Raw) -> tuple[str, ...]:
    """Verdict: the finding codes the NTSB flagged as in the probable cause, by finding number."""
    findings = sorted(_dicts(resolve_path(raw, "aircrafts[0].findings")), key=_finding_number)
    return tuple(
        code
        for f in findings
        if f.get("inProbableCause") is True and isinstance(code := f.get("findingCode"), str)
    )
```

`verdict.py`: add `finding_codes_in_cause: tuple[str, ...]` after `finding_codes`. `split.py`: pass `finding_codes_in_cause=fields.finding_codes_in_cause(raw)`. Fix any test that constructs `Verdict(...)` directly (`grep -rn "Verdict(" tests`).

- [x] **Step 6: Run tests and `make check`** — Expected: PASS, including `tests/test_boundary.py` (codes in the tripwire are unchanged: `codes()` already covers all findings).

- [x] **Step 7: Commit**

```bash
git add scripts/build_code_tables.py src/ntsb_probable_cause/scoring docs/results/s1-code-tables.txt src/ntsb_probable_cause/fields.py src/ntsb_probable_cause/records tests/test_codes.py tests/test_records.py
git commit -m "S1: code tables from the NTSB data dictionary; flagged findings in Verdict"
```

---

### Task 6: The Hypothesis schema and the prompt

**Files:**
- Create: `src/ntsb_probable_cause/scoring/hypothesis.py`, `scoring/prompt.py`
- Test: `tests/test_hypothesis.py`

**Interfaces:**
- Consumes: `CodeTables`, `load_tables`, `ModelReply`.
- Produces:

```python
class OccurrenceGuess(BaseModel):  phase: str; event: str; probability: float        # frozen
class FindingGuess(BaseModel):     category6: str; modifier: str; probability: float; item8: str | None = None
class Hypothesis(BaseModel):       # frozen, extra="forbid"
    evidence_narrative: str
    occurrence: tuple[OccurrenceGuess, ...]     # 1..3, ordered
    findings: tuple[FindingGuess, ...]
    probable_cause: str
    lay_explanation: str
    confidence: float                            # 0..1
    abstain: bool
    evidence_used: tuple[str, ...]
    def occurrence_codes(self, tables: CodeTables) -> tuple[str, ...]      # composed, ordered
    def finding_codes(self, tables: CodeTables) -> tuple[str, ...]         # composed 10-digit, only guesses with item8
    def occurrence_distribution(self, tables) -> dict[str, float]          # code -> p, plus "other"
    def with_items(self, items: Mapping[int, str]) -> Hypothesis           # index of finding -> item8
class Refinement(BaseModel):       # stage-2 reply
    items: tuple[RefinedItem, ...]  # RefinedItem: index: int; item8: str
HYPOTHESIS_SCHEMA: dict[str, object]     # JSON schema, strict
REFINEMENT_SCHEMA: dict[str, object]
def parse_hypothesis(text: str, tables: CodeTables) -> Hypothesis          # raises SchemaError
def parse_refinement(text: str, tables: CodeTables, hypothesis: Hypothesis) -> Hypothesis
# prompt.py
PROMPT_VERSION = "s1-v1"
SYSTEM_ANSWER: str
SYSTEM_REFINE: str
def tables_block(tables: CodeTables, *, case_number: str | None = None) -> str   # the four tables, and the case-number line on the development probe only; goes in the SYSTEM text, never in the Payload
def refine_message(hypothesis: Hypothesis, tables: CodeTables) -> str            # stage-1 findings + children lists
```

- [x] **Step 1: Write the failing tests**

```python
# tests/test_hypothesis.py
import json

import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import HYPOTHESIS_SCHEMA, parse_hypothesis, parse_refinement
from ntsb_probable_cause.scoring.prompt import refine_message, tables_block

GOOD = {
    "evidence_narrative": "The airplane departed the runway during the landing roll.",
    "occurrence": [{"phase": "552", "event": "230", "probability": 0.6}, {"phase": "551", "event": "230", "probability": 0.2}],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.7}],
    "probable_cause": "The pilot's loss of directional control during the landing roll.",
    "lay_explanation": "The plane swerved off the runway after touching down.",
    "confidence": 0.6,
    "abstain": False,
    "evidence_used": ["phase_of_flight", "weather_condition"],
}


def test_parse_good_hypothesis_composes_codes() -> None:
    h = parse_hypothesis(json.dumps(GOOD), load_tables())
    assert h.occurrence_codes(load_tables()) == ("552230", "551230")
    assert h.finding_codes(load_tables()) == ()   # no items yet
    dist = h.occurrence_distribution(load_tables())
    assert dist["552230"] == 0.6 and dist["other"] == pytest.approx(0.2)


def test_unknown_code_is_a_schema_error() -> None:
    bad = {**GOOD, "occurrence": [{"phase": "000", "event": "230", "probability": 1.0}]}
    with pytest.raises(SchemaError, match="phase"):
        parse_hypothesis(json.dumps(bad), load_tables())


def test_probabilities_over_one_are_a_schema_error() -> None:
    bad = {**GOOD, "occurrence": [{"phase": "552", "event": "230", "probability": 0.8}, {"phase": "551", "event": "230", "probability": 0.5}]}
    with pytest.raises(SchemaError, match="sum"):
        parse_hypothesis(json.dumps(bad), load_tables())


def test_refinement_attaches_items_and_composes_ten_digits() -> None:
    t = load_tables()
    h = parse_hypothesis(json.dumps(GOOD), t)
    refined = parse_refinement(json.dumps({"items": [{"index": 0, "item8": "02063040"}]}), t, h)
    assert refined.finding_codes(t) == ("0206304044",)
    with pytest.raises(SchemaError, match="child"):
        parse_refinement(json.dumps({"items": [{"index": 0, "item8": "01022214"}]}), t, h)


def test_schema_is_strict_and_tables_block_holds_tables() -> None:
    assert HYPOTHESIS_SCHEMA["additionalProperties"] is False
    block = tables_block(load_tables())
    assert block.startswith("## Phase prefixes") and "552  " in block and "44  Pilot" in block
    assert "## Case number" not in block
    assert tables_block(load_tables(), case_number="CEN16LA001").endswith("## Case number\nCEN16LA001\n")
    h = parse_hypothesis(json.dumps(GOOD), load_tables())
    assert "02063040" in refine_message(h, load_tables())
```

- [x] **Step 2: Run to verify failure** — FAIL on imports.

- [x] **Step 3: Implement `hypothesis.py`**

```python
"""The model's answer: one Hypothesis for a one-shot pass and for every step of a trail (spec §3.4)."""

import json
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import CodeTables


class OccurrenceGuess(BaseModel):
    """One ranked occurrence guess."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    phase: str
    event: str
    probability: float = Field(ge=0, le=1)


class FindingGuess(BaseModel):
    """One finding guess at stage 1 (category + modifier) and, after stage 2, its item."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    category6: str
    modifier: str
    probability: float = Field(ge=0, le=1)
    item8: str | None = None


class Hypothesis(BaseModel):
    """The structured answer (decisions 0006, 0013, 0021)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence_narrative: str
    occurrence: tuple[OccurrenceGuess, ...] = Field(min_length=1, max_length=3)
    findings: tuple[FindingGuess, ...]
    probable_cause: str
    lay_explanation: str
    confidence: float = Field(ge=0, le=1)
    abstain: bool
    evidence_used: tuple[str, ...]

    def occurrence_codes(self, tables: CodeTables) -> tuple[str, ...]:
        """Composed six-digit codes, ranked."""
        return tuple(tables.compose_occurrence(g.phase, g.event) for g in self.occurrence)

    def finding_codes(self, tables: CodeTables) -> tuple[str, ...]:
        """Composed ten-digit codes for guesses that have an item."""
        return tuple(
            tables.compose_finding(g.item8, g.modifier) for g in self.findings if g.item8 is not None
        )

    def occurrence_distribution(self, tables: CodeTables) -> dict[str, float]:
        """Probability per composed code, with the remainder under ``other``."""
        dist = {code: g.probability for code, g in zip(self.occurrence_codes(tables), self.occurrence, strict=True)}
        dist["other"] = max(0.0, 1.0 - sum(dist.values()))
        return dist

    def with_items(self, items: Mapping[int, str]) -> "Hypothesis":
        """A copy with stage-2 items attached by finding index."""
        findings = tuple(
            g.model_copy(update={"item8": items.get(i, g.item8)}) for i, g in enumerate(self.findings)
        )
        return self.model_copy(update={"findings": findings})


class RefinedItem(BaseModel):
    """Stage 2: the chosen item for one stage-1 finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int = Field(ge=0)
    item8: str


class Refinement(BaseModel):
    """The stage-2 reply."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[RefinedItem, ...]


HYPOTHESIS_SCHEMA: dict[str, object] = Hypothesis.model_json_schema()
HYPOTHESIS_SCHEMA["additionalProperties"] = False
REFINEMENT_SCHEMA: dict[str, object] = Refinement.model_json_schema()
REFINEMENT_SCHEMA["additionalProperties"] = False


def parse_hypothesis(text: str, tables: CodeTables) -> Hypothesis:
    """Parse and validate a stage-1 reply against the tables."""
    try:
        hypothesis = Hypothesis.model_validate(json.loads(text))
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"reply is not a Hypothesis: {error}") from error
    if sum(g.probability for g in hypothesis.occurrence) > 1.0 + 1e-9:
        raise SchemaError("occurrence probabilities sum to more than 1")
    hypothesis.occurrence_codes(tables)
    for g in hypothesis.findings:
        if g.category6 not in tables.categories:
            raise SchemaError(f"unknown finding category {g.category6!r}")
        if g.modifier not in tables.modifiers:
            raise SchemaError(f"unknown modifier {g.modifier!r}")
    return hypothesis


def parse_refinement(text: str, tables: CodeTables, hypothesis: Hypothesis) -> Hypothesis:
    """Parse a stage-2 reply and attach each item to its finding; items must be children."""
    try:
        refinement = Refinement.model_validate(json.loads(text))
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"reply is not a Refinement: {error}") from error
    items: dict[int, str] = {}
    for chosen in refinement.items:
        if chosen.index >= len(hypothesis.findings):
            raise SchemaError(f"refinement index {chosen.index} has no finding")
        category = hypothesis.findings[chosen.index].category6
        if chosen.item8 not in tables.items_under(category):
            raise SchemaError(f"{chosen.item8!r} is not a child of category {category!r}")
        items[chosen.index] = chosen.item8
    return hypothesis.with_items(items)
```

If the provider's strict mode rejects pydantic's schema (for example `$defs`), inline the definitions with `pydantic.json_schema.GenerateJsonSchema(ref_template=...)` or a small resolver, and log a deviation.

- [x] **Step 4: Implement `prompt.py`**

```python
"""System prompts and message rendering. Versioned: the run record carries PROMPT_VERSION (spec §3.5)."""

from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

PROMPT_VERSION = "s1-v1"

SYSTEM_ANSWER = """You are an aviation accident analyst working from the evidence investigators recorded.
First write an evidence narrative: what the evidence shows, in plain clinical prose, without naming any
person. Then decide the probable cause.

Choose codes only from the tables in the message. For the occurrence, give up to three guesses, each a
phase prefix and an event suffix with a probability; the probabilities may sum to less than 1. For the
findings in the probable cause, give one or more six-digit categories, each with a modifier (who or
what) and a probability. Write the probable cause in one or two sentences in the NTSB's style, and a lay
explanation a reader with no aviation knowledge can follow. State your confidence that your first
occurrence guess is right. If the evidence is too thin to name a cause, set abstain to true and say why
in the narrative. Reply only with JSON matching the schema."""

SYSTEM_REFINE = """You chose finding categories for this case. For each, choose the single most specific
item from the list of that category's items given in the message. Reply only with JSON matching the
schema: one entry per finding index."""


def tables_block(tables: CodeTables, *, case_number: str | None = None) -> str:
    """The four choice tables, appended to the system text. The Payload stays the evidence alone,
    so S0's provenance check still reads it unchanged. The case-number line exists only for the
    development-split probe (spec §6.2); the runner refuses it elsewhere."""
    block = (
        f"## Phase prefixes (first three digits of the occurrence code)\n{tables.render('phases')}\n\n"
        f"## Event suffixes (last three digits of the occurrence code)\n{tables.render('events')}\n\n"
        f"## Finding categories (first six digits of a finding code)\n{tables.render('categories')}\n\n"
        f"## Modifiers (last two digits of a finding code: who or what)\n{tables.render('modifiers')}\n"
    )
    if case_number is not None:
        block += f"\n## Case number\n{case_number}\n"
    return block


def refine_message(hypothesis: Hypothesis, tables: CodeTables) -> str:
    """The stage-1 findings and, for each, its category's items with definitions."""
    parts = ["## Your findings and the items available under each\n"]
    for index, guess in enumerate(hypothesis.findings):
        label = tables.categories[guess.category6]
        parts.append(f"### Finding {index}: {guess.category6}  {label}\n")
        parts.extend(f"{code}  {text}" for code, text in sorted(tables.items_under(guess.category6).items()))
        parts.append("")
    return "\n".join(parts)
```

The system text is therefore `SYSTEM_ANSWER + "\n\n" + tables_block(...)`, and the user message is the Payload text alone. Because the tables are identical in every call, they sit in the system text where the provider's prompt cache, if the probe showed it is honoured, keeps them cheap.

- [x] **Step 5: Run tests and `make check`** — Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/scoring/hypothesis.py src/ntsb_probable_cause/scoring/prompt.py tests/test_hypothesis.py
git commit -m "S1: Hypothesis schema, two-stage parsing against the tables, prompts"
```

---

### Task 7: Metrics — per case, per step, intervals

**Files:**
- Create: `src/ntsb_probable_cause/scoring/metrics.py`
- Modify: `tests/test_import_boundaries.py`, `pyproject.toml` (import-linter contract)
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Verdict`, `Hypothesis`, `CodeTables`.
- Produces:

```python
@dataclass(frozen=True)
class CaseScores:
    occurrence_top1: bool; occurrence_top3: bool; event_match: bool; pair_unseen: bool
    finding_precision_10: float | None; finding_recall_10: float | None    # None when the model gave / the verdict has no codes
    finding_precision_8: float | None; finding_recall_8: float | None; finding_precision_6: float | None; finding_recall_6: float | None
    finding_precision_all_10: float | None; finding_recall_all_10: float | None
    abstained: bool; confidence: float
def score_case(hypothesis: Hypothesis, verdict: Verdict, tables: CodeTables, *, seen_pairs: AbstractSet[str]) -> CaseScores
def primary_occurrence(verdict: Verdict) -> str | None
def prob_on_true(hypothesis, verdict, tables) -> float
def information_gain(before: Hypothesis | None, after: Hypothesis, verdict, tables) -> float
def movement(before: Hypothesis | None, after: Hypothesis, tables) -> float           # total variation
@dataclass(frozen=True) class StepScores: step: int; scores: CaseScores; prob_on_true: float; information_gain: float; movement: float
def score_trail(trail: Sequence[Hypothesis], verdict, tables, *, seen_pairs) -> tuple[StepScores, ...]
def wilson(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]
def paired_difference(a: Sequence[bool], b: Sequence[bool], *, resamples: int = 2000, seed: int = 20260914) -> tuple[float, float, float]   # mean, low, high
def bootstrap_mean(values: Sequence[float], *, resamples=2000, seed=20260914) -> tuple[float, float, float]
@dataclass(frozen=True) class CalibrationBin: low: float; high: float; count: int; mean_confidence: float; accuracy: float
def calibration(confidences: Sequence[float], correct: Sequence[bool], *, bins: int = 10) -> tuple[tuple[CalibrationBin, ...], float]   # bins, expected calibration error
def stated_versus_actual(observed: Sequence[str], gains: Sequence[float]) -> tuple[float, float]   # agreement, chance agreement
```

- [x] **Step 1: Write the failing tests, with hand-worked answers**

```python
# tests/test_metrics.py
import json

import pytest

from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import metrics
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis

T = load_tables()
VERDICT = Verdict(
    probable_cause="x",
    occurrence_codes=("552230", "553000"),
    finding_codes=("0206304044", "0102256099", "0500000000"),
    finding_codes_in_cause=("0206304044", "0102256099"),
)


def hyp(occ: list[tuple[str, str, float]], findings: list[tuple[str, str, str | None]], conf: float = 0.5, abstain: bool = False):
    body = {
        "evidence_narrative": "n", "probable_cause": "p", "lay_explanation": "l", "confidence": conf,
        "abstain": abstain, "evidence_used": [],
        "occurrence": [{"phase": p, "event": e, "probability": pr} for p, e, pr in occ],
        "findings": [{"category6": c[:6], "modifier": m, "probability": 0.5} for c, m, _ in findings],
    }
    h = parse_hypothesis(json.dumps(body), T)
    return h.with_items({i: item for i, (_, _, item) in enumerate(findings) if item})


def test_score_case_by_hand() -> None:
    h = hyp([("551", "230", 0.5), ("552", "230", 0.3)], [("02063040", "44", "02063040"), ("03013010", "99", "03013010")])
    s = metrics.score_case(h, VERDICT, T, seen_pairs={"551230", "552230"})
    assert s.occurrence_top1 is False and s.occurrence_top3 is True and s.event_match is True
    assert s.pair_unseen is False
    # flagged: 0206304044, 0102256099; model: 0206304044, 0301301099
    assert s.finding_precision_10 == 0.5 and s.finding_recall_10 == 0.5
    assert s.finding_precision_6 == 0.5 and s.finding_recall_6 == 0.5
    # against all three findings: precision 1/2, recall 1/3
    assert s.finding_precision_all_10 == 0.5 and s.finding_recall_all_10 == pytest.approx(1 / 3)


def test_abstained_case_scores_zero_on_accuracy() -> None:
    h = hyp([("552", "230", 0.9)], [], abstain=True)
    s = metrics.score_case(h, VERDICT, T, seen_pairs=set())
    assert s.abstained and not s.occurrence_top1 and s.pair_unseen is True


def test_trail_scores_by_hand() -> None:
    steps = [
        hyp([("551", "230", 0.5)], []),                               # p(true)=0
        hyp([("552", "230", 0.4), ("551", "230", 0.4)], []),         # p(true)=0.4
        hyp([("552", "230", 0.7)], []),                               # p(true)=0.7
    ]
    scored = metrics.score_trail(steps, VERDICT, T, seen_pairs={"551230", "552230"})
    assert [s.prob_on_true for s in scored] == [0.0, 0.4, 0.7]
    assert [round(s.information_gain, 6) for s in scored] == [0.0, 0.4, pytest.approx(0.3)]
    # movement step 1 -> 2: before {551230:.5, other:.5}; after {552230:.4, 551230:.4, other:.2}
    # TV = 0.5 * (|0-.4| + |.5-.4| + |.5-.2|) = 0.5 * 0.8 = 0.4
    assert scored[1].movement == pytest.approx(0.4)
    assert scored[0].movement == 0.0


def test_wilson_matches_published_value() -> None:
    low, high = metrics.wilson(23, 40)
    assert (round(low, 3), round(high, 3)) == (0.421, 0.715)


def test_paired_difference_is_zero_for_identical_runs_and_positive_when_a_wins() -> None:
    a = [True] * 30 + [False] * 10
    mean, low, high = metrics.paired_difference(a, a)
    assert (mean, low, high) == (0.0, 0.0, 0.0)
    b = [True] * 20 + [False] * 20
    mean, low, high = metrics.paired_difference(a, b)
    assert mean == pytest.approx(0.25) and low > 0


def test_calibration_by_hand() -> None:
    conf = [0.95, 0.95, 0.15, 0.15]
    right = [True, False, False, False]
    bins, ece = metrics.calibration(conf, right, bins=10)
    top = [b for b in bins if b.count and b.low >= 0.9][0]
    assert top.accuracy == 0.5 and top.mean_confidence == 0.95
    # ece = (2/4)*|0.95-0.5| + (2/4)*|0.15-0| = 0.225 + 0.075
    assert ece == pytest.approx(0.30)


def test_stated_versus_actual() -> None:
    agreement, chance = metrics.stated_versus_actual(["confirmed", "weakened", "unchanged", "confirmed"], [0.2, -0.1, 0.0, -0.3])
    assert agreement == 0.75 and 0 < chance < 1
```

- [x] **Step 2: Run to verify failure** — FAIL on import.

- [x] **Step 3: Implement `metrics.py`**

```python
"""Scores per case and per step, and the intervals they carry (spec §4). Pure functions."""

import random
from collections.abc import AbstractSet, Sequence
from dataclasses import dataclass
from math import sqrt

from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

_SIGN = {"confirmed": 1, "weakened": -1, "unchanged": 0}


@dataclass(frozen=True)
class CaseScores:
    """The §4.1 columns for one case. An abstained case scores False on every accuracy column."""

    occurrence_top1: bool
    occurrence_top3: bool
    event_match: bool
    pair_unseen: bool
    finding_precision_10: float | None
    finding_recall_10: float | None
    finding_precision_8: float | None
    finding_recall_8: float | None
    finding_precision_6: float | None
    finding_recall_6: float | None
    finding_precision_all_10: float | None
    finding_recall_all_10: float | None
    abstained: bool
    confidence: float


def primary_occurrence(verdict: Verdict) -> str | None:
    """The defining event's code: first in the verdict's ordered list."""
    return verdict.occurrence_codes[0] if verdict.occurrence_codes else None


def _precision_recall(predicted: Sequence[str], truth: Sequence[str], digits: int) -> tuple[float | None, float | None]:
    p = {c[:digits] for c in predicted}
    t = {c[:digits] for c in truth}
    precision = len(p & t) / len(p) if p else None
    recall = len(p & t) / len(t) if t else None
    return precision, recall


def score_case(
    hypothesis: Hypothesis, verdict: Verdict, tables: CodeTables, *, seen_pairs: AbstractSet[str]
) -> CaseScores:
    """Score one hypothesis against one verdict."""
    codes = hypothesis.occurrence_codes(tables)
    truth = primary_occurrence(verdict)
    top1 = codes[0]
    answered = not hypothesis.abstain
    predicted = hypothesis.finding_codes(tables) if answered else ()
    p10, r10 = _precision_recall(predicted, verdict.finding_codes_in_cause, 10)
    p8, r8 = _precision_recall(predicted, verdict.finding_codes_in_cause, 8)
    p6, r6 = _precision_recall(predicted, verdict.finding_codes_in_cause, 6)
    pa, ra = _precision_recall(predicted, verdict.finding_codes, 10)
    return CaseScores(
        occurrence_top1=answered and top1 == truth,
        occurrence_top3=answered and truth in codes,
        event_match=answered and truth is not None and top1[3:] == truth[3:],
        pair_unseen=top1 not in seen_pairs,
        finding_precision_10=p10, finding_recall_10=r10,
        finding_precision_8=p8, finding_recall_8=r8,
        finding_precision_6=p6, finding_recall_6=r6,
        finding_precision_all_10=pa, finding_recall_all_10=ra,
        abstained=hypothesis.abstain,
        confidence=hypothesis.confidence,
    )


def prob_on_true(hypothesis: Hypothesis, verdict: Verdict, tables: CodeTables) -> float:
    """The probability the hypothesis puts on the primary occurrence code; 0 if unlisted."""
    truth = primary_occurrence(verdict)
    return hypothesis.occurrence_distribution(tables).get(truth or "", 0.0)


def information_gain(before: Hypothesis | None, after: Hypothesis, verdict: Verdict, tables: CodeTables) -> float:
    """Change in probability on the true code caused by one step; the first step's gain is 0."""
    if before is None:
        return 0.0
    return prob_on_true(after, verdict, tables) - prob_on_true(before, verdict, tables)


def movement(before: Hypothesis | None, after: Hypothesis, tables: CodeTables) -> float:
    """Total variation distance between the occurrence distributions before and after a step."""
    if before is None:
        return 0.0
    a, b = before.occurrence_distribution(tables), after.occurrence_distribution(tables)
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


@dataclass(frozen=True)
class StepScores:
    """The §4.2 numbers for one step of a trail."""

    step: int
    scores: CaseScores
    prob_on_true: float
    information_gain: float
    movement: float


def score_trail(
    trail: Sequence[Hypothesis], verdict: Verdict, tables: CodeTables, *, seen_pairs: AbstractSet[str]
) -> tuple[StepScores, ...]:
    """Score every step of a trail; a one-shot run is a trail of length one."""
    out: list[StepScores] = []
    before: Hypothesis | None = None
    for k, h in enumerate(trail):
        out.append(
            StepScores(
                step=k,
                scores=score_case(h, verdict, tables, seen_pairs=seen_pairs),
                prob_on_true=prob_on_true(h, verdict, tables),
                information_gain=information_gain(before, h, verdict, tables),
                movement=movement(before, h, tables),
            )
        )
        before = h
    return tuple(out)


def wilson(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def bootstrap_mean(values: Sequence[float], *, resamples: int = 2000, seed: int = 20260914) -> tuple[float, float, float]:
    """Mean with a percentile bootstrap 95% interval over cases."""
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)  # noqa: S311 -- statistics, not security
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(resamples))
    return sum(values) / n, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def paired_difference(a: Sequence[bool], b: Sequence[bool], *, resamples: int = 2000, seed: int = 20260914) -> tuple[float, float, float]:
    """Mean of (a − b) per case with its bootstrap interval; a and b are on the same cases."""
    if len(a) != len(b):
        raise ValueError("paired runs must cover the same cases")
    return bootstrap_mean([float(x) - float(y) for x, y in zip(a, b, strict=True)], resamples=resamples, seed=seed)


@dataclass(frozen=True)
class CalibrationBin:
    """One confidence bin."""

    low: float
    high: float
    count: int
    mean_confidence: float
    accuracy: float


def calibration(confidences: Sequence[float], correct: Sequence[bool], *, bins: int = 10) -> tuple[tuple[CalibrationBin, ...], float]:
    """Reliability bins and the expected calibration error."""
    out: list[CalibrationBin] = []
    ece = 0.0
    total = len(confidences)
    for i in range(bins):
        low, high = i / bins, (i + 1) / bins
        members = [(c, r) for c, r in zip(confidences, correct, strict=True) if low <= c < high or (i == bins - 1 and c == 1.0)]
        if not members:
            out.append(CalibrationBin(low, high, 0, 0.0, 0.0))
            continue
        mean_c = sum(c for c, _ in members) / len(members)
        acc = sum(r for _, r in members) / len(members)
        out.append(CalibrationBin(low, high, len(members), mean_c, acc))
        ece += len(members) / total * abs(mean_c - acc)
    return tuple(out), ece


def stated_versus_actual(observed: Sequence[str], gains: Sequence[float]) -> tuple[float, float]:
    """Share of steps where the stated effect matches the sign of the gain, and chance agreement."""
    stated = [_SIGN[o] for o in observed]
    actual = [(g > 0) - (g < 0) for g in gains]
    n = len(stated)
    agreement = sum(s == a for s, a in zip(stated, actual, strict=True)) / n
    chance = sum((stated.count(v) / n) * (actual.count(v) / n) for v in (-1, 0, 1))
    return agreement, chance
```

- [x] **Step 4: Open the import boundary by decision 0025**

`tests/test_import_boundaries.py`: replace the allow-list with

```python
# Decision 0025: the scoring modules that grade against the verdict, and the judge that also
# reads synthesis. Everything else in scoring stays outside.
ALLOWED_TO_IMPORT_SYNTHESIS_OR_VERDICT = frozenset(
    {
        "ntsb_probable_cause.records.split",
        "ntsb_probable_cause.scoring.metrics",
        "ntsb_probable_cause.scoring.runner",
        "ntsb_probable_cause.scoring.judge",
        "ntsb_probable_cause.scoring.report",
    }
)
```

and add a second test that `ntsb_probable_cause.records.synthesis` is imported only by `records.split` and `scoring.judge`. In `pyproject.toml`, the contract "Only the splitter constructs synthesis and verdict" lists source modules explicitly; add `"ntsb_probable_cause.scoring.codes"`, `"ntsb_probable_cause.scoring.hypothesis"`, `"ntsb_probable_cause.scoring.prompt"`, `"ntsb_probable_cause.scoring.samples"`, `"ntsb_probable_cause.scoring.records"`, `"ntsb_probable_cause.scoring.ledger"`, `"ntsb_probable_cause.scoring.baseline"` to its `source_modules`. The contract "The model boundary cannot see synthesis or verdict" gains `"ntsb_probable_cause.scoring"` in `forbidden_modules`.

- [x] **Step 5: Run tests and `make check`** — Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/scoring/metrics.py tests/test_metrics.py tests/test_import_boundaries.py pyproject.toml
git commit -m "S1: per-case and per-step metrics with intervals; scoring may read the verdict (0025)"
```

---

### Task 8: The scripted trail through the recording fake (done-means 4)

**Files:**
- Test: `tests/test_scripted_trail.py`

**Interfaces:** consumes `RecordingFakeClient`, `parse_hypothesis`, `score_trail`.

- [x] **Step 1: Write the test**

```python
# tests/test_scripted_trail.py
"""Done means 4: per-step scoring on a scripted three-step trail replayed through the fake."""

import json

import pytest

from ntsb_probable_cause.model.client import ModelSettings, Payload, RecordingFakeClient
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import score_trail

T = load_tables()
VERDICT = Verdict(probable_cause=None, occurrence_codes=("552230",), finding_codes=("0206304044",), finding_codes_in_cause=("0206304044",))


def step(occ: list[tuple[str, str, float]], conf: float) -> str:
    return json.dumps({
        "evidence_narrative": "n", "probable_cause": "p", "lay_explanation": "l",
        "confidence": conf, "abstain": False, "evidence_used": [],
        "occurrence": [{"phase": p, "event": e, "probability": pr} for p, e, pr in occ],
        "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
    })


def test_three_step_trail_is_scored_step_by_step() -> None:
    client = RecordingFakeClient([
        step([("551", "230", 0.5)], 0.4),
        step([("552", "230", 0.5), ("551", "230", 0.3)], 0.6),
        step([("552", "230", 0.8)], 0.85),
    ])
    payload = Payload.from_evidence(Evidence(case_id="X", docket_url=None, phase_of_flight="Landing"))
    trail = [parse_hypothesis(client.complete(payload, ModelSettings()).content or "", T) for _ in range(3)]
    scored = score_trail(trail, VERDICT, T, seen_pairs={"551230", "552230"})
    assert [s.scores.occurrence_top1 for s in scored] == [False, True, True]
    assert [s.prob_on_true for s in scored] == [0.0, 0.5, 0.8]
    assert [round(s.information_gain, 6) for s in scored] == [0.0, 0.5, pytest.approx(0.3)]
    # step 2 -> 3: before {552230:.5, 551230:.3, other:.2}; after {552230:.8, other:.2}
    # TV = 0.5*(|.5-.8| + |.3-0| + |.2-.2|) = 0.3
    assert scored[2].movement == pytest.approx(0.3)
    assert len(client.payloads) == 3
```

- [x] **Step 2: Run** — `uv run pytest tests/test_scripted_trail.py -v` → PASS (everything it needs exists). If it fails, the bug is in Task 7; fix there.

- [x] **Step 3: Commit**

```bash
git add tests/test_scripted_trail.py
git commit -m "S1: scripted trail through the recording fake (done means 4)"
```

---

### Task 9: Records, samples, the mask, the ledger

**Files:**
- Create: `scoring/records.py`, `scoring/samples.py`, `scoring/ledger.py`, `scripts/draw_samples.py`
- Create: `tests/fixtures/eval/heldout_400_ids.csv`, `dev_400_ids.csv` (by the script, from `cases.parquet`)
- Modify: `scripts/copy_eval_ids.py` (copy the full sheets as `decidability_full.csv`, `leakage_full.csv`)
- Test: `tests/test_records_s1.py`, `tests/test_samples.py`, `tests/test_ledger.py`, `tests/test_contamination.py`

**Interfaces:**

```python
# records.py  (all frozen, extra="forbid")
class RunRecord(BaseModel):
    run_id: str; sample: str; arm: Literal["A", "ceiling"]; exclusions: tuple[str, ...]; includes: tuple[str, ...]
    prompt_version: str; model: str; price_variant: str; cap_usd: float; budget_usd: float
    commit_sha: str; dirty: bool; started: datetime; finished: datetime | None = None
    batch_ids: tuple[str, ...] = (); cases: int = 0; cost_usd: float = 0.0; reported_batch_cost_usd: float | None = None
class StepRecord(BaseModel):
    case_id: str; step: int; arm: str; condition: Literal["full", "masked"]; day: int | None
    tool: str; arguments: dict[str, object]; reason: str; expected_effect: str
    returned_roles: tuple[str, ...]; not_available: tuple[str, ...]; payload_fingerprint: str
    hypothesis: Hypothesis; observed_effect: Literal["confirmed", "weakened", "unchanged", ""]
    stop_reason: Literal["answered", "abstained", "budget", "cap", "nothing_available", ""]
    model: str; price_variant: str; prompt_tokens: int; completion_tokens: int; cost_usd: float; cumulative_cost_usd: float
    commit_sha: str; dirty: bool
class CaseResult(BaseModel):
    case_id: str; split: str; fatal: bool; investigation_class: str | None; report_flavour: str | None
    verdict_occurrence: tuple[str, ...]; verdict_findings: tuple[str, ...]; verdict_findings_in_cause: tuple[str, ...]
    steps: tuple[StepRecord, ...]; scores: CaseScores | None; cost_usd: float; failure: str | None
def write_jsonl(path: Path, rows: Iterable[BaseModel]) -> None
def read_jsonl(path: Path, model: type[T]) -> list[T]
def fingerprint(payload: Payload) -> str       # sha256 hex
# samples.py
SAMPLES = ("heldout-40", "heldout-400", "dev-400")
START_FACTS = frozenset({EvidenceRole.PHASE_OF_FLIGHT, EvidenceRole.INJURY_LEVEL, EvidenceRole.AIRCRAFT_MAKE, EvidenceRole.AIRCRAFT_MODEL, EvidenceRole.ENGINE_TYPE, EvidenceRole.REGISTRATION})
def arm_exclusions(arm: Literal["A", "ceiling"]) -> frozenset[EvidenceRole]
def masked_exclusions(day: int) -> frozenset[EvidenceRole]     # from the spike's fresh-case profile: pilot roles and weather_metar absent before day 14; prelim always absent
def sample_ids(name: str) -> tuple[str, ...]                    # from tests/fixtures/eval
def load_cases(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]   # raw records from cases.parquet, in the sample's order
def draw(processed: Path, split: Split, *, per_slice: int = 200, seed: int = 20260914) -> list[tuple[str, str]]   # (case_id, event_date)
# ledger.py
def commit_state(repo: Path = Path(".")) -> tuple[str, bool]    # (sha, dirty)
def append_row(ledger: Path, run: RunRecord, results_file: str) -> None
def refuse_if_heldout_and_dirty(sample: str, dirty: bool) -> None   # raises ConfigurationError
def seen_pairs(processed: Path) -> frozenset[str]                  # primary occurrence codes seen in the development split (the "pair unseen" column)
```

- [x] **Step 1: Write the failing tests**

```python
# tests/test_samples.py
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import samples


def test_arm_a_keeps_only_start_facts() -> None:
    kept = set(EvidenceRole) - samples.arm_exclusions("A")
    assert kept == samples.START_FACTS
    assert samples.arm_exclusions("ceiling") == frozenset()


def test_mask_hides_late_fields_early() -> None:
    day1 = samples.masked_exclusions(1)
    assert EvidenceRole.PILOT_TOTAL_HOURS in day1 and EvidenceRole.WEATHER_METAR in day1
    assert EvidenceRole.PRELIM_NARRATIVE in samples.masked_exclusions(400)
    assert EvidenceRole.PHASE_OF_FLIGHT not in day1


def test_sample_ids_are_loaded(eval_ids: dict[str, dict[str, str]]) -> None:
    assert len(samples.sample_ids("heldout-40")) == 40
```

```python
# tests/test_ledger.py
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import ledger


def test_heldout_refused_when_dirty() -> None:
    with pytest.raises(ConfigurationError, match="uncommitted"):
        ledger.refuse_if_heldout_and_dirty("heldout-400", dirty=True)
    ledger.refuse_if_heldout_and_dirty("dev-400", dirty=True)
    ledger.refuse_if_heldout_and_dirty("heldout-400", dirty=False)


def test_append_row_creates_header_once(tmp_path: Path, run_record) -> None:
    path = tmp_path / "heldout-ledger.md"
    ledger.append_row(path, run_record, "docs/results/x.txt")
    ledger.append_row(path, run_record, "docs/results/y.txt")
    lines = path.read_text().splitlines()
    assert lines[0].startswith("# Held-out ledger") and sum(l.startswith("| 20") for l in lines) == 2
```

Add to `tests/conftest.py` a `run_record` fixture building a `RunRecord` with fixed values. Extend `tests/test_contamination.py`:

```python
def test_s1_samples_are_split_pure_and_disjoint(eval_ids: dict[str, dict[str, str]]) -> None:
    dev = eval_ids.get("dev_400_ids", {})
    held = eval_ids.get("heldout_400_ids", {})
    assert all(split_of(date.fromisoformat(d)) is Split.DEV for d in dev.values())
    assert all(split_of(date.fromisoformat(d)) is Split.HELDOUT for d in held.values())
    assert not set(dev) & set(held)
    fixture_ids = {r["ntsbNumber"] for r in load_record_fixtures()}
    assert not fixture_ids & (set(dev) | set(held))
```

(Until the files exist the test passes vacuously on empty dicts; it bites once Step 5 commits them.)

- [x] **Step 2: Run to verify failure** — FAIL on imports.

- [x] **Step 3: Implement `records.py`, `samples.py`, `ledger.py`**

`records.py`: the three models exactly as in Interfaces, plus

```python
def fingerprint(payload: Payload) -> str:
    """SHA-256 of the rendered payload; stored instead of the text (spec §6.4)."""
    return hashlib.sha256(payload.text.encode()).hexdigest()


def write_jsonl(path: Path, rows: Iterable[BaseModel]) -> None:
    """Append rows as JSON lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def read_jsonl(path: Path, model: type[T]) -> list[T]:
    """Read every row of one record type."""
    return [model.model_validate_json(line) for line in path.read_text().splitlines() if line]
```

`samples.py`:

```python
"""The three fixed samples, arms as exclusion sets, and the day-N mask (spec §5, §6.1)."""

import csv
import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.splits import Split

SAMPLES = ("heldout-40", "heldout-400", "dev-400")
_FILES = {"heldout-40": "decidability_ids.csv", "heldout-400": "heldout_400_ids.csv", "dev-400": "dev_400_ids.csv"}
EVAL_DIR = Path("tests/fixtures/eval")
START_FACTS = frozenset(
    {
        EvidenceRole.PHASE_OF_FLIGHT,
        EvidenceRole.INJURY_LEVEL,
        EvidenceRole.AIRCRAFT_MAKE,
        EvidenceRole.AIRCRAFT_MODEL,
        EvidenceRole.ENGINE_TYPE,
        EvidenceRole.REGISTRATION,
    }
)
# ../ntsb-spike/scripts/fresh_case_profile.py: pilot hours on 0% of cases in the first two weeks,
# METAR in the record on 17%; the preliminary narrative is deleted at closure (decision 0023).
_LATE_BEFORE_DAY_14 = frozenset(
    {
        EvidenceRole.PILOT_CERTIFICATES,
        EvidenceRole.PILOT_TOTAL_HOURS,
        EvidenceRole.PILOT_HOURS_IN_TYPE,
        EvidenceRole.WEATHER_METAR,
        EvidenceRole.WEATHER_CONDITION,
    }
)


def arm_exclusions(arm: Literal["A", "ceiling"]) -> frozenset[EvidenceRole]:
    """Arm A keeps only the start facts; the ceiling excludes nothing (0022, 0023)."""
    return frozenset(set(EvidenceRole) - START_FACTS) if arm == "A" else frozenset()


def masked_exclusions(day: int) -> frozenset[EvidenceRole]:
    """What a live case would not yet have at day N; the preliminary narrative never (0023)."""
    late = _LATE_BEFORE_DAY_14 if day < 14 else frozenset()
    return frozenset(late | {EvidenceRole.PRELIM_NARRATIVE})


def sample_ids(name: str) -> tuple[str, ...]:
    """Case IDs of a named sample, in file order."""
    with (EVAL_DIR / _FILES[name]).open(newline="") as handle:
        return tuple(row["case_id"] for row in csv.DictReader(handle))


def load_cases(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]:
    """Raw records for the given IDs from cases.parquet, in the IDs' order (decision 0014)."""
    table = pq.read_table(processed / "cases.parquet", columns=["ntsb_number", "raw_json"])
    by_id = dict(zip(table["ntsb_number"].to_pylist(), table["raw_json"].to_pylist(), strict=True))
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"cases not in the processed file: {missing[:5]}")
    return [json.loads(by_id[i]) for i in ids]


def seen_pairs(processed: Path) -> frozenset[str]:
    """Every primary occurrence code in the development split; a top-1 outside it is "pair unseen"."""
    table = pq.read_table(processed / "cases.parquet", columns=["split", "raw_json"])
    return frozenset(
        codes[0]
        for s, r in zip(table["split"].to_pylist(), table["raw_json"].to_pylist(), strict=True)
        if s == Split.DEV.value and (codes := fields.occurrence_codes(json.loads(r)))
    )


def draw(processed: Path, split: Split, *, per_slice: int = 200, seed: int = 20260914) -> list[tuple[str, str]]:
    """200 fatal and 200 non-fatal, each stratified by class C/F/L in proportion (0026)."""
    table = pq.read_table(processed / "cases.parquet", columns=["ntsb_number", "event_date", "split", "investigation_class", "raw_json"])
    rows = [
        (str(n), str(d), str(c), json.loads(r)["highestInjuryLevel"] == "Fatal")
        for n, d, s, c, r in zip(*(table[col].to_pylist() for col in table.column_names), strict=True)
        if s == split.value and c in {"C", "F", "L"}
    ]
    rng = random.Random(seed)  # noqa: S311
    chosen: list[tuple[str, str]] = []
    for fatal in (True, False):
        pool = [r for r in rows if r[3] is fatal]
        by_class = {c: [r for r in pool if r[2] == c] for c in ("C", "F", "L")}
        quota = {c: round(per_slice * len(v) / len(pool)) for c, v in by_class.items()}
        for c, members in by_class.items():
            chosen.extend((n, d) for n, d, _, _ in rng.sample(members, min(quota[c], len(members))))
    return sorted(chosen)
```

`ledger.py`:

```python
"""The held-out ledger and the commit state every run records (decisions 0018, 0026)."""

import subprocess
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.records import RunRecord

_HEADER = "# Held-out ledger\n\nEvery run that touched a held-out sample (decision 0026).\n\n| date | sample | arm | exclusions | includes | model | commit | cost USD | results |\n|---|---|---|---|---|---|---|---|---|\n"


def commit_state(repo: Path = Path()) -> tuple[str, bool]:
    """Short SHA and whether the tree has uncommitted changes."""
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603,S607
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout  # noqa: S603,S607
    return sha, bool(status.strip())


def refuse_if_heldout_and_dirty(sample: str, dirty: bool) -> None:
    """A held-out run from a dirty tree is refused."""
    if sample.startswith("heldout") and dirty:
        raise ConfigurationError(f"{sample}: refusing to run with uncommitted changes; commit first")


def append_row(ledger: Path, run: RunRecord, results_file: str) -> None:
    """Append one row, writing the header on first use."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.write_text(_HEADER)
    with ledger.open("a") as handle:
        handle.write(
            f"| {run.started.date()} | {run.sample} | {run.arm} | {','.join(run.exclusions) or '-'} | "
            f"{','.join(run.includes) or '-'} | {run.model} | {run.commit_sha}{'*' if run.dirty else ''} | "
            f"{run.cost_usd:.2f} | {results_file} |\n"
        )
```

`scripts/draw_samples.py`: calls `draw` for `Split.HELDOUT` and `Split.DEV`, writes the two CSVs with header `case_id,event_date`, prints the fatal/class counts. `scripts/copy_eval_ids.py`: add copying of the two full sheets to `decidability_full.csv` and `leakage_full.csv` and update its README text (replace "Case IDs only — the full sheets are copied in S1." with "The full sheets are `*_full.csv`; their NTSB code and cause columns are withheld data and never enter a payload.").

- [x] **Step 4: Run tests and `make check`** — PASS.

- [x] **Step 5: Build the processed file if absent, draw the samples, copy the sheets**

```bash
make ingest && make build          # if data/processed/cases.parquet is absent
uv run python -m scripts.draw_samples
uv run python -m scripts.copy_eval_ids ../ntsb-spike
uv run pytest tests/test_contamination.py -v
```

Record the fatal × class counts of both samples in the Deviations section (they are numbers a spec reader will want).

- [x] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/scoring/records.py src/ntsb_probable_cause/scoring/samples.py src/ntsb_probable_cause/scoring/ledger.py scripts/draw_samples.py scripts/copy_eval_ids.py tests/fixtures/eval tests/test_samples.py tests/test_ledger.py tests/test_contamination.py tests/conftest.py
git commit -m "S1: run, case and step records; the three samples; the held-out ledger"
```

---

### Task 10: The baseline

**Files:**
- Create: `scoring/baseline.py`
- Test: `tests/test_baseline.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class BaselineModel:
    top_by_key: Mapping[str, tuple[str, ...]]            # "phase|weather" -> up to 3 most common primary codes
    findings_by_code: Mapping[str, tuple[str, ...]]      # primary code -> top-3 finding codes (10-digit)
    fallback: tuple[str, ...]                              # unconditional top-3
def key_of(raw: Mapping[str, object]) -> str                 # f"{phase_of_flight}|{weather_condition}" via the evidence extractors
def fit(raws: Iterable[Mapping[str, object]]) -> BaselineModel
def predict(model: BaselineModel, raw: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]   # (occurrence top3, finding top3)
def stratified_draw(rows: Sequence[tuple[str, str]], n: int, seed: int = 7) -> list[str]   # (case_id, primary code) -> ids, the spike's rule
```

- [x] **Step 1: Write the failing test on the fixtures, worked by hand**

```python
# tests/test_baseline.py
from ntsb_probable_cause.scoring import baseline


def test_fit_and_predict_on_fixtures_by_hand(record_fixtures: list[dict[str, object]]) -> None:
    model = baseline.fit(record_fixtures)
    # Work the expected value by hand from the nine fixtures: group by key_of, count primary codes.
    from collections import Counter, defaultdict
    from ntsb_probable_cause.fields import occurrence_codes
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for raw in record_fixtures:
        groups[baseline.key_of(raw)][occurrence_codes(raw)[0]] += 1
    for raw in record_fixtures:
        expected = tuple(c for c, _ in groups[baseline.key_of(raw)].most_common(3))
        occ, _ = baseline.predict(model, raw)
        assert occ == expected


def test_stratified_draw_is_deterministic_and_proportional() -> None:
    rows = [(f"c{i}", "A" if i < 80 else "B") for i in range(100)]
    ids = baseline.stratified_draw(rows, 10, seed=7)
    assert ids == baseline.stratified_draw(rows, 10, seed=7) and len(ids) == 10
    assert sum(1 for i in ids if int(i[1:]) < 80) == 8
```

- [x] **Step 2: Run to verify failure** — FAIL.

- [x] **Step 3: Implement**

```python
"""The spike's phase-and-weather modal baseline, ported by method (spec §6.3)."""

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceRole


@dataclass(frozen=True)
class BaselineModel:
    """Most common codes per phase|weather key, and per primary code for findings."""

    top_by_key: Mapping[str, tuple[str, ...]]
    findings_by_code: Mapping[str, tuple[str, ...]]
    fallback: tuple[str, ...]


def _extract(raw: Mapping[str, object], role: EvidenceRole) -> str:
    field = next(f for f in fields.EVIDENCE_FIELDS if f.role is role)
    value = field.extract(raw)
    return str(value) if value is not None else ""


def key_of(raw: Mapping[str, object]) -> str:
    """The spike's conditioning key: phase of flight and weather condition."""
    return f"{_extract(raw, EvidenceRole.PHASE_OF_FLIGHT)}|{_extract(raw, EvidenceRole.WEATHER_CONDITION)}"


def fit(raws: Iterable[Mapping[str, object]]) -> BaselineModel:
    """Count primary codes per key and finding codes per primary code."""
    by_key: dict[str, Counter[str]] = defaultdict(Counter)
    by_code: dict[str, Counter[str]] = defaultdict(Counter)
    overall: Counter[str] = Counter()
    for raw in raws:
        codes = fields.occurrence_codes(raw)
        if not codes:
            continue
        primary = codes[0]
        by_key[key_of(raw)][primary] += 1
        overall[primary] += 1
        by_code[primary].update(fields.finding_codes(raw))
    return BaselineModel(
        top_by_key={k: tuple(c for c, _ in v.most_common(3)) for k, v in by_key.items()},
        findings_by_code={k: tuple(c for c, _ in v.most_common(3)) for k, v in by_code.items()},
        fallback=tuple(c for c, _ in overall.most_common(3)),
    )


def predict(model: BaselineModel, raw: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Top-3 occurrence codes for the case's key, and top-3 findings for the top-1 code."""
    occ = model.top_by_key.get(key_of(raw), model.fallback)
    findings = model.findings_by_code.get(occ[0], ()) if occ else ()
    return occ, findings


def stratified_draw(rows: Sequence[tuple[str, str]], n: int, seed: int = 7) -> list[str]:
    """The spike's ``stratified_sample``: per stratum max(1, round(share*n)), then shuffle, head n."""
    rng = random.Random(seed)  # noqa: S311
    strata: dict[str, list[str]] = defaultdict(list)
    for case_id, code in rows:
        strata[code].append(case_id)
    picked: list[str] = []
    for code, members in sorted(strata.items()):
        k = max(1, round(len(members) / len(rows) * n))
        picked.extend(rng.sample(sorted(members), min(k, len(members))))
    rng.shuffle(picked)
    return picked[:n]
```

Note in the Deviations log: the spike used pandas' `sample(random_state=7)`, whose stream differs from `random.Random(7)`, so the reproduction matches by method, not by identical draw; the spec's done-means already allows "within one point or explained".

- [x] **Step 4: Run tests and `make check`** — PASS.

- [x] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/scoring/baseline.py tests/test_baseline.py
git commit -m "S1: the phase-and-weather modal baseline, by method"
```

---

### Task 11: The runner — sync and batch, caps and budget

**Files:**
- Create: `scoring/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class RunSpec:
    sample: str; arm: Literal["A", "ceiling"]; exclusions: frozenset[EvidenceRole] = frozenset()
    include_case_number: bool = False; model: str = "openai/gpt-5.6-luna"; price_variant: Literal["batch","standard"] = "batch"
    cap_usd: float = 0.05; budget_usd: float = 25.0; sync: bool = False; expected_cost_per_case_usd: float | None = None
class Runner:
    def __init__(self, client: ModelClient, *, batch: BatchClient | None, tables: CodeTables, seen_pairs: frozenset[str], runs_dir: Path, ledger_path: Path, month_spent_usd: float, commit: tuple[str, bool], now: Callable[[], datetime] = ...) -> None
    def run(self, spec: RunSpec, raws: Sequence[Mapping[str, object]]) -> RunRecord
    # writes runs_dir/<run_id>/{run.jsonl, cases.jsonl, steps.jsonl}; appends the ledger row for heldout-*
def project_cost(spec: RunSpec, cases: int) -> float          # cases × (expected or cap)
def refuse_over_budget(projected: float, month_spent: float, budget: float) -> None    # BudgetError
def case_payload(raw, spec, tables) -> tuple[Payload, str, Verdict, Evidence]   # (payload, system text, verdict, evidence); case number only if include_case_number and split is DEV
def over_cap(payload_text: str, system: str, spec: RunSpec) -> bool               # (len(text) / 4) input tokens × input price > cap_usd
```

The case-number probe path: `case_payload` raises `LeakageError` unless `split_of(event_date) is Split.DEV`. The number travels in the **system** text through `prompt.tables_block(tables, case_number=...)`, never in the `Payload`, because `Evidence` is `extra="forbid"` and `Payload.from_evidence` rejects unknown keys by design. The boundary test asserts the case-number line is absent from the system text on every non-development sample. The run record's `includes=("case_number",)` says what happened.

The cap: before any call, `over_cap` estimates the prompt at one token per four characters of payload plus system text, prices it at the model's input price, and if that exceeds `cap_usd` the case is recorded as failed with reason `cap` and no call is made (spec §11).

- [x] **Step 1: Write the failing tests**

```python
# tests/test_runner.py
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import BudgetError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import RecordingFakeClient
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, read_jsonl
from ntsb_probable_cause.scoring.runner import RunSpec, Runner, project_cost, refuse_over_budget

GOOD = json.dumps({
    "evidence_narrative": "n", "probable_cause": "p", "lay_explanation": "l", "confidence": 0.7,
    "abstain": False, "evidence_used": ["phase_of_flight"],
    "occurrence": [{"phase": "552", "event": "230", "probability": 0.7}],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
})
REFINE = json.dumps({"items": [{"index": 0, "item8": "02063040"}]})


def runner(tmp_path: Path, client: RecordingFakeClient, spent: float = 0.0) -> Runner:
    return Runner(client, batch=None, tables=load_tables(), seen_pairs=frozenset({"552230"}), runs_dir=tmp_path / "runs",
                  ledger_path=tmp_path / "ledger.md", month_spent_usd=spent, commit=("abc1234", False),
                  now=lambda: datetime(2026, 9, 15, tzinfo=UTC))


def test_over_cap_case_is_failed_without_a_call(tmp_path: Path, record_fixtures: list[dict[str, object]]) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(sample="dev-400", arm="ceiling", sync=True, cap_usd=0.0000001, expected_cost_per_case_usd=0.0)
    run = runner(tmp_path, client).run(spec, record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure == "cap" and client.payloads == []


def test_sync_run_writes_three_files_and_one_step_per_case(tmp_path: Path, record_fixtures: list[dict[str, object]]) -> None:
    client = RecordingFakeClient([GOOD, REFINE] * len(record_fixtures))
    spec = RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001)
    run = runner(tmp_path, client).run(spec, record_fixtures)
    folder = tmp_path / "runs" / run.run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    steps = read_jsonl(folder / "steps.jsonl", StepRecord)
    assert len(cases) == len(record_fixtures) and len(steps) == len(record_fixtures)
    assert all(c.scores is not None and c.failure is None for c in cases)
    assert steps[0].tool == "none" and steps[0].stop_reason == "answered"
    assert read_jsonl(folder / "run.jsonl", RunRecord)[0].prompt_version == "s1-v1"
    assert len(client.payloads) == 2 * len(record_fixtures)   # two turns per case


def test_schema_failure_is_retried_once_then_recorded(tmp_path: Path, record_fixtures: list[dict[str, object]]) -> None:
    client = RecordingFakeClient(["not json", "still not json"] + [GOOD, REFINE] * 10)
    run = runner(tmp_path, client).run(RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001), record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is not None and case.failure.startswith("schema") and case.scores is None


def test_arm_a_excludes_everything_but_start_facts(tmp_path: Path, record_fixtures: list[dict[str, object]]) -> None:
    client = RecordingFakeClient([GOOD, REFINE] * 2)
    runner(tmp_path, client).run(RunSpec(sample="dev-400", arm="A", sync=True, expected_cost_per_case_usd=0.001), record_fixtures[:1])
    sent = client.payloads[0].fields()
    assert "pilot_total_hours" not in sent and "weather_metar" not in sent


def test_case_number_probe_refused_off_dev(tmp_path: Path, record_fixtures: list[dict[str, object]]) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    with pytest.raises(LeakageError, match="case number"):
        runner(tmp_path, client).run(RunSpec(sample="heldout-40", arm="ceiling", sync=True, include_case_number=True, expected_cost_per_case_usd=0.001), record_fixtures[:1])


def test_budget_refusal_before_any_call(tmp_path: Path, record_fixtures: list[dict[str, object]]) -> None:
    client = RecordingFakeClient([GOOD])
    with pytest.raises(BudgetError):
        runner(tmp_path, client, spent=24.99).run(RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.01), record_fixtures)
    assert client.payloads == []


def test_project_cost_and_refusal() -> None:
    assert project_cost(RunSpec(sample="dev-400", arm="A", cap_usd=0.05), 400) == pytest.approx(20.0)
    assert project_cost(RunSpec(sample="dev-400", arm="A", expected_cost_per_case_usd=0.001), 400) == pytest.approx(0.4)
    refuse_over_budget(1.0, 20.0, 25.0)
    with pytest.raises(BudgetError):
        refuse_over_budget(6.0, 20.0, 25.0)


def test_heldout_run_appends_ledger_row(tmp_path: Path, record_fixtures: list[dict[str, object]]) -> None:
    client = RecordingFakeClient([GOOD, REFINE] * 2)
    r = runner(tmp_path, client)
    r.run(RunSpec(sample="heldout-40", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001), record_fixtures[:1])
    assert (tmp_path / "ledger.md").read_text().count("| heldout-40 |") == 1
```

The fixtures are development records; the runner takes the raw records it is given, so `heldout-40` in the test is only a label for the ledger path. The boundary test in Task 12 covers real held-out behaviour by split of event date.

- [x] **Step 2: Run to verify failure** — FAIL (`ModuleNotFoundError: No module named 'ntsb_probable_cause.scoring.runner'`).

- [x] **Step 3: Implement `runner.py`**

```python
"""One evaluation run: cases → payloads → answering pass → scored results (spec §6)."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from ntsb_probable_cause.errors import BudgetError, LeakageError, ModelError, SchemaError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.batch import BatchClient, BatchRequest
from ntsb_probable_cause.model.client import ModelClient, ModelReply, ModelSettings, Payload, Turn, cost_usd
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import HYPOTHESIS_SCHEMA, REFINEMENT_SCHEMA, Hypothesis, parse_hypothesis, parse_refinement
from ntsb_probable_cause.scoring.ledger import append_row, refuse_if_heldout_and_dirty
from ntsb_probable_cause.scoring.metrics import score_case
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, fingerprint, write_jsonl
from ntsb_probable_cause.scoring.samples import arm_exclusions
from ntsb_probable_cause.splits import Split, split_of
from ntsb_probable_cause.data.build import investigation_class


@dataclass(frozen=True)
class RunSpec:
    """Everything that varies between runs (spec §2)."""

    sample: str
    arm: Literal["A", "ceiling"]
    exclusions: frozenset[EvidenceRole] = frozenset()
    include_case_number: bool = False
    model: str = "openai/gpt-5.6-luna"
    price_variant: Literal["batch", "standard"] = "batch"
    cap_usd: float = 0.05
    budget_usd: float = 25.0
    sync: bool = False
    expected_cost_per_case_usd: float | None = None


def project_cost(spec: RunSpec, cases: int) -> float:
    """Cases times the measured cost per case, or the cap where there is no measurement (0030)."""
    return cases * (spec.expected_cost_per_case_usd if spec.expected_cost_per_case_usd is not None else spec.cap_usd)


def refuse_over_budget(projected: float, month_spent: float, budget: float) -> None:
    """Refuse a run that would take the month past its budget."""
    if month_spent + projected > budget:
        raise BudgetError(f"projected ${projected:.2f} plus ${month_spent:.2f} spent exceeds the ${budget:.2f} budget")


def _settings(spec: RunSpec, schema: dict[str, object], name: str) -> ModelSettings:
    return ModelSettings(model=spec.model, price_variant=spec.price_variant, json_schema=schema, schema_name=name)


def case_payload(raw: Mapping[str, object], spec: RunSpec, tables: CodeTables) -> tuple[Payload, str, Verdict, Evidence]:
    """The only route to a payload; the case-number line exists on development cases alone."""
    evidence, _, verdict = split_record(raw, exclude=spec.exclusions | arm_exclusions(spec.arm))
    payload = Payload.from_evidence(evidence)
    case_number: str | None = None
    if spec.include_case_number:
        event = date.fromisoformat(str(raw["eventDate"])[:10])
        if split_of(event) is not Split.DEV:
            raise LeakageError(f"{evidence.case_id}: the case number may be included on development cases only")
        case_number = evidence.case_id
    system = f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables, case_number=case_number)}"
    return payload, system, verdict, evidence


def over_cap(payload_text: str, system: str, spec: RunSpec) -> bool:
    """Would the prompt alone, at one token per four characters, cost more than the cap?"""
    price = sources.price_of(_settings(spec, HYPOTHESIS_SCHEMA, "hypothesis").model_id())
    return (len(payload_text) + len(system)) / 4 * price.input_usd_per_mtok / 1e6 > spec.cap_usd


class Runner:
    """Runs one RunSpec over raw records and writes the records (spec §6.4)."""

    def __init__(  # noqa: PLR0913
        self,
        client: ModelClient,
        *,
        batch: BatchClient | None,
        tables: CodeTables,
        runs_dir: Path,
        ledger_path: Path,
        processed: Path,
        month_spent_usd: float,
        commit: tuple[str, bool],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client, self._batch, self._tables, self._seen = client, batch, tables, seen_pairs
        self._runs_dir, self._ledger = runs_dir, ledger_path
        self._spent, (self._sha, self._dirty), self._now = month_spent_usd, commit, now

    def run(self, spec: RunSpec, raws: Sequence[Mapping[str, object]]) -> RunRecord:
        """Run every case, write three JSON-lines files, append the ledger for held-out samples."""
        refuse_if_heldout_and_dirty(spec.sample, self._dirty)
        refuse_over_budget(project_cost(spec, len(raws)), self._spent, spec.budget_usd)
        started = self._now()
        run_id = f"{started:%Y%m%dT%H%M%S}-{self._sha}-{spec.sample}-{spec.arm}"
        results = [self._answer_case(raw, spec) for raw in raws] if spec.sync else self._answer_batch(raws, spec)
        folder = self._runs_dir / run_id
        write_jsonl(folder / "cases.jsonl", results)
        write_jsonl(folder / "steps.jsonl", (s for r in results for s in r.steps))
        record = RunRecord(
            run_id=run_id, sample=spec.sample, arm=spec.arm,
            exclusions=tuple(sorted(e.value for e in spec.exclusions)), includes=("case_number",) if spec.include_case_number else (),
            prompt_version=prompt.PROMPT_VERSION, model=spec.model, price_variant=spec.price_variant,
            cap_usd=spec.cap_usd, budget_usd=spec.budget_usd, commit_sha=self._sha, dirty=self._dirty,
            started=started, finished=self._now(), cases=len(results), cost_usd=sum(r.cost_usd for r in results),
        )
        write_jsonl(folder / "run.jsonl", [record])
        if spec.sample.startswith("heldout"):
            append_row(self._ledger, record, str(folder / "cases.jsonl"))
        return record

    def _answer_case(self, raw: Mapping[str, object], spec: RunSpec) -> CaseResult:
        payload, system, verdict, evidence = case_payload(raw, spec, self._tables)
        if over_cap(payload.text, system, spec):
            return self._failed(evidence, raw, verdict, "cap", 0.0)
        cost = 0.0
        tokens = [0, 0]
        try:
            hypothesis, replies = self._two_turns(payload, system, spec)
            for reply in replies:
                dollars, _ = cost_usd(reply, _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis"))
                cost += dollars
                tokens[0] += reply.usage.prompt_tokens
                tokens[1] += reply.usage.completion_tokens
            failure = None
            scores = score_case(hypothesis, verdict, self._tables, seen_pairs=self._seen)
        except SchemaError as error:
            return self._failed(evidence, raw, verdict, f"schema: {error}", cost)
        except ModelError as error:
            return self._failed(evidence, raw, verdict, f"model: {error}", cost)
        step = StepRecord(
            case_id=evidence.case_id, step=0, arm=spec.arm, condition="full", day=None, tool="none", arguments={},
            reason="", expected_effect="", returned_roles=tuple(sorted(payload.fields())), not_available=(),
            payload_fingerprint=fingerprint(payload), hypothesis=hypothesis, observed_effect="",
            stop_reason="abstained" if hypothesis.abstain else "answered", model=spec.model, price_variant=spec.price_variant,
            prompt_tokens=tokens[0], completion_tokens=tokens[1], cost_usd=cost, cumulative_cost_usd=cost,
            commit_sha=self._sha, dirty=self._dirty,
        )
        return self._result(evidence, raw, verdict, (step,), scores, cost, failure)

    def _two_turns(self, payload: Payload, system: str, spec: RunSpec) -> tuple[Hypothesis, list[ModelReply]]:
        """Stage 1 then stage 2, each with one retry on a schema error; ``system`` holds the tables."""
        replies: list[ModelReply] = []
        first = self._client.complete(payload, _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis"), system=system)
        replies.append(first)
        try:
            hypothesis = parse_hypothesis(first.content or "", self._tables)
        except SchemaError as error:
            retry = self._client.complete(payload, _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis"), system=f"{system}\n\nYour previous reply was rejected: {error}")
            replies.append(retry)
            hypothesis = parse_hypothesis(retry.content or "", self._tables)
        if hypothesis.abstain or not hypothesis.findings:
            return hypothesis, replies
        history = (Turn(role="assistant", content=first.content),)
        second = self._client.complete(payload, _settings(spec, REFINEMENT_SCHEMA, "refinement"), system=prompt.SYSTEM_REFINE + "\n\n" + prompt.refine_message(hypothesis, self._tables), history=history)
        replies.append(second)
        try:
            return parse_refinement(second.content or "", self._tables, hypothesis), replies
        except SchemaError as error:
            retry = self._client.complete(payload, _settings(spec, REFINEMENT_SCHEMA, "refinement"), system=prompt.SYSTEM_REFINE + f"\n\nYour previous reply was rejected: {error}\n\n" + prompt.refine_message(hypothesis, self._tables), history=history)
            replies.append(retry)
            return parse_refinement(retry.content or "", self._tables, hypothesis), replies
```

Note the boundary: the tables and the case-number line travel in the **system** text, not in the `Payload`, so `Payload` keeps S0's invariant and `RecordingFakeClient.payloads` stays the provenance check.

Add `from ntsb_probable_cause import sources` to the imports. Add `_result` and `_failed` helpers building `CaseResult` with `split=split_of(event).value`, `fatal=raw["highestInjuryLevel"]=="Fatal"`, `investigation_class(evidence.case_id)`, `report_flavour=raw.get("factualFinalReportFlavor")`, the verdict tuples, `scores`, `cost_usd`, `failure`. Add `_answer_batch`: build one `BatchRequest` per case for stage 1 (custom_id = case id), `submit`, `wait` (log status to stderr), parse each; for cases needing stage 2 build a second batch with `history`; parse; assemble the same `CaseResult`s; put the batch ids in `RunRecord.batch_ids` and the summed `reported_cost_usd` in `reported_batch_cost_usd`. Cases whose batch item carries an error get `failure="model: ..."`. A batch that ends `expired`/`failed` raises `ModelError` naming the batch id (resume is a follow-up: `ntsb-eval resume <run id>` is out of S1's plan unless it is needed in practice — log a deviation if added).

- [x] **Step 4: Run tests and `make check`** — PASS. The batch path is tested here, not deferred
  to Task 13 (controller resolution 2): `tests/test_runner.py` adds a scripted `FakeBatchClient`
  covering two batches with every custom_id, abstain/no-findings skipping stage 2, batch-priced
  per-case cost, `batch_ids`/`reported_batch_cost_usd`, schema and model-error retries at both
  stages, a `failed`/`expired`/`cancelled` batch raising `ModelError` naming the batch id, and
  the same three files as sync. 332 tests pass, 97.16% coverage (gate 90%); `runner.py` itself is
  99% covered. `make check` (ruff format, ruff check, lint-imports, deptry, vulture, mypy
  --strict, pytest) all pass.

- [x] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/scoring/runner.py tests/test_runner.py
git commit -m "S1: the runner — two-turn answering pass, cap, budget, ledger"
```

---

### Task 12: The judge, and the boundary extended

**Files:**
- Create: `scoring/judge.py`
- Modify: `tests/boundary.py`, `tests/test_boundary.py`
- Test: `tests/test_judge.py`

**Interfaces:**

```python
class JudgeLabels(BaseModel):   # frozen
    narrative: Literal["consistent", "contradicts", "adds_unsupported_facts"]
    cause: Literal["same_cause", "related", "different"]
    lay: Literal["explains_chosen_codes", "does_not"]
JUDGE_SCHEMA: dict[str, object]
JUDGE_MODEL = "anthropic/claude-haiku-4.5"
SYSTEM_JUDGE: str
def judge_text(hypothesis: Hypothesis, synthesis: Synthesis, verdict: Verdict, tables: CodeTables) -> str
    # THE ONLY function that renders withheld text for a model; never a Payload
def judge_case(client: ModelClient, hypothesis, synthesis, verdict, tables, *, price_variant="batch") -> tuple[JudgeLabels, ModelReply]
def agreement_table(labels: Sequence[JudgeLabels], scores: Sequence[CaseScores]) -> dict[str, dict[str, int]]   # cause label × top1
def pick_disagreements(case_ids, labels, scores, *, n=30, seed=20260914) -> list[str]
```

`judge_case` sends the text as the **system** prompt with an empty `Payload`? No: `Payload.from_evidence` needs an `Evidence`; the judge builds `Payload.from_evidence(Evidence(case_id=..., docket_url=None))`, an empty payload, and carries everything in `system`. The boundary test asserts that on every judge call the `Payload` is empty and the system text contains the factual narrative, and that no answering call's system text ever does.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_judge.py
import json

from ntsb_probable_cause.model.client import RecordingFakeClient
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring import judge

H = parse_hypothesis(json.dumps({
    "evidence_narrative": "The airplane ran off the runway.", "probable_cause": "Loss of directional control.",
    "lay_explanation": "It swerved.", "confidence": 0.5, "abstain": False, "evidence_used": [],
    "occurrence": [{"phase": "552", "event": "230", "probability": 0.5}],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.5}],
}), load_tables())
S = Synthesis(factual_narrative="The pilot reported a gust during the landing roll.", analysis_narrative=None)
V = Verdict(probable_cause="The pilot's failure to maintain directional control.", occurrence_codes=("552230",), finding_codes=("0206304044",), finding_codes_in_cause=("0206304044",))


def test_judge_text_holds_the_withheld_narrative_and_cause() -> None:
    text = judge.judge_text(H, S, V, load_tables())
    assert "gust during the landing roll" in text and "failure to maintain directional control" in text


def test_judge_case_parses_labels_and_sends_empty_payload() -> None:
    client = RecordingFakeClient([json.dumps({"narrative": "consistent", "cause": "same_cause", "lay": "explains_chosen_codes"})])
    labels, _ = judge.judge_case(client, H, S, V, load_tables())
    assert labels.cause == "same_cause"
    assert client.payloads[0].fields() == {}
```

Extend `tests/test_boundary.py` with a test that runs `Runner` over the fixtures with the fake and asserts, for every recorded answering call, that neither the factual narrative nor the probable cause of that case appears in the system text the fake saw. To see system text, add `self.systems: list[str]` to `RecordingFakeClient` (Task 3's class; extend it here and log nothing — it is test support).

- [x] **Step 2: Run to verify failure** — FAIL.

- [x] **Step 3: Implement `judge.py`**

```python
"""The judge: labels for the prose outputs, validated before use, never a bar (decision 0028).

This is the only module that renders withheld text for a model. It builds an empty Payload and
carries everything in the system prompt, so the Payload invariant of S0 is untouched and the
boundary test can name this path.
"""

import json
import random
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.model.client import ModelClient, ModelReply, ModelSettings, Payload
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores

JUDGE_MODEL = "anthropic/claude-haiku-4.5"
SYSTEM_JUDGE = """You are grading an analyst's written outputs against the official record. Return labels only.
narrative: is the analyst's evidence narrative consistent with the official factual narrative, does it
contradict it, or does it add facts the official narrative does not support?
cause: does the analyst's probable cause name the same cause as the official one, a related one, or a different one?
lay: does the lay explanation explain, in plain language, the codes the analyst chose?
Reply only with JSON matching the schema."""


class JudgeLabels(BaseModel):
    """The three labels."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    narrative: Literal["consistent", "contradicts", "adds_unsupported_facts"]
    cause: Literal["same_cause", "related", "different"]
    lay: Literal["explains_chosen_codes", "does_not"]


JUDGE_SCHEMA: dict[str, object] = JudgeLabels.model_json_schema()
JUDGE_SCHEMA["additionalProperties"] = False


def judge_text(hypothesis: Hypothesis, synthesis: Synthesis, verdict: Verdict, tables: CodeTables) -> str:
    """The comparison text: withheld narrative and cause beside the analyst's outputs."""
    chosen = ", ".join(f"{c} {tables.categories.get(c[:6], '')}" for c in hypothesis.finding_codes(tables)) or "none"
    return (
        f"## Official factual narrative\n{synthesis.factual_narrative or '(none)'}\n\n"
        f"## Official probable cause\n{verdict.probable_cause or '(none)'}\n\n"
        f"## Analyst's evidence narrative\n{hypothesis.evidence_narrative}\n\n"
        f"## Analyst's probable cause\n{hypothesis.probable_cause}\n\n"
        f"## Analyst's chosen codes\n{chosen}\n\n"
        f"## Analyst's lay explanation\n{hypothesis.lay_explanation}\n"
    )


def judge_case(
    client: ModelClient, hypothesis: Hypothesis, synthesis: Synthesis, verdict: Verdict, tables: CodeTables,
    *, price_variant: Literal["batch", "standard"] = "batch",
) -> tuple[JudgeLabels, ModelReply]:
    """One judge call. The payload is empty by construction."""
    empty = Payload.from_evidence(Evidence(case_id="judge", docket_url=None))
    settings = ModelSettings(model=JUDGE_MODEL, price_variant=price_variant, json_schema=JUDGE_SCHEMA, schema_name="judge", max_output_tokens=200)
    reply = client.complete(empty, settings, system=f"{SYSTEM_JUDGE}\n\n{judge_text(hypothesis, synthesis, verdict, tables)}")
    try:
        return JudgeLabels.model_validate(json.loads(reply.content or "")), reply
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"judge reply is not JudgeLabels: {error}") from error


def agreement_table(labels: Sequence[JudgeLabels], scores: Sequence[CaseScores]) -> dict[str, dict[str, int]]:
    """Confusion table: judge cause label × occurrence top-1."""
    table: dict[str, dict[str, int]] = {}
    for label, score in zip(labels, scores, strict=True):
        row = table.setdefault(label.cause, {"top1_right": 0, "top1_wrong": 0})
        row["top1_right" if score.occurrence_top1 else "top1_wrong"] += 1
    return table


def pick_disagreements(case_ids: Sequence[str], labels: Sequence[JudgeLabels], scores: Sequence[CaseScores], *, n: int = 30, seed: int = 20260914) -> list[str]:
    """Cases where the judge and the code layer disagree, sampled for Andy's hand-check."""
    candidates = [
        cid for cid, label, score in zip(case_ids, labels, scores, strict=True)
        if (label.cause == "same_cause") != score.occurrence_top1
    ]
    rng = random.Random(seed)  # noqa: S311
    return sorted(rng.sample(candidates, min(n, len(candidates))))
```

- [x] **Step 4: Run tests and `make check`** — PASS, including the extended boundary test.

- [x] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/scoring/judge.py src/ntsb_probable_cause/model/client.py tests/test_judge.py tests/boundary.py tests/test_boundary.py
git commit -m "S1: the judge, the only path that carries withheld text; boundary extended"
```

---

### Task 13: Report, threshold, and the `ntsb-eval` command

**Files:**
- Create: `scoring/report.py`, `apps/eval/__init__.py`, `apps/eval/__main__.py`
- Modify: `pyproject.toml` (`ntsb-eval = "apps.eval.__main__:main"`), `Makefile` (`bars`, `probe`), `README.md`, `CLAUDE.md` (commands)
- Test: `tests/test_report.py`, `tests/test_eval_app.py`

**Interfaces:**

```python
# report.py
@dataclass(frozen=True) class Cell: value: float; low: float; high: float; n: int
def proportion(flags: Sequence[bool]) -> Cell
def mean_cell(values: Sequence[float]) -> Cell
def slices(results: Sequence[CaseResult]) -> dict[str, list[CaseResult]]     # "all", "fatal", "non-fatal", "class C/F/L", "flavour ..."
def weighted_headline(results, *, fatal_share: float = 727 / 4241) -> Cell
def summarise(results: Sequence[CaseResult]) -> str            # every §4.1 column per slice, with n and interval; the baseline floor if given
def compare(a: Sequence[CaseResult], b: Sequence[CaseResult]) -> str   # paired differences on shared case ids
def threshold_curve(results) -> list[tuple[float, float]]      # (t, mean score) for t in 0.05..0.95
def choose_threshold(results) -> float
def baseline_report(processed: Path, sample_ids: Sequence[str] | None, tables) -> str   # reproduction + honest baseline, at 10/8/6 digits
# apps/eval/__main__.py: subcommands baseline | run | report | judge | threshold; see spec §6.5.
# run also takes --sync, --limit N (first N cases of the sample), --out; report takes --against RUN_ID
# or --latest ARM SAMPLE / --against-latest ARM SAMPLE; judge takes --validated.
```

`compare`'s paired difference uses occurrence top-1 by default and prints finding recall too. `summarise` prints Markdown tables; the app writes them to stdout and, with `--out docs/results/<name>.txt`, to a file.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_report.py
from ntsb_probable_cause.scoring import report


def test_proportion_cell_has_wilson_interval() -> None:
    cell = report.proportion([True] * 23 + [False] * 17)
    assert cell.n == 40 and round(cell.low, 3) == 0.421


def test_choose_threshold_by_hand() -> None:
    # confidences and correctness: high-confidence right, low-confidence wrong
    results = make_results(conf=[0.9, 0.9, 0.2, 0.2], right=[True, True, False, False])   # helper in the test file builds CaseResult with scores
    curve = dict(report.threshold_curve(results))
    assert curve[0.05] == 0.0            # answer all: (2 - 2)/4
    assert curve[0.5] == 0.5             # abstain the two low ones: (2 - 0)/4
    assert report.choose_threshold(results) == 0.25   # the smallest t that reaches the maximum
```

Write `make_results` in the test to construct minimal `CaseResult`s (use a helper that builds a `Hypothesis` from `GOOD` and a `CaseScores` with the given `occurrence_top1` and `confidence`). Pin `choose_threshold` to "the smallest t with the maximal mean" and assert `== 0.25`.

```python
# tests/test_eval_app.py
from apps.eval.__main__ import main


def test_help_lists_subcommands(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for word in ("baseline", "run", "report", "judge", "threshold"):
        assert word in out
```

Plus one end-to-end test of `run --sync` on the fixtures with the fake client injected (add a `client_factory` parameter to `main` defaulting to the real one), asserting the run folder exists and `report <run id>` prints an "occurrence top-1" row.

- [x] **Step 2: Run to verify failure** — FAIL.

- [x] **Step 3: Implement `report.py`** with the functions above. `summarise`:

```python
def fmt(cell: Cell) -> str:
    """``57.5% [42.1, 71.5]``."""
    return f"{cell.value:.1%} [{cell.low:.1%}, {cell.high:.1%}]"


def _column(scored: Sequence[CaseResult], pick: Callable[[CaseScores], float | None]) -> Cell:
    values = [v for r in scored if r.scores is not None and (v := pick(r.scores)) is not None]
    return mean_cell(values)


def summarise(results: Sequence[CaseResult], *, floor: Mapping[str, float] | None = None) -> str:
    """Markdown tables: per slice, every §4.1 column with n and its 95% interval."""
    head = "| slice | n | top-1 | top-3 | event | pair unseen | abstain | answered top-1 | finding P@10 | R@10 | P@8 | R@8 | P@6 | R@6 | R@10 all | failed | cost/case USD |"
    lines = [head, "|" + "---|" * 17]
    for name, rows in slices(results).items():
        scored = [r for r in rows if r.scores is not None]
        if not scored:
            continue
        s = [r.scores for r in scored if r.scores is not None]
        answered = [x for x in s if not x.abstained]
        cells = [
            fmt(proportion([x.occurrence_top1 for x in s])),
            fmt(proportion([x.occurrence_top3 for x in s])),
            fmt(proportion([x.event_match for x in s])),
            fmt(proportion([x.pair_unseen for x in s])),
            fmt(proportion([x.abstained for x in s])),
            fmt(proportion([x.occurrence_top1 for x in answered])) if answered else "-",
            fmt(_column(scored, lambda x: x.finding_precision_10)),
            fmt(_column(scored, lambda x: x.finding_recall_10)),
            fmt(_column(scored, lambda x: x.finding_precision_8)),
            fmt(_column(scored, lambda x: x.finding_recall_8)),
            fmt(_column(scored, lambda x: x.finding_precision_6)),
            fmt(_column(scored, lambda x: x.finding_recall_6)),
            fmt(_column(scored, lambda x: x.finding_recall_all_10)),
            f"{sum(1 for r in rows if r.failure) } of {len(rows)}",
            f"{sum(r.cost_usd for r in rows) / len(rows):.4f}",
        ]
        lines.append(f"| {name} | {len(scored)} | " + " | ".join(cells) + " |")
    if floor:
        lines.append("\nBaseline floor: " + ", ".join(f"{k} {v:.1%}" for k, v in floor.items()))
    return "\n".join(lines)
```

`slices` yields `"all"`, `"fatal"`, `"non-fatal"`, `"class C"`, `"class F"`, `"class L"`, and one `"flavour ..."` per report flavour present, in that order; `weighted_headline` combines the fatal and non-fatal top-1 cells as `0.1714 × fatal + 0.8286 × non-fatal` with the interval from the same weighting of the bootstrap draws (write it as a bootstrap over the two slices' per-case flags, weighted). `compare` prints, for the shared case ids, the paired difference in top-1, top-3 and finding recall at 10 digits, each as `mean [low, high] on n cases`. `threshold_curve` implements the rule in spec §9 exactly: score +1 right, −1 wrong, 0 abstained-or-below-t, mean over all cases, for t in `[i/20 for i in range(1, 20)]`.

- [x] **Step 4: Implement `apps/eval/__main__.py`**

Thin argparse wiring only. `run` builds `Settings()`, `OpenRouterClient(settings.require_openrouter_key(), base_url=settings.openrouter_base_url)`, `BatchClient(http)`, computes `month_spent` by summing `cost_usd` over `RunRecord`s under `runs_dir` whose `started` is in the current month, reads the sample's raw records with `samples.load_cases(settings.data_dir / "processed", samples.sample_ids(args.sample))`, passes `seen_pairs=samples.seen_pairs(settings.data_dir / "processed")`, and calls `Runner.run`. `report` prints `summarise` (and `compare` with `--against`). `judge` runs `judge_case` over a run's cases (dev-400 only unless `--validated` is passed, which the plan's Task 15 sets after Andy's check), writes `judge.jsonl` beside the run and prints `agreement_table` and `pick_disagreements`. `threshold` prints the curve and the chosen value. `baseline` prints `baseline_report`. `--out` writes the printed text to a file.

Makefile:

```make
probe:
	uv run python -m scripts.openrouter_probe

bars:
	uv run ntsb-eval baseline --out docs/results/s1-baseline.txt
	uv run ntsb-eval run --arm ceiling --sample heldout-40
	uv run ntsb-eval run --arm ceiling --sample heldout-400
	uv run ntsb-eval run --arm A --sample heldout-400
	uv run ntsb-eval report --latest ceiling heldout-400 --against-latest A heldout-400 --out docs/results/s1-bars.txt
```

(`--latest ARM SAMPLE` resolves the newest run folder for that arm and sample; implement it in the app.)

- [x] **Step 5: Run tests and `make check`** — PASS.

- [x] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/scoring/report.py apps/eval pyproject.toml Makefile README.md CLAUDE.md tests/test_report.py tests/test_eval_app.py
git commit -m "S1: report with intervals and slices, threshold rule, ntsb-eval command, make bars"
```

---

### Task 14: Development-split runs (Andy runs; about $10)

These steps spend money and produce numbers. Each writes its summary under `docs/results/` and the numbers go into the Deviations log and, at close-out, the As-built record. Nothing here touches a held-out sample.

- [ ] **Step 1: Cost check.** `uv run ntsb-eval run --arm ceiling --sample dev-400 --sync --limit 10 --cap-usd 0.05` (add `--limit N` to the app: first N cases of the sample). Read `report`'s cost per case. Set `NTSB_EXPECTED_COST_PER_CASE_USD` in `.env` (add the setting; default None) so later projections use it. Record the number.
- [ ] **Step 2: Ceiling on `dev-400`, batch.** `uv run ntsb-eval run --arm ceiling --sample dev-400`. Read the failure rate (schema failures) and the abstain rate. If schema failures exceed 5%, fix the prompt or schema, bump `PROMPT_VERSION` to `s1-v2`, re-run. Freeze the prompt: record the version in the Deviations log and do not change it after this step.
- [ ] **Step 3: Arm A on `dev-400`.** `uv run ntsb-eval run --arm A --sample dev-400`, then `report --against`.
- [ ] **Step 4: Threshold.** `uv run ntsb-eval threshold <ceiling run id> --out docs/results/s1-threshold.txt`.
- [ ] **Step 5: Ablations.** `--exclude registration`, `--exclude phase_of_flight`, `--include case_number`, each on `dev-400`, each reported `--against` the ceiling run, written to `docs/results/s1-ablations-dev.txt`.
- [ ] **Step 6: Sonnet comparison.** `uv run ntsb-eval run --arm ceiling --sample dev-400 --model anthropic/claude-sonnet-5` (about $5), `report --against`, written to `docs/results/s1-model-comparison-dev.txt`. If Luna's top-1 is more than 10 points below Sonnet's, stop and ask Andy before any held-out run (0031).
- [ ] **Step 7: Judge validation.** `uv run ntsb-eval judge <ceiling run id> --out docs/results/s1-judge-validation.txt`. Give Andy the 30 disagreement case ids with the model's outputs and the official cause (from `cases.jsonl`, outside git) as a sheet; he marks each `judge right` / `codes right` / `both defensible`. Commit the sheet with ids and verdict text removed as `docs/results/s1-judge-handcheck.csv`. Apply the rule in spec §8 and record the outcome: validated or not.
- [ ] **Step 8: Commit the results files** (numbers only; check none contains model text):

```bash
git add docs/results/s1-*.txt docs/results/s1-judge-handcheck.csv .env.example
git commit -m "S1: development-split results — ceiling, arm A, threshold, ablations, model comparison, judge validation"
```

---

### Task 15: `make bars` — the held-out runs (Andy runs; about $2)

- [ ] **Step 1: Clean tree.** `git status --porcelain` must be empty; the runner refuses otherwise.
- [ ] **Step 2: `make bars`.** Produces the baseline file, the two ceiling runs, arm A, the ledger rows, and `docs/results/s1-bars.txt`.
- [ ] **Step 3: Registration ablation on `heldout-400`.** `uv run ntsb-eval run --arm ceiling --sample heldout-400 --exclude registration`, then `report --against <heldout-400 ceiling run>` to `docs/results/s1-registration-heldout.txt`. Apply the rule in spec §9 / decision 0027. If the difference favours having the registration: remove `EvidenceRole.REGISTRATION` from `samples.START_FACTS` and add it to every run's default exclusions, write the next numbered decision record amending 0023 (the number is whatever follows the last record at the time), and re-run `make bars` once (the ledger shows both).
- [ ] **Step 4: Judge on `heldout-400`** only if validated in Task 14 step 7: `uv run ntsb-eval judge <run id> --validated --out docs/results/s1-judge-heldout.txt`. Otherwise write one line in `s1-bars.txt`: "prose unchecked by a validated judge".
- [ ] **Step 5: Baseline reproduction check.** Open `docs/results/s1-baseline.txt`; confirm the reproduction row is within one point of 16.2% / 32.2%, or write the explanation into the file.
- [ ] **Step 6: Commit** results and the ledger:

```bash
git add docs/results/s1-bars.txt docs/results/s1-baseline.txt docs/results/s1-registration-heldout.txt docs/results/heldout-ledger.md docs/results/s1-judge-heldout.txt
git commit -m "S1: the bars — baseline, ceiling, arm A on the held-out samples; registration decided"
```

---

### Task 16: Close-out

- [ ] **Step 1: Retire the `CLAUDE.md` eval-bars table.** Replace the "Eval bars to beat" section with two sentences pointing at `docs/results/s1-bars.txt` and decision 0025.
- [ ] **Step 2: Verify every Done-means condition in spec §13 has evidence** (test id, results file, or ledger). List them in the pull-request description.
- [ ] **Step 3: Open the pull request** titled `S1: scoring and the evaluation harness`, with the template's checklist.
- [ ] **Step 4: Run `/close-stage`** (the project skill): As-built section with five parts, status `Implemented`, roadmap S1 entry marked done, this plan deleted, `version = "0.2.0"`, `uv run python -m scripts.check_docs` clean.
- [ ] **Step 5: CI green; Andy squash-merges and tags `v0.2.0`.**

---

## Deviations

*Log every departure from the specification here, dated, with the reason. Moved into the As-built record at close-out (decision 0017).*

- 2026-09-16, Task 12 (step 1): the confirmed price entry `HAIKU_45_BATCH` for
  `anthropic/claude-haiku-4.5:batch` ($0.50/$2.50 per MTok, OpenRouter models API,
  checked 2026-09-15) already existed in `sources.py` from an earlier task's addition, so no
  change to `sources.py` was needed for this task — verified rather than added.
- 2026-09-16, Task 12 (step 1): `test_synthesis_is_imported_only_by_split_and_judge` in
  `tests/test_import_boundaries.py` and the `scoring.judge`/`scoring.report` allow-list
  entries were already present (added ahead of time by an earlier task), so no changes to
  `tests/test_import_boundaries.py` or `pyproject.toml` were needed for this task.
- 2026-09-16, Task 12 (step 1): the brief's boundary-test extension is phrased as "assert, for
  every recorded answering call, that neither the factual narrative nor the probable cause of
  that case appears in the system text". Implemented instead as a stronger cross-product
  check: every system string the fake `Runner` run produced is checked against every fixture's
  factual narrative and probable cause, not only the matching case's own values. This is
  strictly stronger (it also catches a leak of one case's withheld text into a different
  case's system prompt, e.g. from a shared/cached fragment) and avoids a fragile pairing
  between `client.systems` entries and fixtures, since the number of answering calls per case
  varies (one call when a case abstains or has no findings, two when stage 2 runs, more on a
  schema retry) so a fixed-stride zip (`client.systems[::2]`) would silently mispair as soon
  as any fixture takes a different number of calls than another.
- 2026-09-16, Task 12 (step 3), **superseded by the fix-round-1 entry below**: the first cut
  of `JUDGE_SCHEMA` was built as the brief's literal code shows
  (`JudgeLabels.model_json_schema()` plus a manual top-level `additionalProperties = False`)
  rather than by calling `scoring/hypothesis.py`'s strict-schema helper, on the reasoning that
  `JudgeLabels` has no nested `BaseModel` so there was no nested object for the recursive
  helper to reach that the manual line did not already cover. Review round 1 correctly
  pointed out this only covers recursion, not `title`/`default`-stripping: the manual line
  left `"title": "JudgeLabels"` and a `title` on every property in `JUDGE_SCHEMA`, which
  `openrouter.py` forwards to the provider verbatim, unlike `HYPOTHESIS_SCHEMA`/
  `REFINEMENT_SCHEMA`, whose stripped shape is the only one confirmed live. Fixed below.
- 2026-09-16, Task 12 fix round 1 (Important 1, schema title-stripping): renamed
  `scoring/hypothesis.py`'s private `_strict_schema` to a public `strict_schema` (its
  recursive `_strict` helper stays private) and imported it into `scoring/judge.py`, so
  `JUDGE_SCHEMA = strict_schema(JudgeLabels)` gets exactly the treatment
  (`additionalProperties: false` on every object node, every property required, `title` and
  `default` stripped throughout) confirmed live against OpenRouter for
  `HYPOTHESIS_SCHEMA`/`REFINEMENT_SCHEMA`, instead of a hand-rolled approximation.
  `test_judge_schema_is_openai_strict_compatible` now walks `JUDGE_SCHEMA` recursively
  (mirroring `test_hypothesis.py`'s `_walk_objects`/`no_default` helpers) and asserts no
  `title` or `default` key appears anywhere, not just the two top-level properties checked
  before.
- 2026-09-16, Task 12 fix round 1 (Important 2, no retry on a truncated judge reply):
  `judge_case`'s `max_output_tokens` was a bare `200`, unspecified by the brief interface or
  spec §8, with no retry on failure. The project's own probe measured the analogous failure
  on the answering model: reasoning tokens consumed a 300-token cap and produced empty
  content with `finish_reason: "length"` on 3 of 10 calls; there is no fixture or probe for
  `anthropic/claude-haiku-4.5`, so the same failure mode is untested for the judge and would
  have failed every case of Task 14's 400-case judged run with no way to recover. Fixed both
  halves: (a) `max_output_tokens` is now a keyword parameter defaulting to `2000`
  (`ModelSettings`'s own default) rather than a magic number — the judge's reply is a few
  tokens of JSON, so a generous cap costs nothing while a tight one risks the whole run; (b)
  `judge_case` now retries once on a `SchemaError` (which an empty/`None` content from a
  `length` finish also raises, via the same `_parse_judge_reply` path used for the first
  attempt), noting the rejection in the system text, mirroring `Runner._two_turns`'s handling
  of the identical failure mode; it raises only if the retry also fails. The return type
  stays `tuple[JudgeLabels, ModelReply]` per the brief's interface: on a retried case only the
  retry's `ModelReply` is returned, so that case is priced from the retry's usage alone, not
  both attempts' combined usage — the interface was not widened to
  `tuple[JudgeLabels, tuple[ModelReply, ...]]` because no caller in this plan (Task 13's
  `judge` CLI command, Task 14) was written yet to consume a tuple of replies, and widening
  it now would be speculative; flagged for Andy/the reviewer in the Task 12 report as a
  follow-up if judge-run cost accounting later needs the first attempt's tokens too. New
  tests: `test_judge_case_defaults_to_a_generous_output_cap` (asserts `max_output_tokens ==
  2000` via a settings-capturing scripted client), `test_judge_case_retries_once_after_a_
  truncated_reply` (a scripted client returns `content=None, finish_reason="length"` first,
  then a good reply; asserts one retry, the rejection text in the retry's system, and the
  retry's `ModelReply` is what's returned), and `test_judge_case_raises_after_two_bad_replies`
  (both replies unparsable; still raises `SchemaError`, two calls made).
- 2026-09-15, Task 2 (steps 1–4): under mypy `--strict`, the brief's `structured` and `body`
  dict literals in `scripts/openrouter_probe.py` inferred a narrower value type than
  `dict[str, object]` (e.g. `dict[str, Sequence[Collection[str]]]`), which failed the calls to
  `_post`/`_save` (dict's value type is invariant). Added explicit `dict[str, object]`
  annotations on those two literals instead of the brief's `# type: ignore[index]` comments,
  which mypy strict reported as unused (the actual errors were `arg-type` on the two call
  sites, not `index`). Also reformatted the final `print("sync usage:", ...)` line, which
  exceeded the 100-character line length, by extracting the redacted usage block into a local
  variable first. Behaviour is unchanged from the brief.
- 2026-09-15, Task 2 (steps 5–6), redaction gap found in `two_turn.json`: the saved request's
  tool message carried an unredacted `tool_call_id` (an OpenRouter-issued call id, not the
  case's own `id` field, so it was not covered by the existing `_REDACT_KEYS`). Added
  `"tool_call_id"` to `_REDACT_KEYS` in `scripts/openrouter_probe.py`, extended the redaction
  test to cover a `tool_call_id` field, and hand-redacted that one value in the already-saved
  `tests/fixtures/openrouter/two_turn.json` (no other byte in that file was changed).
  Confirmed with `grep -rE "sk-or|Bearer|call_[A-Za-z0-9]" tests/fixtures/openrouter`: the only
  match left is the field name `"tool_call_id"` itself (now holding the value `"redacted"`),
  which the pattern's `call_[A-Za-z0-9]` fragment matches inside the key name `tool_call_id`
  regardless of the value; no key material or live id remains.
- 2026-09-15, Task 2 (step 5), probe results: sync usage fields are `prompt_tokens`,
  `completion_tokens`, `total_tokens`, `cost` (USD), `completion_tokens_details.reasoning_tokens`,
  `prompt_tokens_details.cached_tokens`. `response_format` json_schema strict was honoured
  (every reply that finished with content parsed as the mini schema). Tool calls work
  (`finish_reason: tool_calls`, arguments `"{}"`); the two-turn exchange with a tool message
  works. Batch: submitted, first poll status null, then `in_progress`, `completed` after about
  3 minutes (luna 20:53->20:56 UTC, luna-pro about 4 minutes); results under
  `results[].response.body` (a chat completion), `response.status_code`; batch-level
  `usage.cost` present ($0.0012243 for 10 luna requests) but per-result `body.usage.cost` is
  null; batch `model` field is a dated id (`openai/gpt-5.6-luna-20260709`) while each body's
  `model` is `openai/gpt-5.6-luna:batch`; `request_counts` reports `{total, completed, failed}`.
  Both variants were run by the controller with Andy's key; total cost about $0.014.
- 2026-09-15, Task 2 (step 5), variant chosen: `openai/gpt-5.6-luna`, departing from the plan's
  stated rule ("prefer the one whose ten replies all parsed"). Luna's batch had 7 of 10 replies
  parse; all 3 failures had `finish_reason: length` with empty content because reasoning
  tokens used the probe's whole 300-token `max_tokens` (one reported 0 completion tokens).
  Luna-pro's batch had 10 of 10 parse, but its sync structured call also ended `length` with
  empty content, and it used about 15 times the prompt tokens (about 2,700-3,000 against 185
  for the same messages) and about 7 times the cost (batch of 10: $0.0082 against $0.0012). The
  rule's premise -- that the two variants cost the same -- does not hold in practice, so the
  rule does not apply as written; `luna`'s failures are a `max_tokens` cap artefact, not a
  model defect, and it is far cheaper. Only `luna`'s fixtures are kept under
  `tests/fixtures/openrouter/`.
- 2026-09-15, Task 2 (step 5), consequence for later tasks: reasoning tokens count against
  `max_tokens`, so `ModelSettings.max_output_tokens` must stay generous (the plan's 2000), and
  a reply with `finish_reason: length` and no content must be treated as a schema failure
  (retried once), not parsed.
- 2026-09-15, Task 2 (step 6), typos exclusion: `uv run typos` flagged many false positives in
  `tests/fixtures/openrouter/batch.json`, all inside the base64-encoded batch-file payload
  (`results[].response.body` blobs), the same class of problem Task 5 hit for the code-table
  CSVs. Added `tests/fixtures/openrouter/*.json` to `[tool.typos.files] extend-exclude` in
  `pyproject.toml` and mirrored it in `.pre-commit-config.yaml`'s `typos` hook `exclude`
  pattern (added `openrouter` to the `tests/fixtures/(records|api)/` alternation), matching
  the pattern already used for the other fixture directories. `uv run typos .` is clean after
  the change.

- 2026-09-15, Task 3 (Step 2's test, resolved by the controller before implementation): the
  brief's `test_client_retries_then_raises` expects `sleeps.count(1.0) == 1 and
  sleeps.count(2.0) == 1` with `max_attempts=3, backoff_seconds=1.0` and the default 60
  requests/minute (gap 1.0s), but the brief's `request_json` also sleeps the 1.0s rate-limit
  gap before every request after the first, through the same `sleep` function, which would
  make `count(1.0) == 3`. Resolved as directed: `request_json` no longer stacks the gap sleep
  on top of a retry backoff that already spaced the requests -- after a backoff sleep of `b`
  seconds, the next gap sleep is `max(0, gap - b)`, skipped when zero or negative; with no
  preceding backoff, the full gap applies. Added
  `test_client_applies_rate_limit_gap_between_successful_calls` (two successful `complete()`
  calls record exactly one gap sleep of `60/rpm`) to cover the case the brief's own test does
  not exercise.
- 2026-09-15, Task 3 (Step 3/4, mypy `--strict`): the brief's `parse_chat_completion` used a
  single `# type: ignore[index]` on `body["choices"][0]` and otherwise indexed the untyped
  JSON body directly (`message.get("tool_calls")`, `usage["prompt_tokens"]`, etc.). Under
  `--strict` that produced further `[index]`/`[attr-defined]`/`[arg-type]` errors beyond the
  one ignored (an object is not indexable, `int()`/`float()` do not accept `object`), and the
  one ignore comment itself would have been flagged unused once those were fixed by narrowing
  instead. Replaced the single ignore with explicit runtime-narrowing helpers
  (`_as_mapping`, `_first_choice`, `_as_int`, `_as_float`) that `isinstance`-check each
  untyped JSON value before use; a value of the wrong shape raises `TypeError`, still caught
  by the existing `except (KeyError, IndexError, TypeError, ValueError)` block and translated
  to `ModelError`, so behaviour for malformed replies is unchanged from the brief's intent.
  `tests/test_openrouter.py`'s `saved()`/`saved_response()` helpers needed the same treatment
  (`json.loads` returns `Any`): added an explicit `cast` in `saved()` and a `saved_response()`
  helper that casts `saved(name)["response"]` to `Mapping[str, object]`, used at each call
  site instead of the brief's inline `saved("name")["response"]`. No behaviour change; the
  saved fixtures and assertions are otherwise verbatim.
- 2026-09-15, Task 3 (Step 3/4, ruff): the brief's combined-condition assertions in
  `tests/test_openrouter.py` (e.g. `assert reply.content and json.loads(...)["phase"]`,
  `assert how == "reported" and dollars == ...`) trip ruff's `PT018` ("assertion should be
  broken down into multiple parts"). Split each into separate `assert` statements with the
  same checks, in the same order; no test loosened or removed. One `TRY301` ("abstract raise
  to an inner function") on the choices-list narrowing in `parse_chat_completion` was
  resolved the same way as the mypy fix above, by moving that check into the `_first_choice`
  helper, rather than a `noqa`.

- 2026-09-15, Task 5 (step 3): inspected the real `avall.mdb` schema (mdbtools) before writing
  the script, per the project's "never guess data details" rule. Table and column names
  (`eADMSPUB_DataDictionary`, `Table`, `Column`, `code_iaids`, `meaning`, `Question_Def`,
  `Events_Sequence`, `Occurrence_Code`, `findings_code`, `modifier_no`) matched the brief
  exactly. Two real departures found by inspection:
  1. **Phases and events both come directly from the dictionary, not from parsing
     `Events_Sequence`.** `eADMSPUB_DataDictionary` rows with `Table == "Events_Sequence"` and
     `Column == "Occurrence_Code"` already encode phase codes: a code_iaids of `"<3 digits>xxx"`
     (e.g. `"552xxx"`) is a phase, meaning "Landing-Landing Roll"; a code_iaids of
     `"xxx<3 digits>"` (e.g. `"xxx230"`) is an event, meaning "Loss of control on ground". This
     is simpler and more reliable than the brief's script, which loaded the `Events_Sequence`
     *data* table and inferred phase labels by string-stripping each row's
     `Occurrence_Description` and taking a `Counter.most_common()` majority vote — a heuristic
     that is unneeded once the dictionary's own phase rows are used directly. `Events_Sequence`
     is no longer exported at all.
  2. **`len(t.events) == 94` (M10) does not hold; the true count is 93, and the test was
     changed to assert 93.** The brief's literal events dict comprehension —
     `{r["code_iaids"][-3:]: r["meaning"] for r in dictionary if Table=="Events_Sequence" and
     Column=="Occurrence_Code"}` — takes the last three characters of *every* such row,
     including the 47 phase rows (`"552xxx"`, `"401xxx"`, …), which all end in the literal
     `"xxx"`. Those 47 rows collapse into one spurious dict entry at key `"xxx"` (last-writer-
     wins), so the literal script's `events` table actually holds 93 real three-digit event
     codes plus that one non-numeric artifact = 94, matching M10 by coincidence — M10 was
     measured with this same bug. Shipping key `"xxx"` in the events table would let
     `compose_occurrence` accept a nonsense event code and would render as a garbage line in
     the prompt (`render("events")`), so the script filters events to rows whose code_iaids
     starts with `"xxx"` **and does not also end with `"xxx"`**, giving the true count of 93.
     `phases` (47, using the dictionary-direct method above; floor `>= 43` still holds),
     `categories` (130), `items` (1019) and `modifiers` (73) all matched M10 exactly with the
     brief's literal formulas — no other counts changed.

  Also: `tests/test_records.py`'s `test_verdict_carries_flagged_findings`, as given in the
  brief, compares `finding_codes_in_cause` (which is sorted by `findingNumber`, per its own
  docstring and per the existing `finding_codes`) against `raw["aircrafts"][0]["findings"]` in
  raw fixture order. Real fixtures are not stored in finding-number order (e.g. one fixture's
  findings carry `findingNumber` values in the order `[4, 2, 1, 3]`), so the brief's test fails
  against real data. Fixed the test to sort by `findingNumber` before comparing, matching the
  documented, sorted contract of `finding_codes_in_cause`; used `cast` (as the rest of the file
  does) rather than the brief's `# type: ignore[index]` to satisfy mypy `--strict`.

  The committed `items.csv`/`modifiers.csv` tables are verbatim NTSB data-dictionary labels and
  trip several `typos` false positives: navigation and gear-system abbreviations the checker
  reads as truncated common words, plus a misspelling that is already present in the NTSB's own
  source data. Added `src/ntsb_probable_cause/scoring/tables/*.csv` to
  `[tool.typos.files] extend-exclude` in
  `pyproject.toml` (same rationale as the existing fixture excludes, decision 0015) and to the
  separate `exclude` regex on the `typos` hook in `.pre-commit-config.yaml`, which does not read
  that pyproject.toml setting.

  The corpus check (`_corpus_check_line`) is implemented and gated on
  `Settings().data_dir / "processed/cases.parquet"` existing; the processed corpus is not yet
  built in this worktree (an ingest is running elsewhere), so it was not run here — the results
  file records `"corpus check: data/processed/cases.parquet not present; not run"`. The
  controller should re-run `uv run python -m scripts.build_code_tables ...` once that file
  exists, to get the real corpus-check line.

- 2026-09-15, Task 4 (`model/batch.py`, `tests/test_batch.py`): implementation deviations from
  the brief, all confirmed against the saved `tests/fixtures/openrouter/batch.json`:
  - `poll`/`_result_from_item` use `isinstance`-narrowing helpers (`_as_mapping`, `_as_sequence`)
    instead of the brief's `# type: ignore[union-attr]` comments, matching Task 3's precedent
    for mypy `--strict`; behaviour is unchanged.
  - The saved fixture nests one result as `results[].response.body` (a `body` under `response`),
    which is what the brief already assumed — no shape deviation.
  - The brief's own two tests combine unrelated assertions with `and` in a single `assert`
    (e.g. `assert status.status == "completed" and sleeps == [5.0]`); ruff's `PT018` rejects
    that. Split each into one `assert` per condition; the checks themselves are unchanged.
  - Added four tests beyond the brief's two: `test_submit_rejects_mixed_model_ids` (the brief's
    `submit` code path raises `ModelError` on mixed model ids but the brief supplied no test for
    it), `test_poll_reports_batch_level_cost`, `test_poll_handles_a_result_with_no_body` (a
    result with no `body`, from the task prompt's carried instruction), and
    `test_reply_parsed_from_batch_has_no_reported_cost_and_prices_at_batch_rate` (carried from
    Task 3's review: the `cost_usd` "priced" branch was untested elsewhere, and every batch
    reply hits it since per-result `usage` has no `cost` key, confirmed against the fixture).
- 2026-09-15, Task 6 (`hypothesis.py`, `prompt.py`): resolved the brief's own open item ("if the
  provider's strict mode rejects pydantic's schema... log a deviation") before any live call,
  per the controller's instruction. Added `_strict`/`_strict_schema` — a small recursive
  converter run over `Hypothesis.model_json_schema()` / `Refinement.model_json_schema()` — that
  sets `additionalProperties: false` and completes `required` to every property (pydantic's
  `extra="forbid"` already gives the former; only the optional `item8` field, expressed by
  pydantic as `anyOf: [string, null]` with `default: null`, needed adding to `required`) and
  drops every `default` and `title` key, on the top-level schema and every node under `$defs`.
  Kept `$ref`/`$defs` (not inlined) since OpenAI strict mode accepts them, per the brief's
  suggestion this was simpler. `description` keys from docstrings are left in (strict mode
  accepts them; brief only named `default` and `title` as noise). Added
  `test_strict_schemas_are_openai_compatible`, walking both schemas recursively to assert every
  object has `additionalProperties is False`, `required == properties`, and no `default`
  anywhere, plus four more error-path tests (malformed JSON at both stages, unknown finding
  category, unknown modifier, refinement index out of range) that the brief's own test list
  did not cover, to keep `hypothesis.py` itself at 100% coverage rather than resting on the
  repo-wide 90% gate. Dropped the brief's unused `Payload` import from `prompt.py` (ruff/vulture,
  per the controller's instruction). Reflowed `SYSTEM_ANSWER`, `SYSTEM_REFINE`, the module
  docstrings, and `tables_block`'s literal (content unchanged, only where the line breaks fall)
  to fit the 100-character line limit; `tables_block`'s asserted output format
  (`"## Phase prefixes"` prefix, `"552  "`, `"44  Pilot"`, the case-number suffix) is unchanged.
  Test's modifier-not-in-table example uses `"97"` rather than the brief's implied `"99"`, which
  the real table already defines as a modifier — confirmed against `tables/modifiers.csv`.
- 2026-09-15, Task 6 fix round 1 (live smoke test + review, three findings):
  1. The controller's live smoke test against `openai/gpt-5.6-luna` found both strict schemas
     accepted (finish `stop`; stage 1 parsed), but at stage 2 the model returned `item8` as the
     full rendered `refine_message` line (`"02063040  Personnel issues — ... — Aircraft
     control"`) instead of the bare code, so `parse_refinement` raised "is not a child" — a live
     defect, not a hypothetical one. Fix: added `Field(pattern=...)` to every code field —
     `OccurrenceGuess.phase`/`.event` (`^[0-9]{3}$`), `FindingGuess.category6` (`^[0-9]{6}$`),
     `FindingGuess.modifier` (`^[0-9]{2}$`), `FindingGuess.item8` (`^[0-9]{8}$`, still nullable
     via `default=None`), `RefinedItem.item8` (`^[0-9]{8}$`, required). Verified first, via
     `test_every_table_code_matches_its_field_pattern`, that every code in all five committed
     tables (`phases` 47, `events` 93, `categories` 130, `items` 1019, `modifiers` 73) matches
     its pattern — no offenders, so no pattern needed loosening. Pydantic raises
     `ValidationError` on a pattern mismatch, already caught and re-raised as `SchemaError` by
     the existing `try`/`except` in `parse_hypothesis`/`parse_refinement`; added
     `test_rendered_item_label_in_item8_is_a_schema_error`, reproducing the smoke test's exact
     bad reply. Reworded `SYSTEM_REFINE` to say "Return only its eight-digit item code, never
     its label text" — kept short, clinical tone preserved. `PROMPT_VERSION` stays `"s1-v1"`:
     no evaluation run has used it yet, so the wording change needs no version bump.
  2. Review: `parse_hypothesis` validated `category6`/`modifier` against the tables but never
     `item8` on stage-1 findings, so a non-null stage-1 `item8` under the wrong category would
     silently compose a wrong 10-digit code (`finding_codes`), or raise a `SchemaError` far from
     where the bad value entered (inside `tables.compose_finding`, only if `finding_codes` is
     later called). Fix: `parse_hypothesis` now rejects any finding whose `item8` is not `None`
     and not a member of `tables.items_under(g.category6)`, in the same loop as the
     category/modifier checks. Added `test_stage1_item8_must_be_a_child_of_its_own_category`
     (valid child accepted and composes; wrong-category item rejected). The Task 6 report's
     self-review claim that `parse_hypothesis` validates every code before returning was wrong
     for this one field; corrected in the fix report appended to `task-6-report.md`.
  3. Review: `occurrence_distribution`'s dict comprehension keys by composed code, so two
     occurrence guesses that happen to compose to the same six-digit code would silently drop
     all but the last one's probability — a real risk once Task 7's `prob_on_true`/movement
     metrics read this distribution, not just a hypothetical. Fix: `parse_hypothesis` now
     raises `SchemaError` when `len(set(codes)) != len(codes)` over the composed occurrence
     codes, in the same place as the probability-sum check. Added
     `test_duplicate_occurrence_codes_are_a_schema_error`.
  All three fixes and their tests are in commit (see report); `uv run pytest
  tests/test_hypothesis.py -v` and `make check` both pass (264 total tests, 96.76% coverage,
  `scoring/hypothesis.py` and `scoring/prompt.py` both 100%).
- 2026-09-15, Task 5 follow-up (moving the controller's throwaway coverage measurement into
  `scripts/build_code_tables.py`, so it comes from a committed script per CLAUDE.md): the NTSB
  data dictionary that Task 5 built the tables from does not list every phase, event and modifier
  the corpus actually uses. `coverage_check` in `scripts/build_code_tables.py` (tested in
  `tests/test_build_code_tables.py`) counts, per split, cases whose primary occurrence code
  (`fields.occurrence_codes(raw)[0]`) cannot be composed because its phase prefix or event suffix
  is missing from the tables, and cases with at least one finding flagged in the probable cause
  (`fields.finding_codes_in_cause`) whose item or modifier is missing. Measured on the full
  corpus (`docs/results/s1-code-tables.txt`): development split (13,560 cases) has 204 (1.50%)
  with a non-composable primary occurrence code and 37 with a non-composable flagged finding;
  held-out (4,241 cases) has 77 (1.82%) and 20. That caps occurrence top-1 at about 98.5% on
  development and 98.2% on held-out, before the model gets a chance to be wrong. The build script
  ranks the two kinds of missing part separately, in different units, across both splits, because
  a case has one primary occurrence code but can carry several flagged findings: missing phase or
  event parts are ranked by CASE count (each case contributes at most one to a given part) —
  phase prefixes `553` (Landing-Landing Roll family, 135 cases) and `601` (113 cases) are absent
  from the dictionary's `Events_Sequence` rows entirely, and event suffixes `850`, `284`, `282`,
  `281` (20, 5, 4, 4 cases) are likewise undefined; missing item or modifier parts are ranked by
  FINDING count (a case with two flagged findings needing the same missing part contributes 2) —
  modifier `27` (50 findings, from fewer than 50 cases) and `98` (4 findings) are absent from the
  dictionary's `Findings` rows, and item `01011100` (9 findings) is likewise undefined. The tables
  are left exactly as Task 5 built them from the dictionary — S1
  does not extend them from corpus observation — and this gap is reported alongside the S1 bars
  rather than silently lowering the ceiling. Extending the tables with codes observed in the
  corpus (a `codes in use but not in the tables` list of 159, already printed by the existing
  corpus check) is a follow-up for Andy to decide, not part of this task.

- 2026-09-15, Task 7 (Step 1's test, resolved by the controller before implementation): the
  brief's `test_wilson_matches_published_value` asserted `(0.421, 0.715)` for
  `wilson(23, 40)`. Hand-computed the standard Wilson score interval as written in Step 3
  (`z=1.96, n=40, p=0.575`): centre ≈ 0.568232, half-width ≈ 0.146466, giving
  `low ≈ 0.421766` and `high ≈ 0.714698`, which round to `(0.422, 0.715)`, not `(0.421, 0.715)`.
  Kept the formula unchanged and corrected the test's expected low bound to `0.422`. Task 13
  carries the same `0.421` value in a later test and needs the same fix.
- 2026-09-15, Task 7 (Step 3, mypy `--strict`): under Python 3.14, `collections.abc` no longer
  exports `AbstractSet` (only `typing.AbstractSet`, deprecated, and `collections.abc.Set`).
  Importing `AbstractSet` from `collections.abc` as the brief's Step 3 does fails at import
  time. Changed the import to `from collections.abc import Set as AbstractSet` so the
  `seen_pairs: AbstractSet[str]` signatures are unchanged; behaviour is identical.
- 2026-09-15, Task 7 (Step 4, contracts, controller-resolved before implementation): import-linter
  `forbidden` contracts check transitive imports by default, so the brief's instruction to add
  all seven scoring modules (`codes`, `hypothesis`, `prompt`, `samples`, `records`, `ledger`,
  `baseline`) to "Only the splitter constructs synthesis and verdict"'s `source_modules` would
  fail lint-imports for modules that do not exist yet. Added only the three that exist now and
  do not reach `records.verdict`/`records.synthesis` even indirectly:
  `ntsb_probable_cause.scoring.codes`, `ntsb_probable_cause.scoring.hypothesis`,
  `ntsb_probable_cause.scoring.prompt`. `scoring.samples`, `scoring.ledger` and `scoring.baseline`
  are added to that contract's `source_modules` as each is created in a later task, not now.
  Noted for later: `scoring.records` and `scoring.ledger` (Task 9) will import
  `metrics.CaseScores`, which imports `records.verdict`, so they cannot ever be listed in that
  forbidden contract — the grimp allow-list test in `tests/test_import_boundaries.py` (direct
  imports only) is what covers them instead. Added `"ntsb_probable_cause.scoring"` to
  `forbidden_modules` of "The model boundary cannot see synthesis or verdict" as the brief says.
- 2026-09-15, Task 7 (Step 3, ruff `PT018`/`RUF015`): the brief's hand-worked test assertions in
  Step 1 combine multiple conditions with `and` (flagged by ruff `PT018`) and one bin lookup uses
  `[...][0]` instead of `next(...)` (flagged by `RUF015`). Split each combined assertion into
  separate `assert` statements and replaced the slice with `next(b for b in bins if ...)`; no
  expected value changed. Also added an explicit `-> Hypothesis` return annotation on the test
  helper `hyp()`, required by mypy `--strict` (`no-untyped-def`) and not spelled out in the
  brief's Step 1 snippet.
- 2026-09-15, Task 7 fix round 1 (review finding, plan-mandated, controller-resolved in favour
  of the approved spec): the plan's own Step 3 snippet for `score_case` gave an abstained case
  `predicted = ()`, so every `finding_precision_*` read `None` (indistinguishable from an
  answered case that gave no codes) and `finding_recall_*` read `0.0` only incidentally — a
  later mean over cases would silently drop abstained cases from precision instead of counting
  them against the model. Spec §4.1 (`docs/specs/2026-09-14-s1-scoring-and-evaluation-design.md`
  around line 267) is explicit: "an abstained case scores 0 on every accuracy column" —
  abstention is not a free pass. The spec governs. Added an `abstained` flag to
  `_precision_recall` in `metrics.py`: when true, precision is `0.0` when the verdict side has
  codes and `None` only when it does not (recall already computed to `0.0` in the abstained
  case without change, since `predicted` is empty and the verdict side is non-empty in every
  case this task scores). `score_case` now passes `abstained=hypothesis.abstain` to all four
  `_precision_recall` calls. Updated `CaseScores`' docstring to state the rule. Extended
  `test_abstained_case_scores_zero_on_accuracy` to assert all eight finding precision/recall
  columns are `0.0`. Flagged for Andy: the plan text itself needs the same correction wherever
  a later task's own snippet repeats the old `None`-on-abstain assumption.
- 2026-09-15, Task 7 fix round 1 (minor, cheap): `stated_versus_actual` divided by `n` with no
  guard for empty input (`ZeroDivisionError` on `observed=[]`). Added an `n == 0` guard
  returning `(0.0, 0.0)`, matching the empty-input behaviour of `wilson` and `bootstrap_mean`.
  Added `test_stated_versus_actual_on_no_steps`.
- 2026-09-15, Task 9 (controller resolution, no deviation needed but noted here for the
  record): `seen_pairs(processed)` lives in `samples.py`, not `ledger.py` as the brief's
  Interfaces block lists it — followed the code block, which puts it in `samples.py` (also
  what Task 13 expects). `ledger.py` does not re-export it.
- 2026-09-15, Task 9 (controller resolution, `tests/conftest.py`'s `eval_ids` fixture): changed
  the glob from `*.csv` to `*_ids.csv` so it loads only the four case-id-and-event-date lists
  (`decidability_ids`, `leakage_ids`, `heldout_400_ids`, `dev_400_ids`) and never the new
  `*_full.csv` regression sheets, which carry extra, withheld columns
  (`test_both_evaluation_lists_are_present` and every other existing `eval_ids` consumer are
  unaffected, since they only ever read the `*_ids.csv` lists by name).
- 2026-09-15, Task 9 (controller resolution, `test_evaluation_cases_are_held_out_by_event_date`):
  excluded `dev_400_ids` by name from this assertion — it is the one development-split list
  among the eval id lists (spec §5.3) — and added
  `test_s1_samples_are_split_pure_and_disjoint` (brief's Step 1) to assert `dev_400_ids` is
  development, `heldout_400_ids` is held-out, the two are disjoint, and neither overlaps the
  record fixtures.
- 2026-09-15, Task 9 (found while running the extended contamination suite against the real
  drawn samples, Step 5): `test_case_number_year_would_misclassify_labelled_cases` iterated
  `eval_ids.values()` and asserted the mismatch count is exactly 16 — M2's own measurement of
  the spike's original 70 labelled cases (`decidability_ids` + `leakage_ids`). Once
  `heldout_400_ids` (400 cases) and `dev_400_ids` (401 cases) are committed, the same loop over
  every list counts 189 mismatches, because the case-number/fiscal-year mismatch rate applies
  to any large sample, not only the labelled 70. This is not a regression: the test's own
  docstring names the fixed measurement ("M2: 16 of 70"). Scoped the loop to
  `("decidability_ids", "leakage_ids")` only, so the test keeps checking the number M2 measured
  and does not turn into a moving target as more samples are added; docstring extended to say
  so explicitly. No other existing assertion in `tests/test_contamination.py` was changed.
- 2026-09-15, Task 9 (`draw`, deviation from the brief's literal code, per the task's own
  context note): the brief's `draw` zips `*(table[col].to_pylist() for col in table.column_names)`
  against a `columns=[...]` list in a different order; `pq.read_table`'s returned column order
  is not guaranteed to match the requested list. Built an explicit `columns` list once and
  indexed `table[col]` by name for each of those names (`by_column = {col: table[col].to_pylist()
  for col in columns}`, then zipped `by_column[col] for col in columns`) so the tuple unpacking
  `(n, d, s, c, r)` always lines up with `(ntsb_number, event_date, split, investigation_class,
  raw_json)` regardless of the table's physical column order. Same fix applied in
  `scripts/draw_samples.py`'s own `_counts` helper. Behaviour on the actual processed file is
  unchanged (its columns happened to come back in request order), but the code no longer
  depends on that.
- 2026-09-15, Task 9 (ruff `--strict`/lint, mechanical, no behaviour change): `records.py`'s
  `read_jsonl` used a module-level `TypeVar("T", bound=BaseModel)` per the brief; ruff's `UP047`
  (Python 3.14 target) requires the PEP 695 syntax instead, so it is now
  `def read_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]`. `ledger.py`'s two
  `subprocess.run` calls had a single combined `# noqa: S603,S607` on the `subprocess.run(`
  line; ruff reported `S607` unused there because the partial-executable-path violation is
  actually raised on the argv list's own line, so each call now carries `# noqa: S603` on the
  call line and `# noqa: S607` on the list-literal line. `samples.py`'s day-14 threshold is now
  the named constant `MASK_LIFTS_AT_DAY = 14` (ruff `PLR2004`), and its `seen_pairs` docstring
  was shortened to fit the 100-column limit; wording only. `test_ledger.py`'s
  `sum(l.startswith(...) for l in lines)` (ruff `E741`, ambiguous name `l`) is now
  `sum(row.startswith(...) for row in lines)` in a separate `assert`, splitting the brief's
  combined `and` assertion (also required by `PT018`, hit again in `test_samples.py`'s day-1
  mask test). None of these change what is asserted.
- 2026-09-15, Task 9 (import-linter, per controller resolution): added
  `ntsb_probable_cause.scoring.samples` to the `source_modules` of "Only the splitter
  constructs synthesis and verdict" (`pyproject.toml`) — confirmed `lint-imports` still passes
  with it added, since `samples.py` imports only `fields`, `splits` and `pyarrow`. Did not add
  `scoring.records` or `scoring.ledger`: both import `scoring.metrics.CaseScores`, which
  imports `records.verdict`, so a `forbidden` contract (which import-linter checks
  transitively) would immediately break; `tests/test_import_boundaries.py`'s grimp allow-list
  test already covers them (neither imports `records.verdict`/`records.synthesis` directly, so
  neither needs to be on that allow-list either).
- 2026-09-15, Task 9 (fixture-guard check, controller resolution item 3): before committing the
  spike's full labelling sheets, checked `scripts/check_fixtures_redacted.py` (scans
  `tests/fixtures/**/*.json` only — the sheets are CSV, so it does not touch them, and running
  it after adding the files is still clean: `uv run python -m scripts.check_fixtures_redacted`
  exits 0), `.pre-commit-config.yaml` (no hook scans fixture CSVs for withheld text), decision
  0015 (redaction is about personal-data fields in JSON record fixtures, not about this copy),
  and `tests/test_contamination.py`/`tests/conftest.py` (the `eval_ids` fixture now loads only
  `*_ids.csv`, so `decidability_full.csv`/`leakage_full.csv` — which do carry the spike's own
  NTSB code and cause columns, and `leakage_full.csv`'s `factual_account` column — are never
  read by that fixture, by `samples.sample_ids` (`_FILES` names only the three `*_ids.csv`
  files), or by any payload builder). This matches spec §5.4's own instruction to copy them "as
  regression fixtures... kept out of any payload by the same guard as everything else." No
  guard rejected them and no test reads verdict/synthesis text out of them, so they were
  committed; `scripts/copy_eval_ids.py`'s README note now says so explicitly.
- 2026-09-15, Task 9 (typos, found when running `uv run typos .` after Step 5): the generated
  `tests/fixtures/eval/README.md` embeds a short git SHA from the spike repository, and the
  one drawn at this commit reads as two letters `typos` treats as a misspelled word (it
  suggests two three-letter replacements). This is the same class of false
  positive already excluded for the other fixture directories (base64 blobs, NTSB abbreviations
  in real records), not an authored typo, and will recur on some future spike commit's own SHA
  regardless of wording. Added `tests/fixtures/eval/README.md` to
  `[tool.typos.files] extend-exclude` in `pyproject.toml` and to the `typos` hook's `exclude`
  pattern in `.pre-commit-config.yaml`.
- 2026-09-15, Task 9 (Step 5, drawn sample counts, from `scripts.draw_samples`'s printed
  output, `NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data`):
  `heldout-400` came out at exactly 400 (`fatal=False`: C 23, F 1, L 176 = 200;
  `fatal=True`: F 142, L 58 = 200). `dev-400` came out at 401, one over target, from the
  per-class `round()` quota (spec §5.3/0026 keep the method as specified rather than
  re-tuning to hit 400 exactly): `fatal=False`: C 113, F 3, L 85 = 201; `fatal=True`: F 156,
  L 44 = 200.
- 2026-09-15, Task 9 fix round 1, point 2 (decision 0026 point 1's "the exclusion is
  stated"): `draw`'s docstring now names the class-I/M/T exclusion, and
  `scripts/draw_samples.py` gained `_excluded_counts` and now also prints, per split, how
  many cases of classes outside C/F/L were excluded in each fatal/non-fatal slice (counts
  only, never case IDs). Re-ran `NTSB_DATA_DIR=.../data uv run python -m
  scripts.draw_samples` after this change and after the point-1 fix below; the two committed
  CSVs came back byte-identical to the versions already in the commit (checked with `diff`
  against copies saved before the re-run, and `git status --porcelain` on
  `tests/fixtures/eval` showed no changes) — the exclusion count is a new read-only report,
  not a change to what is drawn. Printed exclusion counts: `heldout-400`: 4 non-fatal, 1
  fatal cases outside C/F/L excluded; `dev-400`: 242 non-fatal, 25 fatal.
- 2026-09-15, Task 9 fix round 1, point 1 (bug found while writing the new unit tests for
  `draw`): `draw` divided by `len(pool)` for each of the fatal and non-fatal slices with no
  guard for an empty pool, so a split/fatal combination with zero cases in classes C/F/L
  raised `ZeroDivisionError` instead of contributing zero cases to that slice. The real
  processed file never hits this (both fatal states have cases in dev and heldout), which is
  why it went unnoticed in Step 5, but `tests/test_samples.py`'s new
  `test_draw_excludes_classes_outside_c_f_l` (a fatal-only pool, so the non-fatal slice is
  empty) reproduced it immediately. Added `if not pool: continue` before the per-class quota
  computation in `samples.draw`. Confirmed this does not change the committed samples: the
  fatal x class counts and the two CSVs from a fresh `scripts.draw_samples` run after the fix
  are identical to the pre-fix ones (see the point-2 entry above, same re-run).
- 2026-09-15, Task 10 (`scoring/baseline.py`): the spike's `stratified_sample`
  (`ntsb_spike/src/ntsb_spike/common.py`) samples each stratum with pandas'
  `df[...].sample(min(k, count), random_state=seed)`, which pandas seeds as a *fresh*
  `numpy.random.RandomState(seed)` on every call, so each stratum's draw (and the final
  `sample(frac=1, random_state=seed)` reshuffle) is independent of the order strata are
  visited and independent of every other stratum's draw. The brief's port instead threads one
  continuing `random.Random(seed)` through every stratum and the final shuffle, so (a) the
  exact ids drawn differ from a literal re-implementation of the spike's RNG calls (already
  noted in the brief itself: "the spike used pandas' `sample(random_state=7)`, whose stream
  differs from `random.Random(7)`, so the reproduction matches by method, not by identical
  draw"), and (b) unlike the spike, the draw is sensitive to the order strata are processed,
  because they share one advancing RNG state. Mitigated by iterating strata in a fixed
  (`sorted`) order so the port is at least deterministic run to run, but this is a second,
  narrower way the port's random stream diverges from the spike's beyond the single sentence
  the brief flagged. Per spec §6.3's done-means ("within one point... or the results file
  explains the difference"), this affects only which specific case ids land in the 1,000-case
  draw, not the stratification rule (per-stratum share of `n`, floor of one) that determines
  the resulting occurrence-code mix; Task 13/15, which run the baseline on real data, should
  re-confirm the reproduction lands within the one-point band and log there if it does not.
- 2026-09-15, Task 10 fix round 1: review found that `predict`'s finding prediction was
  conditioned on each case's own key-conditioned top-1 occurrence code
  (`model.findings_by_code.get(occ[0], ())`), but the spike's `finding_code_baseline`
  (`ntsb_spike/src/ntsb_spike/baseline.py:44-58`) predicts one fixed top-3 finding set for
  every case in the sample: the finding codes most common among cases whose primary
  occurrence code equals the single sample-wide modal code
  (`df[occ_col].value_counts().index[0]`), never a per-key code. `fit`'s `findings_by_code`
  already accumulates, per primary code, the finding codes of every case with that primary
  code regardless of key — exactly what the spike computes for the modal code — so only
  `predict` needed to change, to `model.findings_by_code.get(model.fallback[0], ())`
  (`model.fallback[0]` is the sample-wide modal primary code, since `fallback` is built from
  the unconditioned `overall` counter). The occurrence prediction stays key-conditioned;
  only findings follow the spike's single sample-wide code, so the finding-baseline
  reproduction is like-for-like with the spike's 17.0%/19.0% precision/recall. Added
  `test_finding_prediction_is_the_sample_wide_modal_codes_not_per_key`, a hand-computed
  synthetic-record test (not built with the implementation's own `Counter`/`most_common`)
  showing two cases with different phase|weather keys get different occurrence predictions
  but the identical finding prediction. Noted on
  `test_fit_and_predict_on_fixtures_by_hand` that it is a wiring test, since it shares
  `Counter.most_common` with the implementation and would not have caught this bug.
- 2026-09-15/16, Task 11 (`scoring/runner.py`): the brief's own Step 1 test,
  `test_case_number_probe_refused_off_dev`, runs `include_case_number=True` against
  `sample="heldout-40"` but hands it a `record_fixtures[:1]` case, and every committed
  record fixture has a development-split event date (2009–2015). The brief's Step 3
  `case_payload` gates the probe on `split_of(event_date)` alone, which for that fixture is
  `Split.DEV`, so the given implementation does not raise — confirmed by running the given
  test, which failed with "DID NOT RAISE LeakageError". Spec §6.2's table reads "development
  split only, refused on any other **sample**", so the gate needs the run's requested sample
  too, not only the record's real date: `case_payload` now refuses unless *both*
  `_sample_split(spec.sample) is Split.DEV` and `split_of(event)` is `Split.DEV`. Checking
  only the sample would let a `dev-400` run leak a case number on a record that turns out not
  to be development-dated; checking only the date is what the brief wrote and it fails the
  brief's own test. Added `test_case_number_probe_included_on_a_development_sample_and_case`
  (calls `case_payload` directly) to cover the allowed path, since the brief's tests exercise
  only the refusal.
- 2026-09-15/16, Task 11: the brief's `_two_turns` returned the accumulated `replies` list
  only on a successful return, so a case that made two real, billable calls and then raised
  `SchemaError` (both the original and the retry failed to parse) was recorded with
  `cost_usd=0.0` — silently wrong cost accounting for exactly the failure mode the task
  description calls out ("correctness of ... cost accounting ... matters more than anywhere
  else"). Changed `_two_turns`/`_run_stage1_pass`/`_run_stage2_pass` to append every reply —
  including ones from calls whose parse then fails — to the case's reply list (`ctx.replies`
  in the sync path, `run.contexts[cid].replies` in the batch path) as soon as each call
  returns, before any parsing is attempted, so `_cost`/`_fail_case` always price a failed case
  from every call actually made for it. As a related consequence, the stage-2 history turn
  now carries the content of whichever stage-1 reply actually parsed (`ctx.replies[-1]`),
  rather than the brief's `first.content`, which would have replayed a rejected ("not json")
  stage-1 reply as assistant history whenever the first attempt failed and the retry
  succeeded.
- 2026-09-15/16, Task 11 (controller resolution 2): the brief defers the batch path to
  Task 13's app-level `respx`/`batch.json` test, but real held-out money moves through this
  path in Tasks 14–15, so per the controller's resolution the batch path is unit-tested here
  with a scripted fake satisfying a small `BatchRunner` `Protocol` (not the brief's
  `BatchClient` type on the constructor) — `submit`/`wait` only, so `BatchClient` still
  satisfies it structurally. Schema and missing-reply failures in batch mode are retried once
  per stage exactly as sync does (resolution 3: system text carries "Your previous reply was
  rejected: <error>"), capping every run at four batches (stage 1, stage 1 retry, stage 2,
  stage 2 retry); a batch ending anywhere but `completed` raises `ModelError` naming the
  batch id; batch ids are appended to `runs_dir/<run id>/batches.jsonl` with stage and time
  immediately after `submit`, before `wait` (resolution 4); `on_status` writes to stderr, not
  stdout (resolution 7, via `Runner._log_status`, since `sys.stderr.write` returns an `int`
  and the `Callable[[str], None]` the batch client expects does not accept that). Not built:
  a `resume` command reading `batches.jsonl` to continue an interrupted run by polling
  (resolution 4 says this is out of scope unless needed in practice; it was not needed here).
- 2026-09-15/16, Task 11: read spec §11 ("a call whose prompt estimate exceeds the cap is
  recorded as failed with reason `cap`") and §14 (the cost bound is a pre-run/pre-call
  estimate, never a post-hoc reconciliation) as specifying only the brief's pre-call
  `over_cap` estimate from character counts; neither section asks for a second check against
  a case's *actual* spend after the calls are made. Implemented only the brief's pre-call
  cap (controller resolution 5's first branch); did not add a post-hoc actual-cost flag,
  since the spec does not ask for one and resolution 5 says not to invent extra behaviour it
  doesn't ask for.
- 2026-09-15/16, Task 11: refactored the brief's flat per-call parameter lists (many methods
  threading `spec`, `folder`, `batch_ids`, `costs`, `contexts`, `results` separately) into two
  small dataclasses, `_CaseContext` (one case's payload/system/verdict/spec/replies, reused
  by both the sync and batch paths) and `_BatchRun` (the batch pass's shared mutable state:
  folder, contexts, results, per-stage hypotheses, batch ids, costs), because the brief's
  literal parameter lists tripped ruff's `PLR0913`/`PLR0917` (more than five arguments) on
  most of the batch-path helpers once they were fleshed out. Behaviour is unchanged; this is
  a structural cleanup, not a semantic departure, done to pass `make check` without `noqa`
  comments scattered across the batch path.
- 2026-09-15/16, Task 11: the attribution trailer in this plan's own "Commit messages end
  with" rule and in `global-constraints.md` ("Co-Authored-By: Claude Opus 5 (1M context)")
  disagrees with the live session's attribution instruction for this task
  ("Co-Authored-By: Claude Sonnet 5"), which is explicitly stated to supersede a previous
  copy of the same reminder and names the same session URL. Used the live session's trailer
  (Claude Sonnet 5) as the more specific, current instruction; flagging here since the two
  disagree and a future session should reconcile which is authoritative.
- 2026-09-16, Task 11 fix round 1: the review (weighted to cost correctness, since Tasks
  14-15 spend real money) found three Important problems and four Minors in commit
  `830148c`, all fixed in one round:
  - **Important — batch stage-2 retry replayed the wrong assistant turn.**
    `_run_stage2_pass` built history from `run.contexts[cid].replies[-1].content`, which on
    the *retry* pass is the just-rejected stage-2 reply, not the stage-1 hypothesis (the
    sync path never had this bug: it pins `history` once in a local variable and reuses it
    for both stage-2 attempts). Fixed by adding `_CaseContext.stage1_content`, set once in
    `_run_stage1_pass` right after a stage-1 reply parses successfully, and read by
    `_run_stage2_pass` for every stage-2 request instead of `replies[-1]`. Covered by
    `test_batch_stage2_retry_replays_the_stage1_content_not_the_rejected_reply`, which
    captures both stage-2 requests' `history` and asserts both carry the accepted stage-1
    reply's text.
  - **Important — a mid-run abort recorded no spend.** `cases.jsonl`/`run.jsonl` were
    written only after every case finished, so a stage-2 batch ending
    `expired`/`failed`/`cancelled` after the stage-1 batch for the whole sample was billed
    (or a `LeakageError` on case *N* of a sync run) discarded every already-paid case:
    `Runner.run`, which reports the month's spend to the next run's budget refusal, never
    even wrote those files. Fixed by wrapping `Runner.run`'s answering step in
    try/except: on any exception, `cases.jsonl`/`steps.jsonl` and a `RunRecord` with
    `finished=None` (no new field added to `records.py` — `finished` was already optional)
    are written from whatever was accumulated, before re-raising. For the batch path,
    `_answer_batch` now populates a `_BatchRun` passed in by the caller (instead of
    returning a tuple), and on any exception marks every case that never got a result as
    `failed(..., f"aborted: {error}", cost)` priced from whatever replies it already
    received, so the accrued cost surfaces in both the per-case and run-level totals rather
    than vanishing. No `resume` command was added (out of scope, per the original Task 11
    resolution 4). Covered by
    `test_batch_abort_on_stage_two_failure_still_records_stage_one_spend`: a fake batch
    client that ends the stage-2 wait `expired` leaves a `run.jsonl` whose `cost_usd` (and a
    `cases.jsonl` entry) equal exactly the billed stage-1 reply.
  - **Important — cost accounting was verified only by tests that cannot fail.**
    `case.cost_usd >= 0.0` passes at `0.0`, and `RecordingFakeClient` hardcoded
    zero-token `Usage`, so every sync-path cost assertion in the file was vacuous — the
    suite would have passed identically with the $0 accounting bug Deviation 2 (commit
    `830148c`) describes. Fixed by giving `RecordingFakeClient` an optional `usage`
    parameter (`Sequence[Usage]`, defaulting to `()` — unchanged zero-usage behaviour for
    every test that does not pass it) and rewriting the weak assertions to hand-computed
    dollar amounts: `test_sync_stage_two_schema_failure_is_retried_once_then_recorded` now
    prices all three calls by hand; a new
    `test_sync_cost_reflects_both_replies_when_the_retry_succeeds` covers a stage-1 schema
    failure whose retry succeeds, asserting `CaseResult.cost_usd`, `RunRecord.cost_usd` and
    `StepRecord.cumulative_cost_usd` all equal the hand-computed price of both calls; and
    the batch-path failure tests now assert cost from the fixture's existing 100/50-token
    `Usage`.
  - **Minor — `reported_batch_cost_usd` silently summed only the batches that reported a
    cost**, presenting a partial total as "the batch total" the spec asks it to be. Changed
    `_BatchRun.costs` to `list[float | None]` (one entry per batch, always appended, `None`
    when a batch stayed silent) and `Runner._reported_total` returns `None` if any entry is
    `None`. `test_batch_stage1_retry_recovers_and_the_case_still_completes` (whose first,
    "not json", batch never reported a cost) now asserts `run.reported_batch_cost_usd is
    None` instead of the old partial `0.03`.
  - **Minor — a retry pass's failure text recorded pass 1's error.** `_stage1`/`_stage2`
    discarded the retry pass's own returned error dict and reused the first pass's, so a
    case that failed schema validation on attempt 1 but failed with a model error on retry
    was filed `schema: ...` instead of `model: ...`. Fixed by capturing and iterating the
    retry pass's own return value. Covered by
    `test_batch_stage1_retry_records_its_own_error_not_pass_ones`.
  - **Minor — `test_batch_records_batch_ids_before_waiting` only checked the end state.**
    Rewritten so the fake's own `wait` handler asserts `batches.jsonl` already contains its
    batch id when `wait` is called (before returning a status), which actually tests the
    submit-before-wait ordering rather than only the final file contents.
  - **Minor — no test asserted batch status stays off stdout.** Added
    `test_batch_status_goes_to_stderr_not_stdout`, using `capsys` to assert `captured.out ==
    ""` and that both stage names appear in `captured.err`.
  Files touched: `src/ntsb_probable_cause/scoring/runner.py`,
  `src/ntsb_probable_cause/model/client.py` (`RecordingFakeClient`'s new optional `usage`
  parameter), `tests/test_runner.py`. `uv run pytest tests/test_runner.py -v` — 31 passed;
  full suite — 337 passed, 97.11% coverage (gate 90%), `runner.py` itself 98%. `make check`
  (ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest) all pass.
  This commit's trailer lines are the two exact lines from `global-constraints.md`
  ("Claude Opus 5 (1M context)"), per the coordinator's explicit instruction for this fix
  round, which is a narrower and more recent directive than the general disagreement noted
  in the entry above (about the *previous* commit, `830148c`); that disagreement between
  `global-constraints.md` and the live session reminder is still unresolved for any future
  commit that does not carry an explicit per-commit instruction.
- 2026-09-16, Task 11 fix round 2 (commit `2a56821` re-reviewed; both Minors folded in
  before Tasks 14-15 spend real money):
  - **Minor — `except Exception` does not catch `KeyboardInterrupt`/`SystemExit`.**
    `Runner.run` and `_answer_batch` caught `Exception`, so a Ctrl-C during a real batch's
    `wait` (which polls for a long time — the most likely real mid-run abort) would skip
    the partial-write path entirely and leave the stage-1 spend invisible to the next run's
    budget guard. Widened both clauses to `except BaseException`, unchanged otherwise
    (still re-raises); `_abort_unresolved` was already typed `error: BaseException` so no
    change there. Corrected `Runner.run`'s docstring, which said "on any exception" without
    saying `BaseException` is what is actually caught. Test:
    `test_batch_keyboard_interrupt_during_wait_still_records_stage_one_spend` — a fake
    batch client whose stage-2 `wait` handler raises `KeyboardInterrupt` after stage 1 was
    billed; asserts `run.jsonl`'s `RunRecord` has `finished is None` and `cost_usd` equal to
    the billed stage-1 reply, `cases.jsonl` has one `aborted: ...` case with the same cost,
    and the `KeyboardInterrupt` itself still propagates out of `.run()`.
  - **Minor — an aborted run reported a partial batch total as the whole.**
    `_submit_and_wait` raised `ModelError` on a non-`"completed"` status *before* its caller
    appended anything to `run.batch_ids`/`run.costs`, so a failing batch contributed
    nothing — an aborted run whose one prior batch reported `0.01` showed
    `reported_batch_cost_usd == 0.01`, silently presenting a one-batch sum as the whole
    run's total, and the failing batch's id was missing from `RunRecord.batch_ids` even
    though `batches.jsonl` already had it. Fixed by moving the
    `run.batch_ids.append(status.batch_id)` / `run.costs.append(status.reported_cost_usd)`
    calls into `_submit_and_wait` itself, right after `wait()` returns and before the
    status check — so both are recorded (the cost as `None` when the batch did not
    complete) regardless of whether the status was terminal-good or terminal-bad, and
    removed the now-duplicate appends from `_run_stage1_pass`/`_run_stage2_pass`. This also
    gave the "if `batch_ids` can carry the failing batch's id too" request for free: it now
    does, since the append happens unconditionally before the raise.
    `test_batch_abort_on_stage_two_failure_still_records_stage_one_spend` (from round 1) now
    asserts `record.reported_batch_cost_usd is None` (was `pytest.approx(0.01)`) and
    `record.batch_ids == ("b1", "b2")` (was unchecked).
  Files touched: `src/ntsb_probable_cause/scoring/runner.py`, `tests/test_runner.py`.
  `uv run pytest tests/test_runner.py -v` — 32 passed; full suite — 338 passed, 97.11%
  coverage (gate 90%), `runner.py` 98%. `make check` all green. Commit trailer lines exactly
  as given in `global-constraints.md`, per the coordinator's explicit instruction (as in fix
  round 1).
- 2026-09-16, Task 13 (controller resolution 1): the brief's
  `test_proportion_cell_has_wilson_interval` asserts `round(cell.low, 3) == 0.421` for
  `proportion([True] * 23 + [False] * 17)`. Evaluating `scoring.metrics.wilson(23, 40)`
  (unchanged since Task 7, which made the same correction) gives a low bound of
  `0.4217...`, which rounds to `0.422`, not `0.421`. Implemented the test with `0.422`, per
  the controller's resolution, rather than changing the (already-verified) Wilson formula
  to match an arithmetic slip in the brief.
- 2026-09-16, Task 13 (controller resolutions 2-3): implemented `--limit N` on `run` (first
  N sample cases, as Task 14 step 1 needs), and added `--cap-usd`/
  `--expected-cost-per-case-usd` flags plus `Settings.expected_cost_per_case_usd`
  (`NTSB_EXPECTED_COST_PER_CASE_USD`, default `None`), documented in `.env.example`, so
  `RunSpec.expected_cost_per_case_usd` can be fed from either the flag or the environment
  once Task 14 step 1 has measured a number (the flag wins when both are set).
- 2026-09-16, Task 13: `baseline_report`'s `tables: CodeTables` parameter is accepted for
  interface symmetry with the model-scoring commands (`report`, `threshold`) but not used:
  `scoring/baseline.py`'s `fit`/`predict` work on already-composed codes read straight from
  the raw record (`fields.occurrence_codes`/`finding_codes`/`finding_codes_in_cause`), so no
  code-table composition is needed to score a baseline prediction. Documented in the
  function's docstring; the parameter is explicitly `del`eted at the top of the function
  body so it is not flagged as unused.
- 2026-09-16, Task 13: `apps/eval/__main__.py`'s `report` command additionally prints
  `weighted_headline` (spec §5.2's fatal-share-weighted top-1) whenever the run's own sample
  is `heldout-400`, beside `summarise`'s unweighted per-slice table. This is not spelled out
  in the brief's Step 4 prose, but spec §5.2 says the weighted headline is "shown beside" the
  unweighted number for that specific sample, and Task 13 is the only task that builds
  `weighted_headline`, so wiring it into the one command that prints per-run numbers was the
  only way to satisfy that spec sentence within this task rather than leaving the function
  unused by the app until a later task.
- 2026-09-16, Task 13: this task's commit uses the two attribution trailer lines given by
  the live coordinating session's system reminder ("Claude Sonnet 5" /
  `session_0166iU7TDYoS14D2oiw5zzG8`), not the "Claude Opus 5 (1M context)" lines in
  `global-constraints.md`. The disagreement between the two sources was already flagged as
  unresolved in the Task 11 fix-round-1 entry above; those two commits used the
  `global-constraints.md` lines only because the coordinator gave an explicit per-commit
  instruction to do so at the time. No such override was given for this task, and the
  current system reminder states it supersedes an earlier copy of the same reminder embedded
  in project text (which is what `global-constraints.md`'s trailer lines are: attribution
  text from a prior session, not a CLAUDE.md or memory rule from Andy), so this commit
  follows the live reminder instead.
- 2026-09-16, Task 13 fix round 1 (review of commit `454a43a`, before Task 14 spends money):
  - **Important — the `judge` subcommand spent money outside every refusal.** `apps/eval/__main__._cmd_judge`
    called `judge_case` per case with no budget check and no cap, discarded the reply as
    `_reply` so no cost was ever priced, and wrote `judge.jsonl` once with `write_text` after
    the whole loop, so an interrupt or a mid-loop `SchemaError` lost every already-paid label.
    Fixed by moving the loop into `scoring/judge.py` as `judge_run(...)` (library code, inside
    the coverage gate — `apps/eval` stays thin wiring): it refuses over budget first, using
    the same `runner.project_cost`/`refuse_over_budget` pair a `run` uses, projected from a
    new `JUDGE_EXPECTED_COST_PER_CASE_USD` table (`{"batch": 0.0004, "standard": 0.00089}`,
    the controller's measured numbers); it prices each case with `model.client.cost_usd` and
    calls `on_row` immediately after that case is paid for, so the app's `on_row` callback
    (`apps.eval._cmd_judge`) appends the row to `judge.jsonl` and flushes it right away — an
    interrupt after case *k* keeps rows 0..*k*. The judge run's total cost is recorded as a
    second `RunRecord` appended to the same run's `run.jsonl` (`<run_id>-judge`), which
    `month_spent` already sums correctly since it iterates every `RunRecord` a `run.jsonl`
    holds, not just the first; on an exception partway through, `_cmd_judge` still records
    whatever was paid (summed from the rows `on_row` already wrote) before re-raising, mirroring
    the runner's own partial-write-then-reraise. The known gap stays documented in both
    `judge_run`'s and `judge_case`'s docstrings: a case whose reply needs `judge_case`'s
    internal retry is priced from the retry alone, so that case's cost omits the first
    attempt's tokens. New tests: `test_judge_run_refuses_over_budget_before_any_call`,
    `test_judge_run_prices_each_case_and_writes_rows_incrementally`,
    `test_judge_run_keeps_rows_paid_for_before_a_later_case_fails`,
    `test_judge_expected_cost_per_case_matches_the_controllers_measurement` (`tests/test_judge.py`),
    plus `test_month_spent_sums_every_runrecord_in_a_run_jsonl_not_only_the_first`
    (`tests/test_eval_app.py`).
  - **Important — the baseline floor was never wired into a report.** `report.summarise`'s
    `floor=` parameter existed but no command ever passed it, so `s1-bars.txt` would have
    shown no floor despite spec §6.3 calling the honest baseline "the floor every table
    shows". Added `report.honest_baseline_floor(processed) -> dict[str, float]` (fits on
    development, scores on the whole held-out split, returns `Cell.value` floats keyed
    `top-1`/`top-3`/`finding recall@10 (flagged)`/`finding recall@10 (all)`), refactored out
    of `baseline_report`'s existing fit/score logic (`_honest_model_and_all`, shared by both).
    `apps/eval._cmd_report` now always computes it and passes it to `summarise`. Test:
    `test_honest_baseline_floor_returns_the_headline_figures_as_plain_floats`.
  - **Important — the report output had no provenance.** `docs/results/*.txt` is the only
    artefact of a run that survives in git; a table with no run id, sample, arm, model,
    exclusions, commit SHA/dirty flag, timing or total cost cannot be told apart from a
    different run's, or a complete run's from an aborted one (decision 0018 requires the
    commit SHA). Added `report.provenance(record: RunRecord) -> str`, printed at the top of
    `_cmd_report`'s output before `summarise`'s table; it marks `[complete]` or
    `[ABORTED (partial results)]` from `record.finished`. Tests:
    `test_provenance_shows_status_commit_and_totals`,
    `test_provenance_marks_an_aborted_run_and_a_dirty_commit`.
  - **`make bars` never reported `heldout-40`.** It ran `heldout-40` but never printed a
    report for it, so spec §13 item 3's side-by-side with the spike's 57% was never produced.
    Added a `report --latest ceiling heldout-40 --out docs/results/s1-heldout-40.txt` line to
    the `bars` target. This is a departure from the plan's literal `Makefile` block (Task 13,
    Step 4): logged here as the plan requires, not silently changed.
  - **Minor (5) — nothing pinned that CLI flags actually reach `RunSpec`.** Added
    `test_run_flags_reach_runspec_and_month_spent_reaches_runner`, a spy `Runner` class
    (monkeypatched into `apps.eval.__main__`) capturing the constructed `RunSpec` and the
    `month_spent_usd` the app computed, asserting `--cap-usd`, `--budget-usd`,
    `--expected-cost-per-case-usd` and `--limit` all reach it and that the (monkeypatched)
    `month_spent` return value reaches `Runner`.
  - **Minor (6) — `threshold_curve` divided by `len(scored)`, not all cases.** Spec §9 says
    "the mean score" over the cases; a failed case (no hypothesis at all) was previously
    dropped from the denominator instead of counting as a 0, same as an abstention. Fixed the
    divisor to `len(results)`; the chosen threshold is unaffected on every existing case (no
    prior test had a failed case). Test:
    `test_threshold_curve_divides_by_every_case_not_only_scored_ones`.
  - **Minor (7) — the weighted headline printed no count.** Added `report.fmt_n(cell)`
    (`fmt(cell) + " (n=...)"`) and used it in `_cmd_report`'s weighted-headline line, per
    spec §4.3 ("a figure with no count is a bug"). Test: `test_fmt_n_includes_the_count`.
  - **Minor (8) — the held-out ledger path was hardcoded relative to the cwd.** Added
    `Settings.heldout_ledger_path` (`NTSB_HELDOUT_LEDGER_PATH`, default
    `docs/results/heldout-ledger.md`, matching the prior hardcoded literal exactly, so
    existing behaviour is unchanged unless the new variable is set) and used
    `settings.heldout_ledger_path` in `_cmd_run` instead of a literal `Path(...)`. Documented
    in `.env.example`.
  - **Minor (9) — `resolve_latest` could return an aborted run.** Rewrote it to read each
    candidate folder's `run.jsonl` and skip any run with `finished is None`, so `--latest`/
    `--against-latest` (and therefore `make bars`) can never silently resolve to, and report,
    a partial held-out run as if it were complete. Tests:
    `test_resolve_latest_picks_the_newest_completed_matching_folder`,
    `test_resolve_latest_skips_an_aborted_run_even_if_newest`; the
    "raises when nothing matches" test's expected message was updated to
    `"no completed run found"`.
  - **Minor (10) — a bad `--exclude` value and a refused run both produced a raw traceback.**
    `--exclude` now has `type=EvidenceRole`, so an unknown role is caught by argparse itself
    (`invalid EvidenceRole value: ...`, exit code 2) instead of raising deep inside
    `_cmd_run`. `main` now wraps its command dispatch in
    `try/except (BudgetError, ConfigurationError)`, printing `"{command}: {error}"` to stderr
    and returning 1, since both are refusals Andy is expected to hit by hand (an over-budget
    run, a held-out run from a dirty tree) and a one-line message is the right shape, not a
    traceback. Tests: `test_run_rejects_an_unknown_exclude_role_as_an_argparse_error`,
    `test_run_over_budget_exits_one_line_not_a_traceback`.
  Files touched: `src/ntsb_probable_cause/scoring/report.py`, `src/ntsb_probable_cause/scoring/judge.py`,
  `src/ntsb_probable_cause/settings.py`, `.env.example`, `apps/eval/__main__.py`, `Makefile`,
  `tests/test_report.py`, `tests/test_judge.py`, `tests/test_eval_app.py`.
  `uv run pytest` — 384 passed, 97.66% coverage (gate 90%); `report.py` and `judge.py` both
  100%. `make check` (ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict,
  pytest) all pass. Commit trailer lines exactly as given in `global-constraints.md`
  ("Claude Opus 5 (1M context)"), per the coordinator's explicit instruction for this fix
  round (as in the Task 11 fix rounds); the disagreement between `global-constraints.md` and
  the live session reminder, noted in this task's own first entry above, is still otherwise
  unresolved for any future commit without an explicit per-commit instruction.
- 2026-09-16, Task 13 fix round 1, self-review addendum (found while writing the fix report
  for `f5ace7e`, before any further review): appending the judge pass's cost as a second
  `RunRecord` into the same run's `run.jsonl` (fix 1 above) broke every other reader that
  assumed exactly one row -- `apps/eval/__main__.resolve_latest` (`(record,) = read_jsonl(...)`),
  `_cmd_report` and `_cmd_judge` (`(run_record,) = read_jsonl(...)`) would all raise
  `ValueError: too many values to unpack` the first time `report`/`judge`/`--latest` touched a
  folder that had already been judged, or the second time `judge` was run on the same folder.
  Added `answering_run_record(folder) -> RunRecord` (the first row of `run.jsonl`, which is
  always the answering run's own record since the judge row is only ever appended after it
  exists) and used it in all three places instead of tuple-destructuring. Test:
  `test_answering_run_record_is_the_first_row_even_after_a_judge_pass`. Second commit of this
  fix round, same trailer lines, same reason.
- 2026-09-16, Task 13 fix round 2 (re-review of the second fix-round-1 commit; all ten
  fix-round-1 findings confirmed addressed with no Critical/Important breakage):
  1. **`judge.jsonl` unlink ordering.** `judge_path.unlink(missing_ok=True)` ran before
     `judge_run`'s budget refusal, so a refused re-judge (or one that raised before its
     first label) deleted the previous pass's already-paid rows -- the same class of loss
     fix round 1 fixed for the write path, on a new path. Replaced the unconditional unlink
     with a lazy truncate: `on_row` opens the file `"w"` only the first time it is actually
     called (tracked by a `nonlocal wrote_first_row` flag) and `"a"` after, so a run that
     never reaches a first label leaves the previous file untouched. Test:
     `test_judge_command_never_deletes_a_prior_pass_labels_on_a_refused_retry` -- the
     app-level judge test the reviewer asked for, which fails against the pre-fix code.
  2. **`JUDGE_EXPECTED_COST_PER_CASE_USD` provenance and pricing.** Corrected the comment to
     say exactly what was measured: one live call (2026-09-16, standard price,
     anthropic/claude-haiku-4.5), 769 prompt / 24 completion tokens, $0.000889
     provider-reported. The batch figure ($0.000445) is now labelled an estimate computed
     from that same call's tokens against `sources.HAIKU_45_BATCH`'s confirmed price, not a
     second measurement. Both dict values are set to spec §14's own conservative budget
     (~$1/800 cases = $0.00125/case, about 3x the one measured call), with the choice and
     reason stated in the comment. Separately, `price_variant="standard"` had no confirmed
     OpenRouter price (`sources._PRICES` holds only the batch-suffixed judge model id), so a
     standard call whose reply did not report its own cost would `KeyError` from inside
     `cost_usd` after already being paid for. Added `judge._ensure_priced`, called before
     the budget-checked loop, which raises `ConfigurationError` before any call if the
     variant has no confirmed price, rather than inventing one (project rule: no API detail
     is guessed). Tests:
     `test_judge_expected_cost_per_case_uses_the_conservative_spec_budget`,
     `test_judge_run_refuses_a_standard_priced_call_before_any_call`.
  3. **A held-out judge pass must appear in the held-out ledger (spec §13 item 8).**
     `_record_judge_cost` now appends a ledger row via `ledger.append_row` whenever the
     judged run's own sample starts with `"heldout"`, using the judge `RunRecord` it already
     builds and `judge.jsonl` as the results file. `_cmd_judge` also calls
     `ledger.refuse_if_heldout_and_dirty(run_record.sample, commit[1])` before doing
     anything else, the same rule `Runner.run` already applies to an answering run. Tests:
     `test_judge_on_a_heldout_run_appends_a_ledger_row`,
     `test_judge_on_a_heldout_run_from_a_dirty_tree_is_refused` (both monkeypatch
     `ledger.commit_state` rather than depending on the real repo's dirty state, which is
     not reliable inside a test run).
  4. **The floor line was unlabelled and always the held-out population.** `summarise`'s
     floor line now says what it is: "honest baseline, spec §6.3: fit on development, scored
     on all 4,241 held-out cases". `_cmd_report` omits the floor entirely when the reported
     run's own sample is `dev-400`, since a held-out-fit floor beside a development table
     compares against a population the run was not on.
  5. **`report` must not traceback on a missing corpus.** Wrapped the floor computation in
     `apps/eval/__main__._floor_for_report`: on any exception reading/fitting the baseline,
     the report still prints, with a one-line `"(baseline floor unavailable: ...)"` note
     instead of the floor. The per-invocation refit itself is left as is (acceptable cost on
     real data), noted in `_floor_for_report`'s docstring.
  6. **`Settings.monthly_budget_usd` was read by nothing.** `run --budget-usd` and the new
     `judge --budget-usd` both default to `None` in argparse and fall back to
     `settings.monthly_budget_usd` in `_cmd_run`/`_cmd_judge` when unset; an explicit flag
     still wins. `test_run_flags_reach_runspec_and_month_spent_reaches_runner` (fix round 1)
     still passes unchanged since it always passes `--budget-usd` explicitly.
  Files touched: `src/ntsb_probable_cause/scoring/judge.py`,
  `src/ntsb_probable_cause/scoring/report.py`, `apps/eval/__main__.py`,
  `tests/test_judge.py`, `tests/test_report.py`, `tests/test_eval_app.py`.
  `uv run pytest` -- 389 passed, 97.67% coverage (gate 90%); `report.py` and `judge.py` both
  100%. `make check` (ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict,
  pytest) all pass. Commit trailer lines exactly as given in `global-constraints.md`
  ("Claude Opus 5 (1M context)"), per the coordinator's explicit instruction for this fix
  round (as in fix round 1 and Task 11's fix rounds).
- 2026-09-16, Task 14 (step 2), the controller's first paid run: a 10-case ceiling-arm run on
  `dev-400` with real calls (`openai/gpt-5.6-luna`, cost $0.0074) abstained on 10 of 10 cases,
  scoring 0% top-1 and 0% on every finding column. Because the evidence payload never carries
  the factual narrative (decision 0013) and S1 has no docket tool, thin structured-field
  evidence is the normal case, not the exception, and `SYSTEM_ANSWER`'s closing line ("If the
  evidence is too thin to name a cause, set abstain to true") invited abstention on every
  case. Per spec §4.1 ("Abstention is a claim, not a free pass") and §9 (the stopping
  threshold converts low *stated* confidence into abstention after the run, on a rule chosen
  on `dev-400` -- the model's own reticence must not pre-empt that rule), rewrote
  `SYSTEM_ANSWER`'s closing guidance in `src/ntsb_probable_cause/scoring/prompt.py`: the
  analyst now names its most probable cause even on thin evidence, expresses uncertainty
  through the occurrence/finding probabilities and the confidence value, and abstains only
  when the evidence supports no cause at all. Bumped `PROMPT_VERSION` to `"s1-v2"` (no
  results run has used `"s1-v1"`; only the controller's throwaway cost checks did). Updated
  the one test that pinned the version string
  (`tests/test_runner.py::test_sync_run_writes_three_files_and_one_step_per_case`). No schema
  or parsing change.
- 2026-09-16, Task 14 (step 2), the same paid run: `ntsb-eval run --sync` with the default
  `--price-variant batch` sent every case to the chat-completions endpoint under the
  `:batch` model id and got a 404 ("This model is only available through the Batch API. Use
  the /api/beta/batches endpoint instead.") on all 10 cases, recorded as `model:` failures --
  no cost, but indistinguishable from the harness being broken. Added
  `refuse_sync_with_batch_price` to `src/ntsb_probable_cause/scoring/runner.py`, called from
  `Runner.run` immediately after `refuse_if_heldout_and_dirty` and before
  `refuse_over_budget` (the same place the other pre-flight refusals live, so no caller can
  reach a model call while bypassing it): a sync run whose `price_variant` is `"batch"` now
  raises `ConfigurationError` naming the fix (`--price-variant standard` for a sync run, or
  drop `--sync` to use the batch service) before any request is built. `apps/eval/__main__.py`
  already caught `ConfigurationError` generically and prints it as one line, so no CLI change
  was needed. New test
  `tests/test_runner.py::test_sync_with_batch_price_variant_is_refused_before_any_call`
  asserts the error and that `client.payloads == []`. Every other test that ran `sync=True`
  with the (previously default) `batch` price variant now passes `price_variant="standard"`
  explicitly (`tests/test_runner.py`, `tests/test_boundary.py`, `tests/test_eval_app.py`);
  the two cost-accounting tests that hand-compute dollars from Luna's per-token price
  (`test_sync_stage_two_schema_failure_is_retried_once_then_recorded`,
  `test_sync_cost_reflects_both_replies_when_the_retry_succeeds`) were updated to Luna's
  standard rate ($0.20/$1.20 per MTok) instead of the batch rate ($0.10/$0.60 per MTok), since
  they now run at that price. `uv run pytest` -- 390 passed, 97.68% coverage (gate 90%).
  `make check` (ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest)
  all pass.
- 2026-09-16, Task 14 (step 2), second prompt iteration on `dev-400` only (never on a
  held-out sample): a fresh 10-case real run on `s1-v2` fixed the abstention problem
  (abstained 0 of 10, was 10 of 10) but surfaced a new failure -- the model hedges to
  placeholder codes on every case. All ten predicted event suffix `000` ("Unknown or
  undetermined"); all ten chose finding category `050000` / item `05000000` ("Not
  determined -- Not determined -- (general)") with modifier `00` ("Unknown/Not
  determined"). Top-1 was 0 of 10 and every finding precision/recall column 0%, while top-3
  was 20% (the phase prefix is often right; the undetermined event suffix is the miss) and
  cost was $0.0012/case at the standard price. Examples from the run: predicted `450000`
  against true `452470`; predicted `550000` against true `552230`; predicted `300000`
  against true `300330` -- in each case the model had the right general area but retreated
  to the undetermined suffix instead of naming the specific one. Fixed in the prompt only
  (no schema, parsing, or metrics change): added a paragraph to `SYSTEM_ANSWER` in
  `src/ntsb_probable_cause/scoring/prompt.py`, after the s1-v2 abstention wording (kept
  unchanged, since it is working) and before the "Reply only with JSON" sentence, naming the
  undetermined codes (event suffix `000`, finding category `050000`/item `05000000`,
  modifier `00`) as a last resort rather than a safe default, directing the analyst to the
  most specific event suffix and finding category the evidence supports, to express doubt
  through the probabilities and confidence value rather than by choosing an undetermined
  code, and reserving an undetermined code for when the official record itself would have
  nothing more specific to say. Bumped `PROMPT_VERSION` to `"s1-v3"` (no results run has used
  `"s1-v2"`; only this iteration's own cost checks did). Updated the one test that pinned
  the version string
  (`tests/test_runner.py::test_sync_run_writes_three_files_and_one_step_per_case`).
  `uv run pytest` -- 390 passed, 97.68% coverage (gate 90%). `make check` (ruff format, ruff
  check, lint-imports, deptry, vulture, mypy --strict, pytest) all pass.
- 2026-09-16, Task 14 (step 2), third prompt iteration on `dev-400` only (never on a
  held-out sample): `s1-v3` worked well -- a fresh 10-case real run scored top-1 25% (was
  0%), event match 25%, non-zero finding precision/recall, one exact occurrence hit
  (predicted `552230`, true `552230`), abstain 25%, cost $0.0029/case at the standard price.
  But 2 of 10 cases (20%, over the plan's 5% failure-rate threshold) failed with the
  identical stage-2 schema error: `schema: '02041044' is not a child of category
  '020410'`. The model built the item code by gluing the six-digit category to the
  two-digit modifier (`020410` + `44` = `02041044`) instead of choosing one of the
  eight-digit item codes listed under that category in the refine message; the runner's one
  retry made the same mistake. Fixed wording and rendering only (no schema, parsing, or
  metrics change): rewrote `SYSTEM_REFINE` in `src/ntsb_probable_cause/scoring/prompt.py`
  to say plainly that the modifier is already settled and not part of what is chosen now,
  that the message lists the eight-digit item codes belonging to each finding's category,
  that the analyst must choose one of those listed codes exactly as written, and explicitly
  that the item code is not the category code and never the category code with the modifier
  appended -- keeping the existing "return only the eight-digit code, never its label text"
  instruction. Also reworked `refine_message`'s rendering: each finding's heading now reads
  "Finding N: category CCCCCC (label), modifier MM already chosen" -- separating the
  category and the already-chosen modifier from each other and from the item list below,
  with its own line, "Item codes for this finding (choose one, exactly as listed):", so
  nothing in the rendering pairs a category digit string directly against a modifier digit
  string the way the concatenation mistake did; the item lines themselves are unchanged
  (`<8-digit code>  <label>`). Bumped `PROMPT_VERSION` to `"s1-v4"` (no results run has used
  `"s1-v3"`; only this iteration's own cost checks did). Updated the one test that pinned
  the version string
  (`tests/test_runner.py::test_sync_run_writes_three_files_and_one_step_per_case`);
  `tests/test_hypothesis.py::test_schema_is_strict_and_tables_block_holds_tables`'s
  `refine_message` assertion (`"02063040" in refine_message(...)`) needed no change, since
  the item-line format is unchanged. `uv run pytest` -- 390 passed, 97.68% coverage (gate
  90%). `make check` (ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict,
  pytest) all pass.
- 2026-09-16, Task 14 (step 2), found on the first real 400-case batch submission
  (`ntsb-eval run --arm ceiling --sample dev-400`): observed provider fact -- a batch id
  that `submit` just returned can 404 for a short time before it is readable through the
  batch GET endpoint. The stage-1 batch submitted successfully (its id was recorded in
  `batches.jsonl`), but the very first poll raised `ModelError:
  /api/beta/batches/batch-1789521169-LFofWWoQzHwuChB7kK27 returned 404:
  {"error":{"message":"Batch job batch-... not found.","code":404}}`, and the whole run
  aborted with a 400-request stage-1 batch already in flight and paid for. The probe never
  caught this because `scripts/openrouter_probe.py`'s polling loop read the GET response
  with a bare `.json()` and no status check, so the same 404 body silently printed as
  `batch None` instead of failing loudly. One 400-request stage-1 batch was orphaned by the
  abort; its cost will be read from the provider and recorded in the results file by hand,
  and the `dev-400` ceiling run will be re-submitted after this fix. Fixed in
  `src/ntsb_probable_cause/model/batch.py`, where polling belongs: `BatchClient.wait` now
  tolerates a 404 from `poll` for up to `not_found_grace_seconds` (default 120s, injectable),
  sleeping and retrying rather than raising immediately; a poll that succeeds (any status)
  clears the tolerance window, so a later 404 (a provider blip after the batch was already
  seen in a non-terminal state, not just the not-yet-visible case) gets its own fresh grace
  period rather than being tolerated forever; only once a window elapses with no successful
  poll does `wait` raise `ModelError` naming the batch id. Every other status behaviour (the
  `TERMINAL` set, `expired`/`failed` raising, per-result error handling in
  `_result_from_item`) is unchanged. The 404 is detected by matching `"returned 404" in
  str(error)` against the `ModelError` `OpenRouterClient.request_json` already raises for a
  non-retry status, rather than adding a new exception type or reaching into `httpx`
  internals. New tests in `tests/test_batch.py`, all instant (a `_FakeClock` advances a
  fake `now()` inside `sleep()`, never a real clock or a real sleep):
  `test_wait_tolerates_a_404_on_first_poll_then_succeeds`,
  `test_wait_raises_naming_the_batch_id_once_the_404_grace_window_elapses`, and
  `test_wait_tolerates_a_later_404_blip_after_a_non_terminal_status_was_seen`. Also fixed
  the probe's silent hole: `scripts/openrouter_probe.py`'s batch-polling loop now checks the
  GET's status code, treats 404 as "not yet visible" (prints a message and waits, rather
  than printing `batch None`), and calls `raise_for_status()` on every other non-2xx
  response, so the saved-response contract stays honest. `uv run pytest` -- 393 passed,
  97.61% coverage (gate 90%). `make check` (ruff format, ruff check, lint-imports, deptry,
  vulture, mypy --strict, pytest) all pass; two ruff findings surfaced by the new code
  (`PLR2004` magic value `404` in the probe, `PLR0913` too many arguments on
  `BatchClient.wait`) were fixed by naming the probe's constant `_HTTP_NOT_FOUND` and adding
  a `noqa: PLR0913` on `wait` with the reason (every parameter is a seam a test needs, per
  the method's own docstring), matching the project's existing style for that rule
  (`OpenRouterClient.__init__`, `Runner.__init__`).
