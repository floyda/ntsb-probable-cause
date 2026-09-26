# 0061 — The recorder reads the listing page only and never downloads a document

## Context

A docket has a listing page — the web page naming each document with its title, page count
and photo count — and the documents themselves. S2's docket client fetches both. The S2
docket cache for about 400 development cases is 19 GB. Andy's constraint for the recorder
was stated plainly: it should track when documents turn up against a case, and not pay to
store the files.

## Decision

The recorder fetches the listing page only. It never downloads a document. For each document
it stores one row: number, title, page count, photo count, file format, link, and the
interval in which it appeared. A change of title, page count or photo count behind the same
document number is recorded as a revision.

## Why

1. **The measurement needs only the listing.** "Days to first appearance" is answered by
   which documents the page names and when. The content of a document is not needed to know
   that it exists.
2. **Storage stays trivial.** About 200 bytes per document; the whole store is estimated at
   tens of megabytes a year.
3. **Load on the NTSB's site stays at one request per case per night.**

## What this rules out

- **Downloading each new document as it appears.** It would give the live board the text
  immediately and would detect a document's content changing behind the same number. Rejected:
  storage of gigabytes for a stage that makes no use of the text, and the agent will fetch
  documents itself when it runs on a live case in S4, where keeping them is that stage's
  decision.
- **Detecting content changes.** A document replaced behind the same number and with the
  same title and page count is invisible to the recorder. Accepted as a known limit.

## Status

Accepted, 2026-09-22.
