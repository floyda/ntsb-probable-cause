# 0155 — The board is backfilled from the recorder's first night

From Andy, 2026-10-05, in the S5 site design session. Detail: the Draft specification
`docs/specs/2026-10-04-s5-public-site-design.md`, §12 item 6.

## Context

1. **The board lists closed cases**, the agent's coding beside the NTSB's, most recent first
   (decision [0154](0154-the-live-run-is-at-closure.md)).
2. **Closures come in bursts.** In the recorder's first 14 finished nights, 47 cases closed, all
   on three nights: 23 September, 1 October and 2 October 2026; the other eleven nights had none
   (the per-night split is from an ad-hoc read-only query of the store, to be replaced by a
   script; the totals are in `docs/results/s5-recorder-report-2026-10-06.txt`).
3. **A board that starts on launch day** would show a handful of rows, or none, to the readers
   who matter most in the first weeks.
4. **The recorder has watched every ongoing Part 91 case since 23 September 2026**, so it holds
   when each closed and when its docket appeared.

## Decision

1. **At launch the agent codes every watched case that closed on or after 23 September 2026**,
   the recorder's first night, as a closure run (0154), abstains and failures included.
2. **Those rows carry the label "coded after launch, from the declared start".**
3. **The start date is fixed here, before anything is coded**, and is never moved later.
4. After launch the board lists the most recent closures whatever their date, so it never
   empties, and its stamp names the last rebuild and the last closures.

## Why

1. **Nothing is selected.** Every case after a date fixed in advance is coded, so no case can be
   picked for its result.
2. **The protection is the same as every live row's**: the verdict is withheld by the split and
   guard, and each run records its commit.
3. **The board opens with real rows**, which is what the site's first readers see.

## What this rules out

- **Starting empty.** The strongest case: every row is coded on its own closure night, the
  purest public record. Its cost: a near-empty board for weeks, since closures come in bursts.
- **Filling the board with development or held-out cases.** It would mix evaluation results with
  live ones in one figure, which decision 0021 forbids.
- **A start date chosen later.** A date picked after seeing results invites selection.

## Status

Accepted, 2026-10-05 (Andy: "I think B, was the reason to start the recorder early").

## Glossary

- **Backfill**: coding, at launch, the cases that closed between the declared start and launch.
- **Declared start**: the fixed date from which every closed case is coded.
