# 0187. The site repairs a dash the NTSB lost in document titles

## Context

The public site's trail view lists each docket document by its title, as S4's export
(`board/1`, decision 0173) carries it. In the export of 16 October 2026, 19 of 72 trails held
titles with an "A" followed by two U+FFFD replacement characters where a dash belongs. The
titles are of the form "MEMORANDUM FOR RECORD A`\uFFFD\uFFFD` PILOT", where the dash between the two parts of a title should be.

S4 traced it (counts and bytes only, decision 0024). One affected live docket listing, fetched
once and not cached, declares UTF-8 and holds the literal text `A&#xFFFD;&#xFFFD;` at that spot:
an "A" and two HTML entities for U+FFFD. It holds no dash in any form: no bytes `E2 80 93`, no
`&#x2013;`, no `&ndash;`. The character was lost on the NTSB's side before the page was served.
S4's decoding reproduces the page exactly, and the text is already in the closure record, so
S4 copies it faithfully. None of the 1,603 cached development listings holds the sequence.

The pattern is what a UTF-8 en dash (`E2 80 93`) becomes when its bytes are read in another
encoding and the unreadable ones replaced. Every instance sits where a dash would separate
two parts of a title.

## Decision

1. **The site shows the exact sequence "A", U+FFFD, U+FFFD in a document title as an en dash,
   U+2013.** Nothing else in a title is changed, and no other text on the site is touched.
2. **The repair is in the site's code** (`site/src/lib/trail.ts`, `titleShown`), applied where
   the trail view draws a title. It is tested to change that sequence and nothing else.
3. **S4's export is unchanged.** `board/1` stays an exact copy of what the NTSB served. No S4
   code, image or deploy follows from this record.

Andy's ruling, 2026-10-20, through the S4 session, and confirmed in the S5 session on
2026-10-21.

## Why

1. **The garbled text reads as a fault in the site.** A reader sees "A" and two replacement marks in a document's name
   and has no way to know the NTSB served it.
2. **The repair is a guess, and is recorded as one.** The lost character cannot be recovered
   from the page. An en dash is the likeliest one: the sequence is exactly what a UTF-8 en dash
   becomes, and every instance sits where a title's two parts would be separated.
3. **The record stays exact.** Repairing in the site, not in S4, keeps the export a faithful
   copy, so anyone checking the board against the NTSB's pages finds the same text.

## What this rules out

- **Repairing in S4's export.** That would make the export differ from what the NTSB served,
  and every later reader of `board/1` would inherit the guess without seeing it.
- **Leaving the titles garbled.** Faithful, but the site would look broken on one trail in four.
- **A broader rule**, such as replacing every U+FFFD. Other replacement characters could stand
  for other lost characters; guessing each would put words in the NTSB's mouth. Only this one
  sequence, seen and traced, is repaired.

## Status

Accepted.
