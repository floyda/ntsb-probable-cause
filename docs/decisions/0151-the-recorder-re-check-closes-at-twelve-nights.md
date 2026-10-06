# 0151 — The recorder re-check closes at 12 nights: dockets almost always arrive at closure, and S3.2 measures the full condition only

Amends [0123](0123-the-staged-replay-is-paused.md) item 3, which set the re-check at 14 distinct
nights. From Andy, 2026-10-04, during S3.2's Task 12. Detail: the S3.2 specification
(`docs/specs/2026-10-03-s3-2-claims-design.md`) §14 item 1, and the S3.2 plan's Deviations.

## Context

1. **What 0123 set.** The staged replay, and the masked condition with it, were paused because
   no docket had been seen to arrive before its case closed. The recorder was to be re-checked at
   14 distinct nights (about 6 October 2026). If dockets still arrived only at closure, S3.2
   would measure the full condition only; if they arrived earlier, the replay would be reopened.
2. **What the recorder shows now** (`docs/results/s3-recorder-report-2026-10-04.txt`; 13 runs on
   12 distinct finished nights, 23 September to 4 October 2026):
   - docket arrival: before closure 0; in the same nightly run as closure 46; after closure 0;
   - first-sight dockets (documents already present at the first poll of a watched open case, so
     with no arrival time): 5;
   - structured fields that do arrive before closure: make, model, phase of flight and
     registration on 24 cases each (median 5 days from the event), injury level on 23 (median
     5), weather condition on 29 (median 16), the METAR on 31 (median 20).
3. **The snapshot reading, already on file.** Andy asked whether looking at every open case for a
   docket would settle the question as well as the timed watch. The recorder already polls every
   watched open case's docket each night, and the S2.5 probe sampled 100 ongoing cases
   (`docs/results/s25-ongoing-dockets.txt`): 2 had a released docket. With the recorder's 5
   first-sight dockets among about 960 watched cases, roughly 1% to 2% of open cases hold a docket
   before closure. A snapshot cannot say when those documents appeared; the timed watch can, and
   every docket it saw appear (46 of 46) appeared in the same night as the closure.
4. **What two more nights could add.** A handful of new closures. They cannot change the reading
   that matters for S3.2 (Why 2).

## Decision

1. **The re-check closes at 12 distinct nights**, with the report committed as
   `docs/results/s3-recorder-report-2026-10-04.txt`. 0123's 14-night wait is not kept.
2. **The accurate statement is "dockets almost always arrive at closure".** Every timed arrival
   (46 of 46) came in the same nightly run as the case's closure; about 1% to 2% of open cases
   already hold a docket whose arrival time is unknown. Later documents quote this statement, not
   "only at closure".
3. **S3.2 measures the full condition only**, as 0123 item 3 provided for this outcome. The staged
   replay and the masked condition stay paused (0123 item 2).

## Why

1. **The timed reading is unambiguous on what it can see.** 46 of 46 dockets the recorder watched
   appear did so at closure. 0123's 7 of 7 is now 46 of 46.
2. **A staged-evidence measurement would have nothing to measure in S3.2.** It could apply only to
   the open cases that hold a docket before closure, about 1% to 2%. On `heldout-400` that is
   roughly 4 to 8 cases, far too few for any paired difference. So whichever way two more nights
   came out, S3.2's runs would be the same.
3. **The reason for closing early is that waiting cannot change the outcome, not that the reading
   is welcome.** The rule was set in advance to protect against a design built on a short watch;
   the watch is now six times larger in arrivals, and the remaining question (the 1% to 2%) is one
   no number of nights can answer, because it needs arrival times for dockets that were already
   present when first seen.
4. **Andy (2026-10-04):** "Can we not resolve this by looking at all open cases and determine if
   any have dockets? surely this is just as conclusive as the 14 day recorder?", then, on the
   answer above, "yes go that way, makes much more sense".

## What this rules out

- **Waiting the two nights to 6 October.** It keeps 0123 to the letter. Rejected by Why 2 and 3:
  it delays the paid runs by about two days for a reading that cannot change them.
- **Saying "dockets arrive only at closure".** Shorter. Rejected: about 1% to 2% of open cases hold
  a docket before closure (Context 3).
- **Reopening the staged replay for the 1% to 2%.** Rejected by Why 2. The mask must be measured,
  not chosen (0023, Why 4), and those dockets carry no arrival time.
- **A masked condition on structured fields alone, in S3.2.** Those fields do arrive before closure,
  now on 23 to 31 cases each. Not taken up in S3.2: arm A already reports the start-facts-only
  score, and S3.2's run list is fixed (0141). It stays open for S3.3 and S4, where live cases
  arrive in exactly that order.

## Status

Accepted, 2026-10-04 (Andy, S3.2 Task 12).

## Glossary

- **Full condition**: every evidence field and every docket document a closed case holds.
- **Masked condition**: only what a live case would hold on day *N*, from measured arrival times.
- **First-sight docket**: documents already present the first time the recorder polled the case,
  so their arrival time is unknown.
- **Staged replay**: closed cases fed to the loop in steps, timed by measured arrival.
