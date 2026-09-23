# 0083 — The monthly budget is $40 during development

Amends the $25 default of [0030](0030-cost-in-usd-cap-and-budget-in-code.md) item 2. Every other
part of 0030, and the reservation of [0045](0045-monthly-budget-is-a-reservation-under-a-lock.md),
is unchanged.

## Context

S2.6 adds transcription and a picture probe, which were not in Andy's original cost thinking.
Its estimate is about $17–27 of model calls, and more if the transcriber test chooses a dearer
model: Gemini 3.6 Flash is about three times the front-runner's price, which would put the
stage near $35–45 (S2.6 spec §11, estimates).

## Decision

1. The monthly budget is **$40** for the development stages, until the live board runs (S4),
   whose budget is decided there. `monthly_budget_usd` defaults to 40.
2. **A stage pause point.** When a stage re-estimates its remaining spend (in S2.6, after the
   transcriber is chosen) and the stage total passes the month's budget, work stops and Andy
   decides whether to spread it over months or reduce it.

## Why

1. **Andy's choice**, made when the cost of widening the docket was shown to him.
2. **The budget guard sees runs, not stages.** 0045 refuses one run that would overrun the month;
   it cannot see a stage drifting across several runs. The pause point can.

## What this rules out

- **Keeping $25 and spreading S2.6 over two months by default.** Slower, for no measured gain.
- **Raising the budget without a stage pause point.** The guard alone would let a stage spend
  the whole month before anyone looked.

## Status

Accepted, 2026-09-23 (Andy: "happy to extend budget during development to $40").
