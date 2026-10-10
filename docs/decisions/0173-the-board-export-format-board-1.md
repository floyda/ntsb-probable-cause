# 0173 — The board export format, `board/1`

From the S4 design session with Andy, 2026-10-10. Detail: the S4 specification, §10.

## Context

1. **S5's Draft lists what its pages read** (`docs/specs/2026-10-04-s5-public-site-design.md`, §4
   to §6 and §13): the board's columns, the opened case's five parts, the trail's beliefs and
   actions, the withheld-verdict line, the training cut-off.
2. **Andy wants S5 sooner** (2026-10-10): "once we have the export schema we can start building
   the static site".
3. **Decision [0029](0029-live-headline-is-the-finding-score.md)** makes the finding score the live
   board's headline.

## Decision

1. **S4 builds the whole export**: one `index.json` (the build stamp, the site-wide counts, one row
   per closed case) and one `cases/<case number>.json` per case (the facts, the withheld line,
   both codings, the comparison with finding scores, the trail, a fixed sentence for a case not
   coded). JSON, every file `"format": "board/1"`, rebuilt nightly from the run folders.
2. **Six grades**: same first code, same codes in another order, different, abstained, not coded,
   awaiting the NTSB's codes, computed by the harness's scoring code.
3. **It never holds** the registration, the non-expert explanation, Ellery's evidence account, any
   document text, the evidence fingerprint, a make or model, personal names, or anything about an
   open case beyond counts. A test checks every string.
4. **Typed models, a committed JSON Schema, and an invented sample** that S5 builds against. Adding
   an optional field keeps `board/1`; anything else is `board/2`.
5. **S5 writes the one sentence on where the codings differ.** The replying model and provider are
   in the withheld line.

## Why

1. **S5 can start before S4's cloud nights**, against the sample, which is S4's longest wait.
2. **One format, one test**: what the site may show is decided in one place, under a test.
3. **Grades from the scoring code** mean the board's measures are the Methods page's.

## What this rules out

- **A minimal export, with S5 deriving the rest.** Less S4 work. Rejected: S5 would read run
  internals to fill the trail, and the never-holds test would have nothing to check.
- **The difference sentence in the export.** Rejected: wording is the site's, and code writes it
  from the two code lists either way.

## Status

Accepted, 2026-10-10 (Andy: "A").
