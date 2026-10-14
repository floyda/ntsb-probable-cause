# 0200 — A model may read development verdicts to learn coding lessons

From Andy, 2026-10-14. Amends rule 1 and [0013](0013-evidence-synthesis-verdict.md) for two
declared roles only: the coding memory's learner and its coding test. Detail:
`docs/specs/2026-10-08-coding-memory-design.md` §5.

## Context

1. **Rule 1 says verdicts reach a model only for scoring.** The probable cause and the codes are
   verdict (0013). Until now no model has read a verdict as input.
2. **Most misses are coding, not reading.** Andy's hand-read put 34 of 40 `dev-400` misses down
   to coding (`docs/results/s27-round0-dev.txt`). Lessons about how the NTSB codes can only be
   learned by reading how it coded.
3. **The counts already in the agent's tools cannot hold a condition.** They are looked up by
   code. A lesson such as "when the stall followed an engine problem, the power loss is coded
   first" needs the verdict's words.
4. **Live cases are in the open split**, which may enter a measurement only as numbers
   ([0024](0024-open-split-enters-measurements-only-as-numbers.md)).

## Decision

1. **The learner** may read, for cases in the **learning part** only (the S3 statistics pool less
   the steering slice of [0203](0203-the-steering-slice-and-statistics-without-it.md)): each
   case's probable-cause sentence, its occurrence codes in order and its finding codes, with
   their labels. Never evidence, synthesis or a docket.
2. **The coding test** ([0204](0204-the-coding-test-and-the-pilots-stop-rule.md)) may give GPT-6
   Luna the probable-cause sentence of a steering-slice case, and of a `dev-400` case at a
   milestone only.
3. **Never read by either:** `dev-seal-400`, `dev-seal-s3-400`, any held-out case, any open-split
   case closed or ongoing, any live case.
4. **The answering agent never reads a verdict.** It reads only a finished memory file, under
   [0201](0201-the-coding-memory-reaches-a-run-only-as-registered-guidance.md).
5. **Code boundary.** The learner and the coding test live in their own package. It may import
   the verdict records; `agent`, `model` and `live` may not import it, and an import-linter
   contract proves it. Its sample checks refuse every case in item 3 before reading, and a test
   proves each refusal.

## Why

1. **The lever the measurements point to needs the verdict's words** (context 2 and 3).
2. **Narrow reading keeps every measurement honest.** The learner never sees a case it is scored
   on; the coding test sees the steering slice, kept back for that purpose; `dev-400` is read only
   at milestones; the sealed sample stays sealed for version 2
   ([0141](0141-s32-five-runs-and-the-sealed-sample-kept-for-v2.md)).
3. **The model is stateless.** A verdict given to it in one call does not reach another call; only
   the memory file carries anything forward, and that file is checked (0201).

## What this rules out

- **Keeping rule 1 as it was.** No new leakage route. Rejected: it leaves the agent with counts
  only, and S2.7's hand-written guidance showed that conventions in words can help (round 3,
  +4.8% top-1).
- **Learning from live verdicts.** The project's original wish: an agent that keeps learning
  from the NTSB's feedback. Ruled out by 0024; it needs its own later record, either amending
  0024 for the learner with its own guard, or keeping live learning to counts.
- **Letting the agent read past verdicts at answer time.** That is retrieval of precedent, the
  tool of [0140](0140-the-precedent-tool-after-s4-as-a-measured-v2.md), with its own test.

## Status

Accepted.
