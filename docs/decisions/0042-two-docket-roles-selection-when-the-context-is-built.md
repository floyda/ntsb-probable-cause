# 0042 — Two docket evidence roles; the documents attached are chosen when the context is built

Settles how a subset of a docket's documents is sent, given that the evidence schema has fixed
keys (0016 layer 1) and a docket holds a variable number of documents. Depends on 0041. Written
with the S2 specification (§6.2).

## Context

Arm B's filter (0022), a future loop step "read document 3" (S3), and the masked condition
(0023) each need some documents and not others. Exclusion sets work by role, and one role per
document is impossible with fixed keys.

## Decision

1. `EvidenceRole` gains `DOCKET_LISTING` (titles, types, page counts) and `DOCKET_DOCUMENTS`
   (a list of attached documents, each with its provenance header and text).
2. The set of documents to attach is an argument to the attach step (0041). Arm A attaches
   none and excludes both roles; arm B attaches what its filter admits, in rank order, up to
   the cap (0043); a loop step attaches the one it asked for; the masked condition attaches
   what had appeared by day N once the recorder has arrival numbers, and nothing before then.
3. The chosen set is written into the step record's `arguments`, so every run is reproducible
   from its records.

## Why

1. **The split stays the one place that checks, and the attach step becomes the one place
   that chooses.** Each is small enough to test on its own.
2. **The split's signature does not change** with each new source.
3. **The listing on its own is cheap**, so in S3 reading a document is a choice made after
   seeing the titles (roadmap §11).

## What this rules out

- **Selection inside the split**: a `documents` parameter that trims the list after the
  context carries every document. One place decides everything the model sees, but the
  splitter's signature grows per source, the guard needs a rule for partial values within a
  role, and the same set is passed twice.
- **One role per document.** Impossible under fixed keys.

## Status

Accepted, 2026-09-18 (Andy).
