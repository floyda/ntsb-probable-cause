# 0089 — S2.6 closes after the v3 probe on dev-400; its held-out runs are deferred

Takes the held-out step [0088](0088-s26-pauses-after-the-dev-comparison.md) left to Andy. Spec
§9.3 (B-v1 and B-v2 on `heldout-400`, once each) is not run in S2.6; the v3 probe (spec §10,
decision [0082](0082-the-v3-probe-pictures-alongside-text.md)) is.

## Context

The dev-400 comparison (`docs/results/s26-armB-v2-dev.txt`, runs
`20260926T082427-d19aafa-dev-400-B` and `20260926T085904-d19aafa-dev-400-B`): B-v2 against
B-v1 on 399 paired cases, occurrence top-1 +1.3% [-2.5%, +4.8%], top-3 +2.0% [-2.3%, +6.3%],
finding recall@10 +0.6% [-0.9%, +2.1%]. Every difference is positive and every interval
includes zero.

A counts-only breakdown of B-v2's misses (ad hoc, recorded in the plan's Deviations) found most
lost points are coding convention rather than reading: the model's first guess appears
somewhere in the NTSB's own ordered sequence of occurrence codes on 35.1% of cases but is the
sequence's first code on 22.1%; the most common misses name a neighbouring code in the same
chain (for example "loss of control in flight" coded first where the model said "aerodynamic
stall/spin", 33 cases). The model is given the code tables as bare labels, with no
conventions, definitions or examples. Andy has proposed an S2.7 of small, pre-registered
rounds on coding guidance before S3.

## Decision

1. **The v3 probe runs on `dev-400`** (spec §10), in October's budget, as planned in Tasks 16
   and 17: pictures shown alongside the text, development cases only.
2. **The held-out runs of spec §9.3 are deferred.** S2.6 writes no held-out ledger row. S2.4's
   held-out arm B (`docs/results/s24-bars.txt`, occurrence top-1 26.5% [22.1%, 31.5%]) stays
   the bar.
3. **S2.6 then closes**: final whole-branch review, the pending fixes, the As-built record
   (including the S2.7 follow-ups: the ordering check, coding conventions, retrieval of
   similar cases, a wider transcriber re-test), and the stage pull request.

## Why

1. **A held-out run is touched rarely.** Coding guidance is likely to move scores more than
   transcription did, and an S2.7 that adds it re-measures the bar. A held-out B-v1/B-v2 bar
   now would be superseded soon after, at about $16 and one held-out touch.
2. **The picture probe answers a question guidance does not**: whether seeing photographs
   and diagrams helps. Andy chose to have that answer before the stage closes.

## What this rules out

- **Spec §9.3 in S2.6.** B-v2 is not the bar S3's loop must beat; the bar S3 faces is set
  after S2.7.
- **v3 on held-out in S2.6.** Spec §9.3 already said it is decided after the probe; it is
  not run in this stage.

## Status

Accepted, 2026-09-26 (Andy: "B: v3 probe in October, then close").

**Note, 2026-09-26 (final review, I6):** the counts in Context (35.1%, 22.1%, the 33 loss-of-control/stall cases) come from scripts/occurrence_misses.py on run 20260926T085904-d19aafa-dev-400-B, published in docs/results/s26-occurrence-misses-dev.txt; they were quoted before that script was committed.
