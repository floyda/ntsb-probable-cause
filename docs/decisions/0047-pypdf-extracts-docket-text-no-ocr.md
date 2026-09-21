# 0047 — `pypdf` extracts docket text; there is no OCR in S2

Written at the S2 close-out review, which found the dependency had been added under the
specification's authority (§5.1, §11) without the numbered record `CLAUDE.md` rule 8 requires.
Recorded now rather than silently, because the choice decides what the agent can read at all.

## Context

A docket document is a PDF. Some are born-digital, with a text layer that can be read directly.
Many are scans of paper — handwritten pilot statements, faxed maintenance records — with no text
layer at all. The agent's reach over the docket is exactly the set of documents something can turn
into text, so the extractor is not an implementation detail: it is the boundary of the evidence.

The spike measured the consequence before the build began (report §10): about a third of the cases
whose missing information sits in the docket have it in a document with no text layer.

## Decision

1. Text is extracted with **`pypdf`** (`pypdf>=6.19.0`, `src/ntsb_probable_cause/docket/extract.py`),
   page by page, with a page marker so a passage can be cited to a page.
2. A page that fails to extract counts as **zero characters** rather than aborting the document; a
   file that is not a readable PDF raises `DocketError` and is recorded as a status, never
   propagated. One malformed file cannot stop a 400-docket run.
3. **There is no OCR in this stage.** A document with no text layer is classified `unreadable: scan`
   and is not read. That is a measured loss, published in `docs/results/s2-shape-dev.txt`, not a
   silent one.
4. `pypdf` emits warnings about missing font tooling on some documents. Checked on real dockets: the
   documents that warn extract fully (thousands of characters, every page readable). The warning is
   cosmetic and `fontTools` is **not** added.

## Why

1. **Pure Python, no system dependency.** `pypdf` installs from the lock file and needs no binary on
   the machine, which keeps `make check` reproducible for anyone who clones the repository — a demo
   that cannot be rebuilt by a sceptic is not falsifiable in public.
2. **It only has to decide readable or not.** The thresholds in `classify.py` are what turn character
   counts into a verdict on readability, and they are re-measured on 400 real dockets. A more capable
   extractor would move the numbers, not the design.
3. **OCR is a separate claim with a separate cost.** It needs its own accuracy measurement against
   handwriting, its own runtime, and its own decision about what an uncertain transcription does to a
   probable-cause finding. Phase 2 in the top-level `CLAUDE.md` names it; this stage measures the
   size of the prize instead of assuming it.

## What this rules out

- **OCR in S2.** Deliberately. The share of dockets that are scan-only is a published number
  (`docs/results/s2-shape-dev.txt`), so the value of adding OCR later is measured rather than argued.
- **A system-binary extractor (`pdftotext`, Poppler).** Better on some malformed files, but it makes
  the environment part of the result and the project's own numbers unreproducible without it.
- **A model-based or paid extraction service.** It would put document text through a second model,
  need its own error measurement, and cost money per page on a run that is already metered.
- **Adding `fontTools`.** Measured as unnecessary; revisit only if a document is found whose text is
  actually degraded by its absence.

## Status

Accepted, 2026-09-18 (retrospective: the dependency was added under S2 spec §5.1 and §11 during the
build, and this record was written at the close-out review that found it undocumented).

## Corrections, added 2026-09-21 (S2 close-out audit)

1. **The pinned dependency is `pypdf[crypto]>=6.19.0`, not `pypdf>=6.19.0` as the Decision above
   states.** The extra is not cosmetic. Without it `pypdf` falls back to a pure-Python RC4
   implementation on encrypted documents; measured with `memray` over a 40-case fetch, that
   fallback allocated **24.1 GB** against **13.6 GB** with the extra, and was the cause of three
   repeated out-of-memory kills during the S2 measurements.
2. **The page-level half of this record's extraction outcome was adjusted by
   [0053](0053-a-page-of-fifty-characters-is-readable.md)**, which settled the boundary case at
   exactly 50 characters a page, where `classify_pages` and `readable_pages` previously disagreed.
