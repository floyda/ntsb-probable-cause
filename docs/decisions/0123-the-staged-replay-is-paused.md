# 0123 — The staged replay is paused: no docket has been seen before closure; re-checked at 14 nights

With [0121](0121-agency-moves-to-reading-and-coding.md), it takes 0023 item 4's masked condition
off the headline. From the S3 design session (2026-09-29 to 2026-09-30): replay paused. Detail:
[the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §9.

## Context

0023 item 4 reports two availability conditions: **full**, and **masked** (only what a live case
would have at day *N*, taken from measured arrival). 0023's Context said that docket documents
"arrive over months". Andy proposed a **staged replay**: closed development cases released to
the loop in steps, timed by the recorder's measured distributions, so that evaluation mimics
real arrival.

What the recorder has seen (`docs/results/s3-recorder-report-2026-09-29.txt`; 8 runs on 7
distinct nights, 23 to 29 September 2026):

- docket arrival before closure: 0 cases; in the same run as closure: 7; after closure: 0;
- documents that appeared at closure: 94; after closure: 0; new documents in runs 3 to 8 (24 to
  29 September): 0;
- structured fields, on cases seen first without a field and then with it, before closure,
  median days from the event: make, model, phase of flight and registration 3 (n=8); injury
  level 4 (n=9); weather condition 17 (n=15); METAR 18 (n=16). Engine type, pilot hours and
  pilot certificates appeared only in the same run as closure (6 or 7 cases each). These are
  small counts.

The earlier ongoing-docket probe agrees: 98 of 100 sampled ongoing cases had no released docket
(`docs/results/s25-ongoing-dockets.txt`).

If this holds, a live case's docket goes from none to all at closure, together with the verdict.

## Decision

1. **The loop handles all three docket states**, none, some and all, with the same code
   ([0122](0122-h0-and-later-triggers.md)). If documents turn up only at closure, the live page
   shows exactly that.
2. **The staged replay is paused**, and 0023's masked condition with it. S3.1 and S3.2 measure
   the full condition. Arm A still reports the start-facts-only score for every case.
3. **The recorder is re-checked at 14 distinct nights** (about 6 October 2026), with the same
   script (`scripts/recorder_report.py`), before S3.2's specification is fixed.
   - If dockets still arrive only at closure, S3.2 measures the full condition only, and says so.
   - If they arrive earlier, the replay design is reopened, in a new decision record.

## Why

1. **The mask must be measured, not chosen** (0023, Why 4). With no docket measured arriving
   before closure, any schedule for documents would be invented.
2. **Andy's requirement for the live board** (2026-09-29, spelling corrected): the live agent
   "will need to be able to deal with the case where no files exist, some files, and all files
   on closure ... if we find that they don't turn up until closure then that's just how it will
   have to be shown in the live page".
3. **The re-check costs nothing and comes before it matters.** The recorder runs every night
   anyway, and S3.2 is the first stage that would use a replay.

## What this rules out

- **A replay with a docket schedule from judgement.** Available now, and it would give the
  masked condition something to measure. Rejected by Why 1.
- **A masked condition on structured fields only, now.** Those fields do arrive before closure.
  Rejected for now, on judgement: the counts are small (8 to 16 cases a field), and the re-check
  at 14 nights will give more.
- **Dropping the replay for good.** Rejected: 7 nights is a short watch, and the re-check may
  show earlier arrivals.
- **Waiting for the recorder before building the loop.** Rejected: building the loop needs no
  replay, and the loop handles all three docket states anyway.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
