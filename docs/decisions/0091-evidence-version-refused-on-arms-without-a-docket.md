# 0091 — A run's evidence version must be true: v2 and v3 are refused on arms that read no docket

Amends spec §3.1 of S2.6 ("any arm can run on any version") and
[0076](0076-evidence-version-is-an-axis-not-an-arm.md)'s axis for the arms that read no docket.

## Context

Decision 0076 made the evidence version an axis every run records: v1 reads the docket's text
layers, v2 adds transcriptions, v3 adds pictures. The label is written to the run's `spec.json`,
its run record and, for a held-out run, the held-out ledger. Arm A (start facts only) and the
ceiling (one answer, no docket) read no docket at all, yet `Runner.run` accepted
`--evidence-version v2` on them (Task 14 review, I1): such a run would be recorded as having read
transcriptions it never read.

## Decision

`Runner.run` refuses, before any budget reservation or model call, a run whose evidence version
is not v1 on an arm that reads no docket (arm A, the ceiling), saying why.

## Why

1. **The label is evidence about the run.** A reader months later trusts `evidence=v2` to mean
   transcriptions were read; on these arms it could not be true.
2. **Nothing needs the combination.** No planned measurement runs arm A or the ceiling on v2 or v3.

## What this rules out

- **Reading spec §3.1 literally** for arms without a docket.

## Status

Accepted, 2026-09-26 (Andy: "Yes it should refuse it").
