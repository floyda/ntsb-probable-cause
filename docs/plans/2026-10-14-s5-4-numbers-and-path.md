# S5 step 4 — The numbers file and the Path page: implementation plan

**Spec:** docs/specs/2026-10-04-s5-public-site-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Andy's choice for S5: Claude runs the tasks in the session, one fresh review at the end). Steps use checkbox (`- [ ]`) syntax. Tick a step in the same commit as its code (decision 0017). Log every departure in **Deviations**. Tasks marked **Controller** need Andy.

**Goal:** Step 4 of §21. First, the numbers file (§17.3): a Python script writes `site/data/numbers.json` from the committed results files, and CI fails if the file is stale. Then the Path page (§7) at `/path/`:
- the ladder (§7.1);
- the eight questions (§7.2), each with its measured answer, the decision taken, its links and, where §7.4's figure needs no new analysis, its figure;
- what could come next (§7.3).

The first page's caveat is tied to the numbers file, and the first page links to Path. Nothing new is published.

**Out of this step, to step 4b:** three figures of §7.4 need new analysis scripts:
- question 1's published development case;
- question 6's one sentence with many first codes, a new development-only script;
- question 7's beliefs against the NTSB's first code, a new script over S3.2's trails on Andy's Mac.

Their stops carry their measured answers in this step and gain their figures in 4b.

**Architecture:**
- **The numbers script.** `scripts/site_numbers.py` reads only committed `docs/results/*.txt` files. Each number has one small extractor that finds exactly one line by a fixed pattern and fails loudly otherwise. It writes the numbers file, in which every entry names its value, interval, count, sample, model, run, results file and script. Because the inputs are all committed, CI can re-run the script, and a pytest test fails if the committed file differs from a fresh run. This is stronger than §19.2's planned consistency check, which assumed some numbers needed run folders. S3.2's bootstrap has already recomputed the one interval that did: `s32-claims-heldout.txt` gives the no-docket step's top-1 as 15.0% [11.5%, 18.5%].
- **The site.** `site/src/lib/numbers.ts` loads the file and formats an entry by its key. Pages never type a number.
- **The ladder.** It is drawn at build time as SVG from a pure layout function, with a data table behind it.

**Tech Stack:** Python 3.14 with pydantic (already a dependency) for the script; the site as before, with no new package.

## Global Constraints

- **The step 1–3 constraints hold.**
- **No number is typed into a page** (§17.3). Path and the caveat take every figure from `numbers.json` by key. A Vitest test fails if a page source under `site/src/pages/` or `site/src/components/` holds a percentage or dollar literal (`\d%` or `\$\d`).
- **Every reported number comes from a script** (rule 3). Each entry's `results_file` exists, its `script` exists in the repository, and its value is read from that file by the extractor. Nothing is copied by hand.
- **Held-out and live never share a figure** (§9, decision 0021). The ladder is held-out only; the noise-floor band is development and goes to question 7's text, not the ladder (§7.1); question 8's strip is live only.
- **Every score carries its interval and count** (§12 item 9). Costs show billed only (Andy, 2026-10-14, superseding §7.1's list price and billed; see Deviations).
- **Links:** each question links its results file and script on GitHub (`https://github.com/floyda/ntsb-probable-cause/blob/main/<path>`; every path checked to exist). Methods links come in step 5 (the step 2 rule: no link to a page not yet built).
- **Wording:** the measured answers are §7.2's approved text, with every number replaced by its key. "Points" is never used on the first page (Andy, 2026-10-05). Path may say "points", with Methods (step 5) defining it.

## Review Focus

1. **A results file regenerated with a changed number.** The numbers file must change with it, and CI must fail until the file is regenerated, rather than the site quoting the old value. Pinned by Task 1's staleness test.
2. **A results file whose wording changed so that a pattern no longer matches.** The script must fail naming the entry and the file, never write a partial file. Pinned by Task 1.
3. **The caveat's "about one case in four" and "about one case in three" after a re-run moves the rates.** The build must fail when the phrase no longer fits the numbers. Pinned by Task 2's caveat test.
4. **The ladder's labels at phone width.** No label overlaps another or leaves the drawing, and the page does not scroll sideways. Pinned by the phone-width check and Task 3's geometry tests.
5. **Question 2's claim "no better than guessing".** It must hold because the no-docket interval contains the baseline rate, and be tested as such, so a re-run that changes this fails the build. Pinned by Task 2.

## File map

| file | responsibility |
|---|---|
| `scripts/site_numbers.py`, `tests/test_site_numbers.py` | the numbers script and its tests (Task 1) |
| `site/data/numbers.json` | the numbers file, committed (Task 1) |
| `Makefile` (`site-numbers`) | regenerates it (Task 1) |
| `site/src/lib/numbers.ts`, `site/src/lib/numbers.test.ts` | loading and formatting by key; the caveat and question 2 checks (Task 2) |
| `site/src/lib/ladder.ts`, `site/src/lib/ladder.test.ts`, `site/src/components/Ladder.astro` | the ladder's layout and drawing (Task 3) |
| `site/src/pages/path.astro`, `site/src/components/PathStop.astro`, `site/src/components/ClosuresStrip.astro` | the Path page, a question's stop, question 8's strip (Task 4) |
| `site/src/pages/index.astro` | the caveat from the numbers file; a link to Path (Task 2, Task 4) |
| `site/tests/dist.test.ts` | Path checks over the built page (Task 5) |

## The entries

Keys, the line each is read from (the results file's own wording), and the script that wrote that file. The extractor patterns are fixed in Task 1 against these exact lines.

| key | file | line read (abridged) | script |
|---|---|---|---|
| `ladder.baseline.top1` | `s1-baseline.txt` | `Honest baseline (... n=4241): top-1 17.7% [16.6%, 18.9%]` | `apps/eval` (`ntsb-eval baseline`) |
| `ladder.no_docket.top1` | `s32-claims-heldout.txt` | `the loop without the docket top-1: 15.0% [11.5%, 18.5%], n=400` | `scripts/s32_claims.py` |
| `ladder.fixed.top1` | `s32-heldout-diagnosis.txt` | `arm B check top-1: 33.0% [28.5%, 37.5%], n=400` | `scripts/exploratory/s32_heldout_diagnosis.py` |
| `ladder.loop.top1` | `s32-heldout-diagnosis.txt` | `the loop top-1: 23.5% [19.2%, 27.5%], n=400` | as above |
| `ladder.no_docket.cost` | `s32-claims-heldout.txt` | `cases=400 total_cost_usd=0.9774` under `[the loop without the docket]` | `scripts/s32_claims.py` |
| `ladder.fixed.cost`, `ladder.fixed.billed` | `s32-claims-heldout.txt` | `arm B computed 2.3439 USD`; `arm B billed 2.1347 USD` | as above |
| `ladder.loop.cost`, `ladder.loop.billed` | `s32-claims-heldout.txt` | `loop billed 2.0610 USD, computed 3.9270 USD` | as above |
| `q3.docket_gain` | `s24-bars.txt` | `- occurrence top-1: +14.3% [+9.2%, +19.3%] on n=336 cases` | `apps/eval` (`ntsb-eval report`) |
| `q4.v2_gain` | `s26-armB-v2-dev.txt` | B-v2 minus B-v1 occurrence top-1, paired | `apps/eval` (`ntsb-eval report`) |
| `q4.pages.*` | `s26-page-kinds.txt` | the page-kind totals (text only, image only, text and image, total) | `scripts/page_kinds.py` |
| `q5.first_right`, `q5.in_sequence` | `s26-occurrence-misses-dev.txt` | `88 of 399 (22.1%)`; `140 of 399 (35.1%)` | `scripts/occurrence_misses.py` |
| `q5.pairs` | `s26-occurrence-misses-dev.txt` | the commonest miss pairs (count, NTSB first, agent first), top five | as above |
| `q6.twins` | `s3-coding-consistency-dev.txt` | `six-digit first code: 619 of 1650 (37.5%) [35.2%, 39.9%]` | `scripts/exploratory/s3_coding_consistency.py` |
| `q7.loop_vs_fixed` | `s32-heldout-diagnosis.txt` | `top-1, loop - arm B check: -9.5 points [-14.0, -5.2], n=400` | `scripts/exploratory/s32_heldout_diagnosis.py` |
| `q7.loop_vs_answer` | as above | `top-1, loop - arm B answer: -4.2 points [-8.5, +0.0], n=400` | as above |
| `q7.no_docket_loss` | `s32-claims-heldout.txt` | the without-minus-with top-1 difference and its interval | `scripts/s32_claims.py` |
| `q7.read_all` | `s32-claims-heldout.txt` | result 1's "read every document on offer on 245 of 375" | as above |
| `q7.noise_band` | `s3-noise-floor-dev.txt` | the paired top-1 difference between the two identical runs | `scripts/s3_noise_floor.py` |

Where the abridged line above is not the file's exact wording, Task 1 matches the file and logs it. Each entry also records `sample` (`heldout-400`, `dev-400`, the development pool or all held-out) and `model` (`openai/gpt-6-luna`, or `none` for the baseline and the pool counts).

---

## Task 1: The numbers script

**Files:** Create `scripts/site_numbers.py`, `tests/test_site_numbers.py`, `site/data/numbers.json`. Modify `Makefile` (`site-numbers`), `pyproject.toml` only if a lint rule needs a per-file setting.

**Interfaces — Produces:**
- `Entry` (pydantic, frozen): `value: float`, `low: float | None`, `high: float | None`, `n: int | None`, `unit: Literal["percent", "points", "usd", "count"]`, `sample: str`, `model: str`, `run: str | None`, `results_file: str`, `script: str`, `label: str`.
- `Numbers`: `format: Literal["site-numbers/1"]`, `entries: dict[str, Entry]`, `lists: dict[str, list[dict[str, str | int]]]` (for `q5.pairs`).
- `build(results_dir: Path) -> Numbers`; `main()` with `--check` (exit 1 and name the first differing key when `site/data/numbers.json` differs from `build`).
- `ExtractError(entry key, file, pattern)`, raised when a pattern matches zero or several lines.

- [x] **Step 1: Write the failing tests** — `tests/test_site_numbers.py`:

```python
"""The site's numbers file (S5 spec §17.3): every number from a committed results file."""

import json
from pathlib import Path

import pytest

from scripts import site_numbers

_REPO = Path(__file__).resolve().parents[1]
_RESULTS = _REPO / "docs/results"


def test_reads_the_ladder_from_the_committed_results() -> None:
    numbers = site_numbers.build(_RESULTS)
    loop = numbers.entries["ladder.loop.top1"]
    assert (loop.value, loop.low, loop.high, loop.n) == (23.5, 19.2, 27.5, 400)
    assert loop.results_file == "docs/results/s32-heldout-diagnosis.txt"
    baseline = numbers.entries["ladder.baseline.top1"]
    assert (baseline.value, baseline.low, baseline.high, baseline.n) == (17.7, 16.6, 18.9, 4241)
    no_docket = numbers.entries["ladder.no_docket.top1"]
    assert (no_docket.value, no_docket.low, no_docket.high) == (15.0, 11.5, 18.5)
    assert numbers.entries["ladder.loop.billed"].value == pytest.approx(2.0610)
    assert numbers.entries["ladder.fixed.cost"].value == pytest.approx(2.3439)


def test_every_entry_names_a_file_and_script_that_exist() -> None:
    for key, entry in site_numbers.build(_RESULTS).entries.items():
        assert (_REPO / entry.results_file).is_file(), key
        script = entry.script.split(" ")[0]
        assert (_REPO / script).exists(), key


def test_the_committed_numbers_file_is_current() -> None:
    # Review Focus 1: a re-run results file must be followed by a regenerated numbers file.
    committed = json.loads((_REPO / "site/data/numbers.json").read_text())
    assert committed == json.loads(site_numbers.build(_RESULTS).model_dump_json())


def test_a_missing_line_fails_loudly_naming_entry_and_file(tmp_path: Path) -> None:
    # Review Focus 2.
    for f in _RESULTS.glob("*.txt"):
        (tmp_path / f.name).write_text(f.read_text())
    target = tmp_path / "s32-heldout-diagnosis.txt"
    target.write_text(target.read_text().replace("the loop top-1:", "the agent top-1:"))
    with pytest.raises(site_numbers.ExtractError, match=r"ladder\.loop\.top1.*s32-heldout-diagnosis"):
        site_numbers.build(tmp_path)


def test_a_changed_number_is_read_as_changed(tmp_path: Path) -> None:
    for f in _RESULTS.glob("*.txt"):
        (tmp_path / f.name).write_text(f.read_text())
    target = tmp_path / "s32-heldout-diagnosis.txt"
    target.write_text(target.read_text().replace("the loop top-1: 23.5%", "the loop top-1: 24.0%"))
    assert site_numbers.build(tmp_path).entries["ladder.loop.top1"].value == 24.0
```

Run: `uv run pytest tests/test_site_numbers.py --no-cov -q` — Expected: FAIL (module missing).

- [x] **Step 2: Write the script.** It has one extractor per entry in **The entries** table: a compiled pattern, a file name, and the fields the match fills. `_one(path, pattern, key)` returns the single match or raises `ExtractError`. A section-aware read (for `[the loop without the docket]`'s cost) finds the section header first and then the next `cases=` line. The script carries a `Status` paragraph (decision 0059) saying it reads committed results only and computes nothing. It prints nothing but the path written, or the first stale key under `--check`. It writes JSON with sorted keys and a trailing newline.
- [x] **Step 3: Generate and test** — `uv run python -m scripts.site_numbers && uv run pytest tests/test_site_numbers.py --no-cov -q` — Expected: 5 passed.
- [x] **Step 4: The make target** — `site-numbers: uv run python -m scripts.site_numbers`. (CI needs no new job: pytest's staleness test is the check.)
- [x] **Step 5:** `make check` — Expected: green (ruff, mypy strict, vulture and deptry over the new script).
- [x] **Step 6: Commit** — `S5 step 4 Task 1: the numbers script and file, from committed results only`.

---

## Task 2: Numbers on the site

**Files:** Create `site/src/lib/numbers.ts`, `site/src/lib/numbers.test.ts`. Modify `site/src/pages/index.astro`.

**Interfaces — Produces:** `numbers()` (reads and checks `site/data/numbers.json`, throwing on a missing or malformed file); `entry(key): Entry` (throws on an unknown key, so a typo fails the build); `pct(key)` "23.5%"; `withInterval(key)` "23.5% [19.2%, 27.5%], 400 cases"; `points(key)` "−9.5 points [−14.0, −5.2]"; `usd(key)` "$2.06"; `oneIn(key)` "one case in four" (the nearest of one in two to one in ten); `containsValue(rangeKey, valueKey): boolean`.

- [x] **Step 1: Failing tests** for each formatter on the real file, and:
  - **The caveat** (Review Focus 3): `oneIn("ladder.loop.top1") === "one case in four"` and `oneIn("ladder.fixed.top1") === "one case in three"`.
  - **Question 2** (Review Focus 5): `containsValue("ladder.no_docket.top1", "ladder.baseline.top1") === true`.
  - **No typed numbers:** no file under `site/src/pages` or `site/src/components` matches `/\d%|\$\d/`.

  Run them and watch them fail.
- [x] **Step 2: Implement** `numbers.ts`. Signs use the true minus sign (−) and a plus for gains. Percentages keep one decimal, as the results files do.
- [x] **Step 3: The caveat.** In `index.astro`, "On {entry n} accidents it had never seen, its first code matched the investigator's in about {oneIn(loop)}. The fixed method matched in about {oneIn(fixed)}." The rest of §3.1's wording is unchanged. The step 2 deviation that typed these numbers is closed.
- [x] **Step 4: Run** — `pnpm --dir site run test && pnpm --dir site run build && pnpm --dir site run lint && pnpm --dir site run check`.
- [x] **Step 5: Commit** — `S5 step 4 Task 2: numbers on the site by key; the caveat from the numbers file`.

---

## Task 3: The ladder

**Files:** Create `site/src/lib/ladder.ts`, `site/src/lib/ladder.test.ts`, `site/src/components/Ladder.astro`.

**Interfaces — Produces:** `ladderLayout(steps: LadderStep[], width: number): LadderGeometry`. Here `LadderStep` is `{ key, label, plain, rate, cost | null, billed | null }` (keys into the numbers file), and the geometry gives each bar's x, width and y, its whisker's two x values, the baseline line's x, the label positions and the drawing's height.

The four steps, in order (§7.1): "1. No model · always guess the commonest code"; "2. The case record only · the agent with the recorded facts, no documents"; "3. Every document, fixed order · the fixed pipeline"; "4. Choosing what to read · the loop, version 1".

- [x] **Step 1: Failing geometry tests:**
  - every bar starts at x = 0 of the plot;
  - a bar's length is proportional to its value on one scale, from 0 to the largest whisker high rounded up to the next 10%;
  - every whisker lies inside the plot;
  - the baseline line sits at the baseline's value;
  - at a width of 340 no two labels overlap and every label sits inside the width.
- [x] **Step 2: Implement** `ladderLayout`, horizontal bars with labels above each bar, so phone width needs no rotated text.
- [x] **Step 3: `Ladder.astro`.** Props: `lit` (which steps are lit; the rest are dimmed, for questions 2 and 3, §7.4), `width` (default 640). It renders:
  - an inline `<svg>` with `role="img"` and an `aria-label` stating the result;
  - each bar, its whisker, its value with interval as text, and its cost as "list $2.34 · billed $2.13" (step 1: "no model cost");
  - the faint baseline line labelled "always guessing";
  - a visually hidden `<table>` with the same figures, so a screen reader reads the data (§12 item 8);
  - beneath it, the plain sentence: "A step up in machinery is not a step up in result: the loop matched the investigator's first code less often than the fixed pipeline, at about the same bill." Its rates come from the numbers file.

  Colours are theme tokens. No colour marks good or bad (§11).
- [x] **Step 4: Run** the tests and build; commit — `S5 step 4 Task 3: the ladder, drawn at build time from the numbers file`.

---

## Task 4: The Path page

**Files:** Create `site/src/pages/path.astro`, `site/src/components/PathStop.astro`, `site/src/components/ClosuresStrip.astro`. Modify `site/src/pages/index.astro` (a link: "How the project decided what to build: the Path").

- [x] **Step 1: `PathStop.astro`.**
  - **Props:** `id` (the short anchor, §12 item 12), `n`, `question`, `answer` (a slot), `decision`, `results` (paths) and `scripts` (paths).
  - **It renders:** a `<section id>` with the question as an `h2` ("1. Is there an answer key nobody had to write?"); the answer, the decision, and a slot for the figure; then a sources line "Results: <file> · Script: <file>", linked to GitHub.
- [x] **Step 2: `path.astro`.** The page reads, top to bottom:
  1. **The ladder,** all steps lit.
  2. **The eight stops.** Each answer is §7.2's text, with its numbers from the file, and §7.4's figure where this step builds it.
     - `#answer-key` (Q1): text only (figure in 4b).
     - `#case-record` (Q2): the ladder with steps 1 and 2 lit. The answer says "no better than guessing", which is true by `containsValue`.
     - `#docket` (Q3): the ladder with step 3 lit; `q3.docket_gain`.
     - `#scanned-pages` (Q4): `q4.v2_gain`, and a small bar of `q4.pages.*` page kinds with its data table.
     - `#coding` (Q5): `q5.first_right` and `q5.in_sequence`, and a table of `q5.pairs`.
     - `#consistency` (Q6): `q6.twins`, and the results file's own caution; figure in 4b.
     - `#choosing` (Q7): `q7.*` and the run-twice band `q7.noise_band`, labelled as development cases (§7.1); figure in 4b.
     - `#newly-closed` (Q8): `ClosuresStrip` from the export.
  3. **"What could come next"** (§7.3): its four candidates, as plain text.

  The page title is "The path · Ellery".
- [x] **Step 3: `ClosuresStrip.astro`.** One mark per closed case in closure order, using the board's `Mark` shapes and words. It reads "Since 23 Sep 2026: {totalsLine}", has a data table behind it, and is drawn from the export only (§7.4). It never shows a percentage (§12 item 10).
- [x] **Step 4: Build and run** every site check. The internal-link check covers `/path/` and its anchors. The phone-width and axe checks cover the new page.
- [x] **Step 5: Commit** — `S5 step 4 Task 4: the Path page: the ladder, eight questions, what could come next`.

---

## Task 5: Checks over the Path page

**Files:** Modify `site/tests/dist.test.ts`.

- [x] **Step 1:**
  - `/path/` holds every question's anchor;
  - every number entry the page uses appears in its text, formatted as `numbers.ts` formats it;
  - every GitHub link on the page points to a path that exists in the repository;
  - the ladder's data table holds all four steps.
- [x] **Step 2: Prove they can fail:** remove an anchor, alter a value in a built page, and point a link at a missing file. Then restore with a clean build.
- [x] **Step 3:** `make check`; commit — `S5 step 4 Task 5: checks over the Path page`.

---

## Task 6: Preview (Controller)

- [ ] **Step 1:** Screenshots of `/path/` at 390 × 844 and 1280 × 900, in light and dark, and of the first page's caveat. Look at each.
- [ ] **Step 2:** Send them to Andy with the choices for his eye:
  - the ladder's drawing and its cost labels;
  - the sentence under the ladder;
  - each question's answer and decision as worded;
  - question 4's page-kind bar, question 5's pairs table, and question 8's strip;
  - the "What could come next" list.
- [ ] **Step 3:** Record his answers; run the final review and its fix pass; push.

---

## Deviations

- **Task 1 (2026-10-14): how the entries are read.**
  - Counts are stored as counts, not as rates: `q5.first_right` is 88 with `n` 399, `q5.in_sequence` 140 of 399, and `q7.read_all` 245 of 375. The page prints "88 of 399", so nothing is rounded twice.
  - `q4.pages.*` also holds `blank` (109), so the page-kind bar adds up to `total` (16,790).
  - Some lines appear more than once in a file. These are read inside one section: a header line found exactly once, ending at a blank line, a `[name]` block, a heading or the next block's header line.
    - `q3.docket_gain`: under `against …-heldout-400-ceiling:` in `s24-bars.txt`, which holds three paired top-1 lines.
    - `q4.v2_gain`: under the evidence-version comparison.
    - `q7.noise_band`: under the overall `paired difference` header, not its fatal and non-fatal blocks.
    - `q4.pages.*`: under `## pages by kind`, not the photo-only section.
  - `q7.no_docket_loss` is `no-docket - loop, top-1: -8.5 points [-13.0, -3.8], n=400`, which is without minus with.
  - `run` is filled only where the file names exactly one run behind the figure. A paired figure, arm B's three-part cost and the pool counts carry `null`.
- **Task 1: two tests beyond the plan's five.** A line matched twice fails. `first_difference`, behind `--check`, names the first stale key.
- **Task 2 (2026-10-14): more formatters, and a refusal.**
  - `count` ("16,790"), `countOf` ("88 of 399"), `caseCount` (an entry's `n`, for the caveat's "400 accidents", which was also typed) and `list` (question 5's pairs) are added to the plan's set.
  - `oneIn` refuses a rate more than a fifth away from the nearest "one in N", so a re-run that moves the rate to, say, 41% fails the build instead of printing "about one case in three". This is Review Focus 3, stated as a rule rather than as today's two values only.
  - The no-typed-number test also reads `src/layouts`, and it strips `<style>` blocks, where `width: 100%` is not a figure.
- **Task 3 (2026-10-14): two drawings, and a dashed mark per bar.**
  - The ladder is laid out twice, at 340 and 640, and CSS shows one by screen width. One drawing scaled to fit a phone would shrink its text to about half size.
  - The always-guessing line is drawn as a short dashed mark across each bar, not one line through the whole figure, so it never crosses a label. Its label, "dashed mark: always guessing", sits in its own row under the axis.
  - Text widths are estimated (0.6 em a character, 0.64 bold) to wrap and test the labels. Task 5 adds a check of the rendered boxes in the browser, so a wrong estimate fails there.
  - The sentence under the ladder also gives the two rates and the two bills. If a re-run put the loop level with or above the fixed pipeline, the sentence would change to a plain statement of both rates rather than keep claiming "not a step up".
  - The colour tokens `--bar` and `--bar-dim` are added for both themes.
- **Task 4 (2026-10-14): the page as built.**
  - Question 4's page-kind bar is its own component, `PageKinds.astro`, not in the file map. It refuses to build if the four kinds do not add up to the total.
  - `Mark` gains `bare` (the shape alone) for question 8's strip, whose words are in a table under a disclosure.
  - `repoUrl` in `words.ts` builds every GitHub link. A folder (`apps/eval/`, `docs/rounds/`) links as a tree, a file as a blob.
  - The ladder's hidden table is wrapped in a hidden `div`. A table ignores the 1px width of `.vh`, so the phone page had grown to 1,226px wide; the phone check caught it.
  - **Wording beyond §7.2:**
    - Q4: "far more than answering" stands in for decision 0120's "about ten times", which is not in the numbers file.
    - Q7: the no-docket figure is worded as "the same loop without it was −8.5 points … on the first code", because "lost −8.5" reads as a double negative.
    - Q1, Q6 and Q8 have decisions written for the page. §7.2 gives answers, not decisions. They are for Andy's preview.
  - **Sources:** Q1 links `s1-bars.txt` and the eval harness, the first scoring against the NTSB's codes. Q8 has no results file, since its figure is the export.
- **Task 5 (2026-10-14): wider than planned.**
  - "Every number entry the page uses" became every entry in the numbers file: each must appear on `/path/` in its unit's format. A figure added to the file but never shown fails too.
  - A GitHub link must name a folder as a tree and a file as a blob.
  - A browser check in `a11y.spec.ts` (all three projects) measures the ladder's rendered labels with `getBBox`. It confirms they stay inside the shown drawing and never overlap, and that three drawings were checked.
  - **Proved able to fail** on a built page:
    - a removed anchor (`#coding`);
    - an altered value (−9.6 for −9.5);
    - a link to a missing script;
    - every title moved outside its drawing.
  - Each failed. A clean build passes again.
- **Task 6 (2026-10-14), Andy's preview, choice 1: billed costs only.** "Our estimate list cost is there for budgeting, what gets charged is what matters."
  - `ladder.*.cost` (list price) leave the numbers file; a test keeps any `.cost` entry out.
  - The ladder's cost line reads "billed $2.06". Step 1 reads "no model cost". Step 2 reads "bill not recorded", because S3.2's claims file holds only its list price.
  - Question 7 drops the list-price figures and the clause "only through the provider's discount on cached prompts", which needs them. It reads "Its bill was about the same: $2.06 against the pipeline's $2.13."
  - The spec's §7.1 has a dated note.
