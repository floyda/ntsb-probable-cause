# 0048 — Arm B ranks by each document's own measured size, and the category keeps only two jobs

Supersedes item 2 of [0043](0043-arm-b-adds-whole-documents-in-rank-order-up-to-the-cap.md);
items 1 and 3 of 0043 stand unchanged. Taken 2026-09-19, after the first measurement over all 401
development dockets, on Andy's reading: *"I do wonder if categorising is really worth it if the
model will pick in title anyway"* and *"let's keep this simple and measured"*.

## Context

The title classifier (`docket/classify.py`) was carrying four jobs. Measured on 3,790 real
documents across 401 dockets, it is weaker than the design assumed: **561 documents — one in seven
— fall to `other`**, and hand-inspection found errors of several distinct kinds. Shop CCTV
(`Convenience Store Video of the Accident`) classified as air-traffic data because the pattern
contains "video". `Excerpts From Airplane's Maintnenance Records` classified as a manual, because
the NTSB's own title misspells "maintenance" so the maintenance pattern never fired. A
manufacturer's service letter and a repair station's damage estimate both fell to `other`.

Rather than improve a classifier the project would then have to defend, the question asked was what
each of its jobs is actually worth. Two answers changed:

- **Selection.** `render_listing` gives the model the raw title, the NTSB's own file type, the page
  count and the photo count. It does **not** give it the category. The agent already chooses from
  titles, and a capable model reads a title better than a regular expression does.
- **Rank order.** 0043 item 2 ranks by each *type's median* estimated tokens. But every document's
  own estimated token count is measured directly, per document. A category median is a proxy for a
  number already in hand, and it inherits every misclassification above.

Two other jobs were tested and **kept**, one of them against the author's own initial claim that it
was redundant:

- **Excluding photographs.** Of 250 photo-classified documents checked, **122 carry enough
  extracted text to be attachable** — captions, stamps, embedded labels — median 64 tokens but with
  a tail to 13,634. Without the category those would be attached: about 74,000 tokens across the
  250 sampled, against a median docket of 6,676. The exclusion is real work, not redundancy.
- **The deny-list.** A document holding the investigators' conclusions fails the whole case closed.
  Refusing that *kind* of document before it is attached means the case is still answered from the
  rest of the docket. That can only be done at the level of a category.

## Decision

1. **Arm B ranks by each document's own `estimated_tokens`, ascending, then by listing index.**
   The category plays no part in the order. `ARM_B_RANK` is removed.
2. **Ascending still means smallest first**, for 0043's reason unchanged: it fits the largest number
   of whole documents under the cap.
3. **The category keeps exactly two jobs**: the photograph exclusion in `ARM_B_TYPES`, and the
   deny-list. It is not consulted for selection, and no longer for order.
4. **The hand-check (0039 item 3) measures those two jobs, not twelve-way agreement.** For each
   sampled title Andy marks two questions — *is this a photograph?* and *could this document
   contain the investigators' conclusions?* — rather than whether one of twelve labels is best. The
   sample is stratified by category so the rare and the messy ones are actually measured; a flat
   random 60 over twelve categories would have given about five each and none of the 12 party
   submissions.

## Why

1. **A number already measured beats a proxy for it.** Ranking by the real size of each document is
   simpler, more accurate, and cannot be corrupted by a misclassification.
2. **It shrinks what has to be right.** The classifier's error rate stops mattering for order and
   selection entirely, and is confined to two questions that are easier to ask and easier to grade.
3. **It makes the hand-check honest.** Grading twelve-way agreement would have produced one blurred
   number that no decision depended on. Grading the two jobs produces two numbers that each decide
   something.
4. **It is smaller.** The published rank order, the per-type median measurement on `dev-400` and the
   `ARM_B_RANK` constant all disappear, and nothing takes their place.

## What this rules out

- **Improving the title classifier as the answer.** It may still be improved, but the stage no longer
  rests on it, and any improvement must be measured rather than asserted.
- **Ranking by importance rather than size.** Tempting — read the most informative first — but it
  needs a measured notion of informativeness that does not exist, and smallest-first has the
  published, checkable property of maximising how much of the docket is read.
- **Publishing a rank order at all.** There is nothing left to publish: the order is a function of
  each document's own measured size.

## Status

Accepted, 2026-09-19 (Andy). Supersedes 0043 item 2.
