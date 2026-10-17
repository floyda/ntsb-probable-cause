# Coding memory: the cause-sentence lookup — implementation plan

> **For agentic workers:** Use superpowers:executing-plans. Tick each task's boxes in the same
> commit as its code (rule 10), and log every departure under **Deviations** at the end.

**Goal:** Test whether lessons chosen from each case's cause sentence, rather than from the
model's codes, beat the coding tools' counts on finding recall@10, by a rule Andy registers before
the paid steps (decision 0211).

**Architecture:** `scripts/memory_cause_apply.py` runs the learner's apply step (Sonnet 5.5, high,
batch) on `dev-steer-400`'s cause sentences against all lessons of `pilot-2010-recount` and saves
each case's lesson ids. `memory/lookup.py` gains `by_fit`, which ranks the lessons a case was given
by fit. The coding test's `tools --lookup K` gains `--applies RUN_ID`, which chooses each case's
lessons from that run instead of from the first answer's codes.
`scripts/memory_cause_lookup_result.py` reads the runs and applies the registered rule.

**Tech Stack:** Python 3.14, uv, pydantic 2, pytest; the Claude API batch for the apply step; GPT-6
Luna batch over OpenRouter for the coding test.

**Spec:** docs/specs/2026-10-08-coding-memory-design.md

## Global Constraints

- The coding test as in 0210: `dev-steer-400`, GPT-6 Luna batch, reasoning `medium`, guidance
  `r3-loc-stall` and `r6-aircraft-control`, statistics `mem`, source run tables(a)
  `20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a`, K = 5, support floor 10.
- The apply step is the learner's, unchanged: `prompts.SYSTEM_APPLY`, `render_for_apply`,
  `apply_user`, Sonnet 5.5 at effort high, `MAX_TOKENS_SONNET_APPLY`. Its role is `test-apply`;
  its client is refused every sample case but `dev-steer-400`'s (0211 item 3).
- Both paid steps are refused until `docs/rounds/memory-cause-lookup.md` is committed.
- Spend: the apply step on the learner's monthly line; the coding run on the $40 guard and the side
  track's $10 line (`make mem-spend`).
- Ellery version 1 untouched; `make s33-continuity` reports `+t` e7811b387b31 at the end.
- Counts only in anything committed.

## Tasks

### Task 1: The apply step on the steering slice

- [x] `claude.ROLES` gains `test-apply`.
- [x] `memory_learn.apply_call(role, model, effort, memory, case_id, cause)`; `call_for_apply`
  delegates to it, so the recount's keys are unchanged.
- [x] `scripts/memory_cause_apply.py --snapshot NAME [--resume RUN_ID]`: refuses a dirty tree and
  a missing registration; reads the checked snapshot; sends one apply call per case with a cause
  sentence, all lessons in id order; checks the learner line first; writes `applies.json` and
  `apply.json` in the run folder and `docs/results/memory-cause-apply-dev.txt` (counts only).
  `make mem-cause-apply SNAPSHOT=`.
- [x] Tests on an invented snapshot and a fake client.

### Task 2: The cause lookup in the coding test

- [x] `lookup.by_fit(lessons, applied, *, k, min_applies)`.
- [x] `tools --snapshot NAME --lookup K --applies RUN_ID`: condition `cause-lookup`, run id
  `{source}-causelookup{K}-{snapshot}`; refuses an apply run on another snapshot or file hash, or
  one missing a case. The spec records `lookup_by`, `apply_run`, K, the floor and each case's
  lesson ids. `make mem-coding-cause-lookup SOURCE= SNAPSHOT= K= APPLIES=`.
- [x] Tests.

### Task 3: The reading

- [x] `scripts/memory_cause_lookup_result.py`: tables(a), counts(a), counts(b), the 0210 lookup run
  and the cause-lookup run; the rule on cause-lookup minus counts(a); also code-lookup minus
  counts(a) and cause-lookup minus code-lookup. `make mem-cause-lookup-result`, writing
  `docs/results/memory-cause-lookup-dev.txt`.
- [x] Tests.

### Task 4: The records

- [x] Decision 0211 and its README row; the registration, for Andy to sign.

### Task 5: The runs (paid, under $2)

- [ ] Andy signs; the registration is committed.
- [ ] `make mem-cause-apply SNAPSHOT=pilot-2010-recount`; commit its counts file.
- [ ] `make mem-coding-cause-lookup ...`; `make mem-cause-lookup-result ...`; commit the result,
  the spec note and the CLAUDE.md line.

## Deviations

- 2026-10-17, Tasks 1 and 2: `memory_learn`'s `_check_budget`, `_default_factory` and
  `_require_clean` became public (`check_budget`, `default_factory`, `require_clean`) so the apply
  script reuses them; `apply_call` takes the case as keyword arguments. The registration's §8 adds
  a refusal not in the plan: the cause lookup refuses an apply run where more than 2% of the
  replies failed (`memory_coding_test.read_applies`).
- 2026-10-17, independent review of Tasks 1 to 3: (1) a resume could re-send failed apply replies
  and pay for them again; a finished run (one with `apply.json`) now refuses a resume. (2) The
  `test-apply` role was a label only; the client now keeps every excluded case forbidden and lets
  that role alone read the steering slice (`LearningClient.allow_for_test_apply`), so 0211 item 3
  holds in code. (3) `read_applies` now refuses an apply run whose model or effort is not the
  registered Sonnet 5.5 at high. (4) The `causes` docstring now names the apply step as the
  second reader of the cause sentence.
