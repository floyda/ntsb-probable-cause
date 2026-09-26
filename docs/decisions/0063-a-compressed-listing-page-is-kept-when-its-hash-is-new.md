# 0063 — A compressed copy of the listing page is kept whenever its hash is new

## Context

The recorder parses each docket's listing page nightly (0061). Arrival timing cannot be
collected a second time: if the parser has a bug, or the document number (0062) proves
unstable, or a later stage wants a column the parser ignored, the observations already made
are wrong or incomplete for ever unless the page they came from was kept. The seven saved
listing pages are 26–42 KB each and 4–6 KB compressed.

## Decision

Every poll hashes the page. When the hash is new for that case, the compressed page is
stored in `listing_pages`, keyed by hash. A poll whose page hash matches the last stores
nothing. The pages hold document titles, which are open-split text; they stay in the
recorder's store, which 0024 permits, and never enter the repository or an evaluation.

## Why

1. **It makes a parser mistake recoverable.** Every observation can be rebuilt with its
   original timestamp from the stored pages.
2. **A quiet night costs nothing.** At a guessed 25 changes a night the store grows by about
   45 MB a year, well under a cent a month on S3.
3. **It is the only place in the stage where storage buys back an otherwise permanent
   error**, so the small cost is the right trade.

## What this rules out

- **Keeping only the parsed rows.** Smallest store; a parser mistake found in month three
  makes months one to three unrecoverable.
- **Keeping every page every night.** About 1.8 GB a year, almost all identical copies.

## Status

Accepted, 2026-09-22.
