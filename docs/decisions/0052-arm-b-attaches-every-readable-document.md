# 0052 — Arm B attaches every document that yielded text

Supersedes [0048](0048-arm-b-ranks-by-each-documents-measured-size.md) item 4's photograph
exclusion and the `ARM_B_TYPES` set that [0039](0039-filter-measured-by-tripwire-hits-and-a-title-hand-check.md)
established. The ranking 0048 fixed (each document's own measured size, ascending) is unchanged.

## Context

Andy, 2026-09-20: *"Part of me feels like we could be placing each file into much cleaner
buckets focused on how much the model will see in prose."*

Arm B admitted a document if its title-derived category was in `ARM_B_TYPES` — every category
except `photos`. That exclusion was a **proxy**: a guess, from the title, that a photograph has
no text worth reading. Whether a document has text is not a guess. It is measured during
extraction and already recorded on every document as `readable_pages`, and a document is only
given status `"read"` when extraction found text.

The proxy was measured against the thing it stands for
(`scripts/filter_compare.py`, `docs/results/s2-filter-compare.txt`, 384 development cases —
the other 17 are refused by 0050). Both rules were run through `runner.prepare_case`, the real
cap loop rather than a copy:

| | current filter | every readable document |
|---|---|---|
| documents attached per case, median | 4 | 4 |
| estimated tokens per case, median | 6,482 | 6,488 |
| the same, p90 | 30,016 | 30,016 |
| the same, maximum | 123,188 | 123,188 |
| cases stopped by the cost cap | 0 of 384 | 0 of 384 |

- Dropping the exclusion attaches **270 more documents, in 104 of 384 cases (27%)**.
- It displaces **nothing**: zero documents the old rule attached are lost.
- It costs **six tokens** at the median, and nothing at all at p90 and maximum.

The proxy was also wrong in a way already fixed: until `e9dc94e`, 225 documents landed in
`photos` because the listing's `Text/Image` file-type string contains the word *image*, and 138
of them held readable text (`docs/results/s2-doctype.txt`). Among them were witness statements,
toxicology reports and examination summaries.

## Decision

1. **Arm B attaches every document with status `"read"`.** `ARM_B_TYPES` is removed. Admission is
   the extraction outcome, not the category.
2. **Ordering is unchanged**: each document's own `estimated_tokens`, ascending, ties broken by
   listing index (0048).
3. **The `no-submissions` variant stays**, still keyed on the `party_submission` category, because
   0038 item 4 requires arm B to be run with and without submissions. The `unfiltered` variant is
   removed: it is now identical to the published rule.
4. **The category survives for three things only**: the `no-submissions` variant, the deny-list
   (0039, measured empty), and the header label (0051) plus two step-log lines. It is no longer
   an admission filter.
5. Photograph-only documents are still never fetched: `ListingEntry.is_photo_only()` uses the
   listing's own photo column, which is a declared fact rather than an inference. It is true for
   146 of 3,790 cached documents.

## Why

1. **A measured fact beats an inferred one.** "Did extraction find text" is the question the
   exclusion was approximating. We have the answer for every document.
2. **The proxy cost evidence and bought nothing.** 270 documents in 27% of cases, for six tokens
   at the median. The cases it silently thinned are not random — they are the ones with
   scanned material, which correlates with older and less well documented accidents.
3. **It removes a whole class of failure.** A title misread can no longer delete a document from
   arm B. It can still mislabel one, which 0051 reduced to a label the listing corroborates.
4. **It is what a fixed pipeline should be.** Arm B is the bar the loop must beat, and 0022
   requires the comparison to be fair. A bar handicapped by a title-matching heuristic makes the
   loop look better than it is — the direction of error this project exists to avoid.

## What this rules out

- **Excluding photographs by category at all.** Rejected on the measurement above.
- **Excluding a document because extraction found only a little text.** Rejected: that is a new
  threshold, chosen without a measurement, and the cap already bounds total size. See the
  readability boundary note below, which must be settled first.
- **Removing the category entirely.** Rejected: three uses remain (item 4), each with its own
  record. Removing it would need those three retired first.
- **Removing the deny-list because it is empty.** Out of scope: 0039 governs it and it is a named
  candidate in the S2 close-out audit.

## Depends on an open defect

`classify_pages` calls a document a scan when its mean characters per page is **under** 50, while
`readable_pages` counts a page readable when it has **more than** 50. A document averaging exactly
50 is therefore `"partial"`, gets status `"read"`, and has zero readable pages — so this decision
would attach it with no text. Confirmed by direct test; frequency in the corpus not yet measured.
The fix is to define readability once and derive the classification from it. Until then, this
decision's "every document that yielded text" is true of every document except that boundary.

## Status

Accepted, 2026-09-20 (Andy: "yes take the simplification next, implement that").

## Correction, 2026-09-20 (appended; nothing above is edited)

The opening line mis-cites both records it claims to supersede, and `docs/decisions/README.md`
repeated the error:

- The photograph exclusion and `ARM_B_TYPES` are **0048 item 3**, not item 4. Item 4 is the title
  hand-check, which only *grades* the exclusion as one of its three questions.
- **0039 never establishes `ARM_B_TYPES` and never mentions it.** 0039's subjects are the deny-list
  and the measurement that fills it. `ARM_B_TYPES` came from the S2 specification and plan.

Read the opening line as: *supersedes 0048 item 3's photograph exclusion and the `ARM_B_TYPES` set
the S2 specification established; narrows 0039 item 3, which set arm B's admitted types.*

Found by the whole-branch review. It matters because a reader following a supersession chain — the
reader rule 8 exists to serve — would land in the wrong paragraph of 0048 and on a record that
never said the thing.
