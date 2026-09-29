# 0104 — The monthly budget is $50 for September 2026 only

Amends [0083](0083-the-monthly-budget-is-forty-dollars-in-development.md) item 1 for one month. Everything
else in 0083, [0030](0030-cost-in-usd-cap-and-budget-in-code.md) and
[0045](0045-monthly-budget-is-a-reservation-under-a-lock.md) is unchanged, and so is S2.7's
$25 stage line ([0098](0098-guidance-rounds-stop-rule-and-prediction.md) item 6).

## Context

On 2026-09-28 the budget guard refused S2.7's round 2 before any model call: $39.63 was
already spent in September (S2.6's runs, S2.7's Round 0 and Round 1, and track 2's preparation
spend), and the round reserves $1.68 (401 cases at $0.0042). S2.7 itself had spent $5.69 of its
$25 line. The alternative was to wait about two and a half days for the month to reset.

## Decision

1. For September 2026 only, the monthly budget is **$50**. It is set with
   `NTSB_MONTHLY_BUDGET_USD=50` in the environment of each paid command run in September, not by
   changing the code's default, which stays $40 (0083).
2. From 1 October 2026 the $40 line applies again, with no action needed.
3. S2.7's $25 stage line still applies to every paid step (`scripts/stage_spend.py`).

## Why

1. **Andy's choice**: "there are credits available so raise to $50 for September".
2. **A pause of two and a half days buys nothing.** The money is in the same account either
   way; the month line exists to make spend visible, and this record makes it so.
3. **One month, by environment, keeps the default honest.** Changing the default would carry
   the higher line into October without anyone deciding it.

## What this rules out

- **Waiting for 1 October.** Free, but it pauses both tracks for no measured gain.
- **A one-off `--budget-usd` on a single run.** The same decision, less visible.
- **Raising the default in code.** That would outlast September without a decision.

## Status

Accepted, 2026-09-28 (Andy: "there are credits available so raise to $50 for September").
