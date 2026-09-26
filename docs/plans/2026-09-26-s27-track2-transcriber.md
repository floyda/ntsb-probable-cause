# S2.7 track 2 — the transcriber re-test and the page rule: implementation plan

**Spec:** docs/specs/2026-09-26-s27-coding-guidance-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from the specification in the **Deviations** section at the end. A step marked **STOP** is Andy's: stop the track there, report, and wait.

**Goal:** Find out, by rules fixed in advance (spec §7, decision 0100), whether a newer and cheaper vision model can replace Qwen3.5 122B as the transcriber, and which docket pages are worth sending to the transcriber at all; record the outcome in one decision record (number 120) and merge the track back into the stage branch before the meeting point (spec §8).

**Architecture:** The page rule becomes a named, recorded choice in `docket/transcribe.py` (`PageRule`, `PAGE_RULE`), used by `pages_to_read`, `ReadingLookup` and `ntsb-eval transcribe`, with S2.6's rule (`"all"`) unchanged as the default so the existing `dev-400` readings and marker stay valid. Three new scripts do the measuring: `scripts/page_value.py` (T3, free, reads the `dev-400` transcription cache), `scripts/transcriber_shortlist.py` (T1: fetch and filter OpenRouter's model list, probe the shortlist) and `scripts/transcriber_retest.py` (T2: the candidates on S2.6's four answer keys, Andy's marking pages, the choice rule against Qwen). The re-test reuses S2.6's keys and scoring helpers from `scripts/transcriber_test.py` by import and never rewrites S2.6's files. Every paid step is a `make` target Andy runs.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, pypdf, pypdfium2, Pillow, httpx + respx, pytest + pytest-socket, ruff, mypy --strict, import-linter. No new dependency.

## Global Constraints

- **Branch and base.** Track 2 works on `s27-transcriber` in `.claude/worktrees/s27-transcriber`, cut from `s27-coding-guidance` **after track 1's Task 1 has landed there** (it builds `scripts/stage_spend.py`). It merges back into `s27-coding-guidance` with a merge commit (never squashed, never rebased; decision 0033) in Task 12, before the meeting point. Never commit to `main`.
- **What track 2 does not touch.** `scoring/runner.py`, `scoring/records.py`, `scoring/report.py`, `RunSpec`, `RunRecord`, and `_cmd_run` in `apps/eval/__main__.py` belong to track 1. After the merge back, track 1 adds `RunSpec.transcriber` and `RunSpec.page_rule`, the run flags `--transcriber` and `--page-rule`, and the report's refusal to compare two v2 runs that differ in either (spec §7.5). Track 2 provides the names they read, exactly as below, and nothing else in those files.
- **The interface track 1 relies on** (fixed; do not rename): in `src/ntsb_probable_cause/docket/transcribe.py` — `PageRule = Literal["all", "image-only", "image-only+thin-layer"]`; `PAGE_RULES: tuple[PageRule, ...] = ("all", "image-only", "image-only+thin-layer")`; `THIN_LAYER_MAX_CHARS = 200`; `PAGE_RULE: PageRule` (the rule in force, `"all"` until the track-2 decision record changes it); `TRANSCRIBER: str` (unchanged name; changed only by that record); `pages_to_read(data: bytes, *, page_rule: PageRule = PAGE_RULE) -> list[tuple[int, bool]]`; `ReadingLookup(cache, *, model: str = TRANSCRIBER, instruction: Instruction = TRANSCRIBE, dpi: Resolution = RESOLUTION, page_rule: PageRule = PAGE_RULE)` with read-only properties `.model` and `.page_rule`; `ntsb-eval transcribe --model` (default `TRANSCRIBER`) and `--page-rule` (choices `PAGE_RULES`, default `PAGE_RULE`).
- **The done marker stays valid.** `ReadingLookup.done_file` keeps S2.6's stamp, `sha256(f"{model}|{version}|{dpi}")[:12]`, when `page_rule == "all"`, so `data/transcriptions/done/dev-400-940436639bbd.json` still says `dev-400` is transcribed. Any other rule adds `f"|{page_rule}"` to the stamped string.
- **The $25 stage line** (decision 0098 item 6). Every paid `make` target first runs `uv run python -m scripts.stage_spend --estimate <USD>` (track 1, Task 1; the Makefile's `stage-spend EST=<USD>` does the same), which exits 1 if S2.7's spend plus the estimate would pass $25. The $40 monthly guard (0083) applies separately, inside every paid job, as in S2.6.
- **Development cases only.** `page_value.py` refuses any sample but `dev-400`; the re-test reads only S2.6's answer keys, which came from `dev-400` (S2.6 plan, Task 13). No held-out or open-split page is rendered, read or sent anywhere (rule 5, 0024). `ntsb-eval transcribe` keeps refusing held-out samples (0090).
- **Private material lives under `data/`** (git-ignored) and is never committed: the saved model list, answer keys, page images, marking pages and CSVs, transcriptions. Only counts and model ids go to `docs/results/`. Recorded probe replies are of the invented probe page (`scripts/transcriber_test.py:probe_page`) and hold no docket text.
- **S2.6's files are read, never rewritten.** The re-test writes under `data/s27/transcriber-retest/`; it reads `data/s26/transcriber-test/` (keys, sheets, CSVs) and never writes there. `docs/results/s26-transcriber-test*.txt` are not regenerated.
- **Never guess API details** (rule 2). Model ids, prices, modalities, creation dates and reasoning parameters come from the saved model list (`https://openrouter.ai/api/v1/models`, fetched by Task 5 and kept under `data/s27/`); request shapes come from the saved probe replies.
- **Images never go through the batch service by default** (S2.6 decision W1; `model/batch.py:BatchClient.submit` refuses them). Every re-test call is synchronous at the standard price. Task 7's one batch test is the only exception, and it is Andy's to keep or drop (walkthrough W2).
- **Paid commands handed to Andy** always state `export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data`, the expected cost and duration, and are run from a shell that exports `OPENROUTER_API_KEY="$(pass show api/openrouter)"` without printing it.
- **Numbers reported anywhere come from a script.** Qwen's figures are cited from `docs/results/s26-transcriber-test-pass2.txt` and reproduced from the cache by Task 8 before any candidate is scored against them.
- `make check` = ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest (`--cov-fail-under=90`, branch coverage). Google-style docstrings on every public symbol; line length 100. Every module in `scripts/` carries a `Status` paragraph beneath its summary line (decision 0059).
- Commit messages end with the attribution lines the session gives.

---

## Decisions for Andy before any code (the walkthrough)

The spec is approved; these are the places where writing this plan found something the spec did not settle. Each is marked in the task that depends on it. Take them one per message; record each outcome here and in the Deviations section.

- **W1. The reasoning level of each new candidate.** `transcribe.settings_for` sends `sources.LOWEST_REASONING[model]` on every call, and a model missing from that table raises `KeyError`. Spec §7.2 and rule 2 forbid guessing it. The saved model list gives, per model, `supported_parameters` (whether `reasoning` is accepted) and a `reasoning` object (`mandatory`, `default_enabled`, sometimes `supported_efforts`). *Planned as:* a fixed rule applied by `transcriber_shortlist.lowest_reasoning` — the lowest of `supported_efforts` in the ladder `none < minimal < low < medium < high < xhigh < max` when the list gives any; else `"minimal"` if reasoning is `mandatory`; else `"none"`. This reproduces S2.6's choices (Gemini 3.6 Flash, mandatory: `minimal`; Qwen, no levels listed: `none`). The probe (Task 7) is the check: a candidate that refuses its level fails the probe and is replaced. *Undecided.*
- **W2. The one batch-with-image call.** Spec §7.2 asks for one call testing whether a batch variant now accepts an image part. OpenRouter's batch documentation (read 2026-09-24, quoted in `model/batch.py:136`) already says base64 and `data:` images are rejected on every provider, and public image links were rejected in S2.6 (W1: fatal-accident pages at web addresses). *Planned as:* kept, as one call with the invented probe page, and only for a shortlisted candidate the saved list offers a `:batch` variant for (Task 7). If none does, the test is recorded as "not possible". *Alternative:* drop it and cite the documentation. *Undecided.*
- **W3. Andy's marking load.** Photograph and full-page-scan cards are needed for every new candidate reading that holds words (as in S2.6; `transcriber_test._photo_cards`, `cmd_mixed`); Qwen's pass-2 marks are reused, not repeated. With eight candidates that is at most 8 × 50 photograph cards and 8 × 25 scan cards; S2.6's four candidates produced far fewer, because most readings of a no-word photograph are empty or `[illegible]`. The 0086 rule is printed on the page: a word of the docket's stamped "Photo" label counts as on the page. *Planned as:* all eight candidates marked, in one page per set, each page resumable. *Alternative:* mark only candidates that already pass the four automatic measures (handwriting invention, format, handwriting accuracy, typed errors) and cost, since a candidate that fails any of those cannot be chosen whatever its marks (decision 0100 item 3). That cuts the marking to the candidates that can still win. *Undecided; the alternative is recommended.*
- **W4. The done-marker stamp.** Interface above: S2.6's stamp is kept for `"all"`. *Planned as* stated, so `dev-400`'s S2.6 marker stays valid and a new rule gets its own marker. Nothing for Andy unless he prefers every marker to name its rule (which would invalidate the existing marker and force a free but slow re-check of every `dev-400` page before any v2 run). *Undecided, recommended as planned.*
- **W5. Fewer than eight candidates.** The filter may leave fewer than eight models, or fewer than eight may pass the probe. *Planned as:* the re-test runs whatever passes, with no top-up from outside the filter; if none passes, the track records "Qwen stays" without a re-test. *Undecided.*
- **W6. Structured output.** Every transcription call uses a strict JSON schema (`transcribe.settings_for`, `json_schema=instruction.schema()`). A model whose listing lacks `response_format` in `supported_parameters` will fail the probe. *Planned as:* one more filter condition — `response_format` listed — so such a model does not take a shortlist place only to be replaced. It is a departure from spec §7.2's filter, logged if accepted. *Undecided.*
- **W7. Which second-pass CSVs are S2.6's final ones.** `data/s26/transcriber-test/` holds `handwriting-key-pass2.csv` and `photo-words-pass2.csv`, and `pass2/` holds `handwriting-key-pass2-2.csv` and a second `photo-words-pass2.csv`. S2.6's published second pass was scored from one pair. *Planned as:* Task 8's `verify` takes the pair as arguments and must reproduce Qwen's published second-pass figures exactly from the cache (1036 of 1548 handwriting lines right, 54 inventing lines, 2 of 50 photographs, 0 of 25 scans, 2 of 25 format-failed pages, 20219 typed errors in 164464 characters); the pair that reproduces them is the one the re-test uses, and it is named in the results file. If neither does, the track stops (**STOP**). Nothing for Andy unless neither pair reproduces.

---

## File structure

| path | task | responsibility |
|---|---|---|
| `src/ntsb_probable_cause/docket/transcribe.py` | 2 | `PageRule`, `PAGE_RULES`, `PAGE_RULE`, `THIN_LAYER_MAX_CHARS`, `page_choice`; `pages_to_read(..., page_rule=)`; `ReadingLookup(..., page_rule=)`, `.model`, `.page_rule`, the done stamp |
| `apps/eval/__main__.py` (`_page_jobs`, `_maybe_mark_done`, `_cmd_transcribe`, the `transcribe` parser only) | 3 | `ntsb-eval transcribe --model --page-rule` |
| `scripts/page_value.py` | 4 | T3: per-page value of transcription on `dev-400`, three rules, the choice; `docs/results/s27-page-value.txt` |
| `scripts/transcriber_shortlist.py` | 5, 6, 7 | T1: fetch and save the model list; the filter; the shortlist; the reasoning rule; the probe; the batch test; `docs/results/s27-transcriber-shortlist.txt` |
| `src/ntsb_probable_cause/sources.py` | 6 | prices and lowest reasoning levels of the shortlisted models, dated from the saved list |
| `scripts/transcriber_retest.py` | 8, 9, 10 | T2: reproduce Qwen's second pass; run the candidates on the four keys; Andy's pages; the choice rule against Qwen; `docs/results/s27-transcriber-retest.txt` |
| `tests/fixtures/openrouter/transcription/*.json` | 7 | the new candidates' recorded probe replies (the invented page) |
| `tests/test_docket_transcribe.py`, `tests/test_eval_app.py`, `tests/test_page_value.py`, `tests/test_transcriber_shortlist.py`, `tests/test_transcriber_retest.py`, `tests/test_sources_settings.py` | 2–10 | tests |
| `Makefile` | 4–10 | `s27-page-value`, `s27-models-fetch`, `s27-shortlist`, `s27-transcriber-probe`, `s27-batch-image`, `s27-retest-verify`, `s27-retest-run`, `s27-retest-pages`, `s27-retest-score` |
| `docs/decisions/` (number 120) and its index row | 11 | the transcriber and page rule, or "Qwen stays" |

Task numbers in this table are final.

---

### Task 1: The branch and worktree

**Starts when** track 1's Task 1 (`scripts/stage_spend.py`, the `stage-spend` target) is committed on `s27-coding-guidance`.

**Files:** none changed.

- [ ] **Step 1: Cut the branch and the worktree**

```bash
cd /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause
git fetch origin
git worktree add .claude/worktrees/s27-transcriber -b s27-transcriber origin/s27-coding-guidance
cd .claude/worktrees/s27-transcriber
uv sync
```

- [ ] **Step 2: Confirm the base is green and the spend check exists**

Run: `make check && uv run python -m scripts.stage_spend --estimate 0`
Expected: `make check` passes; `stage_spend` prints S2.7's spend so far and exits 0.

- [ ] **Step 3: Push the branch**

```bash
git push -u origin s27-transcriber
```

---

### Task 2: Named page rules in the transcription module (spec §7.3, §7.5; decision 0100 items 4–5; walkthrough W4)

**Files:**
- Modify: `src/ntsb_probable_cause/docket/transcribe.py` (constants near `MIXED_PAGE_MIN_IMAGE_SHARE` at :73; `pages_to_read` at :553; `ReadingLookup` at :571)
- Test: `tests/test_docket_transcribe.py`

**Interfaces:**
- Consumes: `docket.pages.document_facts(data) -> tuple[PageFacts, ...]` (`PageFacts.kind`, `PageFacts.chars`), `docket.render.image_area_shares(data) -> tuple[float, ...]`, `docket.pages.PageKind`.
- Produces (fixed, Global Constraints): `PageRule`, `PAGE_RULES`, `PAGE_RULE`, `THIN_LAYER_MAX_CHARS`; `page_choice(kind: PageKind, chars: int, share: float, *, page_rule: PageRule) -> bool | None` (`None` = not sent, `False` = sent as a full page, `True` = sent as a mixed page); `pages_to_read(data, *, page_rule=PAGE_RULE)`; `ReadingLookup(..., page_rule=PAGE_RULE)` with `.model`, `.page_rule`.

**Why a named rule.** S2.6's rule lived in `pages_to_read` and one constant, and nothing recorded it. A v2 docket read with another rule holds different evidence (spec §7.5), so the rule needs a name a run can record (track 1, after the merge) and a marker can carry. `page_choice` is the rule itself, one function, so `page_value.py` (Task 4) measures exactly what `pages_to_read` does.

**What each rule sends.** Example document: page 1 image-only; page 2 text-and-image with a 55-character text layer (a scanned form with a typed header); page 3 text-and-image with a 900-character text layer (a typed report with a logo); page 4 text only. `"all"` sends 1 (full), 2 and 3 (mixed). `"image-only"` sends 1. `"image-only+thin-layer"` sends 1 and 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_docket_transcribe.py` (it already imports `build_pdf`, `PageSpec`, `TYPED`, `TranscriptionCache`, `pages_to_read`, `transcribe_module`, `hashlib`; add the new names to its import from `ntsb_probable_cause.docket.transcribe`: `PAGE_RULE`, `PAGE_RULES`, `THIN_LAYER_MAX_CHARS`, `ReadingLookup`, `page_choice`, `Transcription`, `TranscriptionKey`, `TRANSCRIBER`, `TRANSCRIBE`, `key_instruction`):

```python
# --- S2.7 track 2, Task 2: named page rules ---

_LONG_LAYER = " ".join([TYPED] * 5)  # about 275 characters: over THIN_LAYER_MAX_CHARS


def _three_kinds() -> bytes:
    return build_pdf(
        [
            PageSpec(images=("/CCITTFaxDecode",)),
            PageSpec(text=TYPED, images=("/DCTDecode",)),
            PageSpec(text=_LONG_LAYER, images=("/DCTDecode",)),
            PageSpec(text=TYPED),
            PageSpec(),
        ]
    )


def test_the_rule_in_force_is_s26s_until_a_decision_changes_it() -> None:
    assert PAGE_RULE == "all"
    assert PAGE_RULES == ("all", "image-only", "image-only+thin-layer")
    assert THIN_LAYER_MAX_CHARS == 200


def test_each_rule_sends_its_own_pages() -> None:
    document = _three_kinds()
    assert pages_to_read(document, page_rule="all") == [(1, False), (2, True), (3, True)]
    assert pages_to_read(document, page_rule="image-only") == [(1, False)]
    assert pages_to_read(document, page_rule="image-only+thin-layer") == [(1, False), (2, True)]


def test_the_default_rule_is_the_rule_in_force() -> None:
    document = _three_kinds()
    assert pages_to_read(document) == pages_to_read(document, page_rule=PAGE_RULE)


def test_page_choice_never_sends_a_text_only_or_blank_page() -> None:
    for rule in PAGE_RULES:
        assert page_choice("text only", 900, 0.0, page_rule=rule) is None
        assert page_choice("blank", 0, 0.0, page_rule=rule) is None
        assert page_choice("image only", 0, 1.0, page_rule=rule) is False


def test_the_thin_layer_rule_cuts_at_the_limit() -> None:
    rule = "image-only+thin-layer"
    assert page_choice("text and image", THIN_LAYER_MAX_CHARS - 1, 0.5, page_rule=rule) is True
    assert page_choice("text and image", THIN_LAYER_MAX_CHARS, 0.5, page_rule=rule) is None


def test_the_done_file_for_s26s_rule_keeps_s26s_stamp(tmp_path: Path) -> None:
    lookup = ReadingLookup(TranscriptionCache(tmp_path))
    old = hashlib.sha256(f"{TRANSCRIBER}|{TRANSCRIBE.version}|150".encode()).hexdigest()[:12]
    assert lookup.done_file("dev-400") == tmp_path / "done" / f"dev-400-{old}.json"
    assert lookup.page_rule == "all"
    assert lookup.model == TRANSCRIBER


def test_another_rule_has_its_own_done_file(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    s26 = ReadingLookup(cache)
    other = ReadingLookup(cache, page_rule="image-only")
    assert other.done_file("dev-400") != s26.done_file("dev-400")
    other.mark_done("dev-400", {"pages": 1})
    assert other.is_done("dev-400")
    assert not s26.is_done("dev-400")


def test_a_lookup_under_a_rule_finds_only_that_rules_pages(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    document = _three_kinds()
    sha = hashlib.sha256(document).hexdigest()
    for page, mixed in pages_to_read(document, page_rule="all"):
        key = TranscriptionKey(
            document_sha256=sha,
            page=page,
            model=TRANSCRIBER,
            instruction=key_instruction(TRANSCRIBE, mixed=mixed),
            dpi=150,
        )
        cache.put(
            Transcription(
                key=key,
                status="transcribed",
                text=f"page {page}",
                mixed=mixed,
                created=datetime(2026, 9, 27, tzinfo=UTC),
            ),
            instruction=TRANSCRIBE,
        )
    assert sorted(ReadingLookup(cache).for_document(document)) == [1, 2, 3]
    assert sorted(ReadingLookup(cache, page_rule="image-only").for_document(document)) == [1]
    thin = ReadingLookup(cache, page_rule="image-only+thin-layer")
    assert sorted(thin.for_document(document)) == [1, 2]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_docket_transcribe.py -k "rule or done_file or page_choice" -v`
Expected: FAIL with `ImportError: cannot import name 'PAGE_RULE'`.

- [ ] **Step 3: Implement**

In `src/ntsb_probable_cause/docket/transcribe.py`, add `from ntsb_probable_cause.docket.pages import PageKind` to the existing `docket.pages` import, and add below `TRANSCRIBER` (:79):

```python
# S2.7 spec §7.3 and §7.5, decision 0100 items 4-5: which pages v2 sends to the transcriber,
# by name, so a run and a finished-transcription marker can say which rule built their
# evidence. "all" is S2.6's rule: every image-only page, and every text-and-image page whose
# images cover at least MIXED_PAGE_MIN_IMAGE_SHARE of it (0.0, so every one). The other two
# are the rules S2.7's T3 measures (scripts/page_value.py). PAGE_RULE is the rule in force; it
# changes only by the track-2 decision record of S2.7 (number 120), as TRANSCRIBER does.
type PageRule = Literal["all", "image-only", "image-only+thin-layer"]
PAGE_RULES: tuple[PageRule, ...] = ("all", "image-only", "image-only+thin-layer")
PAGE_RULE: PageRule = "all"
# Under "image-only+thin-layer", a text-and-image page is sent only when its text layer holds
# fewer characters than this (decision 0100 item 4): a scanned form with a typed header, not a
# typed report with a logo.
THIN_LAYER_MAX_CHARS = 200
```

(If mypy rejects a `type` alias in the `Literal` positions below, write `PageRule = Literal[...]` instead; the name and values are what matter.)

Replace `pages_to_read` (:553-568) with:

```python
def page_choice(kind: PageKind, chars: int, share: float, *, page_rule: PageRule) -> bool | None:
    """Whether a page is sent, and how: ``None`` not sent, ``False`` full, ``True`` mixed.

    ``chars`` is the page's text-layer length as ``docket.pages`` counts it; ``share`` is the
    part of the page its images cover (``render.image_area_shares``). A text-only or blank page
    is never sent; an image-only page always is, in full (0074).
    """
    if kind == "image only":
        return False
    if kind != "text and image" or share < MIXED_PAGE_MIN_IMAGE_SHARE:
        return None
    if page_rule == "all":
        return True
    if page_rule == "image-only":
        return None
    return True if chars < THIN_LAYER_MAX_CHARS else None


def pages_to_read(data: bytes, *, page_rule: PageRule = PAGE_RULE) -> list[tuple[int, bool]]:
    """``(page, mixed)`` for every page v2 transcribes under ``page_rule`` (0074, 0079, 0100).

    A file that is not a PDF raises ``DocketError``, as in ``extract.extract_pdf``.
    """
    chosen: list[tuple[int, bool]] = []
    shares = image_area_shares(data)
    for number, page in enumerate(document_facts(data), start=1):
        share = shares[number - 1] if number <= len(shares) else 0.0
        mixed = page_choice(page.kind, page.chars, share, page_rule=page_rule)
        if mixed is not None:
            chosen.append((number, mixed))
    return chosen
```

In `ReadingLookup`, add the parameter, the properties, the rule in the lookup, and the stamp:

```python
    def __init__(
        self,
        cache: TranscriptionCache,
        *,
        model: str = TRANSCRIBER,
        instruction: Instruction = TRANSCRIBE,
        dpi: Resolution = RESOLUTION,
        page_rule: PageRule = PAGE_RULE,
    ) -> None:
        self._cache = cache
        self._model = model
        self._instruction = instruction
        self._dpi: Resolution = dpi
        self._page_rule: PageRule = page_rule

    @property
    def model(self) -> str:
        """The transcriber whose readings this lookup finds."""
        return self._model

    @property
    def page_rule(self) -> PageRule:
        """The page rule that decides which pages are looked up (S2.7 spec §7.5)."""
        return self._page_rule
```

In `for_document`, change `chosen = pages_to_read(data)` to `chosen = pages_to_read(data, page_rule=self._page_rule)`. Replace `done_file`'s body with:

```python
        # S2.7 walkthrough W4: S2.6's rule keeps S2.6's stamp, so the dev-400 marker written
        # on 2026-09-26 stays valid; any other rule is part of the stamped string.
        stamped = f"{self._model}|{self._instruction.version}|{self._dpi}"
        if self._page_rule != "all":
            stamped += f"|{self._page_rule}"
        stamp = hashlib.sha256(stamped.encode()).hexdigest()[:12]
        return self._cache.root / "done" / f"{sample}-{stamp}.json"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_docket_transcribe.py -v`
Expected: PASS, including every S2.6 test of `pages_to_read` (the default rule is S2.6's).

- [ ] **Step 5: Check the real marker still matches** (read-only, no model call)

```bash
NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data uv run python -c "
from ntsb_probable_cause.docket.transcribe import ReadingLookup, TranscriptionCache
from ntsb_probable_cause.settings import Settings
print(ReadingLookup(TranscriptionCache(Settings().transcription_dir)).is_done('dev-400'))"
```
Expected: `True`.

- [ ] **Step 6: `make check`, then commit**

```bash
make check
git add src/ntsb_probable_cause/docket/transcribe.py tests/test_docket_transcribe.py docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: named page rules; the rule is part of a new marker's stamp"
```

---

### Task 3: `ntsb-eval transcribe --model --page-rule` (spec §8 step 1; decision 0100 item 5)

**Files:**
- Modify: `apps/eval/__main__.py` (`_page_jobs` :477, `_maybe_mark_done` :523, `_cmd_transcribe` :565, the `transcribe` sub-parser :223-235)
- Test: `tests/test_eval_app.py`

**Interfaces:**
- Consumes: Task 2's `PageRule`, `PAGE_RULES`, `PAGE_RULE`, `ReadingLookup(..., page_rule=)`; `sources.price_of`, `sources.LOWEST_REASONING`.
- Produces: `_page_jobs(raws, docs, *, model: str = TRANSCRIBER, page_rule: PageRule = PAGE_RULE)`; `_maybe_mark_done(cache, sample, jobs, skipped, *, model: str = TRANSCRIBER, page_rule: PageRule = PAGE_RULE) -> int`; the marker summary gains `"page_rule"`.

**Why here.** The meeting point (track 1) re-reads `dev-400` with track 2's winner and rule, and the sealed sample may need the same. Without these flags that means editing constants before a paid run. A model with no price or no reasoning level is refused before anything is fetched, because `transcribe.settings_for` would otherwise raise `KeyError` mid-job.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_eval_app.py` (it already has `_transcribe_env`, `main`, `ReadingLookup`, `TranscriptionCache`, `Transcription`, `TRANSCRIBE`, `PageJob`):

```python
def test_transcribe_reads_with_another_model_and_rule_and_marks_that_pair_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcriptions = _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])
    model = "google/gemini-3.1-flash-lite"  # priced, with a reasoning level (sources.py)
    calls: list[Sequence[PageJob]] = []

    def fake_preparation(*, jobs: Sequence[PageJob], **_kwargs: object) -> list[Transcription]:
        calls.append(jobs)
        cache = TranscriptionCache(transcriptions)
        for job in jobs:
            if cache.get(job.key) is None:
                cache.put(
                    Transcription(
                        key=job.key,
                        status="transcribed",
                        text="words",
                        mixed=job.mixed,
                        cost_usd=0.001,
                        created=datetime(2026, 10, 1, tzinfo=UTC),
                    ),
                    instruction=TRANSCRIBE,
                )
        return []

    monkeypatch.setattr("apps.eval.__main__.run_preparation", fake_preparation)
    argv = [
        "transcribe", "--sample", "dev-400", "--expected-cost-per-page-usd", "0.001",
        "--model", model, "--page-rule", "image-only",
    ]
    assert main(argv) == 0
    assert {j.key.model for j in calls[0]} == {model}
    assert {j.mixed for j in calls[0]} == {False}  # image-only sends no mixed page
    cache = TranscriptionCache(transcriptions)
    done = ReadingLookup(cache, model=model, page_rule="image-only")
    assert done.is_done("dev-400")
    assert json.loads(done.done_file("dev-400").read_text())["page_rule"] == "image-only"
    assert not ReadingLookup(cache).is_done("dev-400")  # S2.6's pair is not claimed
    assert f"with {model}" in capsys.readouterr().out


def test_transcribe_refuses_a_model_with_no_price_before_fetching_anything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])

    def no_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("nothing is fetched for a refused model")

    monkeypatch.setattr("apps.eval.__main__._page_jobs", no_fetch)
    argv = [
        "transcribe", "--sample", "dev-400", "--expected-cost-per-page-usd", "0.001",
        "--model", "vendor/unpriced-model",
    ]
    assert main(argv) == 1
    assert "no price on file for vendor/unpriced-model" in capsys.readouterr().err


def test_transcribe_refuses_a_page_rule_it_does_not_know(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])
    argv = ["transcribe", "--sample", "dev-400", "--expected-cost-per-page-usd", "0.001",
            "--page-rule", "every-page"]
    with pytest.raises(SystemExit):
        main(argv)
```

(`ruff format` will re-wrap the `argv` lists; keep the values.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_eval_app.py -k "another_model or no_price or page_rule_it" -v`
Expected: FAIL (`unrecognized arguments: --model`).

- [ ] **Step 3: Implement**

In the `transcribe` sub-parser, add:

```python
    transcribe_p.add_argument(
        "--model",
        default=TRANSCRIBER,
        help="the transcriber (S2.7 spec §8 step 1); needs a price and a reasoning level in "
        "sources.py",
    )
    transcribe_p.add_argument(
        "--page-rule",
        choices=PAGE_RULES,
        default=PAGE_RULE,
        help="which pages are sent (decision 0100 item 4); the rule in force by default",
    )
```

Import `PAGE_RULE`, `PAGE_RULES`, `PageRule` from `ntsb_probable_cause.docket.transcribe`, and `sources` from `ntsb_probable_cause` if not already imported.

Give `_page_jobs` the two keyword parameters and use them:

```python
def _page_jobs(
    raws: Sequence[Mapping[str, object]],
    docs: CachedDocuments,
    *,
    model: str = TRANSCRIBER,
    page_rule: PageRule = PAGE_RULE,
) -> tuple[list[PageJob], int]:
```

with `chosen = pages_to_read(data, page_rule=page_rule)` and `model=model` in the `TranscriptionKey`.

Give `_maybe_mark_done` the same two keyword parameters; build the lookup as `ReadingLookup(cache, model=model, page_rule=page_rule)` and write `"model": model, "page_rule": page_rule` in the summary (keeping `"dpi": RESOLUTION`).

In `_cmd_transcribe`, after the held-out refusal and before loading any case:

```python
    # S2.7 track 2, Task 3: a model the price table or the reasoning table does not know would
    # fail inside the job (transcribe.settings_for); refuse it before anything is fetched.
    try:
        sources.price_of(args.model)
    except KeyError:
        raise ConfigurationError(
            f"no price on file for {args.model}; add it to sources.py"
        ) from None
    if args.model not in sources.LOWEST_REASONING:
        raise ConfigurationError(
            f"no reasoning level on file for {args.model}; add it to sources.LOWEST_REASONING"
        )
```

Pass `model=args.model, page_rule=args.page_rule` to `_page_jobs` and `_maybe_mark_done`, and print `{args.model}` and `rule {args.page_rule}` in the projection line in place of `{TRANSCRIBER}`:

```python
        print(
            f"{args.sample}: {len(jobs)} pages to read with {args.model} at {RESOLUTION} dpi, "
            f"rule {args.page_rule}, {len(pending)} not yet read; projected ${projected:.2f}; "
            f"{skipped} document(s) could not be listed, fetched or parsed"
        )
```

- [ ] **Step 4: Run the transcribe tests**

Run: `uv run pytest tests/test_eval_app.py -k transcribe -v`
Expected: PASS, including the S2.6 tests (the defaults are S2.6's model and rule).

- [ ] **Step 5: `make check`, then commit**

```bash
make check
git add apps/eval/__main__.py tests/test_eval_app.py docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: ntsb-eval transcribe takes a model and a page rule"
```

---

### Task 4: T3 — what each page rule keeps, on `dev-400` (spec §7.3; decision 0100 item 4; free)

**Files:**
- Create: `scripts/page_value.py`
- Create: `tests/test_page_value.py`
- Modify: `Makefile` (target `s27-page-value`; add to `.PHONY`)
- Create (by running): `docs/results/s27-page-value.txt`

**Interfaces:**
- Consumes: `page_choice`, `PAGE_RULES`, `PageRule`, `ReadingLookup`, `TranscriptionCache` (Task 2); `docket.pages.document_facts`; `docket.render.image_area_shares`; `scoring.samples.sample_ids`, `load_cases`; `docket.documents.CachedDocuments`; `docket.client.DocketClient`; `scripts.transcriber_test._offline`.
- Produces: `PageRow` (frozen dataclass: `fatal: bool`, `kind: PageKind`, `layer_chars: int`, `image_share: float`, `status: str | None`, `chars: int`, `cost_usd: float`); `rows_for_document(data: bytes, readings: Mapping[int, Transcription], *, fatal: bool) -> list[PageRow]`; `RuleTally` (`pages`, `chars`, `cost_usd`, `failed`); `tally(rows, page_rule) -> RuleTally`; `choose_rule(rows) -> tuple[PageRule, list[str]]`; `report(rows, *, sample, cases, pdfs) -> str`; `main(argv) -> int`.

**What it measures.** Every image-bearing page of every `dev-400` PDF (S2.6's photo-only entries included, decision W2), with its text-layer size and image cover from the PDF itself, and its S2.6 reading (Qwen, t1, 150 dots per inch) from the cache. S2.6's rule read every such page, so each rule's pages, characters and cost are counted from readings that already exist. No model is called.

**The choice, fixed now** (decision 0100 item 4): of the three rules, the one with the fewest pages whose transcribed characters are at least 90% of the characters `"all"` transcribed; ties go to the earlier rule in `PAGE_RULES`. Its effect on answers is measured at the meeting point, not here.

- [ ] **Step 1: Write the failing tests**

```python
"""S2.7 track 2, Task 4: the page-value counts and the page-rule choice."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.transcribe import (
    TRANSCRIBE,
    TRANSCRIBER,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
    key_instruction,
    pages_to_read,
)
from scripts import page_value
from scripts.page_value import PageRow, choose_rule, rows_for_document, tally
from tests.pdf_builder import PageSpec, build_pdf

TYPED = "Engine sputtered at 800 ft. Switched tanks, no change."


def _row(kind: str, layer: int, chars: int, *, cost: float = 0.001) -> PageRow:
    return PageRow(
        fatal=True,
        kind=kind,  # type: ignore[arg-type]
        layer_chars=layer,
        image_share=0.9,
        status="transcribed",
        chars=chars,
        cost_usd=cost,
    )


def test_tally_counts_only_the_pages_a_rule_sends() -> None:
    rows = [
        _row("image only", 0, 1000),
        _row("text and image", 60, 300),
        _row("text and image", 900, 5),
    ]
    assert tally(rows, "all").pages == 3
    assert tally(rows, "all").chars == 1305
    assert tally(rows, "image-only").pages == 1
    assert tally(rows, "image-only+thin-layer").chars == 1300


def test_choose_rule_takes_image_only_when_it_keeps_nine_tenths() -> None:
    rows = [_row("image only", 0, 950), _row("text and image", 900, 50)]
    rule, _notes = choose_rule(rows)
    assert rule == "image-only"


def test_choose_rule_takes_the_thin_layer_rule_when_image_only_falls_short() -> None:
    rows = [
        _row("image only", 0, 800),
        _row("text and image", 60, 150),
        _row("text and image", 900, 50),
    ]
    rule, _notes = choose_rule(rows)
    assert rule == "image-only+thin-layer"


def test_choose_rule_keeps_all_when_no_narrower_rule_keeps_enough() -> None:
    rows = [_row("image only", 0, 500), _row("text and image", 900, 500)]
    rule, _notes = choose_rule(rows)
    assert rule == "all"


def test_rows_for_document_joins_facts_and_readings(tmp_path: Path) -> None:
    document = build_pdf(
        [
            PageSpec(images=("/CCITTFaxDecode",)),
            PageSpec(text=TYPED, images=("/DCTDecode",)),
            PageSpec(text=TYPED),
        ]
    )
    cache = TranscriptionCache(tmp_path)
    sha = hashlib.sha256(document).hexdigest()
    for page, mixed in pages_to_read(document, page_rule="all"):
        cache.put(
            Transcription(
                key=TranscriptionKey(
                    document_sha256=sha,
                    page=page,
                    model=TRANSCRIBER,
                    instruction=key_instruction(TRANSCRIBE, mixed=mixed),
                    dpi=150,
                ),
                status="transcribed",
                text="x" * (40 if page == 1 else 3),
                mixed=mixed,
                cost_usd=0.002,
                created=datetime(2026, 9, 27, tzinfo=UTC),
            ),
            instruction=TRANSCRIBE,
        )
    from ntsb_probable_cause.docket.transcribe import ReadingLookup

    rows = rows_for_document(document, ReadingLookup(cache).for_document(document), fatal=False)
    assert [(r.kind, r.chars) for r in rows] == [("image only", 40), ("text and image", 3)]
    assert rows[1].layer_chars >= len(TYPED) - 1
    assert all(r.cost_usd == pytest.approx(0.002) for r in rows)


def test_main_refuses_a_sample_that_is_not_dev_400() -> None:
    with pytest.raises(SystemExit, match="dev-400 only"):
        page_value.main(["--sample", "heldout-400"])
```

(Move the `ReadingLookup` import to the top when writing the file; ruff's import-order rule requires it.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_page_value.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.page_value'`.

- [ ] **Step 3: Implement `scripts/page_value.py`**

```python
"""What each page rule keeps of S2.6's transcriptions on dev-400 (S2.7 spec §7.3, T3).

Status
    Repeatable, free: reads the dev-400 docket cache and the transcription cache; makes no
    model call. Counts only (no case number, no page text). Decision 0100 item 4 fixes the
    choice before it runs: of the three rules, the one with the fewest pages whose transcribed
    characters are at least 90% of what S2.6's rule ("all") transcribed. Its effect on answers
    is measured at S2.7's meeting point, not here.

Why
    In the dev-400 transcription, text-and-image pages were about three fifths of the cost and
    most came back nearly empty, because their text layer already held the words (ad-hoc, S2.7
    spec §7.1). This script re-derives that with a committed script and picks a rule by a rule.

Usage
    uv run python -m scripts.page_value [--sample dev-400] [--out PATH]
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import PageKind, document_facts
from ntsb_probable_cause.docket.render import image_area_shares
from ntsb_probable_cause.docket.transcribe import (
    PAGE_RULES,
    PageRule,
    ReadingLookup,
    Transcription,
    TranscriptionCache,
    page_choice,
)
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings
from scripts.transcriber_test import _offline

KEEP_SHARE = 0.9  # decision 0100 item 4
NEAR_EMPTY_CHARS = 20  # "returned under 20 characters" (S2.7 spec §7.1)
_LAYER_BANDS = ((50, 200), (200, 1000), (1000, None))
_SHARE_BANDS = ((0.0, 0.1), (0.1, 0.7), (0.7, None))


@dataclass(frozen=True)
class PageRow:
    """One image-bearing page: what the PDF holds, and what S2.6's reading of it returned."""

    fatal: bool
    kind: PageKind
    layer_chars: int
    image_share: float
    status: str | None  # "transcribed", "failed", or None when there is no reading
    chars: int
    cost_usd: float


@dataclass(frozen=True)
class RuleTally:
    """What one rule sends: pages, transcribed characters, cost, failed readings."""

    pages: int
    chars: int
    cost_usd: float
    failed: int


def rows_for_document(
    data: bytes, readings: Mapping[int, Transcription], *, fatal: bool
) -> list[PageRow]:
    """One row per image-bearing page of one PDF, joined to its S2.6 reading if any."""
    shares = image_area_shares(data)
    rows: list[PageRow] = []
    for number, page in enumerate(document_facts(data), start=1):
        if page.kind not in ("image only", "text and image"):
            continue
        reading = readings.get(number)
        text = reading.text if reading is not None and reading.status == "transcribed" else ""
        rows.append(
            PageRow(
                fatal=fatal,
                kind=page.kind,
                layer_chars=page.chars,
                image_share=shares[number - 1] if number <= len(shares) else 0.0,
                status=None if reading is None else reading.status,
                chars=len(text.strip()),
                cost_usd=0.0 if reading is None else reading.cost_usd,
            )
        )
    return rows


def _sent(row: PageRow, page_rule: PageRule) -> bool:
    choice = page_choice(row.kind, row.layer_chars, row.image_share, page_rule=page_rule)
    return choice is not None


def tally(rows: Sequence[PageRow], page_rule: PageRule) -> RuleTally:
    """Pages, characters, cost and failures of the pages ``page_rule`` sends."""
    sent = [r for r in rows if _sent(r, page_rule)]
    return RuleTally(
        pages=len(sent),
        chars=sum(r.chars for r in sent),
        cost_usd=sum(r.cost_usd for r in sent),
        failed=sum(1 for r in sent if r.status == "failed"),
    )


def choose_rule(rows: Sequence[PageRow]) -> tuple[PageRule, list[str]]:
    """Decision 0100 item 4: the fewest pages keeping at least 90% of "all"'s characters."""
    everything = tally(rows, "all")
    notes: list[str] = []
    kept: list[tuple[int, int, PageRule]] = []
    for order, rule in enumerate(PAGE_RULES):
        counted = tally(rows, rule)
        share = counted.chars / everything.chars if everything.chars else 1.0
        admissible = share >= KEEP_SHARE
        notes.append(
            f"{rule}: {counted.pages} pages, {share:.1%} of the characters "
            f"({'admissible' if admissible else 'under 90%'})"
        )
        if admissible:
            kept.append((counted.pages, order, rule))
    return min(kept)[2], notes


def _band(value: float, bands: Sequence[tuple[float, float | None]]) -> str:
    for low, high in bands:
        if value >= low and (high is None or value < high):
            return f"{low:g}+" if high is None else f"{low:g}-{high:g}"
    return "other"


def _band_lines(rows: Sequence[PageRow], title: str, key: str) -> list[str]:
    mixed = [r for r in rows if r.kind == "text and image"]
    bands = _LAYER_BANDS if key == "layer" else _SHARE_BANDS
    lines = [f"## text-and-image pages by {title}", "  band        pages  near-empty  chars  cost"]
    for low, high in bands:
        label = _band(low, bands)
        members = [
            r
            for r in mixed
            if _band(r.layer_chars if key == "layer" else r.image_share, bands) == label
        ]
        empty = sum(1 for r in members if r.chars < NEAR_EMPTY_CHARS)
        lines.append(
            f"  {label:<10} {len(members):6d} {empty:11d} {sum(r.chars for r in members):6d} "
            f"${sum(r.cost_usd for r in members):.2f}"
        )
        del high
    return lines


def report(rows: Sequence[PageRow], *, sample: str, cases: int, pdfs: int) -> str:
    """The counts, each rule's tally by fatal and non-fatal, and the rule chosen."""
    chosen, notes = choose_rule(rows)
    lines = [
        "# page value: what each page rule keeps of S2.6's transcriptions (S2.7 spec §7.3, "
        "decision 0100 item 4) -- counts only",
        f"sample {sample}: {cases} cases, {pdfs} PDFs; {len(rows)} image-bearing pages; "
        "readings: S2.6's transcriber, instruction t1, 150 dpi",
        f"pages with no reading: {sum(1 for r in rows if r.status is None)}",
        "",
        "## by rule",
        "  rule                    pages   chars      cost  failed  fatal pages  non-fatal pages",
    ]
    for rule in PAGE_RULES:
        t = tally(rows, rule)
        fatal = tally([r for r in rows if r.fatal], rule).pages
        lines.append(
            f"  {rule:<22} {t.pages:6d} {t.chars:8d}  ${t.cost_usd:7.2f} {t.failed:7d} "
            f"{fatal:12d} {t.pages - fatal:16d}"
        )
    lines += ["", *_band_lines(rows, "text-layer characters", "layer")]
    lines += ["", *_band_lines(rows, "image cover", "share")]
    lines += ["", "## the choice (decision 0100 item 4, fixed before this ran)", *notes]
    lines.append(f"chosen: {chosen}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Count, choose, print, and with ``--out`` write the results file."""
    parser = argparse.ArgumentParser(prog="page_value")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.sample != "dev-400":
        raise SystemExit("page_value reads dev-400 only (S2.7 spec §7.3)")
    settings = Settings()
    raws = load_cases(settings.data_dir / "processed", sample_ids(args.sample))
    lookup = ReadingLookup(TranscriptionCache(settings.transcription_dir), page_rule="all")
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1))
    rows: list[PageRow] = []
    pdfs = 0
    for raw in raws:
        mkey = raw.get("mKey")
        if not isinstance(mkey, int):
            continue
        fatal = raw.get("highestInjuryLevel") == "Fatal"
        for entry in docs.listing(mkey).entries:
            if not entry.is_pdf():
                continue
            try:
                data = docs.document(mkey, entry.index)
                rows += rows_for_document(data, lookup.for_document(data), fatal=fatal)
            except DocketError:
                continue
            pdfs += 1
    text = report(rows, sample=args.sample, cases=len(raws), pdfs=pdfs)
    print(text)
    if args.out is not None:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(`del high` silences an unused loop variable; if ruff prefers `for low, _high in bands`, use that. `_band(low, bands)` labels a band by its own lower edge.)

Add to `Makefile` (and `s27-page-value` to `.PHONY`):

```make
s27-page-value:
	uv run python -m scripts.page_value --sample dev-400 --out docs/results/s27-page-value.txt
# S2.7 spec §7.3 (T3), free: reads the dev-400 docket and transcription caches; no model call.
```

- [ ] **Step 4: Run the tests, then `make check`**

Run: `uv run pytest tests/test_page_value.py -v && make check`
Expected: PASS.

- [ ] **Step 5: Commit the code**

```bash
git add scripts/page_value.py tests/test_page_value.py Makefile docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: T3, the page-value counts and the page-rule choice"
```

- [ ] **Step 6: Run it on `dev-400` (free) and commit the results file**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
make s27-page-value
```
Expected: about 12,500 image-bearing pages (S2.6: 12,458 pages chosen, `docs/results/s26-page-kinds.txt`), `pages with no reading` near zero, a `chosen:` line. Check that the `all` row's cost is close to S2.6's $13.06 attributed to cases (`docs/results/s26-armB-v2-dev.txt`); a gap of more than a few per cent is logged in Deviations with its cause before going on.

```bash
git add docs/results/s27-page-value.txt docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: T3 results on dev-400"
```

---

### Task 5: T1 — fetch the model list and apply the fixed filter (spec §7.2; decision 0100 item 1; walkthroughs W1, W5, W6; free)

**Files:**
- Create: `scripts/transcriber_shortlist.py` (the `fetch` and `shortlist` subcommands)
- Create: `tests/test_transcriber_shortlist.py`
- Modify: `Makefile` (targets `s27-models-fetch`, `s27-shortlist`)
- Create (by running): `docs/results/s27-transcriber-shortlist.txt`

**Interfaces:**
- Consumes: `sources.QWEN_35_122B` (`input_usd_per_mtok = 0.26`), `sources.ReasoningEffort`, `scripts.transcriber_test.CANDIDATES` (S2.6's four).
- Produces: `MODELS_URL = "https://openrouter.ai/api/v1/models"`; `RELEASED_FROM = datetime(2026, 6, 1, tzinfo=UTC)`; `SHORTLIST_SIZE = 8`; `Listed` (frozen dataclass: `model_id`, `slug`, `created: datetime`, `input_usd_per_mtok`, `output_usd_per_mtok`, `lowest_reasoning: ReasoningEffort`, `batch_variant: bool`); `refusal(entry: Mapping[str, object], *, ids: AbstractSet[str]) -> str | None`; `lowest_reasoning(entry) -> ReasoningEffort`; `shortlist(entries) -> tuple[list[Listed], Counter[str]]`; `render_shortlist(listed, refused, *, source: Path, fetched: str) -> str`; `main(argv) -> int`.

**The filter, fixed now** (decision 0100 item 1, with walkthrough W6's condition marked): an entry is refused, with the first reason that applies, if it is a `:batch` variant; an alias (`~` id or an `alias_target`); does not take image input; does not return text only; was created before 2026-06-01; lists an input price above Qwen3.5 122B's $0.26 per million tokens; is one of S2.6's four candidates; (W6) does not list `response_format`. The eligible models are ordered by input price, then output price, then id; duplicates of one `canonical_slug` keep the first. The first eight are the shortlist; the rest are the replacements Task 7 takes in order.

- [ ] **Step 1: Write the failing tests**

```python
"""S2.7 track 2, Tasks 5-7: the model-list filter, the reasoning rule and the probe."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from scripts import transcriber_shortlist as ts

_JUNE = int(datetime(2026, 7, 1, tzinfo=UTC).timestamp())
_MAY = int(datetime(2026, 5, 1, tzinfo=UTC).timestamp())


def _entry(model_id: str, **over: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": model_id,
        "canonical_slug": model_id + "-20260701",
        "created": _JUNE,
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        "pricing": {"prompt": "0.00000003", "completion": "0.00000013"},
        "supported_parameters": ["reasoning", "response_format", "max_tokens"],
        "reasoning": {"mandatory": False, "default_enabled": True},
    }
    entry.update(over)
    return entry


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"id": "vendor/model:batch"}, "batch variant"),
        ({"id": "~vendor/model-latest"}, "alias"),
        ({"alias_target": "vendor/model"}, "alias"),
        ({"architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
         "no image input"),
        ({"architecture": {"input_modalities": ["text", "image"],
                           "output_modalities": ["text", "image"]}}, "not text-only output"),
        ({"created": _MAY}, "released before 2026-06-01"),
        ({"pricing": {"prompt": "0.0000003", "completion": "0.000001"}},
         "input price above Qwen3.5 122B's"),
        ({"id": "qwen/qwen3.5-122b-a10b"}, "an S2.6 candidate"),
        ({"supported_parameters": ["reasoning"]}, "no structured output"),
    ],
)
def test_the_filter_refuses_with_the_first_reason_that_applies(
    over: dict[str, object], reason: str
) -> None:
    assert ts.refusal(_entry("vendor/model", **over), ids=frozenset()) == reason


def test_an_eligible_entry_is_not_refused() -> None:
    assert ts.refusal(_entry("vendor/model"), ids=frozenset()) is None


def test_the_shortlist_orders_by_price_and_keeps_one_per_slug() -> None:
    entries = [
        _entry("b/cheap", pricing={"prompt": "0.00000002", "completion": "0.0000001"}),
        _entry("a/dear", pricing={"prompt": "0.0000002", "completion": "0.0000001"}),
        _entry("c/cheap-again", canonical_slug="b/cheap-20260701",
               pricing={"prompt": "0.00000002", "completion": "0.0000002"}),
        _entry("d/old", created=_MAY),
    ]
    listed, refused = ts.shortlist(entries)
    assert [x.model_id for x in listed] == ["b/cheap", "a/dear"]
    assert refused["released before 2026-06-01"] == 1
    assert refused["same model as a cheaper listing"] == 1
    assert listed[0].input_usd_per_mtok == pytest.approx(0.02)


@pytest.mark.parametrize(
    ("reasoning", "params", "lowest"),
    [
        ({"mandatory": False, "supported_efforts": ["low", "minimal", "high"]}, ["reasoning"],
         "minimal"),
        ({"mandatory": True}, ["reasoning"], "minimal"),
        ({"mandatory": False}, ["reasoning"], "none"),
        (None, ["max_tokens"], "none"),
    ],
)
def test_the_lowest_reasoning_rule(
    reasoning: dict[str, object] | None, params: list[str], lowest: str
) -> None:
    entry = _entry("vendor/model", supported_parameters=params)
    entry["reasoning"] = reasoning
    assert ts.lowest_reasoning(entry) == lowest


def test_a_batch_variant_in_the_list_is_noted() -> None:
    listed, _ = ts.shortlist([_entry("v/m"), _entry("v/m:batch")])
    assert [x.model_id for x in listed] == ["v/m"]
    assert listed[0].batch_variant is True


@respx.mock
def test_fetch_saves_the_list_it_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    respx.get(ts.MODELS_URL).mock(
        return_value=httpx.Response(200, json={"data": [_entry("v/m")]})
    )
    assert ts.main(["fetch", "--date", "2026-09-27"]) == 0
    saved = tmp_path / "s27" / "openrouter-models-2026-09-27.json"
    assert json.loads(saved.read_text())["data"][0]["id"] == "v/m"
```

Note: `pytest-socket` blocks real network access; `respx.mock` intercepts the `httpx` call before any socket opens, as in `tests/test_typesafe_client.py` on the `typesafe-probe` branch and every OpenRouter test on `main`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_transcriber_shortlist.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.transcriber_shortlist'`.

- [ ] **Step 3: Implement `fetch` and `shortlist`**

```python
"""The transcriber shortlist: newer vision models by a fixed filter, then probed (S2.7 §7.2).

Status
    Repeatable. Subcommands, in order:
      fetch      -- read OpenRouter's public model list and save it under
                    <data_dir>/s27/openrouter-models-<date>.json (free, no key)
      shortlist  -- apply decision 0100 item 1's filter to a saved list; write
                    docs/results/s27-transcriber-shortlist.txt (free)
      probe      -- one invented page to each shortlisted model, in order, replacing a failure
                    by the next, until eight pass (paid, cents); records each reply as a fixture
      batch-image, batch-poll
                 -- one batch request carrying an image, and its outcome (paid, a fraction of
                    a cent; walkthrough W2)
    The saved list, not memory, is the source of every id, price, date and reasoning level
    (rule 2). The recorded replies are of an invented page and hold no docket text.
"""

import argparse
import json
from collections import Counter
from collections.abc import AbstractSet, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast, get_args

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.settings import Settings
from scripts.transcriber_test import CANDIDATES as S26_CANDIDATES

MODELS_URL = "https://openrouter.ai/api/v1/models"
RELEASED_FROM = datetime(2026, 6, 1, tzinfo=UTC)
SHORTLIST_SIZE = 8
RESULTS = Path("docs/results/s27-transcriber-shortlist.txt")
_LADDER: tuple[sources.ReasoningEffort, ...] = get_args(sources.ReasoningEffort)


@dataclass(frozen=True)
class Listed:
    """One eligible model, as the saved list gives it."""

    model_id: str
    slug: str
    created: datetime
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    lowest_reasoning: sources.ReasoningEffort
    batch_variant: bool


def _map(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def _per_mtok(pricing: Mapping[str, object], name: str) -> float:
    return float(str(pricing.get(name, "inf"))) * 1_000_000


# One return per refusal, in the fixed order of decision 0100 item 1.
def refusal(entry: Mapping[str, object], *, ids: AbstractSet[str]) -> str | None:  # noqa: PLR0911
    """The first reason decision 0100 item 1 refuses this entry, or None if it is eligible.

    ``ids`` is every id in the list; it is unused by the rules above and kept so the batch
    check (``_has_batch``) and this function read the same list.
    """
    del ids
    model_id = str(entry.get("id", ""))
    architecture = _map(entry.get("architecture"))
    if model_id.endswith(":batch"):
        return "batch variant"
    if model_id.startswith("~") or entry.get("alias_target"):
        return "alias"
    if "image" not in _strings(architecture.get("input_modalities")):
        return "no image input"
    if _strings(architecture.get("output_modalities")) != ("text",):
        return "not text-only output"
    created = entry.get("created")
    if not isinstance(created, int) or datetime.fromtimestamp(created, UTC) < RELEASED_FROM:
        return "released before 2026-06-01"
    if _per_mtok(_map(entry.get("pricing")), "prompt") > sources.QWEN_35_122B.input_usd_per_mtok:
        return "input price above Qwen3.5 122B's"
    if model_id in S26_CANDIDATES:
        return "an S2.6 candidate"
    if "response_format" not in _strings(entry.get("supported_parameters")):
        return "no structured output"  # walkthrough W6
    return None


def lowest_reasoning(entry: Mapping[str, object]) -> sources.ReasoningEffort:
    """Walkthrough W1: the lowest listed effort; else minimal if reasoning is mandatory; else none."""
    reasoning = _map(entry.get("reasoning"))
    listed = [e for e in _LADDER if e in _strings(reasoning.get("supported_efforts"))]
    if listed:
        return listed[0]
    return "minimal" if reasoning.get("mandatory") is True else "none"


def shortlist(entries: Sequence[Mapping[str, object]]) -> tuple[list[Listed], Counter[str]]:
    """Eligible models, cheapest input first, one per canonical slug; and refusal counts."""
    ids = {str(e.get("id", "")) for e in entries}
    refused: Counter[str] = Counter()
    eligible: list[Listed] = []
    for entry in entries:
        reason = refusal(entry, ids=ids)
        if reason is not None:
            refused[reason] += 1
            continue
        pricing = _map(entry.get("pricing"))
        model_id = str(entry["id"])
        eligible.append(
            Listed(
                model_id=model_id,
                slug=str(entry.get("canonical_slug") or model_id),
                created=datetime.fromtimestamp(cast("int", entry["created"]), UTC),
                input_usd_per_mtok=_per_mtok(pricing, "prompt"),
                output_usd_per_mtok=_per_mtok(pricing, "completion"),
                lowest_reasoning=lowest_reasoning(entry),
                batch_variant=f"{model_id}:batch" in ids,
            )
        )
    eligible.sort(key=lambda x: (x.input_usd_per_mtok, x.output_usd_per_mtok, x.model_id))
    kept: list[Listed] = []
    slugs: set[str] = set()
    for listed in eligible:
        if listed.slug in slugs:
            refused["same model as a cheaper listing"] += 1
            continue
        slugs.add(listed.slug)
        kept.append(listed)
    return kept, refused


def render_shortlist(
    listed: Sequence[Listed], refused: Counter[str], *, source: Path, fetched: str
) -> str:
    """The results file: the filter's counts, the ordered eligible list, and sources.py lines."""
    lines = [
        "# the transcriber shortlist (S2.7 spec §7.2, decision 0100 item 1) -- model ids only",
        f"model list: {MODELS_URL}, read {fetched}, saved as {source.name}",
        f"eligible: {len(listed)}; refused: "
        + ", ".join(f"{reason} {n}" for reason, n in sorted(refused.items())),
        "",
        f"## eligible, cheapest input first (the first {SHORTLIST_SIZE} are the shortlist; the "
        "rest replace a failed probe, in order)",
    ]
    for rank, x in enumerate(listed, start=1):
        mark = "candidate" if rank <= SHORTLIST_SIZE else "reserve  "
        lines.append(
            f"{mark} {rank:2d} {x.model_id}  ${x.input_usd_per_mtok:.3f}/${x.output_usd_per_mtok:.3f}"
            f" per M tokens; created {x.created:%Y-%m-%d}; lowest reasoning {x.lowest_reasoning}; "
            f"batch variant {'yes' if x.batch_variant else 'no'}"
        )
    return "\n".join(lines)


def _saved(settings: Settings, fetched: str) -> Path:
    return settings.data_dir / "s27" / f"openrouter-models-{fetched}.json"


def cmd_fetch(settings: Settings, fetched: str) -> str:
    """Read the public model list (no key) and save it as read."""
    response = httpx.get(MODELS_URL, timeout=60.0)
    response.raise_for_status()
    path = _saved(settings, fetched)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text)
    count = len(_entries(path))
    return f"saved {count} models to {path}"


def _entries(path: Path) -> list[Mapping[str, object]]:
    data = json.loads(path.read_text())["data"]
    return [cast("Mapping[str, object]", e) for e in data]


def cmd_shortlist(path: Path) -> str:
    """Apply the filter to a saved list."""
    fetched = path.stem.removeprefix("openrouter-models-")
    listed, refused = shortlist(_entries(path))
    return render_shortlist(listed, refused, source=path, fetched=fetched)


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_shortlist")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_p = commands.add_parser("fetch")
    fetch_p.add_argument("--date", default=f"{date.today():%Y-%m-%d}")
    short_p = commands.add_parser("shortlist")
    short_p.add_argument("--models", type=Path, required=True)
    short_p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "fetch":
        text = cmd_fetch(settings, args.date)
    else:
        text = cmd_shortlist(args.models)
        if args.out is not None:
            args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(`date.today()` may be flagged by ruff `DTZ`; that rule set is not selected in this project. If it is, use `datetime.now(UTC).date()`.)

Add to `Makefile` (and both names to `.PHONY`):

```make
s27-models-fetch:
	uv run python -m scripts.transcriber_shortlist fetch
# S2.7 spec §7.2, free: saves OpenRouter's public model list under <data_dir>/s27/.

s27-shortlist:
	$(if $(MODELS),,$(error MODELS is required: the saved list, e.g. MODELS=$$NTSB_DATA_DIR/s27/openrouter-models-2026-09-27.json))
	uv run python -m scripts.transcriber_shortlist shortlist --models $(MODELS) --out docs/results/s27-transcriber-shortlist.txt
# S2.7 spec §7.2, free: decision 0100 item 1's filter over the saved list.
```

- [ ] **Step 4: Run the tests, then `make check`**

Run: `uv run pytest tests/test_transcriber_shortlist.py -v && make check`
Expected: PASS.

- [ ] **Step 5: Commit the code**

```bash
git add scripts/transcriber_shortlist.py tests/test_transcriber_shortlist.py Makefile docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: T1, the model-list filter and the shortlist"
```

- [ ] **Step 6: Fetch, filter, commit the results file** (free)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
make s27-models-fetch
make s27-shortlist MODELS=$NTSB_DATA_DIR/s27/openrouter-models-$(date -u +%Y-%m-%d).json
git add docs/results/s27-transcriber-shortlist.txt docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: T1 shortlist from the saved model list"
```
If fewer than eight models are eligible, record the count in Deviations (walkthrough W5) and go on with what there is.

---

### Task 6: Prices and reasoning levels for the shortlisted models (spec §7.2; rule 2)

**Files:**
- Modify: `src/ntsb_probable_cause/sources.py` (price constants near `QWEN_35_122B` at :101; `_PRICES` at :103; `LOWEST_REASONING` at :138)
- Modify: `scripts/transcriber_shortlist.py` (constant `S27_SHORTLIST`)
- Test: `tests/test_sources_settings.py`, `tests/test_transcriber_shortlist.py`

**Interfaces:**
- Produces: `transcriber_shortlist.S27_SHORTLIST: tuple[str, ...]` (every eligible model in the results file's order, first eight and reserves); a `ModelPrice` and a `LOWEST_REASONING` entry for each.

**Why every eligible model, reserves included.** Task 7 replaces a failed probe by the next model in order; each needs a price and a level before it is called, or `settings_for` and `cost_usd` raise mid-probe.

- [ ] **Step 1: Write the failing tests**

In `tests/test_transcriber_shortlist.py`:

```python
def test_the_shortlist_constant_matches_the_committed_results_file() -> None:
    lines = Path("docs/results/s27-transcriber-shortlist.txt").read_text().splitlines()
    listed = [
        line.split()[2] for line in lines if line.startswith(("candidate ", "reserve "))
    ]
    assert list(ts.S27_SHORTLIST) == listed


def test_every_shortlisted_model_is_priced_and_has_a_reasoning_level() -> None:
    from ntsb_probable_cause import sources

    for model in ts.S27_SHORTLIST:
        price = sources.price_of(model)
        assert "OpenRouter models API, 2026-09" in price.source
        assert model in sources.LOWEST_REASONING
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_transcriber_shortlist.py -k "constant or priced" -v`
Expected: FAIL (`AttributeError: ... has no attribute 'S27_SHORTLIST'`).

- [ ] **Step 3: Add the entries, copied from the results file**

For each line of `docs/results/s27-transcriber-shortlist.txt` that starts `candidate` or `reserve`, add in `sources.py`, below `QWEN_35_122B`, one constant with a source comment naming the saved list, for example:

```python
# https://openrouter.ai/api/v1/models, read <date> and saved as
# <data_dir>/s27/openrouter-models-<date>.json (S2.7 track 2, Task 5): the transcriber
# shortlist of decision 0100 item 1, prices as listed per million tokens.
S27_<NAME> = ModelPrice("<model id>", <input>, <output>, "OpenRouter models API, <date>")
```

add each constant to the `_PRICES` tuple, and add each model to `LOWEST_REASONING` with the level the results file gives (walkthrough W1's rule). Set in `scripts/transcriber_shortlist.py`:

```python
# The results file's eligible models, in its order (Task 6): the first SHORTLIST_SIZE are the
# shortlist, the rest replace a failed probe in order. Every one is priced in sources.py.
S27_SHORTLIST: tuple[str, ...] = (
    "<model id 1>",
    "<model id 2>",
    # ... one line per "candidate"/"reserve" line of docs/results/s27-transcriber-shortlist.txt
)
```

These are data copied from a committed results file, not choices; the two tests prove the copy.

- [ ] **Step 4: Run the tests and `make check`**

Run: `uv run pytest tests/test_transcriber_shortlist.py tests/test_sources_settings.py -v && make check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/sources.py scripts/transcriber_shortlist.py tests/test_transcriber_shortlist.py docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: prices and reasoning levels of the shortlisted models"
```

---

### Task 7: The probe, and the batch-with-image call (spec §7.2; walkthroughs W1, W2, W5; paid, cents)

**Files:**
- Modify: `scripts/transcriber_shortlist.py` (`cmd_probe`, `cmd_batch_image`, `cmd_batch_poll`; constants `PROBE_WANTED`, `S27_CANDIDATES`)
- Modify: `tests/test_transcriber_shortlist.py`
- Modify: `Makefile` (`s27-transcriber-probe`, `s27-batch-image`)
- Create (by running): `tests/fixtures/openrouter/transcription/<model>.json` for each probed model

**Interfaces:**
- Consumes: `scripts.transcriber_test.probe_page`, `PROBE_LINES`, `FIXTURES`; `docket.render.render_pages`; `docket.transcribe.request_for`, `settings_for`, `parse_reply`, `TRANSCRIBE`; `model.client.cost_usd`; `scoring.preparation.openrouter_clients`; `scoring.budget.reserve_within_budget`, `write_spend`, `SpendRecord`, `settle`; `gitinfo.commit_state`; `model.openrouter.OpenRouterClient.request_json`, `request_body`; `model.batch.BatchClient.poll`.
- Produces: `PROBE_WANTED = 8`; `probe(models, complete) -> tuple[list[str], list[str]]` (passed ids, report lines), where `complete: Callable[[str], ModelReply]`; `S27_CANDIDATES: tuple[str, ...]` (set after the run, Step 7).

**What passes.** A model passes if it answers and its reply parses under instruction t1 (`parse_reply`), as in S2.6's probe. How many probe lines it copies is printed, not judged: the answer keys judge reading.

- [ ] **Step 1: Write the failing tests**

```python
from ntsb_probable_cause.model.client import ModelReply, Usage
from ntsb_probable_cause.errors import ModelError


def _reply(content: str) -> ModelReply:
    return ModelReply(
        content=content, usage=Usage(prompt_tokens=10, completion_tokens=5), model="m",
        response_id="r",
    )


_GOOD = json.dumps({"page_kind": "typed text", "text": "Engine sputtered at 800 ft."})


def test_the_probe_replaces_a_failure_by_the_next_model_until_enough_pass() -> None:
    def complete(model: str) -> ModelReply:
        if model == "b/fails":
            raise ModelError("400 reasoning effort not supported")
        if model == "c/bad-json":
            return _reply("not json")
        return _reply(_GOOD)

    passed, lines = ts.probe(("a/ok", "b/fails", "c/bad-json", "d/ok", "e/ok"), complete, wanted=3)
    assert passed == ["a/ok", "d/ok", "e/ok"]
    assert any("b/fails: FAILED" in line for line in lines)
    assert any("c/bad-json: the reply did not parse" in line for line in lines)


def test_the_probe_stops_once_enough_pass() -> None:
    called: list[str] = []

    def complete(model: str) -> ModelReply:
        called.append(model)
        return _reply(_GOOD)

    passed, _ = ts.probe(("a", "b", "c"), complete, wanted=2)
    assert passed == ["a", "b"]
    assert called == ["a", "b"]
```

(Check `ModelReply` and `Usage` constructor fields in `model/client.py` before writing: `Usage` may need `reported_cost_usd` and `reasoning_tokens` defaults. Adjust the helper to the real fields.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_transcriber_shortlist.py -k probe -v`
Expected: FAIL (`AttributeError: ... has no attribute 'probe'`).

- [ ] **Step 3: Implement**

```python
PROBE_WANTED = 8
# Expected cost of one probe call, for the reservation (S2.6's probe: under $0.005 a model).
PROBE_EXPECTED_USD = 0.005


def probe(
    models: Sequence[str],
    complete: Callable[[str], ModelReply],
    *,
    wanted: int = PROBE_WANTED,
) -> tuple[list[str], list[str]]:
    """Probe models in order until ``wanted`` pass; a failure is replaced by the next."""
    passed: list[str] = []
    lines: list[str] = []
    for model in models:
        if len(passed) == wanted:
            break
        try:
            reply = complete(model)
        except ModelError as error:
            lines.append(f"{model}: FAILED -- {type(error).__name__}: {str(error)[:200]}")
            continue
        try:
            text, kind = parse_reply(reply.content or "", TRANSCRIBE)
        except SchemaError as error:
            lines.append(f"{model}: the reply did not parse -- {error}")
            continue
        copied = sum(1 for line in PROBE_LINES if line in text)
        lines.append(f"{model}: ok, kind {kind}, {copied} of {len(PROBE_LINES)} lines copied")
        passed.append(model)
    return passed, lines


def cmd_probe(settings: Settings) -> str:
    """One invented page to each shortlisted model in order; each reply saved as a fixture.

    Reserved, spent and settled as S2.6's probe was (``transcriber_test.cmd_probe``): the
    client factory is built before the reservation, the spend row is written in a ``finally``.
    """
    (rendered,) = render_pages(probe_page())
    payload, system = request_for(rendered, TRANSCRIBE, text_layer=None)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    sha, dirty = commit_state()
    started = datetime.now(UTC)
    job_id = f"{started:%Y%m%dT%H%M%S}-{sha}-s27-transcriber-probe"
    factory = openrouter_clients(settings)
    reserve_within_budget(
        settings.runs_dir,
        job_id,
        len(S27_SHORTLIST) * PROBE_EXPECTED_USD,
        settings.monthly_budget_usd,
        now=started,
    )
    spent = 0.0
    calls = 0
    try:
        with ExitStack() as stack:
            make = factory(stack)

            def complete(model: str) -> ModelReply:
                nonlocal spent, calls
                model_settings = settings_for(model, TRANSCRIBE)
                reply = make().complete(payload, model_settings, system=system)
                calls += 1
                spent += cost_usd(reply, model_settings)[0]
                name = model.replace("/", "__") + ".json"
                (FIXTURES / name).write_text(reply.model_dump_json(indent=1) + "\n")
                return reply

            passed, lines = probe(S27_SHORTLIST, complete)
    finally:
        write_spend(
            settings.runs_dir,
            SpendRecord(
                job_id=job_id,
                kind="transcriber-test",
                model="s27-shortlist",
                started=started,
                calls=calls,
                cost_usd=spent,
                commit_sha=sha,
                dirty=dirty,
            ),
        )
        settle(settings.runs_dir, job_id)
    lines.append(f"passed ({len(passed)}): " + ", ".join(passed))
    return "\n".join(lines)
```

Imports to add: `from collections.abc import Callable`; `from contextlib import ExitStack`; `from ntsb_probable_cause.docket.render import render_pages`; `from ntsb_probable_cause.docket.transcribe import TRANSCRIBE, parse_reply, request_for, settings_for`; `from ntsb_probable_cause.errors import ModelError, SchemaError`; `from ntsb_probable_cause.gitinfo import commit_state`; `from ntsb_probable_cause.model.client import ModelReply, cost_usd`; `from ntsb_probable_cause.scoring.budget import SpendRecord, reserve_within_budget, settle, write_spend`; `from ntsb_probable_cause.scoring.preparation import openrouter_clients`; `from scripts.transcriber_test import FIXTURES, PROBE_LINES, probe_page`.

**The batch call** (walkthrough W2; skip this part and its target if Andy drops it). One batch request carrying the probe image, for the first passed model with `batch_variant` true in the results file. It is sent through `OpenRouterClient.request_json` with the body `BatchClient.submit` builds, because `BatchClient.submit` refuses images by design (S2.6 W1) and must keep refusing them:

```python
def cmd_batch_image(settings: Settings, model: str) -> str:
    """Walkthrough W2: does OpenRouter's batch service now accept one image part?"""
    (rendered,) = render_pages(probe_page())
    payload, system = request_for(rendered, TRANSCRIBE, text_layer=None)
    model_settings = settings_for(model, TRANSCRIBE).model_copy(update={"price_variant": "batch"})
    body: dict[str, object] = {
        "endpoint": "/v1/chat/completions",
        "model": model_settings.model_id(),
        "requests": [
            {"custom_id": "s27-probe", "body": request_body(payload, model_settings, system=system)}
        ],
    }
    key = settings.require_openrouter_key()
    with OpenRouterClient(key, base_url=settings.openrouter_base_url) as http:
        try:
            submitted = http.request_json(sources.BATCHES, method="POST", body=body, retry=False)
        except ModelError as error:
            return f"{model_settings.model_id()}: refused -- {str(error)[:300]}"
    return f"{model_settings.model_id()}: accepted as batch {submitted['id']}; poll it with batch-poll"


def cmd_batch_poll(settings: Settings, batch_id: str) -> str:
    """The accepted batch's status, and whether its one reply parses."""
    key = settings.require_openrouter_key()
    with OpenRouterClient(key, base_url=settings.openrouter_base_url) as http:
        status = BatchClient(http).poll(batch_id)
    parsed = "no result yet"
    for result in status.results:
        if result.reply is None:
            parsed = f"error: {result.error}"
        else:
            try:
                parse_reply(result.reply.content or "", TRANSCRIBE)
                parsed = "the reply parses"
            except SchemaError as error:
                parsed = f"the reply did not parse: {error}"
    return f"batch {batch_id}: {status.status}; {parsed}; cost {status.reported_cost_usd}"
```

(`ModelSettings` is a pydantic model; if `model_copy` is not available on it, rebuild it with `price_variant="batch"`. Check `Settings.require_openrouter_key` exists as named in `settings.py`.)

Add the `probe`, `batch-image --model`, `batch-poll --batch-id` sub-parsers to `main`. Add to `Makefile`:

```make
s27-transcriber-probe:
	uv run python -m scripts.stage_spend --estimate 0.10
	uv run python -m scripts.transcriber_shortlist probe
# S2.7 spec §7.2, paid (estimate under $0.10): one invented page to each shortlisted model,
# replacing failures in order, until eight pass. Replies saved under
# tests/fixtures/openrouter/transcription/.

s27-batch-image:
	$(if $(MODEL),,$(error MODEL is required: a passed candidate with a batch variant))
	uv run python -m scripts.stage_spend --estimate 0.01
	uv run python -m scripts.transcriber_shortlist batch-image --model $(MODEL)
# S2.7 spec §7.2 and walkthrough W2, paid (a fraction of a cent): one batch request carrying
# the invented probe image.
```

- [ ] **Step 4: Run the tests and `make check`**

Run: `uv run pytest tests/test_transcriber_shortlist.py -v && make check`
Expected: PASS.

- [ ] **Step 5: Commit the code**

```bash
git add scripts/transcriber_shortlist.py tests/test_transcriber_shortlist.py Makefile docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: the shortlist probe and the batch-with-image call"
```

- [ ] **Step 6: STOP — Andy runs the probe (paid, under $0.10, a minute or two)**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
export OPENROUTER_API_KEY="$(pass show api/openrouter)"
make s27-transcriber-probe
# only if walkthrough W2 kept the batch call, with the first passed model that has a batch variant:
make s27-batch-image MODEL=<model id>
uv run python -m scripts.transcriber_shortlist batch-poll --batch-id <id printed>   # a few minutes later
```

- [ ] **Step 7: Record the passed candidates and the fixtures**

Set, from the probe's `passed (...)` line:

```python
# The shortlisted models that passed the probe (Task 7 Step 6, <date>), in shortlist order:
# the candidates of the re-test (decision 0100 item 2).
S27_CANDIDATES: tuple[str, ...] = ("<passed 1>", "<passed 2>")  # ... every passed id
```

Extend `tests/test_transcriber_test.py`'s parametrised `test_every_recorded_candidate_reply_parses` only if it globs the fixture folder; if it lists S2.6's four by name, add in `tests/test_transcriber_shortlist.py`:

```python
@pytest.mark.parametrize("model", ts.S27_CANDIDATES)
def test_every_passed_candidates_recorded_reply_parses(model: str) -> None:
    from ntsb_probable_cause.docket.transcribe import TRANSCRIBE, parse_reply
    from ntsb_probable_cause.model.client import ModelReply

    path = Path("tests/fixtures/openrouter/transcription") / (model.replace("/", "__") + ".json")
    reply = ModelReply.model_validate_json(path.read_text())
    text, _kind = parse_reply(reply.content or "", TRANSCRIBE)
    assert "Engine sputtered" in text
```

Append the probe's printed lines (and the batch outcome, or "not tested", with the reason) to `docs/results/s27-transcriber-shortlist.txt` under a `## probe (<date>)` heading. Commit fixtures (only the passed models' and any failed model whose reply was saved), results, constant and test:

```bash
make check
git add scripts/transcriber_shortlist.py tests/test_transcriber_shortlist.py tests/fixtures/openrouter/transcription docs/results/s27-transcriber-shortlist.txt docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: probe results; the re-test's candidates"
```

If no model passed: record it, skip Tasks 8–10, and write the decision record of Task 11 as "Qwen stays; no candidate passed the probe".

---

### Task 8: The re-test's rule, and Qwen's second pass reproduced from the cache (spec §7.4; decision 0100 item 3; walkthrough W7; free)

**Files:**
- Create: `scripts/transcriber_retest.py` (constants, `choose_against_qwen`, `cmd_verify`)
- Create: `tests/test_transcriber_retest.py`
- Modify: `Makefile` (`s27-retest-verify`)

**Interfaces:**
- Consumes: from `scripts.transcriber_test` — `CandidateResult`, `_result`, `_read`, `_int`, `_apply_recheck`, `Recheck`, `FOLDER` (S2.6's keys folder), `RESOLUTION`, `GATE_INVENTED_LINES_PER_100`, `GATE_INVENTED_PHOTO_SHARE`, `GATE_INVENTED_MIXED_SHARE`, `GATE_FORMAT_FAILED_SHARE`, `_offline`; `scripts.marking_page.read_marks`; `docket.pages.page_text`; `docket.transcribe.TranscriptionCache`; `scripts.transcriber_shortlist.S27_CANDIDATES`.
- Produces: `QWEN = "qwen/qwen3.5-122b-a10b"`; `QWEN_PASS2` (the published counts, below); `Limits` and `QWEN_LIMITS` (decision 0100 item 3); `choose_against_qwen(results: Sequence[CandidateResult]) -> tuple[str | None, list[str]]`; `absolute_notes(result) -> list[str]`; `KeyMaterial` (frozen dataclass: `keys`, `key_texts`, `typed_answers`, `qwen_photo_invented`, `qwen_mixed_invented`); `key_material(settings, docs, recheck) -> KeyMaterial`; `cmd_verify(settings, docs, recheck) -> str`.

**Why reproduce Qwen first.** Every candidate is judged against Qwen's second-pass figures (decision 0100 item 3). Those figures were made from Andy's handwriting key after 0086's recheck. If the re-test's reading of the keys differed at all — the wrong CSV pair (W7), a changed helper — every comparison would be against a different Qwen. Re-scoring Qwen from its cached readings and matching the published counts exactly proves the key material is the same, for free.

**The rule, fixed now** (decision 0100 item 3). A candidate replaces Qwen only if all seven hold; of those that do, the cheapest measured cost per test page wins; if none, Qwen stays:

| measure | limit | Qwen, second pass |
|---|---|---|
| invented handwriting lines per 100 | at most 3.5 | 54 in 1548 lines (3.5) |
| photographs with invented words | at most 2 of 50 | 2 of 50 |
| full-page scans with invented added words | at most 0 of 25 | 0 of 25 |
| handwriting pages failing the line format | at most 2 of 25 | 2 of 25 |
| handwriting lines right | at least 61.9% | 1036 of 1548 (66.9%) |
| typed errors per 100 characters | at most 13.29 | 20219 in 164464 (12.29) |
| measured cost per test page | below $0.00154 | $0.00154 |

0080's absolute limits (2 invented lines per 100; 1 in 20 photographs; 1 in 20 scans; 1 in 20 format-failed pages) are printed beside each candidate and decide nothing.

- [ ] **Step 1: Write the failing tests**

```python
"""S2.7 track 2, Tasks 8-10: the re-test against Qwen."""

from fractions import Fraction

import pytest

from scripts import transcriber_retest as tr
from scripts.transcriber_test import CandidateResult


def _result(model: str, **over: object) -> CandidateResult:
    fields: dict[str, object] = {
        "model": model,
        "cost_per_page": 0.0005,
        "hw_lines": 1548,
        "hw_right": 1036,
        "hw_inventing": 54,
        "photo_pages": 50,
        "photo_invented": 2,
        "typed_chars": 164464,
        "typed_errors": 20219,
        "mixed_pages": 25,
        "mixed_invented": 0,
        "hw_pages": 25,
        "hw_format_failed": 2,
    }
    fields.update(over)
    return CandidateResult(**fields)  # type: ignore[arg-type]


def test_a_candidate_equal_to_qwen_and_cheaper_replaces_it() -> None:
    chosen, _ = tr.choose_against_qwen([_result("a/m")])
    assert chosen == "a/m"


@pytest.mark.parametrize(
    "over",
    [
        {"hw_inventing": 55},  # 55 in 1548 lines is over 3.5 per 100
        {"photo_invented": 3},
        {"mixed_invented": 1},
        {"hw_format_failed": 3},
        {"hw_right": 958},  # 958/1548 = 61.89%, under 61.9%
        {"typed_errors": 21858},  # 13.29..., over 13.29 per 100 by one character
        {"cost_per_page": 0.00154},  # not below Qwen's
    ],
)
def test_each_measure_alone_keeps_qwen(over: dict[str, object]) -> None:
    chosen, notes = tr.choose_against_qwen([_result("a/m", **over)])
    assert chosen is None
    assert any("a/m: out" in n for n in notes)
    assert notes[-1] == "no candidate meets all seven: Qwen stays (decision 0100 item 3)"


def test_of_the_candidates_that_meet_all_seven_the_cheapest_wins() -> None:
    chosen, _ = tr.choose_against_qwen(
        [_result("a/dear", cost_per_page=0.0009), _result("b/cheap", cost_per_page=0.0003)]
    )
    assert chosen == "b/cheap"


def test_the_limits_are_decision_0100s() -> None:
    assert tr.QWEN_LIMITS.inventing_per_100 == Fraction(7, 2)
    assert tr.QWEN_LIMITS.photo_invented == 2
    assert tr.QWEN_LIMITS.mixed_invented == 0
    assert tr.QWEN_LIMITS.format_failed == 2
    assert tr.QWEN_LIMITS.hw_accuracy == Fraction(619, 1000)
    assert tr.QWEN_LIMITS.typed_errors_per_100 == Fraction(1329, 100)
    assert tr.QWEN_LIMITS.cost_per_page == 0.00154


def test_absolute_notes_print_0080s_limits_beside_a_candidate() -> None:
    notes = tr.absolute_notes(_result("a/m", hw_inventing=40))
    assert any("0080" in n for n in notes)


def test_verify_accepts_only_qwens_published_counts() -> None:
    assert tr.matches_qwen_pass2(_result(tr.QWEN, cost_per_page=0.00154)) == []
    assert tr.matches_qwen_pass2(_result(tr.QWEN, hw_right=1035)) == ["hw_right 1035, published 1036"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_transcriber_retest.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the rule and `verify`**

```python
"""The transcriber re-test: new candidates on S2.6's answer keys, judged against Qwen (S2.7 §7.4).

Status
    One-shot (S2.7 track 2, Tasks 8-10). Subcommands, in order:
      verify  -- re-score Qwen's cached readings on S2.6's keys and require its published
                 second-pass counts exactly (free; walkthrough W7)
      run     -- every candidate on every key page at 150 dpi, instruction t1 (paid)
      pages   -- Andy's photograph and full-page-scan pages for the candidates' readings
                 that hold words (free)
      score   -- decision 0100 item 3's rule; write docs/results/s27-transcriber-retest.txt
    Reads S2.6's keys and marks under <data_dir>/s26/transcriber-test/ and never writes there;
    its own pages and CSVs are under <data_dir>/s27/transcriber-retest/. Counts only.
"""

from dataclasses import dataclass
from fractions import Fraction

QWEN = "qwen/qwen3.5-122b-a10b"
# docs/results/s26-transcriber-test-pass2.txt, Qwen's second-pass row (decision 0086).
QWEN_PASS2 = {
    "hw_lines": 1548,
    "hw_right": 1036,
    "hw_inventing": 54,
    "photo_pages": 50,
    "photo_invented": 2,
    "mixed_pages": 25,
    "mixed_invented": 0,
    "hw_pages": 25,
    "hw_format_failed": 2,
    "typed_chars": 164464,
    "typed_errors": 20219,
}
QWEN_COST_PER_PAGE = 0.00154


@dataclass(frozen=True)
class Limits:
    """Decision 0100 item 3: no worse than Qwen on invention, within 0080's margins on accuracy."""

    inventing_per_100: Fraction
    photo_invented: int
    mixed_invented: int
    format_failed: int
    hw_accuracy: Fraction
    typed_errors_per_100: Fraction
    cost_per_page: float


QWEN_LIMITS = Limits(
    inventing_per_100=Fraction(7, 2),
    photo_invented=2,
    mixed_invented=0,
    format_failed=2,
    hw_accuracy=Fraction(619, 1000),  # Qwen's 66.9% less 5 points
    typed_errors_per_100=Fraction(1329, 100),  # Qwen's 12.29 plus 1
    cost_per_page=QWEN_COST_PER_PAGE,
)


def _failures(r: CandidateResult, limits: Limits) -> list[str]:
    out: list[str] = []
    if Fraction(100 * r.hw_inventing, r.hw_lines) > limits.inventing_per_100:
        out.append(f"{r.hw_inventing} inventing lines in {r.hw_lines}")
    if r.photo_invented > limits.photo_invented:
        out.append(f"{r.photo_invented} of {r.photo_pages} photographs with invented words")
    if r.mixed_invented > limits.mixed_invented:
        out.append(f"{r.mixed_invented} of {r.mixed_pages} scans with invented added words")
    if r.hw_format_failed > limits.format_failed:
        out.append(f"{r.hw_format_failed} of {r.hw_pages} handwriting pages fail the format")
    if Fraction(r.hw_right, r.hw_lines) < limits.hw_accuracy:
        out.append(f"{r.hw_right} of {r.hw_lines} handwriting lines right")
    if Fraction(100 * r.typed_errors, r.typed_chars) > limits.typed_errors_per_100:
        out.append(f"{r.typed_errors} typed errors in {r.typed_chars} characters")
    if not r.cost_per_page < limits.cost_per_page:
        out.append(f"${r.cost_per_page:.5f} a test page, not below Qwen's")
    return out


def choose_against_qwen(results: Sequence[CandidateResult]) -> tuple[str | None, list[str]]:
    """Decision 0100 item 3: the cheapest candidate meeting all seven, or None (Qwen stays)."""
    notes: list[str] = []
    passing: list[CandidateResult] = []
    for r in results:
        failed = _failures(r, QWEN_LIMITS)
        if failed:
            notes.append(f"{r.model}: out -- " + "; ".join(failed))
        else:
            notes.append(f"{r.model}: meets all seven, ${r.cost_per_page:.5f} a test page")
            passing.append(r)
    if not passing:
        notes.append("no candidate meets all seven: Qwen stays (decision 0100 item 3)")
        return None, notes
    chosen = min(passing, key=lambda r: (r.cost_per_page, r.model))
    notes.append(f"chosen: {chosen.model}, the cheapest of {len(passing)} meeting all seven")
    return chosen.model, notes


def absolute_notes(r: CandidateResult) -> list[str]:
    """0080's absolute limits, printed beside a candidate; they decide nothing here."""
    checks = (
        ("inventing lines per 100", Fraction(100 * r.hw_inventing, r.hw_lines),
         Fraction(GATE_INVENTED_LINES_PER_100)),
        ("photographs with invented words", Fraction(r.photo_invented, r.photo_pages),
         Fraction(1, 20)),
        ("scans with invented added words", Fraction(r.mixed_invented, r.mixed_pages),
         Fraction(1, 20)),
        ("format-failed handwriting pages", Fraction(r.hw_format_failed, r.hw_pages),
         GATE_FORMAT_FAILED_SHARE),
    )
    return [
        f"  0080's limit, {name}: {float(value):.3g} against {float(limit):.3g} "
        f"({'within' if value <= limit else 'over'})"
        for name, value, limit in checks
    ]


def matches_qwen_pass2(r: CandidateResult) -> list[str]:
    """Every count of Qwen's re-scored row that differs from the published second pass."""
    return [
        f"{name} {getattr(r, name)}, published {value}"
        for name, value in QWEN_PASS2.items()
        if getattr(r, name) != value
    ]
```

(The typed limit test uses 21858 errors: `100 × 21858 / 164464 = 13.2904…`, over 13.29. Confirm the arithmetic when writing the test; if it lands on the other side, use the smallest integer over the limit, computed in the test with `Fraction`.)

Key material and `verify`:

```python
@dataclass(frozen=True)
class KeyMaterial:
    """S2.6's four keys as its second pass scored them, and Qwen's photo and scan marks."""

    keys: list[dict[str, object]]
    key_texts: dict[int, str]
    typed_answers: dict[int, str]
    qwen_photo_invented: int
    qwen_mixed_invented: int


def key_material(settings: Settings, docs: CachedDocuments, recheck: Recheck) -> KeyMaterial:
    """The keys, Andy's final handwriting key (0086), the typed answers, Qwen's marks."""
    folder = settings.data_dir / FOLDER
    keys = _read(folder / "keys.jsonl")
    pages = json.loads((folder / "handwriting.json").read_text())
    photo_sheet = json.loads((folder / "photos.json").read_text())
    mixed_sheet = json.loads((folder / "mixed.json").read_text())
    hw_first = read_marks(folder / "pass1" / "handwriting-key.csv")
    photo_first = read_marks(folder / "pass1" / "photo-words.csv")
    hw_marks, photo_marks, _header = _apply_recheck(pages, hw_first, photo_first, recheck)
    mixed_marks = read_marks(folder / "pass1" / "mixed-words.csv")
    typed_answers = {
        _int(r, "k"): page_text(docs.document(_int(r, "mkey"), _int(r, "document")), _int(r, "page"))
        for r in keys
        if r["set"] == "typed"
    }
    return KeyMaterial(
        keys=keys,
        key_texts={k: fields["key"] for k, fields in hw_marks.items()},
        typed_answers=typed_answers,
        qwen_photo_invented=sum(
            1
            for n, fields in photo_marks.items()
            if photo_sheet.get(str(n), {}).get("model") == QWEN
            and fields.get("words") == "some invented"
        ),
        qwen_mixed_invented=sum(
            1
            for n, fields in mixed_marks.items()
            if mixed_sheet.get(str(n), {}).get("model") == QWEN
            and fields.get("added words") == "some invented"
        ),
    )


def cmd_verify(settings: Settings, docs: CachedDocuments, recheck: Recheck) -> str:
    """Walkthrough W7: Qwen re-scored from the cache must equal its published second pass."""
    material = key_material(settings, docs, recheck)
    qwen = _result(
        QWEN,
        material.keys,
        material.key_texts,
        material.qwen_photo_invented,
        material.typed_answers,
        TranscriptionCache(settings.transcription_dir),
        dpi=RESOLUTION,
        mixed_invented=material.qwen_mixed_invented,
        format_gate=True,
    )
    differences = matches_qwen_pass2(qwen)
    if differences:
        raise SystemExit(
            "Qwen's re-scored counts differ from docs/results/s26-transcriber-test-pass2.txt "
            f"with the recheck CSVs {recheck.handwriting_csv.name}, {recheck.photos_csv.name}: "
            + "; ".join(differences)
        )
    return (
        f"verified: Qwen's second pass reproduced exactly from the cache with "
        f"{recheck.handwriting_csv} and {recheck.photos_csv}"
    )
```

Imports: `json`; `from collections.abc import Sequence`; `from pathlib import Path`; `from ntsb_probable_cause.docket.documents import CachedDocuments`; `from ntsb_probable_cause.docket.pages import page_text`; `from ntsb_probable_cause.docket.transcribe import TranscriptionCache`; `from ntsb_probable_cause.settings import Settings`; `from scripts.marking_page import read_marks`; and from `scripts.transcriber_test`: `FOLDER, GATE_FORMAT_FAILED_SHARE, GATE_INVENTED_LINES_PER_100, RESOLUTION, CandidateResult, Recheck, _apply_recheck, _int, _read, _result`. The project's ruff selection does not include the preview rule on private imports; `tests/test_fixtures.py` already imports a private name from a script.

`main` with `verify --handwriting-recheck PATH --photos-recheck PATH`, the docket client built offline exactly as `transcriber_test.main` builds it (`CachedDocuments(DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1))`). Makefile:

```make
s27-retest-verify:
	uv run python -m scripts.transcriber_retest verify --handwriting-recheck $(or $(HW_RECHECK),$$NTSB_DATA_DIR/s26/transcriber-test/handwriting-key-pass2.csv) --photos-recheck $(or $(PHOTO_RECHECK),$$NTSB_DATA_DIR/s26/transcriber-test/photo-words-pass2.csv)
# S2.7 walkthrough W7, free: Qwen's second pass must be reproduced exactly before any candidate
# is scored. If it fails, try HW_RECHECK=$$NTSB_DATA_DIR/s26/transcriber-test/pass2/handwriting-key-pass2-2.csv
# (and the pass2/ photo CSV); if neither pair reproduces it, stop and report.
```

- [ ] **Step 4: Run the tests and `make check`**

Run: `uv run pytest tests/test_transcriber_retest.py -v && make check`
Expected: PASS.

- [ ] **Step 5: Commit, then verify on the real keys (free)**

```bash
git add scripts/transcriber_retest.py tests/test_transcriber_retest.py Makefile docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: the re-test's rule against Qwen, and Qwen's second pass re-scored"
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
make s27-retest-verify
```
Expected: `verified: ...`. Record in Deviations which CSV pair reproduced it. **STOP** if neither pair does.

---

### Task 9: The candidates on the four keys, and Andy's pages (spec §7.4; walkthrough W3; paid)

**Files:**
- Modify: `scripts/transcriber_retest.py` (`cmd_run`, `cmd_pages`; constants `EXPECTED_COST_PER_PAGE_USD`, `RETEST_FOLDER`, `_SEED`)
- Modify: `tests/test_transcriber_retest.py`
- Modify: `Makefile` (`s27-retest-run`, `s27-retest-pages`)

**Interfaces:**
- Consumes: `scripts.transcriber_test` — `_key`, `_text`, `_int`, `_read`, `_image_head`, `_same_as`, `_against_layer`, `_GROUPED_LAYOUT`, `_PHOTO_WORDS`, `FOLDER`, `SEED`; `scripts.marking_page` — `Card`, `Choice`, `render`; `scoring.preparation.run_preparation`; `docket.transcribe.PageJob`, `TRANSCRIBE`; `gitinfo.commit_state`; `transcriber_shortlist.S27_CANDIDATES`.
- Produces: `RETEST_FOLDER = Path("s27") / "transcriber-retest"`; `EXPECTED_COST_PER_PAGE_USD = 0.003`; `word_cards(rows, texts, *, set_name, seed_base) -> tuple[dict[int, dict[str, object]], list[Card]]` (pure, tested); `cmd_run(settings, docs, *, models, retry_failed=False) -> str`; `cmd_pages(settings, docs, *, models) -> str`.

**Cost.** 200 key pages a candidate (100 typed, 25 handwriting, 50 photographs, 25 scans). Every candidate lists an input price at or below Qwen's, and Qwen measured $0.00154 a test page, so eight candidates cost at most about $2.50 (estimate); the reservation uses $0.003 a page, twice Qwen's measured cost, so a job cannot run far past its estimate (`run_preparation` stops at its reservation).

**What Andy marks** (walkthrough W3). Each photograph with no words, and each full-page scan, once, held in view, with one card per candidate reading that holds a word (as S2.6's `_photo_cards` and `cmd_mixed`). The photograph page repeats decision 0086's rule: a word of the docket's stamped "Photo" label is on the page. If Andy chose W3's alternative, `--models` is given only the candidates that pass the automatic measures (Task 10's `automatic_pass`), and `pages` is run after a first `score --automatic-only`.

- [ ] **Step 1: Write the failing test for the cards**

```python
def test_word_cards_make_one_card_per_reading_with_words_numbered_by_page() -> None:
    rows = [{"k": 1}, {"k": 2}]
    texts = {
        (1, "a/m"): "Photo 3",
        (1, "b/m"): "",
        (2, "a/m"): "[illegible]",
        (2, "b/m"): "N123AB left wing",
    }
    sheet, cards = tr.word_cards(
        rows, lambda k, model: texts[(k, model)], models=("a/m", "b/m"), seed_base=300
    )
    assert sorted(sheet) == [c.row for c in cards]
    assert {(v["k"], v["model"]) for v in sheet.values()} == {(1, "a/m"), (2, "b/m")}
    assert all(10 * int(v["k"]) < n < 10 * int(v["k"]) + 10 for n, v in sheet.items())
```

(`[illegible]` holds no word in `[A-Za-z0-9]{2,}` after the brackets are removed? It does: "illegible". S2.6's rule counted any `[A-Za-z0-9]{2,}` match, which `[illegible]` meets. Keep S2.6's rule exactly — `re.search(r"[A-Za-z0-9]{2,}", text)` — so the cards are judged as Qwen's were, and fix the test's expectation to include `(2, "a/m")` if that is what the rule gives. Write the test against the rule, not against intuition.)

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_transcriber_retest.py -k word_cards -v`
Expected: FAIL (`AttributeError: ... 'word_cards'`).

- [ ] **Step 3: Implement**

```python
RETEST_FOLDER = Path("s27") / "transcriber-retest"
# The reservation's price per page: twice Qwen's measured $0.00154; every candidate lists an
# input price at or below Qwen's (decision 0100 item 1).
EXPECTED_COST_PER_PAGE_USD = 0.003
_WORDS = re.compile(r"[A-Za-z0-9]{2,}")  # S2.6's test for "a reading with words"
_LETTERS = "ABCDEFGH"


def word_cards(
    rows: Sequence[Mapping[str, object]],
    text_of: Callable[[int, str], str],
    *,
    models: Sequence[str],
    seed_base: int,
) -> tuple[dict[int, dict[str, object]], list[Card]]:
    """One card per candidate reading holding a word; rows 10k+i, candidates shuffled per page."""
    sheet: dict[int, dict[str, object]] = {}
    cards: list[Card] = []
    for row in rows:
        k = _int(row, "k")
        order = random.Random(SEED + seed_base + k).sample(list(models), len(models))  # noqa: S311
        seen: dict[str, str] = {}
        for i, model in enumerate(order, start=1):
            text = text_of(k, model)
            if not _WORDS.search(text):
                continue
            number = 10 * k + i
            sheet[number] = {"k": k, "model": model}
            letter = _LETTERS[i - 1]
            cards.append(
                Card(
                    row=number,
                    body_html=(
                        f'<p class="meta">Page {k}, version {letter}'
                        + _same_as(seen, text, letter)
                        + f"</p><pre>{html.escape(text)}</pre>"
                    ),
                    group=str(k),
                )
            )
    return sheet, cards


def cmd_run(
    settings: Settings, docs: CachedDocuments, *, models: Sequence[str], retry_failed: bool = False
) -> str:
    """Each candidate reads every key page once at 150 dpi, instruction t1 (as S2.6's run)."""
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    out: list[str] = []
    for model in models:
        done = run_preparation(
            kind="transcriber-test",
            jobs=[
                PageJob(
                    _key(row, model, instruction=TRANSCRIBE, dpi=RESOLUTION,
                         mixed=row["set"] == "mixed"),
                    docs.loader(_int(row, "mkey"), _int(row, "document")),
                    mixed=row["set"] == "mixed",
                )
                for row in keys
            ],
            instruction=TRANSCRIBE,
            settings=settings,
            commit=commit_state(),
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD,
            workers=4,
            retry_failed=retry_failed,
        )
        failed = sum(1 for r in done if r.status == "failed")
        out.append(
            f"{model}: {len(done)} pages read, {failed} failed, "
            f"${sum(r.cost_usd for r in done):.4f}"
        )
    return "\n".join(out)
```

`cmd_pages` builds two pages under `<data_dir>/s27/transcriber-retest/` with `marking_page.render`, reusing S2.6's layout and choices:

- photographs: rows `r["set"] == "photo"`, `word_cards(..., seed_base=300)`, each card's `choices=(_PHOTO_WORDS,)`, groups `{str(k): (_image_head(f"Photograph {k}", <relative path to S2.6's pages/photo-{k}.jpg>), "")}`, intro stating the task and **0086's stamped-label rule**, `storage_key="s27-photo-words"`, `csv_name="s27-photo-words.csv"`, sheet written to `photos.json`;
- scans: rows `r["set"] == "mixed"`, `seed_base=400`, the card body built as in `transcriber_test.cmd_mixed` (the added words through `_against_layer(text, layer)`), `Choice("added words", ("all on the page and new", "repeats the text layer", "some invented"))`, the text layer shown in each group, `storage_key="s27-mixed-words"`, `csv_name="s27-mixed-words.csv"`, sheet `mixed.json`.

Because `Card` is frozen, set `choices` when building (give `word_cards` a `choices: tuple[Choice, ...]` keyword and a `body: Callable[[int, str, str], str]` keyword if the scan body differs; keep the photograph test above by passing defaults). Image paths point at S2.6's rendered `pages/` folder with a relative path from the new page (`../../s26/transcriber-test/pages/photo-{k}.jpg`), so no page image is copied.

Makefile:

```make
s27-retest-run:
	uv run python -m scripts.stage_spend --estimate 2.50
	uv run python -m scripts.transcriber_retest run
	uv run python -m scripts.transcriber_retest run --retry-failed
	uv run python -m scripts.transcriber_retest pages
# S2.7 spec §7.4, paid (estimate up to $2.50, standard price, synchronous): every candidate on
# the four keys, one retry of failed pages, then Andy's two pages under <data_dir>/s27/.

s27-retest-pages:
	uv run python -m scripts.transcriber_retest pages
# Free: rebuilds Andy's pages from the cache (marks already made reload from the browser).
```

- [ ] **Step 4: Run the tests and `make check`**

Run: `uv run pytest tests/test_transcriber_retest.py -v && make check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/transcriber_retest.py tests/test_transcriber_retest.py Makefile docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: the re-test run and Andy's marking pages"
```

- [ ] **Step 6: STOP — Andy runs the re-test (paid, up to about $2.50; 20–60 minutes) and marks the pages**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
export OPENROUTER_API_KEY="$(pass show api/openrouter)"
make s27-retest-run
open "$NTSB_DATA_DIR/s27/transcriber-retest/photos.html"
open "$NTSB_DATA_DIR/s27/transcriber-retest/mixed.html"
```
Andy downloads each page's CSV into `$NTSB_DATA_DIR/s27/transcriber-retest/`. Record the run's printed costs in Deviations.

---

### Task 10: The score, and the results file (spec §7.4–§7.5; decision 0100 item 3; free)

**Files:**
- Modify: `scripts/transcriber_retest.py` (`cmd_score`, `automatic_pass`)
- Modify: `tests/test_transcriber_retest.py`
- Modify: `Makefile` (`s27-retest-score`)
- Create (by running): `docs/results/s27-transcriber-retest.txt`

**Interfaces:**
- Consumes: Task 8's `key_material`, `choose_against_qwen`, `absolute_notes`, `QWEN_LIMITS`; Task 9's sheets; `transcriber_test._result`, `_reading_counts`.
- Produces: `automatic_pass(r: CandidateResult) -> bool` (the four measures that need no marks, and cost); `cmd_score(settings, docs, recheck, photos_csv, mixed_csv, *, models) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def test_automatic_pass_ignores_the_marked_measures() -> None:
    assert tr.automatic_pass(_result("a/m", photo_invented=9, mixed_invented=9))
    assert not tr.automatic_pass(_result("a/m", hw_inventing=60))


def test_score_refuses_an_unmarked_card(tmp_path: Path) -> None:
    sheet = {"11": {"k": 1, "model": "a/m"}}
    marks = {11: {"words": ""}}
    with pytest.raises(SystemExit, match="unmarked"):
        tr.invented_by_model(sheet, marks, field="words", invented="some invented")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_transcriber_retest.py -k "automatic or unmarked" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def automatic_pass(r: CandidateResult) -> bool:
    """Walkthrough W3's alternative: every measure that needs no marks, and cost."""
    unmarked = CandidateResult(**{**r.__dict__, "photo_invented": 0, "mixed_invented": 0})
    return not _failures(unmarked, QWEN_LIMITS)


def invented_by_model(
    sheet: Mapping[str, Mapping[str, object]],
    marks: Mapping[int, Mapping[str, str]],
    *,
    field: str,
    invented: str,
) -> Counter[str]:
    """Cards marked ``invented``, by model; every card on the sheet must be marked."""
    if any(marks.get(int(n), {}).get(field, "") == "" for n in sheet):
        raise SystemExit(f"some cards are unmarked ({field})")
    return Counter(
        str(sheet[str(n)]["model"])
        for n, fields in marks.items()
        if str(n) in sheet and fields.get(field) == invented
    )


def cmd_score(  # noqa: PLR0913 -- the key material's recheck pair and the two new CSVs.
    settings: Settings,
    docs: CachedDocuments,
    recheck: Recheck,
    photos_csv: Path,
    mixed_csv: Path,
    *,
    models: Sequence[str],
) -> str:
    """Decision 0100 item 3 over the candidates; Qwen's published row printed as the bar."""
    material = key_material(settings, docs, recheck)
    folder = settings.data_dir / RETEST_FOLDER
    photos = invented_by_model(
        json.loads((folder / "photos.json").read_text()),
        read_marks(photos_csv),
        field="words",
        invented="some invented",
    )
    mixed = invented_by_model(
        json.loads((folder / "mixed.json").read_text()),
        read_marks(mixed_csv),
        field="added words",
        invented="some invented",
    )
    cache = TranscriptionCache(settings.transcription_dir)
    results = [
        _result(
            m,
            material.keys,
            material.key_texts,
            photos[m],
            material.typed_answers,
            cache,
            dpi=RESOLUTION,
            mixed_invented=mixed[m],
            format_gate=True,
        )
        for m in models
    ]
    chosen, notes = choose_against_qwen(results)
    lines = [
        "# the transcriber re-test (S2.7 spec §7.4, decision 0100) -- counts only",
        f"keys: S2.6's four (docs/results/s26-transcriber-test-pass2.txt); 150 dpi; instruction "
        f"t1; decision 0086's corrections; handwriting recheck {recheck.handwriting_csv.name}",
        "the bar: Qwen3.5 122B's second pass, reproduced from the cache (Task 8): 1036 of 1548 "
        "handwriting lines right, 54 inventing lines, 2 of 50 photographs, 0 of 25 scans, "
        "2 of 25 format-failed pages, 12.29 typed errors per 100 characters, $0.00154 a page",
        "",
    ]
    for r in results:
        lines += [
            f"## {r.model} (measured ${r.cost_per_page:.5f} per test page)",
            f"  invented: {r.hw_inventing} lines ({float(r.invented_per_100_lines):.1f} per 100 "
            f"handwriting lines); {r.photo_invented} of {r.photo_pages} photographs",
            f"  handwriting lines right: {r.hw_right} of {r.hw_lines} ({r.hw_accuracy:.1%})",
            f"  typed errors: {float(r.typed_errors_per_100):.2f} per 100 characters",
            f"  full-page scans: invented added words on {r.mixed_invented} of {r.mixed_pages}",
            f"  format-failed handwriting pages: {r.hw_format_failed} of {r.hw_pages}",
            *absolute_notes(r),
        ]
    lines += ["", "## the rule (decision 0100 item 3, fixed before the run)", *notes]
    return "\n".join(lines)
```

(`CandidateResult`'s property names — `invented_per_100_lines`, `hw_accuracy`, `typed_errors_per_100` — are as listed in `scripts/transcriber_test.py:182-225`; check their return types (Fraction or float) and format accordingly. `automatic_pass` uses `dataclasses.replace(r, photo_invented=0, mixed_invented=0)` if `CandidateResult` is a frozen dataclass, which it is: prefer `replace` to `__dict__`.)

Add `score --handwriting-recheck --photos-recheck --photos --mixed --out` to `main`, with `models=S27_CANDIDATES`. Makefile:

```make
s27-retest-score:
	uv run python -m scripts.transcriber_retest score --handwriting-recheck $(or $(HW_RECHECK),$$NTSB_DATA_DIR/s26/transcriber-test/handwriting-key-pass2.csv) --photos-recheck $(or $(PHOTO_RECHECK),$$NTSB_DATA_DIR/s26/transcriber-test/photo-words-pass2.csv) --photos $$NTSB_DATA_DIR/s27/transcriber-retest/s27-photo-words.csv --mixed $$NTSB_DATA_DIR/s27/transcriber-retest/s27-mixed-words.csv --out docs/results/s27-transcriber-retest.txt
# S2.7 spec §7.4, free: decision 0100 item 3 applied; the CSV pair is the one Task 8 verified.
```

- [ ] **Step 4: Run the tests, `make check`, commit the code**

```bash
uv run pytest tests/test_transcriber_retest.py -v && make check
git add scripts/transcriber_retest.py tests/test_transcriber_retest.py Makefile docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: the re-test's score against Qwen"
```

- [ ] **Step 5: Score (free) and commit the results file**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
make s27-retest-score
git add docs/results/s27-transcriber-retest.txt docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: re-test results"
```

---

### Task 11: The decision record (number 120), and the rule and transcriber in force (spec §7.5)

**Files:**
- Create: `docs/decisions/<the number 120, zero-padded to four digits>-<title>.md`
- Modify: `docs/decisions/README.md` (its index row)
- Modify, only if the outcome changes them: `src/ntsb_probable_cause/docket/transcribe.py` (`TRANSCRIBER`, `PAGE_RULE` and their comments); `tests/test_docket_transcribe.py` (`test_the_rule_in_force_is_s26s_until_a_decision_changes_it`, renamed to state the new rule)

**What the record says.** Context: the three results files (page value, shortlist with probe, re-test), with their numbers quoted from the files. Decision: (1) the transcriber — the re-test's chosen model, or "Qwen3.5 122B stays"; (2) the page rule — T3's chosen rule; (3) that `dev-400` is re-read with them at the meeting point (spec §8 step 1) with `ntsb-eval transcribe --model <m> --page-rule <r>`, and that v2 runs record both (track 1). Why, and What this rules out, in the house format; Status: Accepted with Andy's words.

- [ ] **Step 1: STOP — bring Andy the three results, one decision per message** (the transcriber, then the page rule), in simplified English with a glossary, as the project's memory asks.
- [ ] **Step 2: Write the record and its index row** with Andy's decisions verbatim in Status. It cites decisions 0080, 0086, 0087 and 0100, and no number above 0100 except its own.
- [ ] **Step 3: If the transcriber or the rule changes, set the constants in the same commit**

```python
# S2.7 track 2 decision record (number 120): <one line why>. Changed from qwen/qwen3.5-122b-a10b
# (decision 0087, provisional).
TRANSCRIBER = "<chosen model>"
PAGE_RULE: PageRule = "<chosen rule>"
```

After this, `ReadingLookup().is_done("dev-400")` is false until the meeting point re-reads `dev-400`, which is correct: a v2 run must not read S2.6's evidence under the new name. S2.6's readings stay in the cache under their own keys, and S2.6's results stay citable.

- [ ] **Step 4: `make check` and `uv run python -m scripts.check_docs`, then commit**

```bash
make check && uv run python -m scripts.check_docs
git add docs/decisions src/ntsb_probable_cause/docket/transcribe.py tests/test_docket_transcribe.py docs/plans/2026-09-26-s27-track2-transcriber.md
git commit -m "S2.7 track 2: decision record 120, the transcriber and the page rule"
```

---

### Task 12: Merge back into the stage branch (spec §11)

- [ ] **Step 1: Bring the stage branch in and re-check**

```bash
git fetch origin
git merge origin/s27-coding-guidance   # resolve Makefile, sources.py, decisions index by keeping both sides
make check && uv run python -m scripts.check_docs
git push
```

- [ ] **Step 2: STOP — Andy's go-ahead to merge back.** Report: the decision record, the three results files, what changed in `transcribe.py`, `sources.py` and `apps/eval`, and the track's spend (`uv run python -m scripts.stage_spend --estimate 0`).

- [ ] **Step 3: Merge with a merge commit, from the stage branch's worktree**

```bash
cd /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/.claude/worktrees/s27-coding-guidance
git fetch origin
git merge --no-ff origin/s27-transcriber -m "Merge s27-transcriber (track 2) into s27-coding-guidance"
make check && uv run python -m scripts.check_docs
git push
```

This plan stays in `docs/plans/` until the stage closes; the close-out deletes it with track 1's (decision 0017).

---

## Deviations

*Log every departure from the specification here, dated, with the reason. Moved into the As-built record at close-out (decision 0017).*
