# 0203 — The steering slice, and statistics rebuilt without it

From Andy, 2026-10-14. Detail: `docs/specs/2026-10-08-coding-memory-design.md` §5 and §6.

## Context

1. **The memory is revised again and again.** Anything it is scored against often, it slowly
   learns. It needs a sample to be steered by that it never learns from.
2. **`dev-400` is the project's development yardstick**, and the sealed sample `dev-seal-s3-400`
   is kept for version 2 ([0141](0141-s32-five-runs-and-the-sealed-sample-kept-for-v2.md)).
   Neither should be read after every period.
3. **S3's statistics file counts every pool case** (`scoring/tables/coding_stats_s3.json`, 12,090
   cases, [0129](0129-s3s-sealed-sample-and-statistics.md)). A case scored with counts that include
   its own verdict is scored with its answer in hand.

## Decision

1. **The steering slice, `pool-steer-400`**, is drawn once by `samples.draw` (200 fatal and 200
   non-fatal, stratified by class, decision [0026](0026-slices-fixed-samples-and-heldout-ledger.md))
   from the development split, excluding `dev-400`, `dev-seal-400` and `dev-seal-s3-400`, with
   seed **20261014**. Its case list is committed beside the other samples.
2. **The learning part** is the S3 pool less the steering slice. The learner reads only it; every
   support count is taken over it.
3. **A new statistics file**, `coding_stats_mem`, is built from the learning part. The coding
   test's counts condition and every memory run use it. S3's file is never rewritten, because
   version 1's fingerprint covers it.
4. **The steering slice is read only by the coding test.**

## Why

1. **Learn, steer, measure, confirm.** The learning part teaches; the steering slice steers, as
   often as needed; `dev-400` measures at milestones; the sealed sample confirms once, in
   version 2. Each sample keeps one job.
2. **A slice from the pool costs nothing**: the pool's cases are already fetched and outside every
   existing sample.
3. **The same draw as every other sample** (the same function, a stated seed) makes it
   reproducible and comparable.

## What this rules out

- **Steering by `dev-400`.** No new sample. Rejected: `dev-400` would be learned by selection, and
  the project would lose its development yardstick.
- **Steering by the sealed sample.** Rejected: it opens once, for version 2 (0141).
- **Reusing S3's statistics.** Rejected: the steering slice's own verdicts are in them (context 3),
  and changing S3's file would stop S4's nights.

## Status

Accepted.
