# 0096 — The ordering check: what it sees, what it may choose, and the bar for a model

## Context

Top-1 is exact match against the NTSB's defining event (0025). On B-v2 the first guess is in
the NTSB's sequence on 35.1% of `dev-400` cases but is the defining event on 22.1%
(`docs/results/s26-occurrence-misses-dev.txt`), and a further set of cases have the right event
under the wrong phase. A step after the answer that re-orders the codes by the NTSB's own
habits could recover some of these without changing what the model reads.

## Decision

1. **Position.** A step after the answer, before the finding refinement turn; not an agent
   tool. It is recorded as its own step with its input fingerprint, output and cost; the
   unchecked answer is kept beside it.
2. **What it sees.** The model's three occurrence guesses; the candidate list (item 3); the
   counts of `docs/results/s27-coding-stats.txt` for those candidates (0094); the phase group
   already given as evidence; the model's own evidence narrative. Never the verdict, the
   factual or analysis narrative, or docket text. A boundary test checks the body sent.
3. **The candidate list**, at most eight codes, fixed before any statistic is computed: the
   three guesses; every code defining in at least 25% of pool cases whose sequence contains a
   guessed code, where there are at least 20 such cases; the two commonest defining codes for
   the phase group; the same event as any candidate under another phase prefix in the phase
   group, seen as defining in at least 10 pool cases. Guesses first, then by pool count.
4. **Four ways**, each run on the recorded B-v1 answers and on Round 0's repeat: no check; the
   plain rule (the event the pool most often flags as defining when the first guess appears,
   on at least 20 cases, else the first guess; then the pool's commonest phase for it in the
   phase group; ties to the model's order); GPT-6 Luna asked; Jev asked (0097).
5. **Reading.** A way works if its paired top-1 gain over no check has a lower interval bound
   above zero on both answer sets. A model is chosen only if it beats the plain rule by the same
   test; otherwise the plain rule is chosen if it works; otherwise no check is kept.

## Why

1. **The narrative lets it tell cases apart** that counts alone cannot; in 24 of 33
   stall/loss-of-control misses the model's own narrative says "loss of control" (ad-hoc,
   re-derived in Round 0).
2. **Re-ordering the three guesses alone is capped at top-3** (B-v1: 33.1% against 20.8%,
   `docs/results/s26-armB-v2-dev.txt`); the right code is often outside them.
3. **A model call must earn its place over a lookup table.**
4. **Two answer sets** stop a lucky gain on one run from being kept.

## What this rules out

- **Codes and counts only.** Always the majority code, including where the model was right.
- **The full evidence again.** A second analysis at arm B's price; a coding fix could not be
  told from a second opinion.
- **Any code at all.** A second analyst, not a coding check.

## Status

Proposed, 2026-09-26: written with the S2.7 specification (Andy chose what it sees, "A", and
what it may choose, "A"). Accepted when Andy approves the specification.
