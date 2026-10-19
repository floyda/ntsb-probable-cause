# 0177 — Alerts by email, and one free alarm

From the S4 design session with Andy, 2026-10-10. Detail: the S4 specification, §7.2.

## Context

1. **An unattended task must tell Andy when it needs him**, and when it did not run at all.
2. **Andy's rule** (2026-10-10): "I see no reason to add extra cost, so either the alarm fits under
   the free tier or we go with the simplest option C".
3. **The free tiers** (external, AWS SNS and CloudWatch pricing pages, read 2026-10-10): SNS, 1,000
   email notifications a month; CloudWatch, 10 custom metrics and 10 alarm metrics. The recorder's
   stack uses none.

## Decision

1. **The task publishes one email per failure condition** to an SNS topic, naming the kind and the
   counts, never a case number (the kinds are listed in the specification, §7.2).
2. **One custom metric**, one data point per finished night, and **one CloudWatch alarm** that fires
   when no night has finished for 30 hours, treating missing data as breaching.
3. **Andy confirms the email subscription.**
4. **If the first bill shows a CloudWatch charge**, the alarm and metric are removed, and the task
   sends one summary email every night instead.

## Why

1. **A task that crashes cannot report its own crash.** The alarm watches from outside.
2. **It fits the free tier**, with a stated fallback if the bill disagrees.
3. **Kinds and counts only** keep emails within decision 0024.

## What this rules out

- **A nightly summary email only** (option C). Zero cost for sure. Kept as the fallback: it misses a
  night that never starts unless Andy notices the silence.
- **A paid monitoring service.** Rejected: cost, for one task a night.

## Status

Accepted, 2026-10-10 (Andy: "Agreed").

## Note, 2026-10-16 (appended; nothing above is edited): item 4 read before the first bill

October's first bill was not out at S4's close-out, so AWS Cost Explorer's month to date stood in
for it. CloudWatch showed $0.00036, all of it usage type `CW:GMD-Metrics`: GetMetricData calls,
which the console makes when it draws a metric graph. The alarm (`AlarmMonitorUsage`) and the
custom metric (`MetricMonitorUsage`) cost $0. Andy (2026-10-16) chose to keep the alarm: the
charge item 4 guards against is the alarm's and the metric's, and both are inside the free tier.
A cost from viewing graphs stops when no one opens them.
