# 0175 — Fetch failures are counted, and every message has a runbook row

From the S4 design session with Andy, 2026-10-10. Amends
[0157](0157-s33-codes-closures-through-a-queue.md) (a case that fails before it is seen returns).
Detail: the S4 specification, §7.1 and §7.3.

## Context

1. **A case whose fetch fails is not seen, so it returns**, under 0157, without limit. None returned
   in S3.3 (S3.3 As-built, carried item 6).
2. **An NTSB outage would fail every case at once**, which says nothing about any one case.
3. **Two messages had no runbook row** (carried item 4): a fetch or docket error printed by class
   alone, ending "Tell Claude if it happens again" (`apps/live/__main__.py`), and "the store is not
   sound" (`store/db.py`).

## Decision

1. **A failed fetch counts against a case only on a night when other cases fetched.** A night when
   every fetch failed is an outage: it counts against no case and sends one alert.
2. **After 3 counted failures, an alert. After 7, the case is "not coded: unreachable"**, final.
3. **Counts are kept per night** in `nights/<date>/night.json`.
4. **Every message and alert kind has a row** in the S4 runbook; the two messages gain failure
   kinds `fetch-failed` and `store-unsound`, and the first names its row instead of "Tell Claude".

## Why

1. **A bound without punishing outages**: a case unreachable for a week of good nights is settled;
   an NTSB outage moves nothing.
2. **Short numbers for a demo** (Andy: "This is just a demo so I think A but shorten to 3 and 7").
3. **An unattended task must say what to do**, not ask for Claude.

## What this rules out

- **Returning without limit.** Never gives up on a case. Rejected: one broken case would retry
  forever, unseen.
- **Counting every failed night.** Simpler. Rejected: an outage would settle healthy cases.

## Status

Accepted, 2026-10-10 (Andy).
