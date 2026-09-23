# 0074 — Words in images are read in the build, not in "phase 2"

Replaces item 3 of [0047](0047-pypdf-extracts-docket-text-no-ocr.md) ("there is no OCR in this
stage") as a plan for the build. 0047's other items stand.

## Context

0047 left pages with no text layer unread and deferred OCR to "phase 2", after the held-out
result and the live board (top-level `CLAUDE.md`, goal 4). The spike had measured that about a
third of the docket-fixable cases hold their missing information in such documents (spike
report §10).

A throwaway probe over the `dev-400` docket cache during the S2.6 design (ad-hoc; re-derived by
`scripts/page_kinds.py` in S2.6) found 3,281 pages that are images with under 50 characters of
text, 2,605 of them in fatal cases, and a further 8,403 pages that carry both a text layer and
an image — the most common page kind, and one a program cannot interpret without looking.

Decision 0022 requires the loop (arm C) to beat arm B on equal evidence. If only the loop could
read images, part of any win would come from reading rather than from choosing.

## Decision

1. Reading the words in page images moves into the build, as stage S2.6, before the S3 loop.
2. What is transcribed is decided from a measured **inventory** of what image-bearing pages
   show (S2.6 spec §6), not assumed. If the inventory finds the pages rarely hold words, the
   stage records that and does not transcribe.
3. Transcription copies words and nothing else. Describing or interpreting a picture is not
   transcription; pictures reach the agent, if at all, as pictures (0082).

## Why

1. **Equal evidence must be built before the comparison that needs it.** Adding it after S3
   would re-open the S3 result.
2. **The loss is larger than a few scans.** Most image-bearing pages are mixed pages, which the
   phase-2 framing ("OCR for handwritten pilot forms") did not anticipate.
3. **The inventory keeps the decision falsifiable.** It can come back and say "not worth it".

## What this rules out

- **Keeping OCR in phase 2.** Rejected: the S3 comparison would then be run on evidence the
  project knew to be incomplete, and redone later.
- **Transcribing everything without an inventory.** Rejected: it spends money on logo pages and
  wreckage photos with no words, and decides scope by guess.
- **Classic OCR engines.** Rejected on the published benchmark closest to our pages
  (socOCRbench, read 2026-09-22): Tesseract scores 0.13 on handwriting against 0.64 for the
  front-running vision model (S2.6 spec §7.1).

## Status

Accepted, 2026-09-23 (Andy).
