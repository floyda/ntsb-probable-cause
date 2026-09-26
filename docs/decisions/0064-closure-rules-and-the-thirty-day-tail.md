# 0064 — Closure: status changes are events, nothing is deleted, the verdict is never stored, and the docket is watched for 30 days after

## Context

When a case closes, three things change together: `completionStatus` leaves `Ongoing`, the
API deletes the preliminary narrative (S0 corpus scan: empty in all 19,641 closed cases), and
the verdict appears in the record. The recorder sees all three on the same night. Held-out
evaluation reads each docket as it stands years after closure; a live agent reads it as it
stands before. The roadmap's risk table lists this as "held-out and live evidence differ",
with no number behind it.

## Decision

1. A status change is a `status_events` row with old status, new status and interval, like a
   document arrival. `Ongoing` → `N/A`, a case the API stops returning ("not returned"), and
   `Completed` → `Ongoing` are recorded the same way.
2. Nothing is deleted. The stored preliminary narrative stays after the API removes it.
3. The verdict is never stored. Every record passes through `split_record`; probable cause,
   codes and both narratives are dropped before anything is written. The status and the NTSB's
   publication dates are kept.
4. A docket change and a closure seen in the same poll carry the same interval and no order.
5. The docket is polled daily for 30 days after the status leaves `Ongoing`, then not at all.

## Why

1. **The same form for every event** keeps the store to one rule (specification §3).
2. **Capturing the preliminary narrative before deletion is the reason the recorder stores
   it** (0023, 0024).
3. **The one split, and no second path.** The S4 watcher reads the verdict to score, under its
   own rules; the recorder has no reason to hold it and every reason not to.
4. **Honesty about order.** Two changes between the same two runs cannot be ordered, and the
   store must not pretend otherwise. This may be the common case if dockets open near closure,
   which nothing has measured; the recorder is how the project finds out.
5. **The 30-day tail turns a caveat into a number**: how many documents arrive at or after
   closure, which a live agent never saw. About 100 cases close a month, about 3 minutes added
   to the nightly pass. The 30 days is a judgement; the run summary shows whether changes still
   arrive late in the tail.

## What this rules out

- **One final observation at closure, then stop.** Simpler; would not learn whether dockets
  keep growing afterwards, and one saved page shows Last Modified years after Creation Date.
- **Polling closed cases for ever.** About 1,200 cases a year added with no end, against the
  simple daily pass of 0060.
- **Storing the verdict "for convenience" at closure.** A second place the verdict lives.

## Status

Accepted, 2026-09-22.
