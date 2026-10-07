# 0158 — S3.3's live runs are made on Andy's Mac, at the batch price; S4 moves them to AWS

From the S3.3 design session with Andy (2026-10-07). Detail:
[the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §4 and §4.1. Amends, for
closure runs, the roadmap's §4 sentence that the live path does not use the batch price
(`docs/specs/2026-09-12-architecture-and-roadmap.md`).

## Context

1. **The cloud runs only merged code.** CI builds the recorder's image only on a push to `main`
   (`.github/workflows/ci.yml`), and the deploy role trusts `main` only.
2. **S3's spend line counts by commit on `s3-` branches** (0128 item 2), and the $40 monthly guard
   reads spend records from the local run folders (`scoring/budget.py`).
3. **Paid runs already go through `scripts/paid_run.sh`**, from a clean checkout reset to the
   branch tip, with the key read from `pass`.
4. **The roadmap's §4** says evaluation uses the batch price and "the live path does not". It was
   written for answers on open cases, where speed might have mattered.
5. **Nobody watches a closure run as it happens** (0154: the board lists closed cases).

## Decision

1. **In S3.3 the closure runs are made on Andy's Mac**, by `NTSB_PAID_BRANCH=s3-3-live-shadow
   scripts/paid_run.sh s33-morning`, after `aws login --profile ntsb`. The cloud task, its
   schedule, its key and its spend count are S4's.
2. **At the batch price**, the service Ellery version 1 was measured on.
3. **Timing:** a morning starts after the recorder's night has finished (the command checks the
   store) and warns when started after 09:00 UTC, so its 10 to 15 batch rounds fall inside
   01:00 to 12:00 UTC, when batches finish fastest.
4. **S4 chooses its own service** for the cloud.

## Why

1. **It is the quickest route to S4.** Nothing new on AWS; spend counts in S3's line and the
   monthly guard as every run does now. Andy, spelling corrected: "given S4 was meant to be the
   online agent, it probably makes sense to get running on mac first and then move onto AWS in
   S4".
2. **Batch, because speed buys nothing.** Andy: "They won't be watched live though, so it feels
   like batch processing is probably good enough?" It is also half the price and the same
   service v1 was measured on.
3. **A missed morning loses nothing:** the queue is worked out from the store each time.

## What this rules out

- **A second nightly Fargate task in S3.3.** The strongest case: it runs unattended and
  rehearses exactly what S4 will run, for about $0.10 a month of AWS. Its cost: S3.3 would need
  two pull requests (code merged before the shadow nights), its spend would sit outside S3's
  line, and the monthly guard would need to read cloud spend records.
- **A step inside the recorder's task.** Rejected: the task is killed at 90 minutes and a killed
  night uploads nothing, so a long shadow could cost a recorder night, which can never be rebuilt.
- **The standard price.** Rejected: twice the cost, and not the service v1 was measured on.

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).

## Glossary

- **Batch price**: the provider's half-price queued service.
- **Fargate task**: a container AWS starts, runs and stops; paid only while it runs.
