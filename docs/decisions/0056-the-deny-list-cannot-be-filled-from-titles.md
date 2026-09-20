# 0056 — The deny-list cannot be filled from titles, and is removed

Completes [0039](0039-filter-measured-by-tripwire-hits-and-a-title-hand-check.md) items 1 and 2 by
running the measurement they require, and removes the mechanism they specify. With this, the
document category has no job left in the live path.

## Context

0039 item 2: the deny-list of categories refused before attachment starts empty and is filled
**only** by tripwire hits on `dev-400` — never by judgement. It has been empty since it was
written, because the measurement had never been run. `docket/filter.py` cited
`docs/results/s2-filter.txt` as its source; that file had never existed.

The measurement is now run: `scripts/corpus_scan.py --docket`,
`docs/results/s2-threshold.txt`, 401 development cases, 2,587 readable documents, at the guard's
operating threshold of 20 characters and with the 0050 exemption in force.

**56 hits, stopping 17 cases, spread across 8 of the 12 categories:**

| category | hits |
|---|---|
| `other` | **33** |
| `exam_site` | 9 |
| `conversation_statement` | 8 |
| `specialist_factual` | 2 |
| `medical_tox`, `party_submission`, `photos`, `pilot_form_6120` | 1 each |

The scan also reports that **no candidate sentence length reaches zero hits** — independently
confirming what the leakage sweep found (`docs/results/s2-docket-leak.txt`) by a different route.

## Decision

1. **The deny-list stays empty, permanently for S2, on the measurement above.** `DENY_LIST`,
   `is_denied`, the `denied` parameter of `read_docket` and the `"denied: write-up"` status are
   removed.
2. **The document category keeps no job in the live path.** With
   [0052](0052-arm-b-attaches-every-readable-document.md) (admission),
   [0054](0054-the-party-submission-comparison-is-retired.md) (the run variant) and
   [0055](0055-the-document-header-carries-the-listing-number.md) (the header) already landed, the
   category is now only a statistic published in `docs/results/s2-shape-dev.txt` and a diagnostic
   word in the run's step log.
3. **17 of 401 development cases fail closed and are reported as refusals**, not answered. That is
   the measured cost of the guard and it is published rather than engineered around.

## Why

1. **The risk concentrates in the category that means "unlabelled".** `other` carries 33 of 56
   hits — 59%. Denying it would refuse 604 of 3,790 documents, the largest single bucket, to catch
   33 hits. A mechanism whose biggest target is "we could not tell what this is" cannot work by
   naming categories.
2. **The hits spread across 8 of 12 categories.** Filling the list honestly from this table means
   denying two thirds of the taxonomy, which is not a filter but a decision to stop reading the
   docket. Arm B is the bar the loop must beat; gutting it would flatter the loop, which is the
   direction of error this project exists to avoid.
3. **0039 item 2 forbids the alternative.** A deny-list chosen by judgement rather than by hits is
   exactly what that item rules out, and it was right to.
4. **This is the third independent measurement pointing the same way.** The title hand-check put
   the provenance clause at 58-72% accurate; the filter comparison showed the photograph exclusion
   cost 270 documents for six tokens; this shows the deny-list cannot be filled. Titles do not
   support decisions about what the agent reads.

## What this rules out

- **Filling the deny-list from this table.** Rejected on reasons 1 and 2.
- **Keeping the mechanism empty "in case S3 needs it".** Rejected: a constant that is empty, a
  function that always returns `False`, and a status value nothing can produce are three things a
  reader must understand and none of them does anything. 0052 used the same argument to delete the
  `unfiltered` variant. If S3's loop needs to refuse a document, it will need its own rule and its
  own measurement.
- **Denying `other` alone.** Superficially attractive — it is 59% of the hits. Rejected: it is also
  16% of all documents and the category exists precisely because we do not know what is in it, so
  denying it trades a large, undirected loss of evidence for a partial reduction in a risk the
  tripwire already catches.
- **Answering the 17 cases from their remaining documents.** Rejected here, as
  [0050](0050-tripwire-skips-factual-narrative-sentences-in-docket-documents.md) rejected it:
  dropping the offending document silently changes what arm B reads, and the drop correlates with
  how thoroughly a case was documented. Reconsider only with a measurement behind it.

## What is lost, stated plainly

0013 anticipated that the docket would be filtered by type and title, and 0039 designed the
mechanism. Neither survives measurement. The docket's defence is now the tripwire alone: documents
carrying the analysis narrative, the probable cause or the codes stop the case, and 17 of 401
development cases do stop. There is no second, structural layer, and this record is where a reader
should be told so.

## Status

Accepted, 2026-09-20 (Andy chose to run the measurement — "Lets go with A1" — and accepted its
result).
