# 0078 — The narrative-coverage mark, at 50% of one document, is set in S2.6

Takes up [0071](0071-the-coverage-threshold-is-deferred-to-s3-as-a-mark-not-a-refusal.md), which
deferred the question to the start of S3, and moves it to S2.6.

## Context

0050 exempts factual-narrative sentences inside docket documents, so a document carrying most of
the narrative passes the guard. 0071 recorded Andy's reframing: mark such cases, do not refuse
them, and score the marked group against the rest. `docs/results/s2-narrative-coverage.txt`
measured, over 379 development cases, the largest share of narrative sentences inside one
document: 23 cases reach 25%, 3 reach 50%, 2 reach 80%, none 99%.

S2.6 re-measures arm B on held-out, producing the bar S3 must beat. If the mark arrived in S3,
S3 would open by changing its own bar.

## Decision

1. For each case, the largest single-document share of factual-narrative sentences is stored as
   a number.
2. A case at or above **50%** is marked `narrative_coverage`, by the same mark mechanism as 0077.
3. The marked group's row carries a note that at about three development cases it makes those
   cases visible and cannot show whether coverage inflates the score.

## Why

1. **50% catches documents holding most of the narrative.** At 25% the mark covers 23 cases and
   blurs; at 80% it covers 2.
2. **The stored share makes the line cheap to move.** Any other cut can be reported later
   without re-running.
3. **The bar should carry the mark from the start.**

## What this rules out

- **A refusal threshold** (the S2 close-out's 80% recommendation). Already rejected by 0071.
- **Leaving it to S3.** Rejected for the bar reason above.

## Status

Accepted, 2026-09-23 (Andy).
