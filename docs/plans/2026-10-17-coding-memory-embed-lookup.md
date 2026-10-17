# Coding memory: the embedding lookup — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax. Tick each box in the same commit as its code (rule 10), and log every
> departure under **Deviations** at the end.

**Goal:** Build and run decision 0213: an embedding lookup through OpenRouter, gated free on lesson
coverage, run once on the steering slice against today's cause lookup, then once on
`dev-seal-400`.

**Architecture:** `memory/embeddings.py` (an OpenRouter embeddings client and a vector cache) and
`memory/coverage.py` (hit rate and precision) are pure library parts of the memory package, with
`lookup.by_similarity` beside `by_fit`. Committed scripts drive them: `scripts/memory_embed.py`
(model list, shape probe, embeddings), `scripts/memory_coverage.py` (the gate and the choices
file), a `--choices` option on `scripts/memory_coding_test.py tools` (the `embed-lookup`
condition), `scripts/memory_embed_result.py` (the rule), and, only if the gate prints `none`,
`scripts/memory_cause_pick.py` (the picking call).

**Tech Stack:** Python 3.14, uv, httpx, pydantic 2, pytest with `httpx.MockTransport`; OpenRouter
embeddings; GPT-6 Luna batch for the coding test; the Claude API batch for the apply step and the
picking call.

**Spec:** docs/specs/2026-10-08-coding-memory-design.md

## Global Constraints

- Spec §13 is the design; the registration `docs/rounds/memory-embed-lookup.md` fixes the steps
  and rules. No paid step, the probe included, runs before the registration is committed.
- Candidate models, exactly: `qwen/qwen3-embedding-8b`, `openai/text-embedding-3-small`,
  `openai/text-embedding-3-large`.
- Fixed: K = 5 (`lookup.K`), the support floor 10 (`lookup.MIN_APPLIES`), the snapshot
  `pilot-2010-recount`, the embedded lesson text `f"{statement} (scope: {scope})"`, the cause
  sentence alone; the coding test of 0211 unchanged (GPT-6 Luna batch, `medium`, guidance
  `r3-loc-stall` and `r6-aircraft-control`, statistics `mem`, cap $0.05).
- Never guess API details (rule 2): the client is written against the probe's saved replies.
- The memory package is imported by nothing in the library (import-linter); no new contract
  exemption: `memory/embeddings.py` writes no spend row, its scripts do.
- Spend rows: kind `embedding` for embedding calls, `probe` for the shape probe, `coding-test` and
  `learning` as now. Every OpenRouter target runs `scripts.stage_spend --stage mem` first.
- `dev-seal-400` is refused by every memory script until the registration is committed; on it only
  tables, counts, cause-lookup and embed-lookup may run. `dev-400` and `dev-seal-s3-400` are not read.
- Counts only in anything committed. Keys from `pass` through `scripts/with_pass_keys.sh`, never
  printed. Every paid step needs a clean tree.
- Ellery version 1 untouched: `make s33-continuity` reports `+t` e7811b387b31 at the end, and
  `git checkout -- docs/results/s33-fingerprint-continuity.txt` after it.

## Review Focus

1. **A case with no occurrence code** (or no flagged finding) in the coverage reading: it must not
   crash `curate.first_agrees` (which indexes `occurrence[0]`); it is left out and counted.
   Test in Task 5.
2. **An embedding reply whose `data` items come back out of order:** vectors must be matched by
   `index`, not position. Test in Task 3.
3. **A lesson whose text changed since it was cached** (another snapshot): the cache key is the
   text's hash, so it re-embeds; a vector of another length for the same model is refused. Test in
   Task 3.
4. **A choices file for another sample, snapshot, K or floor** handed to the coding test: refused
   before anything is sent. Test in Task 6.
5. **A resumed or repeated `mem-embed`** after a partial failure: cached texts are not sent again
   and not paid twice; the spend row counts only what was sent. Test in Task 4.

---

### Task 1: The records

**Files:**
- Create: `docs/decisions/0213-an-embedding-lookup-is-tried-on-the-steering-slice-and-confirmed-on-dev-seal-400.md`
- Modify: `docs/decisions/README.md`, `docs/specs/2026-10-08-coding-memory-design.md` (§13)
- Create: `docs/rounds/memory-embed-lookup.md` (committed only once Andy signs)

- [x] Decision 0213 and its README row; this plan; spec §13 amended (client in the memory package,
  the interval helper named). Commit together.
- [x] Andy signs the registration ("Approved by Andy, <date>" as its last line); commit it alone.

### Task 2: The spend kind, the model list and the shape probe

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/budget.py:42-44` (add `"embedding"` to `SpendRecord.kind`)
- Create: `scripts/memory_embed.py` (commands `models` and `probe` in this task)
- Modify: `Makefile` (`mem-embed-models`, `mem-embed-probe`; add both to `.PHONY`)
- Test: `tests/test_memory_embed.py`

**Interfaces:**
- Produces: `scripts.memory_embed.CANDIDATES: Final = ("qwen/qwen3-embedding-8b",
  "openai/text-embedding-3-small", "openai/text-embedding-3-large")`;
  `REGISTRATION: Final = Path("docs/rounds/memory-embed-lookup.md")`;
  `refuse_without_registration() -> None` (raises `ConfigurationError`);
  `MODELS_FILE = "mem/openrouter-embedding-models.json"` under `settings.data_dir`;
  `load_prices(data_dir: Path) -> dict[str, float]` (model id to dollars per input token, from the
  saved list's `pricing.prompt`, refusing a missing file or a candidate not in it);
  `slug(model: str) -> str` (`"qwen/qwen3-embedding-8b"` to `"qwen-qwen3-embedding-8b"`);
  fixtures `tests/fixtures/openrouter/embeddings/<slug>.json`.

- [x] **Step 1: Failing tests.** In `tests/test_memory_embed.py`:

```python
def test_spend_record_accepts_embedding() -> None:
    row = SpendRecord(job_id="j", kind="embedding", model="m", started=NOW, calls=1,
                      cost_usd=0.0, commit_sha="abc1234", dirty=False)
    assert row.kind == "embedding"

def test_load_prices_reads_saved_list(tmp_path: Path) -> None:
    _save_list(tmp_path, {c: "0.00000002" for c in memory_embed.CANDIDATES})
    assert memory_embed.load_prices(tmp_path)["openai/text-embedding-3-small"] == 2e-08

def test_load_prices_refuses_a_missing_candidate(tmp_path: Path) -> None:
    _save_list(tmp_path, {"openai/text-embedding-3-small": "0.00000002"})
    with pytest.raises(ConfigurationError, match="qwen/qwen3-embedding-8b"):
        memory_embed.load_prices(tmp_path)

def test_probe_refused_before_registration(monkeypatch, capsys) -> None:
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): False)
    assert memory_embed.main(["probe"], settings=_settings(tmp)) == 1
    assert "memory-embed-lookup.md is not committed" in capsys.readouterr().out

def test_probe_saves_each_reply_and_a_counts_report(tmp_path, monkeypatch) -> None:
    # MockTransport answers each candidate with a two-vector reply; the probe writes one
    # fixture per model and a report with: status, top-level keys, vectors, length, usage keys.
```

`_save_list` writes `{"data": [{"id": m, "pricing": {"prompt": p, "completion": "0"}}, ...]}`, the
shape of the list saved on 2026-10-17 (`GET https://openrouter.ai/api/v1/embeddings/models`).

- [x] **Step 2:** `uv run pytest tests/test_memory_embed.py -v` fails (no module, no kind).
- [x] **Step 3: Implement.** `models`: `GET {base_url}/api/v1/embeddings/models` (public; no key
  needed), saved verbatim to `<data_dir>/mem/openrouter-embedding-models.json`, printing the three
  candidates' prices; free, no registration needed. `probe`: refuses a dirty tree and an
  uncommitted registration; checks the monthly guard with `budget.reserve_within_budget(runs_dir,
  job_id, 0.01, settings.monthly_budget_usd, now=...)`; for each candidate, one
  `POST {base_url}/api/v1/embeddings` with bearer key and JSON `{"model": m, "input": [TEXT_A,
  TEXT_B]}` where the two texts are invented (`"a single-engine aeroplane lost power after takeoff"`,
  `"the pilot did not maintain airspeed in the turn"`); saves each response body verbatim to the
  fixture path; writes one `probe` spend row with the sum of each reply's `usage.cost` when present,
  else the price times `usage.prompt_tokens`, else times the characters over four; `budget.settle`;
  writes `docs/results/memory-embed-probe.txt` through `write_result`: per model the HTTP status,
  the body's top-level keys, the number of vectors, their length, the `usage` keys and the cost.
  Module docstring in the house style (Status, What it sends, What it writes, Usage). Makefile:

```make
mem-embed-models: ## OpenRouter's embedding model list, saved under data/mem (0213); free
	uv run python -m scripts.memory_embed models

mem-embed-probe: ## The embeddings shape probe, ONCE (0213; paid, cents)
	uv run python -m scripts.stage_spend --stage mem --estimate 0.01 && scripts/with_pass_keys.sh uv run python -m scripts.memory_embed probe --out docs/results/memory-embed-probe.txt
```

- [x] **Step 4:** tests pass; `make check` passes (apart from the known `test_store_sync` boto3
  failure).
- [x] **Step 5:** commit (`budget.py`, `scripts/memory_embed.py`, `Makefile`, the test).
- [x] **Step 6 (paid, cents; after Task 1's signature):** `make mem-embed-models`, then
  `make mem-embed-probe`. Read the saved replies. Commit the fixtures and
  `docs/results/memory-embed-probe.txt`. Any shape that differs from Task 3's sketch goes in
  Deviations, and Task 3 follows the fixture.

### Task 3: The embeddings client and the vector cache

**Files:**
- Create: `src/ntsb_probable_cause/memory/embeddings.py`
- Test: `tests/test_memory_embeddings.py`

**Interfaces:**
- Consumes: the Task 2 fixtures.
- Produces:

```python
@dataclass(frozen=True)
class EmbeddingReply:
    vectors: tuple[tuple[float, ...], ...]   # in input order
    prompt_tokens: int | None
    cost_usd: float | None                   # the reply's own cost, if it reports one

class EmbeddingClient:
    def __init__(self, api_key: str, *, base_url: str = sources.OPENROUTER_BASE_URL,
                 transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None: ...
    def embed(self, model: str, texts: Sequence[str]) -> EmbeddingReply: ...
    def close(self) -> None: ...   # and __enter__/__exit__

def text_key(text: str) -> str          # sha256 hex of the UTF-8 text

class VectorCache:
    """One JSONL file per model: {"key": ..., "vector": [...]} rows; appended, never rewritten."""
    def __init__(self, folder: Path, model: str) -> None: ...
    def get(self, text: str) -> tuple[float, ...] | None: ...
    def put(self, text: str, vector: Sequence[float]) -> None: ...
```

The sketch below assumes the documented reply `{"data": [{"index": i, "embedding": [...]}],
"usage": {"prompt_tokens": n, "cost": x}}`. The fixtures decide; follow them where they differ.

- [x] **Step 1: Failing tests.**

```python
def test_embed_parses_the_saved_reply(fixture_reply) -> None:
    client = EmbeddingClient("k", transport=_answer(200, fixture_reply))
    reply = client.embed("openai/text-embedding-3-small", ["a", "b"])
    assert len(reply.vectors) == 2 and len({len(v) for v in reply.vectors}) == 1

def test_embed_orders_by_index() -> None:
    body = {"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]}
    reply = EmbeddingClient("k", transport=_answer(200, body)).embed("m", ["a", "b"])
    assert reply.vectors == ((1.0, 0.0), (0.0, 1.0))

@pytest.mark.parametrize("body", [
    {"data": [{"index": 0, "embedding": [1.0]}]},                                   # too few
    {"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [1.0, 2.0]}]},  # lengths
    {"error": {"message": "x"}},                                                     # no data
])
def test_embed_refuses_a_malformed_reply(body) -> None:
    with pytest.raises(ModelError):
        EmbeddingClient("k", transport=_answer(200, body)).embed("m", ["a", "b"])

def test_embed_retries_once_then_fails() -> None:
    calls = _counting(_answer(503, {}))
    with pytest.raises(ModelError):
        EmbeddingClient("k", transport=calls, sleep=lambda s: None).embed("m", ["a"])
    assert calls.count == 2

def test_cache_round_trip_and_new_text_misses(tmp_path) -> None:
    cache = VectorCache(tmp_path, "m"); cache.put("a", [1.0, 2.0])
    assert VectorCache(tmp_path, "m").get("a") == (1.0, 2.0)
    assert VectorCache(tmp_path, "m").get("a changed") is None

def test_cache_refuses_a_vector_of_another_length(tmp_path) -> None:
    cache = VectorCache(tmp_path, "m"); cache.put("a", [1.0, 2.0])
    with pytest.raises(ConfigurationError):
        cache.put("b", [1.0])
```

- [x] **Step 2:** the tests fail.
- [x] **Step 3: Implement.** httpx client with bearer header and the house user agent; one retry on
  429, 500, 502, 503, 504 or a transport error, after `sleep(2.0)`; a reply is refused with
  `ModelError` unless it has exactly one vector per input, each `index` once, all of one length.
  The API key never appears in an error message.
- [x] **Step 4:** tests pass; `make check` passes.
- [x] **Step 5:** commit.

### Task 4: The embedding step, the lookup, and `dev-seal-400` in the memory scripts

**Files:**
- Modify: `scripts/memory_embed.py` (command `embed`)
- Modify: `src/ntsb_probable_cause/memory/lookup.py` (`cosine`, `by_similarity`)
- Modify: `scripts/memory_coding_test.py` (`refuse_sample`, `refuse_condition`, the `answer
  --sample` choices, `Condition` gains `"embed-lookup"`)
- Modify: `scripts/memory_cause_apply.py` (`--sample dev-seal-400`, output path by sample, `_run_id`'s
  resume check for every non-steering sample)
- Modify: `Makefile` (`mem-embed`)
- Test: `tests/test_memory_lookup.py`, `tests/test_memory_embed.py`,
  `tests/test_memory_coding_test.py`, `tests/test_memory_cause_apply.py`

**Interfaces:**
- Consumes: `EmbeddingClient`, `VectorCache`, `text_key` (Task 3); `load_prices`, `slug` (Task 2).
- Produces:

```python
# memory/lookup.py
def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector is all zeros."""

def by_similarity(
    lessons: Sequence[Lesson],
    vectors: Mapping[str, Sequence[float]],     # lesson id -> vector
    query: Sequence[float],
    *, k: int = K, min_applies: int = MIN_APPLIES,
) -> tuple[Lesson, ...]:
    """Up to ``k`` eligible lessons closest to ``query`` (decision 0213).

    Eligible: support applies >= ``min_applies`` and a vector in ``vectors``. Order: highest
    cosine, then highest fit, then most cases applied to, then lesson id.
    """
    def rank(lesson: Lesson) -> tuple[float, float, int, str]:
        applies = lesson.support.applies if lesson.support is not None else 0
        return (-cosine(vectors[lesson.lesson_id], query), -fit(lesson), -applies, lesson.lesson_id)
    eligible = [x for x in lessons if x.support is not None
                and x.support.applies >= min_applies and x.lesson_id in vectors]
    return tuple(sorted(eligible, key=rank)[:k])

def lesson_text(lesson: Lesson) -> str:
    return f"{lesson.statement} (scope: {lesson.scope})"
```

  `scripts.memory_embed.embed` writes `<runs>/<run id>/` with `vectors.json`:
  `{"model", "sample", "snapshot", "snapshot_sha256", "lessons": {id: vec}, "cases": {case_id: vec},
  "failed_cases": [ids], "commit"}` and one `spend.jsonl` row of kind `embedding`. Run id:
  `{stamp}-{commit}-memory-embed-{sample}-{slug(model)}`. The cache is `<runs>/memory-embed-cache/`.
  `memory_coding_test.SEAL_SAMPLE: Final = "dev-seal-400"`, `EMBED_REGISTRATION: Final =
  Path("docs/rounds/memory-embed-lookup.md")`, `SEAL_CONDITIONS: Final = frozenset({"tables",
  "counts", "cause-lookup", "embed-lookup"})`.

- [x] **Step 1: Failing tests.**

```python
# tests/test_memory_lookup.py
def test_by_similarity_keeps_the_floor_and_orders_by_cosine() -> None:
    lessons = [_lesson("L1", applies=20, agrees=10), _lesson("L2", applies=9, agrees=9),
               _lesson("L3", applies=30, agrees=3)]
    vectors = {"L1": [1.0, 0.0], "L2": [1.0, 0.0], "L3": [0.6, 0.8]}
    assert [x.lesson_id for x in lookup.by_similarity(lessons, vectors, [1.0, 0.0])] == ["L1", "L3"]

def test_by_similarity_breaks_ties_by_fit_then_applies_then_id() -> None:
    lessons = [_lesson("L2", 10, 5), _lesson("L1", 10, 5), _lesson("L3", 10, 9)]
    vectors = {x.lesson_id: [1.0, 0.0] for x in lessons}
    assert [x.lesson_id for x in lookup.by_similarity(lessons, vectors, [1.0, 0.0])] == ["L3", "L1", "L2"]

def test_by_similarity_skips_lessons_without_a_vector_and_caps_at_k() -> None: ...
def test_cosine_of_a_zero_vector_is_zero() -> None:
    assert lookup.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0

# tests/test_memory_embed.py
def test_embed_sends_only_uncached_texts_and_records_spend(tmp_path, monkeypatch) -> None: ...
def test_embed_rerun_sends_nothing_and_writes_a_zero_row(tmp_path, monkeypatch) -> None: ...
def test_embed_stops_when_a_lesson_fails(tmp_path, monkeypatch) -> None: ...
def test_embed_stops_past_two_percent_failed_causes(tmp_path, monkeypatch) -> None:
    # 9 of 401 cause sentences fail twice: refused, the vectors file is not written
def test_embed_allows_eight_failed_causes_and_lists_them(tmp_path, monkeypatch) -> None: ...
def test_embed_refuses_dev_seal_400_before_registration(monkeypatch, capsys) -> None: ...
def test_embed_refuses_a_model_not_in_the_candidates(capsys) -> None: ...

# tests/test_memory_coding_test.py
def test_dev_seal_400_refused_until_registered(monkeypatch) -> None: ...
def test_dev_seal_400_allows_the_four_conditions_only() -> None:
    for c in ("tables", "counts", "cause-lookup", "embed-lookup"):
        memory_coding_test.refuse_condition("dev-seal-400", c)
    for c in ("memory", "lookup"):
        with pytest.raises(ConfigurationError):
            memory_coding_test.refuse_condition("dev-seal-400", c)
def test_dev_400_still_refuses_embed_lookup() -> None: ...

# tests/test_memory_cause_apply.py
def test_dev_seal_400_apply_writes_its_own_counts_file(...) -> None:
    # out defaults to docs/results/memory-cause-apply-devseal.txt; header names 0211 and 0213
def test_resume_of_a_dev_seal_run_needs_its_sample(...) -> None: ...
```

- [x] **Step 2:** the tests fail.
- [x] **Step 3: Implement.**
  - `embed --model M [--sample S] [--snapshot pilot-2010-recount]`: refuse a dirty tree, an
    uncommitted registration, a model not in `CANDIDATES`, and a sample `refuse_sample` refuses.
    Texts: every lesson of the snapshot, kept or pushed out (`lesson_text`), then each case's cause
    sentence (`memory_coding_test.causes`). Uncached texts are sent in chunks of 64. Worst case
    before sending: the uncached characters over four, times 2.43 (`docs/results/s32-context-ratio-dev.txt`),
    times the price, reserved with `budget.reserve_within_budget`. A chunk that fails twice: if it
    holds a lesson, stop with `refused:`; else its cases are failed. More than 2% of the sample's
    cause sentences failed (`failed * 100 > sent * 2`): refused, no `vectors.json`. The spend row's
    cost: each reply's `cost_usd` when present, else the price times `prompt_tokens`, else times the
    characters over four. `budget.settle` at the end, finished or refused. Prints counts only.
  - `refuse_sample`: `dev-seal-400` allowed only when `EMBED_REGISTRATION` is committed (message
    names decision 0213); the error for other samples lists the three allowed.
  - `refuse_condition`: `dev-400` keeps `CONFIRM_CONDITIONS`; `dev-seal-400` uses `SEAL_CONDITIONS`.
  - `answer --sample` choices gain `dev-seal-400`; run ids are as now (`...-dev-seal-400-mem-tables-a`).
  - `memory_cause_apply`: `--sample` choices gain `dev-seal-400`; out path by sample
    (`dev-seal-400` → `docs/results/memory-cause-apply-devseal.txt`); `_decision` gives "decisions
    0211 and 0213" for it; `_run_id`'s resume check compares the sample named in the id (any
    non-steering sample is named) with `--sample`.
  - Makefile:

```make
mem-embed: ## Embed the lessons and a sample's cause sentences with MODEL (0213; paid, OpenRouter, cents)
	uv run python -m scripts.stage_spend --stage mem --estimate 0.05 && scripts/with_pass_keys.sh uv run python -m scripts.memory_embed embed --model $(MODEL) $(if $(SAMPLE),--sample $(SAMPLE))
```

  Also `SAMPLE=` help text on `mem-coding-answer` and `mem-cause-apply` names `dev-seal-400`.
- [x] **Step 4:** tests pass; `make check` passes.
- [x] **Step 5:** commit.

### Task 5: Lesson coverage, the gate and the choices file

**Files:**
- Create: `src/ntsb_probable_cause/memory/coverage.py`
- Create: `scripts/memory_coverage.py`
- Modify: `Makefile` (`mem-coverage`)
- Test: `tests/test_memory_coverage.py`

**Interfaces:**
- Consumes: `lookup.by_fit`, `lookup.by_similarity` (Task 4); `curate.agrees`; `pool.LearningCase`;
  an apply run's `applies.json` and `apply.json` (`memory_coding_test.read_applies`); Task 4's
  `vectors.json`.
- Produces:

```python
# memory/coverage.py
@dataclass(frozen=True)
class Coverage:
    hits: dict[str, bool]       # case id -> at least one chosen lesson agrees
    handed_out: int
    agreeing: int
    @property
    def hit_rate(self) -> float: ...     # mean of hits; 0.0 when empty
    @property
    def precision(self) -> float: ...    # agreeing / handed_out; 0.0 when none handed out

def coverage(chosen: Mapping[str, Sequence[Lesson]], cases: Mapping[str, LearningCase]) -> Coverage:
    """Scored on the case ids in ``cases`` only; a case missing from ``chosen`` has no lesson."""
    hits, handed, agreeing = {}, 0, 0
    for case_id, case in cases.items():
        lessons = chosen.get(case_id, ())
        agree = [curate.agrees(x, case) for x in lessons]
        hits[case_id] = any(agree); handed += len(lessons); agreeing += sum(agree)
    return Coverage(hits, handed, agreeing)

def verdict_cases(ids: Sequence[str], raws: Sequence[Mapping[str, object]]) -> tuple[dict[str, LearningCase], int]:
    """The cases with a cause sentence and at least one occurrence code, and how many were left out."""
```

  `scripts/memory_coverage.py`: `gate_rule(today: Coverage, candidates: Mapping[str, Coverage],
  prices: Mapping[str, float]) -> tuple[str | None, list[str]]` (the winner, and one line per
  candidate saying why it passed or not); the choices folder `<runs>/<run id>/` with `choices.json`
  (`{case_id: [lesson ids in order]}`) and its summary, `choice.json`: `{"sample",
  "snapshot", "snapshot_sha256", "k", "min_applies", "method": "embedding" | "pick", "model",
  "source_run", "commit"}`; run id `{stamp}-{commit}-memory-choices-{sample}-{slug or "pick"}`.

  `gate_rule`'s docstring is the registration's §5 text, word for word:

```python
def gate_rule(today, candidates, prices):
    """Decision 0213, as registered in docs/rounds/memory-embed-lookup.md.

    A candidate passes only if its hit rate minus today's cause lookup's, paired on the same
    cases, is positive with its whole 95% interval above zero, and its precision is no lower
    than today's. Of those that pass, the highest hit rate goes forward; an exact tie goes to the
    lower list price. None passing gives none.
    """
```

  The paired interval is `metrics.paired_difference([c.hits[i] for i in ids], [today.hits[i] for i
  in ids])`, `ids` the cases scored in both; pass when its low end is above zero and
  `c.precision >= today.precision`.

- [x] **Step 1: Failing tests.**

```python
def test_coverage_counts_hits_and_precision() -> None:
    cases = {"A": _case("A", occ=("120013",), findings=("010101",)),
             "B": _case("B", occ=("220013",), findings=())}
    chosen = {"A": [_predicts("L1", first=("120013",)), _predicts("L2", first=("999999",))],
              "B": []}
    cov = coverage.coverage(chosen, cases)
    assert cov.hits == {"A": True, "B": False}
    assert (cov.hit_rate, cov.precision) == (0.5, 0.5)

def test_verdict_cases_leaves_out_a_case_without_occurrence_codes() -> None:
    cases, left_out = coverage.verdict_cases(["A", "B"], [_raw(occ=["120013"]), _raw(occ=[])])
    assert list(cases) == ["A"] and left_out == 1

def test_gate_one_passes() -> None: ...
def test_gate_tie_goes_to_the_lower_price() -> None: ...
def test_gate_higher_hit_rate_but_lower_precision_fails() -> None: ...
def test_gate_interval_touching_zero_fails() -> None: ...
def test_gate_none_pass_gives_none() -> None: ...
def test_gate_docstring_matches_the_registration() -> None:
    # reads docs/rounds/memory-embed-lookup.md §5's text block; equal to gate_rule.__doc__ (dedented)
def test_steering_reading_writes_the_winners_choices(tmp_path) -> None: ...
def test_a_vectors_file_for_another_sample_or_snapshot_is_refused(tmp_path) -> None: ...
def test_dev_seal_reading_names_no_winner_and_writes_the_named_models_choices(tmp_path) -> None: ...
def test_picks_are_scored_and_gated_the_same_way(tmp_path) -> None: ...
```

- [x] **Step 2:** the tests fail.
- [x] **Step 3: Implement** `memory/coverage.py`, then `scripts/memory_coverage.py`:
  - Arguments: `--applies RUN` (today's apply run), `--embeds RUN [RUN ...]` (one embedding run
    per model), `[--picks RUN]`, `[--sample S]` (default the steering slice), `[--model M]` (on
    `dev-seal-400`: which embedding run's or pick's choices to write), `--out PATH`.
  - Today's choices: `lookup.by_fit(every, applied[case], k=5)`; each model's:
    `lookup.by_similarity(every, run.lessons, run.cases[case], k=5)` (no vector: no lesson); the
    picks: the pick run's ids in order (Task 8). `every` is the snapshot's lessons, kept or pushed
    out.
  - Refusals: a sample `refuse_sample` refuses; an embedding run or apply run on another sample,
    snapshot or snapshot hash; two embedding runs of one model; a live run (`refuse_live`).
  - On the steering slice: one block per lookup (hit rate, precision, lessons handed out, cases with
    none, paired hit-rate difference against today's with its interval), the gate's lines, and the
    last line `winner: <model>`, `winner: pick` or `winner: none`. The winner's choices folder is
    written; its run id is printed. With `--picks`, the picking call is gated against today's in
    the same way and the text adds its block. Output `docs/results/memory-coverage-dev.txt`.
  - On `dev-seal-400`: the same blocks, no gate, last line `description only (decision 0213)`;
    writes the choices for `--model` (or the picks). Output `docs/results/memory-coverage-devseal.txt`.
  - Makefile:

```make
mem-coverage: ## Lesson coverage and the gate on the steering slice, or SAMPLE=dev-seal-400 (0213); free
	uv run python -m scripts.memory_coverage --applies $(or $(APPLIES),20261017T090550Z-0b949a6-memory-cause-apply-pilot-2010-recount) --embeds $(EMBEDS) $(if $(PICKS),--picks $(PICKS)) $(if $(SAMPLE),--sample $(SAMPLE)) $(if $(MODEL),--model $(MODEL))
```

- [x] **Step 4:** tests pass; `make check` passes.
- [x] **Step 5:** commit.

### Task 6: The `embed-lookup` condition in the coding test

**Files:**
- Modify: `scripts/memory_coding_test.py` (`tools --choices RUN_ID`; `read_choices`;
  `_tools_run_id`; `_condition`; `_picked`; docstring)
- Modify: `Makefile` (`mem-coding-embed-lookup`)
- Test: `tests/test_memory_coding_test.py`

**Interfaces:**
- Consumes: Task 5's choices folder.
- Produces: `read_choices(folder: Path, snapshot: str, sha: str, sample: str) -> tuple[dict[str,
  tuple[str, ...]], dict[str, object]]` (ids in order per case, and the summary); run id
  `{source}-embedlookup5-{snapshot}`; spec keys `lookup_k`, `lookup_min_applies`,
  `lookup_lessons`, `lookup_by: "embedding"` (or `"pick"`), `choices_run`, `embedding_model`.

- [x] **Step 1: Failing tests.**

```python
def test_embed_lookup_gives_each_case_exactly_its_choices(tmp_path, ...) -> None:
    # choices {"A": ["L3", "L1"]}: case A's system text holds L3 then L1 and no other lesson
def test_embed_lookup_refuses_a_choices_file_for_another_sample(...) -> None: ...
def test_embed_lookup_refuses_another_snapshot_hash_k_or_floor(...) -> None: ...
def test_embed_lookup_refuses_an_unknown_lesson_id(...) -> None: ...
def test_embed_lookup_needs_the_registration(...) -> None: ...
def test_choices_and_applies_together_are_refused(...) -> None: ...
def test_embed_lookup_run_id_and_spec(...) -> None: ...
```

- [x] **Step 2:** the tests fail.
- [x] **Step 3: Implement.** `--choices` needs `--snapshot` and `--lookup 5`, and refuses
  `--applies`; it is refused until `EMBED_REGISTRATION` is committed. `read_choices` refuses a
  missing or unreadable folder, a summary whose sample, snapshot, hash, `k` or `min_applies`
  differ, an id not in the snapshot, or more than `k` ids for a case. The case's lessons are the
  snapshot's lessons with those ids, in the file's order. A case missing from the file gets no
  lesson (the counts text), as the cause lookup's empty cases do. Makefile:

```make
mem-coding-embed-lookup: ## The embed-lookup condition: 5 lessons per case from CHOICES (0213; paid, OpenRouter)
	uv run python -m scripts.stage_spend --stage mem --estimate 4.01 && scripts/with_pass_keys.sh uv run python -m scripts.memory_coding_test tools --source $(SOURCE) --snapshot pilot-2010-recount --lookup 5 --choices $(CHOICES) $(if $(RESUME),--resume $(RESUME))
```

- [x] **Step 4:** tests pass; `make check` passes.
- [x] **Step 5:** commit.

### Task 7: The reading and its rule

**Files:**
- Create: `scripts/memory_embed_result.py`
- Modify: `Makefile` (`mem-embed-result`)
- Test: `tests/test_memory_embed_result.py`

**Interfaces:**
- Consumes: `memory_pilot_result.load_run`, `measures`, `paired`, `stop_rule`, `summary_lines`,
  `refuse_unequal_cases`; `memory_cause_lookup_result.refuse_unrelated` (called on the four runs
  without embed-lookup, whose labels it knows), `folder`; `memory_lookup_result.lookup_counts`.
- Produces: `embed_rule(looked: Diff3, noise: Diff3) -> tuple[bool, list[str]]`, returning
  `stop_rule(looked, noise)`, its docstring the registration's §6 text word for word:

```python
def embed_rule(looked: Diff3, noise: Diff3) -> tuple[bool, list[str]]:
    """Decision 0213, as registered in docs/rounds/memory-embed-lookup.md.

    ``looked`` is embed lookup minus today's cause lookup; ``noise`` is counts(b) minus counts(a);
    all on one sample. Pass only if the finding gain exceeds the noise on findings, and neither
    occurrence measure falls by more than its own noise: the rule of decisions 0204 and 0210 to
    0212, with today's cause lookup in place of counts(a).
    """
    return stop_rule(looked, noise)
```

- [x] **Step 1: Failing tests.**

```python
def test_rule_reads_embed_minus_cause_lookup(tmp_path) -> None: ...   # a pass and a fail
def test_embed_lookup_must_come_from_tables_a_with_k5_floor10_and_a_choices_run(tmp_path) -> None: ...
def test_runs_on_another_sample_are_refused(tmp_path) -> None: ...
def test_output_path_by_sample() -> None:
    # dev-steer-400 -> docs/results/memory-embed-lookup-dev.txt;
    # dev-seal-400 -> docs/results/memory-embed-confirm-devseal.txt
def test_rule_docstring_matches_the_registration() -> None: ...
def test_report_last_line() -> None:   # "rule on dev-steer-400: PASS" / "FAIL"
```

- [x] **Step 2:** the tests fail.
- [x] **Step 3: Implement.** Arguments `--tables-a --counts-a --counts-b --cause-lookup
  --embed-lookup [--sample S] [--out PATH]`. Per run: the three measures with intervals and failed
  cases. Paired: `counts(b) - counts(a), the noise`; `embed lookup - cause lookup, read by the rule`;
  and, for description, `embed lookup - counts(a)` and `cause lookup - counts(a)`. Lessons per case
  for both lookups (`lookup_counts`), the embed lookup's model and choices run. Then every
  `not passed:` reason and the last line `rule on <sample>: PASS|FAIL`. Makefile:

```make
mem-embed-result: ## The embed lookup's reading and rule, steering or SAMPLE=dev-seal-400 (0213); free
	uv run python -m scripts.memory_embed_result --tables-a $(TA) --counts-a $(CA) --counts-b $(CB) --cause-lookup $(CAUSE) --embed-lookup $(EMBED) $(if $(SAMPLE),--sample $(SAMPLE))
```

- [x] **Step 4:** tests pass; `make check` passes.
- [x] **Step 5:** commit.

### Task 8: The picking call (only if Task 9's gate prints `winner: none`)

Skip this task, and tick it with "not needed" in Deviations, if the gate names a model.

**Files:**
- Modify: `src/ntsb_probable_cause/memory/prompts.py` (`SYSTEM_PICK`, `pick_user`)
- Modify: `scripts/memory_learn.py` (`pick_call`)
- Create: `scripts/memory_cause_pick.py`
- Modify: `scripts/memory_coverage.py` (read a pick run), `Makefile` (`mem-cause-pick`)
- Test: `tests/test_memory_cause_pick.py`, `tests/test_memory_prompts.py`

**Interfaces:**
- Consumes: Task 4's `vectors.json`; `lookup.by_similarity(..., k=20)`; the apply step's machinery
  (`LearningClient`, `allow_for_test_apply`, `check_budget`, batch send, resume, `refuse_finished`).
- Produces: `<runs>/<run id>/picks.json` (`{case_id: [up to 5 ids, best first]}`) and `pick.json`
  (`sample`, `snapshot`, `snapshot_sha256`, `embed_run`, `model`, `effort`, `cases_sent`, `failed`,
  `commit`); run id `{stamp}-{commit}-memory-cause-pick-{sample}-{slug(model)}`.

```python
SYSTEM_PICK: Final = """You decide which coding lessons best cover an accident, from the NTSB's \
probable-cause sentence alone. A lesson covers the accident when its situation and scope describe \
what the sentence says happened. Judge by the situation only; do not guess how the accident was \
coded. Answer with the ids of at most five lessons that cover it, the best first, or an empty list \
if none does.

The lessons:
"""
```

  The reply schema is `prompts.ApplyReply`; ids not in the shortlist are dropped, and the rest are
  cut to five in the reply's order.

- [ ] **Step 1: Failing tests:** the request shows the 20 shortlisted lessons by
  `render_for_apply` (no codes) and the cause sentence alone; unknown ids dropped and order kept; a
  sixth id cut; more than 2% failed replies refused at the coverage reading; resume of a finished
  run refused; `dev-seal-400` refused before registration; the budget checked before sending.
- [ ] **Step 2:** the tests fail.
- [ ] **Step 3: Implement**, following `scripts/memory_cause_apply.py` throughout (Sonnet 5.5 at
  high, role `test-apply`, kind `learning`). Makefile:

```make
mem-cause-pick: ## The picking call over MODEL's 20 closest lessons (0213; paid, plan credit)
	scripts/with_pass_keys.sh uv run python -m scripts.memory_cause_pick --embeds $(EMBEDS) $(if $(SAMPLE),--sample $(SAMPLE)) $(if $(RESUME),--resume $(RESUME))
```

- [ ] **Step 4:** tests pass; `make check` passes.
- [ ] **Step 5:** commit.

### Task 9: The steering runs (paid: cents, then about $0.18)

- [ ] `make mem-embed MODEL=<each candidate>`, three times; note each run id.
- [ ] `make mem-coverage EMBEDS="<three runs>"`; commit `docs/results/memory-coverage-dev.txt`.
- [ ] If `winner: none`: Task 8, then `make mem-cause-pick EMBEDS=<highest hit rate's run>` and
  `make mem-coverage EMBEDS="<three runs>" PICKS=<pick run>`; commit. If `winner: none` again,
  stop: Task 11 records it.
- [ ] `make mem-coding-embed-lookup SOURCE=20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a CHOICES=<choices run>`.
- [ ] `make mem-embed-result TA=20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a CA=<...-counts-a> CB=<...-counts-b> CAUSE=<...-causelookup5-pilot-2010-recount> EMBED=<embed lookup run>`;
  commit `docs/results/memory-embed-lookup-dev.txt`. If it fails, stop: Task 11 records it.

### Task 10: The `dev-seal-400` runs (paid: about $0.75 and $1.50 of credit), only if Task 9 passed

- [ ] `make mem-coding-answer REPEAT=a SAMPLE=dev-seal-400`.
- [ ] `make mem-coding-tools SOURCE=<tables-a> REPEAT=a`, then `REPEAT=b`.
- [ ] `make mem-cause-apply SNAPSHOT=pilot-2010-recount SAMPLE=dev-seal-400`; commit its counts file.
- [ ] `make mem-coding-cause-lookup SOURCE=<tables-a> SNAPSHOT=pilot-2010-recount K=5 APPLIES=<apply run>`.
- [ ] `make mem-embed MODEL=<winner's model> SAMPLE=dev-seal-400` (and, if the winner is the
  picking call, `make mem-cause-pick EMBEDS=<that run> SAMPLE=dev-seal-400`).
- [ ] `make mem-coverage SAMPLE=dev-seal-400 APPLIES=<apply run> EMBEDS=<embed run> MODEL=<model> [PICKS=<pick run>]`;
  commit `docs/results/memory-coverage-devseal.txt`.
- [ ] `make mem-coding-embed-lookup SOURCE=<tables-a> CHOICES=<choices run>`.
- [ ] `make mem-embed-result SAMPLE=dev-seal-400 TA=... CA=... CB=... CAUSE=... EMBED=...`; commit
  `docs/results/memory-embed-confirm-devseal.txt`.

### Task 11: Close the records

- [ ] Spec §13: an "Added" note with the result, every figure from the committed results files;
  its Status line updated.
- [ ] CLAUDE.md's coding-memory paragraph: one sentence on 0213's result and the new targets.
- [ ] `make s33-continuity` reports `+t` e7811b387b31; then
  `git checkout -- docs/results/s33-fingerprint-continuity.txt`.
- [ ] `make check` passes; commit.

## Deviations

- 2026-10-17, Task 2 step 6: the first probe run (commit 7be1885) succeeded on all three models,
  but its result file was refused: the probe saved its fixtures in the repo before writing
  `docs/results/memory-embed-probe.txt`, so the tree was dirty. The probe now writes the result
  first and the fixtures after, and saves them even when a request or that write fails
  (`test_probe_writes_the_result_before_the_fixtures`). The probe is run once more; both runs'
  spend rows stand (under a thousandth of a cent each). The first run's replies are not committed.
- 2026-10-17, Task 5: `--picks` and its test move to Task 8, where the pick run's format is made;
  the gate and the choices writer are shared, so Task 8 adds only the reader. Until then
  `make mem-coverage ... PICKS=` (registration §4 step 5) is not wired: step 5 runs only after
  `winner: none`, which needs Task 8 first.
- 2026-10-17, Task 5: `read_vectors` was written in `scripts/memory_embed.py` ahead of Task 4's
  `embed` command, because the coverage reading reads it.
- 2026-10-17, Task 4: `embed` refuses `dev-400` although `refuse_sample` allows it: the
  registration embeds only `dev-steer-400` and `dev-seal-400`, and `dev-400` is not read again.
- 2026-10-17, Task 4: a case with no cause sentence is listed in `vectors.json` as
  `no_cause_cases`, not as failed, and does not count toward the 2% rule: it was never sent, and
  it gets no lesson, as in today's cause lookup. Identical texts (a cause sentence shared by
  several cases) are sent once; the cache is keyed by the text.
- 2026-10-17, final review (three Important findings, fixed with tests): the steering gate now
  needs all three candidates' runs; `mem-coverage` refuses a dirty tree before writing a choices
  folder, `choice.json` records `dirty`, and the coding test refuses choices not made from a clean
  tree; on `dev-seal-400`, `mem-embed`, `mem-coverage` and `mem-embed-result` accept only the
  steering winner, read from the last line of the committed
  `docs/results/memory-coverage-dev.txt`, and `mem-coverage` takes one embedding run there.
