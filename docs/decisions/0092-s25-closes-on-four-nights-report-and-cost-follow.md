# 0092 — S2.5 closes on four recorded nights; the 14-night report and billed cost follow as a dated addendum

## Context

Spec S2.5 §14 ("Done means") sets three conditions this record concerns: item 2, the recorder
has run on at least 14 consecutive nights, with a `runs` row for each; item 3,
`scripts/recorder_report.py` prints the run summaries and every number in the As-built record
comes from it; item 6, the stage's AWS cost is stated from the billing console.

The recorder has run on 4 distinct nights (5 runs). Stage S2.6 (pull request #10) is built on
this branch and cannot merge until S2.5 does. The merge does not affect recording: the nightly
AWS task keeps running from the image already in ECR, whatever the branch state.

## Decision

The stage closes now. Its As-built record cites the report over the 5 runs below.

The ≥14-night report and the billed AWS cost follow as a dated addendum to the As-built record,
produced by the same script, once they exist.

The 8-week measurements (spec §10.2: arrival distributions, the feed comparison, regulation
changes) were never part of §14 and stay where the spec put them.

## Why

Numbers come from `scripts/recorder_report.py`, run 2026-09-26 on the S3 store version written
2026-09-26T03:39:44Z. That source holds for every number below, in order of weight.

1. What §14 items 2–3 exist to show — that the recorder runs unattended, within its limits,
   with the store and the log agreeing — is already shown:
   - 5 runs on 4 distinct nights: 1 local container run, 1 manual AWS run, 3 scheduled AWS
     runs;
   - 5 of 5 finished; 0 unfinished; 0 failed requests;
   - 39–50 minutes per night, against the 65-minute run deadline and the 90-minute container
     limit;
   - the watched cases grew from 936 to 946, and every one was polled every night;
   - the report's run table matches the four `run done` lines in CloudWatch exactly (the local
     night has no CloudWatch log).
2. Ten more nights add little to that proof, and nothing to the stage's real questions — those
   are 8-week questions (§10.2). Four nights give only early signals, and the record must quote
   them as signals, not results:
   - the change feed reported 70 of 97 field changes (21 of 29 case-nights);
   - all 94 documents that appeared did so on the same run as their case closed, and none
     before closure;
   - 2 blank regulations were filled in as 091 and 2 as another part;
   - each field has only 6–13 true arrivals.
3. Holding the branch blocks S2.6 and raises the risk of decision-number clashes. CI's image
   push also cannot start until the merge (runbook stage 9).
4. This is a judgement, not a measurement: no number says when enough nights are enough.

## What this rules out

- **Waiting the full 14 nights.** This is the spec's own finish line, and its strongest form is
  that a close-out record should rest on the data it names. Rejected because it blocks S2.6 for
  about 10 days for data that proves nothing new.
- **Closing with no report at all.** Rejected: it breaks "every number comes from a script".
- **Dropping the 14-night report entirely.** Rejected: the addendum keeps the promise.

## Status

Accepted, 2026-09-26. Amends spec S2.5 §14 items 2, 3 and 6: the stage closes on four nights;
the ≥14-night report and the billed cost follow as a dated addendum to the As-built record.
