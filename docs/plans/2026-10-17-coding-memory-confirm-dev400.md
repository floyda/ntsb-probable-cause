# Coding memory: the cause lookup's confirmation on dev-400 — implementation plan

> **For agentic workers:** Use superpowers:executing-plans. Tick each task's boxes in the same
> commit as its code (rule 10), and log every departure under **Deviations** at the end.

**Goal:** Run the cause lookup that passed on the steering slice once on `dev-400`, unchanged, with
that sample's own tables and counts runs, by a rule Andy registers before the paid steps (decision
0212).

**Architecture:** `memory_coding_test` and `memory_cause_apply` take `dev-400` as a second sample,
refused until `docs/rounds/memory-confirm-dev400.md` is committed; on `dev-400` the coding test
allows the tables, counts and cause-lookup conditions only. `scripts/memory_confirm_result.py` reads
the four `dev-400` runs and applies 0211's rule.

**Tech Stack:** Python 3.14, uv, pydantic 2, pytest; the Claude API batch for the apply step; GPT-6
Luna batch over OpenRouter for the coding test.

**Spec:** docs/specs/2026-10-08-coding-memory-design.md

## Global Constraints

- The method of 0211, unchanged: `pilot-2010-recount`, Sonnet 5.5 at high, all 198 lessons, K = 5,
  support floor 10, the counts post-pass, GPT-6 Luna batch at `medium`, guidance `r3-loc-stall` and
  `r6-aircraft-control`, statistics `mem`, cap $0.05 a case.
- Every paid step refused until the registration is committed.
- `dev-seal-400` and `dev-seal-s3-400` untouched.
- Ellery version 1 untouched; `make s33-continuity` reports `+t` e7811b387b31 at the end.
- Counts only in anything committed.

## Tasks

### Task 1: dev-400 in the scripts

- [x] `memory_coding_test`: `CONFIRM_SAMPLE`, `CONFIRM_REGISTRATION`; `refuse_sample` allows
  `dev-400` only once registered; `refuse_condition` refuses memory and code lookup there;
  `answer --sample`; `tools` takes the source run's sample; `causes` and `read_applies` take a
  sample.
- [x] `memory_cause_apply --sample`: the same refusal; the client may read that sample's cases under
  `test-apply` only; the run id names `dev-400`; output `docs/results/memory-cause-apply-dev400.txt`.
- [x] `memory_pilot_result.load_run(..., sample)`; `scripts/memory_confirm_result.py`, reusing the
  cause-lookup reading's refusal of unrelated runs.
- [x] Makefile: `SAMPLE=` on `mem-coding-answer` and `mem-cause-apply`; `mem-confirm-result`.
- [x] Tests.

### Task 2: The records

- [x] Decision 0212 and its README row; the registration, for Andy to sign.

### Task 3: The runs (paid, about $0.57 and $1.56 of credit)

- [ ] Andy signs; the registration is committed.
- [ ] `make mem-coding-answer REPEAT=a SAMPLE=dev-400`.
- [ ] `make mem-coding-tools SOURCE=<tables> REPEAT=a`, then `REPEAT=b`.
- [ ] `make mem-cause-apply SNAPSHOT=pilot-2010-recount SAMPLE=dev-400`; commit its counts file.
- [ ] `make mem-coding-cause-lookup SOURCE=<tables> SNAPSHOT=pilot-2010-recount K=5 APPLIES=<apply>`.
- [ ] `make mem-confirm-result ...`; commit the result, the spec note and the CLAUDE.md line.

## Deviations
