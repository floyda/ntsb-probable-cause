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
3. **The category keeps exactly three jobs**: the photograph exclusion in `ARM_B_TYPES`, the
   deny-list, and the provenance header (`attach.header`, decision 0038). It is not consulted for
   selection, and no longer for order.

   *Corrected the same day.* This item first said "exactly two jobs" and omitted the provenance
   header, which reads `record.category` at `attach.py:67`. That was an error in this record, not
   in the code, and it mattered: the header is the one use that puts words in front of the model,
   so a misclassification there is active misinformation rather than a suboptimal ordering. It is
   the most consequential of the three, and it is now measured as such.
4. **The hand-check (0039 item 3) measures those three jobs, not twelve-way agreement.** For each
   sampled title Andy marks three questions, one per job:
   - *Is this a photograph?* — grades the `ARM_B_TYPES` exclusion.
   - *Could this document contain the investigators' conclusions?* — grades the deny-list.
   - *Whose account is this?* — one of **`investigation` / `party` / `independent` / `recorded` /
     `unclear`** — grades the provenance header directly, in the terms the header itself uses.

     *Fifth option added 2026-09-19, on Andy's question: "who constitutes each of the different
     parties? i.e. where does an air traffic control transcript land?"* It exposed a real
     ambiguity. Formally, the FAA **is** a party to an NTSB aviation investigation, so by status an
     ATC transcript is a party document. But that is not what the label is for. A pilot's accident
     report form is an interested person's *account*; a manufacturer's technical report is an
     interested organisation's *analysis*; an ATC transcript is neither — it is a verbatim capture
     of what was said at the time, in which nobody is arguing anything.

     So the question is *whose account is this*, not *who holds party status*, and `recorded` names
     the documents that are nobody's account: ATC audio and transcripts, radar and ADS-B tracks,
     engine data downloads, photographs. The distinction is the one that matters most for weighing
     a document, and collapsing it into `party` would lose it. It also decides the hard case
     cleanly: a transcript is `recorded`, while an FAA inspector's written statement is `party`,
     because there the FAA is telling you something.

     The same five words are used by `attach.header`'s provenance line, so a mark and a label are
     directly comparable. A vocabulary used for grading that differs from the vocabulary being
     graded would measure nothing.

   Each question maps to exactly one use, so each produces a number that decides something. None
   of them asks whether one of twelve labels is the best fit, which would have produced one blurred
   figure no decision rested on. The sample is stratified by category so the rare and the messy ones
   are actually measured; a flat random 60 over twelve categories would have given about five each
   and none of the 12 party submissions.

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

**Superseded in part, 2026-09-20 (appended; nothing above is edited).**

Item 3 said the category keeps exactly three jobs: the photograph exclusion, the deny-list and the
provenance header. Two are gone.
[0052](0052-arm-b-attaches-every-readable-document.md) removed the photograph exclusion and
`ARM_B_TYPES` with it, after measuring that dropping it attaches 270 more documents in 27% of cases,
displaces none, and costs six tokens at the median — which refutes this record's Context, where the
exclusion is argued to be "real work, not redundancy".
[0051](0051-the-document-header-drops-the-provenance-clause.md) and
[0055](0055-the-document-header-carries-the-listing-number.md) removed the header's label
altogether. [0054](0054-the-party-submission-comparison-is-retired.md) removed the run variant.

Item 2's ranking — each document's own `estimated_tokens`, ascending, ties broken by listing index —
is unchanged and is still what `arm_b_documents` does. Item 4's hand-check was carried out; its
results are in `docs/results/s2-handcheck.txt` and are the evidence for 0051.
