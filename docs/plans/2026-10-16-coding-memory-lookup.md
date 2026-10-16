# Coding memory: the counting fix and the lookup test — implementation plan

> **For agentic workers:** Use superpowers:executing-plans. Tick each task's boxes in the same
> commit as its code (rule 10), and log every departure under **Deviations** at the end.

**Goal:** Fix the pilot's support count, recount the 2010 lessons from the learner's saved
answers at no cost, and test whether lessons looked up for each case beat the coding tools' counts
on finding recall@10, by a rule Andy registers before the paid runs.

**Architecture:** The counting rule in `memory/curate.py` is corrected and each lesson's support
gains two counts (decision 0209). `scripts/memory_recount.py` rebuilds a finished learner run's
final apply answers from its saved replies (self-checking against the saved request keys) and
writes a new snapshot with corrected support and the corrected cap. `memory/lookup.py` picks, for
one case, the lessons whose codes match the model's first answer; the coding test's `tools`
command gains `--lookup K`, which gives each case its own system text (decision 0210).
`scripts/memory_lookup_result.py` reads the runs and applies the registered rule.

**Tech Stack:** Python 3.14, uv, pydantic 2, pytest; GPT-6 Luna batch over OpenRouter for the
coding test. No learner (Claude) call anywhere in this plan.

**Spec:** docs/specs/2026-10-08-coding-memory-design.md

## Global Constraints

- No Claude call: the recount reads `calls.jsonl` of run `20261016T102829Z-beba05b-memory-2010`
  and sends nothing; it refuses unless every rebuilt request key is in that file.
- Saved snapshots are never rewritten: `pilot-2009` and `pilot-2010` render exactly as before
  (their support has no per-part counts), so the pilot's runs stay reproducible.
- The coding test as in the pilot: `dev-steer-400`, GPT-6 Luna batch, reasoning `medium`, guidance
  `r3-loc-stall` and `r6-aircraft-control`, statistics `mem`, source run tables(a)
  `20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a` (0204).
- Ellery version 1 untouched; `make s33-continuity` reports `+t` e7811b387b31 at the end.
- Lookup runs are refused until `docs/rounds/memory-lookup.md` is committed (0210).
- Spend: coding tests count on the $40 guard and the side track's $10 line (`make mem-spend`).
- Counts only in anything committed.

## Tasks

### Task 1: The counting fix (decision 0209)

- [x] `curate.agrees`: the first code must be one the lesson predicts (when it predicts any), and
  at least one predicted finding category must be flagged (when it predicts any). Was: every
  category.
- [x] `Support` gains `first_agrees` and `finding_agrees` (`int | None`, default None);
  `count_support` fills each when the lesson predicts that part.
- [x] `render_lesson` shows both counts when either is present; otherwise the old line, unchanged.
- [x] `finish` saves the final apply answers as `applies.json` in the run folder.
- [x] Tests in `tests/test_memory_curate.py` and `tests/test_memory_lessons.py`.

### Task 2: The recount (decision 0209)

- [ ] `scripts/memory_recount.py --run RUN --from SNAPSHOT --to NAME`: rebuild the final apply's
  memory text from the run's `draft.json` order and the snapshot's lessons, find the one retired
  lesson by trying each lesson the snapshot lacks, refuse unless every case's key is saved, count
  support with the fixed rule, cap, save unchecked. `make mem-recount`.
- [ ] Tests on a small invented run folder.
- [ ] Run it to `pilot-2010-recount`; `make mem-check SNAPSHOT=pilot-2010-recount`; commit the
  snapshot and stamp.

### Task 3: The lookup (decision 0210)

- [ ] `memory/lookup.py:lookup(lessons, occurrence_codes, finding_categories, k, min_applies)`.
- [ ] `memory_coding_test.py tools --snapshot NAME --lookup K`: condition `lookup`, run id
  `<source>-lookup<K>-<snapshot>`, refused without the registration; the spec records K, the
  floor and each case's lesson ids.
- [ ] Tests.

### Task 4: The reading

- [ ] `scripts/memory_lookup_result.py`: tables(a), counts(a), counts(b), the refilled notebook
  run and the lookup run; the registered rule on lookup − counts(a); `make mem-lookup-result`.
- [ ] Tests.

### Task 5: The records

- [ ] Decisions 0209 and 0210, README rows; the pilot plan's Deviations entry for the defect; a
  dated note under the spec's §12; the registration `docs/rounds/memory-lookup.md`.
- [ ] An independent review of Tasks 1–4 before any paid run.
- [ ] Andy signs the registration.

### Task 6: The runs (paid, under $1)

- [ ] The refilled notebook: `make mem-coding-tools SOURCE=<tables-a> SNAPSHOT=pilot-2010-recount`.
- [ ] The lookup: `make mem-coding-lookup SOURCE=<tables-a> SNAPSHOT=pilot-2010-recount K=5`.
- [ ] `make mem-lookup-result`; commit `docs/results/memory-lookup-dev.txt`; report to Andy.

## Deviations

(none yet)
