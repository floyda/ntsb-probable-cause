# TypeSafe's Jev on dev-400: result

*Run 2026-09-17. Specification: `docs/specs/2026-09-17-typesafe-jev-dev400-design.md`. Every
number here is quoted from `docs/results/typesafe-jev-dev400.txt`, printed by
`scripts/exploratory/jev_dev400.py` from run `20260917T182646-adda233-dev-400-jev`. The two
readings were fixed in the specification before the run.*

**The short version.** Jev's probabilities are **not calibrated** on this task, and its
accuracy does not beat the baseline. The experiment's central question (decision 0036) is
answered, and the answer is negative. Nothing about the loop changes; S3 should not be built
on a bought-in calibration claim.

## 1. What was run

Every one of the 401 `dev-400` development cases was sent once to Jev (the reply names
version `jev-1.13.0`), at commit `adda233` with a clean tree. The model was given the same
evidence payload the language models were given, and two questions: which phase of flight
(47 labels) and which event (93 labels). The two answers are combined into the NTSB's
six-digit occurrence code by multiplying their probabilities, as decision 0036 fixed.

All 401 were answered. No request failed and none needed a retry. The whole run cost $0.0517
at the vendor's published price ($0.000129 per case), which is reported for comparison only:
Jev is in preview. Replies took a median of 0.30 seconds, at four at a time, so no batch path
is needed.

## 2. Accuracy: it does not beat the baseline

| | top-1 | top-3 | event alone |
|---|---|---|---|
| **Jev** | **9.7% [7.2, 13.0]** | **20.2% [16.6, 24.4]** | **17.7% [14.3, 21.7]** |
| Luna | 8.7% | 22.9% | 17.7% |
| Gemini 3.1 Flash Lite | 12.5% | 22.9% | 24.7% |
| honest baseline (no model) | 17.7% | 35.7% | — |

The Luna and Gemini figures are S1's, on these same cases
(`docs/results/s1-model-comparison-dev.txt`); the baseline is `docs/results/s1-bars.txt`.

**Reading (fixed in advance): not above the baseline.** Top-1's interval reaches 13.0%, well
below 17.7%. Case by case, Jev is level with Luna (+1.0% [-2.7, +4.7]) and level with Gemini
(-2.7% [-6.2, +0.7]). A third model, of a different kind, lands in the same place. That
strengthens what S1 already said: the bar is the task, not the model.

**One split is much sharper than any model has shown before.** Jev scores 19.0% top-1 on
fatal cases and 0.5% on non-fatal ones — one case in 201. Fatal accidents are mostly loss of
control in flight, which the evidence hints at; non-fatal ones are a scatter of mechanical
and ground events that the evidence does not distinguish. Jev commits to the common answer.

**It also invents pairs the NTSB never records.** Its top-1 is an unseen phase-event pair on
7.7% of cases, against 3.5% for Luna. That is the cost of asking two independent questions
and multiplying: nothing stops the most probable phase and the most probable event from being
a combination that never occurs.

## 3. Calibration: the vendor's claim fails here

This is what the experiment existed to measure. Grouping the 401 answers by Jev's stated
confidence and comparing with how often it was right:

| stated confidence | cases | mean stated | share right | gap |
|---|---|---|---|---|
| 0.2–0.3 | 41 | 0.245 | 0.122 | −0.123 |
| 0.3–0.4 | 82 | 0.356 | 0.098 | −0.259 |
| 0.4–0.5 | 100 | 0.449 | 0.130 | −0.319 |
| 0.5–0.6 | 63 | 0.539 | 0.238 | −0.301 |
| 0.6–0.7 | 37 | 0.639 | 0.189 | −0.450 |
| 0.7–0.8 | 39 | 0.744 | 0.231 | −0.513 |
| 0.9–1.0 | 13 | 0.952 | 0.308 | −0.645 |

**Expected calibration error 0.318. Reading (fixed in advance): not calibrated.** The
threshold for that verdict was 0.10, and the measured error is three times it. Every bin is
overconfident, and the gap widens as confidence rises: when Jev says 95%, it is right 31% of
the time.

Using Jev's highest event probability instead of its confidence changes nothing (error
0.334). On the composed code, Jev's error is 0.359, against **Luna's 0.279** — the language
model's self-reported numbers, which nobody claims are calibrated, are closer to the truth
than the model sold on calibration. Gemini is worse than both at 0.624.

**What this means for S3.** Decision 0022 says the loop is warranted only if its intermediate
hypotheses are calibrated. The cheap route — buy calibration from a model class trained for
it — does not work on this task. S3 should not store Jev's distributions or use its
confidence as a stopping rule. Calibration remains something the project has to measure and
earn, not purchase.

**Per decision 0036's own rule, this declines the experiment.** 0036 point 4 named this
column as the one it exists for, and §5 of the specification fixed "not calibrated" as
grounds for declining. The status change is Andy's to make.

## 4. How the model behaves

- **It rules the right answer out entirely on a third of cases.** The probability Jev put on
  the true event has a median of 0.030, and is exactly 0 on 127 of 401 cases (31.7%).
  Probabilities come back rounded to two decimals, so "0" means below 0.005.
- **It falls back to a non-answer.** In the five seeded examples, two are led by "Unknown or
  undetermined" (0.54 and 0.55) on cases whose true event was a total loss of engine power.
- **It is right, and confident, where the evidence is suggestive.** Two examples are
  maneuvering fatal accidents: 0.74 and 0.75 on "Loss of control in flight", both correct.
- **Its confidence is not its top probability.** They differ by about 0.01 throughout, as the
  probe first showed.

## 5. What this does not show

The findings questions (130 yes/no claims per case), the abstention threshold, whether the
wording of the question changes the answer, and the judge test of 0036 point 5 were all out
of scope. Nothing here bears on whether the tool loop is warranted: that needs arms B and C
with the docket, which do not exist yet. No held-out case was touched.

## Glossary

- **Calibrated.** Stated probabilities match how often the model is right: of the answers
  given at 70%, about 70% are correct.
- **Expected calibration error.** Answers are put in ten bins by stated probability. For each
  bin, take the gap between the mean stated probability and the share correct, weight it by
  the bin's size, and add them up. 0 is perfect.
- **dev-400.** The fixed sample of 401 development-split cases S1 uses for development runs.
- **Occurrence code.** The NTSB's six-digit code for what happened: a three-digit phase of
  flight and a three-digit event, joined.
- **Pair unseen.** The share of cases where the model's first answer is a code that is never
  the defining occurrence of any development-split case.
- **Top-1, top-3.** The first code offered is right; or the right code is among the first
  three.
