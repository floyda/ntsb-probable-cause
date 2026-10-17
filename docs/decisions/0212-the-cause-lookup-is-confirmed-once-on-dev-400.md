# 0212 — The cause lookup is confirmed once on dev-400, unchanged

From Andy, 2026-10-17 ("Yes confirm dev-400 and approve the spend"), after the cause lookup of 0211
passed on the steering slice. Detail: the registration `docs/rounds/memory-confirm-dev400.md` and
the plan `docs/plans/2026-10-17-coding-memory-confirm-dev400.md`.

## Context

1. **The cause lookup passed its registered rule on `dev-steer-400`**
   (`docs/results/memory-cause-lookup-dev.txt`): finding recall@10 +2.9 points [+0.6, +5.3] over
   the counts condition, against a noise of 0.3; top-1 +2.5 [+0.5, +4.5]; top-3 +4.0 [+1.2, +6.7].
   Its registration (§10) recommends a registered confirmation on a fresh development sample,
   with its own counts runs, before any relearning.
2. **That pass was the steering slice's fourth look at a memory.** Each look could select what
   happens to suit those 401 cases, so the pass alone does not show the lookup helps elsewhere.
3. **Andy asked for a sample that is already cut.** Three development samples exist besides the
   steering slice:
   - **`dev-400`**, the project's development yardstick. The memory's pool leaves it out, so no
     lesson was learned from it and the `mem` counts do not hold its verdicts; no memory test has
     read it. Decision 0203 reserves it for the memory's milestones.
   - **`dev-seal-400`**, used once by S2.7 and never by the memory.
   - **`dev-seal-s3-400`**, sealed for Ellery version 2 (0141).
4. **Andy also expects a better lookup** (embedding search, or a ranking pass) to find the right
   lessons better. A lookup tuned on the steering slice needs its own unseen sample afterwards.

## Decision

1. **The cause lookup of 0211 runs once on `dev-400`, unchanged.** The same snapshot
   (`pilot-2010-recount`, checked, its hash recorded), the same apply step (Sonnet 5.5 at high, all
   198 lessons, the cause sentence alone), K = 5, the support floor of 10, the same coding tools'
   post-pass, GPT-6 Luna batch at reasoning `medium`, the same guidance and the `mem` statistics.
2. **`dev-400` gets its own comparison runs:** one tables run, two counts runs over it (their
   difference is `dev-400`'s noise), the apply step, and the cause lookup over the same tables run.
3. **The stop rule is 0211's, read on `dev-400`:** cause lookup minus counts(a) must exceed the
   finding noise on finding recall@10, and neither occurrence measure may fall by more than its own
   noise.
4. **What may read `dev-400`:** the coding test's tables, counts and cause-lookup conditions, and
   the apply step under its role `test-apply`. The memory and code-lookup conditions are refused
   there. All of them are refused until the registration is committed. This amends 0211 item 3
   (the apply step reads `dev-400`'s cause sentences too) and uses one of 0203's `dev-400`
   milestones.
5. **A registration is committed first**, after Andy signs it.
6. **Spend.** Estimates from the steering runs' own records: tables $0.15, counts $0.12 each,
   cause lookup $0.18, about $0.57 on OpenRouter (kind `coding-test`, on the $40 guard and the side
   track's $10 line); the apply step $1.56 of plan credit (kind `learning`, the learner's monthly
   line).

## Why

1. **It turns a steering-slice pass into a claim, or shows it was selection.** Nothing in the
   method was chosen on `dev-400`, and the lessons were learned without it.
2. **`dev-400` is the sample the design already set aside for this**, it is cut, and it is the
   yardstick every other development number sits beside.
3. **It keeps `dev-seal-400` for the better lookup.** That lookup is tuned on the steering slice,
   then confirmed once on `dev-seal-400`, so each claim is tested on cases its method never saw.
4. **It is cheap, and it changes nothing in the method.**

## What this rules out

- **Changing the method before this result.** The better lookup waits for this reading, and then
  gets its own decision.
- **Tuning anything on `dev-400`.** It is read once here; a later memory reading on it (the
  design's transfer check) would be its second look, and says so.
- **Using `dev-seal-s3-400`.** It stays sealed for Ellery version 2 (0141).
- **Connecting the memory to Ellery version 1, S4 or the board.** Unchanged from 0201.

## Status

Accepted. Amends 0211 item 3 (the apply step's sample) and uses one of 0203's `dev-400` milestones.
