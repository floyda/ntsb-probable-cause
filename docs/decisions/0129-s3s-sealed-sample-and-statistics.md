# 0129 — S3's sealed sample and statistics file; the guidance files stay unchanged

From the S3 design session (2026-09-29 to 2026-09-30): sealed choice A, and guidance-files
choice A. Detail: [the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §12 and
§20.

## Context

- `dev-seal-400` was opened once, on 2026-09-29, for S2.7
  ([0095](0095-a-sealed-development-sample.md)). A second look would make it a working sample.
  S3.2 needs a sample on which the loop was never tuned.
- The coding tools, arm B's tool post-pass and its ordering check read counts from the
  statistics pool ([0094](0094-coding-statistics-from-a-pool-outside-the-samples.md)): every
  development case in classes C, F and L outside `dev-400` and `dev-seal-400`, about 12,490
  cases (ad-hoc in 0094, re-derived by the script). A new sample drawn from the pool would
  otherwise have its own verdicts in the counts.
- S2.7's two kept guidance files (`r3-loc-stall`, `r6-aircraft-control`) cite counts from
  S2.7's pool, which includes the cases the new sample will be drawn from.

## Decision

1. **A new sealed sample, `dev-seal-s3-400`.** It is drawn by `samples.draw` exactly as
   `dev-seal-400` was (200 fatal and 200 non-fatal asked for, each split by class C, F and L in
   proportion; 0026), with seed 20260930, excluding every `dev-400` and `dev-seal-400` case.
   Each class's share is rounded on its own, so the draw gave 401 cases: 200 fatal and 201
   non-fatal (the committed list, `tests/fixtures/eval/dev_seal_s3_400_ids.csv`, and the S3.1
   plan's Task 5 Deviations). Its list is committed as a test fixture.
2. **It is refused until registered.** Nothing about it is scored, read, fetched or transcribed
   until S3.2's registration file (`docs/rounds/s3-registration.md`) is committed. The runner,
   the docket fetch and every other command refuse it before then, and tests prove they refuse.
3. **It is used once, in S3.2**: arm C and arm B, reported beside the same setups' `dev-400`
   results.
4. **S3's statistics file.** The same script builds a new counts-only file,
   `docs/results/s3-coding-stats.txt`, from the pool without the new sample. The script refuses
   the new sample, `dev-400`, `dev-seal-400`, held-out and open cases, and a test proves it.
   Both arms in S3 read this file: the loop's tools, arm B's tool post-pass and its ordering
   check.
5. **S2.7's statistics file stays as it is**, so S2.7's numbers stay citable. The pool shrinks
   by about 400 cases.
6. **The two guidance files stay unchanged.** S3.2's registration file discloses that their
   counts come from a pool that includes the new sample's cases.

## Why

1. **A sealed sample is worth something only if it is used once** (0095). S3's own sample gives
   S3.2 a check, besides held-out, on cases the loop was never tuned on.
2. **Counts must not include the verdicts they are tested on**: 0094's contamination rule,
   applied to the new sample.
3. **The guidance text cannot have been fitted to the new sample.** It was fixed before the
   sample existed, and 400 of about 12,490 cases carry little weight in a count. Keeping the
   files keeps arm B's guidance text as S2.7's measured setup had it. It does not keep arm B as
   S2.7 measured it: decision 4 makes arm B's tool post-pass and its ordering check read S3's
   statistics, and S3.2 runs arm B again in any case (spec §11). Andy (2026-09-30): "Go with A
   and keep them unchanged".

## What this rules out

- **Re-using `dev-seal-400`.** No new draw. Rejected: it has been opened once, and a second look
  makes it a working sample.
- **No sealed sample for S3.** Less work. Rejected: S3.2's claims would rest on `dev-400`, where
  the loop is tuned, and on held-out alone.
- **Keeping S2.7's statistics for S3.** No rebuild. Rejected by Why 2.
- **Rewriting the guidance files' counts from the smaller pool.** The counts would then agree
  with S3's file. Rejected: it would change arm B's guidance text away from S2.7's final setup
  (Andy's choice, Why 3). It would not have spared a new measurement of arm B: decision 4
  already changes the statistics arm B's post-pass and ordering check read, and S3.2 runs arm B
  again anyway (spec §11).

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).

**Amended 2026-10-03 by [0141](0141-s32-five-runs-and-the-sealed-sample-kept-for-v2.md)
(appended; nothing above is edited).** Items 2 and 3: the sample stays sealed in S3.2 and is kept
for v2's development test ([0140](0140-the-precedent-tool-after-s4-as-a-measured-v2.md) item 3).
Its unlock moves from `docs/rounds/s3-registration.md` to `docs/rounds/s3-sealed.md`, written only
when the sample is used. Items 1 and 4 to 6 stand.
