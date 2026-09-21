# 0030 — Cost is recorded in US dollars from the provider; the cap and the monthly budget are enforced in code

## Context

The spike reported cost in pounds at an assumed exchange rate and measured $0.0454 per
case at list price through the Claude command line, eight times its static estimate
(`../ntsb-spike/scripts/oneshot_summary.py`). S1 is the first stage that pays for calls,
through OpenRouter, which bills in US dollars and reports usage per call. Andy's limit is
$25 a month on OpenRouter. The build brief asks for a hard per-case cap in code; the
roadmap says the cap is re-measured in S1 and S3.

## Decision

1. Cost is recorded per call in US dollars, from the provider's usage block where it reports
   cost and from the prices in `sources.py` where it does not; the record says which. The
   batch service reports cost per batch, so per-case cost there is tokens times price, and
   the batch total is stored as the check. No currency conversion appears in code or
   results.
2. Every run carries a per-case cap (`--cap-usd`) and a budget (`--budget-usd`, default
   $25). A call whose prompt estimate exceeds the cap is not made and the case is recorded
   as failed with reason `cap`. A run whose projected cost — cases times the measured cost
   per case from the probe, or the cap where there is no measurement — would take the
   month's ledger total past the budget does not start.
3. S1 records the ceiling's mean and p95 cost per case; S3 sets the per-case cap for the
   loop from those numbers. S1's cap is a run parameter, not the project's cap.
4. Evaluation runs use the provider's batch price variant where the probe confirms it is
   honoured (0009).

## Why

1. **Measured, in the unit billed.** A converted figure is an estimate twice over.
2. **A bound that cannot be exceeded by accident.** The spike's estimate was wrong by eight
   times; a flag that refuses the run is the only protection that works before the bill.
3. **Two caps for two questions.** The per-case cap bounds one case; the budget bounds a
   month. S1 needs the second more than the first.

## What this rules out

- **Cost only measured, not enforced.** The build brief already rejected this.
- **A project-wide cap set in S1.** S1 has no loop to measure; it records the numbers S3
  needs.

## Status

Accepted.

## Forward pointer, added 2026-09-21 (S2 close-out audit)

**The budget guard this record describes did not hold across runs launched together.** Four
held-out runs started in parallel on 2026-09-17 each read the month's spend before any of them
had written a cost, so each saw the same headroom and none of them saw the others.
[0045](0045-monthly-budget-is-a-reservation-under-a-lock.md) replaces the read-then-run check
with a reservation taken under `fcntl.flock` at run start and settled at the end. The per-case
cap and the decision to enforce cost in code rather than only measure it, which are the substance
of this record, both stand.
