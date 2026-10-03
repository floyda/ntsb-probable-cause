# 0144 — One cost cap of $0.30 a case for every arm and part

From the S3.2 design session (2026-10-03): the cap, option A. Applies
[0022](0022-loop-must-beat-call-every-tool-arm.md) item 1. Detail:
[the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §5.

## Context

- 0022 item 1 requires the same per-case cap for every arm. Today arms A and B use $0.05
  (`RunSpec.cap_usd`) and arm C $0.15 (`agent/run.py:CAP_USD`). Neither cap was reached on
  `dev-400`.
- **A known issue sits in a fingerprinted file.** The room held at a read choice does not count
  the documents about to be read (`agent/loop.py`;
  [0142](0142-frozen-means-an-unchanged-prompt-version.md) item 6). The cap still holds, but a
  case may stop at the cap before it answers.
- On `dev-400` the dearest loop case cost $0.089 and $0.1055 computed in the two noise-floor
  runs (ad-hoc, counted in the design session). Held-out fatal dockets may be larger.
- The cap is checked against the computed price, which errs high
  ([0135](0135-s3-spend-counts-what-was-billed.md) item 4).

## Decision

1. **Every S3.2 run uses `--cap-usd 0.30` a case**: arm A, each part of arm B, the loop and both
   ablations. Every S3.2 `make` target passes the value.
2. **The defaults in code stay as they are** (`RunSpec.cap_usd = 0.05`, `agent/run.py:CAP_USD =
   0.15`), so the records of earlier runs stay true.
3. **The check.** A committed script (`scripts/s32_cap_check.py`, with its results file
   `docs/results/s32-cap-check-dev.txt`) counts, in the noise-floor trails, any case whose
   coding was cut short because the room left for the answer ran short, at $0.15. If there is
   one, raising the cap would change what such a case does, and this choice goes back to Andy
   before any S3.2 run.

## Why

1. **It guards the `loop.py` issue without editing `loop.py`.** At $0.30 the issue practically
   cannot arise: the dearest `dev-400` case cost about a third of it.
2. **For arm B a higher cap can only help it.** It can let arm B read more of a very large
   docket, never less. That makes the bar stronger, which is the safe side for the loop's test.
3. **Money stays bounded.** Each run still reserves its expected cost, and the run budget and the
   monthly guard still stop it ([0150](0150-s32s-share-of-the-spend-line.md)).
4. **Equal caps keep 0022 item 1.** Every arm has the same one.

## What this rules out

- **$0.15 for every arm.** The strongest case: it is the loop's own cap and the one the noise
  floor ran under, so nothing changes for the loop. Rejected: it leaves the `loop.py` issue
  within reach on large fatal dockets, and the issue cannot be fixed without changing the label.
- **$0.05 for arms A and B and $0.15 for the loop.** The caps as they are in code. Rejected: it
  breaks 0022 item 1, which requires the same cap for every arm.
- **Raising the cap only for the loop.** Rejected for the same reason.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Computed price**: every token priced at the list rate, ignoring the cache discount.
- **Per-case cap**: the most one case may cost; a case that reaches it stops (0030).
- **Room**: the budget a case keeps for its answer when it chooses its next step.
