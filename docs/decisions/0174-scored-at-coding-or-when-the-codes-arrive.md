# 0174 — Scored at coding, or when the codes arrive

From the S4 design session with Andy, 2026-10-10. Applies
[0159](0159-closure-runs-are-scored-as-counts-only.md)'s scoring to S4, and completes what it left
unscored. Detail: the S4 specification, §6.3 and §6.4.

## Context

1. **The live run is at closure** ([0154](0154-the-live-run-is-at-closure.md)), so the verdict is
   usually in the same record the agent was coded from, withheld from it.
2. **A closed record can lack the NTSB's codes.** 0159 left such a case unscored.
3. **The recorder's store holds no verdict**, by design, so it cannot say when codes arrive.

## Decision

1. **A case is scored when it is coded**, from the same record, by the harness's scoring code.
2. **A case without codes is marked "coded, awaiting the NTSB's codes"**, and its record is fetched
   again each night. When the codes arrive, the night appends to `scores/<date>.jsonl`: both code
   lists, the NTSB's cause statement, the grades, the record's SHA-256 and the date.
3. **After 7 nights without codes, an alert**; the re-check goes on.
4. **Verdict revisions are not followed.** A score, once written, stands.

## Why

1. **It is the roadmap's resolution watcher in the form 0154 leaves it**: a case is scored without
   anyone intervening, at coding or later.
2. **The record's hash** shows which verdict a later score came from.
3. **Not following revisions** keeps a score fixed. Revisions are rare (judgement, not counted).

## What this rules out

- **Waiting to score every case one night later.** One path for all. Rejected: the verdict is
  usually already there, and the board would lag a night for nothing.
- **Following revisions.** More faithful to the NTSB's latest word. Rejected: a score that can
  change undermines the ledger, and the work is unbounded.

## Status

Accepted, 2026-10-10 (Andy: "A sounds simple enough").
