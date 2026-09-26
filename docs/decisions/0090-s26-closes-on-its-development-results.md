# 0090 — S2.6 closes on its development results; the v3 probe and held-out runs are deferred

Supersedes [0089](0089-s26-closes-after-the-v3-probe-held-out-deferred.md) item 1 (the v3 probe
in October). 0089's item 2 (held-out runs deferred; S2.4's held-out arm B stays the bar) and its
reasons stand.

## Context

0089 kept the v3 probe (spec §10; decision 0082) in S2.6. Weighing it again, Andy judged it
likely to show only noise now: transcription added about 3.8 million characters of text to
dev-400 and moved occurrence top-1 by +1.3% [-2.5%, +4.8%] (`docs/results/s26-armB-v2-dev.txt`),
and B-v2's misses are mostly coding convention (the NTSB's choice of which code in a chain comes
first), which photographs rarely settle. A null result now would be ambiguous between "pictures
do not help" and "their help is hidden behind convention errors".

## Decision

1. **S2.6 closes on its development results.** Task 16 (v3 code), Task 17 (the probe) and
   Task 18 (held-out B-v1 and B-v2) are not done in this stage. The Task 16 build that had
   started was stopped before any commit; its partial diff is kept, uncommitted, at
   `<NTSB_DATA_DIR>/s26/task-16-v3-partial.patch`.
2. **The v3 probe joins the S2.7 candidates**, to be run, if at all, after coding guidance,
   when a picture effect would not be hidden behind convention errors.
3. **The close-out proceeds**: final whole-branch review, the pending fixes, the As-built
   record, the stage pull request.

## Why

1. **A cleaner test later.** The probe's own design measures a noise floor; run after coding
   guidance, a picture effect would stand on its own rather than inside the convention errors
   that dominate today's misses.
2. **Money and time go to the larger lever.** About $6–10 and two sync runs of hours each are
   better spent on S2.7's guidance rounds.

## What this rules out

- **v3 in S2.6.** The evidence-version axis keeps "v3" as a name; runs refuse it until it is
  built.
- **Reading 0089 item 1 as current.**

## Status

Accepted, 2026-09-26 (Andy: "close S2.6 on its development results now; defer the picture probe
and held-out").
