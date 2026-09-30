# 0121 — Agency moves to the read choice and the coding step; parts of 0021 to 0023 are superseded

Supersedes, in part, [0021](0021-agency-measured-as-hypothesis-trail.md) (items 1 and 4),
[0022](0022-loop-must-beat-call-every-tool-arm.md) (item 4 reworded; item 5, the predictions P1
to P6, withdrawn) and [0023](0023-evidence-by-source-with-measured-availability.md) (items 1, 2
and 4). Those records stay in place, each with a dated note appended. From the S3 design session
(2026-09-29 to 2026-09-30): the direction agreed before the learning probe, and supersession
choice C. Detail: [the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §1, §2,
§4, §13 and §17 (record 1).

## Context

0021 to 0023 put the loop's choices in **gathering evidence**: tools grouped by source, a
hypothesis after every tool call, a stop at a confidence threshold, and a masked condition in
which evidence arrives late. Three measurements since then show where choices can matter
(spec §1):

- **Reading more barely helps.** Arm B with transcribed pages against arm B without, on
  `dev-400`, paired on 399 cases: occurrence top-1 +1.3% [-2.5%, +4.8%]
  (`docs/results/s26-armB-v2-dev.txt`).
- **Coding moves the score.** S2.7's ordering check raised arm B's top-1 by +6.8% [+3.3%,
  +10.3%] and +9.8% [+6.0%, +13.8%] on two answer sets (`docs/results/s27-round1-dev.txt`).
  Andy's hand-read of 40 misses put 34 down to coding (19 convention, 15 wrong phase) and 4 to
  a misread or missing fact (`docs/results/s27-round0-dev.txt`).
- **Dockets arrive at closure.** The recorder has seen 7 dockets appear, all in the same nightly
  run as their case's closure, none before (`docs/results/s3-recorder-report-2026-09-29.txt`;
  [0123](0123-the-staged-replay-is-paused.md)).

**The learning probe, disclosed.** Before this record was written, a learning probe (pull
request #18) ran a flow like the loop on 20 `dev-400` cases, twice with identical settings
(`docs/results/s3-probe-dev.txt`, `docs/results/s3-probe-dev-run2.txt`). It shaped this design
(spec §2) and carries no claim. It saw development accuracy at every checkpoint. The table
gives occurrence top-1 and top-3 as cases right out of 20; run 1's answer is out of 17,
because 3 cases failed.

| checkpoint | run 1 top-1 | run 1 top-3 | run 2 top-1 | run 2 top-3 |
|---|---|---|---|---|
| before reading (H0) | 5 | 8 | 5 | 9 |
| after the first read choice (H1) | 5 | 8 | 9 | 10 |
| after the second look (H2) | 5 | 9 | 9 | 10 |
| the answer | 6 of 17 | 8 of 17 | 9 | 11 |

These figures moved between identical runs: at n=20 they are noise. Accuracy by checkpoint
bears on P5, though it is not the probability on the true codes that P5 names, which the
reports do not give. The reports score none of the other five predictions: they give no steps
by fatality, no comparison with arm B, no masked condition, and no stated effect against an
observed one.

## Decision

1. **Where the agency is.** On every case the loop makes two kinds of choice (spec §1, §4.2):
   - **which documents to read**: read or skip for every offered document, with the effect the
     agent expects from it;
   - **how to code**: "code first, then check". The agent drafts its codes, then checks them
     with tools that take codes as arguments.

   Arm B gets the same tools in a fixed order
   ([0127](0127-arms-ablations-and-the-ordering-check-in-arm-b.md)). If the loop's choices add
   nothing, arm B shows it.
2. **0021 item 1 is superseded.** The hypothesis is recorded at checkpoints, not after every
   tool call: before reading (H0), after each read choice that read something (H1, H2), and in
   the answer. Each holds the top three occurrence codes with probabilities, finding codes with
   probabilities, a one-sentence working cause, a stated confidence and an abstain flag (spec
   §5.1). The expected effect is stated for each document in the read choice. 0021 items 2, 3,
   5, 6 and 7 stand; the trail they score and publish is the checkpoints and tool calls of spec
   §4.2 and §8.3.
3. **0021 item 4 is superseded.** The loop does not stop at a confidence threshold. It stops at
   the end of its steps, at the per-case cost cap, or when a call fails after one retry, and it
   records the stop reason (spec §4.4). Abstain is a threshold on a confidence fitted in code,
   chosen on `dev-400` only, as 0021 item 4 required of its threshold
   ([0126](0126-confidence-is-calibrated-in-code.md)).
4. **0023 items 1, 2 and 4 are superseded.**
   - Structured evidence is not put behind tools. H0 is formed from all non-docket evidence the
     case holds ([0122](0122-h0-and-later-triggers.md)). The start facts that item 1 lists
     remain arm A's input.
   - Every offered docket document gets a read-or-skip decision, whatever its size. Item 2 put
     a document behind a tool only when it was large enough for choosing to be a real decision.
   - The masked condition is no longer a headline. It is paused with the staged replay (0123).
     Results are reported in the full condition, and arm A still gives the start-facts-only
     score for every case.

   0023 items 3, 5 and 6 stand: every tool result goes through `split_record`, the preliminary
   narrative is absent from every evaluation, and event date and location are not evidence.
5. **0022 item 4 is reworded** for this loop. The loop is warranted only if arm C beats arm B on
   accuracy at equal cost, or matches it at lower cost. Any one of these four results counts
   against the loop:
   1. arm C reads every offered document on most cases, **or** calls the coding tools in arm
      B's fixed order on most cases;
   2. arm C matches arm B only at the same or greater cost;
   3. arm C's code-fitted confidence is not calibrated on held-out, by the bound S3.2 registers;
   4. the effect the agent states for a document it reads does not agree with the change
      observed after reading it more often than chance.

   As in 0022, if any one holds, it is published whichever way the others go. S3.2's
   registration file defines equal cost (spec §11).
6. **0022 item 5 is withdrawn: P1 to P6.** The withdrawal comes before any measurement of the
   loop. The six stay published in 0022 as written. The reason for each:

   | # | prediction (0022) | why it is withdrawn |
   |---|---|---|
   | P1 | Fatal cases take more steps than non-fatal cases. | The number of steps no longer grows with the docket. One read choice covers every offered document, and the limits are fixed: at most 2 read choices and 6 coding calls (spec §8.2). P1 would test the step design, not the agent. |
   | P2 | In the full condition, arm C matches arm B's accuracy at lower cost on non-fatal cases. | Both arms it compares have changed. Arm B now also calls every coding tool and runs the ordering check (0127). The loop no longer fetches one document per call, and it has no early stop (item 3). Cost against arm B is now result 2 of item 5, on all cases. |
   | P3 | Any accuracy advantage of C over B is concentrated in fatal cases. | It rested on fatal dockets being larger, so that choosing what to read would matter most there. Reading more has since barely helped, and coding has moved the score (Context). The loop's main choice is now how to code, which has no measured link to fatality. |
   | P4 | In the masked condition, C abstains more often than in the full condition, and asks for the missing evidence. | The masked condition is paused (0123). The loop has no tool that asks for evidence, and code, not the model, sets the abstain flag (0126). |
   | P5 | On average, the probability on the true codes rises with each step. | It was written for a hypothesis after every tool call. The loop records one at up to three checkpoints and in the answer, so "each step" no longer names the same thing. The probe's accuracy by checkpoint was noise at n=20: top-1 stayed at 5 of 20 from H0 to H2 in run 1, and went from 5 to 9 in run 2 (Context). How accuracy moves across checkpoints is for S3.2's predictions, after the noise floor (item 7). |
   | P6 | Stated and actual effects agree more often than chance. | It is now result 4 of item 5, stated for documents read. As a result that counts against the loop, it is published whichever way it comes out. Keeping it as a prediction too would count one test twice. |

7. **Nothing about the loop is predicted in S3.1.** New predictions are registered at the start
   of S3.2, in its registration file, before its first run and after the loop's noise floor
   ([0130](0130-the-loops-noise-floor-and-format-gate.md)).

## Why

1. **The choices go where measurement says they can matter.** Reading more moved top-1 by an
   amount whose interval includes zero. The ordering check moved it by several points on both
   answer sets, and most of the hand-read misses were coding.
2. **The test does not change.** Arm B, with the same tools in a fixed order, still decides
   whether the loop's choices add anything (0022 item 1 stands).
3. **A step count and a confidence stop no longer fit.** One read choice covers every document,
   so the number of steps does not measure effort. In the probe, stated confidence tracked how
   much was read, not how often the answer was right (spec §2, lesson 2). A stop at a stated
   threshold would stop on reading, not on being right.
4. **The predictions are withdrawn in the open, before the loop has run.** They were fixed so
   that no one could change them after seeing a result. Withdrawing them now, with a reason for
   each, keeps that purpose as far as it can. The probe, a different flow on 20 cases, gave
   accuracy by checkpoint, which bears on P5; those figures are disclosed above, so a reader
   can judge the withdrawal against them. It scored none of the others. Andy (2026-09-29,
   capitals corrected): "Should we be making predictions before we start to build? I think
   definitely withdraw the others if they no longer make sense".
5. **Effect sizes need the noise floor first.** S2.7's prediction (top-1 on `dev-400` between
   30% and 36%) was fixed before S2.7 measured its own noise floor, and was not met: 25.1%
   (`docs/results/s27-sealed-dev.txt`).

## What this rules out

The session offered Andy three options for this record; C, this record, was chosen. The other
two:

- **A. One record now, with new predictions in it.** Everything would be fixed and published at
  the start. Rejected: the effect sizes would be set before the loop's noise floor exists, so
  any size would be a guess (Why 5), and the probe's look at development accuracy has already
  happened.
- **B. Three records, one per superseded decision.** Each record would state exactly what it
  rules out, which suits the append-only style. Rejected: three pieces of paperwork for one
  design move, and the predictions would still need a home.

Also considered in writing this record:

- **Keeping the design of 0021 to 0023.** On 2026-09-14 it was the best-argued place for
  agency. Rejected: reading more barely helps, coding moves the score, and with no docket yet
  seen to arrive before closure its masked condition has no measured docket mask, which 0023
  requires.
- **Keeping P1 to P6 and measuring them on the new loop.** It keeps the letter of 0022.
  Rejected: each was written for a mechanism that is gone (the table above), so a result either
  way would mislead.
- **Superseding later, in S3.2's registration.** Less to write now. Rejected: S3.1 would build
  and tune a loop while 0021 to 0023 still described another design, and P1 to P6 still stood
  as if they applied to it.
- **A read choice only for large documents** (0023 item 2's rule). Fewer decisions and fewer
  tokens. Rejected: the documents the probe's agent skipped were mostly short ones. It read 77
  and 84 of 108 documents under 2,000 tokens, against 23 of 23 between 2,000 and 10,000 tokens
  (scripted, the two probe reports). The rule would remove most of the choices the agent makes.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).

## Glossary

- **Arm A, B, C**: start facts only, one call; the fixed pipeline, every tool in a fixed order
  and then one answer; the loop (0022, 0127).
- **Checkpoint**: a point where the agent records its hypothesis. **H0** is before reading,
  **H1** and **H2** after each read choice that read something, then the answer.
- **Read choice**: one tool call that gives read or skip, with the expected effect, for every
  offered document.
- **Coding tools**: tools that take codes as arguments and return labels and counts from the
  statistics pool (0125, 0129).
- **Ordering check**: S2.7's second call after the answer, which re-orders its occurrence codes
  (0096).
- **Full condition**: everything a closed case holds in evidence roles, with its whole docket;
  the state of a live case at closure. **Masked condition**: only what a live case would have at
  day *N* (0023).
- **Staged replay**: closed cases released to the loop in steps timed by measured arrival (0123).
- **Noise floor**: how much two identical runs differ by chance alone (0130).
- **Learning probe**: the trial of a loop-like flow on 20 development cases, run before the S3
  specification; it carries no claim.
