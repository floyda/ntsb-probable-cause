# Coding memory: every embedding lookup goes to the coding test (decision 0214) — plan

> **For agentic workers:** executed inline (superpowers:executing-plans), one independent review
> of the whole branch before any paid run. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** docs/specs/2026-10-08-coding-memory-design.md

The section is §13.13 (decision 0214; Andy approved every run the confirmation needs, 2026-10-18).

**Goal:** send the four embedding lookups the review named to the coding test on the steering
slice, pick one by the registered rule of 0213, and confirm it once on `dev-seal-400`.

**Architecture:** two new candidate rankings in `memory/lookup.py` (cosine × fit; today's lookup
filled by the nearest lesson); a part split in `memory/coverage.py`; a choices script that writes
every candidate's choices on the steering slice and the winner's on `dev-seal-400`; a steering
reading over four coding runs that names the winner; the seal reading of 0213 reused. A free
exploratory script records the review's findings first.

**Tech Stack:** Python 3.14, the repo's strict toolchain, OpenRouter (GPT-6 Luna batch) for the
coding test, plan credit (Sonnet 5.5) for the apply step and a picking call on `dev-seal-400`.

## Global Constraints

- Snapshot `pilot-2010-recount`, K = 5, support floor 10, every coding-test setting of 0211.
- The embedding run is 0213's `openai/text-embedding-3-large` run; the picking run is 0213's.
- Counts only in every committed file; `dev-400`, `dev-seal-s3-400` and held-out never read.
- Every paid step waits for `docs/rounds/memory-embed-coding.md`, committed after Andy signs it.
- Results files only from a clean tree (`write_result`).

## Review Focus

- A choices folder written from a dirty tree, or for a candidate not registered: refused.
- `dev-seal-400` reached by anything but the steering reading's winner: refused.
- The steering reading given fewer or other runs than the four registered candidates: refused.
- `fill` on a case with neither an apply lesson nor a vector: no lesson, counted.
- A tie on the finding gain: the registered order decides, never the reader.

---

### Task 1: The review's findings, recorded (free)

- [x] `coverage.part_coverage`: each part (first code, findings) scored on its own, with tests.
- [x] `scripts/exploratory/memory_proxy_check.py`: the part split of 0213's lookups, the per-case
  check of agreement against coding benefit, the picking call's spend; tests.
- [x] Run it; commit `docs/results/memory-proxy-check-dev.txt`.

### Task 2: The records

- [x] Decision 0214, its README row, spec §13.13 (with the picking call's spend), this plan.
- [ ] The registration `docs/rounds/memory-embed-coding.md`, drafted outside the repo until Andy
  signs it; then committed alone.

### Task 3: The code

- [x] `lookup.by_similarity_fit` and `lookup.by_fit_or_nearest`, with tests.
- [x] `memory_embed`: candidate names `fit:` and `fill:`, a method for each prefix, the steering
  winner read from `docs/results/memory-embed-coding-dev.txt`, with tests.
- [x] `memory_coding_test.CHOICE_METHODS` gains `fit` and `fill`; `memory_coverage` refuses
  `dev-seal-400` (0214's choices script writes it); tests.
- [x] `scripts/memory_embed_choices.py` and `scripts/memory_embed_coding_result.py`, Makefile
  targets `mem-embed-choices` and `mem-embed-coding-result`, with tests.
- [x] `make check` passes; commit.

### Task 4: Review

- [x] One independent review of the branch since 0213's close (78458c1), most capable model;
  Critical and Important fixed with tests.

### Task 5: The steering runs (paid, about $0.73)

- [ ] `make mem-embed-choices ...`; commit `docs/results/memory-embed-choices-dev.txt`.
- [ ] Four `make mem-coding-embed-lookup` runs, one per choices run.
- [ ] `make mem-embed-coding-result ...`; commit `docs/results/memory-embed-coding-dev.txt`.

### Task 6: `dev-seal-400` (only if Task 5 names a winner)

- [ ] As the registration's §4 step 4.

### Task 7: Close the records

- [ ] Spec §13 Status and an "Added" note; CLAUDE.md; `make s33-continuity`, then
  `git checkout -- docs/results/s33-fingerprint-continuity.txt`; `make check`; commit.

## Deviations

- 2026-10-18, Task 1: the proxy check's tests were written after its first trial run (exploratory,
  decision 0059; its numbers were then reproduced by `make mem-proxy-check`). The trial showed the
  review's per-case reading needs the noise beside it: in the same groups, counts(b) − counts(a)
  is +3.6 points where today's lessons do not agree and −1.9 where one agrees, so the cases with an
  agreeing lesson gained more over their own noise, mostly on top-3. Decision 0214 says so.
- 2026-10-18, Task 2: the registration is drafted in `docs/rounds/` but left uncommitted until Andy
  signs it (committing it unlocks the paid steps); Task 3's commits stage explicit paths around it,
  and `test_selection_rule_docstring_matches_the_registration` reads the draft.
- 2026-10-18, Task 3: `memory_coding_test`'s embed-lookup run id now ends with the choices run's
  candidate (`<source>-embedlookup5-<snapshot>-<candidate>`), so the four steering runs over one
  tables run do not share a folder. No embed-lookup run had been made, so no run is renamed.
- 2026-10-18, Task 3: `memory_coverage` now refuses `dev-seal-400` and lost `--model`; its seal
  path (0213 §4 step 8.6) is `memory_embed_choices` (registration §4 step 4.6). Its seal tests
  were replaced by one refusal test.
- 2026-10-18, Task 3: `scripts/memory_embed_coding_result.py` was written before its tests (the
  tests then ran green on first run, apart from the registration-text test, which waited for the
  draft). The exploratory proxy check keeps its own part-split lines rather than importing
  `memory_embed_choices.part_lines`, so its committed output stays reproducible.
- 2026-10-18, Task 4: the review (Fable 5.1) found no Critical and two Important findings, both
  fixed with tests that failed first: the steering reading now opens each choices run and refuses
  one not made from the registered runs (`refuse_unregistered_choices`), and
  `memory_embed_choices` refuses any steering run but `STEERING_RUNS`; the paid embed-lookup run
  on `dev-seal-400` now checks the steering winner itself (`_refuse_seal_choice`). Three wording
  minors were fixed because the registration is not yet signed: §7 (the picking call gives a case
  with no vector nothing), §8 (the learning line's figure names its function), and stale
  docstrings. Deferred minors: the `dev-seal-400` tables, counts and apply steps are not gated in
  code on a steering winner (as under 0213); `_tools_run_id` accepts a choices name without its
  marker; a crash mid-loop could leave some choices folders written.
