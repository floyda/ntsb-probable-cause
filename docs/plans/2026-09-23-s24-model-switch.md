# S2.4 — The model switch: implementation plan

**Spec:** docs/specs/2026-09-23-s24-model-switch-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from the specification in the **Deviations** section at the end.

**Goal:** Name the agent's default model and reasoning level once, price GPT-6 Luna, report failures by reason and label cross-model comparisons, then — behind a one-case shape probe and a 1% format gate on `dev-400` — switch the default to `openai/gpt-6-luna` and re-measure the ceiling and arm B once each on `heldout-400`.

**Architecture:** `sources.py` gains `DEFAULT_MODEL`, `DEFAULT_REASONING_EFFORT` and the GPT-6 Luna prices; `ModelSettings` gains an optional `reasoning_effort` that `request_body` sends as `{"reasoning": {"effort": ...}}` only when set, so the judge's calls are unchanged; `RunSpec` carries the level into every call, `spec.json` and `RunRecord`. `report.py` gains `failure_summary` and `comparison_heading`, wired into `ntsb-eval report`. The paid steps are three `make` targets run by Andy. The default model changes value in one line, only after the gate passes.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, httpx + respx, pytest + pytest-socket, ruff, mypy --strict, import-linter. No new dependency.

## Global Constraints

- **One change.** No change to the evidence, the guard, the prompts (`prompt.PROMPT_VERSION` stays as it is) or the scoring. The guard refuses exactly what it refuses today (spec §1).
- Every model call goes through `ModelClient` or `BatchRunner` (0009). Tests never reach the network (`--disable-socket`).
- The agent's calls state `reasoning: {"effort": "medium"}`; the judge's calls send no reasoning key (spec §4.1).
- The gate: at most 1% of `dev-400` cases (4 of 401) fail the reply format — `schema` or `model` failures — each listed by reason. The score is recorded, not gated, unless the paired top-1 interval against GPT-5.6 Luna lies wholly below zero, when the stage stops for Andy (spec §3.2).
- Held-out is touched only in Task 7, once per run, from a clean tree; each run appends its own ledger row (0026). If the probe or the gate fails, held-out is not touched (spec §3.3).
- Numbers reported anywhere come from a script. `data/` is never committed; only summaries go under `docs/results/`.
- `make check` = ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest; coverage gate `--cov-fail-under=90`, branch coverage. Google-style docstrings on every public symbol; line length 100.
- The monthly budget on this branch is $25 (0030).
- Andy runs the paid steps (Tasks 4, 5, 7) from a shell script that exports the key from `pass show api/openrouter` and never prints it.
- Commit messages end with the attribution lines the session gives you. Never commit to `main`. The stage pull request is merged with a merge commit, never squashed (0033).

---

## File structure

| path | responsibility |
|---|---|
| `src/ntsb_probable_cause/sources.py` | + `ReasoningEffort`, `LUNA_6`, `LUNA_6_BATCH`, `DEFAULT_MODEL`, `DEFAULT_REASONING_EFFORT` |
| `src/ntsb_probable_cause/model/client.py` | `ModelSettings.model` from `DEFAULT_MODEL`; + `reasoning_effort`; `RecordingFakeClient.settings` |
| `src/ntsb_probable_cause/model/openrouter.py` | `request_body` sends `reasoning` when set (the batch client reuses it) |
| `src/ntsb_probable_cause/scoring/runner.py` | `RunSpec.model` from `DEFAULT_MODEL`; + `RunSpec.reasoning_effort`; into `spec_json`, `_settings`, the run record |
| `src/ntsb_probable_cause/scoring/records.py` | + `RunRecord.reasoning_effort` (default `None` = not recorded) |
| `src/ntsb_probable_cause/scoring/report.py` | `provenance` shows the level; + `failure_summary`, `comparison_heading` |
| `apps/eval/__main__.py` | `report` prints failures by reason and the comparison heading |
| `Makefile` | + `s24-probe`, `s24-gate`, `s24-bars` |
| `tests/test_sources_settings.py`, `tests/test_openrouter.py`, `tests/test_runner.py`, `tests/test_report.py` | the tests below |
| `docs/results/s24-gate-dev.txt`, `docs/results/s24-bars.txt` | the stage's results |

---

### Task 1: The default model, the reasoning level and GPT-6 Luna's prices, in the model layer (spec §4, §4.1)

**Files:**
- Modify: `src/ntsb_probable_cause/sources.py`
- Modify: `src/ntsb_probable_cause/model/client.py` (`ModelSettings`, `RecordingFakeClient`)
- Modify: `src/ntsb_probable_cause/model/openrouter.py` (`request_body`)
- Test: `tests/test_sources_settings.py`, `tests/test_openrouter.py`

**Interfaces:**
- Produces: `sources.ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]`; `sources.LUNA_6`, `sources.LUNA_6_BATCH` (`ModelPrice`); `sources.DEFAULT_MODEL: str` (value `"openai/gpt-5.6-luna"` until Task 6); `sources.DEFAULT_REASONING_EFFORT: ReasoningEffort = "medium"`; `ModelSettings.reasoning_effort: ReasoningEffort | None = None`; `RecordingFakeClient.settings: list[ModelSettings]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sources_settings.py` (add `from ntsb_probable_cause.model.client import ModelSettings` to its imports if absent):

```python
def test_gpt_6_luna_is_priced_from_the_models_api() -> None:
    """Decision 0073: read from https://openrouter.ai/api/v1/models on 2026-09-22."""
    assert sources.price_of("openai/gpt-6-luna:batch") is sources.LUNA_6_BATCH
    assert sources.price_of("openai/gpt-6-luna") is sources.LUNA_6
    assert (sources.LUNA_6_BATCH.input_usd_per_mtok, sources.LUNA_6_BATCH.output_usd_per_mtok) == (
        0.05,
        0.25,
    )
    assert (sources.LUNA_6.input_usd_per_mtok, sources.LUNA_6.output_usd_per_mtok) == (0.10, 0.50)


def test_the_default_model_and_reasoning_level_are_named_once() -> None:
    """S2.4 spec §4: one constant each, read by ModelSettings (and, from Task 2, RunSpec)."""
    assert sources.DEFAULT_REASONING_EFFORT == "medium"
    assert ModelSettings().model == sources.DEFAULT_MODEL
    assert ModelSettings().reasoning_effort is None  # the judge and probes send no level
```

Append to `tests/test_openrouter.py`:

```python
def test_request_body_states_the_reasoning_level_when_set(
    record_fixtures: list[dict[str, object]],
) -> None:
    """S2.4 spec §4.1: the agent's level is stated, never left to the provider's default."""
    evidence, _, _ = split_record(record_fixtures[0])
    payload = Payload.from_evidence(evidence)
    settings = ModelSettings(reasoning_effort="medium")
    body = request_body(payload, settings, system="s", history=())
    assert body["reasoning"] == {"effort": "medium"}


def test_request_body_sends_no_reasoning_key_when_unset(
    record_fixtures: list[dict[str, object]],
) -> None:
    """The judge's calls (no level set) are byte-for-byte what they were before S2.4."""
    evidence, _, _ = split_record(record_fixtures[0])
    payload = Payload.from_evidence(evidence)
    body = request_body(payload, ModelSettings(), system="s", history=())
    assert "reasoning" not in body
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_sources_settings.py tests/test_openrouter.py -k "gpt_6 or named_once or reasoning" -v`
Expected: FAIL — `AttributeError: module 'ntsb_probable_cause.sources' has no attribute 'LUNA_6_BATCH'` and `ModelSettings` rejecting `reasoning_effort`.

- [ ] **Step 3: Implement**

In `src/ntsb_probable_cause/sources.py`, change the import line to `from typing import Literal` alongside `from dataclasses import dataclass`, and after `LUNA_BATCH` add:

```python
# https://openrouter.ai/api/v1/models, checked 2026-09-22 (decision 0073). The same line as
# GPT-5.6 Luna at about half the price; the default only moves to it after S2.4's gate.
LUNA_6 = ModelPrice("openai/gpt-6-luna", 0.10, 0.50, "OpenRouter models API, 2026-09-22")
LUNA_6_BATCH = ModelPrice(
    "openai/gpt-6-luna:batch", 0.05, 0.25, "OpenRouter models API, 2026-09-22"
)
```

Add `LUNA_6,` and `LUNA_6_BATCH,` to the tuple inside `_PRICES`, after `LUNA_BATCH,`. After `price_of`, add:

```python
# The reasoning levels OpenRouter's model list gives both Luna models
# (``reasoning.supported_efforts``, read 2026-09-23); their default is ``medium``.
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]

# The agent's default model and reasoning level, each named once (decision 0073). The level is
# stated on every agent request rather than left to the provider, whose default could change
# with nothing in a run's record to show it (S2.4 spec §4.1).
DEFAULT_MODEL = "openai/gpt-5.6-luna"
DEFAULT_REASONING_EFFORT: ReasoningEffort = "medium"
```

In `src/ntsb_probable_cause/model/client.py`, `ModelSettings`: change the docstring to `"""Per-call model settings. The default model is decision 0073's."""`, change `model: str = "openai/gpt-5.6-luna"` to `model: str = sources.DEFAULT_MODEL`, and add after `tools`:

```python
    reasoning_effort: sources.ReasoningEffort | None = None
```

In `RecordingFakeClient.__init__` add `self.settings: list[ModelSettings] = []`, and in its `complete` add `self.settings.append(settings)` next to `self.payloads.append(payload)`.

In `src/ntsb_probable_cause/model/openrouter.py`, `request_body`, after the `if settings.tools:` block and before `return body`:

```python
    if settings.reasoning_effort is not None:
        body["reasoning"] = {"effort": settings.reasoning_effort}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_sources_settings.py tests/test_openrouter.py tests/test_batch.py tests/test_model_client.py -v`
Expected: PASS. The batch client builds each line with `request_body`, so it carries the key too.

- [ ] **Step 5: Commit**

```bash
make check
git add src/ntsb_probable_cause/sources.py src/ntsb_probable_cause/model/client.py src/ntsb_probable_cause/model/openrouter.py tests/test_sources_settings.py tests/test_openrouter.py docs/plans/2026-09-23-s24-model-switch.md
git commit -m "S2.4: name the default model and reasoning level once; price GPT-6 Luna (0073)"
```

---

### Task 2: Every agent call states the level, and every run records it (spec §4.1)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`RunSpec`, `spec_json`, `_settings`, `build_record`)
- Modify: `src/ntsb_probable_cause/scoring/records.py` (`RunRecord`)
- Modify: `src/ntsb_probable_cause/scoring/report.py` (`provenance`)
- Test: `tests/test_runner.py`, `tests/test_report.py`, `tests/test_sources_settings.py`

**Interfaces:**
- Consumes: `sources.DEFAULT_MODEL`, `sources.DEFAULT_REASONING_EFFORT`, `sources.ReasoningEffort`, `RecordingFakeClient.settings` (Task 1).
- Produces: `RunSpec.reasoning_effort: sources.ReasoningEffort | None = sources.DEFAULT_REASONING_EFFORT`; `spec.json` key `"reasoning_effort"`; `RunRecord.reasoning_effort: str | None = None`; `provenance` prints `reasoning=<level>` or `reasoning=provider default`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runner.py`:

```python
def test_every_call_states_the_runs_reasoning_level_and_the_run_records_it(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """S2.4 spec §4.1: stated on both stages, written to spec.json and to the run record."""
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.0,
    )
    run = runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert [s.reasoning_effort for s in client.settings] == ["medium", "medium"]
    folder = tmp_path / "runs" / run.run_id
    assert json.loads((folder / "spec.json").read_text())["reasoning_effort"] == "medium"
    assert read_jsonl(folder / "run.jsonl", RunRecord)[-1].reasoning_effort == "medium"
```

Append to `tests/test_report.py`:

```python
def test_provenance_shows_the_reasoning_level(run_record: RunRecord) -> None:
    """A run from before S2.4 never recorded its level; the header says so plainly."""
    assert "reasoning=provider default" in report.provenance(run_record)
    stated = run_record.model_copy(update={"reasoning_effort": "medium"})
    assert "reasoning=medium" in report.provenance(stated)
```

Append to `tests/test_sources_settings.py` (import `RunSpec` from `ntsb_probable_cause.scoring.runner`, and `Path` from `pathlib`, if absent):

```python
def test_run_spec_defaults_come_from_sources() -> None:
    spec = RunSpec(sample="dev-400", arm="ceiling")
    assert spec.model == sources.DEFAULT_MODEL
    assert spec.reasoning_effort == sources.DEFAULT_REASONING_EFFORT


def test_no_module_but_sources_names_a_luna_model() -> None:
    """S2.4 spec §4 item 1: the default lives in one place, so a switch is one line."""
    offenders = [
        str(path)
        for path in Path("src/ntsb_probable_cause").rglob("*.py")
        if path.name != "sources.py" and "-luna" in path.read_text()
    ]
    assert offenders == []
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_runner.py tests/test_report.py tests/test_sources_settings.py -k "reasoning or defaults_come or names_a_luna" -v`
Expected: FAIL — `RunSpec` has no `reasoning_effort`; `runner.py` still names `openai/gpt-5.6-luna`.

- [ ] **Step 3: Implement**

`src/ntsb_probable_cause/scoring/runner.py`, `RunSpec`: replace `model: str = "openai/gpt-5.6-luna"` with

```python
    model: str = sources.DEFAULT_MODEL
    reasoning_effort: sources.ReasoningEffort | None = sources.DEFAULT_REASONING_EFFORT
```

`spec_json`: add `"reasoning_effort": spec.reasoning_effort,` directly after `"model": spec.model,`. (A resume of a run folder written before S2.4 is then refused as a changed spec, which is correct: its calls did not state a level.)

`_settings`:

```python
def _settings(spec: RunSpec, schema: dict[str, object], name: str) -> ModelSettings:
    """Model settings for one call; ``schema`` and ``name`` vary between the two stages."""
    return ModelSettings(
        model=spec.model,
        price_variant=spec.price_variant,
        reasoning_effort=spec.reasoning_effort,
        json_schema=schema,
        schema_name=name,
    )
```

`build_record` (inside `Runner.run`): add `reasoning_effort=spec.reasoning_effort,` after `model=spec.model,`.

`src/ntsb_probable_cause/scoring/records.py`, `RunRecord`: after `model: str` add

```python
    # None on a run from before S2.4, which sent no level and used the provider's default.
    reasoning_effort: str | None = None
```

`src/ntsb_probable_cause/scoring/report.py`, `provenance`: change the second line of the returned string to

```python
        f"sample={record.sample} arm={record.arm} model={record.model} "
        f"reasoning={record.reasoning_effort or 'provider default'} "
        f"price_variant={record.price_variant}\n"
```

If an existing test asserts the old header line exactly, update its expected string to include `reasoning=provider default`; do not change what it checks otherwise.

- [ ] **Step 4: Run the tests to see them pass**

Run: `make check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/scoring/runner.py src/ntsb_probable_cause/scoring/records.py src/ntsb_probable_cause/scoring/report.py tests/test_runner.py tests/test_report.py tests/test_sources_settings.py docs/plans/2026-09-23-s24-model-switch.md
git commit -m "S2.4: every agent call states the reasoning level; every run records it (spec §4.1)"
```

---

### Task 3: Failures by reason, and cross-model comparisons labelled (spec §5, §6)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/report.py` (+ `failure_summary`, `comparison_heading`)
- Modify: `apps/eval/__main__.py` (`_cmd_report`)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `CaseResult.failure: str | None` (strings `"cap"`, `"schema: …"`, `"model: …"`, `"leak: <case>: <kind> from <source> in <role> (N chars withheld)[; …]"`); `RunRecord.model`, `.reasoning_effort`, `.commit_sha`, `.run_id`.
- Produces: `report.failure_summary(results: Sequence[CaseResult]) -> str`; `report.comparison_heading(this: RunRecord, other: RunRecord) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report.py`:

```python
def test_failure_summary_counts_by_reason_and_never_names_a_case() -> None:
    """S2.4 spec §6: the refusal count S2.6 needs, from a script, without case numbers."""
    rows = [
        _case(
            "CEN20LA123",
            failure="leak: CEN20LA123: sentence from analysis_narrative in docket_documents"
            " (80 chars withheld)",
        ),
        _case(
            "ERA21LA161",
            failure="leak: ERA21LA161: sentence from analysis_narrative in docket_documents"
            " (40 chars withheld); sentence from probable_cause in docket_documents"
            " (60 chars withheld)",
        ),
        _case("WPR22FA087", failure="schema: reply is not a Hypothesis"),
        _case("WPR23FA080", failure="cap"),
        _case("WPR20LA001"),
    ]
    text = report.failure_summary(rows)
    assert text == (
        "failures by reason: cap 1, leak (analysis_narrative) 1, "
        "leak (analysis_narrative, probable_cause) 1, schema 1"
    )
    assert not any(case_id in text for case_id in ("CEN20LA123", "ERA21LA161", "WPR22FA087"))


def test_failure_summary_with_no_failures() -> None:
    assert report.failure_summary([_case("WPR20LA001")]) == "failures by reason: none"


def test_comparison_heading_labels_a_cross_model_comparison(run_record: RunRecord) -> None:
    """Decision 0031 item 2: a comparison across models is labelled, with both commits."""
    same = run_record.model_copy(update={"run_id": "other"})
    assert report.comparison_heading(run_record, same) == "against other:"
    other = run_record.model_copy(
        update={
            "run_id": "old",
            "model": "openai/gpt-5.6-luna",
            "commit_sha": "c717ab5",
        }
    )
    this = run_record.model_copy(
        update={"model": "openai/gpt-6-luna", "reasoning_effort": "medium"}
    )
    assert report.comparison_heading(this, other) == (
        f"model comparison (decision 0031 item 2): openai/gpt-6-luna at {this.commit_sha}, "
        "reasoning medium, against openai/gpt-5.6-luna at c717ab5, reasoning provider default "
        "-- run old:"
    )
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_report.py -k "failure_summary or comparison_heading" -v`
Expected: FAIL — `AttributeError: module 'ntsb_probable_cause.scoring.report' has no attribute 'failure_summary'`.

- [ ] **Step 3: Implement**

In `src/ntsb_probable_cause/scoring/report.py` add `import re` and `from collections import Counter` to the imports if absent, and after `cap_summary`:

```python
# The leak message is "<kind> from <source> in <role> (N chars withheld)", joined by "; "
# (records/guard.py ``Leak.__str__``, records/split.py).
_LEAK_SOURCE = re.compile(r"\b\w+ from (\w+) in \w+")


def failure_summary(results: Sequence[CaseResult]) -> str:
    """Failed cases counted by reason, never naming a case (S2.4 spec §6).

    A leak is counted under the withheld sources its message names, so a refusal for an
    analysis-narrative sentence reads apart from one for the probable cause.
    """
    counts: Counter[str] = Counter()
    for result in results:
        if not result.failure:
            continue
        kind = result.failure.split(":", 1)[0].strip()
        if kind == "leak":
            named = sorted(set(_LEAK_SOURCE.findall(result.failure)))
            kind = f"leak ({', '.join(named) or 'unparsed'})"
        counts[kind] += 1
    if not counts:
        return "failures by reason: none"
    return "failures by reason: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))


def comparison_heading(this: RunRecord, other: RunRecord) -> str:
    """The line above a paired comparison; labels one made across models or levels.

    Decision 0031 item 2: a table across models is separate and labelled, never a bar. The
    two commits are printed because such runs were made at different times (S2.4 spec §5).
    """
    if this.model == other.model and this.reasoning_effort == other.reasoning_effort:
        return f"against {other.run_id}:"

    def side(record: RunRecord) -> str:
        level = record.reasoning_effort or "provider default"
        return f"{record.model} at {record.commit_sha}, reasoning {level}"

    return (
        f"model comparison (decision 0031 item 2): {side(this)}, against {side(other)} "
        f"-- run {other.run_id}:"
    )
```

In `apps/eval/__main__.py`, `_cmd_report`: after the line that builds `text = report.provenance(...) + ...`, add

```python
    text += "\n\n" + report.failure_summary(cases)
```

and replace

```python
        text += f"\n\nagainst {other_id}:\n{report.compare(cases, other_cases)}"
```

with

```python
        other_record = answering_run_record(settings.runs_dir / other_id)
        heading = report.comparison_heading(run_record, other_record)
        text += f"\n\n{heading}\n{report.compare(cases, other_cases)}"
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `make check`
Expected: PASS. Existing `report --against` tests compare two runs on one model, so their `against <id>:` line is unchanged; any test asserting the whole report text gains the `failures by reason:` line — update its expected text, nothing else.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/scoring/report.py apps/eval/__main__.py tests/test_report.py tests/test_eval_app.py docs/plans/2026-09-23-s24-model-switch.md
git commit -m "S2.4: the report counts failures by reason and labels cross-model comparisons (spec §5, §6)"
```

---

### Task 4: The shape probe (spec §3.1; Andy runs, under a cent)

**Files:**
- Modify: `Makefile` (+ `s24-probe`, `s24-gate`, `s24-bars`)

- [ ] **Step 1: Add the three targets**

After the `s2-bars` target in `Makefile`:

```make
s24-probe:
	uv run ntsb-eval run --arm ceiling --sample dev-400 --limit 1 --sync --price-variant standard --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
	uv run ntsb-eval run --arm ceiling --sample dev-400 --limit 1 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
# S2.4 spec §3.1: one development case, both stages, standard then batch.

s24-gate:
	uv run ntsb-eval run --arm ceiling --sample dev-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
# S2.4 spec §3.2. About $0.20. The report is made from the explicit run id afterwards.

s24-bars:
	uv run ntsb-eval run --arm ceiling --sample heldout-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
	uv run ntsb-eval run --arm B --sample heldout-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.01
# S2.4 spec §5 -- ONCE, only after the gate has passed; appends two rows to the held-out ledger.
```

Append `s24-probe s24-gate s24-bars` to the `.PHONY` line (line 1 of the `Makefile`). The `--expected-cost-per-case-usd` values are deliberate, conservative estimates (GPT-5.6's measured ceiling cost was about $0.0011 a case and arm B's $0.005); without them the budget guard projects each run at the $0.05 cap.

- [ ] **Step 2: Commit the targets**

```bash
git add Makefile docs/plans/2026-09-23-s24-model-switch.md
git commit -m "S2.4: make targets for the probe, the gate and the held-out bars"
```

- [ ] **Step 3: Andy runs the probe**

From the key-exporting shell script: `make s24-probe`. Note both run ids from the terminal, then:

```bash
uv run ntsb-eval report <sync-probe-run-id>
uv run ntsb-eval report <batch-probe-run-id>
```

**Pass:** both show `failed` `0 of 1` and `failures by reason: none`. **Stop point:** otherwise record what the failure reason says in the Deviations section and stop the stage for Andy. If the reason shows empty content, a different reasoning level is a change to the comparison and is Andy's decision (spec §3.1).

---

### Task 5: The gate on `dev-400` (spec §3.2; Andy runs, about $0.20)

**Files:**
- Create: `docs/results/s24-gate-dev.txt`
- Modify: `docs/decisions/0073-the-default-model-is-gpt-6-luna-behind-a-gate.md` (an appended result note), `docs/decisions/README.md` (its status cell)

- [ ] **Step 1: Andy runs the gate**

From the key-exporting shell script: `make s24-gate`. Note the run id.

- [ ] **Step 2: Write the results file**

```bash
{
  uv run ntsb-eval report <sync-probe-run-id>; echo
  uv run ntsb-eval report <batch-probe-run-id>; echo
  uv run ntsb-eval report <gate-run-id> --against 20260916T032106-179520f-dev-400-ceiling
} > docs/results/s24-gate-dev.txt
```

Expected: two probe tables, the gate table with its `failures by reason:` line, and a `model comparison (decision 0031 item 2): …` block pairing the gate run with the GPT-5.6 Luna ceiling run.

- [ ] **Step 3: Apply the rule**

Format failures are the `schema` and `model` counts on the gate's `failures by reason:` line.

- **Pass:** format failures ≤ 4 of 401, and the paired `occurrence top-1` interval is not wholly below zero. Go to Step 4.
- **Fail on format:** more than 4. Append to 0073 a dated `**Result, <date>:** the gate failed …` note citing the results file, leave the default unchanged, skip Tasks 6 and 7, and go to Task 8, which closes the stage with this negative result.
- **Clearly worse score:** the paired interval's upper end is below zero. Stop and ask Andy; record his decision in the Deviations section before going on.

- [ ] **Step 4: Record the pass and commit**

Append to `docs/decisions/0073-the-default-model-is-gpt-6-luna-behind-a-gate.md`:

```markdown

**Conditions met, <date> (appended; nothing above is edited).** The shape probe passed on the
standard and batch paths, and the gate run failed the reply format on <n> of 401 `dev-400`
cases (`docs/results/s24-gate-dev.txt`); the paired top-1 difference against GPT-5.6 Luna was
<difference and interval, copied from the file>.
```

Change 0073's status cell in `docs/decisions/README.md` from `Accepted, conditional; replaces 0031 item 1` to `Accepted; gate passed <date>; replaces 0031 item 1`.

```bash
git add docs/results/s24-gate-dev.txt docs/decisions/0073-the-default-model-is-gpt-6-luna-behind-a-gate.md docs/decisions/README.md docs/plans/2026-09-23-s24-model-switch.md
git commit -m "S2.4: GPT-6 Luna passes the shape probe and the format gate on dev-400 (spec §3)"
```

---

### Task 6: The switch (spec §4)

**Files:**
- Modify: `src/ntsb_probable_cause/sources.py` (`DEFAULT_MODEL`)
- Test: whichever existing tests encode GPT-5.6 Luna's price through the default model

- [ ] **Step 1: Change the one line**

```python
DEFAULT_MODEL = "openai/gpt-6-luna"
```

- [ ] **Step 2: Run the suite**

Run: `make check`
Expected: the tests of Tasks 1 and 2 pass unchanged. A test whose expected number depends on the default model's *price* (a cost, a cap boundary, a budget projection) now fails, because GPT-6 Luna costs about half as much. Fix each such test by passing `model="openai/gpt-5.6-luna"` explicitly to the `RunSpec` or `ModelSettings` it builds, so it keeps testing what it was written to test; never by changing its expected number. List each test changed in the commit message.

- [ ] **Step 3: Commit**

```bash
git add src/ntsb_probable_cause/sources.py tests/ docs/plans/2026-09-23-s24-model-switch.md
git commit -m "S2.4: the default model is GPT-6 Luna (decision 0073)"
```

---

### Task 7: The bars on `heldout-400`, once each (spec §5; Andy runs, about $1.10)

**Files:**
- Create: `docs/results/s24-bars.txt`
- Modify: `docs/results/heldout-ledger.md` (two rows, appended by the runs)

- [ ] **Step 1: Confirm the tree is clean and the switch is in**

Run: `git status --short` (empty), `make check` (green), and `uv run python -c "from ntsb_probable_cause import sources; print(sources.DEFAULT_MODEL)"` (prints `openai/gpt-6-luna`).

- [ ] **Step 2: Andy runs the two held-out runs**

From the key-exporting shell script: `make s24-bars`. Note both run ids. Expected: exactly two new ledger rows, model `openai/gpt-6-luna`.

- [ ] **Step 3: Write the results file**

```bash
{
  uv run ntsb-eval report <heldout-B-run-id> --against <heldout-ceiling-run-id>; echo
  uv run ntsb-eval report <heldout-B-run-id> --against 20260921T071430-3bc3a51-heldout-400-B; echo
  uv run ntsb-eval report <heldout-ceiling-run-id> --against 20260917T061527-c717ab5-heldout-400-ceiling
} > docs/results/s24-bars.txt
```

Expected, the four comparisons of spec §5: arm B against the ceiling on GPT-6 Luna (`against <id>:`); arm B, and the ceiling, each against GPT-5.6 Luna (`model comparison (decision 0031 item 2): … at <commit> …`, which states both commits — the limit spec §5 requires); and arm B against the no-model baseline, which every `heldout-400` report prints as its `Baseline floor` line. The `failures by reason:` line under arm B is the scripted count of held-out refusals S2.6 cites.

- [ ] **Step 4: Commit**

```bash
git add docs/results/s24-bars.txt docs/results/heldout-ledger.md docs/plans/2026-09-23-s24-model-switch.md
git commit -m "S2.4: the ceiling and arm B on heldout-400 with GPT-6 Luna, the bar until S2.6 (spec §5)"
```

---

### Task 8: Close-out (decision 0017)

- [ ] **Step 1: Documentation**

`CLAUDE.md`, appended rather than rewritten:
- "Model access": the agent's model is `openai/gpt-6-luna`, batch for evaluation, at reasoning level `medium`, stated on every call and recorded on every run (decision 0073, replacing 0031 item 1); GPT-5.6 Luna results are history.
- "Eval bars to beat": an S2.4 paragraph with the GPT-6 Luna figures copied from `docs/results/s24-bars.txt` — ceiling and arm B top-1 and top-3 with intervals, the paired differences, the baseline comparison, and the held-out failures by reason — with the S1 and S2 figures left in place and marked as GPT-5.6 Luna.
- "Commands": `make s24-probe`, `make s24-gate`, `make s24-bars`.

`README.md`: the same three commands beside `make s2-bars`.

If the gate failed (Task 5), write instead: the default stays GPT-5.6 Luna, and why, citing `docs/results/s24-gate-dev.txt`.

- [ ] **Step 2: Run the close-stage skill**

Invoke `close-stage`: it appends the As-built record (Delivered; Done means, with evidence, one line per spec §11 item; Departures, from the Deviations below; Decisions taken during the stage; Implementation record with the total spend from `month_spent` over the S2.4 run records), marks the specification Implemented, marks the roadmap's S2.4 entry done, deletes this plan, and runs `scripts/check_docs.py`. Set `version` in `pyproject.toml` to the next minor above `main`'s at merge time: `0.4.0` if `main` is still at `0.3.0`, otherwise one minor higher.

- [ ] **Step 3: Pull request**

Title `S2.4: the model switch`. Merge with a merge commit, never squash (0033). After the merge Andy runs `gh release create v<version> --generate-notes`.

---

## Deviations

*Log every departure from the specification here, dated, with the reason. Moved into the As-built record at close-out (decision 0017).*

- 2026-09-23, plan: the shape probe (spec §3.1) is run through `ntsb-eval run --limit 1` rather than a separate probe script. It sends exactly the two-stage exchange the gate and the bars send, through the same code, so it tests the shape that matters; a separate script would test a copy.
- 2026-09-23, plan: spec §7's last item — the shape probe's replies recorded as fixtures — is not
  done. The probe runs through `ntsb-eval run`, which records no raw replies, and the offline
  tests need none: GPT-6 Luna is reached through the same request and reply shapes as the
  fixtures already under `tests/fixtures/openrouter/`, and Task 1's tests pin the one new field in
  the request. If the probe shows a reply shape those fixtures do not cover, record one then.
- 2026-09-23, plan: spec §5's four comparisons are written to `s24-bars.txt` as three `report` invocations; the fourth, against the no-model baseline, is the `Baseline floor` line every `heldout-400` report already prints.
