# 0176 — The docket is frozen by its hashes

From the S4 design session with Andy, 2026-10-10. Extends
[0160](0160-the-live-package-its-run-folders-and-the-open-split-fence.md)'s closure record.
Detail: the S4 specification, §9.2 and §9.3.

## Context

1. **S3.3 deleted a case's documents after its run** (0160, cleanup), and its closure record kept
   only each document's title and status (S3.3 As-built, carried item 5).
2. **The NTSB can add or replace documents later**, so "the docket as published at closure" cannot
   be shown afterwards.

## Decision

1. **The closure record becomes `live-closure/2`**: version 1's fields, plus the SHA-256 of each
   fetched file, plus, for each model call, the SHA-256 of the request's messages, in call order,
   plus the replying models and providers (decision 0169).
2. **No document and no sent text is kept.**

## Why

1. **An audit trail is enough** (Andy: "B makes the most sense, an audit trail is more than
   enough"). Anyone holding the NTSB's file can show it is the one coded from.
2. **Nothing grows**: hashes are bytes, documents are megabytes, and kept text would be open-split
   evidence held beside the board.

## What this rules out

- **Keeping the documents in the bucket.** Shows the docket itself. Rejected: storage that grows
  with every case, and copies of public documents to look after.
- **Titles and statuses only, as S3.3 did.** No change. Rejected: no proof of which file was read.

## Status

Accepted, 2026-10-10 (Andy).

## Amended, 2026-10-12 (appended; nothing above is edited)

- The hashes are taken before the first model call and kept in the run folder as `dockets.json` (hashes and positions only), and the closure record takes them from there, not from a later fetch ([0185](0185-a-resumed-night-pays-what-is-left-and-codes-the-same-docket.md), item 2).
