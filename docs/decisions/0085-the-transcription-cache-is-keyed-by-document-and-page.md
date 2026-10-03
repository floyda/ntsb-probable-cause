# 0085 — The transcription cache is keyed by document and page, not by image

Amends [0081](0081-transcription-is-evidence-preparation.md) item 1. Items 2 and 3 of 0081
(transcription counts against the monthly budget, not the agent's per-case cap) are unchanged.

## Context

0081 item 1 keys each cached transcription on the page image's hash, the model, the
instruction's version and the resolution. The S2.6 plan (Task 11, and its Deviations,
2026-09-24) keys it on the **document's content hash and the page number** in place of the image
hash. The plan was approved with that change in it, but a change to an accepted decision
belongs in a decision record, not only in a plan that is deleted at merge (0017). Task 11's
review found the gap.

An example of why it matters. An evaluation run that meets a scanned page must find out
whether that page has been transcribed. Keyed by the image, it has to draw the page first to
hash the picture — for a fatal docket of 120 scanned pages, 120 renders before it knows
anything. Keyed by the document and page, it looks the answer up from the bytes it already
holds.

## Decision

1. A transcription is cached under a key made of the **document's content hash (SHA-256 of its
   bytes), the page number, the model, the instruction's version and the resolution**
   (`docket.transcribe.TranscriptionKey`). The cache sits under `NTSB_DATA_DIR`
   (`Settings.transcription_dir`), never committed.
2. Every record also stores the **page image's hash**, so what the model was shown can still be
   identified and checked afterwards.
3. A change of model, instruction or resolution still gives a new key, and so a new reading.

## Why

1. **Same identity, cheaper lookup.** The same document bytes drawn at the same resolution give
   the same image (checked while the plan was written: rendering is repeatable), so the two keys
   name the same page. The document key needs no render to look up.
2. **Nothing checkable is lost.** The image hash is kept in the record (item 2).

## What this rules out

- **Keying on the image alone.** Every lookup would pay a render, on every run, for every page.
- **Keying on the document without the page number, model, instruction or resolution.** Any of
  those changes what the model reads or how, so each must give a different reading.

## Status

Accepted, 2026-09-24, in the S2.6 plan Andy approved (its Deviations, 2026-09-24); recorded here
2026-09-25 after Task 11's review.
