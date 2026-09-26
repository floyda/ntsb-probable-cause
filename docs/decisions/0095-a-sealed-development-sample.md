# 0095 — A sealed development sample, dev-seal-400, opened once

## Context

S2.7 runs several rounds, each read on `dev-400`, and Andy's hand-read of misses is also drawn
from `dev-400`. Guidance written from those cases and chosen by its score on them can fit them
rather than the NTSB's coding in general. Without a second check, the first sign of that would
be the held-out run, which is touched rarely (0026) and whose number is the one published.

## Decision

1. `dev-seal-400` is drawn by `samples.draw` exactly as `dev-400` was (200 fatal, 200 non-fatal,
   each split by class C, F, L in proportion; 0026), with seed 20260926 and every `dev-400`
   case excluded. Its list is committed as `tests/fixtures/eval/dev_seal_400_ids.csv`.
2. Nothing about it is scored, read, fetched or transcribed until `docs/rounds/s27-sealed.md`
   is committed, naming the final setup exactly. The runner, the docket fetch and
   `ntsb-eval transcribe` refuse it before then, and tests prove they refuse.
3. It is then used **once**: dockets fetched, transcribed only if v2 went forward, the final
   setup run once with the judge, and the result reported beside the same setup's `dev-400`
   result, with the drop printed.

## Why

1. **It is the one clean check that guidance generalises**, still on development cases.
2. **It frees `dev-400`** to be read and tuned on without that tuning going unmeasured.
3. **The held-out run stays a single confirmation**, as the project intends.

## What this rules out

- **Everything on `dev-400`, held-out as the only check.** Free, but over-fitting would be
  discovered at the held-out touch.
- **Halving `dev-400`.** 200 cases give intervals of roughly ±6 points, wider than a round's
  likely effect.
- **Opening the sealed sample more than once.** A second look turns it into a working sample.

## Status

Proposed, 2026-09-26: written with the S2.7 specification (Andy: "I think A", a sealed sample;
"I can probably swallow the extra transcription cost"). Accepted when Andy approves the
specification.
