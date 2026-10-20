# 0181 — S4's closing rule

From the S4 design session with Andy, 2026-10-10. Detail: the S4 specification, §15.

## Context

1. **The roadmap's done means**: "a case closing causes its standing prediction to be scored without
   anyone intervening". Decision [0154](0154-the-live-run-is-at-closure.md) moved the run to
   closure.
2. **Fresh closures arrive in bursts**: S3.3 saw 47 in 14 nights, all on three dates (decision
   [0157](0157-s33-codes-closures-through-a-queue.md) context 3).

## Decision

S4 closes when all seven hold:

1. `VERSION_1` is re-pinned with continuity shown, before any cloud night (decision 0168);
2. the scheduled task has run the backfill until it drained, with no one intervening;
3. at least one fresh closure has been coded and scored by the scheduled task on the night after it
   closed;
4. the ledger job has committed those runs' manifest hashes;
5. a test alert email has been received, and the missed-night alarm has been shown to fire by a
   deliberate state test;
6. an export built from the real store passes the `board/1` schema, and the counts-only S4 results
   file is committed from its script;
7. the Mac's key is removed.

If no fresh closure arrives within 14 days after the backfill drains, S4 closes on the rest and
says so.

## Why

1. **Each condition is a part of the done means seen working once**, unattended.
2. **The time limit** keeps S4 from waiting on the NTSB, as S3.3's did, because Andy's priority is
   S5.

## What this rules out

- **Closing at the first cloud night.** Sooner. Rejected: it would not show a fresh closure handled
  with no one watching.
- **Waiting for a week of clean nights.** Stronger evidence. Rejected: S5 waits for it.

## Status

Accepted, 2026-10-10 (Andy: "A sounds fine because once we have the export schema we can start
building the static site").
