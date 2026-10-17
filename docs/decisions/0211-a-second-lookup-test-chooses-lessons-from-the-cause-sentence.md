# 0211 — A second lookup test chooses lessons from the cause sentence, not the codes

From Andy, 2026-10-17 ("Ye go ahead"), after the lookup test of 0210 did not pass. Detail: the
registration `docs/rounds/memory-cause-lookup.md` and the plan
`docs/plans/2026-10-17-coding-memory-cause-lookup.md`.

## Context

1. **The lookup of 0210 did not pass its registered rule** (`docs/results/memory-lookup-dev.txt`):
   finding recall@10 +0.0 points [−2.2, +2.2] over the counts condition, against a noise of 0.3;
   top-3 +4.5 [+2.0, +7.2]. As registered, the side track stopped.
2. **Its query was the model's own codes.** A lesson was chosen only if it named a first code or a
   finding category already in the model's first answer (0210 item 2). So a chosen lesson could
   confirm or reorder that answer, but could rarely bring in a category the answer lacked. Andy
   asked for the agent's hypothesis to choose the lessons, and the lessons to guide the coding;
   0210 tested only the codes half of that.
3. **0210 ruled out matching by text** because it seemed to need an embedding model. A text
   matcher already exists: the learner's apply step (`memory.prompts.SYSTEM_APPLY`). It reads one
   case's cause sentence alone, sees each lesson's statement and scope and never its codes
   (`lessons.render_for_apply`), and lists the lessons that cover the case. Each lesson's support
   was counted from its answers, with Sonnet 5.5 at effort high, the applier the agreement test
   chose (`docs/results/memory-agreement-dev.txt`).

## Decision

1. **A cause-lookup condition is added to the coding test.** For each `dev-steer-400` case, the
   apply step reads the case's probable-cause sentence (the coding test's input, 0205; on a live
   case the agent's own draft) against all 198 lessons of `pilot-2010-recount`. Of the lessons it
   names, those that apply to at least 10 learning cases are ranked by fit, then by cases applied
   to, then by id, and the first five go into the coding tools' post-pass in place of the whole
   memory, as in 0210. No code from any answer is read in choosing them.
2. **Only the query changes from 0210:** the sample, the source run tables(a), the post-pass, K,
   the support floor and the stop rule are the same. So the result answers whether the codes were
   the problem.
3. **A registered exception to 0200:** the learner's transport reads `dev-steer-400`'s cause
   sentences, for this apply step only, under its own role (`test-apply`). It reads no code and
   writes no lesson: its reply is a list of existing lesson ids, and the snapshot is checked and
   fixed before it runs. Every other learner role still refuses every sample case.
4. **A registration is committed first**, after Andy signs it; the apply step and the coding run
   are both refused without it.
5. **Spend.** The apply step is kind `learning`, on plan credit, under the learner's monthly line;
   the 2010 batch apply calls averaged $0.0035 each, so about $1.40 for 401 cases. The coding run
   is kind `coding-test`, on the $40 guard and the side track's $10 line, about $0.20.

## Why

1. **It tests the design Andy described**: the hypothesis chooses the lessons, the lessons guide
   the codes.
2. **It reuses the matcher the counts came from.** A lesson's fit is the share of the cases the
   apply step said it covers whose NTSB codes agree with it; choosing lessons with the same step
   keeps fit meaningful for the cases it is applied to. No new dependency, no new prompt.
3. **It is cheap, and it changes one thing.**

## What this rules out

- **Tuning the apply step, K or the floor on this sample.** All three are fixed as they were. This
  is the steering slice's fourth look at a memory; a pass is confirmed on a fresh sample before
  any larger spend.
- **Lessons before the first answer** (in the tables condition rather than the post-pass). Tested
  second, only if this test shows something, because it needs new comparison runs.
- **Connecting the memory to Ellery version 1, S4 or the board.** Unchanged from 0201.

## Status

Accepted. Overrides the registered stop of `docs/rounds/memory-lookup.md` §10 for this one test;
amends 0210's "What this rules out" (matching by text) and, for the apply step only, 0200.
