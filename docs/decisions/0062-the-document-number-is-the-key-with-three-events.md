# 0062 — The document number in the link is the key; three events; suspected re-numbers are counted

## Context

A listing row gives a document's position, title, page count, photo count, file format and
link. It carries no date. The link carries an integer (`docBLOB?ID=…`). In the seven listing
pages saved as fixtures the integer does not follow row order — in one docket the fourth of
five rows carries a number about 1,100 higher than its neighbours — so it belongs to the
document and not to its place in the list. S2's review already found that positions shift
when documents are added (`docket/client.py`, the `href` check). Whether the number survives
a re-publication of a docket has never been measured.

## Decision

The document number is the key for diffing one night's listing against the last. Three
events are recorded, each with its interval (0060, §3 of the specification):

- **appeared** — absent last time, present now;
- **revised** — same number, changed title, page count or photo count; old and new values kept;
- **disappeared** — present last time, gone now; the row is kept and stamped, never deleted.

A change of position alone is not an event. When one poll shows a disappearance and an
appearance with identical title and page count, the pair is counted as a suspected re-number
in the run summary. The full link is stored with every document.

## Why

1. **The number is the only thing on the page that belongs to the document.** Position is
   known to shift; titles repeat within a docket ("Photo 1") and are edited.
2. **The one unmeasured assumption becomes a reported number.** If the NTSB re-numbers, the
   suspect count shows it the next morning, and the stored links and pages (0063) let the rows
   be re-keyed.
3. **Keeping disappeared rows preserves the record.** A document withdrawn from a docket is
   itself an observation.

## What this rules out

- **Keying on title and page count.** Needs no assumption about the number, but every title
  edit would look like one document leaving and another arriving.
- **Keying on position.** Simplest, and wrong whenever a document is inserted above another.
- **Recording position changes as events.** Noise; the current position is stored and no
  history of positions is kept.

## Status

Accepted, 2026-09-22.
