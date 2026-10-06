# 0141 — S3.2 makes five runs; the sealed sample stays sealed for v2

Amends [0129](0129-s3s-sealed-sample-and-statistics.md) items 2 and 3 and
[0127](0127-arms-ablations-and-the-ordering-check-in-arm-b.md) item 5, each with a dated note
appended. From the S3.2 design session (2026-10-03): the run list, option A cut to five. Detail:
[the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §3 and §16 (record 1).

## Context

- The S3 specification's outline (§11) planned about ten paid runs for S3.2: three ablations on
  `dev-400`, arms A, B and C again on `dev-400`, `dev-seal-s3-400` once, and held-out. Andy
  (spelling corrected): "I don't want to spend $13-15 on 10 runs though, maybe 6?" The session
  cut the list to five.
- **The loop was never tuned.** S3.1 closed with no registered round
  ([0139](0139-s31-tuning-closes-without-a-registered-round.md)). The sealed sample was meant as
  a second check, on fresh cases, for a loop tuned on `dev-400` (0129 Why 1). Held-out gives a
  fresh-case check without it.
- **The `dev-400` readings of the loop and arm B already exist** at the frozen loop's text. The
  loop: two noise-floor runs, `20261001T201506-fd6053f-dev-400-C` and
  `20261001T201648-fd6053f-dev-400-C`. Arm B: S3's full arm B,
  `20260929T053953-674c92e-dev-400-B-tools-check-luna`, whose tool post-pass carries the same
  `+p947fac1c86a4` as the loop's prompt version. They answer every question the outline asked
  of a re-run.
- 0126 and 0130 planned the calibration fit on the loop's own `dev-400` runs. The noise-floor
  runs are those runs.

## Decision

1. **Five runs.**

   | # | run | cases |
   |---|---|---|
   | 1 | the loop without its coding tools (`run --arm C --without coding`) | `dev-400` |
   | 2 | arm A, start facts only | `heldout-400` |
   | 3 | arm B, in three commands: the answer run, `ntsb-eval tools`, then `ntsb-eval check --way luna --stats s3`; each writes a held-out ledger row | `heldout-400` |
   | 4 | the loop (arm C) | `heldout-400` |
   | 5 | the loop without the docket (the docket roles excluded) | `heldout-400` |

   Held-out therefore carries six commands and six new ledger rows.
2. **Reused, not re-run:** the two noise-floor runs and S3's full arm B on `dev-400` (Context).
   The coding ablation is read against the two noise-floor runs. The calibration curve is
   fitted on the noise-floor runs ([0147](0147-calibration-and-abstain.md)). 0127 item 1's
   re-run of arm A on `dev-400` is not made: arm A runs on held-out only.
3. **`dev-seal-s3-400` stays sealed and is kept for v2's development test**
   ([0140](0140-the-precedent-tool-after-s4-as-a-measured-v2.md) item 3). Its lock moves: it is
   unlocked by `docs/rounds/s3-sealed.md`, written only when the sample is used, no longer by
   `docs/rounds/s3-registration.md`. This amends 0129 items 2 and 3 (and the row for S3.2 in
   [0128](0128-s3-in-three-sub-stages-with-one-spend-line.md) item 1, which named the sample).
4. **The ablations of 0127 item 5 change.** The no-docket ablation runs on held-out only. The
   `suggest_codes` ablation is not run. The no-coding ablation stays on `dev-400`.
5. **Estimate:** about $6.50 billed for the five (the specification's §3). S3.2's share of the
   spend line is set in [0150](0150-s32s-share-of-the-spend-line.md).

## Why

1. **Cost and speed were Andy's stated limit.** Five runs are half the outline's number of runs.
2. **Each run kept answers a question the claims need.** Held-out arms A, B and C give the
   headline test. The no-docket run is CLAUDE.md goal 2's ablation: "an ablation with the
   docket tool removed must show a real loss". The coding ablation tests where the agency is
   meant to sit.
3. **The reused runs are like for like.** They carry the frozen loop's label, so a held-out
   result and its `dev-400` reading differ only by the cases.
4. **An unopened sealed sample is worth more later.** A sample is useful only if used once
   (0095, 0129 Why 1). v2 will be a changed agent, built and read on `dev-400` first, and will need a development
   check on cases it has not seen (0140 item 3).

## What this rules out

- **The outline's ten runs.** The strongest case for them: every arm on `dev-400` and on the
  sealed sample would give a second and third reading beside held-out. Rejected for cost, with
  Andy's words above.
- **Using the sealed sample now.** It would give S3.2 a check if held-out surprises. Given up
  on purpose: if held-out surprises, S3.2 cannot tell whether held-out is unusual or `dev-400`
  was. Rejected because the loop was not tuned, and v2 needs the sample more.
- **Dropping the coding ablation.** It costs about $1.20 and tests
  the loop's chosen place for agency (0121 item 1). Rejected: without it, the claim would say
  nothing on whether the coding step earns its place.
- **Dropping the no-docket ablation.** It is goal 2's own requirement. Rejected.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Ablation**: the loop with one part removed, to measure what that part adds.
- **Held-out ledger**: `docs/results/heldout-ledger.md`; one row per held-out run, committed
  before the next held-out command (0026).
- **Noise-floor runs**: two identical runs of the loop on `dev-400`, made to measure how much a
  result moves by chance (0130).
- **Sealed sample**: cases set aside, unread and unscored, until one final check (0095, 0129).
- **v1, v2**: the loop as frozen at `fd6053f`; the loop with the precedent tool, built after S4
  (0140).
