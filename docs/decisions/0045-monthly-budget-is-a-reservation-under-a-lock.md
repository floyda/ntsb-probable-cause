# 0045 — The monthly budget is a reservation taken under a lock at run start and settled at the end

Fixes the defect S1's As-built record logged: the budget guard of 0030 did not hold across
runs launched together. Written with the S2 specification (§3.3).

## Context

A run read the month's spend once at start and wrote its own cost only at the end. Four runs
launched seconds apart on 2026-09-17 each saw zero spent and each projected $20 against a
$25 budget; actual spend was about $1.30. `CLAUDE.md` says the budget is enforced in code,
and it was not.

## Decision

1. At start a run takes a lock on the runs directory, sums the month's finished costs plus
   every other run's open **reservation**, and refuses if its own projection would take the
   total over budget. Otherwise it writes its projection as a reservation and releases the
   lock.
2. At the end, or on abort, the reservation is replaced by the actual cost.
3. A run that dies leaves its reservation standing, so the guard errs towards refusing.
   `ntsb-eval release RUN_ID` clears one by hand; `report` lists open reservations.
4. The test starts two runs in sequence against one directory and shows the second sees the
   first's reservation.

## Why

1. **Projections already exist**; the new code is the lock, the record and one test.
2. **Parallel runs stay possible.** S1 turned nine hours of batch queue into thirty-six
   minutes by launching in parallel, and the guard must allow that.
3. **Erring towards refusing is the right failure** for a metered service.

## What this rules out

- **One lock for the whole run, so runs never overlap.** Serialises an hour of provider
  waiting per run and still does not see a run that crashed holding the lock.
- **A rule in prose, "launch runs one at a time".** What failed on the 17th.

## Status

Accepted, 2026-09-18 (Andy).
