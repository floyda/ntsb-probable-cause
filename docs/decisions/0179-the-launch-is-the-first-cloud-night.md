# 0179 — The launch is the first cloud night; no early runs

From the S4 design session with Andy, 2026-10-10. Applies
[0155](0155-the-board-is-backfilled-from-the-recorders-first-night.md) to S4. Detail: the S4
specification, §6.2.

## Context

1. **The board is backfilled from 23 September 2026** (0155).
2. **S3.3 coded 60 cases on the Mac** as a rehearsal, and left 2 fresh closures queued (scripted,
   `docs/results/s33-live-shadow.txt`; S3.3 As-built, carried item 8).
3. **No docket arrived before its case closed**: 46 of 46 at closure (scripted,
   `docs/results/s5-recorder-report-2026-10-06.txt`).

## Decision

1. **The launch is S4's first cloud night.** The backfill list, every closure from 23 September 2026
   to that night, is fixed then, written to the run folder with its count and SHA-256, and its
   manifest's hash goes in the ledger. It is coded oldest first, at about 30 cases a night.
2. **The Mac's rehearsal folders stay on the Mac** and are never uploaded; their cases are coded
   again in the cloud.
3. **No early runs** on open cases. The export carries the count of open cases holding a docket.

## Why

1. **One system, one record**: every result on the board comes from the cloud task, under the same
   checks and the same ledger.
2. **Early runs would have almost nothing to read** (the count above), at a cost.

## What this rules out

- **Uploading the Mac's results.** Saves about $0.30 (estimate). Rejected: they were made under
  another setup, outside the ledger.
- **Early runs on cases with a docket.** Rejected: about 5 cases, and S5 shows no answers before
  closure ([0154](0154-the-live-run-is-at-closure.md)).

## Status

Accepted, 2026-10-10 (Andy: "A", twice).
