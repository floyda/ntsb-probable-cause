# 0065 — The event months are re-fetched nightly as the source of truth; the change feed is stored beside them and compared by script

## Context

The roadmap (§S2.5 and CLAUDE.md) planned "incremental ingestion by modification date". The
endpoint for it, `/api/Common/v1/GetCasesByModifiedDateRange/` (`../ntsb-spike/public.yaml:330`),
had never been called. It was probed once in the design session with a throwaway script, and
the data discarded (ad-hoc; re-established by `scripts/change_feed_probe.py` in the stage).
It is a change feed: a list of 30-field summary rows with `mkey`, `caseClosed`,
`lastChangeDateTimeUtc` and `stepNumber`, and no evidence fields. It reports open cases (93 of
195 aviation rows in 7 days were not closed), ignores the `mode` parameter, and returned 564
rows for 30 days in one response. What one probe cannot show is whether every change to an
evidence field moves `lastChangeDateTimeUtc`: a feed that ignores small edits looks exactly
like a quiet case.

The endpoint ingestion already uses, `GetCasesByDateRangeV2`, returns full records by event
month, one request per month. Every ongoing case sits in one of about 56 months (ad-hoc; the
oldest is from 2022).

## Decision

Each night the recorder re-fetches every event month from the earliest watched case's month
to the current month, compares each watched record with its last snapshot, and writes only
changes. That is the source of truth. It also makes one call to the change feed for the last
two days and stores each aviation row's change timestamp, step number and closed flag in
`change_feed`. After 8 weeks `scripts/recorder_report.py` counts how many of the field changes
the re-fetch found the feed also reported within a day. The window sets itself from the
store; on an empty store it walks back until 12 consecutive months hold no ongoing Part 91
case.

## Why

1. **The re-fetch uses only code and API behaviour the project already has**, and it catches a
   change whether or not the feed reports it. About 56 requests, about 2 minutes.
2. **The feed carries two things no other endpoint has** — an NTSB-side change time finer
   than a daily poll, and the investigation step — at the cost of one request and one table.
3. **A measured switch, not a guessed one.** If the feed reported every change, feed-first
   fetching becomes a decision with a number behind it. If it missed some, the project knows
   not to rely on it. This is a departure from the roadmap's wording, taken because the
   endpoint turned out not to return records at all.
4. **A self-setting window** never needs a typed start date and shrinks as old cases close.

## What this rules out

- **The feed as the only source now.** Its completeness is unmeasurable from one call, and a
  missed change is silent.
- **A fixed start month typed into the code.** The first-run walk-back finds the oldest open
  case whatever it is on the day the recorder first runs.
- **Fetching old stragglers one at a time by the single-case endpoint.** Saves perhaps 20
  requests a night and adds a second unprobed endpoint.

## Status

Accepted, 2026-09-22.
