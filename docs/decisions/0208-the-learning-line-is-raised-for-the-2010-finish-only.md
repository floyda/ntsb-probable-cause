# 0208 — The learning line is raised for the 2010 finish only

From Andy, 2026-10-16. Detail: `docs/rounds/memory-pilot.md` §5 and §10; the plan's Deviations,
2026-10-16, Task 16 Step 5.

## Context

1. **The registration names this stop.** If `finish` projects a cost past the $90 learning line
   with Sonnet as the applier, it refuses before any call, the pilot stops, and Andy decides by
   record whether to raise the line or stop (`docs/rounds/memory-pilot.md` §5).
2. **It happened on 2010.** `make mem-learn-finish RUN=20261016T102829Z-beba05b-memory-2010
   TO=pilot-2010` projected the first Sonnet apply at most $135.9010 for 2,370 calls. The learning
   line's October total was $15.7012 (`budget.learning_month_spent`). $15.7012 + $135.9010 passes
   $90, so it refused. Nothing was spent on it.
3. **The projection is high on purpose.** It prices every call at its full 4,000-token output
   limit (§10). In the fresh 2009 run, the 2,168 Sonnet apply calls cost $5.0242, with a mean
   output of 177 tokens and a largest of 714 (`calls.jsonl` of
   `20261016T061311Z-0efdd63-memory-2009`). 2010 applies over about twice the cases.
4. **The check runs before each phase.** If a revision changes a lesson, `finish` applies a second
   time. That second apply is checked against the month's spend so far plus its own projection,
   which will again be about $136 or more (2009's second apply projected $47.07 against its first
   $45.46).

## Decision

1. **For the one command** `make mem-learn-finish RUN=20261016T102829Z-beba05b-memory-2010
   TO=pilot-2010`, `NTSB_LEARNING_MONTHLY_BUDGET_USD` is set to **$175** in that command's
   environment. The default in `settings.py` stays $90, and every other learner command keeps it.
2. **Why $175 and not $155.** $155 clears the first apply ($15.7012 + $135.9010 = $151.6122). It
   would not clear a second apply: about $23 spent by then plus about $140 projected. $175 clears
   both with a margin.
3. **The Console workspace's spend limit stays the hard stop** (0207 item 2). The expected real
   cost of the step is about $7–13, from 2009's measured rates (context 3).
4. **Nothing else changes.** The applier, the cap, the checks, the order of runs and the stop rule
   are as registered.

## Why

1. **The projection is about twenty times the measured cost** of the same calls on 2009 (177 of
   4,000 output tokens on average). The line was set to protect the credit, and the expected spend
   stays well under it.
2. **The registered verdict needs `pilot-2010`.** The stop rule is read on the memory run after
   2010. Stopping here would leave the pilot without a verdict.
3. **One command, by record.** Raising the default would weaken the guard for every later learner
   step. Raising it for one named command keeps it everywhere else.

## What this rules out

- **Stopping the pilot at `pilot-2009`.** Rejected by Andy: no verdict.
- **Changing how the projection is computed** (for example, from 2009's measured output). Rejected
  for now: a code change under review, slower, and the registration fixes the projection's rule.
- **Raising the default line.** Rejected: see Why 3.

## Status

Accepted; amends [0207](0207-the-pilots-money-and-tooling.md) item 2 for one command only.
Approved by Andy, 2026-10-16 ("Raise it and get on with it"). Andy approved raising the line for
this step; the figure $175 rather than the $155 first put to him follows from context 4.
