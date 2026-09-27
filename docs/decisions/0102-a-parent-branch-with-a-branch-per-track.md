# 0102 — S2.7 is a parent branch with a branch per track; its spend is traced on every branch grown from the parent

Amends [0093](0093-s27-runs-as-two-tracks-guidance-on-v1.md) item 3 (branches). Taken before
any code, on the S2.7 track 1 plan's walkthrough item W8.

## Context

0093 item 3 put the specification and track 1 on `s27-coding-guidance` and cut track 2's
`s27-transcriber` from it. The stage's $25 line (0098 item 6) is checked before every paid step
by counting the spend recorded against the stage's commits; the plan counted a fixed list of
branch names. Andy set the layout instead: a parent S2.7 branch from `main`, a branch per track
stacked on it, costs traced on the branches found from the parent, and track names that do not
change.

## Decision

1. **The parent** is `s27-coding-guidance`, cut from `main` at the S2.6 merge `971ee40`. It holds
   the specification, the decisions and both plans, carries the work both tracks need first (the
   spend check, track 1 plan Task 1), and becomes the stage pull request, `S2.7: coding guidance`.
2. **The tracks** are cut from the parent: track 1 on `s27-guidance`, track 2 on
   `s27-transcriber`. Their names do not change. Each merges back into the parent with a merge
   commit (0033); the meeting point, the sealed run and the close-out are done on the parent.
3. **Spend is traced on every branch grown from the parent**: `scripts/stage_spend.py` counts the
   commits reachable from HEAD and from every local branch whose history holds S2.7's first commit
   (`94f5d42`), `main` excepted, back to `971ee40`, and prints the branches it counted.

## Why

1. **Each track's work stays on its own branch** until it is finished, and the parent only ever
   receives finished tracks.
2. **A branch that grew from the parent is counted whatever it is called**; the constant names
   make the printed list predictable, so a missing branch is noticed.
3. **`main` is excluded** because once the stage merges it also carries later stages' commits.

## What this rules out

- **Track 1 on the parent itself**, as 0093 item 3 first wrote it.
- **A fixed list of branch names** as the only way the spend check finds the stage.
- **Counting spend by date.** S2.6 found a date filter caught another stage's runs.

## Status

Accepted, 2026-09-27 (Andy: "Assume we have a parent s2.7 branch from main. Stacked on that will
be a branch per track. Find costs traceable on branches found from the parent branch, the names
of the track branches will remain constant"; names: "A is fine").
