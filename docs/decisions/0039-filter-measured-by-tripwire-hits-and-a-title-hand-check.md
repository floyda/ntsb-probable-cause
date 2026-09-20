# 0039 — The docket filter is measured by tripwire hits, and its type labels by a title hand-check

Settles how S2's filter lists are reviewed and their error rate measured, which the
roadmap's S2 entry ("a reviewed allow-list and a measured error rate") left to S2. Depends on
0038, which reduced the filter's job.

## Context

After 0038, every docket document is evidence and the filter has two jobs left:

1. **Catch the NTSB's case-level write-up if it appears in a docket.** The roadmap warns that
   a closed docket can contain NTSB-written factual reports. The spike's shape probe found no
   such title in 160 development listings (`../ntsb-spike/scripts/docket_shape_probe.py`).
   Rare is not never, and one miss puts the answer's first half in front of the model.
2. **Sort documents into types** for the provenance header (0038) and for arm B's filter
   (0022). The spike's title categories are regular expressions written in a day, never
   checked.

The roadmap's wording assumes documents are labelled by hand and the filter is scored against
the labels. That costs hours of reading and the labels are judgements. For job 1 a cheaper
and harder measure exists: the withheld text itself.

The tripwire's minimum sentence length (20) was measured when no evidence field held free
text (S0 As-built, "Tripwire coverage limits"). Docket text will produce hits from ordinary
sentences. The roadmap already requires re-measuring the threshold on docket text.

## Decision

1. **Job 1 is measured by the tripwire, not by labels.** On a fixed sample of development
   dockets, every readable document is passed through the tripwire against its case's
   withheld narratives and codes. A document containing a withheld sentence is a **hit**. The
   deny-list of titles is scored against hits: a hit whose title is not on the list is a
   **miss**; a listed title with no hit is a **false deny**. Both are published by title
   category. The withheld text is the label; nobody labels documents.
2. **The deny-list starts empty and is filled only by hits.** No title goes on it by
   guesswork. If the sample produces no hits, the published result says so, and the tripwire
   remains the only defence, which it is in any case.
3. **Job 2 gets a hand-check of titles only.** The type classifier is run over every title in
   the sample; Andy reads a seeded random sample of 60 titles with their assigned type and
   marks each right or wrong. Titles hold no personal data, so the sheet is committed under
   `tests/fixtures/`, and the error rate is published with the header the agent reads.
4. **The sample is the docket listings of `dev-400`** (0026), fetched once. Listing pages and
   PDFs are cached under `data/`, never committed; per-docket statistics go to a results
   file. One fetch serves the shape numbers, the filter measurement, the threshold
   re-measurement and the fixture pool (0037).
5. **The tripwire threshold is re-measured on docket text first**, before the deny-list is
   scored, by the same rule S0 used: the lowest minimum sentence length with zero hits on
   ordinary evidence, reported with the hit counts at each candidate length. The measurement
   in item 1 uses the re-measured threshold.

## Why

1. **A hit says what a document contains; a label says what it looks like.** The write-up we
   fear is the one that contains the record's text, and the tripwire finds exactly that.
2. **It costs Andy twenty minutes, not hours,** and the part he checks is the part only a
   person can check: whether a title's type is right.
3. **An empty deny-list is an honest result.** A list filled by guesswork would be a filter
   nobody measured.
4. **Without item 5 the miss count is noise.** A threshold set with no free text in evidence
   will fire on "The pilot was not injured."

## What this rules out

- **Hand-labelling a stratified sample of documents as evidence or synthesis**, the
  conventional way to score a classifier. It would catch a write-up whose wording differs from
  the record's narrative, which the tripwire cannot. Rejected on cost and on what it measures;
  the paraphrase gap is stated in the published result rather than hidden behind a label that
  might not have caught it either.
- **Scoring the filter on the spike's 160-listing sample.** Already fetched once. Rejected:
  those listings are not cached here, the sample was drawn for a different question, and
  `dev-400` is the population every other development measurement uses.
- **Skipping the threshold re-measurement** because 20 had zero hits corpus-wide. Rejected
  for reason 4.

## Status

Accepted, 2026-09-17 (Andy).

**Amended, 2026-09-20 (appended; nothing above is edited).**

- **Item 3's `ARM_B_TYPES` is removed** by [0052](0052-arm-b-attaches-every-readable-document.md).
  Arm B admits every document extraction found text in. There is no type list to set.
- **Item 5's threshold rule was tried and rejected.** It required the lowest minimum sentence length
  with zero hits. The sweep was run (`docs/results/s2-docket-leak.txt`) and reaches zero only at 400
  characters, which is a paragraph, not a sentence — so choosing it would have disabled the sentence
  check for every source and role. `MIN_SENTENCE_CHARS` stays 20 and
  [0050](0050-tripwire-skips-factual-narrative-sentences-in-docket-documents.md) solves the problem
  with a source-scoped exemption instead.
- **Item 1's measurement was outstanding until 2026-09-20** and is `docs/results/s2-threshold.txt`.
  Until it existed, `docket/filter.py` cited a file — `docs/results/s2-filter.txt` — that had never
  been produced.
- Item 2's rule stands: the deny-list is filled only by tripwire hits, never by judgement.
