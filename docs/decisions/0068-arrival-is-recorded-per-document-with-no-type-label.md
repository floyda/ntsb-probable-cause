# 0068 — Arrival is recorded per document with no type label; the mask's docket rule is presence and count

## Context

The agency design (`docs/specs/2026-09-14-agency-hypothesis-trail-design.md` §6.2) says the
masked condition uses "the number of days from the event to the first appearance of each
field and each document type". S2 then measured the title-based type label: 58–72% accurate
on a hand-check, 16% of development documents in `other`, and removed every job it had in the
live path (0054, 0055, 0056). Arm B attaches every readable document (0052), so the agent
receives the whole docket, and a live agent would receive it as it arrives. The recorder never
downloads a document (0061), so a type could only ever be guessed from the title.

## Decision

The recorder records arrival per document, keyed by document number (0062), and stores no
type label. The masked condition's docket rule becomes "docket present, with K documents, by
day N", from the distribution the recorder measures. With a first-seen interval per document,
S3 can replay a closed case's docket in arrival order. How the mask groups arrivals beyond
presence and count is decided in S3, when the numbers exist. This amends agency design §6.2.

## Why

1. **A label deemed unreliable has no place in a store of observations.** Andy's objection,
   verbatim in substance: the label was found unreliable, so the recorder should neither use
   it nor care about it.
2. **Presence and count are what a live agent actually gets.** Every readable document goes to
   the agent, drip-fed as it arrives; the mask should cut evidence the same way.
3. **Per-document intervals are the finest fact the page supports**, and any coarser grouping
   can be computed from them later. The reverse is not true.

## What this rules out

- **A mask keyed on document type.** Commits the evaluation to a label wrong one time in
  three.
- **Deciding the mask's grouping now.** S3 will have real arrival data; deciding earlier is
  guessing.

## Status

Accepted, 2026-09-22. Amends the agency design §6.2.
