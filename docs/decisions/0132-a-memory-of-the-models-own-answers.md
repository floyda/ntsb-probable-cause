# 0132 — A memory of the model's own answers, from drawn development batches, keyed like the table and refused when stale

## Context

The table of 0130 assumes the model's occurrence is right. A memory of the model's own answers —
"when the model's first occurrence was X, the NTSB flagged Y" — would learn the model's habits
instead, and could close part of the 5-point gap between the table and a table keyed on the
NTSB's true code (ad-hoc, `scripts/exploratory/s28_design_lookup_keys.py`).

The only model answers held are on `dev-400`. Learned from four fifths of them (320) and scored on
the rest, the memory reached 33.5% against the full table's 34.6%; against a table built from
the same number of pool cases it was level (32.4% against 31.7%, and 32.2% against 32.5% on a
second run; ad-hoc, `s28_design_memory.py`). The loss was size, not the idea. Keyed on the model's
findings instead, it reached 29.8%.

Dockets cost disk, not money: 401 cases took 5.2 GB (2026-09-28/29), leaving 23.2 GB free.

## Decision

1. **The memory sample**: three batches of development cases, each drawn by `samples.draw` as
   `dev-400` was (401 cases), with seeds 20260928, 20260929 and 20260930, each excluding
   `dev-400`, `dev-seal-400` and the earlier batches. Committed as
   `tests/fixtures/eval/dev_memory_<n>_ids.csv` by `scripts/draw_memory.py`, which must reproduce
   batch 1 as already fetched.
2. **Batch 1's dockets are fetched**; batches 2 and 3 wait until Andy frees disk space or names
   another disk. The memory uses the batches fetched when S2.8's registration is committed.
3. **Its answers**: arm B and the kept ordering check on each batch, with S2.7's final setup.
4. **Its content**: for each checked first occurrence code the model gave in the memory sample,
   the NTSB's flagged findings in those cases, with counts; shown as up to five lines beneath the
   table where at least 5 answers exist.
5. **Staleness**: a memory built on another model or reasoning level is refused; a difference in
   prompt version, guidance or check is printed with the result.
6. It runs only if the model step without it is kept (0133).

## Why

1. **Andy's choice**, over plain counts alone: "Let's go with E". A size-matched comparison
   showed the idea was not beaten, only under-fed.
2. **Keyed like the table** because the finding key did worse (29.8%), and a shared key lets the
   two sit side by side.
3. **Drawn like `dev-400`** so the memory's cases look like the cases it is applied to, and
   seeded so the build re-draws the list already fetched.
4. **Staleness is real**: every change to model, prompt or guidance makes a memory describe a
   model that no longer runs.

## What this rules out

- **A memory from `dev-400`'s own answers.** Free, but it would score the cases it learned from.
- **Plain counts only.** Simpler and never stale. Andy chose to test the memory now.
- **A memory keyed on the model's findings.** Weaker ad hoc.
- **All three batches regardless of disk.** About 10.4 GB more (estimate) would pass the fetch's
  15 GB free-space guard.

## Status

Proposed, 2026-09-29, with the S2.8 specification; accepted when Andy approves it. Andy chose the
memory ("Let's go with E", 2026-09-28) and the overnight fetch of batch 1 only ("Let's go with A
and then in the morning I will look at disk space").
