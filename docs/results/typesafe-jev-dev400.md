# TypeSafe's Jev on dev-400: result

*Run 2026-09-17. Specification: `docs/specs/2026-09-17-typesafe-jev-dev400-design.md`. Jev's
own numbers — accuracy, calibration, the examples — are quoted from
`docs/results/typesafe-jev-dev400.txt`, printed by `scripts/exploratory/jev_dev400.py` from run
`20260917T182646-adda233-dev-400-jev`. Luna's and Gemini's figures (including Luna's
event-alone and unseen-pair rates) are quoted from `docs/results/s1-ceiling-dev.txt` and
`docs/results/s1-model-comparison-dev.txt`; the honest baseline is `docs/results/s1-bars.txt`.
The two readings were fixed in the specification before the run.*

**The short version.** Jev's probabilities are **not calibrated** on this task, and its
accuracy does not beat the baseline. The experiment's central question (decision 0060) is
answered, and the answer is negative. Nothing about the loop changes; S3 should not be built
on a bought-in calibration claim.

## 1. What was run

Every one of the 401 `dev-400` development cases was sent once to Jev (the reply names
version `jev-1.13.0`), at commit `adda233` with a clean tree. The model was given the same
evidence payload the language models were given, and two questions: which phase of flight
(47 labels) and which event (93 labels). The two answers are combined into the NTSB's
six-digit occurrence code by multiplying their probabilities, as decision 0060 fixed.

All 401 were answered. No request failed and none needed a retry. The whole run cost $0.0517
at the vendor's published price ($0.000129 per case), which is reported for comparison only:
Jev is in preview. Replies took a median of 0.30 seconds (90th percentile 0.41 seconds, max
1.01 seconds), at four at a time, so no batch path is needed.

## 2. Accuracy: it does not beat the baseline

| | top-1 | top-3 | event alone | answered top-1 |
|---|---|---|---|---|
| **Jev** | **9.7% [7.2, 13.0]** | **20.2% [16.6, 24.4]** | **17.7% [14.3, 21.7]** | **9.7%** |
| Luna | 8.7% | 22.9% | 17.7% | 11.3% |
| Gemini 3.1 Flash Lite | 12.5% | 22.9% | 24.7% | 12.7% |
| honest baseline (no model) | 17.7% | 35.7% | — | — |

Luna's and Gemini's figures are S1's, on these same cases (`docs/results/s1-ceiling-dev.txt`,
`docs/results/s1-model-comparison-dev.txt`); the baseline is `docs/results/s1-bars.txt`. Four
of the 401 cases have a true phase that is not one of the 47 phase labels offered, so no
model's top-1 can reach the composed code on them; this affects Jev, Luna and Gemini equally
and moves no comparison in this report.

The baseline was measured on held-out cases, not on these 401. It is the bar S1 set, so it
is the line this row is read against.

**Reading (fixed in advance): not above the baseline.** Top-1's interval reaches 13.0%, well
below 17.7%.

Jev never abstains; Luna abstains on 22.9% of these cases and Gemini on 1.5%. Decision 0060
point 4 fixed `answered top-1` — top-1 restricted to the cases each model chose to answer —
as the like-for-like column for that reason, and it is the fourth column above. On it, Jev
(9.7%, unchanged, since it always answers) sits below both Luna (11.3%) and Gemini (12.7%):
Jev is not level with either model on the column 0060 set for the comparison. The paired
plain-top-1 differences below count an abstention as wrong, which is a second, looser
convention that includes cases the LLMs declined: on that basis Jev is +1.0% [-2.7, +4.7]
against Luna and -2.7% [-6.2, +0.7] against Gemini, both too small at n=401 to call either
way. Under either convention, a third model of a different kind lands in the same place S1
already found: the bar is the task, not the model.

**One split is much sharper than any model has shown before.** Jev scores 19.0% top-1 on
fatal cases and 0.5% on non-fatal ones — one case in 201. Event 240, loss of control in
flight, is the true primary event of 83 of the 200 fatal cases (41.5%) — a plurality, which
the evidence hints at often enough for Jev to commit to it; non-fatal cases are a scatter of
mechanical and ground events that the evidence does not distinguish.

**It also invents pairs the NTSB never records.** Its top-1 is an unseen phase-event pair on
7.7% of cases, against 3.5% for Luna. That is the cost of asking two independent questions
and multiplying: nothing stops the most probable phase and the most probable event from being
a combination that never occurs. §4 below has a worked example of the same mechanism landing
on a *seen* pair that is still the wrong code.

## 3. Calibration: the vendor's claim fails here

This is what the experiment existed to measure. Grouping the 401 answers by Jev's stated
confidence and comparing with how often it was right:

| stated confidence | cases | mean stated | share right | gap |
|---|---|---|---|---|
| 0.1–0.2 | 9 | 0.177 | 0.000 | −0.177 |
| 0.2–0.3 | 41 | 0.245 | 0.122 | −0.123 |
| 0.3–0.4 | 82 | 0.356 | 0.098 | −0.259 |
| 0.4–0.5 | 100 | 0.449 | 0.130 | −0.319 |
| 0.5–0.6 | 63 | 0.539 | 0.238 | −0.301 |
| 0.6–0.7 | 37 | 0.639 | 0.189 | −0.450 |
| 0.7–0.8 | 39 | 0.744 | 0.231 | −0.513 |
| 0.8–0.9 | 17 | 0.821 | 0.588 | −0.233 |
| 0.9–1.0 | 13 | 0.952 | 0.308 | −0.645 |

**Expected calibration error 0.318. Reading (fixed in advance): not calibrated.** The
threshold for that verdict was 0.10, and the measured error is three times it. Every one of
the nine bins is overconfident, and the worst is the top one (0.9–1.0, gap −0.645): when Jev
says 95%, it is right 31% of the time. The gap does not simply widen as confidence rises,
though — the 0.8–0.9 bin (gap −0.233) is closer to correct than the bins from 0.3–0.4 through
0.7–0.8, though not than the 0.1–0.2 or 0.2–0.3 bins — so the honest statement is
"overconfident everywhere, worst at the top," not a smooth trend.

Using Jev's highest event probability instead of its confidence changes nothing (error
0.334). On the composed code, Jev's error is 0.359, against **Luna's 0.279** and Gemini's
0.624 — both read off Luna's and Gemini's own first-guess probability, whether or not the
model abstained, since table (c) deliberately ignores abstention for the language models: it
is a second convention alongside the abstention-aware `answered top-1` column above, used on
purpose because Jev has no abstention to control for. The language model's self-reported
numbers, which nobody claims are calibrated, are closer to the truth than the model sold on
calibration.

**What this means for S3.** Decision 0022 says the loop is warranted only if its intermediate
hypotheses are calibrated. The cheap route — buy calibration from a model class trained for
it — does not work on this task. S3 should not store Jev's distributions or use its
confidence as a stopping rule. Calibration remains something the project has to measure and
earn, not purchase.

**Per decision 0060's own rule, this declines the experiment.** 0060 point 4 named this
column as the one it exists for, and §5 of the specification fixed "not calibrated" as
grounds for declining. The status change is Andy's to make.

## 4. How the model behaves

- **It rules the right answer out entirely on a third of cases.** The probability Jev put on
  the true event has a median of 0.030, and is exactly 0 on 127 of 401 cases (31.7%).
  Probabilities come back rounded to two decimals (decision 0060, probe result point 2), so
  "0" means below 0.005.
- **It falls back to a non-answer.** In the five seeded examples, two are led by "Unknown or
  undetermined" (0.54 and 0.55) on cases whose true event was a total loss of engine power.
- **The event can be right while the composed code is still wrong.** Two seeded examples,
  CEN12FA594 and WPR12FA184, are maneuvering fatal accidents where Jev puts 0.74 and 0.75 on
  "Loss of control in flight" — the correct event, on both cases. But its top phase answer is
  450 ("Maneuvering") on both, where the true phase is the more specific 452
  ("Maneuvering-Low-alt flying"), so the composed top-1 (450240) is wrong on both and misses
  top-3 as well. This is the same multiplication mechanism behind the 7.7% unseen-pair rate
  in §2: the phase answer and the event answer are each the most probable label on its own
  question, and nothing ties the two together, so a correct event can still be paired with the
  wrong phase.
- **Its confidence is not its top probability.** They differ by 0.02 on 238 of the 401 cases
  and by 0.01 on the remaining 163, as the probe first showed.

## 5. What this does not show

The findings questions (130 yes/no claims per case), the abstention threshold, whether the
wording of the question changes the answer, and the judge test of 0060 point 5 were all out
of scope. Nothing here bears on whether the tool loop is warranted: that needs arms B and C
with the docket, which do not exist yet. No held-out case was touched.

## Glossary

- **Calibrated.** Stated probabilities match how often the model is right: of the answers
  given at 70%, about 70% are correct.
- **Choice.** A Jev question type: the model picks one label from a list and returns a
  probability for every label plus a confidence. Phase and event were each asked as a Choice.
- **Expected calibration error.** Answers are put in ten bins by stated probability. For each
  bin, take the gap between the mean stated probability and the share correct, weight it by
  the bin's size, and add them up. 0 is perfect.
- **State.** The single piece of text a Jev request carries — here, the same evidence payload
  the language models were given.
- **dev-400.** The fixed sample of 401 development-split cases S1 uses for development runs.
- **Occurrence code.** The NTSB's six-digit code for what happened: a three-digit phase of
  flight and a three-digit event, joined.
- **Pair unseen.** The share of cases where the model's first answer is a code that is never
  the defining occurrence of any development-split case.
- **Top-1, top-3.** The first code offered is right; or the right code is among the first
  three.
