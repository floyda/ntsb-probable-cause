# 0075 — Pages are rendered with `pypdfium2`

Extends [0047](0047-pypdf-extracts-docket-text-no-ocr.md), whose rule against system tools this
record keeps and explains.

## Context

A vision model needs a picture of the page. Two routes exist: pull the embedded image out of the
PDF with `pypdf`, or draw the whole page with a renderer. A throwaway probe of the image-only
pages in `dev-400` (ad-hoc; re-derived in S2.6) found that extraction fails on real dockets:

- 527 pages are rotated 90°, 180° or 270°; the rotation lives on the page, so an extracted image
  comes out sideways;
- 200 pages are assembled from five or more image pieces, which extract as strips;
- image encodings include 929 fax (CCITT), 250 JPEG 2000 and 54 JBIG2; JBIG2 needs a system
  program to decode.

Mixed pages — text and image together, such as a photo with its caption — cannot be handled by
extraction at all.

0047 ruled out system tools such as Poppler because the machine's setup would become part of the
result, and the project's numbers would not be reproducible without it.

## Decision

1. Every page sent to a vision model is drawn with **`pypdfium2`** (PDFium, the engine in Chrome;
   BSD and Apache licences), with `Pillow` to write the image.
2. Resolution is one typed constant, chosen in the transcriber test between 150 and 200 dots per
   inch, and part of every transcription's cache key.

## Why

1. **The page as presented.** Upright, whole, every encoding handled, one code path for every
   page kind.
2. **0047's test is reproducibility, and this passes it.** `pypdfium2` installs from the lock
   file as a ready-built package for macOS on Apple silicon and Linux on x86 and ARM (PyPI,
   version 5.13.0, 2026-09-22). `uv sync` reproduces it anywhere; nothing is installed on the
   machine itself.

## What this rules out

- **Extracting embedded images with `pypdf`.** No new dependency, but the rotated, tiled and
  JBIG2 pages above are lost or garbled, and mixed pages cannot be handled.
- **Poppler (`pdftoppm`) or another system tool.** Mature, but 0047's reason still holds.

## Status

Accepted, 2026-09-23 (Andy: "option A is the best option to maintain the pages as presented").
