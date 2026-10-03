# 0139 — S3.1's tuning closes without a registered round

From Andy, 2026-10-03, at the end of S3.1 Task 15. Detail: the S3.1 plan's Deviations
(`docs/plans/2026-09-30-s3-1-agent-loop.md`, Task 15 entries from 2026-10-02 on). This changes the
plan's Task 15, which provided for tuning rounds until two were dropped in a row or S3.1 had spent
$20 ([0128](0128-s3-in-three-sub-stages-with-one-spend-line.md)).

## Context

1. **The noise a round has to beat.** Two identical runs of the frozen loop differ by -2.1%
   [-5.9%, +1.6%] on occurrence top-1, on 387 paired cases (`docs/results/s3-noise-floor-dev.txt`).
   A round is kept only when its gain clears that noise
   ([0136](0136-s3-rounds-count-failed-cases-as-wrong.md)).
2. **Before registering a round, Task 15 measured where gains could come from.** Every result below
   is a committed file, read by a rule written before it ran where it had one:
   - **The ordering check adds nothing to the loop's top-1:** +1.3% [-1.5%, +4.1%]
     (`docs/results/s3-check-diagnostic-dev.txt`, [0137](0137-the-ordering-check-as-a-diagnostic-on-arm-c.md)).
     The loop's own `occurrence_usage` calls already do that job.
   - **The NTSB codes identical cause sentences differently.** Cases whose probable-cause sentences
     match word for word share their first occurrence code 37.5% of the time, the event 71.9%,
     the phase 49.2% (`docs/results/s3-coding-consistency-dev.txt`). They share 74.1% of their
     flagged findings at 10 digits (`docs/results/s3-finding-consistency-dev.txt`).
   - **Mechanical precedent does not help.** The five nearest earlier cases hold the NTSB's first
     code in 48 of 266 "always wrong" cases, "in between" by its rule
     (`docs/results/s3-precedent-probe-dev.txt`); their findings fall below the loop's own, and
     level with them on the whole pool ([0138](0138-precedent-pool-whole-for-development.md);
     `docs/results/s3-finding-precedent-dev.txt`).
   - **The loop's finding losses are mostly whole categories:** of run a's 1085 NTSB flagged
     findings, 46.0% are in a category the loop never named, 19.6% lose the item and 7.4% the
     modifier; the item misses do not follow the pool's habit (21.6%), so item choice reads as
     case-specific (`docs/results/s3-finding-misses-dev.txt`).
   - **The loop is level with the full fixed pipeline on development cases.** Against S3's arm B
     (S2.7's answer, every coding tool in a fixed order, one more answer, the ordering check), run
     a and run b: top-1 -1.0% [-5.3%, +3.3%] and +1.0% [-3.6%, +5.6%]; finding recall@10 +0.4%
     [-2.0%, +2.9%] and -1.5% [-3.9%, +0.6%]; top-3 -11.4% [-16.0%, -6.9%] and -12.8% [-17.9%,
     -8.2%] (`docs/results/s3-armc-a-vs-s3-armb-full-dev.txt`, `-b-`).
3. **The candidates left.** "Code the starting event, not the result", "search, not confirm",
   dropping S2.7's round 3 guidance, and small findings fixes (who acted; "not determined"). Each
   was expected to move top-1 by a few points at most, inside the noise above.

## Decision

1. **Task 15 ends with no registered round.** Its probes, diagnostic and comparisons, each a
   committed results file, are S3.1's tuning record.
2. **The loop frozen at `fd6053f`** (prompt `s3-v1+ge17fecdc66ec+p947fac1c86a4`) is S3.1's
   result, and the loop S3.2 measures.
3. **The candidates stay written down** in the plan's Deviations and this record, for any later
   stage to register.
4. **The precedent tool is not a round.** It is a new capability, placed by
   [0140](0140-the-precedent-tool-after-s4-as-a-measured-v2.md).

## Why

1. **No candidate's expected gain clears the noise.** Two identical runs differ by up to about 4
   points of top-1; no measurement points to a change worth more.
2. **The measurements already say where the limits are**: the NTSB's own spread on occurrence
   codes, the ordering job already done, precedent flat when used mechanically, and finding losses
   that are mostly which kind of cause, not how it is coded.
3. **A dropped round costs about $2 and three hours** and would confirm what the probes show. The
   project's priority is the demo page; S3.2 to S4 come sooner.

## What this rules out

- **Running the planned rounds until the stop rule.** The strongest case: registered rounds are
  the plan's own tuning method, and "tried, read against the noise, dropped" is direct evidence
  for the write-up. Its cost: about $4–6 and one to two days for two rounds the evidence does not
  support. Rejected for that reason.
- **Keeping S3.1 open for the precedent tool.** It would mix tuning with a new capability (0140).

## Status

Accepted, 2026-10-03 (Andy: "Close S3.1 now", choosing to close S3.1 with no tuning round
registered).

## Glossary

- **Round**: one registered change, run on `dev-400`, kept only if its gain clears the noise.
- **Noise**: the difference between two identical runs of the loop.
- **Probe**: a free, offline measurement script; it sets no bar and tunes nothing.
- **Arm B (S3's)**: the fixed pipeline: S2.7's answer, every coding tool in a fixed order, one
  more answer, then the ordering check.
