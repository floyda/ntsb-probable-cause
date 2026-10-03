# S2.7: the sealed sample's registration (decision 0095)

Committed before anything reads `dev-seal-400`. From the commit that adds this file, the
runner, the check and `ntsb-eval transcribe` accept the sample (`samples.refuse_sealed`); before
it, they refuse it. The sample is used **once**, as below.

## The final setup, exactly

- **Arm and evidence:** arm B at evidence version **v1** (docket text layers only). The meeting
  point was skipped (Andy, 2026-09-29; the plan's Deviations), and decision
  [0120](../decisions/0120-qwen-stays-and-transcription-is-off-by-default.md) keeps
  transcription off by default, so there is no v2 run and no transcription of the sample.
- **Guidance, in stacking order:** `r3-loc-stall`, then `r6-aircraft-control`; combined
  fingerprint `e17fecdc66ec6ad35139e2732a653a4942dcb0826250e3a3f8fac6aedb29a3f1`; prompt
  version `s1-v6+ge17fecdc66ec` (decision
  [0105](../decisions/0105-codes-missing-from-the-dictionary-join-the-tables.md) set the base
  `s1-v6`).
- **Round 6 was kept by override** (decision
  [0106](../decisions/0106-round-6-kept-by-override.md)): the do-no-harm rule dropped it
  (finding recall@10 +11.4% [+8.2%, +14.6%], occurrence top-1 -6.3% [-10.5%, -2.5%] against
  Round 3's checked run), and Andy kept it, since Round 3's run was the highest of the six and
  against the other three checked runs top-1's interval included zero.
- **The ordering check:** `luna` (GPT-6 Luna, synchronous at the standard price), as a post-pass
  over the finished run (`ntsb-eval check RUN --way luna`; decisions
  [0096](../decisions/0096-the-ordering-check.md), [0101](../decisions/0101-the-clear-habit-safeguard.md),
  [0103](../decisions/0103-a-registered-second-jev-check.md)).
- **The answering model:** `openai/gpt-6-luna` at reasoning `medium`, batch, reply budget 8,000
  tokens (decisions [0073](../decisions/0073-the-default-model-is-gpt-6-luna-behind-a-gate.md),
  [0084](../decisions/0084-the-reply-budget-is-8000-tokens.md)).
- **The `dev-400` result it is read beside:** Round 6's checked run,
  `20260929T053953-674c92e-dev-400-B-check-luna` (answers `20260929T053953-674c92e-dev-400-B`,
  commit `674c92e`, $1.2128 for 401 cases).

## What runs, once

1. `make s27-sealed-run PER_CASE=0.0042`: arm B on `dev-seal-400` with the setup above. It
   fetches the sealed dockets as it goes (2 seconds a request). Estimate about $1.21 (Round 6's
   cost on `dev-400`).
2. `make s27-check RUN=<that run's id> WAY=luna`. Estimate about $0.12 (Round 1's measured Luna
   check cost was about that per answer set).
3. `make s27-sealed-results SEALED=<that run's id>-check-luna` (free): writes
   `docs/results/s27-sealed-dev.txt`.

**Not run:** the judge. Its narrative label failed validation in Round 0 (decision
[0099](../decisions/0099-the-judges-narrative-label-and-four-outcomes.md); 32 of 46, 69.6%,
against 75%), and `ntsb-eval judge` refuses a sample other than `dev-400` without
`--validated`. The misread part of the prediction is therefore scored "not scored".

`scripts/draw_sealed.py --verify` re-drew the sample on 2026-09-29: 401 committed, 401 re-drawn,
identical.

## What is reported

Top-1 (with its interval) and finding recall@10 for the sealed run beside the `dev-400` run
above, and the prediction of decision
[0098](../decisions/0098-guidance-rounds-stop-rule-and-prediction.md) item 7, scored whichever
way it comes out:

- occurrence top-1 on `dev-400` with the final setup between 30% and 36%;
- the misread share not falling beyond its label churn (not scored: label unvalidated);
- the sealed sample lower than `dev-400` on top-1 by less than 5 points.

The drop, or rise, from `dev-400` to the sealed sample is printed as it is.
