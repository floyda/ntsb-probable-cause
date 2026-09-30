# 0126 — Confidence is calibrated in code; abstain is a threshold on the fitted value

With [0121](0121-agency-moves-to-reading-and-coding.md), it replaces 0021 item 4's stop at a
confidence threshold. From the S3 design session (2026-09-29 to 2026-09-30): calibration choice
B. Detail: [the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §6, and §2
lesson 2.

## Context

In the learning probe, the agent's mean stated confidence was 0.25 and 0.24 before reading
(H0), and 0.69 and 0.72 after reading (H2), in the two runs. After reading, answers at a stated
confidence of 0.6 or above were right on 5 of 16 and 8 of 18 cases. The abstain flag never fired
after reading. (Exploratory, `scripts/exploratory/s3_probe_confidence.py`; spec §2.) Stated
confidence tracked how much was read, not how often the agent was right.

## Decision

1. The model still states a confidence at every checkpoint and in its answer.
2. **Code, not the model, turns it into the reported confidence**: a curve from stated
   confidence to the chance of being right, fitted on the loop's own `dev-400` runs and frozen
   before any held-out run.
3. **The abstain flag is a threshold on the fitted value**, chosen on `dev-400` only, as 0021
   item 4 required of its threshold.
4. **The raw stated confidence is recorded and reported beside the fitted one**, so that the
   fit can be audited.
5. **S3.1 records the raw values.** The noise-floor runs give 802 answers to fit on
   ([0130](0130-the-loops-noise-floor-and-format-gate.md)). The fit, its method and its check on
   the sealed sample ([0129](0129-s3s-sealed-sample-and-statistics.md)) belong to S3.2.
6. Result 3 of 0121 item 5 tests the fitted confidence on held-out, by the bound S3.2 registers.

## Why

1. **A reported confidence must mean what it says.** A board that shows 70% beside answers that
   are right a third of the time misleads the reader.
2. **The fit can be checked.** Raw and fitted values sit side by side, and the curve is frozen
   before held-out, so held-out tests the curve rather than shapes it.

## What this rules out

- **Reporting the model's stated confidence.** It needs no fit. Rejected by the probe (Context)
  and Why 1.
- **The model's own abstain flag.** The simplest rule. Rejected: in the probe it never fired
  after reading.
- **A fixed threshold on stated confidence** (for example, abstain below 0.5). Rejected: stated
  confidence rose to about 0.7 with reading, so such a threshold would act on how much was read,
  not on how likely the answer is to be right.
- **Fitting the curve, or choosing the threshold, on held-out or on the sealed sample.**
  Rejected: held-out scores would stop meaning anything (0021's reason), and the sealed sample
  checks the fit once; it is not used to make it.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
