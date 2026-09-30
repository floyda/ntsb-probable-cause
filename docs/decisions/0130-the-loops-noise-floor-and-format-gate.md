# 0130 — The loop's noise floor, and a 2% format gate

From the S3 design session (2026-09-29 to 2026-09-30): noise floor choice A, and the format gate
of spec §10.4. Detail: [the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md)
§10.2 to §10.4.

## Context

- Two identical arm B runs in S2.7 differed by occurrence top-1 +4.0% [+0.5%, +7.5%] on 399
  cases (`docs/results/s27-round0-dev.txt`). The loop has more sources of chance: read choices,
  tool arguments and state carried over many turns. In the learning probe, two identical runs
  gave top-1 after reading (H2) of 5 of 20 and 9 of 20 (scripted, the two probe reports).
- S2.4's format gate allowed at most 1% of cases (4 of 401) to fail, for a single call
  ([0073](0073-the-default-model-is-gpt-6-luna-behind-a-gate.md) item 2). GPT-6 Luna failed none
  of 401 (`docs/results/s24-gate-dev.txt`). The loop makes about ten calls per case: the probe's
  median was 12 and 11 calls (scripted).
- A failed case is left out of `n` and listed with its reason (spec §8.4).

## Decision

1. **The noise floor.** Arm C runs on `dev-400` twice, identically: evidence v1, the batch
   price, one frozen commit.
2. **A third run** is added only if the paired top-1 difference between the first two is larger
   than 4.0 points, S2.7's figure.
3. **What is reported**, as counts and paired differences with intervals: occurrence top-1 and
   top-3; finding recall@10; cases whose first code changed; read-or-skip agreement per
   document; tool-argument agreement; failures by reason; cost; and the cached share of prompt
   tokens. The raw stated confidences are kept for S3.2's calibration fit
   ([0126](0126-confidence-is-calibrated-in-code.md)).
4. **Tuning rounds are read against this noise floor** (spec §10.3). As in S2.7 (0098), each
   round is registered in `docs/rounds/` before it runs, and failures count in the do-no-harm
   rule.
5. **The format gate.** On each noise-floor run, at most 2% of cases (8 of 401) may fail for
   format or tool reasons. If the gate fails, the fix comes before S3.2.
6. Estimate (spec §10.2): about $7 for two runs; about $10.50 with a third.

## Why

1. **A tuning round can be read only against the loop's own noise.** S2.7's figure is for a
   single answer; the loop has more chance in it.
2. **A third run only improves the estimate of the spread.** It is worth its cost only when the
   first gap is wide.
3. **The gate scales with the calls.** Each of about ten calls per case is a chance to break
   format, so 0073's 1% for one call is too tight for the loop. 2% still stops a loop that
   breaks often.
4. **A gate protects the score.** Failed cases leave `n`, so a loop that fails often could
   flatter its own accuracy.
5. **The runs do double duty.** Their 802 answers are what S3.2 fits the calibration curve on.

## What this rules out

- **One run.** Half the cost. Rejected: one run gives no spread.
- **Reusing S2.7's noise floor.** Free. Rejected by Why 1.
- **Always three runs.** A better estimate every time. Rejected by Why 2.
- **A noise floor on part of `dev-400`.** Cheaper. Rejected, on judgement: tuning rounds are
  read on the whole of `dev-400`, so their noise should be measured on the same cases.
- **0073's 1% gate.** Rejected by Why 3.
- **No gate.** Rejected by Why 4.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
