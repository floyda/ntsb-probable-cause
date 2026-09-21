# 0055 — The document header carries the listing number, not a category label

Amends [0051](0051-the-document-header-drops-the-provenance-clause.md) item 3, which kept the
category label when the provenance clause was removed. The header's *shape* is unchanged — an
identifier, a page count, a readability fact. Only the identifier changes.

## Context

0051 removed the provenance clause after Andy's hand-check measured it at 58-72% accurate, on the
argument that the agent is already given the whole docket listing, so a clause the listing
corroborates is redundant and a clause it does not is a guess. The same record kept the category
label, on the narrower ground that the hand-check had not graded it.

Two facts, surfaced by the whole-branch review, undo that reasoning:

1. **The label is now the only place a guess reaches the model.** After 0052 the category no
   longer admits or excludes anything, and after 0054 it no longer selects a run variant. Every
   other use is a published statistic. The label is the last one that puts an inference in front
   of the agent.
2. **604 of 3,790 development documents — 16% — fall to `other`**, whose label is the empty
   "Docket document" (`docs/results/s2-shape-dev.txt`). For one document in six the label already
   says nothing.

And a gap nobody had noticed: **the attached text carries no way back to the listing.**
`listing.render_listing` gives the agent a numbered table — `3. WITNESS STATEMENTS (Text/Image,
4 pages, 0 photos)` — but `attach.header` renders neither the index nor the title, so an agent
reading a document's text cannot tell which listing row it came from. `render_document` already
receives the whole record, including `entry.index` and `entry.title`, and uses neither.

Andy, 2026-09-20: *"I thought we had removed this categorisation, and if the guess is still there
then it should be removed."*

## Decision

1. The header's identifier is the **listing index**, not the category label:
   - every page readable: `Docket item 3, 11 pages.`
   - partly readable: `Docket item 3, 11 pages, of which 4 held readable text.`
2. `_LABELS` is removed from `docket/attach.py`.
3. The page count and the readability clause (0051 item 2) are unchanged, and so is the rule that
   the clause appears only when some pages could not be read.

## Why

1. **Three facts, no inference.** The index and the page count come from the listing; the
   readability count is measured at extraction. Nothing in the header is now a guess.
2. **It is 0051's own argument, applied to the part 0051 exempted.** Where the listing already
   says it, repeating it is redundant; where the listing does not, we are guessing. The title and
   the document type are in the listing. The index is the join.
3. **It closes a real gap for free.** The agent gains the ability to tie attached text to its
   listing row — which it did not have — in the same change that removes the guess.
4. **It makes one sentence true**, and that sentence is the one that has to be defensible: *the
   classifier is a statistic this project publishes about dockets. It is never shown to the
   model, and it never decides what the model reads.*

## What this rules out

- **Keeping both the index and the label.** Nothing would be lost, but the guess would stay in
  front of the model and one document in six would still be labelled "Docket document". The
  sentence in Why item 4 would remain false.
- **Carrying the title in the header instead of the index.** Rejected as duplication: the title is
  already in the listing, verbatim, and repeating it per document spends tokens to restate what
  the index points at. The index is the smaller fact that recovers the larger one.
- **Removing the header entirely.** Rejected: the page count and the readability clause are the
  only place the agent learns how much of a document it is not seeing, which bears on the abstain
  path.

## Relationship to 0051

0051 item 3 kept the label because removing it would have been "a change with no measurement
behind it". That argument was weak and is withdrawn: *keeping* it had no measurement behind it
either, and this record replaces it with facts rather than with nothing. 0051's items 1, 2 and 5
stand unchanged, and its measurement of the provenance clause is untouched.

## Status

Accepted, 2026-09-20 (Andy: "if the guess is still there then it should be removed and therefore
go with C1 … it does change it in respect to the label being in that listing sentence").
