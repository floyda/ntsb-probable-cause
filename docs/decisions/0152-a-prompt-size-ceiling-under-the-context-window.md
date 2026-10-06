# 0152 — A prompt-size ceiling under the model's context window, for both arms

Amends [0144](0144-one-per-case-cap-for-every-arm.md), whose reason "a higher cap can only let
arm B read more" missed the model's context window. From Andy, 2026-10-04, during S3.2's Task 15,
after held-out arm B's answer batch was refused. Detail: the S3.2 plan's Task 15a and Deviations.
Recorded after the registration (`docs/rounds/s3-registration.md`, commit `f0e78b7`) and before
any result of arm B or arm C on held-out had been seen.

## Context

1. **The refusal.** Held-out arm B's answer run (`20261004T094550-7948ac0-heldout-400-B`) sent its
   400 requests as one batch twice, and the provider refused the batch both times within about a
   minute: 0 of 400 answered, nothing billed. Its error named one case whose request was about
   1,444,916 tokens: "This endpoint's maximum context length is 1050000 tokens". One over-long
   request fails a whole batch. The run is recorded ABORTED in the held-out ledger.
2. **Why the cap did not stop it.** Arm B attaches docket documents until its cost estimate
   reaches the per-case cap. At S2.4's $0.05 cap that also kept every prompt well under the
   context window, and S2.4's held-out arm B ran. At 0144's $0.30 cap the estimate admits about
   three million estimated tokens per call. 0144's reason, "a higher cap can only let arm B read
   more of a very large docket, never less, which makes the bar stronger", did not consider the
   context window under it.
3. **The loop was exposed the same way.** A loop call over the context window would fail every
   batch round it was in, for every case of the run, until the round limit.
4. **The estimate undercounts document text** (`docs/results/s32-context-ratio-dev.txt`, from
   `scripts/s32_context_ratio.py` over the two noise-floor trails): the real prompt tokens divided
   by the characters-over-four estimate reach 2.4303 at most (99th percentile 2.0791, median
   1.0211). Document text tokenizes at about two characters a token.

## Decision

1. **A prompt-size ceiling of 345,000 estimated tokens** (`sources.PROMPT_TOKEN_CEILING`): 80% of
   the 1,050,000-token context window divided by the measured maximum ratio, 2.4303, rounded down
   to a thousand. The estimate stays characters over four, the runner's and the loop's own.
2. **Arm B**: a document is not attached when the prompt with it would pass the cap **or** the
   ceiling; a document left out by the ceiling is recorded `context`, not `cap`. On held-out, for
   a very large docket, the ceiling, not the $0.30 cap, is now what limits how much arm B reads.
3. **The loop and arm B's tool post-pass**: both drivers check every call before it is sent,
   including the first fresh round after a resume. A call over the ceiling is never sent; its case
   stops `cap: context`, and the rest of the round goes out without it. Such a case counts as wrong
   under the registered failure rule (decision 0146); it is not a guard refusal and is not counted
   by the format gate.
4. **The $0.30 cap stands** (0144) for cost; its reason about arm B is corrected by item 2.
5. **What the ceiling bounds, exactly.** It bounds arm B's stage-1 answer prompt (payload and
   system text) and every loop and post-pass call. Arm B's stage-2 refinement resends the stage-1
   payload with its own system text and the stage-1 reply; a stage-1 retry resends the stage-1
   system text with the rejection message. Either may exceed the ceiling slightly. A test pins the
   stage-2 overshoot: for a stage-1 prompt exactly at the ceiling and an answer with five findings
   in the widest categories it is 244 estimated tokens, because stage 2's system text replaces the
   longer stage-1 one (`tests/test_runner.py`, limit 20,000). At the measured ratio a stage-1
   prompt at the ceiling is about 838,000 real tokens, so this stays far inside the
   1,050,000-token window. The margin also covers text denser than any `dev-400` prompt measured:
   at the ceiling the window is reached only at an undercount of about 3.0, against the 2.43
   measured on prompts of up to about 263,000 estimated tokens.
6. **Under the ceiling nothing changes.** No noise-floor call, no `dev-400` arm B prompt and no arm
   B post-pass call was over it (the three counts in the results file), so no development run
   would have run differently, and the loop's prompt version is unchanged.
7. **Held-out arm B's answer run is made again, fresh**, from a commit with the ceiling. The
   registration gains a dated note saying so; its rules and predictions are unchanged.

## Why

1. **The context window is a hard limit the cost cap does not express.** A size ceiling states it
   directly, for both arms, in code.
2. **The margin is measured, not chosen.** With the measured maximum undercount, a prompt at the
   ceiling is at most about 840,000 real tokens, under the 1,050,000 limit.
3. **No held-out result has been seen.** The refused batch returned nothing, and no arm C held-out
   run had started, so the change cannot have been shaped by a result.

## What this rules out

- **Arm B back at $0.05, the loop at $0.30.** It worked in S2.4. Rejected: it breaks 0022 item 1's
  one cap for every arm, and it does nothing for the loop's exposure (Context 3).
- **A lower cap for every arm.** One number for both limits. Rejected: a cap low enough to keep
  arm B's prompt under the ceiling (about $0.04: two answer calls of 345,000 estimated tokens at
  the batch input price, with the reply reserve) would stop the loop's ordinary cases, whose
  dearest `dev-400` case cost $0.106 computed.
- **A ceiling set from the 99th percentile** (404,000). More documents read on the few largest
  dockets. Rejected: less margin; a single over-long request fails a whole batch.
- **A better token estimate in the loop.** It would need `agent/loop.py`, one of the fingerprinted
  files (0142).

## Status

Accepted, 2026-10-04 (Andy, S3.2 Task 15: "Yes" to the size ceiling).

## Glossary

- **Context window**: the most tokens one request may hold, prompt and reply together.
- **Ceiling**: the largest estimated prompt the code will send.
- **Undercount ratio**: real prompt tokens divided by the estimate, characters over four.
