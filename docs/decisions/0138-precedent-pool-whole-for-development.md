# 0138 — In development work, precedent search reads the whole pool, less the judged case's own date

From Andy, 2026-10-03, during S3.1 Task 15. Detail: the S3.1 plan's Deviations
(`docs/plans/2026-09-30-s3-1-agent-loop.md`, entry "The precedent probes re-read with the whole
pool"). This changes one condition of the roadmap's rule for similar-case search (§10, amended
2026-09-14, and §13): "earlier accidents only". It changes it for development work only.

## Context

1. **The rule.** The roadmap allows similar-case search "only as a declared experiment: stated
   before it runs, earlier accidents only, with the retrieval-contamination test"
   (`docs/specs/2026-09-12-architecture-and-roadmap.md`, §10 and §13).
2. **What "earlier only" does in each setting.**
   - In S3.2's held-out run, the judged cases are from 2020–2023 and the pool is the development
     split, 2009–2019. Every pool case is earlier, so the limit never binds.
   - In live use, the judged case is open and every closed case is earlier, so again it never
     binds.
   - In development work, the judged cases are from 2009–2019, inside the pool's own years. A
     2010 case can see only 2009–2010 precedents; a 2019 case sees ten years. The limit gives
     early cases a pool far smaller than the live agent's.
3. **What it changed where it was measured.** In the occurrence precedent probe, on run a's 266
   "always wrong" cases, the probable-cause query found the NTSB's first code among the five
   nearest cases' first codes in 48 cases with earlier cases only, and in 56 with the whole pool
   less the judged case's date (`docs/results/s3-precedent-probe-dev.txt`).
4. **What the pool already leaves out.** The S3 statistics pool is the development split, classes
   C, F and L, less `dev-400`, `dev-seal-400` and `dev-seal-s3-400`
   ([0094](0094-coding-statistics-from-a-pool-outside-the-samples.md),
   [0129](0129-s3s-sealed-sample-and-statistics.md)): 12,090 cases. Held-out and open cases never
   enter it (rule 5, [0024](0024-open-split-enters-measurements-only-as-numbers.md)).

## Decision

1. **In development work** (probes, pilots and rounds on development samples), a precedent search
   reads the whole S3 statistics pool, less every case whose event date is the judged case's
   event date. The date rule removes the same accident filed under a second case number (for
   example, the two aircraft of a mid-air collision).
2. **The earlier-only search is printed beside it** wherever a development precedent result is
   reported, as a sensitivity check.
3. **In held-out and live use nothing changes.** The pool is the same, and every case in it is
   earlier than the judged case, so "earlier accidents only" holds there by construction.
4. **The pool's exclusions stand everywhere.** `dev-400` and both sealed samples stay out; held-out
   and open cases never enter. The retrieval-contamination test proves it for any tool that
   returns precedents: no judged-sample, sealed, held-out or open case, and no case on the judged
   case's date, can be returned.
5. **Earlier results stand as committed.** The probes' outcomes under "earlier only" are not
   rewritten; their whole-pool figures are second readings, labelled as such.

## Why

1. **Development work should see the pool the deployed agent sees.** Held-out and live searches
   read about 12,000 earlier cases; an early development case under "earlier only" reads a few
   hundred. Tuning against the smaller pool would understate what precedent can do.
2. **The leakage risk is named and handled.** The judged case is never in the pool; the same
   accident under another number shares the event date and is removed. A later case's verdict
   does not hold the judged case's verdict.
3. **The stricter figure stays visible.** Printing "earlier only" beside every development result
   lets a reader check that nothing depends on seeing later cases.

## What this rules out

- **"Earlier only" everywhere.** The strongest case for it: no result may use anything decided
  after the judged accident, so no later coding habit can inform an earlier case. Its cost: early
  development cases get a pool unlike the live agent's, so development work understates
  precedent. Kept as the sensitivity check instead.
- **All development cases, `dev-400` and the sealed samples included.** About 6% more cases. Its
  cost: the loop would read the verdicts of the very sample it is tuned on (the overfitting 0094
  rules out for statistics), and the sealed samples would no longer be unseen.
- **Held-out or open cases as precedent.** Rule 5 and 0024.

## Status

Accepted, 2026-10-03 (Andy: "Yes and can we re-run the relevant probes", approving the whole pool
for development work and the decision record).

## Glossary

- **Pool**: the development cases the statistics and precedent tools may read: 12,090 cases
  outside every scored or sealed sample.
- **Same-date rule**: leaving out pool cases on the judged case's event date, so one accident
  filed twice cannot answer for itself.
- **Sensitivity check**: the same result under the stricter rule, printed beside it.
- **Second reading**: a result re-read under a changed definition after the first was seen,
  labelled so it cannot pass for the registered one.
