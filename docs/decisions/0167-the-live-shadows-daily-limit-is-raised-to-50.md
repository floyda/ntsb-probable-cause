# 0167 — The live shadow's daily limit is raised to 50 for the rest of S3.3

From Andy, 2026-10-09, after S3.3's third paid morning. Amends
[0157](0157-s33-codes-closures-through-a-queue.md) item 2 and its Why 3 (10 cases a UTC day becomes
50); 0157's other items, the closing rule among them, stand. The caps of
[0163](0163-the-live-shadows-caps.md) stand unchanged. Detail: the S3.3 plan's Deviations (Task 11).

## Context

1. **0157 set 10 cases a UTC day**, to spread a burst of closures over two or three mornings and
   to bound a day's worst cost at 10 × $0.30 = $3.
2. **Three mornings have run**, at 1, 9 and 10 cases (2026-10-08 and 2026-10-09). The two at the
   standard price (decision [0165](0165-live-runs-at-the-standard-price.md)) cost $0.0654 for 9
   cases and $0.0470 for 10, and took 14.2 and 12.4 minutes (ad-hoc, read from the mornings'
   summaries; S3.3's report script re-derives them).
3. **After the third morning, 42 cases were queued**: 27 left of the 47-case backfill list and
   about 15 fresh closures from the recorder's night of 2026-10-09. At 10 a day the backfill drains
   on the third morning from now, 2026-10-12, which is also when the closing rule would be met.
4. **The waiting cases are already closed.** Nothing more from the NTSB is needed to meet the
   closing rule. The days between mornings add no information, only delay.
5. **What the limit was there to show has been shown.** The queue has run over three mornings,
   with the backfill fixed, cases waiting their turn and one morning started by a schedule
   while nobody watched.

## Decision

1. **At most 50 cases a UTC day** across live runs, for the rest of S3.3
   (`live.queue.DAILY_LIMIT`). The count is per UTC day as before, so on 2026-10-09, with 10
   already coded, a morning takes at most 40.
2. **The spending-line checks before a morning** (`make s33-morning`'s two `stage_spend` lines)
   use the estimate for a full day: 50 cases at the $0.04 projection, $2.00.
3. **Every cap stands**: $0.30 a case, $5 a calendar month of live spend, S3.3's stop at $10 of
   its own spend, and the $40 monthly guard.
4. **S4 sets its own limit.** This one is S3.3's and ends with it.

## Why

1. **It reaches S4 three days sooner, for no lost information.** Andy, 2026-10-09: "yes lift it
   to 50 and lets get it done, then I can look towards S4 over the weekend".
2. **The cost is small**: at the two standard-price mornings' costs (about $0.005 to $0.007 a
   case), 40 cases cost about $0.20 to $0.30, and take about 50 to 60 minutes.
3. **It is the same queue, in the same order.** The cases coded and their order do not change.
   Only how many mornings it takes changes, so the result is not selected.

**What it gives up, stated plainly.** Under 10 a day the worst day could not pass $3. Under 50 it
can pass the $5 monthly cap: the cap is checked before a morning, as a projection at $0.04 a case
(40 cases come to $1.60), and is not a stop during the run. During the run, the run's budget is
the $40 monthly guard. A morning of 40 cases passes $5 only if the average case costs about
$0.12, about 20 times what the standard-price mornings measured, with each case still stopped at
its $0.30 cap.

## What this rules out

- **Keeping 10 a day.** It keeps the $3 bound on a day. Rejected: three more mornings for the
  same cases, in the same order, for no new information.
- **No limit at all.** Simpler. Rejected: a burst of closures (47 in 14 nights, all on three
  dates, 0157 context 3) would make an open-ended morning. 50 covers today's queue and keeps a
  morning to about an hour.
- **Changing the order, or skipping cases, to finish sooner.** Rejected: selection (0157 Why 2).

## Status

Accepted, 2026-10-09 (Andy, after S3.3's third paid morning).

## Glossary

- **Daily limit**: the most cases the live shadow codes in one UTC calendar day, across every
  live run that day.
- **Projection**: the cost a morning is assumed to have before it runs ($0.04 a case), used by
  the checks that refuse a morning before any call.
- **Closing rule**: 0157 item 5; the live runs end once the backfill has drained and a fresh
  closure has been coded, or 14 days pass with none.
