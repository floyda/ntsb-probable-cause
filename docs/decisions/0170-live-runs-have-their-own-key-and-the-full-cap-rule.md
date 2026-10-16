# 0170 — Live runs have their own key and limit; a night's size by the full-cap rule

From the S4 design session with Andy, 2026-10-10. Replaces, on the cloud path,
[0163](0163-the-live-shadows-caps.md)'s $5 month and $0.04 projection and
[0167](0167-the-live-shadows-daily-limit-is-raised-to-50.md)'s daily limit. Detail: the S4
specification, §8.

## Context

1. **S3.3's live runs shared the development key** and counted against the $40 monthly guard from
   `data/runs`. A resume near $40 could be refused inside the runner after the morning's own check
   passed (S3.3 As-built, carried item 3).
2. **The cloud task cannot read the Mac's `data/runs`.**
3. **OpenRouter sets a credit limit per key**, reset daily, weekly or monthly at midnight UTC, and
   `GET /api/v1/key` returns `limit`, `limit_remaining`, `limit_reset` and `usage_monthly`
   (external, OpenRouter's documentation, read 2026-10-10).
4. **A case costs about $0.005 billed** (estimate, from S3.2's held-out loop run, $2.0610 for 400
   cases, scripted, `docs/results/s32-claims-heldout.txt`); version 1's cap is $0.30 a case
   ([0144](0144-one-per-case-cap-for-every-arm.md)).

## Decision

1. **A separate OpenRouter key for live runs**, used only by the cloud task, with a **$10 a month**
   limit that Andy sets on OpenRouter, reset monthly. The development key keeps the $40 guard.
2. **The cloud's spend counter reads `usage_monthly`** from the live key. If the endpoint cannot be
   reached, or the key has no limit, the night refuses.
3. **Cases a night = floor((cap − `usage_monthly`) ÷ $0.30)**, the cap being $9, or the key's limit
   less $1 if lower. No daily limit and no projection.
4. **$0.30 a case stays.**
5. **An alert when money holds a night back.**
6. **S4's development spend line is $10** on the development key, counted by commit on `s4-`
   branches (`stage_spend --stage s4`). The S4 report states the first cloud nights' live spend
   apart.

## Why

1. **Two budgets that cannot reach each other** (Andy: "could the not have different budgets? maybe
   even separate keys and I can manage budgets in openrouter"). Development cannot starve the
   board, and the board cannot spend the development budget.
2. **The limit on OpenRouter is a backstop the code cannot get wrong.** The code's cap sits $1
   below it.
3. **The full-cap rule cannot overspend**: every case could run to its cap and the night would still
   fit. It does not starve the month, because the allowance falls by what cases really cost, about
   $0.005 each, not $0.30: 100 closures use about $0.51.
4. **Carried item 3 dissolves**: the container's `data/runs` is empty, so the $40 guard never binds
   on the live path.

## What this rules out

- **Keeping one key with a projection.** Fewer moving parts. Rejected: the shared guard is what
  caused carried item 3, and the cloud cannot read it.
- **A $20 limit** (Claude's first suggestion). More headroom. Rejected by Andy: "$10 a month … more
  than enough and allow me to use the remaining budget for any further development".
- **Sizing a night by the expected cost.** Codes more cases a night. Rejected: a fault that made
  every case run to its cap could pass the limit mid-night.

## Status

Accepted, 2026-10-10 (Andy).

## Amended, 2026-10-12 (appended; nothing above is edited)

- On a resume, the full-cap rule is applied to the remaining exposure: for each unanswered case, $0.30 less the computed cost already recorded for it ([0185](0185-a-resumed-night-pays-what-is-left-and-codes-the-same-docket.md), item 1).
