# 0157 — S3.3 codes closures through a queue of 10 a day, rehearses the backfill, and closes by a fixed rule

From the S3.3 design session with Andy (2026-10-06 to 2026-10-07). Detail:
[the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §3 and §11. Applies
[0154](0154-the-live-run-is-at-closure.md) item 6 and
[0155](0155-the-board-is-backfilled-from-the-recorders-first-night.md) to S3.3.

## Context

1. **The S3 specification's outline** (§11) planned nightly batch runs on open cases that
   changed, with a first pass over about 940 watched cases.
2. **Decision 0154** moved the live run to closure: dockets arrive on the night the NTSB closes a
   case (46 of 46 in 14 nights; none before; `docs/results/s5-recorder-report-2026-10-06.txt`),
   and on the recorded facts alone the loop scored 15.0% against the no-model baseline's 17.7%.
   Its item 6 left S3.3 to decide how its shadow uses closure runs and the backfill of 0155.
3. **Closures come in bursts**: 47 cases closed in those 14 nights, all on three dates (ad-hoc,
   from the S5 session's read-only query of the store; S3.3's report script re-derives it).

## Decision

1. **The shadow codes closures, nightly, and rehearses the backfill once.** A case enters the queue
   when the recorder first records its status leaving Ongoing, to Completed or N/A
   (`Store._closure_runs`), on or after 23 September 2026. It is coded once, from the docket as
   published, with the verdict withheld.
2. **A queue, at most 10 cases a UTC day** across live runs. Cases over the limit wait for the
   following mornings, oldest closure first, ties by the recorder's case key (mkey). Nothing about
   a case decides its place.
3. **One run per case.** A case is **seen** once its first model call is sent. A case that fails
   after it is seen (format, guard, cap, ceiling) is recorded "not coded" and never tried again; a
   case that fails before it is seen (the API, the docket site or the store unreachable) returns to
   the queue. A run interrupted mid-round is resumed, never restarted.
4. **The backfill list** is the queue as it stands on the first live morning. It is fixed then,
   kept in the first run's folder, never committed (0024); the committed results file holds its
   count and its SHA-256. S3.3's runs are a rehearsal and never become board rows: S4 codes the
   backfill again at launch, as 0155 says.
5. **The closing rule**, fixed before any run: the live runs end once the backfill has drained
   and either a fresh closure (one after the backfill list was fixed) has been coded, or 14 days
   have passed since the first live morning with none coded.

## Why

1. **Closure is where the evidence is** (0154). A pass over open cases would mostly code facts
   alone, below the no-model baseline.
2. **A queue, not a skip**: skipping cases over the limit would leave them uncoded, which is
   selection (0155, Why 1). Andy, 2026-10-07: "A because there aren't closures every day anyway".
3. **Ten a day** spreads a burst over two or three mornings and bounds a day's worst cost at
   10 × $0.30 = $3 (decision [0163](0163-the-live-shadows-caps.md)). Andy: "A but we might want an
   upper limit on cases in one night"; then "Can we reduce it to 10 cases a night".
4. **One run per case**: a second try is a second draw, and choosing between draws flatters the
   result. A case Ellery never saw is not a draw.
5. **The closing rule** proves both runs S4 depends on (the backfill and a fresh night's
   closures) without waiting weeks for a burst; fixing it now stops the stage closing at a
   convenient moment.

## What this rules out

- **A nightly pass over open cases, and a first pass over the 960 watched.** The S3 outline's
  plan. Rejected by 0154: facts alone score below the baseline.
- **Skipping cases over the limit.** Simpler. Rejected: selection.
- **Closing after the backfill alone.** About five mornings. Rejected: it never shows a fresh
  closure being picked up, which is S4's trigger.
- **Four fixed weeks of mornings.** More scored cases. Rejected: it delays S4 for figures S4's
  board gathers anyway.
- **25 cases a day.** Andy's first choice. Replaced by 10 the same day.

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).

## Glossary

- **Backfill list**: the closures from 23 September 2026 to the first live morning, fixed then.
- **Fresh closure**: a case that closes after the backfill list is fixed.
- **Seen**: a case whose first model call has been sent.
- **Second draw**: running the same case again; answers vary between identical runs.
