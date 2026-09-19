# 0037 — Docket fixtures come from development-split dockets only

Amends the S2 entry of `docs/specs/2026-09-12-architecture-and-roadmap.md` §11, which says
S2's offline fixtures are "built from the 14 dockets already probed in the spike". Extends
0015 (fixtures are redacted real development records) to docket listings and documents.

## Context

The roadmap's S2 entry was written before 0015, 0024 and 0026 existed. The 14 dockets it
names are the B-category cases of the spike's decidability sheet
(`../ntsb-spike/scripts/b_docket_probe.py`). Checked against the committed evaluation list
`tests/fixtures/eval/decidability_ids.csv`: all 14 are held-out cases by their own event
date, 2020 to 2023. For example, WPR20CA166 has event date 2020-06-03. Rule 5 and 0015 forbid
a held-out case in any fixture, `tests/test_contamination.py` enforces it by event date, and
0026 counts every held-out look in the ledger. The roadmap sentence cannot be followed as
written.

A docket document is free text that names people: a record of conversation names the pilot,
witnesses and the investigator; a Form 6120 is the pilot's own account. 0015's redaction
removes a fixed list of owner and operator fields from a record. It cannot find a name inside
a paragraph, and rule 6 forbids victim names in any output, which a public repository is.

## Decision

1. **Every docket fixture comes from a development-split case** (event date up to 2019),
   never from a held-out or open case. Cases are drawn by script from the committed `dev-400`
   list (`tests/fixtures/eval/dev_400_ids.csv`, 0026), so the docket fixtures and the
   development measurements share one population. The fixture script refuses any case whose
   event date is outside the development split, as `scripts/make_fixture.py` already does for
   records.
2. **The docket listing is committed as a saved real response**: the HTML page with its table
   of document titles, types and page counts. It holds no personal text and is what the parser
   is tested against. A change in the NTSB's page structure fails the parser test loudly.
3. **Document text is committed only for NTSB-authored, born-digital documents**, after a
   scripted redaction pass and Andy's read of each document before it is committed. Scanned
   documents, non-PDF files and party submissions appear in fixtures as their classification
   and extraction outcome only, for example "scan, 11 pages, 0 readable pages", never as text.
   That exercises the "cannot read this, say so" path without putting handwriting or names in
   git.
4. **The 14 held-out dockets are touched in S2 once**, by the arm B run at the end of the
   stage (0022), recorded in `docs/results/heldout-ledger.md`, and are never cached as
   fixtures or opened while the client, the classifier or the filter are being built.
5. The S2 specification restates the roadmap's S2 entry with this rule; the roadmap's
   original text stays in place, marked amended.

## Why

1. **A cached held-out docket is what the contamination test exists to catch.** Evidence text
   in the test tree shapes the parser, the classifier and the filter, whichever way it got
   there. 0026 exists because every held-out look is a small tune.
2. **The development split is the only place the filter may be chosen anyway.** 0022 fixes arm
   B's document filter on the development split. Fixtures from the same population let the
   filter's tests and its measurement agree on what a document looks like.
3. **Names cannot be redacted by field list.** Committing only NTSB-authored born-digital text,
   read by a person before commit, is the narrowest rule that keeps real document shapes (0015,
   reason 1) without publishing private individuals' words or names.
4. **Real shapes, still.** The listing page is a real response, and the committed documents are
   real NTSB reports. Rule 2 forbids authored shapes.

## What this rules out

- **The 14 probed dockets as parser fixtures**, on the grounds that the spike already
  published their verdicts on its sheet. Rejected: the sheet is a scoring fixture that holds
  codes; a cached docket is evidence text in the test tree, and the spike's sheet does not
  license a second look.
- **Synthetic docket pages and documents.** No personal-data risk and no split question.
  Rejected for the reason 0015 gives: authored shapes drift from the real page without any test
  noticing.
- **Committing every document from a development docket verbatim.** Simplest, and the fullest
  test of extraction. Rejected: pilot forms and conversation records name people, and no
  scripted redaction of free text is reliable enough to trust unread.
- **No committed documents, only listings.** Safest. Rejected because the extractor and the
  synthesis-document test (roadmap §9) would then be untested where it counts.

## Status

Accepted, 2026-09-17 (Andy: "Any example dockets should come from the dev set, don't re-use
any from held-out").

**Partly superseded by [0049](0049-the-name-line-is-the-public-surface-not-the-repository.md),
2026-09-19.** Item 2's conclusion stands — the listing page is still committed as a saved real
response — but two things written here turned out to be wrong once measured, and are corrected
there rather than edited here:

- Item 2 says the listing "holds no personal text". It does. Document titles carry the surnames of
  pilots, instructors and witnesses; 367 of 401 cached listings carry at least one word the title
  check cannot vouch for, and real surnames were found in the first hand-check sheet drawn.
- The context above says "rule 6 forbids victim names in any output, which a public repository is".
  0049 narrows where "output" begins: a byte-exact copy of a page the NTSB already publishes is not
  this project speaking, while the live board, a published results file and a prediction row are.
  `CLAUDE.md` rule 6 itself is unchanged and absolute.

Item 1 (development dockets only) and item 3 (document text only for NTSB-authored, born-digital
documents after the scripted pass and a human read) are untouched.
