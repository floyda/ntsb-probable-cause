# 0107 — S2.7's spend counts only its own branches, not a later stage cut from one

Amends [0102](0102-a-parent-branch-with-a-branch-per-track.md) item 3 (how the stage's spend is
traced).

## Context

0102 item 3 counts S2.7's spend on every local branch whose history holds S2.7's first commit
(`94f5d42`), `main` excepted, plus HEAD. On 2026-09-29, `scripts/stage_spend.py` listed five such
branches: the three S2.7 branches, and `s28-coding-lookup` (S2.8's draft design) and
`s3-probe` (the S3 probe), both cut from S2.7's track 1 branch. Their commits would be counted
against S2.7's $25 line (decision 0098 item 6) once they spent anything; at that date neither
had, so the stage total was the same either way ($13.81, `uv run python -m scripts.stage_spend`).
Counting HEAD has the same fault: run from another stage's branch, it counts that branch.

## Decision

1. A branch counts only if it holds S2.7's first commit **and** its name starts with `s27-`
   (`STAGE_BRANCH_PREFIX`); `main` stays excluded.
2. HEAD is not counted. Every S2.7 commit is on an S2.7 branch, so nothing is lost.
3. The script prints the branches it counted, as before.

## Why

1. **A later stage's spend is its own**, against its own line, not S2.7's.
2. **The track names are constant** (0102, Andy's condition), so the prefix is stable.

## What this rules out

- **Counting every branch grown from the parent**, as 0102 item 3 first wrote it.
- **Counting HEAD.**

## Status

Accepted, 2026-09-29 (Andy approved the close-out steps that named this fix: "A, skip it and
carry on here").
