# 0206 — The steering slice is named `dev-steer-400`

From Andy, 2026-10-15. Detail: `docs/specs/2026-10-08-coding-memory-design.md` §5.

## Context

1. **Two guards read a sample's name.** `samples.refuse_unless_development` refuses a sample whose
   name does not start with `dev`. `coding_stats.refuse_pool_holding` checks only samples whose
   names start with `dev`.
2. **[0203](0203-the-steering-slice-and-statistics-without-it.md) named the slice
   `pool-steer-400`.** That name starts with neither prefix.
3. **So a run could pair the slice with S3's statistics, and no guard would refuse it.** S3's
   statistics hold the slice's verdicts, so the slice would be scored with its answers in hand.

## Decision

1. **The steering slice is `dev-steer-400`.** This amends 0203 item 1 for the name only. Its seed
   (20261014), its draw and its use are unchanged.

## Why

1. **The existing guards then do their work.** They refuse `("s3", "dev-steer-400")` and allow
   `("mem", "dev-steer-400")`, with no change to shared code.

## What this rules out

- **Keeping the name and widening both guards.** Rejected: two edits to shared code, and every
  later guard would have to remember a second prefix.

## Status

Accepted; amends 0203 item 1. Approved by Andy, 2026-10-15.
