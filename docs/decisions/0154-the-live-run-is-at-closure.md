# 0154 — The agent's live run is at closure, and the site shows no answers locked before the verdict

From Andy, 2026-10-04 to 2026-10-06, in the S5 site design session. Detail: the Draft
specification `docs/specs/2026-10-04-s5-public-site-design.md`, §8 and §13.

## Context

1. **The roadmap's live board** described predictions on open cases, locked, and scored when the
   NTSB later publishes (`docs/specs/2026-09-12-architecture-and-roadmap.md`, §8 and S4).
   Decision [0140](0140-the-precedent-tool-after-s4-as-a-measured-v2.md) item 3 has version 1 and
   version 2 "both locked before the NTSB publishes".
2. **Dockets arrive at closure.** Decision
   [0151](0151-the-recorder-re-check-closes-at-twelve-nights.md) found 46 of 46 timed docket
   arrivals came at closure. The recorder's report at 14 finished nights, the threshold at which
   it is citable, says the same: no docket appeared before its case closed, 46 dockets appeared
   on the night their case closed, and 5 of the 936 cases watched from the first night already
   held one (`docs/results/s5-recorder-report-2026-10-06.txt`).
3. **Without the docket the agent does no better than guessing.** On `heldout-400`, the loop
   without the docket scored occurrence top-1 15.0%, against the no-model baseline's 17.7%
   (`docs/results/s32-claims-heldout.txt`, `docs/results/s1-bars.txt`).

## Decision

1. **The agent's main live run is made when the NTSB closes a case**, from the docket as
   published at closure, with the verdict withheld by the same split and guard as in evaluation
   (decisions 0013, 0016, 0077).
2. **The site shows no answers locked before the verdict.** The Open cases page carries one
   counted line, such as "5 open cases have a docket so far", and those cases are coded at
   closure like every other.
3. **This amends 0140 item 3**: the live head-to-head of version 1 and version 2 is made by
   coding the same newly closed cases, at closure, not by answers locked before publication.
4. **Whether S4 still runs and locks answers on the rare early dockets is S4's decision.** A
   stored answer that cannot be edited afterwards is still kept for every case, as proof that
   rows were not changed later.
5. **For each closure run, S4 records** the date, time and commit that coded it, and each read
   document's title, joined from the docket listing by position (a document classed as
   synthesis is shown as withheld, never its text). **S4 also records the model's published
   training cut-off**, so the site can say whether a case closed after it.
6. **For S3.3**: a nightly shadow on open cases would mostly run on the recorded facts alone.
   The runs worth exercising are closure runs and the backfill of decision 0155. S3.3's
   specification decides how its shadow uses this.

## Why

1. **The evidence arrives at closure.** A run before closure reads almost nothing, and on the
   recorded facts alone the agent does no better than guessing.
2. **Each closure is still a fair test.** The verdict is public by then, but the split and its
   guard withhold it, every run records its commit, and the cases are newer than anything the
   agent was developed on. If the cases also closed after the model's training cut-off, they
   are the cleanest test the project has; item 5 makes that checkable rather than assumed.
3. **Building a locking mechanism for a handful of cases a year** would cost S4 time for almost
   no evidence.

## What this rules out

- **Locked answers before the verdict, as the live claim.** The strongest case: it is the only
  test made before the answer exists anywhere, so no one can suspect the verdict reached the
  agent. Its cost: on the count, almost no cases, and those few would be coded from the
  recorded facts, where the agent does no better than guessing.
- **A first belief for every open case.** About a thousand weak guesses about fatal accidents,
  paid for and published, would mislead.

## Status

Accepted, 2026-10-06 (Andy: "Closure is where they get coded by agent and ntsb"; on the early
docket section, "yes A").

## Glossary

- **Closure run**: the agent coding a case on the night the NTSB closes it.
- **Early docket**: a docket that appears while the case is still open.
- **Locked answer**: an answer stored, with its time, before the verdict exists.
