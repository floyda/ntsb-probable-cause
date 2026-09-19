# Title hand-check: what to mark

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
- `author` -- who wrote it: `investigation` / `party` / `independent` / `unclear`
  Grades the provenance header shown to the model (e.g. "Party submission, ... submitted by a
  party to the investigation"): the one place a misclassification puts words in front of it,
  rather than only reordering or dropping a document.
- `notes` -- anything worth flagging; optional, free text.

The sample is stratified by the classifier's own category (the `category` column) so that
rare categories -- `party_submission`, 11 unique titles across all of dev-400 -- are actually
represented, not drowned out by common ones such as `other` (408 unique titles) or `photos`
(984). It is reproducible: the same seed draws the same sample from the same cache.

Titles only. No case is named, and no document text is in this sheet.
