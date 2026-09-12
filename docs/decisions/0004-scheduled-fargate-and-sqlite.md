# 0004 — Scheduled Fargate task, SQLite in S3

## Context

Scheduled work has to run unattended: poll open investigations, diff docket listings, run
the agent where evidence changed, and score predictions when cases close. Polling a few
hundred dockets at a self-imposed 30 requests per minute takes about ten minutes before
the agent does anything. Volume is 1,000 to 1,400 cases a year.

## Decision

One scheduled AWS Fargate task, triggered by EventBridge Scheduler, running the same
container image that runs locally. State is a SQLite file in S3 with object versioning:
download, change, upload, single writer.

## Why

1. **The compute choice determines the store.** A single scheduled container is a single
   writer, which lets SQLite stay SQLite. Build brief §7 already judged SQLite sufficient
   at this volume. Fan-out would mean concurrent writers, therefore a different database,
   therefore two store implementations and a weaker local development story.
2. **Identical execution locally and in the cloud.** One image, one entrypoint. What runs
   on the laptop is what runs at 03:00, which makes "the evaluated agent is the deployed
   agent" concrete rather than asserted.
3. **No fifteen-minute ceiling** to design around for a job whose polling phase alone is
   ten minutes.

## What this rules out

- **Lambda with SQS fan-out.** The strongest version: it reads as conventional serverless
  production infrastructure, scales without thought, and bills only for execution. It is
  rejected because this is a batch workload with a single writer, and adopting fan-out
  would force a second store implementation to solve a concurrency problem we do not have.
  This is a judgement about matching the shape of the work, not a measurement.
- **GitHub Actions on a schedule.** Simplest and nearly free, but it is not the unattended
  cloud deployment this project set out to demonstrate.

## Cost

Estimated, not measured — to be replaced with billed figures once the stack runs. Fargate
at roughly 20 minutes a day: under £1/month. S3 and CloudFront: under £1/month. Model
calls dominate at roughly £5/month. A budget alarm is set separately from the per-case cap
in code, because the two fail differently: the cap stops one runaway case, the alarm
catches a pattern.

## Status

Accepted. See `docs/specs/2026-09-12-architecture-and-roadmap.md` §6.
