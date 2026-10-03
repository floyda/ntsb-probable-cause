# 0136 — In an S3 tuning round, a failed case counts as wrong, and the format gate is a hard limit

From Andy, 2026-10-02, before S3.1's first tuning round. Detail: the S3.1 plan's Deviations
(`docs/plans/2026-09-30-s3-1-agent-loop.md`). This says how
[0130](0130-the-loops-noise-floor-and-format-gate.md) item 4's "failures count in the do-no-harm
rule" is applied, and how [0098](0098-guidance-rounds-stop-rule-and-prediction.md) item 4's
reading rule reads an S3 round. S2.7's rounds are read as before.

## Context

1. **The reading rule leaves failed cases out.** 0098 item 4 pairs a round's run with its
   reference on the cases scored in both. `scripts/round_result.py` does this: a failed case
   leaves `n` (spec §8.4).
2. **No rule said how failures count.** 0130 item 4 and spec §10.3 say failures count in the
   do-no-harm rule. They do not say how. S3.1 Task 13's round template asked each round's
   registration to state its own limit before its run (the plan's Deviations, 2026-10-01).
3. **The loop fails more cases than arm B.** In the noise floor
   (`docs/results/s3-noise-floor-dev.txt`), the two identical arm C runs failed 5 and 8 of 401
   cases for format or tool reasons (`failed: coding 4, failed: h2 1` and `failed: coding 6,
   failed: h1 2`). Each run also had 2 guard refusals (`leak (probable_cause) 2`), and no case
   ran out of batch rounds. The two runs were paired on 387 of 401 cases. S2.7's two identical
   arm B runs were paired on 399 (`docs/results/s27-round0-dev.txt`), and the first one's 2
   failures were both guard refusals (`failures by reason: leak (probable_cause) 2`).
4. **Run b sits on the gate.** The format gate passes at most 8 of 401 cases
   ([0130](0130-the-loops-noise-floor-and-format-gate.md) item 5). Run b failed exactly 8.
5. **How a failure flatters a round.** Example: the reference run gets a case right. A round's
   change makes the loop break format on that case, so the case fails. Under S2.7's rule the case
   leaves `n`, and the round loses nothing for it. The round can look better than it is
   (0130, Why 4).

## Decision

1. **A failed case counts as wrong.** For an S3 round (arm C runs), the paired differences are
   taken over every case of the sample, the same cases in each run. A case that failed in a run
   scores 0 in that run. This holds for every kind of failure: format or tool (`failed:
   <step>`), the round limit (`failed: rounds`), a guard refusal (`leak: ...`) and the per-case
   cap (`cap`). A case that holds no score is counted the same way.
   - Occurrence top-1 and top-3: the case is a miss.
   - Finding recall@10: the case scores 0 when the NTSB flagged findings in its probable cause.
     When it flagged none, the case has nothing to score, in every run, as before.
   - The noise pair is read by the same rule, so the noise floor and the gain are measured alike.
2. **The format gate is a hard limit.** If the round's run fails more than 8 of 401 cases for
   format or tool reasons, the round is dropped, whatever its accuracy. The count is the one
   `scripts/s3_noise_floor.py` makes (`format_gate`): `failed: <step>`, but not `failed:
   rounds`; guard refusals and cap stops are not counted. The reading prints the gate first and,
   when it fails, says that the round is dropped for it.
3. **What the reading prints**, in order: the gate's lines for the round's run; the four runs; how
   many cases failed in each run; the run's failures by reason; occurrence top-1, the noise floor
   and finding recall@10, each with failures counted wrong and with its `n`; occurrence top-3,
   beside the rule and not in it; the line of first codes changed; the outcome.
4. **Where it applies.** `scripts/round_result.py` applies items 1 to 3 when the round's runs are
   arm C. An arm B run, which is every S2.7 round, is read exactly as before. Its output is the same
   byte for byte: this is tested, and it was checked on the run folders of S2.7's five rounds.
5. **The case groups use item 1 too.** `scripts/s3_case_groups.py` (plan Task 15) counts a
   failed case as wrong in that run.

## Why

1. **A failure must not flatter a round.** A rule that leaves failed cases out rewards a change
   that breaks the loop on hard cases (Context 5). Counting each failure as a miss makes a
   broken case cost what a wrong answer costs.
2. **A rule set before the first round cannot be argued around afterwards.** If each
   registration chose its own limit, the limit could be set with the expected result in mind.
   One rule for every round, fixed before any round runs, removes that choice.
3. **The gate is the limit the frozen loop met.** The noise floor's runs passed with 5 and 8
   failures of 401. A round changes the loop's text, not its machinery. If it fails more cases
   than the frozen loop did at its worst, something is broken, and a fix must come before any
   score is read (0130 item 5).
4. **The rule is simple to check, and it errs against the round.** A reader can recount it from
   `cases.jsonl` alone. A failure that is not the round's fault, such as a guard refusal, counts
   against the reference and the noise runs in the same way.

## What this rules out

- **Leave failed cases out of `n`, as S2.7 did.** It is the rule the rounds' script already used,
  and it keeps one reading for both stages. Rejected by Why 1: the loop fails more cases than
  arm B (Context 3), so the flattery is larger here.
- **Drop a round only when its run's failures exceed the noise floor's range, 5 to 8 of 401,
  and leave failed cases out of `n` otherwise.** Two identical runs already differ by 3
  failures, so this is kinder to a round that adds a failure or two by chance. Rejected (Andy):
  it is easier to argue around afterwards. A range from two runs is itself uncertain, and a rule
  that forgives small rises invites argument about where the range ends. Counting every failure
  as wrong needs no such judgement.
- **Count failures as wrong but keep no hard gate.** One rule fewer. Rejected by Why 3: a loop
  that breaks format often is broken, whatever its score.
- **Apply the rule to S2.7's rounds too.** One rule for both stages. Rejected: S2.7's results
  are committed and cited (decisions 0098, 0106), and its two identical arm B runs each scored
  399 of 401 cases (`docs/results/s27-round0-dev.txt`), so the rule would change little there.

## Status

Accepted, 2026-10-02 (Andy, before S3.1's first tuning round).

## Glossary

- **Arm C**: the agent loop. **Arm B**: every tool called in a fixed order, then one answer.
- **Do-no-harm rule**: a round is dropped if the other score's paired difference lies wholly
  below zero (0098 item 4).
- **Failed case**: a case with a `failure` reason in a run's `cases.jsonl`, and no score.
- **Format or tool failure**: a step of the loop whose call failed twice in a row: no tool call,
  a tool not allowed, arguments that did not check, or a tool that could not run. Written
  `failed: <step>`.
- **Format gate**: the count of format or tool failures in a run; at most 8 of 401 pass.
- **Guard refusal**: the leakage guard refused a document; written `leak: ...`.
- **`n`**: the number of cases a paired difference is taken over.
- **Noise floor**: the absolute occurrence top-1 difference between two identical runs. A round's
  gain must be larger.
- **Paired difference**: the mean, over cases, of a score in one run minus the same score in
  another run, with a 95% interval.
- **Round limit**: the most batch rounds a run may use; a case left at the end fails
  `failed: rounds`.
