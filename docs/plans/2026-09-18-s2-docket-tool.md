# S2 — The docket tool: implementation plan

**Spec:** docs/specs/2026-09-18-s2-docket-tool-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from the specification in the **Deviations** section at the end.

**Goal:** Build the docket module (client, parser, extractor, classifier, manifest, filter), put docket documents behind the one split as evidence, close the four S1 gaps before any document reaches a model, measure the threshold, the filter and the docket shape on `dev-400` and on closed open-split cases, and run arm B with the docket once on `heldout-400` as the bar for S3.

**Architecture:** A new `ntsb_probable_cause.docket` package turns a case's `mkey` into a `Docket`: a parsed listing, a per-document manifest, and the extracted text of every readable PDF, page-marked. One pure function, `attach_docket`, adds a `docket` subtree to the raw record to make the **case context**; `fields.py` declares two new evidence roles that read from that subtree, so `split_record`, the five guard layers and `Payload.from_evidence` are unchanged (0041, 0042). The runner gains arm `B`, which attaches documents in a published rank order until the cap, estimated with output tokens, would be exceeded (0043). The monthly budget becomes a reservation under a lock (0045). Every measurement is a script writing counts to `docs/results/`.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, httpx + respx, `pypdf` (new), pyarrow, pytest + pytest-socket + hypothesis, ruff, mypy --strict, import-linter (all in `pyproject.toml` except `pypdf`).

## Global Constraints

- Every model call goes through `ModelClient` or `BatchRunner` (0009). Tests never reach the network (`--disable-socket`); HTTP is replayed with `respx` from files under `tests/fixtures/`.
- No withheld text or code reaches an answering payload: every payload is built by `split_record` + `Payload.from_evidence`, over a case context built only by `attach_docket`. There is no second assembler (0023, 0041).
- Docket fixtures come from `dev-400` cases only, drawn by script; a listing page is committed as received; document text is committed only for NTSB-authored born-digital documents after the scripted redaction pass and Andy's read, marked `reviewed_by` (0037). Everything else is outcome only.
- Numbers reported anywhere come from a script. Raw data, docket caches, run outputs and model text never go in git: `data/` is ignored; only summaries go under `docs/results/`. Open-split cases enter measurements as numbers only (0024, 0040).
- Coverage gate `--cov-fail-under=90`, branch coverage. `make check` = ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest.
- Docstrings in Google style on every public symbol (ruff `D`). Line length 100.
- Costs in US dollars; the default budget is $25 (0030). Nothing is tuned on `heldout-*`; every held-out run appends to `docs/results/heldout-ledger.md` and is refused from a dirty tree (0026). The single held-out run of this stage is Task 19 and nothing else touches held-out dockets.
- Polite fetching: one request every two seconds to `data.ntsb.gov`, the project user agent, and a cache under `data/docket/` so nothing is fetched twice.
- Commit messages end with the attribution lines the session gives you. Never commit to `main`. Pull requests are merged, never squashed (0033).
- Andy runs the paid and long-network steps (Tasks 15, 17, 18, 19); keys are read inside a shell script from `pass show api/openrouter`, never printed.

---

## File structure

| path | responsibility |
|---|---|
| `src/ntsb_probable_cause/errors.py` | + `DocketError` |
| `src/ntsb_probable_cause/settings.py` | + `docket_dir`, `docket_seconds_per_request` |
| `src/ntsb_probable_cause/sources.py` | + `DOCKET_BASE_URL`, `DOCKET_USER_AGENT`, `docket_document_url(href)` |
| `src/ntsb_probable_cause/model/client.py` | `Turn` gains `payload`; a tool turn carries a `Payload`, never text |
| `src/ntsb_probable_cause/model/openrouter.py` | `request_body` renders a tool turn from its payload |
| `src/ntsb_probable_cause/scoring/budget.py` | new: `month_spent`, `budget_lock`, `reserve`, `settle`, `release`, `open_reservations` (0045) |
| `src/ntsb_probable_cause/scoring/runner.py` | arm `B`; `estimated_cost_usd` with output; `prepare_case` with the drop rule; the reservation |
| `src/ntsb_probable_cause/scoring/records.py` | `RunRecord.arm` and `docket_filter`; `StepRecord.documents_attached`, `documents_not_read` |
| `src/ntsb_probable_cause/scoring/samples.py` | arm `B` in `arm_exclusions`; the docket roles in `masked_exclusions` |
| `src/ntsb_probable_cause/scoring/report.py` | cap-bound counts under the table |
| `src/ntsb_probable_cause/docket/__init__.py` | package docstring |
| `src/ntsb_probable_cause/docket/listing.py` | `ListingEntry`, `Listing`, `parse_listing`, `render_listing` |
| `src/ntsb_probable_cause/docket/client.py` | `DocketClient`: listing HTML and document bytes, cache, polite rate |
| `src/ntsb_probable_cause/docket/extract.py` | `extract_pdf` → `ExtractedDocument` with page markers |
| `src/ntsb_probable_cause/docket/classify.py` | `classify_pages`, `readable_pages`, `estimated_tokens`; `document_category` |
| `src/ntsb_probable_cause/docket/manifest.py` | `DocumentRecord`, `Docket`, `read_docket`; the status set |
| `src/ntsb_probable_cause/docket/filter.py` | `DENY_LIST`, `ARM_B_TYPES`, `ARM_B_RANK`, `is_denied`, `arm_b_documents` |
| `src/ntsb_probable_cause/docket/attach.py` | `attach_docket`, `render_document`, `amateur_built_replace` |
| `src/ntsb_probable_cause/fields.py` | `DOCKET_LISTING`, `DOCKET_DOCUMENTS` and their paths |
| `src/ntsb_probable_cause/records/evidence.py` | the two new fields |
| `src/ntsb_probable_cause/records/guard.py` | `MIN_SENTENCE_CHARS` re-set from `docs/results/s2-threshold.txt` (Task 16) |
| `apps/eval/__main__.py` | `--arm B`, `--docket-filter`; `release RUN_ID`; open reservations in `report`; judge writes a partial file |
| `scripts/make_docket_fixture.py` | `listing`, `draw`, `document`, `handcheck` |
| `scripts/docket_scan.py` | §8.1: the `dev-400` fetch and the development shape file |
| `scripts/corpus_scan.py` | `--docket`: §8.2 threshold and §8.3 filter measurement |
| `scripts/docket_shape_open.py` | §8.4 (0040), read and discard |
| `scripts/check_fixtures_redacted.py` | docket text fixtures carry `reviewed_by` |
| `tests/boundary.py` | + `RecordingBatchRunner`, `assert_requests_clean` |
| `tests/test_boundary.py` | the batch-path test and its mutation |
| `tests/test_budget.py`, `tests/test_docket_*.py`, `tests/test_attach.py` | new |
| `tests/fixtures/docket/<case_id>/` | `listing.html`, `manifest.json`, reviewed documents |
| `docs/results/s2-*.txt` | the results files of spec §8 |

---

### Task 1: The batch-path boundary test (spec §3.1)

**Files:**
- Modify: `tests/boundary.py`
- Modify: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `Runner`, `RunSpec` (`scoring/runner.py`), `BatchRequest`, `BatchResult`, `BatchStatus`, `BatchCounts` (`model/batch.py`), `ModelReply`, `Usage` (`model/client.py`).
- Produces: `tests.boundary.RecordingBatchRunner(stage1: str, stage2: str)` with `.requests: list[BatchRequest]`; `tests.boundary.assert_requests_clean(requests: Sequence[BatchRequest], withheld: Sequence[tuple[str, str]]) -> None`, which Task 2 extends to tool turns.

- [x] **Step 1: Write the failing test**

Append to `tests/test_boundary.py`:

```python
from tests.boundary import RecordingBatchRunner, assert_requests_clean

from ntsb_probable_cause.scoring import runner as runner_module


def _withheld(record_fixtures: list[dict[str, object]]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for raw in record_fixtures:
        narrative = fields.factual_narrative(raw)
        cause = fields.probable_cause(raw)
        if narrative:
            found.append(("factual narrative", narrative))
        if cause:
            found.append(("probable cause", cause))
    return found


def _batch_runner(tmp_path: Path, batch: RecordingBatchRunner) -> Runner:
    return Runner(
        RecordingFakeClient([]),
        batch=batch,
        tables=load_tables(),
        seen_pairs=frozenset(),
        runs_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.md",
        month_spent_usd=0.0,
        commit=("abc1234", False),
        now=lambda: datetime(2026, 9, 18, tzinfo=UTC),
    )


def test_batch_runner_never_sends_withheld_text_in_any_request(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The batch path is the default; it must be checked like the sync path (spec §3.1)."""
    batch = RecordingBatchRunner(stage1=_GOOD_STAGE1, stage2=_GOOD_REFINE)
    spec = RunSpec(sample="dev-400", arm="ceiling", expected_cost_per_case_usd=0.001)
    _batch_runner(tmp_path, batch).run(spec, record_fixtures)

    assert batch.requests, "the run should have submitted at least one batch request"
    assert_requests_clean(batch.requests, _withheld(record_fixtures))


def test_batch_boundary_test_fails_when_a_system_prompt_leaks(
    tmp_path: Path,
    record_fixtures: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation test: the batch assertion must be able to fail (decision 0016)."""
    leaked = next(fields.factual_narrative(r) for r in record_fixtures if fields.factual_narrative(r))

    def leaky_retry_system(system: str, error: str | None) -> str:
        return f"{system}\n\n{leaked}"

    monkeypatch.setattr(runner_module.Runner, "_retry_system", staticmethod(leaky_retry_system))
    batch = RecordingBatchRunner(stage1=_GOOD_STAGE1, stage2=_GOOD_REFINE)
    spec = RunSpec(sample="dev-400", arm="ceiling", expected_cost_per_case_usd=0.001)
    _batch_runner(tmp_path, batch).run(spec, record_fixtures)

    with pytest.raises(AssertionError, match=r"^tripwire"):
        assert_requests_clean(batch.requests, _withheld(record_fixtures))
```

Add `from ntsb_probable_cause.scoring.codes import load_tables` is already imported; keep the existing imports.

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_boundary.py -q`
Expected: ImportError, `RecordingBatchRunner` not defined.

- [x] **Step 3: Write the recording batch runner and the assertion**

Append to `tests/boundary.py`:

```python
from collections.abc import Sequence
from dataclasses import dataclass, field

from ntsb_probable_cause.model.batch import (
    BatchCounts,
    BatchRequest,
    BatchResult,
    BatchStatus,
)
from ntsb_probable_cause.model.client import ModelReply, Usage


@dataclass
class RecordingBatchRunner:
    """A ``BatchRunner`` for boundary tests: keeps every request it was given, replies by stage.

    The stage is read off each request's ``settings.schema_name`` (``hypothesis`` for
    stage 1, ``refinement`` for stage 2), so one instance serves a whole two-stage run.
    """

    stage1: str
    stage2: str
    requests: list[BatchRequest] = field(default_factory=list)
    _pending: dict[str, list[BatchRequest]] = field(default_factory=dict)

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        batch_id = f"boundary-{len(self._pending) + 1}"
        self.requests.extend(requests)
        self._pending[batch_id] = list(requests)
        return batch_id

    def wait(self, batch_id: str, *, on_status=lambda _s: None) -> BatchStatus:  # type: ignore[no-untyped-def]
        results = tuple(
            BatchResult(
                custom_id=r.custom_id,
                reply=ModelReply(
                    content=self.stage1 if r.settings.schema_name == "hypothesis" else self.stage2,
                    usage=Usage(prompt_tokens=100, completion_tokens=50),
                    model=r.settings.model_id(),
                    response_id="fake",
                ),
                error=None,
            )
            for r in self._pending[batch_id]
        )
        status = BatchStatus(
            batch_id=batch_id,
            status="completed",
            results=results,
            reported_cost_usd=None,
            counts=BatchCounts(len(results), len(results), 0),
        )
        on_status(status)
        return status


def _request_texts(request: BatchRequest) -> list[tuple[str, str]]:
    """Every string a batch request would send: system, payload, and each history turn."""
    texts = [("system", request.system), ("payload", request.payload.text)]
    for turn in request.history:
        if turn.content is not None:
            texts.append((f"{turn.role} turn", turn.content))
        if getattr(turn, "payload", None) is not None:
            texts.append((f"{turn.role} turn payload", turn.payload.text))
    return texts


def assert_requests_clean(
    requests: Sequence[BatchRequest], withheld: Sequence[tuple[str, str]]
) -> None:
    """No withheld text in any system prompt, payload or history turn of any request."""
    for request in requests:
        for where, text in _request_texts(request):
            for kind, needle in withheld:
                assert needle not in text, (
                    f"tripwire: {kind} reached a batch request's {where} ({request.custom_id})"
                )
```

Type the `on_status` parameter properly instead of the ignore: `on_status: Callable[[BatchStatus], None] = lambda _s: None` with `from collections.abc import Callable`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_boundary.py -q`
Expected: PASS, including the mutation test.

- [x] **Step 5: Run the full check and commit**

Run: `make check`
Expected: green.

```bash
git add tests/boundary.py tests/test_boundary.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: batch-path boundary test with its mutation (spec §3.1)"
```

---

### Task 2: Tool turns carry a `Payload` (spec §3.2)

**Files:**
- Modify: `src/ntsb_probable_cause/model/client.py` (`Turn`)
- Modify: `src/ntsb_probable_cause/model/openrouter.py` (`request_body`, tool branch)
- Test: `tests/test_model_client.py`, `tests/test_openrouter.py`, `tests/test_boundary.py`

**Interfaces:**
- Produces: `Turn(role="tool", tool_call_id=..., payload=Payload)`; `Turn.content` is refused on a tool turn and `Turn.payload` on an assistant turn.

- [ ] **Step 1: Find every tool turn built today**

Run: `grep -rn 'role="tool"' src tests`
Expected: the `request_body` branch in `openrouter.py`, and possibly a test that builds a tool turn from `tests/fixtures/openrouter/two_turn.json`. Note each hit: they are updated in Step 4.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_model_client.py`:

```python
import pytest
from pydantic import ValidationError

from ntsb_probable_cause.model.client import Payload, Turn
from ntsb_probable_cause.records.split import split_record


def _payload(record_fixtures: list[dict[str, object]]) -> Payload:
    evidence, _, _ = split_record(record_fixtures[0])
    return Payload.from_evidence(evidence)


def test_tool_turn_carries_a_payload(record_fixtures: list[dict[str, object]]) -> None:
    turn = Turn(role="tool", tool_call_id="c1", payload=_payload(record_fixtures))
    assert turn.payload is not None
    assert turn.content is None


def test_tool_turn_refuses_plain_text() -> None:
    with pytest.raises(ValidationError, match="Payload"):
        Turn(role="tool", tool_call_id="c1", content="unchecked text")


def test_tool_turn_without_a_payload_is_refused() -> None:
    with pytest.raises(ValidationError, match="Payload"):
        Turn(role="tool", tool_call_id="c1")


def test_assistant_turn_refuses_a_payload(record_fixtures: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError, match="assistant"):
        Turn(role="assistant", content="ok", payload=_payload(record_fixtures))
```

Append to `tests/test_openrouter.py`:

```python
def test_request_body_renders_a_tool_turn_from_its_payload(
    record_fixtures: list[dict[str, object]],
) -> None:
    evidence, _, _ = split_record(record_fixtures[0])
    payload = Payload.from_evidence(evidence)
    history = (
        Turn(role="assistant", content=None, tool_calls=(ToolCall(call_id="c1", name="list_docket", arguments="{}"),)),
        Turn(role="tool", tool_call_id="c1", payload=payload),
    )
    body = request_body(payload, ModelSettings(), system="s", history=history)
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": payload.text}
```

(Import `Payload`, `Turn`, `ToolCall`, `ModelSettings`, `request_body`, `split_record` at the top of that file if not already there.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_model_client.py tests/test_openrouter.py -q`
Expected: the four `Turn` tests fail (no `payload` field / no validation), the body test fails on content.

- [ ] **Step 4: Implement**

In `src/ntsb_probable_cause/model/client.py`, replace the `Turn` class:

```python
class Turn(BaseModel):
    """One earlier message in a multi-turn exchange (assistant or tool).

    A tool turn carries its result as a ``Payload`` (spec §3.2): the only text that can go
    back to the model is text that passed the split and the guard. An assistant turn is the
    model's own words and carries plain content.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    role: Literal["assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    payload: Payload | None = None

    @model_validator(mode="after")
    def _tool_turns_carry_a_payload(self) -> Self:
        if self.role == "tool" and (self.payload is None or self.content is not None):
            raise ValueError("a tool turn carries its result as a Payload, never as text")
        if self.role == "assistant" and self.payload is not None:
            raise ValueError("an assistant turn carries content, not a Payload")
        return self
```

Add `from pydantic import model_validator` and `from typing import Self` to the imports. `Turn` must be defined after `Payload` in the module (it already is: `Payload` is at the top).

In `src/ntsb_probable_cause/model/openrouter.py`, the tool branch of `request_body`:

```python
        else:
            if turn.payload is None:  # pragma: no cover -- Turn's validator refuses this
                raise ModelError("a tool turn without a Payload cannot be sent")
            messages.append(
                {"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.payload.text}
            )
```

Update every hit from Step 1 that built a tool turn with `content=` to build it with `payload=`.

- [ ] **Step 5: Extend the boundary assertion to tool turns**

`tests/boundary.py`'s `_request_texts` already reads `turn.payload` via `getattr`; replace the `getattr` with a direct `turn.payload` now that the field exists. Add to `tests/test_boundary.py`:

```python
def test_batch_boundary_assertion_reads_tool_turn_payloads(
    record_fixtures: list[dict[str, object]],
) -> None:
    """A tool turn's payload is one of the texts the batch assertion inspects."""
    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    evidence, synthesis, _ = split_record(raw)
    leaked = evidence.model_copy(update={"prelim_narrative": synthesis.factual_narrative})
    request = BatchRequest(
        custom_id="x",
        payload=Payload.from_evidence(evidence),
        settings=ModelSettings(),
        system="",
        history=(Turn(role="tool", tool_call_id="c1", payload=Payload.from_evidence(leaked)),),
    )
    with pytest.raises(AssertionError, match=r"tool turn payload"):
        assert_requests_clean([request], [("factual narrative", synthesis.factual_narrative or "")])
```

(Import `BatchRequest`, `ModelSettings`, `Turn` in `tests/test_boundary.py`.)

- [ ] **Step 6: Run the tests, then the full check**

Run: `uv run pytest tests/test_model_client.py tests/test_openrouter.py tests/test_boundary.py tests/test_batch.py tests/test_runner.py -q` then `make check`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add src/ntsb_probable_cause/model tests/boundary.py tests/test_boundary.py tests/test_model_client.py tests/test_openrouter.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: a tool turn carries a Payload, never text (spec §3.2)"
```

---

### Task 3: The budget reservation under a lock (spec §3.3, decision 0045)

**Files:**
- Create: `src/ntsb_probable_cause/scoring/budget.py`
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`Runner.run`, `refuse_over_budget`)
- Modify: `apps/eval/__main__.py` (`month_spent` moves; `release`; `report`)
- Test: `tests/test_budget.py`, `tests/test_runner.py`, `tests/test_eval_app.py`

**Interfaces:**
- Produces: `budget.month_spent(runs_dir: Path, *, now: datetime) -> float` (moved from `apps/eval/__main__.py`, which re-imports it so `apps.eval.__main__.month_spent` still resolves); `budget.budget_lock(runs_dir) -> ContextManager[None]`; `budget.reserve(runs_dir, run_id, projected_usd, *, now)`; `budget.settle(runs_dir, run_id)`; `budget.release(runs_dir, run_id) -> bool`; `budget.open_reservations(runs_dir) -> dict[str, float]`; `RESERVATION_FILE = "reservation.json"`.
- `refuse_over_budget(projected, month_spent, budget, *, reserved=0.0)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_budget.py`:

```python
"""The monthly budget as a reservation under a lock (decision 0045)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import BudgetError
from ntsb_probable_cause.scoring.budget import (
    RESERVATION_FILE,
    budget_lock,
    month_spent,
    open_reservations,
    release,
    reserve,
    settle,
)
from ntsb_probable_cause.scoring.runner import refuse_over_budget

NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_reserve_writes_a_reservation_the_next_run_can_see(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert (tmp_path / "run-1" / RESERVATION_FILE).exists()
    assert open_reservations(tmp_path) == {"run-1": 20.0}


def test_settle_removes_the_reservation(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    settle(tmp_path, "run-1")
    assert open_reservations(tmp_path) == {}
    settle(tmp_path, "run-1")  # idempotent


def test_release_reports_whether_anything_was_open(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert release(tmp_path, "run-1") is True
    assert release(tmp_path, "run-1") is False


def test_second_run_is_refused_when_the_first_reservation_fills_the_budget(tmp_path: Path) -> None:
    """The 2026-09-17 incident: four runs each projected $20 against $25 and all passed."""
    with budget_lock(tmp_path):
        refuse_over_budget(20.0, month_spent(tmp_path, now=NOW), 25.0, reserved=0.0)
        reserve(tmp_path, "run-1", 20.0, now=NOW)
    with budget_lock(tmp_path):
        reserved = sum(open_reservations(tmp_path).values())
        with pytest.raises(BudgetError, match="reserved"):
            refuse_over_budget(20.0, month_spent(tmp_path, now=NOW), 25.0, reserved=reserved)


def test_budget_lock_is_reentrant_across_processes_by_file(tmp_path: Path) -> None:
    """The lock is a file under the runs directory, created on first use."""
    with budget_lock(tmp_path):
        assert (tmp_path / ".budget.lock").exists()


def test_month_spent_ignores_reservations(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert month_spent(tmp_path, now=NOW) == 0.0
```

Append to `tests/test_runner.py`:

```python
from ntsb_probable_cause.scoring.budget import RESERVATION_FILE, open_reservations, reserve


def test_run_reserves_at_start_and_settles_at_the_end(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400", arm="ceiling", sync=True, price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    run = runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert not (tmp_path / "runs" / run.run_id / RESERVATION_FILE).exists()
    assert open_reservations(tmp_path / "runs") == {}


def test_run_is_refused_by_another_runs_open_reservation(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    reserve(tmp_path / "runs", "other-run", 24.99, now=datetime(2026, 9, 15, tzinfo=UTC))
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400", arm="ceiling", sync=True, price_variant="standard",
        expected_cost_per_case_usd=0.05,
    )
    with pytest.raises(BudgetError, match="reserved"):
        runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert client.payloads == []


def test_an_aborted_run_settles_its_reservation(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    class Dies:
        def complete(self, payload: object, settings: object, *, system: str = "", history: object = ()) -> ModelReply:
            raise KeyboardInterrupt

    spec = RunSpec(
        sample="dev-400", arm="ceiling", sync=True, price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    with pytest.raises(KeyboardInterrupt):
        runner(tmp_path, Dies()).run(spec, record_fixtures[:1])
    assert open_reservations(tmp_path / "runs") == {}
```

Append to `tests/test_eval_app.py` (use the file's `_eval_env` helper the way `test_run_over_budget_exits_one_line_not_a_traceback` does):

```python
def test_release_clears_a_dead_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    reserve(runs_dir, "dead-run", 5.0, now=datetime(2026, 9, 18, tzinfo=UTC))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    assert main(["release", "dead-run"]) == 0
    assert "released dead-run" in capsys.readouterr().out
    assert open_reservations(runs_dir) == {}
    assert main(["release", "dead-run"]) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_budget.py tests/test_runner.py tests/test_eval_app.py -q`
Expected: ImportError on `ntsb_probable_cause.scoring.budget`.

- [ ] **Step 3: Write the budget module**

Create `src/ntsb_probable_cause/scoring/budget.py`:

```python
"""The monthly budget: finished spend plus open reservations, under a lock (decision 0045).

A run reserves its projected cost at start and settles it at the end. A run launched a
second later sees the reservation. A run that dies leaves its reservation standing, so the
guard errs towards refusing; ``release`` clears one by hand.
"""

import fcntl
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl

RESERVATION_FILE = "reservation.json"
LOCK_FILE = ".budget.lock"


def month_spent(runs_dir: Path, *, now: datetime) -> float:
    """Cost of every run started in ``now``'s month, aborted runs included.

    A run folder's ``run.jsonl`` may hold more than one ``RunRecord`` (the answering run
    and a judge pass), and every one of them counts. Reservations are not spend and are
    not counted here.
    """
    if not runs_dir.exists():
        return 0.0
    total = 0.0
    for run_file in sorted(runs_dir.glob("*/run.jsonl")):
        for record in read_jsonl(run_file, RunRecord):
            if record.started.year == now.year and record.started.month == now.month:
                total += record.cost_usd
    return total


@contextmanager
def budget_lock(runs_dir: Path) -> Iterator[None]:
    """Hold the runs directory's budget lock for the duration of the block."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    with (runs_dir / LOCK_FILE).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def reserve(runs_dir: Path, run_id: str, projected_usd: float, *, now: datetime) -> None:
    """Write the run's projected cost as an open reservation."""
    folder = runs_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RESERVATION_FILE).write_text(
        json.dumps({"projected_usd": projected_usd, "started": now.isoformat()})
    )


def settle(runs_dir: Path, run_id: str) -> None:
    """Remove the run's reservation; its actual cost is in ``run.jsonl`` by now."""
    (runs_dir / run_id / RESERVATION_FILE).unlink(missing_ok=True)


def release(runs_dir: Path, run_id: str) -> bool:
    """Clear a dead run's reservation by hand; True if one was open."""
    path = runs_dir / run_id / RESERVATION_FILE
    if not path.exists():
        return False
    path.unlink()
    return True


def open_reservations(runs_dir: Path) -> dict[str, float]:
    """Every open reservation, run id to projected dollars."""
    if not runs_dir.exists():
        return {}
    found: dict[str, float] = {}
    for path in sorted(runs_dir.glob(f"*/{RESERVATION_FILE}")):
        projected = json.loads(path.read_text()).get("projected_usd")
        if isinstance(projected, int | float):
            found[path.parent.name] = float(projected)
    return found
```

- [ ] **Step 4: Wire the runner**

In `scoring/runner.py`:

```python
def refuse_over_budget(
    projected: float, month_spent: float, budget: float, *, reserved: float = 0.0
) -> None:
    """Refuse a run that would take the month past its budget, counting open reservations."""
    if month_spent + reserved + projected > budget:
        raise BudgetError(
            f"projected ${projected:.2f} plus ${month_spent:.2f} spent and ${reserved:.2f} "
            f"reserved by other runs exceeds the ${budget:.2f} budget"
        )
```

In `Runner.run`, delete the early `refuse_over_budget(...)` line, and after `folder` is known (both the fresh and the resume branch) insert:

```python
        projected = project_cost(spec, len(raws))
        with budget_lock(self._runs_dir):
            # The caller's figure is a floor; the lock re-reads so a run that finished a
            # moment ago is counted, and other runs' reservations are added (0045).
            spent = max(self._spent, month_spent(self._runs_dir, now=started))
            reserved = sum(v for k, v in open_reservations(self._runs_dir).items() if k != run_id)
            refuse_over_budget(projected, spent, spec.budget_usd, reserved=reserved)
            reserve(self._runs_dir, run_id, projected, now=started)
```

The reservation is taken before `write_spec_json` on the fresh path is fine either way; keep `write_spec_json` where it is. In `write_outputs`, after `write_jsonl(folder / RUN_FILE, [record])`, add `settle(self._runs_dir, run_id)`. Import `budget_lock, month_spent, open_reservations, reserve, settle` from `ntsb_probable_cause.scoring.budget`.

`set_aside_aborted_outputs(folder)` moves the dead run's output files aside on a resume; check it does not move `reservation.json` (it renames named files; if it globs, exclude the reservation).

- [ ] **Step 5: Wire the command**

In `apps/eval/__main__.py`: delete the local `month_spent` and add `from ntsb_probable_cause.scoring.budget import month_spent, open_reservations, release`. Add a subcommand:

```python
    release_p = commands.add_parser("release", help="clear a dead run's budget reservation")
    release_p.add_argument("run_id")
```

and

```python
def _cmd_release(args: argparse.Namespace, settings: Settings) -> int:
    if release(settings.runs_dir, args.run_id):
        print(f"released {args.run_id}")
        return 0
    print(f"release: no open reservation for {args.run_id}", file=sys.stderr)
    return 1
```

dispatched in `main` (return its exit code). In `_cmd_report`, after the tables:

```python
    reservations = open_reservations(settings.runs_dir)
    if reservations:
        text += "\n\nopen budget reservations: " + ", ".join(
            f"{k} ${v:.2f}" for k, v in sorted(reservations.items())
        )
```

- [ ] **Step 6: Run the tests and the full check**

Run: `make check`
Expected: green. If `tests/test_eval_app.py::test_run_over_budget_exits_one_line_not_a_traceback` matches on the old message text, update its match to `"exceeds"`.

- [ ] **Step 7: Commit**

```bash
git add src/ntsb_probable_cause/scoring/budget.py src/ntsb_probable_cause/scoring/runner.py apps/eval/__main__.py tests/test_budget.py tests/test_runner.py tests/test_eval_app.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the monthly budget is a reservation under a lock (decision 0045)"
```

---

### Task 4: The cap counts output, and the re-judge writes a partial file (spec §3.4, §3.5)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`over_cap` → `estimated_cost_usd`)
- Modify: `apps/eval/__main__.py` (`_cmd_judge`)
- Test: `tests/test_runner.py`, `tests/test_eval_app.py`

**Interfaces:**
- Produces: `runner.estimated_cost_usd(payload_text: str, system: str, spec: RunSpec) -> float`; `over_cap` unchanged in signature, now `estimated_cost_usd(...) > spec.cap_usd`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runner.py`:

```python
from ntsb_probable_cause import sources
from ntsb_probable_cause.model.client import ModelSettings
from ntsb_probable_cause.scoring.runner import estimated_cost_usd, over_cap


def test_estimated_cost_reserves_the_maximum_output_at_the_output_price() -> None:
    spec = RunSpec(sample="dev-400", arm="ceiling", model="anthropic/claude-sonnet-5", price_variant="standard")
    price = sources.price_of("anthropic/claude-sonnet-5")
    reserve = ModelSettings().max_output_tokens * price.output_usd_per_mtok / 1e6
    assert estimated_cost_usd("", "", spec) == pytest.approx(reserve)
    assert estimated_cost_usd("x" * 4000, "", spec) == pytest.approx(
        reserve + 1000 * price.input_usd_per_mtok / 1e6
    )


def test_cap_binds_on_output_alone_for_a_dear_model() -> None:
    """M1: at Sonnet 5's standard price the output reserve is $0.02 of a $0.05 cap."""
    spec = RunSpec(sample="dev-400", arm="ceiling", model="anthropic/claude-sonnet-5", price_variant="standard", cap_usd=0.01)
    assert over_cap("", "", spec)
```

Append to `tests/test_eval_app.py`, next to `test_judge_command_never_deletes_a_prior_pass_labels_on_a_refused_retry` and using its fixtures and fake client shape:

```python
def test_judge_that_dies_mid_pass_leaves_the_previous_pass_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """Spec §3.5: rows go to judge.jsonl.partial; the old file is replaced only when complete."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0], record_fixtures[1])
    run_id = "20260101T000000-abc1234-dev-400-ceiling"
    _write_judgeable_run(runs_dir, run_id, case_id, sample="dev-400")
    second_id = str(record_fixtures[1]["ntsbNumber"])
    _write_judgeable_run(runs_dir, run_id, second_id, sample="dev-400")

    good = RecordingFakeClient([GOOD_LABELS, GOOD_LABELS])

    def good_factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return good, None

    assert main(["judge", run_id], client_factory=good_factory) == 0
    judge_path = runs_dir / run_id / "judge.jsonl"
    prior = judge_path.read_text()

    class DiesAfterOne:
        """One good label, then the provider falls over."""

        def __init__(self) -> None:
            self._inner = RecordingFakeClient([GOOD_LABELS])
            self.calls = 0

        def complete(self, payload: Payload, settings: ModelSettings, *, system: str = "", history: Sequence[Turn] = ()) -> ModelReply:
            self.calls += 1
            if self.calls > 1:
                raise ModelError("boom")
            return self._inner.complete(payload, settings, system=system, history=history)

    dying = DiesAfterOne()

    def dying_factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return dying, None

    with pytest.raises(ModelError):
        main(["judge", run_id], client_factory=dying_factory)
    assert judge_path.read_text() == prior
    assert (runs_dir / run_id / "judge.jsonl.partial").read_text().count("\n") == 1
```

`_write_judgeable_run` is the file's existing helper; check its signature and whether calling it twice appends a second case to `cases.jsonl` (it uses `write_jsonl`, which appends). Import `Payload`, `ModelSettings`, `Turn` from `model.client` and `Sequence` if missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_runner.py -k "estimated or cap_binds" tests/test_eval_app.py -k dies_mid_pass -q`
Expected: ImportError on `estimated_cost_usd`; the judge test fails because `judge.jsonl` was truncated.

- [ ] **Step 3: Implement the cap**

In `scoring/runner.py`, replace `over_cap`:

```python
def estimated_cost_usd(payload_text: str, system: str, spec: RunSpec) -> float:
    """Prompt at one token per four characters at the input price, plus the maximum output.

    The output reserve is what the S1 cap ignored (spec §3.4): with the default model it
    is a tenth of a cent, with Sonnet 5 at its standard price two cents of a five-cent cap.
    """
    settings = _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis")
    price = sources.price_of(settings.model_id())
    prompt_tokens = (len(payload_text) + len(system)) / 4
    return (
        prompt_tokens * price.input_usd_per_mtok
        + settings.max_output_tokens * price.output_usd_per_mtok
    ) / 1e6


def over_cap(payload_text: str, system: str, spec: RunSpec) -> bool:
    """Would the prompt plus the maximum output cost more than the cap?"""
    return estimated_cost_usd(payload_text, system, spec) > spec.cap_usd
```

- [ ] **Step 4: Implement the partial file**

In `_cmd_judge`, replace `judge_path` handling:

```python
    judge_path = folder / "judge.jsonl"
    partial_path = folder / "judge.jsonl.partial"
    judge_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path.unlink(missing_ok=True)
    paid: list[float] = []

    def on_row(row: Mapping[str, object]) -> None:
        # Rows go to a partial file; the previous pass's file is replaced only once this
        # pass completes (spec §3.5), so a pass that dies mid-way destroys nothing paid for.
        with partial_path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        paid.append(cast(float, row["cost_usd"]))
```

and after `judge_run` returns successfully, before `_record_judge_cost`:

```python
    if paid:
        partial_path.replace(judge_path)
```

Delete `wrote_first_row`.

- [ ] **Step 5: Run the tests and the full check**

Run: `make check`
Expected: green. `test_over_cap_case_is_failed_without_a_call` still passes (its cap is below the output reserve).

- [ ] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/scoring/runner.py apps/eval/__main__.py tests/test_runner.py tests/test_eval_app.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the cap counts output tokens; a re-judge writes a partial file (spec §3.4, §3.5)"
```

---

### Task 5: Settings, sources, errors, and the docket client with its cache (spec §4.1, §4.2)

**Files:**
- Modify: `src/ntsb_probable_cause/errors.py`, `settings.py`, `sources.py`, `.env.example`, `pyproject.toml` (import-linter contract 2 gains `ntsb_probable_cause.docket`)
- Create: `src/ntsb_probable_cause/docket/__init__.py`, `src/ntsb_probable_cause/docket/client.py`
- Test: `tests/test_docket_client.py`, `tests/test_sources_settings.py`

**Interfaces:**
- Produces: `errors.DocketError(NtsbError)`; `Settings.docket_dir: Path = Path("data/docket")`, `Settings.docket_seconds_per_request: float = 2.0`; `sources.DOCKET_BASE_URL = "https://data.ntsb.gov"`, `sources.DOCKET_USER_AGENT`, `sources.docket_document_url(href: str) -> str`; `DocketClient(cache_dir: Path | None, *, seconds_per_request=2.0, sleep=time.sleep, transport=None, max_attempts=5, backoff_seconds=2.0)` with `.listing_html(mkey: int) -> str`, `.document(mkey: int, index: int, href: str) -> bytes`, and `.close()` / context manager. `cache_dir=None` means read and discard (0040).
- Cache layout: `<cache_dir>/<mkey>/listing.html`, `<cache_dir>/<mkey>/<index>.bin`, `<cache_dir>/<mkey>/fetch.json` (`{"listing": {"time", "sha256"}, "documents": {"<index>": {"time", "sha256", "href"}}}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sources_settings.py`:

```python
def test_docket_settings_have_polite_defaults() -> None:
    settings = Settings()
    assert settings.docket_dir == Path("data/docket")
    assert settings.docket_seconds_per_request == 2.0


def test_docket_document_url_joins_the_relative_href() -> None:
    href = "/Docket/Document/docBLOB?ID=1&FileExtension=.pdf&FileName=x.pdf"
    assert sources.docket_document_url(href) == "https://data.ntsb.gov" + href
```

Create `tests/test_docket_client.py`:

```python
"""The docket client: polite fetching, a cache keyed by case, read-and-discard (spec §4.2)."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import DocketError

MKEY = 73612
LISTING_URL = sources.docket_url(MKEY)
HREF = "/Docket/Document/docBLOB?ID=1&FileExtension=.pdf&FileName=a.pdf"
PAGE = "<html>Docket Items: 0</html>"


def _client(tmp_path: Path | None, sleeps: list[float]) -> DocketClient:
    return DocketClient(tmp_path, seconds_per_request=2.0, sleep=sleeps.append)


def test_listing_is_fetched_once_and_cached(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    sleeps: list[float] = []
    with _client(tmp_path, sleeps) as client:
        assert client.listing_html(MKEY) == PAGE
        assert client.listing_html(MKEY) == PAGE
    assert route.call_count == 1
    assert (tmp_path / str(MKEY) / "listing.html").read_text() == PAGE
    fetch = json.loads((tmp_path / str(MKEY) / "fetch.json").read_text())
    assert fetch["listing"]["sha256"] == hashlib.sha256(PAGE.encode()).hexdigest()


def test_document_is_cached_by_index(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 x")
    )
    with _client(tmp_path, []) as client:
        assert client.document(MKEY, 3, HREF) == b"%PDF-1.4 x"
        assert client.document(MKEY, 3, HREF) == b"%PDF-1.4 x"
    assert route.call_count == 1
    assert (tmp_path / str(MKEY) / "3.bin").read_bytes() == b"%PDF-1.4 x"


def test_requests_are_two_seconds_apart(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, content=b"x")
    )
    sleeps: list[float] = []
    with _client(tmp_path, sleeps) as client:
        client.listing_html(MKEY)
        client.document(MKEY, 1, HREF)
    assert sleeps == [2.0]  # no sleep before the first request, one between the two


def test_user_agent_names_the_project(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    with _client(tmp_path, []) as client:
        client.listing_html(MKEY)
    assert route.calls[0].request.headers["user-agent"] == sources.DOCKET_USER_AGENT


def test_read_and_discard_writes_nothing(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    """Decision 0040: the open-split shape script keeps no documents."""
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    with _client(None, []) as client:
        assert client.listing_html(MKEY) == PAGE
    assert list(tmp_path.iterdir()) == []


def test_server_error_is_retried_then_raised(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(503))
    sleeps: list[float] = []
    with DocketClient(tmp_path, sleep=sleeps.append, max_attempts=3, backoff_seconds=1.0) as client:
        with pytest.raises(DocketError, match="503"):
            client.listing_html(MKEY)
    assert sleeps == [1.0, 1.0, 2.0]


def test_not_found_is_not_retried(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(404))
    with _client(tmp_path, []) as client:
        with pytest.raises(DocketError, match="404"):
            client.listing_html(MKEY)
    assert route.call_count == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docket_client.py tests/test_sources_settings.py -q`
Expected: ImportError on `ntsb_probable_cause.docket.client`.

- [ ] **Step 3: Implement**

`errors.py`, append:

```python
class DocketError(NtsbError):
    """The docket site returned an unusable page or file, or a listing did not parse."""
```

`settings.py`, add fields after `heldout_ledger_path`:

```python
    docket_dir: Path = Path("data/docket")
    docket_seconds_per_request: float = Field(default=2.0, ge=0)
```

`.env.example`, append `# NTSB_DOCKET_DIR=data/docket` and `# NTSB_DOCKET_SECONDS_PER_REQUEST=2`.

`sources.py`, next to `_DOCKET_URL` / `docket_url`:

```python
# The docket is not in the Enterprise API (../ntsb-spike/public.yaml has no docket path). It is
# a web page for people, scraped as the spike's probes did (../ntsb-spike/scripts/
# docket_shape_probe.py). The saved real page under tests/fixtures/docket/ is the source for
# its structure (rule 2, decision 0037).
DOCKET_BASE_URL = "https://data.ntsb.gov"
DOCKET_USER_AGENT = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"


def docket_document_url(href: str) -> str:
    """The absolute URL of a document link as the listing page gives it (``/Docket/Document/...``)."""
    return f"{DOCKET_BASE_URL}{href}"
```

Check `_DOCKET_URL` uses `DOCKET_BASE_URL` (define the base first and build `_DOCKET_URL = DOCKET_BASE_URL + "/Docket?ProjectID={mkey}"`).

`docket/__init__.py`:

```python
"""The docket tool: listing, documents, extraction, classification, the filter (spec S2)."""
```

`docket/client.py`:

```python
"""Fetch a docket's listing page and documents politely, into a cache keyed by case (spec §4.2)."""

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import DocketError

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
LISTING_FILE = "listing.html"
FETCH_FILE = "fetch.json"


class DocketClient:
    """One request every ``seconds_per_request``; every fetch cached unless ``cache_dir`` is None.

    ``cache_dir=None`` is read-and-discard (decision 0040): nothing is written anywhere.
    """

    def __init__(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        cache_dir: Path | None,
        *,
        seconds_per_request: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._cache = cache_dir
        self._gap = seconds_per_request
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._now = now
        self._requested = False
        self._last_backoff_slept = 0.0
        self._http = httpx.Client(
            headers={"User-Agent": sources.DOCKET_USER_AGENT},
            timeout=120.0,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    def listing_html(self, mkey: int) -> str:
        """The listing page for a case, from the cache or one polite fetch."""
        cached = self._cached(mkey, LISTING_FILE)
        if cached is not None:
            return cached.decode("utf-8", "replace")
        content = self._get(sources.docket_url(mkey))
        self._store(mkey, LISTING_FILE, content, {"listing": self._entry(content)})
        return content.decode("utf-8", "replace")

    def document(self, mkey: int, index: int, href: str) -> bytes:
        """One document's bytes, from the cache or one polite fetch."""
        name = f"{index}.bin"
        cached = self._cached(mkey, name)
        if cached is not None:
            return cached
        content = self._get(sources.docket_document_url(href))
        self._store(mkey, name, content, {"documents": {str(index): {**self._entry(content), "href": href}}})
        return content

    def _entry(self, content: bytes) -> dict[str, str]:
        return {"time": self._now().isoformat(), "sha256": hashlib.sha256(content).hexdigest()}

    def _cached(self, mkey: int, name: str) -> bytes | None:
        if self._cache is None:
            return None
        path = self._cache / str(mkey) / name
        return path.read_bytes() if path.is_file() else None

    def _store(self, mkey: int, name: str, content: bytes, fetch_update: dict[str, object]) -> None:
        if self._cache is None:
            return
        folder = self._cache / str(mkey)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        fetch_path = folder / FETCH_FILE
        fetch: dict[str, object] = json.loads(fetch_path.read_text()) if fetch_path.is_file() else {}
        documents = fetch.get("documents")
        if "documents" in fetch_update and isinstance(documents, dict):
            documents.update(fetch_update["documents"])  # type: ignore[arg-type]
        else:
            fetch.update(fetch_update)
        fetch_path.write_text(json.dumps(fetch, indent=1, sort_keys=True))

    def _get(self, url: str) -> bytes:
        """One GET with the polite gap, retried with backoff on transport errors and 5xx.

        The gap is net of any backoff already slept -- the rule ``openrouter.py``'s
        ``request_json`` uses. A backoff of ``b`` seconds has already spaced the requests
        by ``b``, so the next gap sleep is ``gap - b`` when that is positive and is skipped
        otherwise. Without a preceding backoff the full gap applies.
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
                response = self._http.get(url)
            except httpx.TransportError as error:
                status = type(error).__name__
            else:
                if response.is_success:
                    return response.content
                status = response.status_code
                if response.status_code not in _RETRY_STATUSES:
                    raise DocketError(f"{url} returned {status}")
            if attempt < self._max_attempts:
                backoff = self._backoff * 2 ** (attempt - 1)
                self._sleep(backoff)
                self._last_backoff_slept = backoff
        raise DocketError(f"{url} failed after {self._max_attempts} attempts; last status {status}")
```

Fix the `documents.update` typing without an ignore: narrow `fetch_update["documents"]` with `isinstance(..., dict)` before updating. The sleep expectations follow from the net-of-backoff rule above, and the code block is written with it: `test_requests_are_two_seconds_apart` expects `[2.0]` (one full gap before the second request, no backoff), and `test_server_error_is_retried_then_raised` with `max_attempts=3`, `backoff_seconds=1.0` and the default 2.0s gap expects `[1.0, 1.0, 2.0]`: attempt 1 takes no gap and backs off 1.0; attempt 2 sleeps a gap of 2.0-1.0=1.0 and backs off 2.0; attempt 3 sleeps a gap of 2.0-2.0=0, which is skipped, and does not back off.

`pyproject.toml`: add `"ntsb_probable_cause.docket"` to the `source_modules` list of the contract "Only the splitter constructs synthesis and verdict".

- [ ] **Step 4: Run the tests and the full check**

Run: `make check`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/errors.py src/ntsb_probable_cause/settings.py src/ntsb_probable_cause/sources.py src/ntsb_probable_cause/docket .env.example pyproject.toml tests/test_docket_client.py tests/test_sources_settings.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the docket client, its cache and polite rate (spec §4.2)"
```

---

### Task 6: The first listing fixture (spec §4.4; network, run locally, no key)

**Files:**
- Create: `scripts/make_docket_fixture.py` (the `listing` subcommand; `draw`, `document`, `handcheck` come in Task 16)
- Create: `tests/fixtures/docket/<case_id>/listing.html`, `tests/fixtures/docket/<case_id>/manifest.json`
- Modify: `tests/test_contamination.py`
- Test: `tests/test_docket_fixtures.py`

**Interfaces:**
- Produces: `scripts.make_docket_fixture.first_dev_400_case(processed: Path, *, seed: int = 20260918) -> tuple[str, int, str]` (case id, mkey, event date) and `write_listing_fixture(case_id, mkey, event_date, html, fetched_at, criterion) -> Path`; `manifest.json` shape:

```json
{
  "fixture": {"source": "https://data.ntsb.gov/Docket?ProjectID=<mkey>", "fetched_at": "...",
              "case_id": "...", "mkey": 0, "event_date": "YYYY-MM-DD", "criterion": "first draw"},
  "documents": []
}
```

The `documents` list is filled by Task 8's manifest (outcome only) and Task 16's `document` subcommand.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_docket_fixtures.py`:

```python
"""Docket fixtures: development cases only, listing pages as received (decision 0037)."""

import json
from datetime import date
from pathlib import Path

import pytest
from scripts.make_docket_fixture import first_dev_400_case, write_listing_fixture

from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.splits import Split, split_of

DOCKET_FIXTURES = Path("tests/fixtures/docket")


def docket_fixture_dirs() -> list[Path]:
    return sorted(p for p in DOCKET_FIXTURES.iterdir() if p.is_dir())


def test_at_least_one_listing_fixture_exists() -> None:
    assert docket_fixture_dirs(), "Task 6 commits the first listing fixture"


def test_every_docket_fixture_has_a_listing_and_a_manifest() -> None:
    for folder in docket_fixture_dirs():
        assert (folder / "listing.html").is_file(), folder
        manifest = json.loads((folder / "manifest.json").read_text())
        assert manifest["fixture"]["case_id"] == folder.name
        assert split_of(date.fromisoformat(manifest["fixture"]["event_date"])) is Split.DEV


def test_write_listing_fixture_refuses_a_held_out_case(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="2021"):
        write_listing_fixture(
            "X", 1, "2021-05-01", "<html/>", "2026-09-18T00:00:00+00:00", "test", root=tmp_path
        )


def test_write_listing_fixture_writes_the_page_as_received(tmp_path: Path) -> None:
    folder = write_listing_fixture(
        "X", 1, "2016-05-01", "<html>x</html>", "2026-09-18T00:00:00+00:00", "test", root=tmp_path
    )
    assert (folder / "listing.html").read_text() == "<html>x</html>"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["fixture"]["mkey"] == 1
    assert manifest["documents"] == []
```

Append to `tests/test_contamination.py`:

```python
def test_docket_fixtures_are_dev_400_cases_by_event_date(
    eval_ids: dict[str, dict[str, str]],
) -> None:
    """Decision 0037: every docket fixture is a development case drawn from dev-400."""
    dev = eval_ids["dev_400_ids"]
    for folder in sorted(p for p in Path("tests/fixtures/docket").iterdir() if p.is_dir()):
        manifest = json.loads((folder / "manifest.json").read_text())
        case_id = manifest["fixture"]["case_id"]
        assert case_id in dev, f"{case_id} is not in dev-400"
        assert _split(manifest["fixture"]["event_date"]) is Split.DEV
        assert _split(dev[case_id]) is Split.DEV
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docket_fixtures.py tests/test_contamination.py -q`
Expected: ImportError on `scripts.make_docket_fixture`.

- [ ] **Step 3: Write the script's `listing` subcommand**

Create `scripts/make_docket_fixture.py`:

```python
"""Create docket fixtures from development-split cases only (decision 0037).

Usage:
    uv run python -m scripts.make_docket_fixture listing [<case_id>]
        Fetch one dev-400 listing page (the seeded first case when no id is given) and
        commit it as received. Network; no key.

Later subcommands (Task 16): draw, document, handcheck.
"""

import argparse
import json
import random
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split, split_of

FIXTURES = Path("tests/fixtures/docket")
SEED = 20260918


def _cases(processed: Path, ids: tuple[str, ...]) -> dict[str, tuple[int, str]]:
    """Case id to (mkey, event date) for the given ids, from cases.parquet."""
    wanted = set(ids)
    found: dict[str, tuple[int, str]] = {}
    with pq.ParquetFile(processed / "cases.parquet") as parquet_file:
        for batch in parquet_file.iter_batches(columns=["ntsb_number", "mkey", "event_date"]):
            for number, mkey, event in zip(
                batch.column("ntsb_number").to_pylist(),
                batch.column("mkey").to_pylist(),
                batch.column("event_date").to_pylist(),
                strict=True,
            ):
                if number in wanted:
                    found[str(number)] = (int(mkey), str(event))
    return found


def first_dev_400_case(processed: Path, *, seed: int = SEED) -> tuple[str, int, str]:
    """The first dev-400 case in seeded order: id, mkey, event date."""
    ids = list(samples.sample_ids("dev-400"))
    random.Random(seed).shuffle(ids)  # noqa: S311 -- reproducible draw, not security
    cases = _cases(processed, tuple(ids[:1]))
    mkey, event = cases[ids[0]]
    return ids[0], mkey, event


def write_listing_fixture(  # noqa: PLR0913 -- one argument per manifest field.
    case_id: str,
    mkey: int,
    event_date: str,
    html: str,
    fetched_at: str,
    criterion: str,
    *,
    root: Path = FIXTURES,
) -> Path:
    """Write the listing page as received and a manifest; refuse anything outside development."""
    if split_of(date.fromisoformat(event_date)) is not Split.DEV:
        raise FixtureError(f"{case_id}: event date {event_date} is not in the development split")
    folder = root / case_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "listing.html").write_text(html)
    manifest = {
        "fixture": {
            "source": f"https://data.ntsb.gov/Docket?ProjectID={mkey}",
            "fetched_at": fetched_at,
            "case_id": case_id,
            "mkey": mkey,
            "event_date": event_date,
            "criterion": criterion,
        },
        "documents": [],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return folder


def _cmd_listing(args: argparse.Namespace, settings: Settings) -> int:
    processed = settings.data_dir / "processed"
    if args.case_id:
        cases = _cases(processed, (args.case_id,))
        if args.case_id not in samples.sample_ids("dev-400") or args.case_id not in cases:
            raise FixtureError(f"{args.case_id}: not a dev-400 case")
        case_id, (mkey, event) = args.case_id, cases[args.case_id]
    else:
        case_id, mkey, event = first_dev_400_case(processed)
    with DocketClient(settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request) as client:
        html = client.listing_html(mkey)
    folder = write_listing_fixture(
        case_id, mkey, event, html, datetime.now(UTC).isoformat(), args.criterion
    )
    print(f"wrote {folder}")
    return 0


def main(argv: list[str]) -> int:
    """Dispatch one subcommand."""
    parser = argparse.ArgumentParser(prog="make_docket_fixture")
    commands = parser.add_subparsers(dest="command", required=True)
    listing_p = commands.add_parser("listing")
    listing_p.add_argument("case_id", nargs="?")
    listing_p.add_argument("--criterion", default="first draw")
    args = parser.parse_args(argv)
    settings = Settings()
    try:
        if args.command == "listing":
            return _cmd_listing(args, settings)
    except FixtureError as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Fetch the first listing (network, run locally)**

Run: `uv run python -m scripts.make_docket_fixture listing`
Expected: `wrote tests/fixtures/docket/<case_id>`. Open the HTML and confirm it holds a table with `Docket Items:` and rows; if the page shape differs from the spike's regular expression (Task 7), the parser is written against this page, which is the point of committing it. Add the folder to the typos hook's exclude in `.pre-commit-config.yaml` (`^tests/fixtures/docket/.*\.html$`).

- [ ] **Step 5: Run the tests and the full check**

Run: `make check`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add scripts/make_docket_fixture.py tests/fixtures/docket tests/test_docket_fixtures.py tests/test_contamination.py .pre-commit-config.yaml docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the first docket listing fixture, a dev-400 page as received (decision 0037)"
```

---

### Task 7: The listing parser (spec §4.3)

**Files:**
- Create: `src/ntsb_probable_cause/docket/listing.py`
- Test: `tests/test_docket_listing.py`

**Interfaces:**
- Produces: `ListingEntry(index: int, title: str, pages: int, photos: int, doc_type: str, extension: str, href: str)` with `.is_photo_only() -> bool` and `.is_pdf() -> bool`; `Listing(mkey: int, declared_items: int | None, entries: tuple[ListingEntry, ...])`; `parse_listing(page: str, *, mkey: int) -> Listing` (raises `DocketError` when the declared count and the parsed rows disagree); `render_listing(listing: Listing) -> str`, one line per entry: `"3. <title> (<doc_type>, 12 pages, 4 photos)"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_docket_listing.py`:

```python
"""The listing parser against the saved real page (rule 2, decision 0037)."""

import json
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.listing import Listing, ListingEntry, parse_listing, render_listing
from ntsb_probable_cause.errors import DocketError

FIXTURES = Path("tests/fixtures/docket")


def _saved_pages() -> list[tuple[Path, int]]:
    pages = []
    for folder in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        manifest = json.loads((folder / "manifest.json").read_text())
        pages.append((folder / "listing.html", int(manifest["fixture"]["mkey"])))
    return pages


@pytest.mark.parametrize(("page", "mkey"), _saved_pages())
def test_saved_page_parses_and_the_item_count_agrees(page: Path, mkey: int) -> None:
    listing = parse_listing(page.read_text(), mkey=mkey)
    assert listing.mkey == mkey
    assert listing.declared_items == len(listing.entries)
    assert listing.entries, "a real docket has at least one document"
    assert [e.index for e in listing.entries] == list(range(1, len(listing.entries) + 1))
    for entry in listing.entries:
        assert entry.title
        assert entry.pages >= 0 and entry.photos >= 0


def test_doctored_page_with_a_missing_row_fails_loudly() -> None:
    page, mkey = _saved_pages()[0]
    text = page.read_text()
    first_row = text.index("<tr>", text.index("<tbody>") if "<tbody>" in text else 0)
    end = text.index("</tr>", first_row) + len("</tr>")
    with pytest.raises(DocketError, match="declared"):
        parse_listing(text[:first_row] + text[end:], mkey=mkey)


def test_photo_only_and_pdf_predicates() -> None:
    photos = ListingEntry(index=1, title="Photos", pages=3, photos=3, doc_type="Photo", extension="pdf", href="/x")
    report = ListingEntry(index=2, title="Report", pages=5, photos=1, doc_type="Report", extension="pdf", href="/x")
    sheet = ListingEntry(index=3, title="Data", pages=0, photos=0, doc_type="Data", extension="xlsx", href="/x")
    assert photos.is_photo_only() and not photos.is_pdf() is False
    assert not report.is_photo_only() and report.is_pdf()
    assert not sheet.is_pdf()


def test_render_listing_is_one_line_per_entry() -> None:
    listing = Listing(
        mkey=1,
        declared_items=1,
        entries=(ListingEntry(index=1, title="Weather Study", pages=12, photos=0, doc_type="Report", extension="pdf", href="/x"),),
    )
    assert render_listing(listing) == "1. Weather Study (Report, 12 pages, 0 photos)"
```

Fix the awkward double negative in `test_photo_only_and_pdf_predicates`: assert `photos.is_photo_only() is True` and `photos.is_pdf() is True` (a photo set is still a PDF; `is_photo_only` is what skips it).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docket_listing.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/ntsb_probable_cause/docket/listing.py`, starting from the spike's regular expression and adjusting it to the saved page:

```python
"""Parse the docket listing page into entries (spec §4.3). Structure from the saved real page."""

import html
import re

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.errors import DocketError

# From ../ntsb-spike/scripts/docket_shape_probe.py (ROW_RE, ITEMS_RE), checked against
# tests/fixtures/docket/*/listing.html. A change in the page fails the saved-page test.
_ROW = re.compile(
    r"<tr>\s*<td><b>(?P<idx>\d+)</b></td>\s*<td>(?P<title>.*?)</td>\s*"
    r"<td><b>(?P<pages>\d+)</b></td>\s*<td>(?P<photos>\d+)</td>\s*<td>(?P<dtype>.*?)</td>\s*"
    r"<td>\s*(?:<a target=\"_blank\" href=\"(?P<href>/Docket/Document/docBLOB[^\"]*)\">)?",
    re.S,
)
_ITEMS = re.compile(r"Docket Items:\s*(\d+)")
_TAGS = re.compile(r"<[^>]+>")


class ListingEntry(BaseModel):
    """One row of the listing: what the page says about a document, nothing more."""

    model_config = ConfigDict(frozen=True)
    index: int
    title: str
    pages: int
    photos: int
    doc_type: str
    extension: str
    href: str

    def is_photo_only(self) -> bool:
        """Every page is a photo: skipped, not read (spike's rule)."""
        return self.photos > 0 and self.photos >= self.pages

    def is_pdf(self) -> bool:
        """A downloadable PDF."""
        return self.extension == "pdf" and bool(self.href)


class Listing(BaseModel):
    """The docket's table of documents for one case."""

    model_config = ConfigDict(frozen=True)
    mkey: int
    declared_items: int | None
    entries: tuple[ListingEntry, ...]


def _extension(href: str) -> str:
    if not href:
        return ""
    ext = href.split("FileExtension=")[-1].split("&")[0].strip(".").lower()
    return ext or href.rsplit(".", 1)[-1].lower()


def parse_listing(page: str, *, mkey: int) -> Listing:
    """Parse the page; raise ``DocketError`` if its declared count disagrees with the rows."""
    match = _ITEMS.search(page)
    declared = int(match.group(1)) if match else None
    entries = []
    for row in _ROW.finditer(page):
        href = html.unescape(row.group("href") or "")
        entries.append(
            ListingEntry(
                index=int(row.group("idx")),
                title=html.unescape(_TAGS.sub("", row.group("title"))).strip(),
                pages=int(row.group("pages")),
                photos=int(row.group("photos")),
                doc_type=html.unescape(_TAGS.sub("", row.group("dtype"))).strip(),
                extension=_extension(href),
                href=href,
            )
        )
    if declared is not None and declared != len(entries):
        raise DocketError(
            f"docket {mkey}: page declared {declared} items, parsed {len(entries)} rows"
        )
    return Listing(mkey=mkey, declared_items=declared, entries=tuple(entries))


def render_listing(listing: Listing) -> str:
    """The listing as evidence text: one line per document, from the page's own columns."""
    return "\n".join(
        f"{e.index}. {e.title} ({e.doc_type}, {e.pages} pages, {e.photos} photos)"
        for e in listing.entries
    )
```

If the saved page's rows differ from `_ROW` (a class attribute on `<tr>`, a different link target), change the pattern to match the page, never the page to match the pattern, and log the difference in Deviations.

- [ ] **Step 4: Run the tests and the full check**

Run: `make check`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/docket/listing.py tests/test_docket_listing.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the listing parser against the saved real page (spec §4.3)"
```

---

### Task 8: Extraction, classification, the type classifier, and the manifest (spec §5, §7.2)

**Files:**
- Modify: `pyproject.toml` (`pypdf`), `uv.lock`
- Create: `src/ntsb_probable_cause/docket/extract.py`, `classify.py`, `manifest.py`
- Test: `tests/test_docket_extract.py`, `tests/test_docket_classify.py`, `tests/test_docket_manifest.py`

**Interfaces:**
- `extract.PAGE_MARKER = "[page {n} of {total}]"`; `extract.ExtractedDocument(chars_by_page: tuple[int, ...], text: str)`; `extract.extract_pdf(data: bytes) -> ExtractedDocument` (a page that fails to extract counts 0 characters; a file that is not a PDF raises `DocketError`).
- `classify.SCAN_PAGE_MAX_CHARS = 50`, `classify.BORN_DIGITAL_MIN_CHARS_PER_PAGE = 300`; `classify.Kind = Literal["born-digital", "scan", "partial"]`; `classify.classify_pages(chars_by_page: Sequence[int]) -> Kind`; `classify.readable_pages(chars_by_page) -> int`; `classify.estimated_tokens(chars: int) -> int` (`chars // 4`); `classify.CATEGORIES: tuple[tuple[str, str], ...]` (name, pattern), first match wins, `party_submission` first; `classify.document_category(title: str, doc_type: str) -> str` (`"other"` when nothing matches).
- `manifest.Status = Literal["read", "unreadable: scan", "unreadable: not a pdf", "skipped: photo-only", "fetch failed", "denied: write-up"]`; `manifest.DocumentRecord(entry: ListingEntry, category: str, status: Status, pages: int, readable_pages: int, estimated_tokens: int, kind: Kind | None)`; `manifest.Docket(mkey: int, listing: Listing, documents: tuple[DocumentRecord, ...], texts: dict[int, str])` (`texts` holds page-marked text for `status == "read"` only); `manifest.read_docket(client: DocketClient, mkey: int, *, denied: Callable[[str], bool] = lambda _c: False) -> Docket`.

- [ ] **Step 1: Add the dependency**

Run: `uv add pypdf` then `uv lock`.
Expected: `pypdf` in `[project].dependencies`, lock updated. Record the version in Deviations if it is not `>=6`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_docket_classify.py` (pure functions; no fixtures needed):

```python
"""Readable / scan / partial by characters per page (spec §5.2), and the title classifier (§7.2)."""

import pytest

from ntsb_probable_cause.docket.classify import (
    BORN_DIGITAL_MIN_CHARS_PER_PAGE,
    SCAN_PAGE_MAX_CHARS,
    classify_pages,
    document_category,
    estimated_tokens,
    readable_pages,
)


def test_thresholds_are_the_spikes() -> None:
    assert (SCAN_PAGE_MAX_CHARS, BORN_DIGITAL_MIN_CHARS_PER_PAGE) == (50, 300)


def test_born_digital_scan_and_partial() -> None:
    assert classify_pages([1200, 900, 400]) == "born-digital"
    assert classify_pages([0, 12, 3]) == "scan"
    assert classify_pages([600, 0, 0, 0]) == "partial"
    assert classify_pages([]) == "scan"


def test_readable_pages_counts_pages_over_the_scan_threshold() -> None:
    assert readable_pages([600, 0, 51, 50]) == 2


def test_estimated_tokens_is_characters_over_four() -> None:
    assert estimated_tokens(4001) == 1000


@pytest.mark.parametrize(
    ("title", "doc_type", "category"),
    [
        ("Party Submission - Lycoming Engines", "Submission", "party_submission"),
        ("Pilot/Operator Aircraft Accident Report 6120.1", "Form", "pilot_form_6120"),
        ("Weather Study Report", "Report", "weather"),
        ("MAINTENANCE RECORDS -- ENGINE", "Records", "maintenance_records"),
        ("Medical Factual Report", "Report", "medical_tox"),
        ("Powerplant Examination Report", "Report", "exam_site"),
        ("Record of Conversation - witness", "ROC", "conversation_statement"),
        ("ATC Transcript", "Transcript", "atc_radar_data"),
        ("Photographs", "Photos", "photos"),
        ("Something unusual", "", "other"),
    ],
)
def test_document_category_by_title(title: str, doc_type: str, category: str) -> None:
    assert document_category(title, doc_type) == category
```

Create `tests/test_docket_extract.py`. Real PDFs come only in Task 16, so this task tests the extractor through the manifest with a fake client whose "PDF" bytes are built by `pypdf` itself in the test (a writer producing a one-page PDF with a text object is not a fixture, it is a unit test of our wrapper around the library; no docket shape is claimed):

```python
"""Page-marked extraction (spec §5.1)."""

import io

import pytest
from pypdf import PdfWriter

from ntsb_probable_cause.docket.extract import PAGE_MARKER, extract_pdf
from ntsb_probable_cause.errors import DocketError


def _blank_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_blank_pages_extract_to_zero_characters_with_markers() -> None:
    result = extract_pdf(_blank_pdf(2))
    assert result.chars_by_page == (0, 0)
    assert result.text == "[page 1 of 2]\n\n[page 2 of 2]\n"


def test_marker_format_is_stable() -> None:
    assert PAGE_MARKER.format(n=4, total=22) == "[page 4 of 22]"


def test_not_a_pdf_raises() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        extract_pdf(b"<html>not a pdf</html>")
```

Create `tests/test_docket_manifest.py`:

```python
"""read_docket: every document gets a status; text is kept only for read documents (spec §5.3)."""

import io
import json
from pathlib import Path

import httpx
import respx
from pypdf import PdfWriter

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.docket.manifest import read_docket

FIXTURES = Path("tests/fixtures/docket")


def _first_fixture() -> tuple[Path, int]:
    folder = sorted(p for p in FIXTURES.iterdir() if p.is_dir())[0]
    return folder, int(json.loads((folder / "manifest.json").read_text())["fixture"]["mkey"])


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_every_entry_gets_a_status_and_scans_keep_no_text(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    listing = parse_listing(page, mkey=mkey)
    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    for entry in listing.entries:
        if entry.href:
            respx_mock.get(sources.docket_document_url(entry.href)).mock(
                return_value=httpx.Response(200, content=_blank_pdf())
            )
    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey)
    assert len(docket.documents) == len(listing.entries)
    for record in docket.documents:
        if record.entry.is_photo_only():
            assert record.status == "skipped: photo-only"
        elif not record.entry.is_pdf():
            assert record.status == "unreadable: not a pdf"
        else:
            assert record.status == "unreadable: scan"  # a blank page is a scan
            assert record.kind == "scan"
            assert record.readable_pages == 0
    assert docket.texts == {}


def test_fetch_failure_is_a_status_not_an_exception(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    respx_mock.get(url__startswith=sources.DOCKET_BASE_URL + "/Docket/Document").mock(
        return_value=httpx.Response(404)
    )
    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey)
    assert {r.status for r in docket.documents if r.entry.is_pdf() and not r.entry.is_photo_only()} == {"fetch failed"}


def test_denied_category_is_never_fetched(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    route = respx_mock.get(url__startswith=sources.DOCKET_BASE_URL + "/Docket/Document").mock(
        return_value=httpx.Response(200, content=_blank_pdf())
    )
    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey, denied=lambda _category: True)
    assert all(r.status in {"denied: write-up", "skipped: photo-only", "unreadable: not a pdf"} for r in docket.documents)
    assert route.call_count == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docket_classify.py tests/test_docket_extract.py tests/test_docket_manifest.py -q`
Expected: ImportError.

- [ ] **Step 4: Implement**

`docket/extract.py`:

```python
"""Text per page with page markers (spec §5.1)."""

import io

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ntsb_probable_cause.errors import DocketError

PAGE_MARKER = "[page {n} of {total}]"


class ExtractedDocument(BaseModel):
    """Characters per page, and the page-marked text."""

    model_config = ConfigDict(frozen=True)
    chars_by_page: tuple[int, ...]
    text: str


def extract_pdf(data: bytes) -> ExtractedDocument:
    """Extract every page; a page that fails counts 0 characters; a non-PDF raises."""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = list(reader.pages)
    except (PyPdfError, ValueError, TypeError) as error:
        raise DocketError(f"not a PDF: {error}") from error
    total = len(pages)
    counts: list[int] = []
    parts: list[str] = []
    for n, page in enumerate(pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001 -- a broken page is unreadable, not fatal
            text = ""
        counts.append(len(text))
        parts.append(PAGE_MARKER.format(n=n, total=total) + "\n" + text + "\n")
    return ExtractedDocument(chars_by_page=tuple(counts), text="".join(parts))
```

`docket/classify.py`:

```python
"""Readable, scanned or partial by characters per page (spec §5.2); document type by title (§7.2)."""

import re
from collections.abc import Sequence
from typing import Literal

# Thresholds from the spike's session A9 (../ntsb-spike/scripts/a9_pdf_extract.py), carried
# over so the eras compare (decision 0040 item 2); the characters-per-page distribution of
# dev-400 is published in docs/results/s2-shape-dev.txt (spec §10, first row).
SCAN_PAGE_MAX_CHARS = 50
BORN_DIGITAL_MIN_CHARS_PER_PAGE = 300

Kind = Literal["born-digital", "scan", "partial"]

# Title categories, first match wins (../ntsb-spike/scripts/docket_shape_probe.py CATEGORIES,
# plus party_submission). A judgement, not an NTSB taxonomy; the error rate is measured by
# Andy's 60-title hand-check (decision 0039 item 3).
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("party_submission", r"party submission|submission"),
    ("pilot_form_6120", r"6120|pilot/operator|pilot operator|pilot.s aircraft accident|operator.s aircraft accident"),
    ("photos", r"photo|image|picture|video still"),
    ("weather", r"weather|metar|meteorolog|forecast|sigmet|airmet|carburetor icing"),
    ("maintenance_records", r"maintenance|logbook|log book|engine log|aircraft log|airframe log|work order|invoice|annual inspection"),
    ("medical_tox", r"autopsy|toxicolog|medical|pathology|coroner|medical examiner"),
    ("specialist_factual", r"factual report|specialist|group chair|laboratory|metallurg|performance|study|recorded flight data|engine data monitor"),
    ("exam_site", r"exam|wreckage|teardown|site|inspection|memorandum for record"),
    ("conversation_statement", r"record of conversation|conversation|\broc\b|interview|statement|witness|correspondence|email"),
    ("atc_radar_data", r"\batc\b|air traffic|radar|ads-b|track|audio|transcript|video|tower|gps|recorder|csv|data"),
    ("manuals_reference", r"manual|\bpoh\b|handbook|excerpt|specification|airport information|chart|map|advisory"),
)
_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in CATEGORIES)


def classify_pages(chars_by_page: Sequence[int]) -> Kind:
    """Born-digital over 300 characters a page on average, scan under 50, else partial."""
    if not chars_by_page:
        return "scan"
    per_page = sum(chars_by_page) / len(chars_by_page)
    if per_page > BORN_DIGITAL_MIN_CHARS_PER_PAGE:
        return "born-digital"
    return "scan" if per_page < SCAN_PAGE_MAX_CHARS else "partial"


def readable_pages(chars_by_page: Sequence[int]) -> int:
    """Pages with more than the scan threshold of characters."""
    return sum(1 for c in chars_by_page if c > SCAN_PAGE_MAX_CHARS)


def estimated_tokens(chars: int) -> int:
    """The spike's estimate: one token per four characters."""
    return chars // 4


def document_category(title: str, doc_type: str) -> str:
    """The first category whose pattern matches the title or the page's type column."""
    text = f"{title} {doc_type}".lower()
    for name, pattern in _COMPILED:
        if pattern.search(text):
            return name
    return "other"
```

Note "Weather Study Report" must be `weather`, not `specialist_factual` (`study`): the order above puts `weather` before `specialist_factual`, as the spike's did. "Powerplant Examination Report" hits `exam_site` before `specialist_factual`? `specialist_factual` is earlier and matches "factual report" only; "Examination Report" does not contain "factual report", so `exam_site` wins. Check each parametrised title against the order and adjust the order, not the tests, if one misfires; log it.

`docket/manifest.py`:

```python
"""The per-case manifest: what was read, what could not be, and why (spec §5.3)."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.docket.classify import (
    Kind,
    classify_pages,
    document_category,
    estimated_tokens,
    readable_pages,
)
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.extract import extract_pdf
from ntsb_probable_cause.docket.listing import Listing, ListingEntry, parse_listing
from ntsb_probable_cause.errors import DocketError

Status = Literal[
    "read",
    "unreadable: scan",
    "unreadable: not a pdf",
    "skipped: photo-only",
    "fetch failed",
    "denied: write-up",
]


class DocumentRecord(BaseModel):
    """One document's outcome: never its text."""

    model_config = ConfigDict(frozen=True)
    entry: ListingEntry
    category: str
    status: Status
    pages: int
    readable_pages: int
    estimated_tokens: int
    kind: Kind | None


class Docket(BaseModel):
    """A case's listing, every document's record, and the text of the readable ones."""

    model_config = ConfigDict(frozen=True)
    mkey: int
    listing: Listing
    documents: tuple[DocumentRecord, ...]
    texts: dict[int, str]

    def record(self, index: int) -> DocumentRecord:
        """The record for a listing index."""
        return next(r for r in self.documents if r.entry.index == index)


def _record(entry: ListingEntry, category: str, status: Status, **extra: object) -> DocumentRecord:
    fields = {"pages": entry.pages, "readable_pages": 0, "estimated_tokens": 0, "kind": None}
    fields.update(extra)
    return DocumentRecord(entry=entry, category=category, status=status, **fields)  # type: ignore[arg-type]


def read_docket(
    client: DocketClient, mkey: int, *, denied: Callable[[str], bool] = lambda _c: False
) -> Docket:
    """Fetch the listing and every document; classify and extract; keep text for read ones."""
    listing = parse_listing(client.listing_html(mkey), mkey=mkey)
    records: list[DocumentRecord] = []
    texts: dict[int, str] = {}
    for entry in listing.entries:
        category = document_category(entry.title, entry.doc_type)
        if denied(category):
            records.append(_record(entry, category, "denied: write-up"))
        elif entry.is_photo_only():
            records.append(_record(entry, category, "skipped: photo-only"))
        elif not entry.is_pdf():
            records.append(_record(entry, category, "unreadable: not a pdf"))
        else:
            try:
                extracted = extract_pdf(client.document(mkey, entry.index, entry.href))
            except DocketError:
                records.append(_record(entry, category, "fetch failed"))
                continue
            kind = classify_pages(extracted.chars_by_page)
            readable = readable_pages(extracted.chars_by_page)
            tokens = estimated_tokens(sum(extracted.chars_by_page))
            if kind == "scan":
                records.append(_record(entry, category, "unreadable: scan", pages=len(extracted.chars_by_page), kind=kind))
            else:
                records.append(_record(entry, category, "read", pages=len(extracted.chars_by_page), readable_pages=readable, estimated_tokens=tokens, kind=kind))
                texts[entry.index] = extracted.text
    return Docket(mkey=mkey, listing=listing, documents=tuple(records), texts=texts)
```

Replace the `type: ignore` in `_record` with explicit keyword arguments (write `_record` with typed optional parameters `pages`, `readable_pages`, `estimated_tokens`, `kind` instead of `**extra`). "unreadable: photos" from the spec is folded into "skipped: photo-only" (log in Deviations: the listing already says which entries are photo sets; a PDF of photos with no text is a scan).

- [ ] **Step 5: Run the tests and the full check**

Run: `make check`
Expected: green. If `vulture` flags `Docket.record`, it is used in Task 10 (`attach_docket` calls `docket.record(index)`); add it to the vulture allow-list only if the task order leaves it unused at this commit, and remove the entry in Task 10.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/ntsb_probable_cause/docket tests/test_docket_classify.py tests/test_docket_extract.py tests/test_docket_manifest.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: extraction with page markers, classification, the type classifier, the manifest (spec §5, §7.2)"
```

---

### Task 9: The filter: deny-list, arm B's types and rank order (spec §7, §9.1)

**Files:**
- Create: `src/ntsb_probable_cause/docket/filter.py`
- Test: `tests/test_docket_filter.py`

**Interfaces:**
- Produces: `filter.DENY_LIST: frozenset[str] = frozenset()` (categories; filled only by hits, Task 16); `filter.ARM_B_TYPES: frozenset[str]` (initially every category except `photos`; re-set in Task 17 by the §10 rule); `filter.ARM_B_RANK: tuple[str, ...]` (initially listing order, expressed as the empty tuple meaning "by index"; re-set in Task 17 to the median-tokens order); `filter.Variant = Literal["published", "unfiltered", "no-submissions"]`; `filter.is_denied(category: str) -> bool`; `filter.arm_b_documents(docket: Docket, *, variant: Variant = "published") -> list[int]`: the listing indices of `read` documents arm B attaches, in rank order then index order; `unfiltered` admits every category in index order; `no-submissions` is `published` minus `party_submission` (0038 item 4).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_docket_filter.py`:

```python
"""Arm B's document filter: types, rank order, the deny-list (decisions 0022, 0038, 0039, 0043)."""

from ntsb_probable_cause.docket.filter import ARM_B_RANK, ARM_B_TYPES, DENY_LIST, arm_b_documents, is_denied
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord


def _entry(index: int, title: str) -> ListingEntry:
    return ListingEntry(index=index, title=title, pages=2, photos=0, doc_type="", extension="pdf", href="/x")


def _docket() -> Docket:
    rows = [
        (1, "Party Submission - engine maker", "party_submission", "read", 5000),
        (2, "Weather Study", "weather", "read", 800),
        (3, "Photographs", "photos", "skipped: photo-only", 0),
        (4, "Powerplant Examination", "exam_site", "read", 1200),
        (5, "Pilot Operator Report 6120", "pilot_form_6120", "unreadable: scan", 0),
    ]
    records = tuple(
        DocumentRecord(entry=_entry(i, t), category=c, status=s, pages=2, readable_pages=2 if s == "read" else 0, estimated_tokens=tok, kind="born-digital" if s == "read" else None)
        for i, t, c, s, tok in rows
    )
    listing = Listing(mkey=1, declared_items=5, entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=records, texts={1: "a", 2: "b", 4: "c"})


def test_deny_list_starts_empty_and_nothing_is_denied() -> None:
    assert DENY_LIST == frozenset()
    assert not is_denied("specialist_factual")


def test_published_filter_admits_read_documents_of_admitted_types_in_index_order_when_unranked() -> None:
    assert "photos" not in ARM_B_TYPES
    assert ARM_B_RANK == ()
    assert arm_b_documents(_docket()) == [1, 2, 4]


def test_unfiltered_admits_every_read_document() -> None:
    assert arm_b_documents(_docket(), variant="unfiltered") == [1, 2, 4]


def test_no_submissions_drops_party_submissions() -> None:
    assert arm_b_documents(_docket(), variant="no-submissions") == [2, 4]


def test_rank_order_sorts_by_type_then_index(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ntsb_probable_cause.docket import filter as filter_module

    monkeypatch.setattr(filter_module, "ARM_B_RANK", ("weather", "exam_site", "party_submission"))
    assert arm_b_documents(_docket()) == [2, 4, 1]
```

Type the monkeypatch parameter as `pytest.MonkeyPatch` and drop the ignore.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docket_filter.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
"""Arm B's fixed document filter and the deny-list (spec §7, §9; decisions 0022, 0039, 0043).

Every constant here is chosen on the development split and published before any held-out run.
"""

from typing import Literal

from ntsb_probable_cause.docket.classify import CATEGORIES
from ntsb_probable_cause.docket.manifest import Docket

Variant = Literal["published", "unfiltered", "no-submissions"]

# Title categories that carry the NTSB's case-level write-up. Starts empty and is filled only by
# tripwire hits on dev-400 (decision 0039 item 2); source: docs/results/s2-filter.txt.
DENY_LIST: frozenset[str] = frozenset()

# The types arm B attaches. Initial value: every category but photo sets, which hold no text.
# Re-set by the rule in spec §10 after the dev-400 runs; source: docs/results/s2-filter.txt.
ARM_B_TYPES: frozenset[str] = frozenset(name for name, _ in CATEGORIES if name != "photos") | {"other"}

# Rank order: types listed first are attached first (decision 0043). Empty means listing order.
# Re-set to the ascending median-tokens order measured on dev-400; source: s2-filter.txt.
ARM_B_RANK: tuple[str, ...] = ()


def is_denied(category: str) -> bool:
    """True if the category is on the deny-list."""
    return category in DENY_LIST


def arm_b_documents(docket: Docket, *, variant: Variant = "published") -> list[int]:
    """Listing indices of the read documents arm B attaches, in rank order then index order."""
    admitted = (
        {name for name, _ in CATEGORIES} | {"other"}
        if variant == "unfiltered"
        else ARM_B_TYPES - ({"party_submission"} if variant == "no-submissions" else set())
    )
    rank = {name: position for position, name in enumerate(ARM_B_RANK)}
    chosen = [
        r for r in docket.documents if r.status == "read" and r.category in admitted
    ]
    chosen.sort(key=lambda r: (rank.get(r.category, len(rank)), r.entry.index))
    return [r.entry.index for r in chosen]
```

- [ ] **Step 4: Run the tests and the full check, commit**

Run: `make check`
Expected: green.

```bash
git add src/ntsb_probable_cause/docket/filter.py tests/test_docket_filter.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the filter: deny-list, arm B types and rank order (spec §7, §9)"
```

---

### Task 10: The attach step, the two docket roles, and the boundary on documents (spec §6; decisions 0041, 0042, 0044)

**Files:**
- Create: `src/ntsb_probable_cause/docket/attach.py`
- Modify: `src/ntsb_probable_cause/fields.py`, `src/ntsb_probable_cause/records/evidence.py`, `src/ntsb_probable_cause/scoring/samples.py`
- Test: `tests/test_attach.py`, `tests/test_boundary.py`, `tests/test_records.py`, `tests/test_samples.py`

**Interfaces:**
- `fields.EvidenceRole.DOCKET_LISTING = "docket_listing"` (source `docket.listing`, a string) and `DOCKET_DOCUMENTS = "docket_documents"` (source `docket.documents[]`, a tuple of rendered documents).
- `Evidence.docket_listing: str | None = None`, `Evidence.docket_documents: tuple[str, ...] | None = None`.
- `attach.DOCKET_KEY = "docket"`; `attach.AttachResult(context: dict[str, object], attached: tuple[int, ...], not_available: tuple[str, ...], replacements: int)`; `attach.attach_docket(raw: Mapping[str, object], docket: Docket, *, documents: Sequence[int]) -> AttachResult`; `attach.render_document(record: DocumentRecord, text: str) -> str`; `attach.header(record: DocumentRecord) -> str`; `attach.amateur_built_replace(text: str, raw: Mapping[str, object]) -> tuple[str, int]`.
- `samples.masked_exclusions(day)` also excludes both docket roles; `samples.arm_exclusions("B")` excludes nothing.
- `not_available` entries read `"<index>: <status>"` for every document not attached and not `read`, e.g. `"5: unreadable: scan"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_attach.py`:

```python
"""attach_docket builds the case context; the split reads it unchanged (decisions 0041, 0042, 0044)."""

import copy
from collections.abc import Mapping

import pytest

from ntsb_probable_cause.docket.attach import DOCKET_KEY, amateur_built_replace, attach_docket, header
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole, factual_narrative
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.split import split_record


def _entry(index: int, title: str, pages: int = 3) -> ListingEntry:
    return ListingEntry(index=index, title=title, pages=pages, photos=0, doc_type="Report", extension="pdf", href="/x")


def _docket(texts: Mapping[int, str]) -> Docket:
    titles = {1: "Powerplant Examination Report", 2: "Party Submission - engine manufacturer", 3: "Pilot Operator Report 6120"}
    records = []
    for index, title in titles.items():
        read = index in texts
        records.append(
            DocumentRecord(
                entry=_entry(index, title),
                category={1: "exam_site", 2: "party_submission", 3: "pilot_form_6120"}[index],
                status="read" if read else "unreadable: scan",
                pages=3,
                readable_pages=3 if read else 0,
                estimated_tokens=len(texts.get(index, "")) // 4,
                kind="born-digital" if read else "scan",
            )
        )
    listing = Listing(mkey=1, declared_items=3, entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=tuple(records), texts=dict(texts))


def test_context_carries_listing_and_selected_documents_under_the_docket_key(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = record_fixtures[0]
    docket = _docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n", 2: "[page 1 of 3]\nWe submit.\n"})
    result = attach_docket(raw, docket, documents=[2])
    docket_part = result.context[DOCKET_KEY]
    assert isinstance(docket_part, dict)
    assert "1. Powerplant Examination Report" in str(docket_part["listing"])
    assert len(docket_part["documents"]) == 1
    assert "We submit." in docket_part["documents"][0]
    assert "crankshaft" not in docket_part["documents"][0]
    assert result.attached == (2,)
    assert result.not_available == ("3: unreadable: scan",)
    assert raw.get(DOCKET_KEY) is None, "the raw record is not mutated"


def test_split_reads_the_docket_roles_and_the_payload_renders_them(
    record_fixtures: list[dict[str, object]],
) -> None:
    docket = _docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    context = attach_docket(record_fixtures[0], docket, documents=[1]).context
    evidence, _, _ = split_record(context)
    assert evidence.docket_listing is not None
    assert evidence.docket_documents is not None and len(evidence.docket_documents) == 1
    payload = Payload.from_evidence(evidence)
    assert "crankshaft" in payload.text
    assert "[page 1 of 3]" in payload.text


def test_excluding_the_documents_role_keeps_the_listing(record_fixtures: list[dict[str, object]]) -> None:
    docket = _docket({1: "[page 1 of 3]\nx\n"})
    context = attach_docket(record_fixtures[0], docket, documents=[1]).context
    evidence, _, _ = split_record(context, exclude=frozenset({EvidenceRole.DOCKET_DOCUMENTS}))
    fields_sent = Payload.from_evidence(evidence).fields()
    assert "docket_listing" in fields_sent and "docket_documents" not in fields_sent


def test_document_holding_a_withheld_sentence_fails_the_split_closed(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0038 item 3, 0039: the tripwire runs on every document."""
    raw = next(r for r in record_fixtures if factual_narrative(r))
    narrative = factual_narrative(raw) or ""
    docket = _docket({1: f"[page 1 of 3]\nAs the NTSB found: {narrative}\n"})
    context = attach_docket(raw, docket, documents=[1]).context
    with pytest.raises(LeakageError, match="docket_documents"):
        split_record(context)


def test_header_names_type_pages_and_author_role() -> None:
    record = _docket({2: "x"}).record(2)
    assert header(record) == "Party submission, 3 pages, submitted by a party to the investigation."
    exam = _docket({1: "x"}).record(1)
    assert header(exam) == "Examination or site report, 3 pages, NTSB or its investigators."


def test_amateur_built_make_and_model_are_replaced_in_text_and_counted(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "Invented Builder"
    aircrafts[0]["aircraftModel"] = "RV-7X"
    text, count = amateur_built_replace("The INVENTED BUILDER rv-7x was built by Invented Builder.", raw)
    assert text == "The Amateur-built Amateur-built was built by Amateur-built."
    assert count == 3
    docket = _docket({1: "[page 1 of 3]\nInvented Builder logbook.\n"})
    result = attach_docket(raw, docket, documents=[1])
    assert "Invented Builder" not in str(result.context[DOCKET_KEY])
    assert result.replacements == 1


def test_no_replacement_on_a_factory_built_aircraft(record_fixtures: list[dict[str, object]]) -> None:
    raw = record_fixtures[0]
    make = raw["aircrafts"][0]["aircraftMake"]  # type: ignore[index]
    text, count = amateur_built_replace(f"A {make} aircraft.", raw)
    assert count == 0 and make in text
```

Append to `tests/test_boundary.py`:

```python
from ntsb_probable_cause.docket.attach import attach_docket
from tests.test_attach import _docket as _small_docket


def test_boundary_holds_on_a_case_context_with_documents(
    record_fixtures: list[dict[str, object]],
) -> None:
    docket = _small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    context = attach_docket(record_fixtures[0], docket, documents=[1]).context
    assert_boundary_holds(context)


def test_synthesis_document_never_reaches_the_payload(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Roadmap §9 / spec §12: a docket document holding withheld text is stopped whatever its title."""
    raw = next(r for r in record_fixtures if fields.probable_cause(r))
    cause = fields.probable_cause(raw) or ""
    docket = _small_docket({1: f"[page 1 of 3]\nFactual Report. {cause}\n"})
    context = attach_docket(raw, docket, documents=[1]).context
    with pytest.raises(LeakageError):
        split_record(context)
    with pytest.raises(AssertionError, match=r"^tripwire"):
        assert_boundary_holds(context, lambda r: split_record(r, min_sentence_chars=10**9))
```

The second `pytest.raises` disables the sentence and whole-text needles by an impossible minimum length, so only the code check and the boundary's own tripwire block remain; if `assert_boundary_holds` then passes because the code check catches nothing, change the mutated text to omit codes and assert via `find_leaks` directly. Import `LeakageError` in `tests/test_boundary.py`. Move `_docket` from `tests/test_attach.py` into `tests/boundary.py` as `small_docket` if importing between test modules is refused by the linter.

Append to `tests/test_samples.py`:

```python
def test_masked_condition_treats_the_docket_as_absent() -> None:
    excluded = masked_exclusions(1)
    assert EvidenceRole.DOCKET_LISTING in excluded and EvidenceRole.DOCKET_DOCUMENTS in excluded
    assert EvidenceRole.DOCKET_DOCUMENTS in masked_exclusions(400)


def test_arm_a_excludes_the_docket_and_arm_b_excludes_nothing() -> None:
    assert EvidenceRole.DOCKET_DOCUMENTS in arm_exclusions("A")
    assert arm_exclusions("B") == frozenset()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_attach.py tests/test_boundary.py tests/test_samples.py -q`
Expected: ImportError on `docket.attach`; `EvidenceRole.DOCKET_LISTING` missing.

- [ ] **Step 3: Add the roles and evidence fields**

`fields.py`: add to `EvidenceRole`:

```python
    DOCKET_LISTING = "docket_listing"
    DOCKET_DOCUMENTS = "docket_documents"
```

and to `EVIDENCE_FIELDS`:

```python
    # Decisions 0041, 0042: the docket subtree exists only in a case context built by
    # ``docket.attach.attach_docket``; a raw API record has no ``docket`` key, so both are None.
    EvidenceField(EvidenceRole.DOCKET_LISTING, ("docket.listing",), _text_at("docket.listing")),
    EvidenceField(
        EvidenceRole.DOCKET_DOCUMENTS, ("docket.documents[]",), _strings_at("docket.documents")
    ),
```

`records/evidence.py`: add `docket_listing: str | None = None` and `docket_documents: tuple[str, ...] | None = None`.

`scoring/samples.py`: `arm_exclusions(arm: Literal["A", "B", "ceiling"])` (unchanged body: only `A` excludes); `masked_exclusions` returns `frozenset(late | {EvidenceRole.PRELIM_NARRATIVE, EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS})` with a comment: the docket is absent in the masked condition until the recorder (S2.5) has arrival numbers (agency design §6.2).

- [ ] **Step 4: Write the attach step**

`docket/attach.py`:

```python
"""The one place docket text enters a record: the case context (decisions 0041, 0042, 0044)."""

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ntsb_probable_cause.docket.listing import render_listing
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.fields import AMATEUR_BUILT_LABEL
from ntsb_probable_cause.paths import resolve_path

DOCKET_KEY = "docket"

# Provenance header (decision 0038 item 2): a label for the type, then the page count, then
# the author's role the category implies. The agent is told what it reads, never that it is wrong.
_LABELS: Mapping[str, tuple[str, str]] = {
    "party_submission": ("Party submission", "submitted by a party to the investigation"),
    "pilot_form_6120": ("Pilot/operator accident report form", "written by the pilot or operator"),
    "photos": ("Photographs", "NTSB or its investigators"),
    "weather": ("Weather study or data", "NTSB or a weather service"),
    "maintenance_records": ("Maintenance records", "the aircraft's maintainers"),
    "medical_tox": ("Medical or toxicology report", "a medical examiner or laboratory"),
    "specialist_factual": ("Specialist factual report", "NTSB or its investigators"),
    "exam_site": ("Examination or site report", "NTSB or its investigators"),
    "conversation_statement": ("Statement or record of conversation", "a witness or party, recorded by an investigator"),
    "atc_radar_data": ("Air traffic, radar or recorded data", "the FAA or a data source"),
    "manuals_reference": ("Manual or reference excerpt", "the manufacturer or a reference source"),
    "other": ("Docket document", "author not given by the listing"),
}

_AMATEUR_BUILT_FLAG = "aircrafts[0].aircraftAmateurBuilt"
_MIN_REPLACE_LEN = 3


@dataclass(frozen=True)
class AttachResult:
    """The case context and what the attach step did to build it."""

    context: dict[str, object]
    attached: tuple[int, ...]
    not_available: tuple[str, ...]
    replacements: int


def header(record: DocumentRecord) -> str:
    """``Party submission, 22 pages, submitted by a party to the investigation.``"""
    label, role = _LABELS.get(record.category, _LABELS["other"])
    return f"{label}, {record.pages} pages, {role}."


def render_document(record: DocumentRecord, text: str) -> str:
    """The header line, then the page-marked text."""
    return f"{header(record)}\n{text}"


def amateur_built_replace(text: str, raw: Mapping[str, object]) -> tuple[str, int]:
    """Replace the recorded make and model of an amateur-built aircraft, counting replacements.

    Decision 0044: the strings are known from the record, so the replacement is mechanical; a
    variant spelling passes through, so the count is a floor.
    """
    flag = resolve_path(raw, _AMATEUR_BUILT_FLAG)
    if flag is False or flag is None:
        return text, 0
    count = 0
    for path in ("aircrafts[0].aircraftMake", "aircrafts[0].aircraftModel"):
        value = resolve_path(raw, path)
        if not isinstance(value, str) or len(value.strip()) < _MIN_REPLACE_LEN:
            continue
        pattern = re.compile(re.escape(value.strip()), re.IGNORECASE)
        text, n = pattern.subn(AMATEUR_BUILT_LABEL, text)
        count += n
    return text, count


def attach_docket(
    raw: Mapping[str, object], docket: Docket, *, documents: Sequence[int]
) -> AttachResult:
    """Build the case context: the record plus a ``docket`` subtree with the chosen documents.

    The raw record is copied, never mutated. Every document not attached is listed in
    ``not_available`` with its status when it could not have been read; a readable document
    left out by choice is not listed (the step record's ``arguments`` say what was chosen).
    """
    listing_text, replacements = amateur_built_replace(render_listing(docket.listing), raw)
    rendered: list[str] = []
    attached: list[int] = []
    for index in documents:
        record = docket.record(index)
        if record.status != "read":
            continue
        text, n = amateur_built_replace(render_document(record, docket.texts[index]), raw)
        replacements += n
        rendered.append(text)
        attached.append(index)
    not_available = tuple(
        f"{r.entry.index}: {r.status}" for r in docket.documents if r.status != "read"
    )
    context: dict[str, object] = copy.deepcopy(dict(raw))
    context[DOCKET_KEY] = {"listing": listing_text, "documents": rendered, "attached": attached}
    return AttachResult(context, tuple(attached), not_available, replacements)
```

`Docket.record(index)` from Task 8 is now used. The `attached` list inside the context is bookkeeping and is not an evidence path, so it never renders (guard layer 0 reads only declared paths).

- [ ] **Step 5: Run the tests and the full check**

Run: `make check`
Expected: green. `tests/test_records.py::test_evidence_schema_is_exactly_the_evidence_roles_plus_bookkeeping` passes because both the role and the field were added. `tests/test_fields.py` path checks pass: `docket.*` overlaps no withheld subtree.

- [ ] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/docket/attach.py src/ntsb_probable_cause/fields.py src/ntsb_probable_cause/records/evidence.py src/ntsb_probable_cause/scoring/samples.py tests/test_attach.py tests/test_boundary.py tests/test_samples.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the attach step and the two docket evidence roles; the boundary holds on documents (0041, 0042, 0044)"
```

---

### Task 11: Arm B in the records, the run spec and the command (spec §9.1, §11)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/records.py`, `src/ntsb_probable_cause/scoring/runner.py` (`RunSpec`, `spec_json`, `build_record`), `apps/eval/__main__.py` (`--arm B`, `--docket-filter`, `resolve_latest`)
- Test: `tests/test_records.py`, `tests/test_runner.py`, `tests/test_eval_app.py`

**Interfaces:**
- `RunSpec.arm: Literal["A", "B", "ceiling"]`; `RunSpec.docket_filter: Variant = "published"`; `spec_json` records `docket_filter`.
- `RunRecord.arm: Literal["A", "B", "ceiling"]`; `RunRecord.docket_filter: str = "published"`.
- `StepRecord.documents_attached: tuple[str, ...] = ()` (entries `"<index>: <category>, <estimated tokens> tokens"`); `StepRecord.documents_not_read: tuple[str, ...] = ()` (entries `"<index>: cap, <estimated tokens> tokens"`).
- `resolve_latest` skips a run whose `docket_filter != "published"`.
- CLI: `--arm {A,B,ceiling}`, `--docket-filter {published,unfiltered,no-submissions}` (default `published`; refused with any arm but `B`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_records.py`:

```python
def test_step_record_document_fields_default_empty(run_record: RunRecord) -> None:
    hypothesis = parse_hypothesis(GOOD, load_tables())
    step = StepRecord(
        case_id="X", step=0, arm="B", condition="full", day=None, tool="docket", arguments={"documents": [1, 2]},
        reason="", expected_effect="", returned_roles=(), not_available=("3: unreadable: scan",),
        payload_fingerprint="f", hypothesis=hypothesis, observed_effect="", stop_reason="answered",
        model="m", price_variant="batch", prompt_tokens=1, completion_tokens=1, cost_usd=0.0,
        cumulative_cost_usd=0.0, commit_sha="abc", dirty=False,
    )
    assert step.documents_attached == () and step.documents_not_read == ()
    assert run_record.docket_filter == "published"
```

(Import `GOOD`, `parse_hypothesis`, `load_tables`, `StepRecord` as the file's other tests do.)

Append to `tests/test_runner.py`:

```python
def test_spec_json_records_the_docket_filter() -> None:
    spec = RunSpec(sample="dev-400", arm="B", docket_filter="unfiltered")
    assert spec_json(spec, commit_sha="a", dirty=False, case_ids=[])["docket_filter"] == "unfiltered"
```

Append to `tests/test_eval_app.py`:

```python
def test_docket_filter_is_refused_with_any_arm_but_b(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["run", "--arm", "ceiling", "--sample", "dev-400", "--docket-filter", "unfiltered"])
    assert "docket-filter" in capsys.readouterr().err


def test_resolve_latest_skips_an_unfiltered_arm_b_run(tmp_path: Path) -> None:
    _write_run(tmp_path, "20260101T000000-abc-dev-400-B", finished=datetime(2026, 1, 1, tzinfo=UTC))
    later = tmp_path / "20260102T000000-abc-dev-400-B"
    record = RunRecord(**{**_RUN_KWARGS, "arm": "B", "docket_filter": "unfiltered"}, run_id=later.name, started=datetime(2026, 1, 2, tzinfo=UTC), finished=datetime(2026, 1, 2, tzinfo=UTC))
    write_jsonl(later / "run.jsonl", [record])
    assert resolve_latest(tmp_path, "B", "dev-400") == "20260101T000000-abc-dev-400-B"
```

`_write_run` uses `_RUN_KWARGS["arm"] == "ceiling"`; write the first run with `arm="B"` by the same pattern as the second (both explicit), so the test compares two arm-B runs.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_records.py tests/test_runner.py tests/test_eval_app.py -q`
Expected: validation errors on `arm="B"`, missing `docket_filter`.

- [ ] **Step 3: Implement**

`records.py`: `RunRecord.arm: Literal["A", "B", "ceiling"]`, add `docket_filter: str = "published"` after `includes`; `StepRecord` gains `documents_attached: tuple[str, ...] = ()` and `documents_not_read: tuple[str, ...] = ()` after `not_available`.

`runner.py`: `RunSpec.arm: Literal["A", "B", "ceiling"]`, add `docket_filter: Variant = "published"` (import `Variant` from `docket.filter`); `spec_json` adds `"docket_filter": spec.docket_filter` after `"include_case_number"`; `build_record` passes `docket_filter=spec.docket_filter`.

`apps/eval/__main__.py`: `run_p.add_argument("--arm", choices=("A", "B", "ceiling"), required=True)`; `run_p.add_argument("--docket-filter", choices=("published", "unfiltered", "no-submissions"), default="published")`; in `_cmd_run`, before building the spec: `if args.docket_filter != "published" and args.arm != "B": raise SystemExit("--docket-filter applies to --arm B only")`; pass `docket_filter=args.docket_filter` to `RunSpec`. In `resolve_latest`, after the exclusions check: `if record.docket_filter != "published": continue`.

- [ ] **Step 4: Run the tests and the full check, commit**

Run: `make check`
Expected: green.

```bash
git add src/ntsb_probable_cause/scoring/records.py src/ntsb_probable_cause/scoring/runner.py apps/eval/__main__.py tests/test_records.py tests/test_runner.py tests/test_eval_app.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: arm B and the docket filter variant in records, spec and command (spec §9.1)"
```

---

### Task 12: Arm B in the runner: the docket reader, the drop rule, the step record, the report (spec §9, decision 0043)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`DocketReader`, `Prepared`, `prepare_case`, `_CaseContext`, `_step`, `Runner.__init__`, both answering paths)
- Modify: `src/ntsb_probable_cause/scoring/report.py` (`cap_summary`), `apps/eval/__main__.py` (the docket reader in `_cmd_run`, `report`)
- Modify: `Makefile` (`armb`)
- Test: `tests/test_runner.py`, `tests/test_report.py`, `tests/test_eval_app.py`

**Interfaces:**
- `runner.DocketReader` Protocol: `read(mkey: int) -> Docket`.
- `runner.CachedDocketReader(client: DocketClient)` implements it via `manifest.read_docket(client, mkey, denied=filter.is_denied)`.
- `runner.Prepared(payload: Payload, system: str, verdict: Verdict, evidence: Evidence, attached: tuple[int, ...], not_read: tuple[str, ...], not_available: tuple[str, ...], documents_attached: tuple[str, ...])`.
- `runner.prepare_case(raw, spec, tables, docket: Docket | None) -> Prepared`; `case_payload` becomes `prepare_case(raw, spec, tables, None)` unpacked to its old 4-tuple, kept for existing callers.
- `Runner(..., docket: DocketReader | None = None)`; arm B with `docket=None` raises `ConfigurationError` before any call.
- `report.cap_summary(results: Sequence[CaseResult]) -> str`: `"cap: N of M cases hit the cap; K documents not read (fatal a cases/b documents, non-fatal c/d)"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runner.py`:

```python
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.scoring.runner import CachedDocketReader, prepare_case
from tests.test_attach import _docket as small_docket


class FakeDocketReader:
    def __init__(self, docket: Docket) -> None:
        self.docket = docket
        self.reads: list[int] = []

    def read(self, mkey: int) -> Docket:
        self.reads.append(mkey)
        return self.docket


def test_arm_b_without_a_docket_reader_is_refused_before_any_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(sample="dev-400", arm="B", sync=True, price_variant="standard", expected_cost_per_case_usd=0.001)
    with pytest.raises(ConfigurationError, match="docket"):
        runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert client.payloads == []


def test_arm_b_attaches_the_filtered_documents_and_records_them(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n", 2: "[page 1 of 3]\nWe submit.\n"})
    reader = FakeDocketReader(docket)
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(sample="dev-400", arm="B", sync=True, price_variant="standard", expected_cost_per_case_usd=0.001)
    run = runner(tmp_path, client, docket=reader).run(spec, record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    (step,) = case.steps
    assert step.tool == "docket"
    assert step.arguments == {"documents": [1, 2], "docket_filter": "published"}
    assert step.documents_attached == ("1: exam_site, 10 tokens", "2: party_submission, 6 tokens")
    assert step.not_available == ("3: unreadable: scan",)
    assert "crankshaft" in client.payloads[0].text
    assert reader.reads == [record_fixtures[0]["mKey"]]


def test_arm_b_drops_whole_documents_in_rank_order_at_the_cap(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Decision 0043: stop before the first document that would break the cap; record it."""
    big = "[page 1 of 3]\n" + "x" * 40_000 + "\n"
    docket = small_docket({1: "[page 1 of 3]\nsmall\n", 2: big})
    client = RecordingFakeClient([GOOD, REFINE])
    # Sonnet 5 standard (M1): the code tables make the base prompt about 8,500 tokens, so the
    # base estimate is about $0.017 plus the $0.02 output reserve. A 5-cent cap admits the small
    # document and refuses the 10,003-token one ($0.02 more). If the base prompt alone is over
    # the cap the case fails "cap" before any document, which is the existing behaviour.
    spec = RunSpec(sample="dev-400", arm="B", sync=True, price_variant="standard", model="anthropic/claude-sonnet-5", cap_usd=0.05, expected_cost_per_case_usd=0.001)
    run = runner(tmp_path, client, docket=FakeDocketReader(docket)).run(spec, record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    (step,) = case.steps
    assert step.documents_attached == ("1: exam_site, 5 tokens",)
    assert step.documents_not_read == ("2: cap, 10003 tokens",)
    assert "xxxx" not in client.payloads[0].text


def test_arm_b_no_submissions_variant_leaves_out_party_submissions(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    docket = small_docket({1: "[page 1 of 3]\na\n", 2: "[page 1 of 3]\nWe submit.\n"})
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(sample="dev-400", arm="B", docket_filter="no-submissions", sync=True, price_variant="standard", expected_cost_per_case_usd=0.001)
    runner(tmp_path, client, docket=FakeDocketReader(docket)).run(spec, record_fixtures[:1])
    assert "We submit." not in client.payloads[0].text


def test_ceiling_and_arm_a_never_read_the_docket(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    reader = FakeDocketReader(small_docket({1: "[page 1 of 3]\na\n"}))
    for arm in ("A", "ceiling"):
        client = RecordingFakeClient([GOOD, REFINE])
        spec = RunSpec(sample="dev-400", arm=arm, sync=True, price_variant="standard", expected_cost_per_case_usd=0.001)  # type: ignore[arg-type]
        runner(tmp_path, client, docket=reader).run(spec, record_fixtures[:1])
    assert reader.reads == []


def test_batch_arm_b_attaches_documents_too(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    fake = FakeBatchClient(handlers=[lambda bid, reqs: _status(bid, reqs, GOOD), lambda bid, reqs: _status(bid, reqs, REFINE)])
    runner(tmp_path, RecordingFakeClient([]), batch=fake, docket=FakeDocketReader(docket)).run(
        RunSpec(sample="dev-400", arm="B", sync=False, expected_cost_per_case_usd=0.001), record_fixtures[:1]
    )
    assert "crankshaft" in fake.submitted[0][0].payload.text
```

Update the `runner(...)` helper at the top of `tests/test_runner.py` to accept `docket: DocketReader | None = None` and pass it through. Type the `arm` loop with `Literal` instead of the ignore.

Append to `tests/test_report.py` (use the file's existing `CaseResult` builder; if it has none, build a minimal result with a step as `_write_judgeable_run` in `tests/test_eval_app.py` does):

```python
from ntsb_probable_cause.scoring.report import cap_summary


def test_cap_summary_counts_cases_and_documents_by_fatal() -> None:
    fatal_hit = _case("A", fatal=True, not_read=("2: cap, 9000 tokens", "3: cap, 500 tokens"))
    fatal_clear = _case("B", fatal=True)
    non_fatal_hit = _case("C", fatal=False, not_read=("1: cap, 100 tokens",))
    text = cap_summary([fatal_hit, fatal_clear, non_fatal_hit])
    assert text == "cap: 2 of 3 cases hit the cap; 3 documents not read (fatal 1 cases/2 documents, non-fatal 1/1)"
```

Write `_case(case_id, *, fatal, not_read=())` in `tests/test_report.py` returning a `CaseResult` with one `StepRecord` whose `documents_not_read=not_read`, `scores=None`, `failure=None`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_runner.py tests/test_report.py -q`
Expected: ImportError on `prepare_case`, `CachedDocketReader`, `cap_summary`.

- [ ] **Step 3: Implement the reader and `prepare_case`**

In `scoring/runner.py`, imports: `from ntsb_probable_cause.docket import filter as docket_filter`, `from ntsb_probable_cause.docket.attach import attach_docket`, `from ntsb_probable_cause.docket.client import DocketClient`, `from ntsb_probable_cause.docket.manifest import Docket, read_docket`.

```python
class DocketReader(Protocol):
    """Where arm B (and later the loop) gets a case's docket from."""

    def read(self, mkey: int) -> Docket:
        """The docket for a case's internal key."""
        ...


class CachedDocketReader:
    """The real reader: the client's cache, the deny-list applied (spec §7.1)."""

    def __init__(self, client: DocketClient) -> None:
        self._client = client

    def read(self, mkey: int) -> Docket:
        return read_docket(self._client, mkey, denied=docket_filter.is_denied)


@dataclass(frozen=True)
class Prepared:
    """Everything one case needs before its first call, and what the attach step did."""

    payload: Payload
    system: str
    verdict: Verdict
    evidence: Evidence
    attached: tuple[int, ...] = ()
    not_read: tuple[str, ...] = ()
    not_available: tuple[str, ...] = ()
    documents_attached: tuple[str, ...] = ()


def _system_text(raw: Mapping[str, object], spec: RunSpec, tables: CodeTables, case_id: str) -> str:
    case_number: str | None = None
    if spec.include_case_number:
        event = date.fromisoformat(str(raw["eventDate"])[:10])
        if _sample_split(spec.sample) is not Split.DEV or split_of(event) is not Split.DEV:
            raise LeakageError(f"{case_id}: the case number may be included on development cases only")
        case_number = case_id
    return f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables, case_number=case_number)}"


def _split_and_render(context: Mapping[str, object], spec: RunSpec) -> tuple[Evidence, Verdict, Payload]:
    evidence, _, verdict = split_record(context, exclude=spec.exclusions | arm_exclusions(spec.arm))
    return evidence, verdict, Payload.from_evidence(evidence)


def prepare_case(
    raw: Mapping[str, object], spec: RunSpec, tables: CodeTables, docket: Docket | None
) -> Prepared:
    """The only route to a payload. Arm B attaches documents whole, in rank order, up to the cap.

    Decision 0043: documents are added one at a time; the first that would take the case
    over the cap stops the loop, and it and every document after it are recorded as
    ``not read: cap`` with their estimated tokens. Every trial context goes through the split,
    so the tripwire runs on every document that is attached.
    """
    evidence, verdict, payload = _split_and_render(raw, spec)
    system = _system_text(raw, spec, tables, evidence.case_id)
    if spec.arm != "B":
        return Prepared(payload, system, verdict, evidence)
    if docket is None:
        raise ConfigurationError("arm B needs a docket reader")
    ordered = docket_filter.arm_b_documents(docket, variant=spec.docket_filter)
    attached: list[int] = []
    not_read: list[str] = []
    result = attach_docket(raw, docket, documents=attached)
    evidence, verdict, payload = _split_and_render(result.context, spec)
    for position, index in enumerate(ordered):
        trial = attach_docket(raw, docket, documents=[*attached, index])
        trial_evidence, trial_verdict, trial_payload = _split_and_render(trial.context, spec)
        if over_cap(trial_payload.text, system, spec):
            not_read.extend(
                f"{i}: cap, {docket.record(i).estimated_tokens} tokens" for i in ordered[position:]
            )
            break
        attached.append(index)
        result, evidence, verdict, payload = trial, trial_evidence, trial_verdict, trial_payload
    documents_attached = tuple(
        f"{i}: {docket.record(i).category}, {docket.record(i).estimated_tokens} tokens" for i in attached
    )
    return Prepared(
        payload, system, verdict, evidence, tuple(attached), tuple(not_read), result.not_available, documents_attached
    )


def case_payload(
    raw: Mapping[str, object], spec: RunSpec, tables: CodeTables
) -> tuple[Payload, str, Verdict, Evidence]:
    """The one-call arms' payload; kept for callers that predate arm B."""
    prepared = prepare_case(raw, spec, tables, None)
    return prepared.payload, prepared.system, prepared.verdict, prepared.evidence
```

Note the token figures in the tests: `estimated_tokens` is `chars // 4` of the test's document text (`len(text) // 4`), so `"1: exam_site, 10 tokens"` is `len("[page 1 of 3]\nThe crankshaft was intact.\n") // 4`; compute the exact values when the test is written and put those numbers in the assertions rather than the ones written above.

- [ ] **Step 4: Thread it through the runner**

- `Runner.__init__` gains `docket: DocketReader | None = None`, stored as `self._docket`.
- `_CaseContext` gains `prepared: Prepared` (replace the four separate fields with the one object, or add the three tuples `attached`, `not_read`, `not_available` and `documents_attached`; the smaller edit is to keep the four fields and add the tuples).
- A helper on `Runner`:

```python
    def _prepare(self, raw: Mapping[str, object], spec: RunSpec) -> Prepared:
        docket: Docket | None = None
        if spec.arm == "B":
            if self._docket is None:
                raise ConfigurationError("arm B needs a docket reader (--arm B reads the docket cache)")
            mkey = raw.get("mKey")
            if not isinstance(mkey, int):
                raise ConfigurationError(f"{raw.get('ntsbNumber')}: no mKey, so no docket")
            docket = self._docket.read(mkey)
        return prepare_case(raw, spec, self._tables, docket)
```

- `Runner.run`: the early `case_ids = [case_payload(...)[3].case_id ...]` line must not read dockets; replace it with `case_ids = [str(raw["ntsbNumber"]) for raw in raws]` (the split checks the id later anyway). Add, before the budget block, `if spec.arm == "B" and self._docket is None: raise ConfigurationError("arm B needs a docket reader")` so the refusal happens before any reservation.
- `_answer_case` and `_prepare_contexts`: call `self._prepare(raw, spec)` and build `_CaseContext` from it.
- `_step`: `tool="docket" if ctx.spec.arm == "B" else "none"`, `arguments={"documents": list(ctx.attached), "docket_filter": ctx.spec.docket_filter} if ctx.spec.arm == "B" else {}`, `not_available=ctx.not_available`, `documents_attached=ctx.documents_attached`, `documents_not_read=ctx.not_read`, `stop_reason` unchanged.

- [ ] **Step 5: The report and the command**

`report.py`:

```python
def cap_summary(results: Sequence[CaseResult]) -> str:
    """How much of the docket the result was measured on (decision 0043 item 3)."""

    def counts(rows: Sequence[CaseResult]) -> tuple[int, int]:
        hit = [r for r in rows if any(s.documents_not_read for s in r.steps)]
        dropped = sum(len(s.documents_not_read) for r in rows for s in r.steps)
        return len(hit), dropped

    cases_hit, docs = counts(results)
    fatal_hit, fatal_docs = counts([r for r in results if r.fatal])
    non_hit, non_docs = counts([r for r in results if not r.fatal])
    return (
        f"cap: {cases_hit} of {len(results)} cases hit the cap; {docs} documents not read "
        f"(fatal {fatal_hit} cases/{fatal_docs} documents, non-fatal {non_hit}/{non_docs})"
    )
```

In `_cmd_report`, after `summarise`, when `run_record.arm == "B"`: `text += "\n\n" + report.cap_summary(cases)`.

In `_cmd_run`, build the reader: `docket = CachedDocketReader(DocketClient(settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request)) if args.arm == "B" else None` and pass `docket=docket` to `Runner`. Close the client after the run (`with` block around the run).

`Makefile`:

```make
armb:
	uv run ntsb-eval run --arm B --sample dev-400
	uv run ntsb-eval run --arm B --sample dev-400 --docket-filter unfiltered
	uv run ntsb-eval run --arm B --sample dev-400 --docket-filter no-submissions
```

(The reports are generated from explicit run ids afterwards, never `--latest`, as S1 learned.)

- [ ] **Step 6: Run the tests and the full check**

Run: `make check`
Expected: green; coverage still over 90.

- [ ] **Step 7: Commit**

```bash
git add src/ntsb_probable_cause/scoring/runner.py src/ntsb_probable_cause/scoring/report.py apps/eval/__main__.py Makefile tests/test_runner.py tests/test_report.py tests/test_eval_app.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: arm B reads the docket and drops whole documents at the cap; the report counts it (0043)"
```

---

### Task 13: `docket_scan.py`: the `dev-400` fetch and the development shape file (spec §8.1)

**Files:**
- Create: `scripts/docket_scan.py`
- Modify: `Makefile` (`docket-scan`), `scripts/check_fixtures_redacted.py`, `.pre-commit-config.yaml`
- Test: `tests/test_docket_scan.py`, `tests/test_check_fixtures_redacted.py` (create if absent)

**Interfaces:**
- `scripts.docket_scan.ShapeState` accumulates counts only; `scripts.docket_scan.accumulate(state, docket: Docket, *, fatal: bool, raw: Mapping[str, object]) -> None`; `scripts.docket_scan.report(state) -> str`; `scripts.docket_scan.quantiles(values: Sequence[float], qs=(0.5, 0.75, 0.9, 1.0)) -> dict[float, float]`; `scripts.docket_scan.owner_names(raw) -> list[str]` (values of `REDACTED_FIELDS` string fields under `aircrafts[].ownerOperators[]`, at least four characters); `scripts.docket_scan.main(argv) -> int` with `--out PATH` and `--limit N`.
- Statistics per stratum (`fatal`, `non-fatal`) and overall, each a count or quantile: documents per docket; non-photo pages per docket; estimated tokens per docket and per document; share of dockets under 10,000 tokens; scanned pages and share of scan-only dockets; share of `pilot_form_6120` documents with a text layer (`kind != "scan"`); dockets with a party submission; non-PDF share of documents; category mix; characters-per-page histogram in bins `0, 1–49, 50–99, 100–299, 300–599, 600+`; documents and cases containing an owner or operator name, by category; amateur-built replacements by category; fetch failures.
- `check_fixtures_redacted.py`: every `tests/fixtures/docket/*/manifest.json` document with a `text_file` must carry a non-empty `reviewed_by`, and every `.pdf`/`.txt` under `tests/fixtures/docket/` must be named by such a document.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_docket_scan.py`:

```python
"""The development shape scan: counts and quantiles only (spec §8.1)."""

from scripts.docket_scan import ShapeState, accumulate, owner_names, quantiles, report
from tests.test_attach import _docket as small_docket


def test_quantiles_are_nearest_rank() -> None:
    assert quantiles([1, 2, 3, 4]) == {0.5: 2, 0.75: 3, 0.9: 4, 1.0: 4}
    assert quantiles([]) == {}


def test_owner_names_come_from_the_redacted_fields_only() -> None:
    raw = {"aircrafts": [{"ownerOperators": [{"registeredOwner": "Example Flying Club", "ownerZip": "1", "operatorName": "Ab"}]}]}
    assert owner_names(raw) == ["Example Flying Club"]


def test_accumulate_counts_documents_pages_tokens_and_names() -> None:
    state = ShapeState()
    docket = small_docket({1: "[page 1 of 3]\nExample Flying Club report.\n", 2: "[page 1 of 3]\nx\n"})
    raw = {"aircrafts": [{"ownerOperators": [{"registeredOwner": "Example Flying Club"}]}]}
    accumulate(state, docket, fatal=True, raw=raw)
    text = report(state)
    assert "documents per docket" in text
    assert "fatal" in text and "non-fatal" in text
    assert "owner or operator name" in text
    assert state.name_hits["fatal/exam_site"] == 1
    assert state.dockets["fatal"] == 1
```

Create `tests/test_check_fixtures_redacted.py` (if the script has no test yet):

```python
import json
from pathlib import Path

from scripts.check_fixtures_redacted import docket_fixture_problems


def test_docket_text_fixture_without_reviewed_by_is_a_problem(tmp_path: Path) -> None:
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "1.txt").write_text("text")
    (folder / "manifest.json").write_text(json.dumps({"fixture": {}, "documents": [{"index": 1, "text_file": "1.txt", "reviewed_by": ""}]}))
    problems = docket_fixture_problems(tmp_path)
    assert any("reviewed_by" in p for p in problems)


def test_orphan_document_file_is_a_problem(tmp_path: Path) -> None:
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "2.pdf").write_bytes(b"%PDF")
    (folder / "manifest.json").write_text(json.dumps({"fixture": {}, "documents": []}))
    assert any("2.pdf" in p for p in docket_fixture_problems(tmp_path))


def test_reviewed_document_is_fine(tmp_path: Path) -> None:
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "1.txt").write_text("text")
    (folder / "manifest.json").write_text(json.dumps({"fixture": {}, "documents": [{"index": 1, "text_file": "1.txt", "reviewed_by": "Andy, 2026-09-20"}]}))
    assert docket_fixture_problems(tmp_path) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docket_scan.py tests/test_check_fixtures_redacted.py -q`
Expected: ImportError.

- [ ] **Step 3: Write the scan**

Create `scripts/docket_scan.py`:

```python
"""Fetch every dev-400 docket once and report its shape: counts and quantiles only (spec §8.1).

Usage:
    uv run python -m scripts.docket_scan [--limit N] [--out docs/results/s2-shape-dev.txt]

One fetch serves the shape numbers, the threshold, the filter measurement and the fixture pool
(decision 0039 item 4). Listing pages and documents are cached under NTSB_DOCKET_DIR, never
committed. No case number and no text is printed.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ntsb_probable_cause.data.redaction import REDACTED_FIELDS
from ntsb_probable_cause.docket.attach import amateur_built_replace
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket, read_docket
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings

STRATA = ("fatal", "non-fatal")
TOKEN_LINE = 10_000
_MIN_NAME_LEN = 4
_CHAR_BINS = ((0, 0), (1, 49), (50, 99), (100, 299), (300, 599), (600, 10**9))


def quantiles(values: Sequence[float], qs: Sequence[float] = (0.5, 0.75, 0.9, 1.0)) -> dict[float, float]:
    """Nearest-rank quantiles; empty input gives an empty dict."""
    if not values:
        return {}
    ordered = sorted(values)
    return {q: ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))] for q in qs}


def owner_names(raw: Mapping[str, object]) -> list[str]:
    """Owner and operator name strings the record holds (the fields fixtures redact, 0015)."""
    names: list[str] = []
    aircrafts = raw.get("aircrafts")
    for aircraft in aircrafts if isinstance(aircrafts, list) else []:
        operators = aircraft.get("ownerOperators") if isinstance(aircraft, dict) else None
        for operator in operators if isinstance(operators, list) else []:
            if isinstance(operator, dict):
                for key in sorted(REDACTED_FIELDS):
                    value = operator.get(key)
                    if isinstance(value, str) and len(value.strip()) >= _MIN_NAME_LEN and "zip" not in key.lower():
                        names.append(value.strip())
    return names


@dataclass
class ShapeState:
    """Everything the scan accumulates. Counts and per-docket numbers, never text or ids."""

    dockets: Counter[str] = field(default_factory=Counter)
    docs_per_docket: defaultdict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    pages_per_docket: defaultdict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    tokens_per_docket: defaultdict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    tokens_per_doc: defaultdict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    scan_pages: Counter[str] = field(default_factory=Counter)
    scan_only: Counter[str] = field(default_factory=Counter)
    form_6120: Counter[str] = field(default_factory=Counter)
    form_6120_text: Counter[str] = field(default_factory=Counter)
    with_submission: Counter[str] = field(default_factory=Counter)
    documents: Counter[str] = field(default_factory=Counter)
    non_pdf: Counter[str] = field(default_factory=Counter)
    categories: Counter[str] = field(default_factory=Counter)
    statuses: Counter[str] = field(default_factory=Counter)
    char_bins: Counter[str] = field(default_factory=Counter)
    name_hits: Counter[str] = field(default_factory=Counter)
    name_cases: Counter[str] = field(default_factory=Counter)
    replacements: Counter[str] = field(default_factory=Counter)
    fetch_failed: Counter[str] = field(default_factory=Counter)


def _bin(chars: int) -> str:
    for low, high in _CHAR_BINS:
        if low <= chars <= high:
            return f"{low}-{high}" if high < 10**9 else f"{low}+"
    return "?"


def accumulate(state: ShapeState, docket: Docket, *, fatal: bool, raw: Mapping[str, object]) -> None:
    """Add one docket's numbers to the state."""
    stratum = "fatal" if fatal else "non-fatal"
    state.dockets[stratum] += 1
    readable = [r for r in docket.documents if r.status == "read"]
    non_photo = [r for r in docket.documents if not r.entry.is_photo_only()]
    state.docs_per_docket[stratum].append(len(docket.documents))
    state.pages_per_docket[stratum].append(sum(r.entry.pages for r in non_photo))
    state.tokens_per_docket[stratum].append(sum(r.estimated_tokens for r in readable))
    state.tokens_per_doc[stratum].extend(r.estimated_tokens for r in readable)
    pdfs = [r for r in docket.documents if r.kind is not None]
    state.scan_pages[stratum] += sum(r.pages - r.readable_pages for r in pdfs)
    state.scan_only[stratum] += bool(pdfs) and all(r.kind == "scan" for r in pdfs)
    state.with_submission[stratum] += any(r.category == "party_submission" for r in docket.documents)
    names = owner_names(raw)
    case_hit = False
    for record in docket.documents:
        state.documents[stratum] += 1
        state.categories[f"{stratum}/{record.category}"] += 1
        state.statuses[f"{stratum}/{record.status}"] += 1
        state.non_pdf[stratum] += not record.entry.is_pdf()
        if record.category == "pilot_form_6120" and record.kind is not None:
            state.form_6120[stratum] += 1
            state.form_6120_text[stratum] += record.kind != "scan"
        if record.status == "fetch failed":
            state.fetch_failed[stratum] += 1
        text = docket.texts.get(record.entry.index)
        if text is None:
            continue
        for chars in _chars_by_page(text):
            state.char_bins[_bin(chars)] += 1
        lowered = text.lower()
        if any(name.lower() in lowered for name in names):
            state.name_hits[f"{stratum}/{record.category}"] += 1
            case_hit = True
        _, n = amateur_built_replace(text, raw)
        state.replacements[f"{stratum}/{record.category}"] += n
    state.name_cases[stratum] += case_hit


def _chars_by_page(text: str) -> list[int]:
    """Characters per page from the page-marked text (the marker lines excluded)."""
    counts: list[int] = []
    for block in text.split("[page ")[1:]:
        body = block.split("]\n", 1)[1] if "]\n" in block else ""
        counts.append(len(body.strip()))
    return counts


def _fmt_q(values: Sequence[float]) -> str:
    q = quantiles(values)
    return "n=0" if not q else f"n={len(values)} median={q[0.5]:g} p75={q[0.75]:g} p90={q[0.9]:g} max={q[1.0]:g}"


def report(state: ShapeState) -> str:
    """The results text, by stratum and overall."""
    lines = ["# S2 development docket shape (scripts/docket_scan.py) — counts and quantiles only"]
    groups = {s: [s] for s in STRATA} | {"overall": list(STRATA)}
    for name, strata in groups.items():
        docs = [v for s in strata for v in state.docs_per_docket[s]]
        pages = [v for s in strata for v in state.pages_per_docket[s]]
        tokens = [v for s in strata for v in state.tokens_per_docket[s]]
        per_doc = [v for s in strata for v in state.tokens_per_doc[s]]
        n = sum(state.dockets[s] for s in strata)
        lines.append(f"\n## {name}: {n} dockets")
        lines.append(f"documents per docket: {_fmt_q(docs)}")
        lines.append(f"non-photo pages per docket: {_fmt_q(pages)}")
        lines.append(f"estimated readable tokens per docket: {_fmt_q(tokens)}")
        lines.append(f"estimated tokens per readable document: {_fmt_q(per_doc)}")
        under = sum(1 for t in tokens if t < TOKEN_LINE)
        lines.append(f"dockets under {TOKEN_LINE} tokens: {under} of {len(tokens)}")
        lines.append(f"scanned pages: {sum(state.scan_pages[s] for s in strata)}; scan-only dockets: {sum(state.scan_only[s] for s in strata)}")
        lines.append(f"pilot forms with a text layer: {sum(state.form_6120_text[s] for s in strata)} of {sum(state.form_6120[s] for s in strata)}")
        lines.append(f"dockets with a party submission: {sum(state.with_submission[s] for s in strata)}")
        lines.append(f"non-PDF documents: {sum(state.non_pdf[s] for s in strata)} of {sum(state.documents[s] for s in strata)}")
        lines.append(f"fetch failures: {sum(state.fetch_failed[s] for s in strata)}")
        lines.append("category mix: " + ", ".join(f"{k.split('/', 1)[1]} {v}" for k, v in sorted(state.categories.items()) if k.split('/')[0] in strata))
        lines.append("documents containing the record's owner or operator name, by category: " + ", ".join(f"{k.split('/', 1)[1]} {v}" for k, v in sorted(state.name_hits.items()) if k.split('/')[0] in strata))
        lines.append(f"cases with such a document: {sum(state.name_cases[s] for s in strata)} (a floor: names the record does not hold are not counted)")
        lines.append("amateur-built replacements, by category: " + ", ".join(f"{k.split('/', 1)[1]} {v}" for k, v in sorted(state.replacements.items()) if k.split('/')[0] in strata))
    lines.append("\n## characters per page, all readable documents (spec §5.2 thresholds at 50 and 300)")
    lines += [f"{b}: {state.char_bins[b]}" for b in ("0-0", "1-49", "50-99", "100-299", "300-599", "600+")]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Fetch (cached) every dev-400 docket, accumulate, print and optionally write the report."""
    parser = argparse.ArgumentParser(prog="docket_scan")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids("dev-400")
    if args.limit is not None:
        ids = ids[: args.limit]
    raws = samples.load_cases(processed, ids)
    state = ShapeState()
    with DocketClient(settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request) as client:
        for position, raw in enumerate(raws, start=1):
            mkey = raw.get("mKey")
            if not isinstance(mkey, int):
                continue
            try:
                docket = read_docket(client, mkey)
            except DocketError as error:
                print(f"{position}/{len(raws)}: listing failed ({type(error).__name__})", file=sys.stderr)
                continue
            accumulate(state, docket, fatal=raw.get("highestInjuryLevel") == "Fatal", raw=raw)
            print(f"{position}/{len(raws)}: {len(docket.documents)} documents", file=sys.stderr)
    text = report(state)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Progress lines go to stderr and carry a position, never a case number.

- [ ] **Step 4: The fixture check and the hook**

`scripts/check_fixtures_redacted.py`, add:

```python
DOCKET_FIXTURES = Path("tests/fixtures/docket")


def docket_fixture_problems(root: Path = DOCKET_FIXTURES) -> list[str]:
    """Every docket text fixture must name its reviewer; every document file must be listed (0037)."""
    problems: list[str] = []
    if not root.exists():
        return problems
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = json.loads((folder / "manifest.json").read_text())
        listed: set[str] = set()
        for document in manifest.get("documents", []):
            for key in ("text_file", "pdf_file"):
                name = document.get(key)
                if name:
                    listed.add(str(name))
                    if not str(document.get("reviewed_by") or "").strip():
                        problems.append(f"{folder / name}: document text committed without reviewed_by (0037)")
        for path in sorted(folder.iterdir()):
            if path.suffix in {".pdf", ".txt"} and path.name not in listed:
                problems.append(f"{path}: not listed in manifest.json with reviewed_by (0037)")
    return problems
```

and in `main`, after the CSV loop: `for problem in docket_fixture_problems(): print(problem); failed = True`.

`.pre-commit-config.yaml`: change the `check-fixtures-redacted` hook's `files` to `^tests/fixtures/` and add `pass_filenames: false` so the docket check runs whenever any fixture changes. `Makefile`: `docket-scan:` → `uv run python -m scripts.docket_scan --out docs/results/s2-shape-dev.txt`.

- [ ] **Step 5: Run the tests and the full check, commit**

Run: `make check`
Expected: green.

```bash
git add scripts/docket_scan.py scripts/check_fixtures_redacted.py .pre-commit-config.yaml Makefile tests/test_docket_scan.py tests/test_check_fixtures_redacted.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: docket_scan for the dev-400 shape; docket text fixtures must name a reviewer (spec §8.1, 0037)"
```

---

### Task 14: The threshold and filter measurement, and the open-split shape script (spec §8.2, §8.3, §8.4)

**Files:**
- Modify: `scripts/corpus_scan.py` (`--docket` mode)
- Create: `scripts/docket_shape_open.py`
- Modify: `Makefile` (`scan-docket`, `docket-shape-open`)
- Test: `tests/test_corpus_scan.py`, `tests/test_docket_shape_open.py`

**Interfaces:**
- `scripts.corpus_scan.docket_hits(raw, docket: Docket, *, min_sentence_chars: int) -> Counter[str]`: tripwire hits keyed `"<category>/<kind>"` (`kind` in `text`, `sentence`, `code`) over a case context with every readable document attached.
- `scripts.corpus_scan.docket_report(hits_by_length: Mapping[int, Counter[str]], cases: int, documents: int) -> str`: per candidate length the total hits and the breakdown by category; `THRESHOLD_LINE` with the chosen length (lowest with zero hits, or `none`); then, at the chosen (or, if none, the largest) length, the §8.3 table: hits, misses (hit category not in `DENY_LIST`) and false denies (`DENY_LIST` category with no hit) by category, and cases stopped by document category.
- `scripts.corpus_scan.main(["--docket", "--out", PATH])` runs over the `dev-400` cache only (no fetch: a missing cache entry is counted as `not cached` and skipped).
- `scripts.docket_shape_open.draw(processed: Path, *, per_stratum: int = 40, seed: int = 20260918) -> list[tuple[int, bool]]` (mkey, fatal) over closed open-split cases, `completionStatus == "Completed"`, event date 2024 or later; `main(["--out", PATH])` with `DocketClient(None)`, reusing `docket_scan.ShapeState`, `accumulate` and `report`; prints nothing per case but a position.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_corpus_scan.py`:

```python
from scripts.corpus_scan import THRESHOLD_LINE, docket_hits, docket_report
from tests.test_attach import _docket as small_docket


def test_docket_hits_finds_a_withheld_sentence_in_a_document(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    narrative = fields.factual_narrative(raw) or ""
    docket = small_docket({1: f"[page 1 of 3]\n{narrative}\n"})
    hits = docket_hits(raw, docket, min_sentence_chars=20)
    assert hits["exam_site/text"] >= 1


def test_docket_report_names_the_threshold_and_the_filter_table() -> None:
    hits = {10: Counter({"exam_site/sentence": 2}), 20: Counter(), 40: Counter(), 80: Counter()}
    text = docket_report(hits, cases=3, documents=7)
    assert f"{THRESHOLD_LINE}20" in text
    assert "misses" in text and "false denies" in text
```

Create `tests/test_docket_shape_open.py`:

```python
"""The open-split shape script keeps nothing: read and discard (decision 0040)."""

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.docket_shape_open import draw


def _processed(tmp_path: Path) -> Path:
    processed = tmp_path / "processed"
    processed.mkdir()
    rows = [
        ("A", 1, date(2024, 3, 1), "open", "Completed", json.dumps({"highestInjuryLevel": "Fatal"})),
        ("B", 2, date(2024, 4, 1), "open", "Completed", json.dumps({"highestInjuryLevel": "None"})),
        ("C", 3, date(2024, 5, 1), "open", "Ongoing", json.dumps({"highestInjuryLevel": "Fatal"})),
        ("D", 4, date(2021, 5, 1), "heldout", "Completed", json.dumps({"highestInjuryLevel": "Fatal"})),
    ]
    table = pa.table(
        {
            "ntsb_number": [r[0] for r in rows], "mkey": [r[1] for r in rows],
            "event_date": pa.array([r[2] for r in rows], type=pa.date32()),
            "split": [r[3] for r in rows], "completion_status": [r[4] for r in rows],
            "raw_json": [r[5] for r in rows],
        }
    )
    pq.write_table(table, processed / "cases.parquet")
    return processed


def test_draw_takes_closed_open_split_cases_by_stratum(tmp_path: Path) -> None:
    drawn = draw(_processed(tmp_path), per_stratum=40)
    assert sorted(drawn) == [(1, True), (2, False)]


def test_script_writes_nothing_under_data(tmp_path: Path, monkeypatch, respx_mock) -> None:  # type: ignore[no-untyped-def]
    import httpx

    from scripts.docket_shape_open import main

    processed = _processed(tmp_path)
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_DOCKET_DIR", str(tmp_path / "docket"))
    respx_mock.get(url__startswith="https://data.ntsb.gov/Docket").mock(
        return_value=httpx.Response(200, text="<html>Docket Items: 0</html>")
    )
    out = tmp_path / "out.txt"
    assert main(["--out", str(out), "--per-stratum", "40"]) == 0
    assert out.exists()
    assert not (tmp_path / "docket").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt", "processed"]
```

Type the fixtures (`pytest.MonkeyPatch`, `respx.MockRouter`) and drop the ignore. The processed-file columns must match `data/build.py`'s `SCHEMA` names.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_corpus_scan.py tests/test_docket_shape_open.py -q`
Expected: ImportError.

- [ ] **Step 3: The docket mode of the corpus scan**

Append to `scripts/corpus_scan.py`:

```python
# --- docket mode (spec §8.2, §8.3): the threshold on docket text, then the filter measurement ---

from ntsb_probable_cause.docket import filter as docket_filter  # noqa: E402
from ntsb_probable_cause.docket.attach import attach_docket  # noqa: E402
from ntsb_probable_cause.docket.client import DocketClient  # noqa: E402
from ntsb_probable_cause.docket.manifest import Docket, read_docket  # noqa: E402
from ntsb_probable_cause.errors import DocketError  # noqa: E402
from ntsb_probable_cause.scoring import samples  # noqa: E402


def docket_hits(raw: Mapping[str, object], docket: Docket, *, min_sentence_chars: int) -> Counter[str]:
    """Tripwire hits by ``category/kind`` with every readable document attached, one at a time.

    Documents are attached one at a time so a hit is attributed to the document's category.
    """
    withheld = {
        "factual_narrative": fields.factual_narrative(raw),
        "analysis_narrative": fields.analysis_narrative(raw),
        "probable_cause": fields.probable_cause(raw),
    }
    codes = fields.occurrence_codes(raw) + fields.finding_codes(raw)
    hits: Counter[str] = Counter()
    for record in docket.documents:
        if record.status != "read":
            continue
        context = attach_docket(raw, docket, documents=[record.entry.index]).context
        evidence = {
            f.role.value: f.extract(context)
            for f in fields.EVIDENCE_FIELDS
            if f.role in {fields.EvidenceRole.DOCKET_DOCUMENTS}
        }
        for leak in find_leaks(evidence, withheld, codes, min_sentence_chars=min_sentence_chars):
            hits[f"{record.category}/{leak.kind}"] += 1
    return hits


def docket_report(hits_by_length: Mapping[int, Counter[str]], cases: int, documents: int) -> str:
    """The threshold curve on docket text and the §8.3 table at the chosen length."""
    lines = [f"# S2 docket tripwire scan (scripts/corpus_scan.py --docket) — counts only",
             f"dev-400 cases with a cached docket: {cases}; readable documents: {documents}"]
    lines.append("\n## tripwire hits on docket text by minimum sentence length (category/kind)")
    totals = {length: sum(counter.values()) for length, counter in hits_by_length.items()}
    for length in sorted(hits_by_length):
        lines.append(f"{length}: total {totals[length]} {dict(sorted(hits_by_length[length].items()))}")
    chosen = choose_threshold(totals)
    lines.append(f"\n{THRESHOLD_LINE}{chosen if chosen is not None else 'none'}")
    at = chosen if chosen is not None else max(hits_by_length)
    counter = hits_by_length[at]
    hit_categories = {key.split("/")[0] for key in counter}
    lines.append(f"\n## filter measurement at minimum sentence length {at} (decision 0039)")
    lines.append(f"hits by category: {dict(sorted(Counter(k.split('/')[0] for k in counter.elements()).items()))}")
    lines.append(f"misses (hit, category not on the deny-list): {sorted(hit_categories - docket_filter.DENY_LIST)}")
    lines.append(f"false denies (on the deny-list, no hit): {sorted(docket_filter.DENY_LIST - hit_categories)}")
    lines.append(f"deny-list in force: {sorted(docket_filter.DENY_LIST) or 'empty'}")
    return "\n".join(lines)


def docket_main(out: str | None) -> int:
    """Run the docket mode over the dev-400 cache; never fetch."""
    settings = Settings()
    processed = settings.data_dir / "processed"
    raws = samples.load_cases(processed, samples.sample_ids("dev-400"))
    hits_by_length: dict[int, Counter[str]] = {length: Counter() for length in CANDIDATE_LENGTHS}
    cases = documents = 0
    stopped_by_category: Counter[str] = Counter()
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        for raw in raws:
            mkey = raw.get("mKey")
            if not isinstance(mkey, int) or not (settings.docket_dir / str(mkey) / "listing.html").is_file():
                continue
            try:
                docket = read_docket(client, mkey)
            except DocketError:
                continue
            cases += 1
            documents += sum(1 for r in docket.documents if r.status == "read")
            for length in CANDIDATE_LENGTHS:
                hits = docket_hits(raw, docket, min_sentence_chars=length)
                hits_by_length[length].update(hits)
                if length == MIN_SENTENCE_CHARS:
                    stopped_by_category.update({k.split("/")[0]: 1 for k in hits})
    text = docket_report(hits_by_length, cases, documents)
    text += f"\n\ncases stopped by the tripwire at the guard's current threshold ({MIN_SENTENCE_CHARS}), by document category: {dict(sorted(stopped_by_category.items()))}"
    print(text)
    if out:
        Path(out).write_text(text + "\n")
    return 0
```

Wire `main`: parse `--docket` and `--out`; when `--docket` is set, return `docket_main(out)`. Import `MIN_SENTENCE_CHARS` from `records.guard` and `Path`. The cache check keeps the mode fetch-free: a docket not cached by Task 15's scan is skipped and counted (add a `not cached` count to the report). Also add to the existing scan's header: `guard MIN_SENTENCE_CHARS in force: {MIN_SENTENCE_CHARS}` (done-means 4: "the corpus scan reports the threshold it used").

- [ ] **Step 4: The open-split shape script**

Create `scripts/docket_shape_open.py`:

```python
"""Docket shape on closed open-split cases, 40 per stratum, numbers only (decision 0040).

Usage:
    uv run python -m scripts.docket_shape_open [--per-stratum 40] [--out docs/results/s2-shape-open.txt]

Read and discard: the client has no cache, nothing is written under data/, and no case number
is printed. The seed and the rule are here; the drawn list is not (0024).
"""

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
from scripts.docket_scan import ShapeState, accumulate, report

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import read_docket
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import COMPLETED_STATUS, OPEN_MIN_YEAR

SEED = 20260918
PER_STRATUM = 40


def draw(processed: Path, *, per_stratum: int = PER_STRATUM, seed: int = SEED) -> list[tuple[int, bool]]:
    """(mkey, fatal) for up to ``per_stratum`` closed open-split cases per fatal stratum."""
    columns = ["mkey", "event_date", "completion_status", "raw_json"]
    table = pq.read_table(processed / "cases.parquet", columns=columns)
    pool: dict[bool, list[int]] = {True: [], False: []}
    for mkey, event, status, raw_json in zip(*(table[c].to_pylist() for c in columns), strict=True):
        event_date = event if isinstance(event, date) else date.fromisoformat(str(event)[:10])
        if status != COMPLETED_STATUS or event_date.year < OPEN_MIN_YEAR:
            continue
        pool[json.loads(raw_json)["highestInjuryLevel"] == "Fatal"].append(int(mkey))
    rng = random.Random(seed)  # noqa: S311 -- reproducible draw, not security
    drawn: list[tuple[int, bool]] = []
    for fatal in (True, False):
        members = sorted(pool[fatal])
        drawn.extend((m, fatal) for m in rng.sample(members, min(per_stratum, len(members))))
    return drawn


def main(argv: list[str]) -> int:
    """Draw, stream every docket through the parser and extractor, print the numbers."""
    parser = argparse.ArgumentParser(prog="docket_shape_open")
    parser.add_argument("--per-stratum", type=int, default=PER_STRATUM)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    drawn = draw(settings.data_dir / "processed", per_stratum=args.per_stratum)
    state = ShapeState()
    with DocketClient(None, seconds_per_request=settings.docket_seconds_per_request) as client:
        for position, (mkey, fatal) in enumerate(drawn, start=1):
            try:
                docket = read_docket(client, mkey)
            except DocketError as error:
                print(f"{position}/{len(drawn)}: listing failed ({type(error).__name__})", file=sys.stderr)
                continue
            accumulate(state, docket, fatal=fatal, raw={})
            print(f"{position}/{len(drawn)}: {len(docket.documents)} documents", file=sys.stderr)
    text = report(state).replace("S2 development docket shape (scripts/docket_scan.py)", "S2 open-split docket shape (scripts/docket_shape_open.py; decision 0040)")
    text += (
        "\n\nThe 111 closed fatal open-split cases (docs/results/s0-corpus-scan.txt) are a small "
        "population and a draw of 40 covers over a third of it; these figures describe that "
        "population, not cases still open."
    )
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

`accumulate` is called with `raw={}`: no owner names and no amateur-built flag are read for open-split cases, so those two counts are zero by construction and the report says so (add a line to `report` when the state has no name lookups: simplest, print the counts as they are; the open-split file's header sentence explains they are not measured there).

`Makefile`:

```make
scan-docket:
	uv run python -m scripts.corpus_scan --docket --out docs/results/s2-threshold.txt

docket-shape-open:
	uv run python -m scripts.docket_shape_open --out docs/results/s2-shape-open.txt
```

- [ ] **Step 5: Run the tests and the full check, commit**

Run: `make check`
Expected: green.

```bash
git add scripts/corpus_scan.py scripts/docket_shape_open.py Makefile tests/test_corpus_scan.py tests/test_docket_shape_open.py docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: the docket tripwire scan and the open-split shape script (spec §8.2-8.4, 0040)"
```

---

### Task 15: The `dev-400` fetch and the development shape file (spec §8.1; Andy or local, network, one to three hours, no money)

**Files:**
- Create: `docs/results/s2-shape-dev.txt`

- [ ] **Step 1: Fetch and scan**

Run, from a clean tree, in a shell that has no key exported (none is needed):

```bash
make docket-scan
```

Expected: progress lines on stderr with positions, never case numbers; `docs/results/s2-shape-dev.txt` written; `data/docket/` holds 400 folders. About an hour at the spike's median, up to three hours at its 90th percentile (M5). The run resumes from the cache if interrupted.

- [ ] **Step 2: Read the characters-per-page histogram against spec §10's first rule**

If fewer than 5% of pages fall in the `50-99` and `100-299` bins together, the thresholds stand and this is noted in the As-built record. Otherwise stop and write a decision record moving them to the gap's bounds before Task 16, and log it below.

- [ ] **Step 3: Commit**

```bash
git add docs/results/s2-shape-dev.txt docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: development docket shape on dev-400 (spec §8.1)"
```

---

### Task 16: The threshold, the deny-list, the fixture pool and Andy's hand-check (spec §4.4, §7, §8.2, §8.3; decisions 0037, 0039)

**Files:**
- Create: `docs/results/s2-threshold.txt`, `tests/fixtures/docket/title_handcheck.csv`, the criterion fixtures under `tests/fixtures/docket/`
- Modify: `src/ntsb_probable_cause/records/guard.py` (`MIN_SENTENCE_CHARS`), `src/ntsb_probable_cause/docket/filter.py` (`DENY_LIST`), `scripts/make_docket_fixture.py` (`draw`, `document`, `handcheck`), `docs/results/s0-corpus-scan.txt` is not touched
- Test: `tests/test_docket_extract.py` (reviewed PDFs), `tests/test_corpus_scan.py` (`test_guard_threshold_is_the_value_the_scan_recorded` reads the new file), `tests/test_docket_fixtures.py`

- [ ] **Step 1: The threshold**

Run: `make scan-docket`
Expected: `docs/results/s2-threshold.txt` with the hit curve and `chosen minimum sentence length: N`. Set `MIN_SENTENCE_CHARS = N` in `guard.py` with the comment's source changed to `docs/results/s2-threshold.txt`. Update `tests/test_corpus_scan.py::test_guard_threshold_is_the_value_the_scan_recorded` to read the S2 file (keep the S0 assertion on the S0 file as history). If no length has zero hits, follow 0019's precedent: inspect the categories of the hits at length 80 in the results file (counts only), write a decision record for the rule that resolves them, and log it below. Check the abbreviation-break note of 0019: if hits at the chosen length come from a split on an abbreviation, fix `_SENTENCE_END`, re-run, and keep both runs' output in the file.

- [ ] **Step 2: The deny-list**

From the same file: if any category has a hit at the chosen threshold, add it to `DENY_LIST` in `filter.py`, citing `docs/results/s2-threshold.txt`; re-run `make scan-docket` so the file's "false denies" line reflects the list in force. If there are no hits, `DENY_LIST` stays empty and the results file says so (0039 item 2). Update `tests/test_docket_filter.py::test_deny_list_starts_empty_and_nothing_is_denied` to assert the published value.

- [ ] **Step 3: Write the `draw`, `document` and `handcheck` subcommands**

Extend `scripts/make_docket_fixture.py`:

```python
CRITERIA: tuple[tuple[str, Callable[[Docket], bool]], ...] = (
    ("photo-only and non-pdf entries", lambda d: any(e.is_photo_only() for e in d.listing.entries) and any(not e.is_pdf() for e in d.listing.entries)),
    ("a scanned document", lambda d: any(r.kind == "scan" for r in d.documents)),
    ("a partial document", lambda d: any(r.kind == "partial" for r in d.documents)),
    ("over the cap at Sonnet 5 standard", lambda d: sum(r.estimated_tokens for r in d.documents if r.status == "read") > 15_000),
    ("ntsb born-digital documents of two types", lambda d: len({r.category for r in d.documents if r.status == "read" and r.kind == "born-digital" and r.category in {"exam_site", "specialist_factual", "weather", "medical_tox"}}) >= 2),
    ("a party submission", lambda d: any(r.category == "party_submission" for r in d.documents)),
)


def outcome_only(record: DocumentRecord) -> dict[str, object]:
    """A manifest row: the classification and extraction outcome, never text (0037 item 3)."""
    return {
        "index": record.entry.index, "title": record.entry.title, "doc_type": record.entry.doc_type,
        "pages": record.pages, "photos": record.entry.photos, "extension": record.entry.extension,
        "category": record.category, "status": record.status, "kind": record.kind,
        "readable_pages": record.readable_pages, "estimated_tokens": record.estimated_tokens,
        "text_file": None, "pdf_file": None, "reviewed_by": None,
    }


def _cmd_draw(args: argparse.Namespace, settings: Settings) -> int:
    """For each criterion, the first cached dev-400 docket in seeded order that meets it."""
    processed = settings.data_dir / "processed"
    ids = list(samples.sample_ids("dev-400"))
    random.Random(SEED).shuffle(ids)  # noqa: S311
    cases = _cases(processed, tuple(ids))
    taken: dict[str, str] = {}
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        for name, criterion in CRITERIA:
            for case_id in ids:
                mkey, event = cases[case_id]
                if not (settings.docket_dir / str(mkey) / "listing.html").is_file():
                    continue
                docket = read_docket(client, mkey)
                if criterion(docket):
                    taken[name] = case_id
                    if args.write:
                        folder = write_listing_fixture(case_id, mkey, event, client.listing_html(mkey), datetime.now(UTC).isoformat(), name)
                        manifest = json.loads((folder / "manifest.json").read_text())
                        manifest["documents"] = [outcome_only(r) for r in docket.documents]
                        (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
                    break
    for name, case_id in taken.items():
        print(f"{name}: {case_id}")
    return 0


def redact_text(text: str, raw: Mapping[str, object]) -> tuple[str, int]:
    """The scripted redaction pass: owner/operator name strings and the amateur-built rule."""
    text, count = amateur_built_replace(text, raw)
    for name in owner_names(raw):
        text, n = re.subn(re.escape(name), "[redacted]", text, flags=re.IGNORECASE)
        count += n
    return text, count


def _cmd_document(args: argparse.Namespace, settings: Settings) -> int:
    """Commit one NTSB-authored born-digital document's PDF and expected text, after Andy's read."""
    folder = FIXTURES / args.case_id
    manifest = json.loads((folder / "manifest.json").read_text())
    mkey = int(manifest["fixture"]["mkey"])
    raws = samples.load_cases(settings.data_dir / "processed", [args.case_id])
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        docket = read_docket(client, mkey)
        record = docket.record(args.index)
        if record.status != "read" or record.kind != "born-digital":
            raise FixtureError(f"{args.case_id} #{args.index}: only a readable born-digital document may be committed as text")
        if record.category not in {"exam_site", "specialist_factual", "weather", "medical_tox", "atc_radar_data"}:
            raise FixtureError(f"{args.case_id} #{args.index}: category {record.category} is not NTSB-authored (0037 item 3)")
        data = client.document(mkey, record.entry.index, record.entry.href)
    text, redactions = redact_text(docket.texts[args.index], raws[0])
    (folder / f"{args.index}.pdf").write_bytes(data)
    (folder / f"{args.index}.txt").write_text(text)
    for row in manifest["documents"]:
        if row["index"] == args.index:
            row.update({"text_file": f"{args.index}.txt", "pdf_file": f"{args.index}.pdf", "reviewed_by": args.reviewed_by, "redactions": redactions})
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote {folder / f'{args.index}.txt'} ({redactions} redactions); reviewed by {args.reviewed_by}")
    return 0


def _cmd_handcheck(args: argparse.Namespace, settings: Settings) -> int:
    """A seeded sample of 60 titles with their category, for Andy to mark right or wrong."""
    rows: list[tuple[str, str, str]] = []
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        for mkey_dir in sorted(settings.docket_dir.iterdir()):
            if not (mkey_dir / "listing.html").is_file():
                continue
            listing = parse_listing(client.listing_html(int(mkey_dir.name)), mkey=int(mkey_dir.name))
            rows.extend((e.title, e.doc_type, document_category(e.title, e.doc_type)) for e in listing.entries)
    sample = random.Random(SEED).sample(sorted(set(rows)), min(60, len(set(rows))))  # noqa: S311
    with (FIXTURES / "title_handcheck.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["title", "doc_type", "category", "correct"])
        writer.writerows((t, d, c, "") for t, d, c in sample)
    print(f"wrote {FIXTURES / 'title_handcheck.csv'}: {len(sample)} titles")
    return 0
```

Wire the three into `main` beside Task 6's `listing` subparser, and add their dispatch
branches to the same `try` block, so the four subcommands share one `FixtureError` handler:

```python
    draw_p = commands.add_parser("draw", help="draw the fixture pool against the criteria")
    draw_p.add_argument("--write", action="store_true", help="write the fixtures, not just the candidates")
    document_p = commands.add_parser("document", help="add one reviewed document to a drawn fixture")
    document_p.add_argument("case_id")
    document_p.add_argument("index", type=int)
    document_p.add_argument("--reviewed-by", required=True, help='e.g. "Andy, 2026-09-21"')
    commands.add_parser("handcheck", help="write the 60-title hand-check sheet")
```

and, in `main`'s `try` block after the `listing` branch:

```python
        if args.command == "draw":
            return _cmd_draw(args, settings)
        if args.command == "document":
            return _cmd_document(args, settings)
        if args.command == "handcheck":
            return _cmd_handcheck(args, settings)
```

`argparse` turns `--reviewed-by` into `args.reviewed_by`. Every `_cmd_*` takes
`(args: argparse.Namespace, settings: Settings) -> int`, as `_cmd_listing` does, even where
it does not read `settings`. Imports: `csv`, `re`, `Callable`, `Mapping`, `DocumentRecord`, `Docket`, `read_docket`, `parse_listing`, `document_category`, `amateur_built_replace`, `owner_names` (from `scripts.docket_scan`). A `document` PDF is the same document Andy reads; the PDF is committed so the extractor test runs on a real file, and the `.txt` is the expected extraction after redaction. (Titles hold no personal data; the manifest rows hold titles.)

The `document` subcommand's `reviewed_by` value is a statement by Andy that he has read the PDF and the `.txt` and found no personal name or non-NTSB text; the script cannot check that, which is why the check script requires the field.

- [ ] **Step 4: Draw and commit the fixtures (Andy reads the documents)**

Run: `uv run python -m scripts.make_docket_fixture draw` (prints the candidate per criterion), then `--write`. Then for the "ntsb born-digital documents of two types" case, and for one more document of a different type in another drawn case, Andy reads each PDF; for each one he approves:

```bash
uv run python -m scripts.make_docket_fixture document <case_id> <index> --reviewed-by "Andy, 2026-09-2N"
```

Expected: about five listing fixtures with outcome-only manifests and two or three reviewed documents. Add `^tests/fixtures/docket/.*\.(html|txt|pdf|csv)$` to the typos hook's exclude and `tests/fixtures/docket/*.pdf` to `check-added-large-files`' consideration (a large PDF over 500 KB is refused by the hook; choose a smaller document).

- [ ] **Step 5: Extend the extractor test to the reviewed documents**

Append to `tests/test_docket_extract.py`:

```python
def _reviewed() -> list[tuple[Path, Path, int]]:
    found = []
    for folder in sorted(p for p in Path("tests/fixtures/docket").iterdir() if p.is_dir()):
        manifest = json.loads((folder / "manifest.json").read_text())
        for row in manifest["documents"]:
            if row.get("pdf_file") and row.get("text_file"):
                found.append((folder / row["pdf_file"], folder / row["text_file"], int(row["readable_pages"])))
    return found


@pytest.mark.parametrize(("pdf", "text", "readable"), _reviewed())
def test_reviewed_document_extracts_with_page_markers(pdf: Path, text: Path, readable: int) -> None:
    result = extract_pdf(pdf.read_bytes())
    expected = text.read_text()
    assert result.text.count("[page 1 of ") == 1
    assert readable_pages(result.chars_by_page) == readable
    # The committed text is the extraction after the scripted redaction pass; page markers and
    # line structure are identical, and every line not touched by redaction matches.
    assert [l for l in result.text.splitlines() if "[redacted]" not in l and "Amateur-built" not in l][:20] == [l for l in expected.splitlines() if "[redacted]" not in l and "Amateur-built" not in l][:20]


def test_at_least_two_reviewed_documents_exist() -> None:
    assert len(_reviewed()) >= 2, "Task 16 commits reviewed NTSB-authored documents (0037)"
```

Also extend `tests/test_docket_fixtures.py`: every manifest row with `status == "read"` and no `text_file` carries `estimated_tokens > 0`, and every row's `status` is in the manifest's `Status` set.

- [ ] **Step 6: The hand-check sheet**

Run: `uv run python -m scripts.make_docket_fixture handcheck`. Andy fills the `correct` column with `y` or `n` for each of the 60 rows. Add to `tests/test_docket_fixtures.py`:

```python
def test_title_handcheck_is_complete_and_its_error_rate_is_published() -> None:
    with Path("tests/fixtures/docket/title_handcheck.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 60
    assert all(r["correct"] in {"y", "n"} for r in rows)
    wrong = sum(r["correct"] == "n" for r in rows)
    published = Path("docs/results/s2-filter.txt").read_text()
    assert f"title hand-check: {wrong} of 60 wrong" in published
```

Write the hand-check line into `docs/results/s2-filter.txt` by a small addition to `corpus_scan.py --docket` (`_handcheck_line()` reads the CSV and formats the line; the test then holds by construction), and re-run `make scan-docket`. Note the file `s2-filter.txt` is produced by the same `--docket` run as `s2-threshold.txt`: have the mode write both (`--out` names the threshold file; the filter table goes to the sibling `s2-filter.txt`). Log this in Deviations if the split of the two files differs from spec §8.

- [ ] **Step 7: Run the full check and commit**

Run: `make check`
Expected: green; the contamination and redaction checks pass on the new fixtures.

```bash
git add src/ntsb_probable_cause/records/guard.py src/ntsb_probable_cause/docket/filter.py scripts/make_docket_fixture.py scripts/corpus_scan.py tests/fixtures/docket tests/test_docket_extract.py tests/test_docket_fixtures.py tests/test_docket_filter.py tests/test_corpus_scan.py docs/results/s2-threshold.txt docs/results/s2-filter.txt .pre-commit-config.yaml docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: threshold re-measured on docket text, deny-list, fixture pool, title hand-check (0037, 0039)"
```

---

### Task 17: Arm B on `dev-400`, the filter and rank order chosen and published (spec §8.5, §10; Andy runs, about $3)

**Files:**
- Modify: `src/ntsb_probable_cause/docket/filter.py` (`ARM_B_TYPES`, `ARM_B_RANK`), `docs/results/s2-filter.txt`, `docs/results/s2-armB-dev.txt`
- Test: `tests/test_docket_filter.py`

- [ ] **Step 1: Set the rank order from the shape file**

From `docs/results/s2-shape-dev.txt` the per-document median tokens are reported per stratum only; the §10 rule needs them per category. Add to `docket_scan.py`'s report a line `median tokens per readable document by category: ...` (category → median), re-run `make docket-scan` (cache only, minutes), and set `ARM_B_RANK` to the categories in ascending order of that median, citing the file. Update the rank test to assert the published tuple is sorted by those medians (read the file in the test).

- [ ] **Step 2: Run the three development arms**

In a shell script that exports the key from `pass show api/openrouter` and never prints it:

```bash
make armb
```

Expected: three run folders under `data/runs/`, each under a dollar (M4). Note each run id from the terminal.

- [ ] **Step 3: Reports and the submission rule**

```bash
uv run ntsb-eval report <published-run-id> --against <no-submissions-run-id> --out docs/results/s2-armB-dev.txt
uv run ntsb-eval report <unfiltered-run-id> --against <published-run-id> >> docs/results/s2-armB-dev.txt
```

Read off the §10 rules: party submissions stay unless the paired top-1 difference "published minus no-submissions" on cases holding a submission has an interval entirely below zero. (`report --against` pairs on all shared cases; for the "cases holding a submission" restriction add `--only-with-documents CATEGORY` to `report`, which keeps cases whose steps attached a document of that category, with a test.) Set `ARM_B_TYPES` accordingly and append the decision line and both paired differences to `docs/results/s2-filter.txt`. Update the filter tests to the published values.

- [ ] **Step 4: Commit**

```bash
git add src/ntsb_probable_cause/docket/filter.py src/ntsb_probable_cause/scoring/report.py apps/eval/__main__.py scripts/docket_scan.py tests/test_docket_filter.py tests/test_report.py docs/results/s2-filter.txt docs/results/s2-armB-dev.txt docs/results/s2-shape-dev.txt docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: arm B on dev-400; the filter and rank order chosen by the published rule (spec §10)"
```

---

### Task 18: The open-split shape (spec §8.4, decision 0040; Andy or local, network, about half an hour, no money)

**Files:**
- Create: `docs/results/s2-shape-open.txt`

- [ ] **Step 1: Run**

```bash
make docket-shape-open
```

Expected: the results file; `data/docket/` unchanged (confirm with `git status` and `ls data/docket | wc -l` before and after: the count is the same).

- [ ] **Step 2: Commit**

```bash
git add docs/results/s2-shape-open.txt docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: docket shape on closed open-split cases, numbers only (decision 0040)"
```

---

### Task 19: Arm B on `heldout-400`, once (spec §8.6; Andy runs, about $1)

**Files:**
- Create: `docs/results/s2-bars.txt`
- Modify: `docs/results/heldout-ledger.md` (one row, appended by the run), `Makefile` (`s2-bars`)

- [ ] **Step 1: Confirm the tree is clean and the filter is published**

Run: `git status --short` (empty) and `grep -n "ARM_B_TYPES\|ARM_B_RANK\|DENY_LIST" src/ntsb_probable_cause/docket/filter.py` (each cites `s2-filter.txt`).

- [ ] **Step 2: Add the target and run**

```make
s2-bars:
	uv run ntsb-eval run --arm B --sample heldout-400
```

Run `make s2-bars` from the key-exporting shell script. The held-out dockets are fetched into the cache during the run (about an hour of polite fetching before the batch is submitted; the run log shows the fetch positions). Then, from the explicit run id:

```bash
uv run ntsb-eval report <heldout-B-run-id> --against 20260917T061527-c717ab5-heldout-400-ceiling --out docs/results/s2-bars.txt
```

Expected: the table with intervals, the cap summary line, the paired difference against the S1 ceiling, and exactly one new ledger row.

- [ ] **Step 3: Commit**

```bash
git add Makefile docs/results/s2-bars.txt docs/results/heldout-ledger.md docs/plans/2026-09-18-s2-docket-tool.md
git commit -m "S2: arm B with the docket on heldout-400, the bar for S3 (spec §8.6)"
```

---

### Task 20: Close-out (decision 0017)

- [ ] **Step 1: Documentation**

`README.md` and `CLAUDE.md` gain the new commands (`docket-scan`, `scan-docket`, `docket-shape-open`, `armb`, `s2-bars`, `ntsb-eval release`, `--arm B`, `--docket-filter`) and the settings `NTSB_DOCKET_DIR`, `NTSB_DOCKET_SECONDS_PER_REQUEST`. `CLAUDE.md`'s "Eval bars to beat" gains arm B's `heldout-400` figures with a pointer to `docs/results/s2-bars.txt`, and its "Required components" ticks the docket client and classifier. The roadmap's S3 done-means gains "beats arm B with the docket (`docs/results/s2-bars.txt`) at equal cost".

- [ ] **Step 2: Run the close-stage skill**

Invoke `close-stage`: it appends the As-built record (Delivered; Done means, with evidence, one line per §14 item; Departures, from the Deviations below; Decisions taken during the stage; Implementation record with the total spend from `month_spent` over the S2 run records), marks the specification Implemented, marks the roadmap's S2 entry done, deletes this plan, sets `version = "0.3.0"` in `pyproject.toml`, and runs `scripts/check_docs.py`.

- [ ] **Step 3: Pull request**

Title `S2: the docket tool`. Merge, never squash (0033). After the merge Andy runs `gh release create v0.3.0 --generate-notes`.

---

## Deviations

*Log every departure from the specification here, dated, with the reason. Moved into the As-built record at close-out (decision 0017).*

- 2026-09-18, plan: spec §5.3's status set names `unreadable: photos`; the plan folds it into `skipped: photo-only`. The listing already says which entries are photo sets, and a PDF of photographs with no text layer is classified `scan` like any other. One status fewer to explain.
- 2026-09-18, plan: spec §8.2 and §8.3 name two results files from one pass; the plan has `corpus_scan.py --docket` write `s2-threshold.txt` (the curve) and `s2-filter.txt` (the filter table, the hand-check line, and, after Task 17, the submission rule and the published types and rank) in one run. Same numbers, one script.
- 2026-09-18, plan: a reviewed document fixture is committed as the PDF plus its expected extraction (`.txt`), not the text alone (spec §4.4 says "as text"). The extractor test needs the file; the PDF is the document Andy reads. Both are named in the manifest with `reviewed_by`.

### Pre-flight corrections (2026-09-18, before Task 1)

A read-only consistency scan of this plan before execution found four items. Three were
plan defects and are corrected above; one was a false positive and the plan stands.

1. **Task 5, the retry sleeps** — the test's expected list, the code block and the trailing
   note gave three different answers. Corrected to one: `_get` uses `openrouter.py`'s
   net-of-backoff rule, the client keeps `_last_backoff_slept`, and the test expects
   `[1.0, 1.0, 2.0]`.
2. **Task 8, the vulture note** — said `Docket.record` is first used in Task 12. It is
   first used in Task 10, by `attach_docket`. Corrected, so no allow-list entry is left
   standing through Tasks 10 and 11.
3. **Task 16, the fixture subcommands** — `_cmd_draw`, `_cmd_document` and `_cmd_handcheck`
   were defined but never wired into `main`, while Step 4 runs them as subcommands. The
   subparsers, their arguments and the dispatch branches are now written out in Step 3.
4. **Task 3, the aborted run's reservation** — *not* a defect. The scan read
   `settle` as reachable only on the success path and so read
   `test_an_aborted_run_settles_its_reservation` as contradicting decision 0045's "a run
   that dies leaves its reservation standing". `Runner.run` already calls `write_outputs`
   from its `except BaseException:` handler, so a run that unwinds writes its partial cost
   to `run.jsonl` and settles — decision 0045 point 2, "at the end, or on abort". Point 3's
   standing reservation is the run killed outright, where no handler runs and `release`
   is the only way back. The test, the module docstring and the decision agree.
