# 0041 — Docket text enters through a case context built by one attach step, before the split

Settles how docket documents reach the model under 0016's layered guard and 0023's single
assembler. Written with the S2 specification (`docs/specs/2026-09-18-s2-docket-tool-design.md`
§6.1).

## Context

The guard's provenance layer checks that every value the model sees equals its declared path
in the record it was split from. Docket text is free text from a different source and has no
path in the API record. 0023 forbids a second payload assembler. So the text needs a path.

## Decision

1. The harness builds one **case context**: the raw API record plus a `docket` subtree
   holding the listing and each attached document's header, manifest entry and text.
2. One pure function, `attach_docket(raw, docket, documents=...)`, builds it. It is the only
   place document text enters a record and the only place it is changed (0044).
3. `split_record` reads new evidence roles from that subtree (0042). Layers 0 to 4 apply
   unchanged: the allow-list names the docket paths, the keys are fixed, no docket path is
   under a withheld subtree, every value is checked against the context, and the tripwire
   runs over every attached document.
4. The ingest raw store is untouched: the docket is cached separately under `data/docket/`,
   and the context exists only in memory during a run.

## Why

1. **No guard layer changes.** Every S2 measurement then runs through the code path the
   model sees.
2. **Exclusion sets keep working.** Arms and the masked condition stay expressed as role
   exclusions, and `--exclude` covers the docket like any field.
3. **One named slot for changes to document text.** The amateur-built replacement (0044)
   and any later name handling are pure functions inside the attach step, parallel to
   `redact_record`, and everything downstream is unaware of them.

## What this rules out

- **A second input to the splitter** (`split_record(raw, docket=...)`). Explicit types, but
  the provenance layer would need a second rule for values with no raw path, a new layer to
  test and mutate, and the signature would grow again for the weather tool in S3.
- **A docket tool rendering its own payload and calling the tripwire itself.** Already ruled
  out by 0023.
- **Attaching document text to the ingest raw store.** Would make the stored record no
  longer the API response verbatim (0014).

## Status

Accepted, 2026-09-18 (Andy).
