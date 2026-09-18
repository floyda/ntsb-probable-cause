# 0043 — Arm B adds whole documents in a published rank order and stops at the cap; omissions are recorded and counted

Settles what arm B does when a docket is larger than the cost cap allows, which 0022 ("up to
the cost cap") left open. Written with the S2 specification (§9.2, §10).

## Context

At the default model's batch price a 10,000-token docket costs about a fifth of a cent and the
cap of five cents leaves room for about 488,000 prompt tokens after reserving the maximum
output (`scripts/exploratory/s2_design_measurements.py`, M1, M4). The cap does not bind on any
spike-sized docket with the default model. It binds with a dearer model: at Sonnet 5's
standard price the room is 15,000 tokens and the largest document the spike saw goes over
(M3). Model choice is a harness parameter, so the rule must be fixed now.

## Decision

1. Arm B adds documents whole, in a published rank order, and stops before the first that
   would take the case over the cap as estimated before the call, prompt at the input price
   plus the model's maximum output at the output price.
2. The rank order is by each document type's median estimated tokens on `dev-400`, ascending,
   published with the filter before any held-out run.
3. A document left out is written to the step record as `not read: cap` with its estimated
   tokens. The run report counts cases that hit the cap and documents dropped, by fatal and
   non-fatal, and the count is published beside the arm B result.

## Why

1. **A fixed pipeline must be explainable.** A skipped document is one line on the live
   board; a truncated one is not.
2. **The provenance header stays true.** It says 22 pages only when 22 were sent.
3. **The omission is visible.** A reader sees how much of the docket the bar was measured on.

## What this rules out

- **Truncating the last document to fit.** The model reads half a document without knowing
  it, and the tripwire's sentence check runs on a cut that may split a sentence.
- **No cap in arm B.** Ruled out by 0022 (unfiltered arm B is reported on development cases
  only) and 0030 (the cap is in code for every run).

## Status

Accepted, 2026-09-18 (Andy: "lets capture when that token cap is breached").
