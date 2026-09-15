# 0026 — Slices by fatality first; fixed samples; a held-out ledger

## Context

The build brief's slice, factual narrative present or absent, no longer exists: the
narrative is withheld in every case (0013). The agency design proposed fatal / non-fatal
first and investigation class second, and 0022 stated its predictions that way, but the
roadmap left the slicing decision to S1. The corpus counts (M4,
`docs/results/s0-corpus-scan.txt`): C-class cases are 6,126 of 13,560 development cases,
397 of 4,241 held-out cases and 0 of 1,840 closed open-split cases; held-out cases are 727
fatal and 3,514 non-fatal.

The spike's 40 like-for-like cases give an interval of about ±15 points on a proportion
near 50%. The spike computed no intervals. Every look at the held-out split is a small
tune, and the project's rule is that reported numbers come from there.

## Decision

1. Every table is reported for all cases, then by fatal / non-fatal, then by investigation
   class within each. Report flavour is a context slice. Classes I, M and T, five held-out
   cases, are excluded from samples and the exclusion is stated.
2. Three fixed samples, committed as ID and event-date files under `tests/fixtures/eval/`:
   `heldout-40`, the spike's decidability cases; `heldout-400`, 200 fatal and 200 non-fatal
   held-out cases stratified by class within each half, seed 20260914; `dev-400`, the same
   construction on the development split. The all-cases headline on `heldout-400` is
   weighted by the held-out fatal share, 727 of 4,241, with the unweighted number beside
   it.
3. Prompts, schema, threshold, judge validation and model comparisons are settled on
   `dev-400` only, and frozen before any held-out run.
4. `docs/results/heldout-ledger.md` records every run that touches a held-out sample:
   date, sample, arm, exclusions, model, commit, cost, results file. The harness appends
   the row; a held-out run from a tree with uncommitted changes is refused.

## Why

1. **Injury level means the same in every era; class does not.** A slice that is 45% of
   development cases and 0% of live cases would describe cases the live board never sees.
2. **The agency predictions concentrate in fatal cases** (0022, P1 and P3). A proportional
   draw would hold 69 fatal cases; 200 gives an interval of about ±7 points.
3. **Weighting keeps the headline honest.** Oversampling the harder slice would otherwise
   overstate difficulty.
4. **The number of looks at the held-out split should be public and small.** A ledger the
   harness writes cannot be forgotten.

## What this rules out

- **Class as the first slice.** The agency design's own argument, now closed.
- **A proportional 400.** Too few fatal cases to test the predictions that matter.
- **A larger sample.** At Luna's price a 1,000-case run would be affordable, but every
  held-out case run is a case the loop's later evaluation has already been seen on; 400
  is enough for the bars, and S3 may draw a second, disjoint sample.
- **Tuning on `heldout-40` for continuity.** It is reported, not tuned on.

## Status

Accepted.
