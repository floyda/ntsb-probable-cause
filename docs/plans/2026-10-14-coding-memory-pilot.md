# Coding memory pilot — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick each task's boxes in the same commit as its code (rule 10), and log every departure under **Deviations** at the end.

**Goal:** Build and run the coding-memory pilot: a learner on the Claude API writes coding lessons from development verdicts for event years 2009 and 2010, and a coding test on GPT-6 Luna measures whether those lessons beat the coding tools' counts on finding recall@10, by the stop rule Andy registered.

**Architecture:** A new library package `ntsb_probable_cause.memory` holds what a later version would reuse: the lesson and snapshot formats, their three checks and stamp, the learning-part reader, the support counts and cap, the learner's prompts, and the gated Claude client. Committed scripts drive it: the shape probe, the learner (`propose`, `agreement`, `finish`), the local snapshot check, the coding test (`answer`, `tools`) and the pilot's reading. The coding test reuses arm B's fixed tool post-pass (`agent.armb.FixedToolsLoop`) and the batch driver (`agent.drive.drive_batch`) from a script, so nothing in the library imports the agent. Nothing connects the memory to Ellery version 1, `ntsb-eval run`, S4 or the board.

**Tech Stack:** Python 3.14, uv, pydantic 2, pyarrow, the official `anthropic` Python SDK (new runtime dependency, Task 0 and Task 10), the existing OpenRouter transport for GPT-6 Luna, pytest, import-linter, grimp.

**Spec:** docs/specs/2026-10-08-coding-memory-design.md

Decisions this plan implements: 0200 to 0204, and three written in Task 0 (numbers 205 to 207 of the agreed block), which this plan's review asks Andy to approve.

## Global Constraints

- Learning part only: the S3 pool less `dev-400`, `dev-seal-400`, `dev-seal-s3-400` and `dev-steer-400`; never held-out, open, live or sealed cases (0200, 0024).
- The answering agent never reads a verdict. The coding test reads `dev-steer-400` only in this plan; `dev-400` is not read (0204: milestones belong to the full pass).
- Ellery version 1 is untouched: never edit `scoring/guidance/r3-loc-stall.md`, `r6-aircraft-control.md`, the code tables, `scoring/tables/coding_stats_s3.json`, or model-facing text in `agent/` or `model/tool_text.py` (S4, 2026-10-14). `make s33-continuity` must still report `+t` unchanged at the end.
- Learner models and effort: `claude-sonnet-5-5` at effort `high` (propose, revise, agreement reference); `claude-haiku-5-5` at effort `low`, `medium` on the one retry (apply) (0202). Every call states effort; thinking stays at the model default (adaptive); no `budget_tokens`; no forced `tool_choice`; structured output via `output_config.format`.
- No refusal fallbacks on learner calls: a refused call is recorded as failed, so every lesson keeps the model that wrote it (decision 207).
- Coding test: `openai/gpt-6-luna`, batch, reasoning `medium`, max output tokens 8,000, guidance `r3-loc-stall` and `r6-aircraft-control` in every condition, statistics `mem` (0204, 0203).
- Memory cap: 6,000 estimated tokens, where a token is estimated as characters ÷ 4 (`ceil(len(text) / 4)`), the project's estimate (0201).
- Lesson statements and scopes contain no digits, and every word with a capital letter is on `memory/allowed_words.txt`; every number a model reads in the memory is written by the counting step (0201, rule 3).
- Copying rule: no run of 8 or more words shared with any pool probable-cause sentence (0201). Withheld-text rule: no sentence of 30 or more characters shared with any development case's factual narrative, analysis narrative or probable cause (0201, as `scripts/check_guidance.py`).
- Agreement bar: 90% of case-and-lesson pairs that either model marks; sample of 100 learning-part cases from 2009 drawn with `random.Random(20261014)` (0204).
- Stop rule: pass only if memory − counts(a) on finding recall@10 exceeds |counts(b) − counts(a)| on finding recall@10, and memory − counts(a) on occurrence top-1 and on top-3 are each no lower than −|counts(b) − counts(a)| on that measure; failed cases count as wrong (0204, 0136). The registration in Task 15 fixes this wording before any memory condition runs.
- Spend: Claude calls count against `NTSB_LEARNING_MONTHLY_BUDGET_USD` (default 90), never against the $40 OpenRouter guard; OpenRouter coding tests count against the $40 guard and the side track's $10 line, `scripts.stage_spend --stage mem` (decision 207).
- Rule 2: model ids, request and reply shapes are confirmed by the shape probe (Task 11) before any learner run; the SDK calls follow Anthropic's Python SDK reference, never memory.
- Counts only in anything committed: no case numbers, no case text, in results files (0024 applies to open cases; the project applies the same habit to development results).

## Review Focus

- A probable-cause sentence that names a person, place, date or aircraft must never survive into a lesson: the identifier check (Task 7) and the propose prompt (Task 10) both hold it; Task 7 tests a statement with a registration, a date and a capitalised surname.
- The apply step must judge a lesson from the cause sentence alone, never from the case's codes, or agreement is circular: Task 10's `apply_user` takes only the cause, and its test asserts no code appears in the user text.
- A crash or refusal mid-period must not spend twice or lose work: the reply cache (Task 10) returns a recorded reply for an identical request, and a refused or truncated reply is recorded as a failure, not raised; Task 10 tests both.
- A snapshot edited after it was checked must be refused, in CI and at run time: Task 7 tests a one-character edit against its stamp.
- A run that pairs `dev-steer-400` with S3's statistics must be refused, because S3's statistics hold the slice's verdicts: Task 2 tests `refuse_pool_holding("s3", "dev-steer-400")` raises and `("mem", ...)` does not.

---

## Files

**Create (library):**
- `src/ntsb_probable_cause/memory/__init__.py` — package docstring only.
- `src/ntsb_probable_cause/memory/lessons.py` — `Prediction`, `Support`, `Lesson`, `Memory`, `estimated_tokens`, `render_lesson`, `render_memory`, `render_for_apply`.
- `src/ntsb_probable_cause/memory/checks.py` — identifier, withheld-text and copying checks; `Stamp`.
- `src/ntsb_probable_cause/memory/snapshots.py` — save, stamp paths, `load_checked`.
- `src/ntsb_probable_cause/memory/allowed_words.txt` — capitalised words a statement may use.
- `src/ntsb_probable_cause/memory/snapshots/.gitkeep` — snapshot directory.
- `src/ntsb_probable_cause/memory/pool.py` — `LearningCase`, `learning_part`.
- `src/ntsb_probable_cause/memory/curate.py` — agreement with a case, support counts, revision and cap rules, model agreement.
- `src/ntsb_probable_cause/memory/prompts.py` — learner system texts, case rendering, reply models, the coding test's preface.
- `src/ntsb_probable_cause/memory/claude.py` — `Call`, `Reply`, `LearningClient` (sync and batch), `cost_usd`.

**Create (scripts):** `scripts/memory_shape_probe.py`, `scripts/memory_learn.py`, `scripts/memory_check.py`, `scripts/memory_coding_test.py`, `scripts/memory_pilot_result.py`.

**Create (records and data):** decisions 205–207 (`docs/decisions/0205-…`, `0206-…`, `0207-…`), `tests/fixtures/eval/dev_steer_400_ids.csv`, `src/ntsb_probable_cause/scoring/tables/coding_stats_mem.json`, `docs/results/mem-coding-stats.txt`, `docs/results/memory-shape-probe.txt`, `docs/results/memory-agreement-dev.txt`, `docs/rounds/memory-pilot.md`, `docs/results/memory-pilot-dev.txt`, two snapshots and their stamps.

**Modify:** `src/ntsb_probable_cause/scoring/samples.py`, `scoring/coding_stats.py`, `scoring/budget.py`, `settings.py`, `sources.py`, `model/client.py`, `scripts/draw_sealed.py`, `scripts/coding_stats.py`, `scripts/stage_spend.py`, `scripts/paid_run.sh`, `scripts/README.md`, `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example`, `tests/fixtures/eval/README.md`, `CLAUDE.md`, the design note.

**Tests:** `tests/test_memory_lessons.py`, `test_memory_checks.py`, `test_memory_snapshots.py`, `test_memory_pool.py`, `test_memory_curate.py`, `test_memory_prompts.py`, `test_memory_claude.py`, `test_memory_learn.py`, `test_memory_coding_test.py`, `test_memory_pilot_result.py`, `test_memory_shape_probe.py`; additions to `test_samples.py`, `test_contamination.py`, `test_draw_sealed.py`, `test_coding_stats.py`, `test_coding_stats_script.py`, `test_budget.py`, `test_settings.py`, `test_sources.py`, `test_boundary.py`, `test_import_boundaries.py`, `test_stage_spend.py`, `test_paid_run.py`.

---

### Task 0: The three decisions this plan needs

These come from the code survey of 2026-10-14 and are written only after Andy approves them with this plan.

**Files:**
- Create: `docs/decisions/0205-the-coding-tests-payload-is-a-declared-exception-to-the-request-boundary.md`
- Create: `docs/decisions/0206-the-steering-slice-is-named-dev-steer-400.md`
- Create: `docs/decisions/0207-the-pilots-money-and-tooling.md`
- Modify: `docs/decisions/README.md` (three index rows), `docs/specs/2026-10-08-coding-memory-design.md` (§10 list; `pool-steer-400` → `dev-steer-400` in §5 and the glossary, with a note naming 206)

- [x] **Step 1: Write 0205.** Context: `model/client.py`'s `Payload` is built only from evidence or one page (0016's request-side boundary), so the coding test of 0204 cannot send the NTSB probable-cause sentence to GPT-6 Luna without either a declared exception or a hidden workaround (the sentence in the system text beside a dummy payload). Decision: (1) `Payload.for_coding_test(cause: str)` renders `{"ntsb_probable_cause": cause}` and nothing else; (2) only `scripts/memory_coding_test.py` calls it, proven by a test that scans every Python file under `src/`, `apps/` and `scripts/` for the name; (3) it amends 0016 for this one role and 0200 item 2 is its authority. Why: a named door is visible and testable; a workaround in system text would pass the boundary silently. Rules out: the workaround; running the coding test on Claude (0204 chose the product's model). Status: Accepted; amends 0016 for the coding test only. Approved by Andy, 2026-10-15.
- [x] **Step 2: Write 0206.** Context: `samples.refuse_unless_development` refuses a sample whose name does not start with `dev`, and `coding_stats.refuse_pool_holding` checks only samples starting with `dev`; under 0203's name `pool-steer-400` a run could pair the slice with S3's statistics, which hold the slice's verdicts, and no guard would refuse it. Decision: the steering slice is `dev-steer-400` (amends 0203 item 1's name; its seed, draw and use are unchanged). Why: the existing guards then refuse `("s3", "dev-steer-400")` and allow `("mem", "dev-steer-400")`. Rules out: keeping the name and widening both guards (two edits to shared code, and every later guard would need to remember a second prefix). Status: Accepted; amends 0203 item 1. Approved by Andy, 2026-10-15.
- [x] **Step 3: Write 0207.** Decision items: (1) the official `anthropic` Python SDK is a runtime dependency, imported only by `memory/claude.py` (a grimp test proves it), because rule 2 says wire shapes come from the provider's documentation and the SDK is its documented interface; 0097's plain-HTTP choice was for a vendor whose SDK was not needed; (2) learner spend rows are kind `learning`, counted against a separate monthly line, `NTSB_LEARNING_MONTHLY_BUDGET_USD`, default $90 (under the $100 credit, leaving a margin for the gap between a reply and its billing), checked under the budget lock before each job; the $40 OpenRouter guard never counts them; the Console workspace's spend limit is the hard stop; (3) coding-test spend rows are kind `coding-test`, counted by the $40 guard and by a side-track line of $10, `scripts.stage_spend --stage mem`, counted by commit on branches named `coding-memory*` holding the branch's first commit `938bd83`; (4) learner calls send no refusal fallback, so every lesson keeps the model that wrote it; a refused call is a failed call, recorded with its `stop_details` category, and the pilot's reading counts refusals by category. Context for item 4 (Anthropic's model-migration guidance, as bundled with the claude-api skill, read 2026-10-15): Anthropic advises opting in to `fallbacks: "default"` by default; on Sonnet 5.5 it retries only `cyber` and `frontier_llm` declines, on Sonnet 5 without Sonnet 5.5's thinking; Haiku 5.5 has no server-side fallback; the learner's prompts never ask the model to write out its reasoning, which invites `reasoning_extraction` declines. The wire names here are confirmed against the shape probe's saved replies before use (rule 2). Rules out: plain HTTP (more wire detail to get right by hand); counting credit spend against the $40 line (it would crowd out S4 development runs for money that is not the project's). Status: Accepted; amends 0097's precedent for this transport only. Approved by Andy, 2026-10-15.
- [x] **Step 4: Index rows, note edits, check.**

Run: `uv run python -m scripts.check_docs`
Expected: no output, exit 0.

- [x] **Step 5: Commit.**

```bash
git add docs/decisions/0205-*.md docs/decisions/0206-*.md docs/decisions/0207-*.md docs/decisions/README.md docs/specs/2026-10-08-coding-memory-design.md docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: decisions 0205 to 0207 (payload door, slice name, money and tooling)"
```

---

### Task 1: The steering slice `dev-steer-400`

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/samples.py:18-25`
- Modify: `scripts/draw_sealed.py:47` (the `DRAWS` dict)
- Create: `tests/fixtures/eval/dev_steer_400_ids.csv` (drawn in Step 6)
- Modify: `tests/fixtures/eval/README.md`, `Makefile`
- Test: `tests/test_samples.py`, `tests/test_contamination.py`, `tests/test_draw_sealed.py`

**Interfaces:**
- Produces: sample name `"dev-steer-400"` in `samples.SAMPLES`; `samples.sample_ids("dev-steer-400") -> tuple[str, ...]`; it is **not** in `samples.SEALED`.

- [x] **Step 1: Write the failing tests.**

```python
# tests/test_samples.py (append)
def test_the_steering_slice_is_a_development_sample_and_not_sealed() -> None:
    assert "dev-steer-400" in samples.SAMPLES
    assert "dev-steer-400" not in samples.SEALED
    assert samples.sample_path("dev-steer-400").name == "dev_steer_400_ids.csv"


# tests/test_draw_sealed.py (append)
def test_the_steering_slice_draw_is_seeded_and_excludes_every_sample() -> None:
    plan = draw_sealed.DRAWS["dev-steer-400"]
    assert plan.seed == 20261014
    assert set(plan.excluded) == {"dev-400", "dev-seal-400", "dev-seal-s3-400"}
```

```python
# tests/test_contamination.py (append, beside the sealed-sample tests at :79/:90)
def test_the_steering_slice_is_development_only_and_disjoint(eval_ids) -> None:
    steer = eval_ids["dev_steer_400_ids"]
    assert 395 <= len(steer) <= 405
    assert all(split_of(d) is Split.DEV for _, d in steer)
    ids = {i for i, _ in steer}
    for other in ("dev_400_ids", "dev_seal_400_ids", "dev_seal_s3_400_ids", "heldout_400_ids"):
        assert not ids & {i for i, _ in eval_ids[other]}
```

Use the same `eval_ids` shape the neighbouring tests use (read them first; if they hold bare ids, adapt the two comprehensions to that shape).

- [x] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_samples.py tests/test_draw_sealed.py -k steer -v`
Expected: FAIL (`dev-steer-400` not in `SAMPLES`; `KeyError` in `DRAWS`). The contamination test errors until the csv exists (Step 6).

- [x] **Step 3: Implement.** In `samples.py` add `"dev-steer-400"` to `SAMPLES` and `"dev-steer-400": "dev_steer_400_ids.csv"` to `_FILES`, with a comment `# Decisions 0203, 0206: the coding memory's steering slice; read only by its coding test.` In `draw_sealed.py` add `"dev-steer-400": Draw(seed=20261014, excluded=("dev-400", "dev-seal-400", "dev-seal-s3-400"))` and update the module docstring's Status block to name decision 0203 and 0206. Add to the `Makefile`, beside `s3-draw-sealed`:

```make
mem-draw-steer: ## Draw dev-steer-400 once (seed 20261014, decisions 0203, 0206); free
	uv run python -m scripts.draw_sealed --sample dev-steer-400
```

- [x] **Step 4: Run the unit tests.**

Run: `uv run pytest tests/test_samples.py tests/test_draw_sealed.py -v`
Expected: PASS.

- [x] **Step 5: Draw the slice (free, local data).**

Run: `make mem-draw-steer` then `uv run python -m scripts.draw_sealed --sample dev-steer-400 --verify`
Expected: the csv written with 400 rows (200 fatal, 200 non-fatal) and counts by year printed; `--verify` reports it matches.

- [x] **Step 6: Record it and run the contamination test.** Add a paragraph to `tests/fixtures/eval/README.md`: drawn 2026-10-14 by `make mem-draw-steer`, `samples.draw` seed 20261014 from the development split excluding `dev-400`, `dev-seal-400`, `dev-seal-s3-400`; not sealed; read only by the coding memory's coding test (decisions 0203, 0206).

Run: `uv run pytest tests/test_contamination.py -v`
Expected: PASS.

- [x] **Step 7: Commit.**

```bash
git add src/ntsb_probable_cause/scoring/samples.py scripts/draw_sealed.py tests/fixtures/eval/dev_steer_400_ids.csv tests/fixtures/eval/README.md Makefile tests/test_samples.py tests/test_contamination.py tests/test_draw_sealed.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the steering slice dev-steer-400 (decisions 0203, 0206)"
```

---

### Task 2: The statistics file `mem`

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/coding_stats.py:25-36` and the `load_stats` docstring
- Modify: `scripts/coding_stats.py:67` (`STAGES`)
- Create: `src/ntsb_probable_cause/scoring/tables/coding_stats_mem.json`, `docs/results/mem-coding-stats.txt` (built in Step 5)
- Modify: `Makefile`
- Test: `tests/test_coding_stats.py:171,181,203`, `tests/test_coding_stats_script.py:131-145`

**Interfaces:**
- Produces: `StatsName = Literal["s27", "s3", "mem"]`; `load_stats("mem") -> CodingStats`; `POOL_EXCLUDED["mem"] == ("dev-400", "dev-seal-400", "dev-seal-s3-400", "dev-steer-400")`.

- [x] **Step 1: Write the failing tests.**

```python
# tests/test_coding_stats.py
def test_the_memory_statistics_leave_out_the_steering_slice() -> None:
    assert coding_stats.STATS_NAMES == ("s27", "s3", "mem")
    assert coding_stats.POOL_EXCLUDED["mem"] == (
        "dev-400", "dev-seal-400", "dev-seal-s3-400", "dev-steer-400",
    )


def test_s3_statistics_refuse_the_steering_slice_and_mem_allows_it() -> None:
    with pytest.raises(ConfigurationError):
        coding_stats.refuse_pool_holding("s3", "dev-steer-400")
    coding_stats.refuse_pool_holding("mem", "dev-steer-400")
```

Update the existing assertions at `:171` (add the `mem` row), `:181` (parametrise over `["s27", "s3", "mem"]`) and `:203` (the three names), and the stage checks in `tests/test_coding_stats_script.py:131-145` to include `mem` with a `built_from` that names all four excluded samples.

- [x] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_coding_stats.py tests/test_coding_stats_script.py -v`
Expected: FAIL on the new names.

- [x] **Step 3: Implement.** Add `"mem"` to the Literal, `"mem": "tables/coding_stats_mem.json"` to `_RESOURCES`, the `POOL_EXCLUDED["mem"]` tuple above, and a `STAGES["mem"]` in `scripts/coding_stats.py` mirroring `s3`'s with the fourth exclusion, `json_out` pointing at the new file and `built_from` naming the four samples and decisions 0203 and 0206. Never rebuild the `s3` file (version 1's fingerprint covers it). Add:

```make
mem-coding-stats: ## The coding memory's statistics: S3's pool less dev-steer-400 (0203); free
	uv run python -m scripts.coding_stats --stage mem --out docs/results/mem-coding-stats.txt
```

- [x] **Step 4: Run the tests.**

Run: `uv run pytest tests/test_coding_stats.py tests/test_coding_stats_script.py -v`
Expected: PASS except any test that loads the json before it exists; build it next.

- [x] **Step 5: Build the file (free).**

Run: `make mem-coding-stats`
Expected: `coding_stats_mem.json` written; the report's first lines name 400 fewer pool cases than `docs/results/s3-coding-stats.txt` (12,090 less those of the slice inside the pool; the slice is drawn from the same split and classes, so expect 11,690).

Run: `uv run pytest tests/test_coding_stats.py tests/test_coding_stats_script.py -v && make s33-continuity`
Expected: PASS; `s33-continuity` reports `+t` unchanged.

- [x] **Step 6: Commit.**

```bash
git add src/ntsb_probable_cause/scoring/coding_stats.py scripts/coding_stats.py src/ntsb_probable_cause/scoring/tables/coding_stats_mem.json docs/results/mem-coding-stats.txt Makefile tests/test_coding_stats.py tests/test_coding_stats_script.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: statistics without the steering slice (decision 0203)"
```

---

### Task 3: Spend kinds, the learning line, the key and the side track's line

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/budget.py:40` (kind Literal), `month_spent`, new `learning_month_spent`, `check_learning_budget`
- Modify: `src/ntsb_probable_cause/settings.py` (two fields, one method), `.env.example`
- Modify: `scripts/stage_spend.py` (`STAGES["mem"]`), `Makefile`
- Test: `tests/test_budget.py`, `tests/test_settings.py`, `tests/test_stage_spend.py`

**Interfaces:**
- Produces: `SpendRecord.kind` accepts `"learning"` and `"coding-test"`; `budget.learning_month_spent(runs_dir: Path, *, now: datetime) -> float`; `budget.check_learning_budget(runs_dir: Path, projected_usd: float, budget_usd: float, *, now: datetime) -> None` (raises `BudgetError`); `Settings.anthropic_api_key: SecretStr | None` (alias `ANTHROPIC_API_KEY`); `Settings.learning_monthly_budget_usd: float = 90.0`; `Settings.require_anthropic_key() -> str`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_budget.py
def _row(kind: str, cost: float, when: datetime) -> SpendRecord:
    return SpendRecord(job_id=f"job-{kind}", kind=kind, model="m", started=when, calls=1,
                       cost_usd=cost, commit_sha="abc1234", dirty=False)


def test_learning_spend_is_counted_apart_from_the_monthly_guard(tmp_path: Path) -> None:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    write_spend(tmp_path, _row("learning", 3.0, now))
    write_spend(tmp_path, _row("coding-test", 0.5, now))
    assert month_spent(tmp_path, now=now) == pytest.approx(0.5)
    assert learning_month_spent(tmp_path, now=now) == pytest.approx(3.0)


def test_the_learning_line_refuses_a_job_that_would_pass_it(tmp_path: Path) -> None:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    write_spend(tmp_path, _row("learning", 89.0, now))
    check_learning_budget(tmp_path, 0.9, 90.0, now=now)
    with pytest.raises(BudgetError):
        check_learning_budget(tmp_path, 1.5, 90.0, now=now)


# tests/test_settings.py
def test_the_anthropic_key_and_the_learning_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.learning_monthly_budget_usd == 90.0
    with pytest.raises(ConfigurationError):
        s.require_anthropic_key()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert Settings(_env_file=None).require_anthropic_key() == "k"


# tests/test_stage_spend.py
def test_the_side_track_has_its_own_ten_dollar_line() -> None:
    stage = stage_spend.STAGES["mem"]
    assert stage.line_usd == 10.0
    assert stage.first == "938bd83"
    assert stage.prefix == "coding-memory"
```

Match the constructor and helper names already used in each test file (read the file's head first; `month_spent`'s month boundary helper, `SpendRecord` fields and `Settings(_env_file=None)` are as the survey found them).

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_budget.py tests/test_settings.py tests/test_stage_spend.py -v`
Expected: FAIL (unknown kind, missing functions, missing stage).

- [ ] **Step 3: Implement.** In `budget.py`: extend the kind Literal to `Literal["inventory", "transcriber-test", "transcription", "probe", "learning", "coding-test"]` with a comment naming decision 207; in `month_spent`, skip rows whose `kind == "learning"` (comment: "credit spend has its own line, decision 207"); add:

```python
LEARNING: Final = "learning"


def learning_month_spent(runs_dir: Path, *, now: datetime) -> float:
    """The month's learner spend: every ``learning`` spend row in ``now``'s month (decision 207)."""
    return sum(
        row.cost_usd
        for row in _spend_rows(runs_dir)
        if row.kind == LEARNING and _same_month(row.started, now)
    )


def check_learning_budget(
    runs_dir: Path, projected_usd: float, budget_usd: float, *, now: datetime
) -> None:
    """Refuse a learner job that would take the month's learner spend past its line (207).

    Checked under the budget lock so two jobs cannot both pass on the same remainder. No
    reservation is written: learner jobs run one at a time, and the Console workspace's spend
    limit is the hard stop.

    Raises:
        BudgetError: spent this month plus ``projected_usd`` exceeds ``budget_usd``.
    """
    with budget_lock(runs_dir):
        spent = learning_month_spent(runs_dir, now=now)
        if spent + projected_usd > budget_usd:
            raise BudgetError(
                f"learner spend ${spent:.4f} this month plus ${projected_usd:.4f} projected "
                f"would pass the learning line of ${budget_usd:.2f} (decision 207)"
            )
```

`_spend_rows` and `_same_month` stand for whatever `month_spent` already uses to read rows and compare months; reuse those exact helpers (extract them into named functions if `month_spent` inlines them, without changing its behaviour for other kinds).

In `settings.py` add `anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")`, `learning_monthly_budget_usd: float = 90.0`, and `require_anthropic_key()` mirroring `require_typesafe_key()`. Add `ANTHROPIC_API_KEY=` and `NTSB_LEARNING_MONTHLY_BUDGET_USD=` to `.env.example` with a comment naming 0202 and 207. In `stage_spend.py` add `"mem": Stage(name="mem", base="main", first="938bd83", line_usd=10.0, prefix="coding-memory", line_rule=..., count_rule=...)`, filling `line_rule` and `count_rule` with the same kind of values `s33` uses (read it), and a docstring line naming decision 207. Add:

```make
mem-spend: ## The side track's OpenRouter spend so far; exit 1 past the $10 line (207); free
	uv run python -m scripts.stage_spend --stage mem --estimate $(EST)
```

- [ ] **Step 4: Run the tests.**

Run: `uv run pytest tests/test_budget.py tests/test_settings.py tests/test_stage_spend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/ntsb_probable_cause/scoring/budget.py src/ntsb_probable_cause/settings.py .env.example scripts/stage_spend.py Makefile tests/test_budget.py tests/test_settings.py tests/test_stage_spend.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the learning line, the coding-test kind and the side track's line (decision 0207)"
```

---

### Task 4: Claude's direct-API prices

**Files:**
- Modify: `src/ntsb_probable_cause/sources.py` (new dataclass and four entries)
- Test: `tests/test_sources.py`

**Interfaces:**
- Produces: `sources.ClaudePrice` (frozen dataclass: `model_id: str`, `batch: bool`, `input_usd_per_mtok: float`, `output_usd_per_mtok: float`, `cache_write_usd_per_mtok: float`, `cache_read_usd_per_mtok: float`, `source: str`); `sources.claude_price(model_id: str, *, batch: bool) -> ClaudePrice` (raises `KeyError`); `sources.HAIKU_55_PROMPT_LIMIT: Final = 100_000`.

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_sources.py
def test_claude_direct_prices_as_published_on_2026_10_08() -> None:
    sonnet = sources.claude_price("claude-sonnet-5-5", batch=False)
    assert (sonnet.input_usd_per_mtok, sonnet.output_usd_per_mtok) == (2.0, 10.0)
    assert (sonnet.cache_write_usd_per_mtok, sonnet.cache_read_usd_per_mtok) == (2.5, 0.10)
    sonnet_b = sources.claude_price("claude-sonnet-5-5", batch=True)
    assert (sonnet_b.input_usd_per_mtok, sonnet_b.output_usd_per_mtok) == (1.0, 5.0)
    assert (sonnet_b.cache_write_usd_per_mtok, sonnet_b.cache_read_usd_per_mtok) == (1.25, 0.05)
    haiku = sources.claude_price("claude-haiku-5-5", batch=False)
    assert (haiku.input_usd_per_mtok, haiku.output_usd_per_mtok) == (0.10, 0.50)
    assert (haiku.cache_write_usd_per_mtok, haiku.cache_read_usd_per_mtok) == (0.125, 0.01)
    haiku_b = sources.claude_price("claude-haiku-5-5", batch=True)
    assert (haiku_b.input_usd_per_mtok, haiku_b.output_usd_per_mtok) == (0.05, 0.25)
    assert (haiku_b.cache_write_usd_per_mtok, haiku_b.cache_read_usd_per_mtok) == (0.0625, 0.005)
    assert sources.HAIKU_55_PROMPT_LIMIT == 100_000
    with pytest.raises(KeyError):
        sources.claude_price("anthropic/claude-sonnet-5", batch=False)
```

- [ ] **Step 2: Run it to see it fail.**

Run: `uv run pytest tests/test_sources.py -k claude_direct -v`
Expected: FAIL (`AttributeError: ClaudePrice`).

- [ ] **Step 3: Implement.**

```python
# Anthropic's direct API, for the coding memory's learner only (decisions 0202, 207). The ids are
# Anthropic's own, distinct from OpenRouter's ``anthropic/...`` ids above. Source: Anthropic's
# pricing page, read 2026-10-08: Sonnet 5.5 $2 / $10, 5-minute cache writes $2.50, cache hits
# $0.10 (0.05x); Haiku 5.5 up to 100,000 prompt tokens $0.10 / $0.50, writes $0.125, hits $0.01
# (0.1x); the Batch API halves every rate, and the multipliers stack.
CLAUDE_PRICING_SOURCE: Final = "Anthropic pricing page, read 2026-10-08"
HAIKU_55_PROMPT_LIMIT: Final = 100_000


@dataclass(frozen=True)
class ClaudePrice:
    """One Claude model's direct-API price per million tokens, standard or batch."""

    model_id: str
    batch: bool
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    cache_write_usd_per_mtok: float
    cache_read_usd_per_mtok: float
    source: str


_CLAUDE_PRICES: Final = (
    ClaudePrice("claude-sonnet-5-5", False, 2.0, 10.0, 2.5, 0.10, CLAUDE_PRICING_SOURCE),
    ClaudePrice("claude-sonnet-5-5", True, 1.0, 5.0, 1.25, 0.05, CLAUDE_PRICING_SOURCE),
    ClaudePrice("claude-haiku-5-5", False, 0.10, 0.50, 0.125, 0.01, CLAUDE_PRICING_SOURCE),
    ClaudePrice("claude-haiku-5-5", True, 0.05, 0.25, 0.0625, 0.005, CLAUDE_PRICING_SOURCE),
)


def claude_price(model_id: str, *, batch: bool) -> ClaudePrice:
    """The recorded direct-API price for ``model_id``.

    Raises:
        KeyError: no price is recorded for that model and variant.
    """
    for price in _CLAUDE_PRICES:
        if price.model_id == model_id and price.batch is batch:
            return price
    raise KeyError(f"no Claude direct-API price recorded for {model_id} (batch={batch})")
```

- [ ] **Step 4: Run the test.**

Run: `uv run pytest tests/test_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/ntsb_probable_cause/sources.py tests/test_sources.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: Claude direct-API prices, read 2026-10-08 (decisions 0202, 0207)"
```

---

### Task 5: The coding test's payload door

**Files:**
- Modify: `src/ntsb_probable_cause/model/client.py:57-114` (`Payload.for_coding_test`, class docstring, `TypeError` message)
- Test: `tests/test_boundary.py`

**Interfaces:**
- Produces: `Payload.for_coding_test(cause: str) -> Payload`, whose text is `json.dumps({"ntsb_probable_cause": cause}, indent=1, ensure_ascii=False)` and whose `fields()` is `{"ntsb_probable_cause": cause}`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_boundary.py
CODING_TEST_CALLER = Path("scripts/memory_coding_test.py")


def test_the_coding_test_payload_holds_the_cause_and_nothing_else() -> None:
    payload = Payload.for_coding_test("Loss of control during the landing roll.")
    assert payload.fields() == {"ntsb_probable_cause": "Loss of control during the landing roll."}


def test_only_the_coding_test_script_opens_the_coding_test_door() -> None:
    callers = sorted(
        path
        for root in (Path("src"), Path("apps"), Path("scripts"))
        for path in root.rglob("*.py")
        if "for_coding_test" in path.read_text()
    )
    assert callers in (
        [Path("src/ntsb_probable_cause/model/client.py")],
        [Path("src/ntsb_probable_cause/model/client.py"), CODING_TEST_CALLER],
    )
```

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_boundary.py -k coding_test -v`
Expected: FAIL (`AttributeError: for_coding_test`).

- [ ] **Step 3: Implement.**

```python
    @classmethod
    def for_coding_test(cls, cause: str) -> Payload:
        """The coding memory's coding test: one NTSB probable-cause sentence, nothing else.

        A declared exception to the request-side boundary (decision 0205, under 0200 item 2): the
        test measures coding given a perfect cause, on development cases only. Only
        ``scripts/memory_coding_test.py`` calls this, and ``tests/test_boundary.py`` proves it.
        The answering agent never receives a payload built here.
        """
        return cls(
            json.dumps({"ntsb_probable_cause": cause}, indent=1, ensure_ascii=False),
            _token=_CONSTRUCTION_TOKEN,
        )
```

Name the third constructor in the class docstring, and change the `TypeError` message to `"Payload is built only by its named constructors"`. Run `make s33-continuity`: `model/client.py` is not model-facing text, so `+t` must not move; if it does, stop and log it under Deviations.

- [ ] **Step 4: Run the tests.**

Run: `uv run pytest tests/test_boundary.py -v && make s33-continuity`
Expected: PASS; `+t` unchanged.

- [ ] **Step 5: Commit.**

```bash
git add src/ntsb_probable_cause/model/client.py tests/test_boundary.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the coding test's payload, a declared door (decision 0205)"
```

---

### Task 6: The memory package, its boundaries and the lesson format

**Files:**
- Create: `src/ntsb_probable_cause/memory/__init__.py`, `src/ntsb_probable_cause/memory/lessons.py`
- Modify: `pyproject.toml` (import-linter contracts), `tests/test_import_boundaries.py`
- Test: `tests/test_memory_lessons.py`

**Interfaces:**
- Consumes: `scoring.codes.CodeTables` (`phases`, `events`, `categories` mappings).
- Produces (all in `memory.lessons`):
  - `Kind = Literal["convention", "split", "evidence"]`
  - `Prediction(BaseModel)`: `first_occurrence: tuple[str, ...] = ()`, `finding_categories: tuple[str, ...] = ()`
  - `Support(BaseModel)`: `applies: int`, `agrees: int`, `first_codes: tuple[tuple[str, int], ...] = ()`
  - `Lesson(BaseModel)`: `lesson_id: str`, `kind: Kind`, `statement: str`, `scope: str`, `predicts: Prediction`, `written_in: int`, `support: Support | None = None`, `history: tuple[str, ...] = ()`
  - `Memory(BaseModel)`: `name: str`, `periods: tuple[int, ...]`, `cap_tokens: int = 6000`, `lessons: tuple[Lesson, ...] = ()`, `pushed_out: tuple[Lesson, ...] = ()`
  - `CAP_TOKENS: Final = 6000`; `estimated_tokens(text: str) -> int`; `render_lesson(lesson: Lesson, tables: CodeTables) -> str`; `render_memory(memory: Memory, tables: CodeTables) -> str`; `render_for_apply(memory: Memory) -> str`

- [ ] **Step 1: Write the failing tests.**

```python
"""The coding memory's lesson format (decision 0201). Offline; made-up lessons."""

import pytest
from pydantic import ValidationError

from ntsb_probable_cause.memory import lessons as ls
from ntsb_probable_cause.scoring.codes import load_tables

TABLES = load_tables()


def _lesson(**changes: object) -> ls.Lesson:
    base: dict[str, object] = {
        "lesson_id": "L001",
        "kind": "convention",
        "statement": "when the pilot stalls the airplane on approach, the NTSB codes loss of control first",
        "scope": "stall or spin during approach or landing",
        "predicts": ls.Prediction(first_occurrence=("550240",)),
        "written_in": 2009,
    }
    base.update(changes)
    return ls.Lesson.model_validate(base)


def test_a_convention_predicts_at_most_one_first_code() -> None:
    with pytest.raises(ValidationError):
        _lesson(predicts=ls.Prediction(first_occurrence=("550240", "550241")))


def test_a_split_predicts_two_or_more_first_codes() -> None:
    with pytest.raises(ValidationError):
        _lesson(kind="split", predicts=ls.Prediction(first_occurrence=("550240",)))
    _lesson(kind="split", predicts=ls.Prediction(first_occurrence=("550240", "500240")))


def test_an_evidence_lesson_names_a_finding_category() -> None:
    with pytest.raises(ValidationError):
        _lesson(kind="evidence", predicts=ls.Prediction())
    _lesson(kind="evidence", predicts=ls.Prediction(finding_categories=("010101",)))


def test_a_lesson_must_predict_something() -> None:
    with pytest.raises(ValidationError):
        _lesson(predicts=ls.Prediction())


def test_tokens_are_characters_over_four_rounded_up() -> None:
    assert ls.estimated_tokens("") == 0
    assert ls.estimated_tokens("abcde") == 2


def test_the_rendered_lesson_carries_counted_numbers_and_labels() -> None:
    lesson = _lesson(support=ls.Support(applies=41, agrees=33, first_codes=(("550240", 29),)))
    text = ls.render_lesson(lesson, TABLES)
    assert lesson.statement in text
    assert "550240" in text and "applies to 41" in text and "agrees in 33" in text


def test_the_apply_view_names_ids_statements_and_scopes_but_no_codes() -> None:
    memory = ls.Memory(name="pilot-2009", periods=(2009,), lessons=(_lesson(),))
    text = ls.render_for_apply(memory)
    assert "L001" in text and "approach" in text
    assert "550240" not in text
```

Replace `"010101"` with any category code present in `TABLES.categories` (read one from `load_tables().categories` when writing the test), and `"500240"` with a phase code that composes with event `240` in the tables.

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_memory_lessons.py -v`
Expected: FAIL (`ModuleNotFoundError: ntsb_probable_cause.memory`).

- [ ] **Step 3: Implement `memory/__init__.py`.**

```python
"""The coding memory: written lessons learned from development verdicts (decisions 0200-0207).

A declared experiment beside Ellery version 1, never part of it. ``agent``, ``model``, ``live``
and the rest of the library may not import this package (pyproject import-linter contracts);
committed scripts drive it.
"""
```

- [ ] **Step 4: Implement `memory/lessons.py`.**

```python
"""Lessons, snapshots of them, and the text a model reads (decision 0201).

A lesson's statement is the learner's words; every number shown with it is written by the
counting step (``curate.count_support``), never by the learner (rule 3).
"""

import math
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from ntsb_probable_cause.scoring.codes import CodeTables

Kind = Literal["convention", "split", "evidence"]
CAP_TOKENS: Final = 6000


class Prediction(BaseModel):
    """What a lesson predicts for a case it applies to, checkable by a script."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    first_occurrence: tuple[str, ...] = ()
    finding_categories: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """True when the lesson predicts nothing a script can check."""
        return not self.first_occurrence and not self.finding_categories


class Support(BaseModel):
    """A lesson's counted support over the learning part seen so far."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    applies: int
    agrees: int
    first_codes: tuple[tuple[str, int], ...] = ()


class Lesson(BaseModel):
    """One lesson: the learner's statement, its scope, and what it predicts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    lesson_id: str
    kind: Kind
    statement: str
    scope: str
    predicts: Prediction
    written_in: int
    support: Support | None = None
    history: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _predicts_by_kind(self) -> Self:
        first = self.predicts.first_occurrence
        if self.predicts.is_empty():
            raise ValueError(f"{self.lesson_id}: a lesson must predict something")
        if self.kind == "convention" and len(first) > 1:
            raise ValueError(f"{self.lesson_id}: a convention predicts at most one first code")
        if self.kind == "split" and len(first) < 2:  # noqa: PLR2004 -- a split is two or more
            raise ValueError(f"{self.lesson_id}: a split predicts two or more first codes")
        if self.kind == "evidence" and not self.predicts.finding_categories:
            raise ValueError(f"{self.lesson_id}: an evidence lesson names a finding category")
        return self


class Memory(BaseModel):
    """A snapshot: the lessons kept after a period, and those the cap pushed out."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    periods: tuple[int, ...]
    cap_tokens: int = CAP_TOKENS
    lessons: tuple[Lesson, ...] = ()
    pushed_out: tuple[Lesson, ...] = ()


def estimated_tokens(text: str) -> int:
    """The project's estimate: characters over four, rounded up."""
    return math.ceil(len(text) / 4)


def _occurrence_label(code: str, tables: CodeTables) -> str:
    phase = tables.phases.get(code[:3], "?")
    event = tables.events.get(code[3:], "?")
    return f"{code} {phase} / {event}"


def render_lesson(lesson: Lesson, tables: CodeTables) -> str:
    """One lesson as a model reads it: statement, what it predicts, and its counted support."""
    lines = [f"- [{lesson.lesson_id}] ({lesson.kind}) {lesson.statement}", f"  scope: {lesson.scope}"]
    if lesson.predicts.first_occurrence:
        named = "; ".join(_occurrence_label(c, tables) for c in lesson.predicts.first_occurrence)
        lines.append(f"  first occurrence code: {named}")
    if lesson.predicts.finding_categories:
        named = "; ".join(
            f"{c} {tables.categories.get(c, '?')}" for c in lesson.predicts.finding_categories
        )
        lines.append(f"  finding categories: {named}")
    if lesson.support is not None:
        s = lesson.support
        seen = ", ".join(f"{code} ({n})" for code, n in s.first_codes)
        counted = f"  counted: applies to {s.applies} learning cases, agrees in {s.agrees}"
        lines.append(f"{counted}; first codes seen: {seen}" if seen else counted)
    return "\n".join(lines)


def render_memory(memory: Memory, tables: CodeTables) -> str:
    """The whole memory, in lesson order, as the coding test and the learner read it."""
    return "\n".join(render_lesson(lesson, tables) for lesson in memory.lessons)


def render_for_apply(memory: Memory) -> str:
    """The apply step's view: ids, statements and scopes only, never codes or counts.

    The apply step judges from a case's cause sentence whether a lesson covers it; showing it
    the predicted codes would let it judge by codes and make agreement circular.
    """
    return "\n".join(
        f"- [{lesson.lesson_id}] {lesson.statement} (scope: {lesson.scope})"
        for lesson in memory.lessons
    )
```

- [ ] **Step 5: Run the tests.**

Run: `uv run pytest tests/test_memory_lessons.py -v`
Expected: PASS.

- [ ] **Step 6: Add the import contracts.** In `pyproject.toml`:
  - add `"ntsb_probable_cause.memory"` to the source list of "Only the splitter constructs synthesis and verdict" (the package reads verdict fields through `fields.*` only), of "Nothing in the library imports the agent", and of "Nothing in the library or the other commands imports the live package";
  - add a new contract:

```toml
[[tool.importlinter.contracts]]
name = "Nothing in the library imports the memory package (decisions 0200, 0201)"
type = "forbidden"
source_modules = [
    "ntsb_probable_cause.agent",
    "ntsb_probable_cause.data",
    "ntsb_probable_cause.docket",
    "ntsb_probable_cause.live",
    "ntsb_probable_cause.model",
    "ntsb_probable_cause.records",
    "ntsb_probable_cause.recorder",
    "ntsb_probable_cause.scoring",
    "ntsb_probable_cause.store",
    "apps",
]
forbidden_modules = ["ntsb_probable_cause.memory"]
```

  Use the exact list of top-level library modules the "Nothing in the library imports the agent" contract names (read it), less `memory`, plus `agent`, `live` and `apps`. Update `tests/test_import_boundaries.py:114`'s list of package children to include `memory`, and add a grimp test that only `ntsb_probable_cause.memory.claude` imports `anthropic` (it passes vacuously until Task 10).

- [ ] **Step 7: Run the boundary checks.**

Run: `uv run lint-imports && uv run pytest tests/test_import_boundaries.py -v`
Expected: every contract KEPT; tests PASS.

- [ ] **Step 8: Commit.**

```bash
git add src/ntsb_probable_cause/memory pyproject.toml tests/test_memory_lessons.py tests/test_import_boundaries.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the package, its boundaries and the lesson format (decisions 0200, 0201)"
```

---

### Task 7: The three checks, the stamp and checked loading

**Files:**
- Create: `src/ntsb_probable_cause/memory/checks.py`, `src/ntsb_probable_cause/memory/snapshots.py`, `src/ntsb_probable_cause/memory/allowed_words.txt`, `src/ntsb_probable_cause/memory/snapshots/.gitkeep`
- Create: `scripts/memory_check.py`
- Modify: `Makefile`, `scripts/README.md`
- Test: `tests/test_memory_checks.py`, `tests/test_memory_snapshots.py`

**Interfaces:**
- Consumes: `memory.lessons.Memory`, `Lesson`.
- Produces:
  - `checks.ALLOWED_WORDS: frozenset[str]` (from `allowed_words.txt`)
  - `checks.identifier_findings(memory: Memory, allowed: frozenset[str] = ALLOWED_WORDS) -> list[str]`
  - `checks.normalise(text: str) -> str`; `checks.sentences(text: str) -> list[str]` (≥ 30 characters, as `scripts/check_guidance.py`)
  - `checks.withheld_findings(memory: Memory, withheld: Iterable[str]) -> list[str]`
  - `checks.windows(text: str, n: int = 8) -> set[tuple[str, ...]]`
  - `checks.copying_findings(memory: Memory, causes: Iterable[str], n: int = 8) -> list[str]`
  - `checks.Stamp(BaseModel)`: `snapshot: str`, `sha256: str`, `withheld_texts_compared: int`, `causes_compared: int`, `checked_on: date`, `commit: str`, `dirty: bool`
  - `snapshots.SNAPSHOT_DIR: Path`; `snapshots.snapshot_path(name) -> Path`; `snapshots.stamp_path(name) -> Path`; `snapshots.sha256_of(path: Path) -> str`; `snapshots.save(memory: Memory, directory: Path = SNAPSHOT_DIR) -> Path` (refuses to overwrite); `snapshots.load(name, directory=SNAPSHOT_DIR) -> Memory`; `snapshots.load_checked(name, directory=SNAPSHOT_DIR) -> Memory` (raises `ConfigurationError`); `snapshots.names(directory=SNAPSHOT_DIR) -> list[str]`

- [ ] **Step 1: Write the failing tests.**

```python
"""The coding memory's three checks and its stamp (decision 0201). Offline; made-up lessons."""

from datetime import date
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import checks, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction


def _memory(statement: str, scope: str = "approach and landing") -> Memory:
    lesson = Lesson(lesson_id="L001", kind="convention", statement=statement, scope=scope,
                    predicts=Prediction(first_occurrence=("550240",)), written_in=2009)
    return Memory(name="t", periods=(2009,), lessons=(lesson,))


def test_digits_and_unlisted_capitals_are_identifiers() -> None:
    found = checks.identifier_findings(_memory("the pilot of N123AB lost control on 4 May"))
    assert any("digit" in f for f in found)
    found = checks.identifier_findings(_memory("when Smith stalls on approach, the NTSB codes loss of control"))
    assert any("Smith" in f for f in found)
    assert checks.identifier_findings(_memory("when the pilot stalls under VFR, the NTSB codes loss of control")) == []


def test_a_shared_withheld_sentence_is_found() -> None:
    withheld = ["The pilot did not maintain adequate airspeed during the approach, which resulted in a stall."]
    memory = _memory("the pilot did not maintain adequate airspeed during the approach, which resulted in a stall.")
    assert checks.withheld_findings(memory, withheld)


def test_eight_shared_words_are_a_copy_and_seven_are_not() -> None:
    cause = "the pilot's failure to maintain adequate airspeed during the approach"
    assert checks.copying_findings(_memory("a pilot's failure to maintain adequate airspeed during the flare"), [cause]) == []
    assert checks.copying_findings(_memory("the pilot's failure to maintain adequate airspeed during the approach leads"), [cause])


def test_a_snapshot_edited_after_its_stamp_is_refused(tmp_path: Path) -> None:
    memory = _memory("when the pilot stalls on approach, the NTSB codes loss of control first")
    path = snapshots.save(memory, tmp_path)
    stamp = checks.Stamp(snapshot="t", sha256=snapshots.sha256_of(path), withheld_texts_compared=3,
                         causes_compared=2, checked_on=date(2026, 10, 14), commit="abc1234", dirty=False)
    snapshots.stamp_path("t", tmp_path).write_text(stamp.model_dump_json(indent=1))
    assert snapshots.load_checked("t", tmp_path) == memory
    path.write_text(path.read_text().replace("first", "fist"))
    with pytest.raises(ConfigurationError):
        snapshots.load_checked("t", tmp_path)


def test_an_unstamped_snapshot_is_refused(tmp_path: Path) -> None:
    snapshots.save(_memory("when the pilot stalls on approach, the NTSB codes loss of control"), tmp_path)
    with pytest.raises(ConfigurationError):
        snapshots.load_checked("t", tmp_path)


def test_save_refuses_to_overwrite(tmp_path: Path) -> None:
    memory = _memory("when the pilot stalls on approach, the NTSB codes loss of control")
    snapshots.save(memory, tmp_path)
    with pytest.raises(ConfigurationError):
        snapshots.save(memory, tmp_path)
```

```python
"""Every committed snapshot passes the identifier check and has a matching stamp (decision 0201).

Runs in continuous integration, which has no case data: the withheld-text and copying checks
run locally (``make mem-check``) and their result is the stamp.
"""

import pytest

from ntsb_probable_cause.memory import checks, snapshots


@pytest.mark.parametrize("name", snapshots.names())
def test_every_committed_snapshot_is_stamped_and_names_no_one(name: str) -> None:
    memory = snapshots.load_checked(name)
    assert checks.identifier_findings(memory) == []
```

(With no snapshots yet, pytest reports the parametrised test as skipped with an empty parameter set; that is expected until Task 16.)

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_memory_checks.py tests/test_memory_snapshots.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `allowed_words.txt`.** One word per line, with a header comment line starting `#`: `NTSB`, `FAA`, `ATC`, `VFR`, `IFR`, `IMC`, `VMC`, `CFIT`, `ELT`, `AGL`, `MSL`, `GPS`, `CFI`. Andy reviews additions; a word is added only when a lesson needs it and it names no person, place or operator.

- [ ] **Step 4: Implement `memory/checks.py`.**

```python
"""The three checks every coding-memory snapshot passes before use (decision 0201).

The identifier check needs no case data and runs in continuous integration; the withheld-text
and copying checks compare against development case text and run locally
(``scripts/memory_check.py``), whose result is the stamp.
"""

import re
from collections.abc import Iterable
from datetime import date
from importlib import resources
from typing import Final

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.memory.lessons import Memory

MIN_SENTENCE_CHARS: Final = 30  # as scripts/check_guidance.py (S2.7)
COPY_WORDS: Final = 8
_WORD: Final = re.compile(r"[A-Za-z][A-Za-z'-]*")
_LOWER_WORD: Final = re.compile(r"[a-z0-9']+")
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


def _allowed_words() -> frozenset[str]:
    text = resources.files("ntsb_probable_cause.memory").joinpath("allowed_words.txt").read_text()
    return frozenset(
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
    )


ALLOWED_WORDS: Final = _allowed_words()


def _texts(memory: Memory) -> list[tuple[str, str]]:
    return [
        (lesson.lesson_id, text)
        for lesson in (*memory.lessons, *memory.pushed_out)
        for text in (lesson.statement, lesson.scope)
    ]


def identifier_findings(memory: Memory, allowed: frozenset[str] = ALLOWED_WORDS) -> list[str]:
    """Statements or scopes holding a digit, or a capitalised word not on the allowed list."""
    found: list[str] = []
    for lesson_id, text in _texts(memory):
        if any(ch.isdigit() for ch in text):
            found.append(f"{lesson_id}: a digit in {text!r}")
        found.extend(
            f"{lesson_id}: capitalised word {word!r} is not allowed"
            for word in _WORD.findall(text)
            if word != word.lower() and word not in allowed
        )
    return found


def normalise(text: str) -> str:
    """Lower case, whitespace collapsed, stripped."""
    return " ".join(text.lower().split())


def sentences(text: str) -> list[str]:
    """Normalised sentences of at least ``MIN_SENTENCE_CHARS`` characters."""
    return [
        s for s in (normalise(part) for part in _SENTENCE_END.split(text))
        if len(s) >= MIN_SENTENCE_CHARS
    ]


def withheld_findings(memory: Memory, withheld: Iterable[str]) -> list[str]:
    """Lesson sentences found inside any withheld text (plain substring, as S2.7's check)."""
    needles = [(lid, s) for lid, text in _texts(memory) for s in sentences(text)]
    found: list[str] = []
    for haystack in withheld:
        hay = normalise(haystack)
        found.extend(f"{lid}: {s!r} is in withheld text" for lid, s in needles if s in hay)
    return found


def windows(text: str, n: int = COPY_WORDS) -> set[tuple[str, ...]]:
    """Every run of ``n`` consecutive lower-case words in ``text``."""
    words = _LOWER_WORD.findall(text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def copying_findings(memory: Memory, causes: Iterable[str], n: int = COPY_WORDS) -> list[str]:
    """Lessons sharing a run of ``n`` or more words with any probable-cause sentence."""
    seen: set[tuple[str, ...]] = set()
    for cause in causes:
        seen |= windows(cause, n)
    return [
        f"{lid}: shares {n} words with a probable-cause sentence: {' '.join(w)!r}"
        for lid, text in _texts(memory)
        for w in sorted(windows(text, n) & seen)
    ]


class Stamp(BaseModel):
    """The local checks' record, committed beside the snapshot it names."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: str
    sha256: str
    withheld_texts_compared: int
    causes_compared: int
    checked_on: date
    commit: str
    dirty: bool
```

- [ ] **Step 5: Implement `memory/snapshots.py`.**

```python
"""Coding-memory snapshots on disk, and the refusal of any that is unchecked (decision 0201)."""

import hashlib
from pathlib import Path
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import checks
from ntsb_probable_cause.memory.lessons import Memory

SNAPSHOT_DIR: Final = Path(__file__).parent / "snapshots"


def snapshot_path(name: str, directory: Path = SNAPSHOT_DIR) -> Path:
    """Where snapshot ``name`` lives."""
    return directory / f"{name}.json"


def stamp_path(name: str, directory: Path = SNAPSHOT_DIR) -> Path:
    """Where snapshot ``name``'s stamp lives."""
    return directory / f"{name}.stamp.json"


def sha256_of(path: Path) -> str:
    """The file's bytes, hashed."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(memory: Memory, directory: Path = SNAPSHOT_DIR) -> Path:
    """Write a new snapshot; never overwrite one.

    Raises:
        ConfigurationError: a snapshot of that name exists.
    """
    path = snapshot_path(memory.name, directory)
    if path.exists():
        raise ConfigurationError(f"snapshot {memory.name} exists; snapshots are never rewritten")
    path.write_text(memory.model_dump_json(indent=1) + "\n")
    return path


def load(name: str, directory: Path = SNAPSHOT_DIR) -> Memory:
    """Read a snapshot without checking it (the local check and the learner's draft only)."""
    return Memory.model_validate_json(snapshot_path(name, directory).read_text())


def load_checked(name: str, directory: Path = SNAPSHOT_DIR) -> Memory:
    """Read a snapshot only if its stamp matches it and it names no one.

    Raises:
        ConfigurationError: the stamp is missing, names another file or hash, or the identifier
            check finds anything.
    """
    stamp_file = stamp_path(name, directory)
    if not stamp_file.exists():
        raise ConfigurationError(f"snapshot {name} has no stamp: run make mem-check SNAPSHOT={name}")
    stamp = checks.Stamp.model_validate_json(stamp_file.read_text())
    digest = sha256_of(snapshot_path(name, directory))
    if stamp.snapshot != name or stamp.sha256 != digest:
        raise ConfigurationError(f"snapshot {name} changed after its check; check it again")
    memory = load(name, directory)
    if found := checks.identifier_findings(memory):
        raise ConfigurationError(f"snapshot {name} fails the identifier check: {found}")
    return memory


def names(directory: Path = SNAPSHOT_DIR) -> list[str]:
    """Every snapshot in ``directory``, by name."""
    return sorted(
        p.name.removesuffix(".json")
        for p in directory.glob("*.json")
        if not p.name.endswith(".stamp.json")
    )
```

- [ ] **Step 6: Implement `scripts/memory_check.py`.** Docstring with a `Status` block ("Live tool, free, local: needs `data/processed/cases.parquet`. Writes the stamp of decision 0201."), `What it reads`, `What it writes`, `Usage` (`uv run python -m scripts.memory_check --snapshot NAME`). `main(argv) -> int`:
  1. `memory = snapshots.load(name)`; print and return 1 if `checks.identifier_findings(memory)` finds anything.
  2. Stream every development row of `cases.parquet` (columns `split`, `raw_json`, as `scripts/check_guidance.py` does) and collect `fields.factual_narrative(raw)`, `fields.analysis_narrative(raw)`, `fields.probable_cause(raw)` (non-empty) as the withheld texts; collect `fields.probable_cause(raw)` as the causes. Development only: refuse any row whose `split` is not `dev` from entering either list.
  3. Run `withheld_findings` and `copying_findings`; print every finding and return 1 if any.
  4. Else write `snapshots.stamp_path(name)` with a `Stamp` (`sha256_of(snapshot_path(name))`, the two counts, `date.today()`, `gitinfo.commit_state()`), print a counts-only summary, return 0.
  Add a test in `tests/test_memory_snapshots.py` that runs `main` on a tmp snapshot directory with a three-row parquet built by `pyarrow` (`pa.table({...}); pq.write_table(...)`), monkeypatching `snapshots.SNAPSHOT_DIR` and the processed path, and asserts a stamp is written for a clean memory and none for a copying one. Add to the `Makefile`:

```make
mem-check: ## Check a coding-memory snapshot against development text and stamp it (0201); free, local
	uv run python -m scripts.memory_check --snapshot $(SNAPSHOT)
```

  Add the script to `scripts/README.md`'s table.

- [ ] **Step 7: Run the tests.**

Run: `uv run pytest tests/test_memory_checks.py tests/test_memory_snapshots.py -v`
Expected: PASS (the committed-snapshot test reports no parameters).

- [ ] **Step 8: Commit.**

```bash
git add src/ntsb_probable_cause/memory scripts/memory_check.py scripts/README.md Makefile tests/test_memory_checks.py tests/test_memory_snapshots.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the three checks, the stamp and checked loading (decision 0201)"
```

---

### Task 8: The learning part

**Files:**
- Create: `src/ntsb_probable_cause/memory/pool.py`
- Test: `tests/test_memory_pool.py`

**Interfaces:**
- Consumes: `fields.probable_cause`, `fields.occurrence_codes`, `fields.finding_codes_in_cause`; `samples.sample_ids`; `coding_stats.POOL_EXCLUDED["mem"]`; `coding_stats.POOL_CLASSES` if public, else the literal `{"C", "F", "L"}` with a comment naming 0094.
- Produces: `pool.LearningCase` (frozen dataclass: `case_id: str`, `year: int`, `cause: str`, `occurrence: tuple[str, ...]`, `findings: tuple[str, ...]`); `pool.learning_part(processed: Path, *, years: AbstractSet[int], excluded: AbstractSet[str] | None = None) -> list[LearningCase]` (sorted by `case_id`; `excluded` defaults to the ids of every sample in `POOL_EXCLUDED["mem"]`).

- [ ] **Step 1: Write the failing tests.**

```python
"""The learning part: development pool cases outside every sample (decisions 0200, 0203).

A made-up parquet under tmp_path built from the redacted fixture records; offline.
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.memory import pool
from tests.conftest import FIXTURES


def _write(processed: Path, rows: list[tuple[str, str, str, str, dict[str, object]]]) -> None:
    processed.mkdir(parents=True)
    pq.write_table(
        pa.table({
            "ntsb_number": [r[0] for r in rows],
            "event_date": [r[1] for r in rows],
            "split": [r[2] for r in rows],
            "investigation_class": [r[3] for r in rows],
            "raw_json": [json.dumps(r[4]) for r in rows],
        }),
        processed / "cases.parquet",
    )


def _coded_record() -> dict[str, object]:
    for path in sorted((FIXTURES / "records").glob("*.json")):
        raw = json.loads(path.read_text())["record"]
        if fields.probable_cause(raw) and fields.occurrence_codes(raw):
            return raw
    raise AssertionError("no coded fixture record")


def test_only_development_pool_cases_of_the_years_asked_and_outside_samples(tmp_path: Path) -> None:
    raw = _coded_record()
    _write(tmp_path / "processed", [
        ("A1", "2009-05-01", "dev", "C", raw),
        ("A2", "2010-05-01", "dev", "C", raw),
        ("A3", "2009-06-01", "heldout", "C", raw),
        ("A4", "2009-07-01", "dev", "I", raw),
        ("A5", "2009-08-01", "dev", "F", raw),
    ])
    got = pool.learning_part(tmp_path / "processed", years={2009}, excluded={"A5"})
    assert [c.case_id for c in got] == ["A1"]
    case = got[0]
    assert case.year == 2009
    assert case.cause == fields.probable_cause(raw)
    assert case.occurrence == fields.occurrence_codes(raw)
    assert case.findings == fields.finding_codes_in_cause(raw)


def test_a_case_without_a_cause_or_an_occurrence_code_is_left_out(tmp_path: Path) -> None:
    raw = _coded_record()
    bare = {**raw, "narratives": []}
    _write(tmp_path / "processed", [("B1", "2009-05-01", "dev", "C", bare)])
    assert pool.learning_part(tmp_path / "processed", years={2009}, excluded=set()) == []
```

If `fields.probable_cause` reads somewhere other than `narratives` (check `fields.py:301`), blank that path instead in `bare`. If the fixture records' event years differ from the rows' `event_date`, the reader must take the year from `event_date` (the parquet column), which these tests assume.

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_memory_pool.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `memory/pool.py`.**

```python
"""The learning part: what the learner may read (decisions 0200, 0203).

The S3 statistics pool (development split, classes C/F/L) less every sample the ``mem``
statistics leave out, ``dev-steer-400`` among them. Only cases with a probable-cause sentence
and at least one occurrence code. Verdict fields are read through ``fields`` from the raw
record; no ``Verdict`` is built here.
"""

import json
from collections.abc import AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import coding_stats, samples

POOL_CLASSES: Final = frozenset({"C", "F", "L"})  # decision 0094
COLUMNS: Final = ("ntsb_number", "event_date", "split", "investigation_class", "raw_json")


@dataclass(frozen=True)
class LearningCase:
    """One learning-part case as the learner reads it."""

    case_id: str
    year: int
    cause: str
    occurrence: tuple[str, ...]
    findings: tuple[str, ...]


def excluded_ids() -> frozenset[str]:
    """The ids of every sample the ``mem`` statistics leave out."""
    return frozenset(i for name in coding_stats.POOL_EXCLUDED["mem"] for i in samples.sample_ids(name))


def learning_part(
    processed: Path, *, years: AbstractSet[int], excluded: AbstractSet[str] | None = None
) -> list[LearningCase]:
    """Learning-part cases with event years in ``years``, sorted by case id."""
    leave_out = excluded_ids() if excluded is None else excluded
    table = pq.read_table(processed / "cases.parquet", columns=list(COLUMNS))
    cols = {c: table[c].to_pylist() for c in COLUMNS}
    found: list[LearningCase] = []
    for case_id, day, split, klass, raw_json in zip(*(cols[c] for c in COLUMNS), strict=True):
        year = int(str(day)[:4])
        if split != "dev" or klass not in POOL_CLASSES or case_id in leave_out or year not in years:
            continue
        raw = json.loads(raw_json)
        cause = fields.probable_cause(raw)
        occurrence = fields.occurrence_codes(raw)
        if not cause or not occurrence:
            continue
        found.append(LearningCase(str(case_id), year, cause, tuple(occurrence),
                                  tuple(fields.finding_codes_in_cause(raw))))
    return sorted(found, key=lambda c: c.case_id)
```

If `cases.parquet` is too large to read whole with these columns (S1's note in `samples.py:151` says `pyarrow` reads whole row groups), stream it the way `samples.load_cases` does instead, keeping this function's signature.

- [ ] **Step 4: Run the tests.**

Run: `uv run pytest tests/test_memory_pool.py -v && uv run lint-imports`
Expected: PASS; contracts KEPT.

- [ ] **Step 5: Commit.**

```bash
git add src/ntsb_probable_cause/memory/pool.py tests/test_memory_pool.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the learning part (decisions 0200, 0203)"
```

---

### Task 9: Support counts, revision, the cap and model agreement

**Files:**
- Create: `src/ntsb_probable_cause/memory/curate.py`
- Test: `tests/test_memory_curate.py`

**Interfaces:**
- Consumes: `lessons.Lesson`, `Support`, `Memory`, `estimated_tokens`, `render_lesson`; `pool.LearningCase`.
- Produces:
  - `curate.agrees(lesson: Lesson, case: LearningCase) -> bool`
  - `curate.count_support(lessons: Sequence[Lesson], cases: Sequence[LearningCase], applies: Mapping[str, frozenset[str]]) -> dict[str, Support]` (`applies` maps case id to the lesson ids judged to apply)
  - `curate.needs_revision(support: Support) -> bool`; `curate.unused(support: Support) -> bool`
  - `curate.with_support(lessons: Sequence[Lesson], support: Mapping[str, Support]) -> tuple[Lesson, ...]`
  - `curate.apply_cap(lessons: Sequence[Lesson], tables: CodeTables, cap_tokens: int) -> tuple[tuple[Lesson, ...], tuple[Lesson, ...]]` (kept, pushed out)
  - `curate.agreement(a: Mapping[str, frozenset[str]], b: Mapping[str, frozenset[str]]) -> tuple[int, int]` (pairs both mark, pairs either marks)

- [ ] **Step 1: Write the failing tests.**

```python
"""Support counts, revision, the cap and model agreement (decisions 0201, 0204). Offline."""

from ntsb_probable_cause.memory import curate
from ntsb_probable_cause.memory.lessons import Lesson, Prediction, Support
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring.codes import load_tables

TABLES = load_tables()


def _case(case_id: str, first: str, findings: tuple[str, ...] = ()) -> LearningCase:
    return LearningCase(case_id, 2009, "cause", (first, "600470"), findings)


def _lesson(lid: str, kind: str = "convention", first: tuple[str, ...] = ("550240",),
            cats: tuple[str, ...] = ()) -> Lesson:
    return Lesson(lesson_id=lid, kind=kind, statement="the NTSB codes it so", scope="a scope",
                  predicts=Prediction(first_occurrence=first, finding_categories=cats), written_in=2009)


def test_a_convention_agrees_when_the_first_code_matches() -> None:
    assert curate.agrees(_lesson("L1"), _case("A", "550240"))
    assert not curate.agrees(_lesson("L1"), _case("A", "551240"))


def test_a_split_agrees_when_the_first_code_is_any_of_its_codes() -> None:
    lesson = _lesson("L2", kind="split", first=("550240", "551240"))
    assert curate.agrees(lesson, _case("A", "551240"))


def test_finding_categories_must_all_be_among_the_flagged_findings() -> None:
    lesson = _lesson("L3", kind="evidence", first=(), cats=("020630",))
    assert curate.agrees(lesson, _case("A", "550240", ("0206304044",)))
    assert not curate.agrees(lesson, _case("A", "550240", ("0101010101",)))


def test_support_counts_applies_agrees_and_the_commonest_first_codes() -> None:
    cases = [_case("A", "550240"), _case("B", "550240"), _case("C", "551240"), _case("D", "550240")]
    applies = {"A": frozenset({"L1"}), "B": frozenset({"L1"}), "C": frozenset({"L1"}), "D": frozenset()}
    s = curate.count_support([_lesson("L1")], cases, applies)["L1"]
    assert (s.applies, s.agrees) == (3, 2)
    assert s.first_codes == (("550240", 2), ("551240", 1))


def test_revision_when_disagreements_outnumber_agreements_and_unused_when_none_apply() -> None:
    assert curate.needs_revision(Support(applies=5, agrees=2))
    assert not curate.needs_revision(Support(applies=4, agrees=2))
    assert curate.unused(Support(applies=0, agrees=0))


def test_the_cap_keeps_the_best_supported_lessons_first() -> None:
    strong = _lesson("L1").model_copy(update={"support": Support(applies=10, agrees=9)})
    weak = _lesson("L2").model_copy(update={"support": Support(applies=10, agrees=3)})
    room = curate.estimated_tokens(curate.render_lesson(strong, TABLES))
    kept, pushed = curate.apply_cap([weak, strong], TABLES, room)
    assert [lesson.lesson_id for lesson in kept] == ["L1"]
    assert [lesson.lesson_id for lesson in pushed] == ["L2"]


def test_agreement_counts_pairs_either_model_marks() -> None:
    a = {"A": frozenset({"L1", "L2"}), "B": frozenset()}
    b = {"A": frozenset({"L1"}), "B": frozenset({"L3"})}
    assert curate.agreement(a, b) == (1, 3)
```

Replace `"020630"`, `"0206304044"` and `"0101010101"` with codes from `TABLES` that keep the stated relationship (a ten-digit finding whose first six digits are the category, and one whose first six are not).

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_memory_curate.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `memory/curate.py`.**

```python
"""Counting support, choosing what to revise, the cap, and model agreement (0201, 0204).

Every number a lesson carries is counted here, by a script, over learning-part cases (rule 3).
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from ntsb_probable_cause.memory.lessons import Lesson, Support, estimated_tokens, render_lesson
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring.codes import CodeTables

FIRST_CODES_SHOWN: Final = 3

__all__ = ["agreement", "agrees", "apply_cap", "count_support", "estimated_tokens",
           "needs_revision", "render_lesson", "unused", "with_support"]


def agrees(lesson: Lesson, case: LearningCase) -> bool:
    """Whether ``case``'s codes are what ``lesson`` predicts, on every part it predicts."""
    first = lesson.predicts.first_occurrence
    if first and case.occurrence[0] not in first:
        return False
    flagged = {code[:6] for code in case.findings}
    return all(category in flagged for category in lesson.predicts.finding_categories)


def count_support(
    lessons: Sequence[Lesson], cases: Sequence[LearningCase], applies: Mapping[str, frozenset[str]]
) -> dict[str, Support]:
    """Each lesson's applies, agrees and commonest first codes over ``cases``."""
    support: dict[str, Support] = {}
    for lesson in lessons:
        covered = [c for c in cases if lesson.lesson_id in applies.get(c.case_id, frozenset())]
        firsts = Counter(c.occurrence[0] for c in covered)
        top = tuple(sorted(firsts.items(), key=lambda kv: (-kv[1], kv[0]))[:FIRST_CODES_SHOWN])
        support[lesson.lesson_id] = Support(
            applies=len(covered), agrees=sum(agrees(lesson, c) for c in covered), first_codes=top
        )
    return support


def needs_revision(support: Support) -> bool:
    """A lesson that disagrees with more cases than it agrees with goes back to the learner."""
    return support.applies - support.agrees > support.agrees


def unused(support: Support) -> bool:
    """A lesson no case was judged to fall under; it cannot be supported, so it is retired."""
    return support.applies == 0


def with_support(lessons: Sequence[Lesson], support: Mapping[str, Support]) -> tuple[Lesson, ...]:
    """The lessons, each carrying its counted support."""
    return tuple(lesson.model_copy(update={"support": support[lesson.lesson_id]}) for lesson in lessons)


def apply_cap(
    lessons: Sequence[Lesson], tables: CodeTables, cap_tokens: int
) -> tuple[tuple[Lesson, ...], tuple[Lesson, ...]]:
    """Keep the best-supported lessons that fit in ``cap_tokens``; the rest are pushed out.

    Order: most agreements, then most applies, then lesson id. Each lesson's size is its
    rendered text's estimate (``estimated_tokens``), plus one for its line break.
    """
    def rank(lesson: Lesson) -> tuple[int, int, str]:
        s = lesson.support or Support(applies=0, agrees=0)
        return (-s.agrees, -s.applies, lesson.lesson_id)

    kept: list[Lesson] = []
    pushed: list[Lesson] = []
    used = 0
    for lesson in sorted(lessons, key=rank):
        size = estimated_tokens(render_lesson(lesson, tables)) + 1
        if used + size <= cap_tokens:
            kept.append(lesson)
            used += size
        else:
            pushed.append(lesson)
    return tuple(kept), tuple(pushed)


def agreement(
    a: Mapping[str, frozenset[str]], b: Mapping[str, frozenset[str]]
) -> tuple[int, int]:
    """Case-and-lesson pairs both models mark, and pairs either marks."""
    both = either = 0
    for case_id in a.keys() | b.keys():
        left, right = a.get(case_id, frozenset()), b.get(case_id, frozenset())
        both += len(left & right)
        either += len(left | right)
    return both, either
```

The test's `_case` gives every case a second occurrence code so `case.occurrence[0]` always exists; `pool.learning_part` guarantees at least one.

- [ ] **Step 4: Run the tests.**

Run: `uv run pytest tests/test_memory_curate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/ntsb_probable_cause/memory/curate.py tests/test_memory_curate.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: support counts, revision, the cap and agreement (decisions 0201, 0204)"
```

---

### Task 10: The learner's prompts and the gated Claude client

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (`uv add anthropic`)
- Create: `src/ntsb_probable_cause/memory/prompts.py`, `src/ntsb_probable_cause/memory/claude.py`
- Test: `tests/test_memory_prompts.py`, `tests/test_memory_claude.py`

**Interfaces:**
- Consumes: `lessons.*`, `pool.LearningCase`, `scoring.codes.CodeTables`, `scoring.hypothesis.strict_schema`, `scoring.prompt.SYSTEM_ANSWER`, `scoring.prompt.tables_block`, `scoring.prompt.guidance_block`, `sources.claude_price`, `sources.HAIKU_55_PROMPT_LIMIT`, `budget.write_spend`, `budget.SpendRecord`.
- Produces (`memory.prompts`):
  - `SYSTEM_PROPOSE: str`, `SYSTEM_APPLY: str`, `SYSTEM_REVISE: str`, `MAX_NEW_PER_CALL: Final = 5`
  - `LessonDraft(BaseModel)`: `kind: Kind`, `statement: str`, `scope: str`, `first_occurrence: list[str]`, `finding_categories: list[str]`; `LessonEdit(LessonDraft)`: `lesson_id: str`
  - `ProposeReply(BaseModel)`: `new: list[LessonDraft]`, `edits: list[LessonEdit]`, `retire: list[str]`
  - `ApplyReply(BaseModel)`: `applies: list[str]`
  - `ReviseReply(BaseModel)`: `action: Literal["edit", "retire"]`, plus `LessonDraft`'s fields
  - `render_case(case: LearningCase, label: str, tables: CodeTables) -> str`; `propose_user(memory_text: str, cases: Sequence[LearningCase], tables: CodeTables) -> str`; `apply_user(cause: str) -> str`; `revise_user(lesson_text: str, disagreeing: Sequence[LearningCase], agreeing: Sequence[LearningCase], tables: CodeTables) -> str`
  - `CODING_PREFACE: str`; `MEMORY_HEADING: str`; `coding_system(tables: CodeTables, guidance: Sequence[str], memory: Memory | None) -> str`
- Produces (`memory.claude`):
  - `SONNET: Final = "claude-sonnet-5-5"`, `HAIKU: Final = "claude-haiku-5-5"`, `ROLES: Final[frozenset[str]]` (`propose`, `apply`, `revise`, `agreement`, `probe`), `Effort = Literal["low", "medium", "high"]`
  - `Call` (frozen dataclass: `role`, `model`, `effort`, `system`, `user`, `schema`, `max_tokens`, `case_ids`; `params() -> dict[str, object]`; `key() -> str`)
  - `Reply` (frozen pydantic model: `key`, `role`, `model`, `effort`, `batch: bool`, `text: str | None`, `stop_reason: str | None`, `stop_category: str | None`, `error: str | None`, `input_tokens`, `output_tokens`, `cache_write_tokens`, `cache_read_tokens`, `cost_usd: float`; property `ok`)
  - `cost_usd(input_tokens: int, output_tokens: int, cache_write_tokens: int, cache_read_tokens: int, price: ClaudePrice) -> float`
  - `LearningClient(sdk: anthropic.Anthropic, runs_dir: Path, run_id: str, *, commit: tuple[str, bool], forbidden: frozenset[str])` with `send(call: Call) -> Reply` and `send_batch(calls: Sequence[Call], *, every_seconds: float = 60.0, sleep: Callable[[float], None] = time.sleep) -> dict[str, Reply]`

- [ ] **Step 1: Add the SDK.**

Run: `uv add anthropic` then `uv run deptry . && uv run pip-audit`
Expected: `anthropic` in `[project].dependencies` and `uv.lock`; deptry reports it unused (DEP002) until Step 6; pip-audit clean. If the repository's uv cooldown refuses the newest release, take the newest it allows and record the version under Deviations.

- [ ] **Step 2: Write the failing prompt tests.**

```python
"""The learner's prompts and the coding test's system text (decisions 0200-0204). Offline."""

from ntsb_probable_cause.memory import prompts
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring.codes import load_tables

TABLES = load_tables()
CASE = LearningCase("ERA09LA123", 2009, "The pilot's failure to maintain directional control.",
                    ("552230", "552470"), ())


def test_a_rendered_case_carries_codes_with_labels_and_no_case_number() -> None:
    text = prompts.render_case(CASE, "K1", TABLES)
    assert "552230" in text and TABLES.events["230"] in text
    assert "ERA09LA123" not in text


def test_the_apply_question_carries_only_the_cause() -> None:
    text = prompts.apply_user(CASE.cause)
    assert CASE.cause in text
    assert "552230" not in text and "ERA09LA123" not in text


def test_the_propose_system_text_forbids_numbers_names_and_places() -> None:
    lowered = prompts.SYSTEM_PROPOSE.lower()
    assert "no digits" in lowered and "names" in lowered and "places" in lowered


def test_the_coding_system_adds_the_memory_only_when_given() -> None:
    lesson = Lesson(lesson_id="L001", kind="convention", statement="the NTSB codes it so",
                    scope="a scope", predicts=Prediction(first_occurrence=("552230",)), written_in=2009)
    guidance = ("r3-loc-stall", "r6-aircraft-control")
    without = prompts.coding_system(TABLES, guidance, None)
    with_memory = prompts.coding_system(TABLES, guidance, Memory(name="m", periods=(2009,), lessons=(lesson,)))
    assert prompts.MEMORY_HEADING not in without
    assert with_memory.startswith(without) and prompts.MEMORY_HEADING in with_memory
    assert without.startswith(prompts.CODING_PREFACE)
```

- [ ] **Step 3: Implement `memory/prompts.py`.** The texts are model-facing; write them as below (edit wording only to fix an error, and log the edit).

```python
"""What the learner and the coding test read (decisions 0200-0204).

The learner reads learning-part verdicts: a case's probable-cause sentence and its codes, with
their labels, under a position label (K1, K2, ...), never its case number. The apply step reads a
case's cause sentence alone (``apply_user``), so a lesson is judged to apply by its situation and
never by its codes.
"""

from collections.abc import Sequence
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.memory.lessons import Kind, Memory, render_memory
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables

MAX_NEW_PER_CALL: Final = 5

SYSTEM_PROPOSE: Final = """You study how the NTSB codes closed US general-aviation accidents, to \
write short coding lessons another model will use. You are given the current lessons and a batch \
of closed cases, each with the NTSB's probable-cause sentence, its occurrence codes in the NTSB's \
order (the first is the defining event), and the findings it flagged as causal.

Write lessons about how the NTSB codes, not about any one accident. Each lesson is one of three \
kinds:
- convention: in this situation the NTSB codes the same way nearly every time; it predicts the \
first occurrence code, or finding categories, or both.
- split: the situation is clear but the NTSB's first code divides between two or more codes, \
usually the same event in different phases; it predicts every code in the split, and says what in \
the evidence decides between them.
- evidence: the finding category follows from the situation but the specific item depends on the \
evidence; it predicts the category and says what to read for the item.

Rules for every statement and scope:
- One sentence. Start in lower case. Use capital letters only for these acronyms: {allowed}.
- No digits at all. Never state a count, share or percentage: those are counted for you later.
- No names of people, places, operators or aircraft, no dates, no registrations, no case details.
- Do not copy wording from a probable-cause sentence; say what the NTSB does in your own words.
- Codes go only in first_occurrence and finding_categories, from the codes shown in the cases.

Return at most {max_new} new lessons. Edit an existing lesson (by its id) when the cases show it \
should be broader, narrower or corrected. Retire a lesson (by its id) only when the cases show it \
is wrong. Return empty lists when nothing should change."""

SYSTEM_APPLY: Final = """You decide which coding lessons cover an accident, from the NTSB's \
probable-cause sentence alone. A lesson covers the accident when its situation and scope describe \
what the sentence says happened. Judge by the situation only; do not guess how the accident was \
coded. Answer with the ids of every lesson that covers it, or an empty list.

The lessons:
"""

SYSTEM_REVISE: Final = """You maintain coding lessons about how the NTSB codes closed US \
general-aviation accidents. The lesson below was judged to cover the cases shown, but the NTSB's \
codes disagree with it in more of them than they agree. Either edit it so its situation, scope and \
prediction fit what the NTSB does, or retire it if no correct lesson can be made from it. The same \
rules hold as when it was written: one sentence, lower case except the acronyms {allowed}, no \
digits, no names, places, operators, aircraft, dates or registrations, no copied wording, and codes \
only in first_occurrence and finding_categories."""

CODING_PREFACE: Final = """In this task you are not given the evidence. You are given the NTSB's \
own probable-cause statement for one accident, as the field `ntsb_probable_cause`. Code it as the \
NTSB would. Write the evidence narrative as a one-sentence restatement of that statement, and name \
`ntsb_probable_cause` as the evidence used.

"""

MEMORY_HEADING: Final = "\n\n## Coding memory (lessons learned from earlier NTSB cases)\n"


class LessonDraft(BaseModel):
    """A lesson as the learner writes it; the script assigns its id and counts its support."""

    model_config = ConfigDict(extra="forbid")
    kind: Kind
    statement: str
    scope: str
    first_occurrence: list[str]
    finding_categories: list[str]


class LessonEdit(LessonDraft):
    """A change to an existing lesson."""

    lesson_id: str


class ProposeReply(BaseModel):
    """The propose step's reply."""

    model_config = ConfigDict(extra="forbid")
    new: list[LessonDraft]
    edits: list[LessonEdit]
    retire: list[str]


class ApplyReply(BaseModel):
    """The apply step's reply: the ids of the lessons that cover the case."""

    model_config = ConfigDict(extra="forbid")
    applies: list[str]


class ReviseReply(LessonDraft):
    """The revise step's reply: an edited lesson, or a retirement."""

    action: Literal["edit", "retire"]


def _occurrence(code: str, tables: CodeTables) -> str:
    return f"{code} {tables.phases.get(code[:3], '?')} / {tables.events.get(code[3:], '?')}"


def _finding(code: str, tables: CodeTables) -> str:
    return f"{code} {tables.items.get(code[:8], '?')} / {tables.modifiers.get(code[8:], '?')}"


def render_case(case: LearningCase, label: str, tables: CodeTables) -> str:
    """One case for the learner, under a position label, never its case number."""
    occurrence = "; ".join(_occurrence(c, tables) for c in case.occurrence)
    findings = "; ".join(_finding(c, tables) for c in case.findings) or "(none flagged)"
    return (f"{label}. cause: {case.cause}\n   occurrence codes in order: {occurrence}\n"
            f"   flagged findings: {findings}")


def propose_user(memory_text: str, cases: Sequence[LearningCase], tables: CodeTables) -> str:
    """The propose step's user text: the current lessons, then the batch of cases."""
    lessons = memory_text or "(no lessons yet)"
    batch = "\n".join(render_case(c, f"K{i}", tables) for i, c in enumerate(cases, start=1))
    return f"Current lessons:\n{lessons}\n\nCases:\n{batch}"


def apply_user(cause: str) -> str:
    """The apply step's user text: the cause sentence and nothing else."""
    return f"Probable cause: {cause}\n\nWhich lessons cover this accident?"


def revise_user(
    lesson_text: str,
    disagreeing: Sequence[LearningCase],
    agreeing: Sequence[LearningCase],
    tables: CodeTables,
) -> str:
    """The revise step's user text: the lesson, cases that disagree, and cases that agree."""
    bad = "\n".join(render_case(c, f"D{i}", tables) for i, c in enumerate(disagreeing, start=1))
    good = "\n".join(render_case(c, f"A{i}", tables) for i, c in enumerate(agreeing, start=1))
    return (f"The lesson:\n{lesson_text}\n\nCases where the NTSB's codes disagree with it:\n{bad}"
            f"\n\nCases where they agree:\n{good or '(none)'}")


def coding_system(tables: CodeTables, guidance: Sequence[str], memory: Memory | None) -> str:
    """The coding test's system text: the preface, arm B's answer text, tables, guidance, memory."""
    base = (f"{CODING_PREFACE}{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables)}"
            f"{prompt.guidance_block(guidance)}")
    if memory is None or not memory.lessons:
        return base
    return f"{base}{MEMORY_HEADING}{render_memory(memory, tables)}"
```

The `{allowed}` and `{max_new}` placeholders are filled once, at import, from `checks.ALLOWED_WORDS` (sorted, comma-separated) and `MAX_NEW_PER_CALL`: define the constants with `.format(...)` applied, importing `ALLOWED_WORDS` from `memory.checks`. Confirm `prompt.tables_block` and `prompt.guidance_block` take these arguments (the survey found `tables_block(tables, *, case_number=None)` and `guidance_block(names)`); `coding_system` composes the same pieces in the same order as `scoring/runner.py:_system_text`.

- [ ] **Step 4: Run the prompt tests.**

Run: `uv run pytest tests/test_memory_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing client tests.**

```python
"""The gated Claude client (decisions 0202, 0207). A fake SDK object; offline; no key."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anthropic
import pytest

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import claude
from ntsb_probable_cause.scoring.budget import learning_month_spent


def _message(text: str | None, stop: str = "end_turn") -> SimpleNamespace:
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage)


class FakeMessages:
    def __init__(self, replies: list[SimpleNamespace]) -> None:
        self.replies = replies
        self.created: list[dict[str, object]] = []
        self.batches = SimpleNamespace(create=self._create_batch, retrieve=self._retrieve,
                                       results=self._results)
        self.batch_requests: list[list[dict[str, object]]] = []

    def create(self, **params: object) -> SimpleNamespace:
        self.created.append(params)
        return self.replies.pop(0)

    def _create_batch(self, *, requests: list[dict[str, object]]) -> SimpleNamespace:
        self.batch_requests.append(requests)
        return SimpleNamespace(id="batch-1")

    def _retrieve(self, batch_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=batch_id, processing_status="ended")

    def _results(self, batch_id: str) -> list[SimpleNamespace]:
        requests = self.batch_requests[-1]
        return [
            SimpleNamespace(custom_id=r["custom_id"],
                            result=SimpleNamespace(type="succeeded", message=_message('{"applies": []}')))
            for r in reversed(requests)
        ]


def _client(tmp_path: Path, replies: list[SimpleNamespace]) -> tuple[claude.LearningClient, FakeMessages]:
    messages = FakeMessages(replies)
    sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=messages))
    client = claude.LearningClient(sdk, tmp_path, "run-1", commit=("abc1234", False),
                                   forbidden=frozenset({"DEV400CASE"}))
    return client, messages


def _call(role: str = "propose", case_ids: tuple[str, ...] = ("A1",), user: str = "u") -> claude.Call:
    return claude.Call(role=role, model=claude.SONNET, effort="high", system="s", user=user,
                       schema={"type": "object"}, max_tokens=16000, case_ids=case_ids)


def test_a_repeated_call_is_answered_from_the_record_without_paying_twice(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [_message('{"new": [], "edits": [], "retire": []}')])
    first = client.send(_call())
    again = client.send(_call())
    assert first.ok and again == first
    assert len(messages.created) == 1


def test_a_refusal_or_a_truncation_is_a_failed_reply_not_an_exception(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [_message(None, stop="refusal"), _message("{", stop="max_tokens")])
    assert not client.send(_call(user="a")).ok
    assert not client.send(_call(user="b")).ok


def test_a_forbidden_case_or_role_is_refused_before_any_call(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [])
    with pytest.raises(ConfigurationError):
        client.send(_call(case_ids=("DEV400CASE",)))
    with pytest.raises(ConfigurationError):
        client.send(_call(role="answer"))
    assert messages.created == []


def test_effort_and_structured_output_are_stated_on_every_call() -> None:
    params = _call().params()
    assert params["output_config"] == {"effort": "high",
                                       "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert "thinking" not in params and "tool_choice" not in params


def test_batch_results_are_matched_by_id_whatever_their_order(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [])
    calls = [_call(role="apply", user=f"u{i}") for i in range(3)]
    replies = client.send_batch(calls, sleep=lambda _: None)
    assert set(replies) == {c.key() for c in calls}
    assert all(r.ok and r.batch for r in replies.values())
    assert len(messages.batch_requests) == 1


def test_cost_is_priced_from_usage_and_written_as_learning_spend(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [_message('{"new": [], "edits": [], "retire": []}')])
    reply = client.send(_call())
    price = sources.claude_price(claude.SONNET, batch=False)
    assert reply.cost_usd == pytest.approx((1000 * price.input_usd_per_mtok + 200 * price.output_usd_per_mtok) / 1e6)
    from datetime import UTC, datetime
    assert learning_month_spent(tmp_path, now=datetime.now(UTC)) == pytest.approx(reply.cost_usd)
```

Add one more test for resume: write a `batches.jsonl` line `{"batch_id": "batch-0", "keys": [...], "finished": false}` holding exactly the calls' keys, call `send_batch`, and assert `messages.batch_requests == []` (the recorded batch is waited on, not sent again); have the fake's `_results` answer for `"batch-0"` from the recorded keys.

- [ ] **Step 6: Implement `memory/claude.py`.**

```python
"""The learner's transport: the Claude API, for learning calls only (decisions 0202, 0207).

Not a ``model.client.ModelClient``: it carries no ``Payload`` and serves no answering call. Every
call states its effort and asks for structured output; thinking stays at the model's default.
Every reply is recorded under the run folder before it is used, so a repeated call is answered
from the record and never paid for twice. A refused or truncated reply is a failed reply.
"""

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

import anthropic
from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory.lessons import estimated_tokens
from ntsb_probable_cause.scoring.budget import SpendRecord, write_spend

SONNET: Final = "claude-sonnet-5-5"
HAIKU: Final = "claude-haiku-5-5"
ROLES: Final = frozenset({"propose", "apply", "revise", "agreement", "probe"})
CALLS_FILE: Final = "calls.jsonl"
BATCHES_FILE: Final = "batches.jsonl"
FAILED_STOPS: Final = frozenset({"refusal", "max_tokens"})
Effort = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Call:
    """One learner request, exactly as sent."""

    role: str
    model: str
    effort: Effort
    system: str
    user: str
    schema: dict[str, object]
    max_tokens: int
    case_ids: tuple[str, ...]

    def params(self) -> dict[str, object]:
        """The Messages API parameters; the system text is cached (the memory repeats)."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": self.user}],
            "output_config": {"effort": self.effort,
                              "format": {"type": "json_schema", "schema": self.schema}},
        }

    def key(self) -> str:
        """The request's hash: its record key, and its batch ``custom_id``."""
        body = json.dumps(self.params(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(body.encode()).hexdigest()[:32]


class Reply(BaseModel):
    """One recorded reply, failed or not, with its usage and price."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    role: str
    model: str
    effort: str
    batch: bool
    text: str | None
    stop_reason: str | None
    stop_category: str | None
    error: str | None
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    cost_usd: float

    @property
    def ok(self) -> bool:
        """A usable reply: text, and no failure."""
        return self.text is not None and self.error is None


def cost_usd(
    input_tokens: int, output_tokens: int, cache_write_tokens: int, cache_read_tokens: int,
    price: sources.ClaudePrice,
) -> float:
    """A reply's price: each kind of token at its own rate (thinking is billed as output)."""
    return (input_tokens * price.input_usd_per_mtok + output_tokens * price.output_usd_per_mtok
            + cache_write_tokens * price.cache_write_usd_per_mtok
            + cache_read_tokens * price.cache_read_usd_per_mtok) / 1e6


def _reply(call: Call, message: object | None, *, batch: bool, error: str | None = None) -> Reply:
    usage = getattr(message, "usage", None)
    counts = [int(getattr(usage, name, 0) or 0) for name in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    stop = getattr(message, "stop_reason", None)
    # A refusal's category (decision 0207 item 4); informational, may be absent. Confirm the
    # attribute names against the shape probe's saved replies (rule 2).
    category = getattr(getattr(message, "stop_details", None), "category", None)
    text = next((b.text for b in getattr(message, "content", []) if b.type == "text"), None)
    if stop in FAILED_STOPS:
        error, text = error or f"stopped: {stop}", None
    price = sources.claude_price(call.model, batch=batch)
    return Reply(key=call.key(), role=call.role, model=call.model, effort=call.effort, batch=batch,
                 text=text, stop_reason=stop, stop_category=category, error=error, input_tokens=counts[0],
                 output_tokens=counts[1], cache_write_tokens=counts[2], cache_read_tokens=counts[3],
                 cost_usd=cost_usd(*counts, price))


class LearningClient:
    """Learner calls, sync or in batches, refused outside their role and the learning part."""

    def __init__(self, sdk: anthropic.Anthropic, runs_dir: Path, run_id: str, *,
                 commit: tuple[str, bool], forbidden: frozenset[str]) -> None:
        self._sdk = sdk
        self._runs_dir = runs_dir
        self._run_id = run_id
        self._commit = commit
        self._forbidden = forbidden
        self._folder = runs_dir / run_id
        self._folder.mkdir(parents=True, exist_ok=True)
        self._replies: dict[str, Reply] = {}
        calls = self._folder / CALLS_FILE
        if calls.exists():
            for line in calls.read_text().splitlines():
                reply = Reply.model_validate_json(line)
                if reply.ok:
                    self._replies[reply.key] = reply

    def _check(self, call: Call) -> None:
        if call.role not in ROLES:
            raise ConfigurationError(f"the Claude transport serves learning calls only, not {call.role!r} (0202)")
        if hit := set(call.case_ids) & self._forbidden:
            raise ConfigurationError(f"{len(hit)} case(s) outside the learning part (0200)")
        prompt = estimated_tokens(call.system + call.user)
        if call.model == HAIKU and prompt > sources.HAIKU_55_PROMPT_LIMIT:
            raise ConfigurationError(f"a Haiku prompt of about {prompt} tokens passes its price limit")

    def _record(self, replies: Sequence[Reply], *, model: str) -> None:
        with (self._folder / CALLS_FILE).open("a") as out:
            for reply in replies:
                out.write(reply.model_dump_json() + "\n")
        for reply in replies:
            if reply.ok:
                self._replies[reply.key] = reply
        sha, dirty = self._commit
        write_spend(self._runs_dir, SpendRecord(
            job_id=self._run_id, kind="learning", model=model, started=datetime.now(UTC),
            calls=len(replies), cost_usd=sum(r.cost_usd for r in replies), commit_sha=sha, dirty=dirty))

    def send(self, call: Call) -> Reply:
        """One call now, at the standard price; a recorded usable reply is returned instead."""
        self._check(call)
        if (known := self._replies.get(call.key())) is not None:
            return known
        try:
            message = self._sdk.messages.create(**call.params())  # type: ignore[arg-type]
            reply = _reply(call, message, batch=False)
        except anthropic.APIError as exc:
            reply = _reply(call, None, batch=False, error=f"{type(exc).__name__}: {exc}")
        self._record([reply], model=call.model)
        return reply

    def send_batch(self, calls: Sequence[Call], *, every_seconds: float = 60.0,
                   sleep: Callable[[float], None] = time.sleep) -> dict[str, Reply]:
        """Calls in one batch at the batch price; a recorded unfinished batch is waited on."""
        for call in calls:
            self._check(call)
        todo = {c.key(): c for c in calls if c.key() not in self._replies}
        if todo:
            batch_id = self._open_batch(set(todo)) or self._submit(list(todo.values()))
            while self._sdk.messages.batches.retrieve(batch_id).processing_status != "ended":
                sleep(every_seconds)
            got: list[Reply] = []
            for result in self._sdk.messages.batches.results(batch_id):
                call = todo[result.custom_id]
                kind = result.result.type
                message = result.result.message if kind == "succeeded" else None
                got.append(_reply(call, message, batch=True, error=None if message else kind))
            missing = set(todo) - {r.key for r in got}
            got.extend(_reply(todo[k], None, batch=True, error="no result") for k in sorted(missing))
            self._record(got, model=calls[0].model)
            self._mark_finished(batch_id)
        return {c.key(): self._replies.get(c.key()) or self._failed(c) for c in calls}
```

Complete the class with three small helpers, written to these contracts:
- `_submit(calls) -> str`: `self._sdk.messages.batches.create(requests=[{"custom_id": c.key(), "params": c.params()} for c in calls]).id`, then append `{"batch_id": id, "keys": sorted(keys), "finished": false}` to `batches.jsonl` before returning (so a crash while waiting resumes on the same batch).
- `_open_batch(keys) -> str | None`: the id of the last `batches.jsonl` row whose `keys` equal `keys` and whose `finished` is false; a later row for the same id with `finished: true` closes it.
- `_mark_finished(batch_id)`: append `{"batch_id": id, "keys": [...], "finished": true}`.
- `_failed(call) -> Reply`: the last recorded failed reply for that key from `calls.jsonl` (read on demand), so the caller sees why it failed.
Mixed models in one batch are refused in `send_batch` (raise `ConfigurationError` if `{c.model for c in calls}` has more than one), so spend rows name one model. Remove the `type: ignore` if mypy accepts the call without it.

- [ ] **Step 7: Run the client tests and the lints.**

Run: `uv run pytest tests/test_memory_claude.py tests/test_memory_prompts.py -v && uv run mypy && uv run lint-imports && uv run deptry .`
Expected: PASS; mypy clean; contracts KEPT (the grimp test from Task 6 now finds `anthropic` imported by `memory.claude` only); deptry clean.

- [ ] **Step 8: Commit.**

```bash
git add pyproject.toml uv.lock src/ntsb_probable_cause/memory/prompts.py src/ntsb_probable_cause/memory/claude.py tests/test_memory_prompts.py tests/test_memory_claude.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the learner's prompts and the gated Claude client (decisions 0202, 0207)"
```

---

### Task 11: Keys from `pass`, and the shape probe (paid, cents of credit)

**Files:**
- Create: `scripts/with_pass_keys.sh`, `scripts/memory_shape_probe.py`, `docs/results/memory-shape-probe.txt` (Step 5)
- Modify: `Makefile`, `scripts/README.md`
- Test: `tests/test_paid_run.py` (or a new `tests/test_with_pass_keys.py` in its style), `tests/test_memory_shape_probe.py`

**Interfaces:**
- Produces: `scripts/with_pass_keys.sh <command...>` exports `OPENROUTER_API_KEY` (from `pass` entry `${NTSB_PASS_OPENROUTER:-api/openrouter}`) and `ANTHROPIC_API_KEY` (from `${NTSB_PASS_ANTHROPIC:-api/anthropic}`), prints neither, then `exec`s the command. Every paid `mem-` target runs through it.

- [ ] **Step 1: Write the wrapper and its test.**

```bash
#!/usr/bin/env bash
# Run one command with the coding memory's two keys from `pass`, printing neither (0202, 0207).
# Usage: scripts/with_pass_keys.sh <command> [args...]
set -euo pipefail
OPENROUTER_API_KEY="$(pass show "${NTSB_PASS_OPENROUTER:-api/openrouter}" | sed -n 1p)"
ANTHROPIC_API_KEY="$(pass show "${NTSB_PASS_ANTHROPIC:-api/anthropic}" | sed -n 1p)"
export OPENROUTER_API_KEY ANTHROPIC_API_KEY
exec "$@"
```

Test it the way `tests/test_paid_run.py` tests `paid_run.sh`'s key reading: a fake `pass` on `PATH` that echoes a known secret per entry, run `scripts/with_pass_keys.sh env`, and assert both variables are set in the child's environment while neither secret appears in stderr; and that `NTSB_PASS_ANTHROPIC` overrides the entry name. Make the script executable (`chmod +x`).

- [ ] **Step 2: Run the test.**

Run: `uv run pytest tests/test_with_pass_keys.py -v` (or the `test_paid_run.py` addition)
Expected: PASS.

- [ ] **Step 3: Write `scripts/memory_shape_probe.py`.** Docstring `Status`: "One-shot probe (decision 0202 item 5, rule 2), paid: a few cents of plan credit. Invented text only; no case is read." `main(argv) -> int`, all output also to `--out`:
  1. Refuse a dirty tree (`gitinfo.commit_state()`), and check the learning line (`budget.check_learning_budget(runs_dir, 0.10, settings.learning_monthly_budget_usd, now=...)`).
  2. `sdk = anthropic.Anthropic(api_key=Settings().require_anthropic_key())`. For `SONNET` and `HAIKU`: `sdk.models.retrieve(id)`; print `id`, `display_name`, `max_input_tokens`, `max_tokens` (each through `getattr(..., None)`).
  3. One `LearningClient.send` of a `Call(role="probe", model=SONNET, effort="high", system=<an invented two-lesson memory>, user=<an invented cause>, schema=strict_schema(prompts.ProposeReply), max_tokens=16000, case_ids=())`; print `stop_reason`, the content block types seen, the four usage counts, the priced cost, and whether `ProposeReply.model_validate_json(reply.text)` succeeds.
  4. One `LearningClient.send_batch` of two `Call(role="probe", model=HAIKU, effort="low", schema=strict_schema(prompts.ApplyReply), max_tokens=2048, ...)` with invented causes; print the same per reply, and the batch's wall-clock time.
  5. Print one line per check with `ok` or `FAILED`: both ids retrievable; Sonnet's reply parses as `ProposeReply`; both Haiku replies parse as `ApplyReply`; every reply has `stop_reason == "end_turn"`; no reply's output tokens reached its `max_tokens`. Return 1 if any check failed.
  Its test (`tests/test_memory_shape_probe.py`) runs `main` with a fake SDK (the `FakeMessages` pattern of Task 10 plus a `models.retrieve` returning a `SimpleNamespace`) and a monkeypatched `Settings`, and asserts every check line reads `ok` and no case file is opened (monkeypatch `samples.load_cases` to raise).

```make
mem-shape-probe: ## The Claude API shape probe, ONCE (0202 item 5; paid, cents of credit)
	scripts/with_pass_keys.sh uv run python -m scripts.memory_shape_probe --out docs/results/memory-shape-probe.txt
```

- [ ] **Step 4: Run the tests.**

Run: `uv run pytest tests/test_memory_shape_probe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit, then run the probe once (paid).** Commit Steps 1–4 first (the probe records a clean commit). Andy stores the key in `pass` at `api/anthropic` first (or sets `NTSB_PASS_ANTHROPIC`).

Run: `make mem-shape-probe`
Expected: every check `ok`; cost a few cents. If any check fails, stop: fix the cause (a wrong id, a schema the API rejects, a truncated reply) under Deviations, and run it again; the probe is the only place rule 2's wire shapes are confirmed.

- [ ] **Step 6: Commit the result.**

```bash
git add scripts/with_pass_keys.sh scripts/memory_shape_probe.py scripts/README.md Makefile tests/test_with_pass_keys.py tests/test_memory_shape_probe.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: keys from pass and the Claude API shape probe (decision 0202)"
git add docs/results/memory-shape-probe.txt docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the shape probe's result (decision 0202 item 5)"
```

---

### Task 12: The learner script

**Files:**
- Create: `scripts/memory_learn.py`
- Modify: `Makefile`, `scripts/README.md`
- Test: `tests/test_memory_learn.py`

**Interfaces:**
- Consumes: everything in `memory.*`; `scoring.codes.load_tables`; `scoring.hypothesis.strict_schema`; `budget.check_learning_budget`; `gitinfo.commit_state`, `gitinfo.is_committed`; `Settings`.
- Produces: subcommands `propose`, `agreement`, `finish`; pure helpers `chunks(cases, size=30) -> list[list[LearningCase]]`, `next_lesson_id(existing: Iterable[str]) -> str`, `merge_proposal(memory: Memory, reply: ProposeReply, year: int, tables: CodeTables, next_id: Callable[[], str]) -> tuple[Memory, list[str]]` (the merged memory, and messages for drafts dropped), `merge_revision(memory, lesson_id, reply: ReviseReply, year, tables) -> tuple[Memory, list[str]]`, `parse_applier(text: str) -> Applier`; `Applier = Literal["haiku-low", "haiku-medium", "sonnet-high"]`; `APPLIERS: dict[Applier, tuple[str, Effort]]`.

- [ ] **Step 1: Write the failing tests for the pure helpers.**

```python
"""The learner script's pure parts (decisions 0201-0204). Offline; made-up replies."""

import pytest

from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction
from ntsb_probable_cause.memory.prompts import LessonDraft, LessonEdit, ProposeReply, ReviseReply
from ntsb_probable_cause.scoring.codes import load_tables
from scripts import memory_learn as ml

TABLES = load_tables()


def _draft(**changes: object) -> LessonDraft:
    base: dict[str, object] = {"kind": "convention", "statement": "the NTSB codes it so",
                               "scope": "a scope", "first_occurrence": ["552230"], "finding_categories": []}
    base.update(changes)
    return LessonDraft.model_validate(base)


def test_ids_continue_after_the_highest() -> None:
    assert ml.next_lesson_id([]) == "L001"
    assert ml.next_lesson_id(["L001", "L007"]) == "L008"


def test_new_lessons_get_ids_and_bad_codes_are_dropped() -> None:
    ids = iter(["L001", "L002"])
    reply = ProposeReply(new=[_draft(), _draft(first_occurrence=["999999"])], edits=[], retire=[])
    memory, dropped = ml.merge_proposal(Memory(name="d", periods=(2009,)), reply, 2009, TABLES, lambda: next(ids))
    assert [lesson.lesson_id for lesson in memory.lessons] == ["L001"]
    assert len(dropped) == 1


def test_more_than_five_new_lessons_are_cut_to_five() -> None:
    counter = iter(f"L{i:03d}" for i in range(1, 20))
    reply = ProposeReply(new=[_draft()] * 7, edits=[], retire=[])
    memory, dropped = ml.merge_proposal(Memory(name="d", periods=(2009,)), reply, 2009, TABLES, lambda: next(counter))
    assert len(memory.lessons) == 5 and len(dropped) == 2


def test_an_edit_replaces_a_lesson_and_keeps_its_history() -> None:
    old = Lesson(lesson_id="L001", kind="convention", statement="old", scope="s",
                 predicts=Prediction(first_occurrence=("552230",)), written_in=2009)
    edit = LessonEdit(lesson_id="L001", **_draft(statement="new").model_dump())
    reply = ProposeReply(new=[], edits=[edit], retire=["L404"])
    memory, dropped = ml.merge_proposal(Memory(name="d", periods=(2009,), lessons=(old,)), reply, 2010, TABLES, lambda: "L002")
    assert memory.lessons[0].statement == "new"
    assert memory.lessons[0].history == ("edited in 2010",)
    assert any("L404" in d for d in dropped)


def test_a_revision_can_retire() -> None:
    old = Lesson(lesson_id="L001", kind="convention", statement="old", scope="s",
                 predicts=Prediction(first_occurrence=("552230",)), written_in=2009)
    reply = ReviseReply(action="retire", **_draft().model_dump())
    memory, _ = ml.merge_revision(Memory(name="d", periods=(2009,), lessons=(old,)), "L001", reply, 2009, TABLES)
    assert memory.lessons == ()


def test_the_applier_is_read_from_the_agreement_result() -> None:
    assert ml.parse_applier("pairs either marked: 40\nchosen applier: haiku-medium\n") == "haiku-medium"
    with pytest.raises(ValueError):
        ml.parse_applier("no choice here")


def test_cases_go_in_thirties_in_id_order() -> None:
    assert [len(c) for c in ml.chunks(list(range(65)))] == [30, 30, 5]
```

A draft is dropped (with a message) when any code in `first_occurrence` is not a six-digit code composable from `TABLES.phases` and `TABLES.events`, any code in `finding_categories` is not in `TABLES.categories`, or `Lesson` validation fails (for example a split with one code).

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_memory_learn.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement the pure helpers** in `scripts/memory_learn.py` to make those tests pass. Docstring `Status`: "Live tool for the coding memory's pilot (decisions 0200-0204), paid from plan credits (0202, 207). Writes run folders under `NTSB_RUNS_DIR` (never committed) and, from `finish`, an unchecked snapshot." Sections `What it reads`, `What it writes`, `Usage` for the three subcommands.

- [ ] **Step 4: Implement the three subcommands.** Shared setup for every subcommand: refuse a dirty tree (`gitinfo.commit_state()`); `tables = load_tables()`; `forbidden = pool.excluded_ids()`; the client is `LearningClient(anthropic.Anthropic(api_key=settings.require_anthropic_key()), settings.runs_dir, run_id, commit=..., forbidden=forbidden)` through a factory parameter on `main` so tests inject a fake. A new run's id is `f"{stamp}-{sha}-memory-{period}"`; `--resume RUN_ID` reuses one (its recorded replies are reused by the client). Before each phase, `budget.check_learning_budget` with that phase's projection: every planned call at its model's standard (sync) or batch price, priced at its estimated input tokens and its full `max_tokens` of output.

  **`propose --period YEAR --from {empty,NAME} --to NAME [--resume RUN_ID]`:**
  1. Start memory: `Memory(name=to, periods=())` for `empty`, else `snapshots.load_checked(from)`; the draft holds its kept lessons and its pushed-out lessons (both may re-enter under the cap at `finish`). `periods` becomes the start's periods plus `YEAR`.
  2. `cases = pool.learning_part(processed, years={YEAR})`; `for chunk in chunks(cases)`: `client.send(Call(role="propose", model=SONNET, effort="high", system=prompts.SYSTEM_PROPOSE, user=prompts.propose_user(render_memory(kept_view, tables), chunk, tables), schema=strict_schema(prompts.ProposeReply), max_tokens=16000, case_ids=tuple(c.case_id for c in chunk)))`, where `kept_view` is the draft less its pushed-out lessons. A failed reply is logged and the chunk skipped; an `ok` reply is parsed with `ProposeReply.model_validate_json` (a parse failure is logged and skipped) and merged with `merge_proposal`.
  3. After every chunk, write the draft to `<run folder>/draft.json`; at the end print counts only: chunks, failed chunks, lessons, drafts dropped.

  **`agreement --resume RUN_ID --out docs/results/memory-agreement-dev.txt`** (2009's run only; refuses if the draft's periods are not `(2009,)`):
  1. `sample = random.Random(20261014).sample(pool.learning_part(processed, years={2009}), 100)`.
  2. For each applier in order `haiku-low`, then `sonnet-high` (the reference): `client.send_batch([Call(role="agreement", model=m, effort=e, system=prompts.SYSTEM_APPLY + render_for_apply(draft), user=prompts.apply_user(c.cause), schema=strict_schema(prompts.ApplyReply), max_tokens=2048 for Haiku and 16000 for Sonnet, case_ids=(c.case_id,)) for c in sample])`; parse each `ok` reply to a frozenset of known lesson ids (unknown ids dropped); a failed reply counts as an empty set and is counted.
  3. `both, either = curate.agreement(haiku, sonnet)`; if `either == 0`, write the result and return 1 (no lesson covered any case: the pilot cannot proceed). If `both / either >= 0.90`, the applier is `haiku-low`; else run `haiku-medium` the same way and take it if its rate reaches 0.90; else `sonnet-high`.
  4. Write the file, counts only: run id, commit, lessons in the draft, the sample size and seed, per applier tried its failed replies, pairs both marked, pairs either marked and the rate to one decimal place, the bar (90%), and a last line `chosen applier: <name>`.

  **`finish --resume RUN_ID --to NAME`:**
  1. Refuse unless `docs/results/memory-agreement-dev.txt` is committed (`gitinfo.is_committed`); `applier = parse_applier(that file's text)`; `model, effort = APPLIERS[applier]`.
  2. `cases = pool.learning_part(processed, years=set(draft.periods))` (every period so far).
  3. `applies = apply(draft, cases)`: one `send_batch` of apply calls as in `agreement` step 2 with the chosen model and effort; returns `case id -> frozenset of lesson ids`.
  4. `support = curate.count_support(draft lessons, cases, applies)`; for each lesson with `curate.needs_revision(support[id])`: `client.send(Call(role="revise", model=SONNET, effort="high", system=prompts.SYSTEM_REVISE, user=prompts.revise_user(render_lesson(lesson with support, tables), up to 10 disagreeing cases, up to 5 agreeing cases, tables), schema=strict_schema(prompts.ReviseReply), max_tokens=16000, case_ids=...))`, then `merge_revision`. Disagreeing and agreeing cases are the first by case id.
  5. If any lesson was revised, apply again (step 3) and recount. Retire every lesson with `curate.unused(...)`. `kept, pushed = curate.apply_cap(curate.with_support(lessons, support), tables, CAP_TOKENS)`.
  6. `snapshots.save(Memory(name=NAME, periods=draft.periods, lessons=kept, pushed_out=pushed))`; write `<run folder>/finish.json` (counts: applied cases, failed applies, revised, retired, kept, pushed out, the cap used in estimated tokens); print the same and the next step: `make mem-check SNAPSHOT=NAME`, then commit the snapshot and its stamp.

  Tests for the subcommands use a fake client factory returning a `LearningClient` over the Task 10 `FakeMessages`, a tmp `cases.parquet` (Task 8's `_write` helper; move it to `tests/conftest.py` as a fixture if two test files need it), and a tmp snapshot directory: (a) `propose` on 31 cases sends two propose calls and writes a draft; (b) `agreement` writes the file and chooses `haiku-low` when the two fakes answer alike and `sonnet-high` when Haiku never agrees; (c) `finish` refuses while the agreement file is uncommitted (monkeypatch `gitinfo.is_committed` to return False) and saves a snapshot when it is committed.

```make
mem-learn-propose: ## The learner's propose step for one period (0202; paid, plan credit)
	scripts/with_pass_keys.sh uv run python -m scripts.memory_learn propose --period $(PERIOD) --from $(FROM) --to $(TO) $(if $(RESUME),--resume $(RESUME))
mem-agreement: ## Haiku against Sonnet on 100 cases of 2009 (0204; paid, plan credit)
	scripts/with_pass_keys.sh uv run python -m scripts.memory_learn agreement --resume $(RUN) --out docs/results/memory-agreement-dev.txt
mem-learn-finish: ## Apply, count, revise, cap and save a snapshot (0201; paid, plan credit)
	scripts/with_pass_keys.sh uv run python -m scripts.memory_learn finish --resume $(RUN) --to $(TO)
```

- [ ] **Step 5: Run the tests.**

Run: `uv run pytest tests/test_memory_learn.py -v && uv run mypy && uv run ruff check scripts/memory_learn.py`
Expected: PASS; clean.

- [ ] **Step 6: Commit.**

```bash
git add scripts/memory_learn.py scripts/README.md Makefile tests/test_memory_learn.py tests/conftest.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the learner script, propose, agreement and finish (decisions 0201-0204)"
```

---

### Task 13: The coding test script

**Files:**
- Create: `scripts/memory_coding_test.py`
- Modify: `Makefile`, `scripts/README.md`
- Test: `tests/test_memory_coding_test.py`

**Interfaces:**
- Consumes: `Payload.for_coding_test` (Task 5); `memory.prompts.coding_system`, `memory.snapshots.load_checked`, `snapshots.sha256_of`; `agent.drive.drive_batch`, `agent.loop.PendingCall`, `agent.loop.LoopConfig`, `agent.loop.PASS_REASONING`, `agent.armb.FixedToolsLoop`; `scoring.prompt` (`SYSTEM_REFINE`, `REJECTED`, `refine_message`, `guidance_sha256`); `scoring.hypothesis` (`parse_hypothesis`, `parse_refinement`, `HYPOTHESIS_SCHEMA`, `REFINEMENT_SCHEMA`); `scoring.coding_stats.load_stats("mem")`, `refuse_pool_holding`; `scoring.samples.sample_ids`, `load_cases`; `budget.reserve_within_budget`, `settle`, `write_spend`; `model.client.ModelSettings`, `Turn`; `model.batch.BatchClient`; `model.openrouter.OpenRouterClient`.
- Produces: subcommands `answer --repeat {a,b}` (the **tables** condition) and `tools --source RUN_ID --repeat {a,b} [--snapshot NAME]` (the **counts** condition, or **memory** with a snapshot); class `CodingAnswerLoop` (a `DrivenLoop`); every run folder holds `spec.json`, `replies.jsonl`, `rounds.jsonl` (from `drive_batch`), `cases.jsonl` (one row per case: `case_id`, `hypothesis` as recorded JSON or null, `failure` or null, `cost_usd`) and a `spend.jsonl` row of kind `coding-test`.

- [ ] **Step 1: Write the failing tests.**

```python
"""The coding test (decisions 0204, 0205). A fake batch runner; offline; made-up cases."""

from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from scripts import memory_coding_test as ct


def test_only_the_steering_slice_is_accepted() -> None:
    ct.refuse_sample("dev-steer-400")
    for other in ("dev-400", "dev-seal-s3-400", "heldout-400", "live"):
        with pytest.raises(ConfigurationError):
            ct.refuse_sample(other)


def test_the_memory_condition_needs_the_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ct.gitinfo, "is_committed", lambda path: False)
    with pytest.raises(ConfigurationError):
        ct.refuse_memory_without_registration()
    monkeypatch.setattr(ct.gitinfo, "is_committed", lambda path: path == ct.REGISTRATION)
    ct.refuse_memory_without_registration()
```

Add three behaviour tests against a scripted batch runner (the `FakeBatchClient` pattern of `tests/test_runner.py:512`, or `ScriptedClient` of `tests/test_agent_drive.py:161`), each over two made-up cases whose causes come from a monkeypatched `ct.causes` (case id → sentence):
- `answer`: a valid stage-1 JSON then a valid refinement JSON per case produce two `cases.jsonl` rows with hypotheses; the first payload sent is `Payload.for_coding_test(<cause>)`; the system text starts with `prompts.CODING_PREFACE`.
- `answer`: a stage-1 reply that fails `parse_hypothesis` is retried once with `prompt.REJECTED` before the error in the system text; a second failure records `failure` and no hypothesis.
- `tools --snapshot`: with a checked snapshot in a tmp snapshot directory (monkeypatch `snapshots.SNAPSHOT_DIR`), the system text the post-pass sends contains `prompts.MEMORY_HEADING`; without `--snapshot` it does not; a source case with no hypothesis gets `failure="source failed"` and no call.

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_memory_coding_test.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement.** Docstring `Status`: "Live tool for the coding memory's pilot (decision 0204), paid on OpenRouter: GPT-6 Luna batch, about a cent or less a case. Development only: `dev-steer-400` and nothing else in this plan." Constants: `SAMPLE: Final = "dev-steer-400"`, `GUIDANCE: Final = ("r3-loc-stall", "r6-aircraft-control")`, `REGISTRATION: Final = Path("docs/rounds/memory-pilot.md")`, `CAP_USD: Final = 0.05`, `EXPECTED_USD_PER_CASE: Final = 0.01`, `STATS: Final = "mem"`.
  - `refuse_sample(sample)`: raise `ConfigurationError` unless `sample == SAMPLE`; then `coding_stats.refuse_pool_holding(STATS, sample)`.
  - `refuse_memory_without_registration()`: raise unless `gitinfo.is_committed(REGISTRATION)`.
  - `causes(processed) -> dict[str, str]`: `samples.load_cases(processed, samples.sample_ids(SAMPLE))` mapped to `fields.probable_cause(raw)`; a case with no cause is left out and later recorded with `failure="no cause"`.
  - `CodingAnswerLoop(case_id, cause, system, tables, settings)`: the `DrivenLoop` interface (`case_id`, `call_index`, `next_call`, `accept(reply, *, error=None, sent_at, returned_at, batch_id)`, `stop(reason)`; read `agent/drive.py:73-110` for the exact `accept` keywords). Calls: stage 1 with `ModelSettings(model=sources.DEFAULT_MODEL, price_variant="batch", reasoning_effort="medium", max_output_tokens=8000, json_schema=HYPOTHESIS_SCHEMA, schema_name="hypothesis")` and `system`; on `SchemaError`, once more with `f"{prompt.REJECTED}{error}\n\n{system}"`; then, unless the answer abstains or has no findings, stage 2 with system `f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(h, tables)}"`, `history=(Turn(role="assistant", content=<stage-1 reply text>),)` and settings with `json_schema=REFINEMENT_SCHEMA, schema_name="refinement"`; parse with `parse_refinement` (one retry the same way). Each `PendingCall` carries the same `step` values `FixedToolsLoop._build` uses for its answer and refinement calls, and an `estimated_usd` from `agent.loop.estimate_usd` (read its signature) checked against `CAP_USD`; over the cap, the case stops `"cap"`. `outcome() -> tuple[Hypothesis | None, str | None, str | None, float]` (answer, its recorded JSON, failure, priced cost).
  - `answer --repeat R`: refuse a dirty tree; `refuse_sample(SAMPLE)`; `run_id = f"{stamp}-{sha}-{SAMPLE}-mem-tables-{R}"`; write `spec.json` (sample, condition `tables`, repeat, model, reasoning, max output tokens, price variant, guidance and `prompt.guidance_sha256(GUIDANCE)`, statistics `mem`, commit, dirty, case ids); `budget.reserve_within_budget(runs_dir, run_id, len(cases) * EXPECTED_USD_PER_CASE, settings.monthly_budget_usd, now=...)`; `drive_batch(loops, BatchClient(OpenRouterClient(settings.require_openrouter_key(), base_url=settings.openrouter_base_url)), folder=folder, now=...)`; write `cases.jsonl`; write one `SpendRecord(kind="coding-test", ...)` whose `cost_usd` is the sum of `drive_batch`'s reported round costs when every round reported one, else the sum of the loops' priced costs (as decision 0135 counts); `budget.settle`.
  - `tools --source RUN_ID --repeat R [--snapshot NAME]`: refuse a dirty tree; read the source's `spec.json` (refuse unless its condition is `tables` and its sample `dev-steer-400`) and `cases.jsonl`; with `--snapshot`, `refuse_memory_without_registration()` and `memory = snapshots.load_checked(NAME)`; `run_id = f"{source}-counts-{R}"` or `f"{source}-memory-{NAME}"`; per case with a source hypothesis: `FixedToolsLoop({"ntsbNumber": case_id}, Payload.for_coding_test(cause), prompts.coding_system(tables, GUIDANCE, memory), first, first_json, None, config)`, where `config = LoopConfig(tables=tables, stats=load_stats(STATS), guidance=GUIDANCE, exclusions=frozenset(), cap_usd=CAP_USD, price_variant="batch", max_output_tokens=8000, max_coding_calls=6, pass_reasoning=PASS_REASONING, without=frozenset(), run_id=run_id, commit=(sha, dirty), model=sources.DEFAULT_MODEL, reasoning_effort="medium")` (match `LoopConfig`'s field names and types exactly as `agent/loop.py:118` defines them) and `first_json` is the source row's recorded JSON. `group=None` means no `suggest_codes` call: the coding test has no phase-of-flight evidence, and the same holds in the counts and memory conditions, so the comparison stays fair (record this in `spec.json` as `"suggest_codes": "omitted: no phase-of-flight evidence"`). `spec.json` adds the source run, the snapshot name and `snapshots.sha256_of(...)` of its file. Then the same budget, driving, `cases.jsonl` (the final answer from the loop's outcome; read `FixedToolsLoop`'s outcome accessor for the final hypothesis and failure) and spend row as `answer`.

```make
mem-coding-answer: ## The coding test's tables condition on dev-steer-400 (0204; paid, OpenRouter)
	scripts/with_pass_keys.sh uv run python -m scripts.memory_coding_test answer --repeat $(REPEAT)
mem-coding-tools: ## The counts condition, or the memory condition with SNAPSHOT (0204; paid, OpenRouter)
	scripts/with_pass_keys.sh uv run python -m scripts.memory_coding_test tools --source $(SOURCE) --repeat $(REPEAT) $(if $(SNAPSHOT),--snapshot $(SNAPSHOT))
```

- [ ] **Step 4: Run the tests and the boundary test.**

Run: `uv run pytest tests/test_memory_coding_test.py tests/test_boundary.py -v && uv run mypy && make s33-continuity`
Expected: PASS; `test_only_the_coding_test_script_opens_the_coding_test_door` now finds exactly the two files; `+t` unchanged.

- [ ] **Step 5: Commit.**

```bash
git add scripts/memory_coding_test.py scripts/README.md Makefile tests/test_memory_coding_test.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the coding test, tables, counts and memory conditions (decisions 0204, 0205)"
```

---

### Task 14: The pilot's reading

**Files:**
- Create: `scripts/memory_pilot_result.py`
- Modify: `Makefile`, `scripts/README.md`
- Test: `tests/test_memory_pilot_result.py`

**Interfaces:**
- Consumes: run folders from Task 13; `scripts._live_fence.refuse_live`; `records.split.split_record`; `scoring.metrics.score_case`, `wilson`, `bootstrap_mean`, `paired_difference`; `samples.load_cases`, `samples.seen_pairs`; `memory.snapshots.load_checked`.
- Produces: `CaseMeasures` (frozen dataclass: `top1: bool`, `top3: bool`, `recall10: float | None`); `measure_failed(*, flags_findings: bool) -> CaseMeasures` (a failed case is wrong: `top1=top3=False`, `recall10=0.0` when the verdict flags findings, else `None`); `measures(rows, verdicts, tables, seen) -> dict[str, CaseMeasures]`; `stop_rule(memory: Diff3, counts_a_vs_b: Diff3) -> tuple[bool, list[str]]` where `Diff3` is a frozen dataclass of the three paired point estimates (`top1`, `top3`, `recall10`); `main` writes `docs/results/memory-pilot-dev.txt`.

- [ ] **Step 1: Write the failing tests.**

```python
"""The pilot's reading and its registered stop rule (decision 0204). Made-up numbers; offline."""

from scripts import memory_pilot_result as pr


def test_a_finding_gain_beyond_the_noise_with_no_harm_passes() -> None:
    noise = pr.Diff3(top1=-0.01, top3=0.02, recall10=0.015)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=0.0, top3=-0.01, recall10=0.03), noise)
    assert ok, reasons


def test_a_finding_gain_inside_the_noise_does_not_pass() -> None:
    noise = pr.Diff3(top1=0.0, top3=0.0, recall10=0.02)
    ok, _ = pr.stop_rule(pr.Diff3(top1=0.05, top3=0.05, recall10=0.02), noise)
    assert not ok


def test_harm_beyond_the_noise_on_top1_fails_even_with_a_finding_gain() -> None:
    noise = pr.Diff3(top1=0.01, top3=0.01, recall10=0.01)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=-0.02, top3=0.0, recall10=0.05), noise)
    assert not ok and any("top-1" in r for r in reasons)


def test_a_failed_case_counts_as_wrong() -> None:
    got = pr.measure_failed(flags_findings=True)
    assert (got.top1, got.top3, got.recall10) == (False, False, 0.0)
    assert pr.measure_failed(flags_findings=False).recall10 is None
```

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/test_memory_pilot_result.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement.** The stop rule, exactly as registered:

```python
@dataclass(frozen=True)
class Diff3:
    """Paired point estimates on the three measures, as fractions."""

    top1: float
    top3: float
    recall10: float


def stop_rule(memory: Diff3, noise: Diff3) -> tuple[bool, list[str]]:
    """Decision 0204 item 5, as registered in docs/rounds/memory-pilot.md.

    ``memory`` is memory minus counts(a); ``noise`` is counts(b) minus counts(a). Pass only if the
    finding gain exceeds the noise on findings, and neither occurrence measure falls by more than
    its own noise.
    """
    reasons: list[str] = []
    if not memory.recall10 > abs(noise.recall10):
        reasons.append(f"finding recall@10 {memory.recall10:+.3f} is not beyond the noise {abs(noise.recall10):.3f}")
    if memory.top1 < -abs(noise.top1):
        reasons.append(f"top-1 {memory.top1:+.3f} falls beyond the noise {abs(noise.top1):.3f}")
    if memory.top3 < -abs(noise.top3):
        reasons.append(f"top-3 {memory.top3:+.3f} falls beyond the noise {abs(noise.top3):.3f}")
    return not reasons, reasons
```

  `main(argv)` takes `--tables-a --tables-b --counts-a --counts-b --memory RUN [RUN ...] --out PATH` (memory runs in period order). For every run: `refuse_live(folder)` first; read `spec.json` and refuse a sample other than `dev-steer-400`; read `cases.jsonl`. Build each case's `Verdict` with `split_record(raw)` from `samples.load_cases(processed, ids)`; score answered cases with `score_case(h, verdict, tables, seen_pairs=samples.seen_pairs(processed))` and failed ones with `measure_failed(flags_findings=bool(verdict.finding_codes_in_cause))`. Per run, print top-1 and top-3 as proportions with `wilson` intervals and finding recall@10 as a mean with a `bootstrap_mean` interval, with each measure's `n` and the run's failed cases. Paired, on cases present in both runs: tables(b) − tables(a), counts(b) − counts(a) (the noise), and each memory run − counts(a), with `paired_difference` for the two proportions and `bootstrap_mean` of per-case differences for recall (recall pairs only where both have a value). Then the stop rule on the **last** memory run (the pilot's final snapshot), with every reason; the curve (tables a, counts a, then each memory run: three measures each); each snapshot's lesson counts (kept, pushed out) from `snapshots.load_checked`; and the agreement file's last line. Counts only: no case number, no cause, no lesson text.

  It also takes `--learn-runs RUN [RUN ...]`, the learner's run folders, and prints one line, "learner refusals by category", counting the failed rows in each folder's `calls.jsonl` whose `stop_reason` is `refusal`, by `stop_category` (`none` when absent), with a test over a made-up `calls.jsonl` (decision 0207 item 4). Counts only.

```make
mem-pilot-result: ## The pilot's reading and stop rule (0204); free
	uv run python -m scripts.memory_pilot_result --tables-a $(TA) --tables-b $(TB) --counts-a $(CA) --counts-b $(CB) --memory $(MEM) --learn-runs $(LEARN) --out docs/results/memory-pilot-dev.txt
```

- [ ] **Step 4: Run the tests.**

Run: `uv run pytest tests/test_memory_pilot_result.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add scripts/memory_pilot_result.py scripts/README.md Makefile tests/test_memory_pilot_result.py docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the pilot's reading and its stop rule (decision 0204)"
```

---

### Task 15: The registration (Andy signs before any paid pilot run)

**Files:**
- Create: `docs/rounds/memory-pilot.md`

- [ ] **Step 1: Write the registration** in simplified technical English, with a glossary (rule 7). It names, before any learner or coding-test run: the samples (learning part, `dev-steer-400`); the three conditions and how each is run (Task 13's commands); the models, efforts and prices (0202, Task 4, the shape probe's result); the snapshots `pilot-2009` and `pilot-2010` and that the reading uses the last; the noise (counts(b) − counts(a), per measure); the stop rule word for word as `stop_rule`'s docstring; that failed cases count as wrong; the agreement check and its bar; the expected costs (the plan's estimates, labelled estimates); and the prediction Andy chooses to write, if any (none is required).
- [ ] **Step 2: Andy reads and approves it.** Stop here until Andy does; record Andy's approval and date in the file.
- [ ] **Step 3: Commit.**

```bash
git add docs/rounds/memory-pilot.md docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the pilot's registration, approved by Andy (decision 0204)"
```

---

### Task 16: Run the pilot (paid)

Before the first OpenRouter run, message the S4 session (as promised on 2026-10-14) that the side track will spend about $2–3 of the shared $40 development line, and wait for any objection. Every step below needs a clean tree; commit between steps. Log anything unexpected under Deviations as it happens.

- [ ] **Step 1: The two tables runs.** `make mem-spend EST=0.80`, then `make mem-coding-answer REPEAT=a` and `make mem-coding-answer REPEAT=b`. Expected: 400 rows each; failures listed by reason.
- [ ] **Step 2: The two counts runs** over tables(a): `make mem-spend EST=0.80`, then `make mem-coding-tools SOURCE=<tables a> REPEAT=a` and `REPEAT=b`.
- [ ] **Step 3: Learn 2009.** `make mem-learn-propose PERIOD=2009 FROM=empty TO=pilot-2009`; then `make mem-agreement RUN=<run id>`; commit `docs/results/memory-agreement-dev.txt`; then `make mem-learn-finish RUN=<run id> TO=pilot-2009`; `make mem-check SNAPSHOT=pilot-2009`; commit the snapshot and its stamp (`uv run pytest tests/test_memory_snapshots.py` passes first).
- [ ] **Step 4: The memory condition after 2009.** `make mem-spend EST=0.40`; `make mem-coding-tools SOURCE=<tables a> REPEAT=a SNAPSHOT=pilot-2009`.
- [ ] **Step 5: Learn 2010.** `make mem-learn-propose PERIOD=2010 FROM=pilot-2009 TO=pilot-2010`; `make mem-learn-finish RUN=<run id> TO=pilot-2010` (the applier is the one already chosen); `make mem-check SNAPSHOT=pilot-2010`; commit the snapshot and stamp.
- [ ] **Step 6: The memory condition after 2010.** `make mem-spend EST=0.40`; `make mem-coding-tools SOURCE=<tables a> REPEAT=a SNAPSHOT=pilot-2010`.
- [ ] **Step 7: The reading.** `make mem-pilot-result TA=… TB=… CA=… CB=… MEM="<2009 run> <2010 run>"`; commit `docs/results/memory-pilot-dev.txt`.
- [ ] **Step 8: Check the boundaries held.** `make check` and `make s33-continuity` pass; `uv run python -m scripts.stage_spend --stage mem` and the learning line's month total are recorded in the results commit message.

Expected costs (estimates, from the published prices and the token sizes in the spec; the results file reports what was spent): learner about $10–20 of plan credit for two periods (propose dominates: about 39 Sonnet calls a period at the standard price); coding tests about $2–3 on OpenRouter for six runs.

---

### Task 17: Close the pilot

**Files:**
- Modify: `docs/specs/2026-10-08-coding-memory-design.md` (a "Pilot result" section, counts and the stop rule's verdict, citing `docs/results/memory-pilot-dev.txt`), `CLAUDE.md` (a short section: the side track, its decisions 0200–0207, the `mem-*` targets, `NTSB_LEARNING_MONTHLY_BUDGET_USD`, `ANTHROPIC_API_KEY` and `NTSB_PASS_ANTHROPIC`), `scripts/README.md`

- [ ] **Step 1: Write the pilot's result into the note and `CLAUDE.md`**, in simplified technical English; the stop rule's verdict as it came out, passed or not.
- [ ] **Step 2: Report to Andy**: one decision per message, the next being whether to run the full pass (if passed) or to stop and keep the code as the record (if not, 0201's alternative of removing it by a record).
- [ ] **Step 3: Final checks and commit.**

Run: `make check && uv run python -m scripts.check_docs`
Expected: PASS.

```bash
git add docs/specs/2026-10-08-coding-memory-design.md CLAUDE.md scripts/README.md docs/plans/2026-10-14-coding-memory-pilot.md
git commit -m "Coding memory: the pilot's result"
```

- [ ] **Step 4: Ask Andy** whether to open a pull request for the branch (not opened without Andy's say-so).

---

## Deviations

Each entry: date, task, what changed and why.

- 2026-10-14, planning: support is not weighted towards recent periods in the pilot (the note's §4 allows it). Two periods give too little drift to weigh; the full pass's plan decides the weighting, with the pilot's counts per period as its evidence.
- 2026-10-15, Task 1: `scripts/draw_sealed.py` needed no behaviour change for an unsealed sample (it never consulted `SEALED`); only its docstring and `--sample` usage line now name `dev-steer-400`. The draw printed 401 cases (the quota rounding the other 400-case samples share), so the contamination test's 395 to 405 bound holds.
- 2026-10-15, Task 1: the seed-20261014 draw included one redacted record fixture case, so fixture ids were excluded from this draw only (`Draw.exclude_fixtures`, True for `dev-steer-400`) and the seed was kept. Decision 0203 names the seed and the pool, not the fixture rule. The other draws are unchanged (their `--verify` stays identical).
- 2026-10-15, Task 2: the `mem` pool holds 11,689 cases (6,710 in 2009-2014, 4,979 in 2015-2019), not the 11,690 the plan expected: the steering slice has 401 cases, not 400, and all 401 were inside S3's 12,090-case pool (12,090 less 401). Figure from `docs/results/mem-coding-stats.txt`.
- 2026-10-15, Task 2: `coding_stats_mem.json` is 1.27 MB, over the pre-commit `check-added-large-files` limit of 500 KB, which already exempts the two other statistics files for the same reason (pairwise code counts built by one script). The exemption regex in `.pre-commit-config.yaml` now also names `coding_stats_mem.json`.
