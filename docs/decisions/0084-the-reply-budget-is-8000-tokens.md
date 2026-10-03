# 0084 — The reply budget is 8,000 tokens

Sets the reply budget (`max_output_tokens`) every evaluation run uses from S2.6 Task 9A on.
Before this record the budget was 2,000 tokens, a default carried from S1 that no decision
chose. Every run records its budget (S2.6 Task 9A), so a run's budget is always on its record.

## Context

1. **S2.4's held-out arm B lost 24 cases to reply-format failures** (`docs/results/s24-bars.txt`,
   `failures by reason: leak (analysis_narrative) 40, schema 24`). S2.4's plan split them by
   hand, not by script, and found most were replies cut off before they finished. The budget
   counts the model's hidden reasoning as well as its answer, and GPT-6 Luna at reasoning
   level `medium` often reasons for more than 1,000 tokens before it writes anything.
2. **One run cannot both confirm the cause and size the fix.** A reply cut off at 2,000 tokens
   says only that it needed more than 2,000, not how much more. So the budget was measured
   with two `dev-400` arm B runs, identical except the budget: a confirmation run at 2,000 and
   a sizing run at 16,000 (Andy's decision B, S2.6 plan Task 9A). The rule that turns them into a
   budget was fixed before either run: the cause is confirmed if at least half the format
   failures are cut off with reasoning of at least half the budget; the new budget is the
   smallest of 4,000, 8,000 and 16,000 that is at least twice the 99th percentile of every
   finished reply's tokens in the sizing run, and above every failed reply's reasoning. If any
   reply in the sizing run was itself cut off, or ended for any other reason, no budget is set
   and the choice returns to Andy.
3. **A larger budget leaves slightly less room for documents.** The per-case cost estimate
   reserves the whole output budget before a case is answered (`estimated_cost_usd`), so every
   S2.6 run shares this effect. In both measurement runs the per-case cap cut no case short
   (0 of 401 each, `docs/results/s26-reply-budget-dev.txt`).
4. **The two runs share one recorded run id.** They were started in the same second at the same
   commit, sample and arm, so the harness gave them one id and one folder. Every run file is
   append-only and the confirmation run finished first, so the folder was split by a script
   into `…-confirm2000` and `…-size16000`, with every row copied unchanged and checked against a
   copy taken before the sizing run finished; the original folder is kept, unchanged, outside
   the runs directory. The results file prints the recorded id, which is why it shows the same
   id twice. The S2.6 plan's Deviations record the recovery and the harness fix.

## The measurement

`docs/results/s26-reply-budget-dev.txt`, from `scripts/reply_budget.py`, on commit `40c6ec6`:

- **Confirmation run (2,000):** 35 cases failed on reply format, 24 of them cut off (`length`)
  and 11 finished (`stop`) but malformed; 22 more replies were cut off and then recovered on
  retry. 46 of those 57 failures were cut off with at least 1,000 reasoning tokens.
  **Cause confirmed.**
- **Sizing run (16,000):** no format failures, no reply cut off, no reply ending any other way.
  Over the 854 replies that finished, total tokens per reply: median 864, 99th percentile 2,548,
  maximum 2,936; reasoning alone: median 484, 99th percentile 2,039, maximum 2,450.

## Decision

1. The reply budget is **8,000 tokens**. `RunSpec.max_output_tokens` defaults to 8,000, and
   every S2.6 run after Task 9A uses it (the plan's "one reply budget" constraint).
2. The budget stays recorded on every run's `spec.json` and run record, so a run on another
   budget is visibly a different run and cannot be resumed as this one.

## Why

1. **The fixed rule gives 8,000.** Twice the 99th percentile is 5,096, so 4,000 is too small and
   8,000 is the smallest step that fits; 8,000 is also above every failed reply's reasoning
   (at most 2,000, the old budget itself).
2. **The margin is measured, not guessed.** The largest finished reply in the sizing run used
   2,936 tokens, under 37% of the new budget.
3. **A failed case leaves `n` rather than counting wrong**, so failures that fall unevenly skew
   the score. S2.4's failures fell unevenly: 42 of 200 fatal cases against 22 of 200 non-fatal
   (`docs/results/s24-bars.txt`, `failed` column). At 16,000 no case failed on format.

## What this rules out

- **Leaving 2,000.** Truncation removes the hardest cases from every result.
- **A lower reasoning level to fit 2,000.** That changes the model's behaviour, which is the
  model axis examined after S3, not a budget setting.
- **16,000 by default.** Twice the size of 8,000 for no measured gain, and a larger reserve
  under the per-case cap.

## Status

Accepted, 2026-09-25 — by the rule Andy fixed before the runs (S2.6 plan Task 9A, decision B).
