# 0014 — The processed file holds index columns and the raw record

## Context

Ingestion writes a local processed file that evaluation reads. The spike flattened every
record with `pd.json_normalize` into an 85-column frame with evidence and answer columns
side by side, and its payload assembler selected columns. Live records (S2.5 onward) arrive
from the API as nested JSON, one at a time. Detail:
`docs/specs/2026-09-13-s0-foundation-design.md` §6.2.

## Decision

`data/processed/cases.parquet` holds one row per case: a small set of index columns
(`ntsb_number`, `mkey`, `event_date`, `split`, `completion_status`, `investigation_class`,
`report_flavour`, `aircraft_count`, `docket_url`) and `raw_json`, the record exactly as
fetched. `split_record(raw)` runs on that record whenever it is loaded.

## Why

1. **Evaluation and live take the same route.** Both start from a raw record and call the
   same `split_record()`. Any other shape needs a second route for live records, which is
   the drift between evaluated and deployed agent that the project exists to rule out.
2. **The leakage path check sees real source paths.** It can tell that an evidence role
   reads from `narratives[0].analysisNarrative`. On a flat frame it would see only column
   names.
3. **The guard runs every time a payload is built**, not once when the file is written.
4. **Ablations and role changes need no rebuild.**

## What this rules out

- **Two physical files, `evidence.parquet` and `answers.parquet`.** The separation is
  visible on disk and model code cannot open answers by accident. Rejected because the
  guard would run only at build time and live records would still need an in-memory split:
  two routes to Evidence.
- **A flat frame, as in the spike.** Direct port, easy exploration in pandas. Rejected for
  the same two-route problem, the weaker path check, and parquet's list-to-array round trip
  that the spike's `build_evidence()` had to work around.

**What it costs:** ad-hoc statistics need a JSON parse per row, and withheld text sits in
the same file as evidence. The rule it relies on — separation in one function with an
assertion — is the rule `CLAUDE.md` states.

## Status

Accepted, 2026-09-13.
