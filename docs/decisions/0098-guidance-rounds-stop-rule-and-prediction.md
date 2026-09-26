# 0098 — Guidance rounds: sources, registration, reading rule, stop rule, the $25 line and the prediction

## Context

The model is given the code tables as bare labels (`scoring/prompt.py:tables_block`). Andy asked
for S2.7 as "several small, pre-registered experimental rounds rather than one big build", and
does not want S3 to start at 20–30% top-1. A target pursued round after round is how guidance
comes to fit `dev-400`; an end fixed in advance is how it does not.

## Decision

1. **What a round changes.** One piece of guidance, in the system text next to the code tables,
   never in the evidence payload; its own committed file under
   `src/ntsb_probable_cause/scoring/guidance/`; a bumped prompt version; the run record names
   both.
2. **Sources, only these:** the counts of `docs/results/s27-coding-stats.txt` (0094); official
   definitions (the NTSB data dictionary, or CICTT definitions once their match to the NTSB's
   events is checked); Round 0's findings, which set the order of rounds. Never text from a
   `dev-400` case, and no worked examples from real cases.
3. **Registration.** `docs/rounds/s27-round-N.md`, committed before the run: the change, its
   source, the miss group it should shrink, the reading rule, the cost estimate, a one-line
   prediction. The result is appended after the run. A run refuses a missing or uncommitted
   registration.
4. **Reading.** Paired against the reference (the last kept round, or Round 0's repeat for the
   first). **Kept** if the paired top-1 gain's lower interval bound is above zero and the gain
   exceeds the absolute paired top-1 difference between Round 0's two identical runs. **Not
   kept** if finding recall@10's paired difference lies wholly below zero. Finding rounds use the
   same rule the other way round. Kept rounds stack; dropped rounds are removed. The judge runs
   on each kept round.
5. **Order.** Occurrence rounds first; then one or two finding rounds.
6. **Stop.** Two dropped rounds in a row end the occurrence rounds (and then the finding
   rounds); S2.7's spend reaching **$25**, counted by commit from `971ee40`, ends all rounds.
   `scripts/stage_spend.py` refuses a paid step that would pass the line.
7. **The prediction**, published whichever way it comes out: occurrence top-1 on `dev-400` with
   the final setup between 30% and 36%; the misread share (if validated, 0099) not falling beyond
   its label churn during the rounds; the sealed sample (0095) lower than `dev-400` on top-1 by
   less than 5 points.

## Why

1. **One change per round** is the only way to say which change moved the score.
2. **The noise floor is part of the bar** because the first guess changed on 181 of 399 cases
   between B-v1 and B-v2 (ad-hoc), and nobody knows how much of that a repeat alone produces.
3. **A stop rule, not a target**: the stage ends whatever the scores, and a disappointing result
   is still a clean one.
4. **A prediction written first** is the project's habit (0022).

## What this rules out

- **A score target.** No natural end if it is out of reach, and every extra round fits
  `dev-400` a little more.
- **A fixed number of rounds.** It ignores what the rounds show.
- **Guidance and the ordering check changed in one round.** Two changes, one score.

## Status

Proposed, 2026-09-26: written with the S2.7 specification (Andy: "A, $25 is fine"; findings after
occurrence, "A"). The prediction's numbers are proposed in the specification for Andy's review.
Accepted when Andy approves the specification.
