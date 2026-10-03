# 0147 — Calibration and abstain: a logistic curve, a three-group test, a threshold with a meaning

From the S3.2 design session (2026-10-03): calibration, and abstain option A. Applies
[0126](0126-confidence-is-calibrated-in-code.md) and
[0121](0121-agency-moves-to-reading-and-coding.md) item 5's result 3. Detail:
[the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §8.

## Context

At its answer the loop states a confidence. Across the two noise-floor runs it averaged about
0.62, but the answers were right on occurrence top-1 about 27% of the time, and the stated number
barely sorts right from wrong. Summing the two runs' bands (scripted,
`docs/results/s3-noise-floor-dev.txt`):

| stated confidence | right | share |
|---|---|---|
| below 0.4 | 28 of 128 | 22% |
| 0.4 to 0.6 | 36 of 153 | 24% |
| 0.6 to 0.8 | 95 of 349 | 27% |
| 0.8 or above | 55 of 155 | 35% |

0126 decided that code, not the model, turns the stated number into the confidence shown, and
left the method and the test to S3.2. S1 chose its own abstain threshold by maximising a penalised
score and chose 0.95, which answered no case at all (scripted, `docs/results/s1-threshold.txt`).

## Decision

1. **The curve is logistic**: from stated confidence to the chance that the first occurrence
   code is right, two numbers, always rising.
2. **It is fitted on the noise-floor runs' scored answers**, both runs pooled (785 answers; a
   case the model abstained on is counted wrong, as top-1 counts it; failed and refused cases
   have no answer and are left out).
3. **It is frozen before any held-out run.** Its two numbers are committed in a file the
   held-out reading loads, with the results file that printed them.
4. **The test on held-out (result 3).**
   - The loop's scored held-out answers are put in **three equal groups by fitted value** (low,
     middle, high).
   - In each group, the **average fitted value** is compared with the **share actually right**.
   - **Calibrated:** in every group, the average fitted value lies inside that group's interval
     for the share right. The three Wilson intervals are each at 98.3% (that is, 1 - 0.05/3), so that a
     perfectly calibrated curve fails by chance at most 1 time in 20 overall.
   - **Reported, not tested:** how well the confidence sorts right from wrong, as the share right
     in the high group minus the low group, with its interval.
5. **The loop abstains when its fitted chance is below 16.4%**, the no-model baseline's top-1 on
   development (scripted, `docs/results/s1-baseline.txt`, its development fit, n=1000).
6. **On held-out, abstain is reported on its own:** how often it fires, and the share right among
   answered and abstained cases. It is not applied to the arm comparison
   ([0146](0146-the-headline-test-and-failed-cases.md) item 5).

## Why

1. **A reported confidence must mean what it says** (0126 Why 1). A board that shows 70% beside
   answers that are right about a third of the time misleads the reader.
2. **A curve with two numbers is hard to overfit.** From the bands above, it would turn a stated
   0.9 into about 0.35 and a stated 0.3 into about 0.22 (estimate).
3. **Freezing the curve first makes held-out a test of it.** Held-out does not shape it (0126
   Why 2).
4. **Three groups at 98.3% keep the false-fail rate at 1 in 20.** Each group holds about 120
   cases. By chance alone a perfect curve shows a gap of about 4 points in a typical group
   (estimate), so a rule such as "the average gap is under 5 points" would fail it too often.
5. **The sorting figure is reported because calibration alone can be useless.** A curve can be
   calibrated and still give every case about the same number.
6. **The threshold has a meaning, not an optimum.** In plain words: if a lookup table would do
   better than the agent on this case, the agent says it does not know. S1's penalised score gave
   a threshold that answered nothing, which is the lesson.
7. **Abstain may seldom fire, and that would be a finding.** From the `dev-400` bands, fitted
   values may run from about 20% to 35%. If the threshold fires on fewer than 5% of cases
   (prediction 8), the confidence cannot yet tell thin evidence from good.

## What this rules out

- **A step curve (isotonic).** It fits the bands closely. Rejected: it bends to noise (run b's
  bands dip, then rise).
- **Fixed bands.** Easy to read. Rejected: they jump at their edges.
- **An average-gap rule** such as "under 5 points". Rejected in Why 4.
- **Abstaining on the lowest 10%.** It would always fire on some cases. Rejected: the threshold
  would not mean anything about the evidence, and it would hide whether the confidence can sort.
- **S1's penalised score for the threshold.** Rejected in Why 6: it chose 0.95, which answered
  no case.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Abstain**: the agent declines to answer. Here, when its fitted chance is below the no-model
  baseline's.
- **Calibrated**: when the board shows 30%, the answer is right about 30% of the time.
- **Fitted value**: the curve's output for a stated confidence.
- **Logistic curve**: a smooth S-shaped curve fixed by two numbers.
- **No-model baseline**: a lookup rule using only basic case facts, with no AI model (S1).
- **Wilson interval**: an interval for a share that stays sensible for small counts.
