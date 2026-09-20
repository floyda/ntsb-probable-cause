# Title hand-check: what to mark

> **Completed 2026-09-20, and every mechanism it graded has since been removed.** The marks are in
> `title_handcheck.filled.csv`; the scored result is `docs/results/s2-handcheck.txt`, produced by
> `scripts/score_handcheck.py`. This file is kept as the instructions Andy actually worked from,
> because the sheet is the evidence for decisions 0051, 0052 and 0056 and a reader should be able
> to see what the marker was asked. **It is not a live task.** What the three questions graded,
> and what became of each:
>
> - `is_photo` graded arm B's photograph exclusion. **Removed** (0052): the exclusion was a
>   title-based guess at "this has no text"; dropping it attaches 270 more documents in 27% of
>   cases, displaces none, and costs six tokens at the median. Arm B now attaches every document
>   extraction found text in.
> - `could_hold_conclusions` graded the deny-list. Marked **no on all 60 rows**. The deny-list was
>   later **removed** outright (0056), after the tripwire measurement showed its hits spread across
>   8 of the 12 categories with 33 of 56 in `other`.
> - `author` graded the provenance header's "whose account is this" clause. The clause agreed with
>   the marks on 32 of 55 rows — 58%, and 58-72% under every more generous reading — so it was
>   **removed** (0051), and the category label that remained went with it (0055). The header now
>   carries the listing index, the page count, and how many pages held readable text.
>
> The sheet did its job: it is the measurement behind three removals. Nothing below needs doing.

This sheet is a stratified sample of about 60 document titles seen in the dev-400 docket
cache, one row per title. It exists to measure three things the title classifier
(`docket/classify.py`) is actually used for (decision 0048 item 4), not whether its twelve
category labels are individually correct.

For each row, fill in the four blank columns:

- `is_photo` -- is this a photograph? (`y`/`n`)
  Grades arm B's photograph exclusion: photographs are never attached as evidence text.
- `could_hold_conclusions` -- could this document contain the investigators' own conclusions
  about the cause, as opposed to the evidence they gathered? (`y`/`n`)
  Grades the deny-list: a document of that kind is refused before it is attached, so the case
  is still answered from the rest of the docket.
- `author` -- **whose account is this** -- not who formally counts as a party to the
  investigation, but whose telling of events the document carries. One of:
  - `investigation` -- written by the NTSB or its investigators, e.g. an exam or factual report.
  - `party` -- an account from a party to the investigation, e.g. the pilot, operator or a
    manufacturer.
  - `independent` -- an account from someone with no stake in the case, e.g. a medical examiner
    or weather service.
  - `recorded` -- nobody's account: a verbatim capture of what happened, not an argument or a
    telling of it. The case that motivated this option: an ATC transcript. Formally the FAA is a
    party to the investigation, but the transcript is not the FAA's account of anything -- it is
    a recording of what was said at the time, the same as a radar track or a photograph.
  - `unclear` -- the listing does not say.

  Grades the provenance header shown to the model (e.g. "Party submission, ... submitted by a
  party to the investigation"): the one place a misclassification puts words in front of it,
  rather than only reordering or dropping a document. The header uses this same vocabulary, in
  prose rather than the bare word, so a mark and a label are directly comparable (decision 0048
  item 4).
- `notes` -- anything worth flagging; optional, free text.

The sample is stratified by the classifier's own category (the `category` column) so that
rare categories -- `party_submission`, 11 unique titles across all of dev-400 -- are actually
represented, not drowned out by common ones such as `other` (408 unique titles) or `photos`
(984). It is reproducible: the same seed draws the same sample from the same cache.

Titles only. No case is named, and no document text is in this sheet.
