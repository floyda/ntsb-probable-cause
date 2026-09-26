# 0094 — Coding statistics come from development verdicts outside the samples

## Context

S2.7's ordering check (0096) and its guidance (0098) need to know how the NTSB codes: which
event it flags as defining when two occur together, which phase prefix it uses within a phase
group. That knowledge is in the verdicts of closed cases. Using a verdict to help answer
another case is safe only if the scored case, and every case in a sample that will be scored,
never contributes. The no-model baseline (S1) already fits on development verdicts and scores
elsewhere.

## Decision

1. **The statistics pool** is every development-split case in classes C, F and L that is in
   neither `dev-400` nor `dev-seal-400` (0095): about 12,490 cases (ad-hoc count, re-derived by
   the script).
2. `scripts/coding_stats.py` builds, once, from the pool only: defining-event shares for pairs
   of codes that occur together; defining-event shares among cases whose sequence contains a
   code; phase-prefix shares per phase group and event; the commonest defining events per phase
   group; each split 2009–2014 and 2015–2019. It writes `docs/results/s27-coding-stats.txt`,
   codes and counts only.
3. The script refuses any case from `dev-400`, `dev-seal-400`, held-out or open, and a test
   proves it refuses (the retrieval-contamination test of the required components, applied to
   statistics).
4. Guidance text and the ordering check cite only this file, at the commit that built it.

## Why

1. **It is the baseline's kind of knowledge, finer grained**, and never touches the case being
   scored.
2. **One committed table makes every count citable** and the check reproducible.
3. **Both halves of the decade are printed** because a coding habit that changed would mislead
   a check applied to later cases.

## What this rules out

- **Statistics from `dev-400`.** They would be fitted to the cases they are scored on.
- **Statistics from held-out or open cases.** Rule 5 and 0024.
- **Case text in the table.** Counts only; a test fails on a case-number pattern.

## Status

Proposed, 2026-09-26: written with the S2.7 specification (Andy approved the design's section
on samples: "yes, go on to section 2"). Accepted when Andy approves the specification.
