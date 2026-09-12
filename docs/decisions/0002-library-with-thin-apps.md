# 0002 — Library with thin application entrypoints

## Context

The same code has to run in three places: an evaluation harness on a laptop with large
local data, scheduled unattended jobs in the cloud, and a site build in continuous
integration. The obvious structure is to organise around those three targets.

## Decision

Organise by responsibility, not by where code runs. `src/ntsb_pc/` holds the library —
data, codes, tools, agent, scoring, store — with no command-line entrypoints, no cloud
dependencies and no printing. `apps/` holds one thin module per entrypoint containing
argument parsing and wiring only.

If logic appears in an app, it moves to the library.

## Why

1. The three contexts are three entrypoints over one library, not three systems. All of
   them call the same agent.
2. The library is the part that runs identically everywhere, so it is the part a test can
   meaningfully cover. Logic that lives only in an app is, by construction, untested in
   the other two contexts.
3. It keeps the units small enough to reason about one at a time.

## What this rules out

- **Organising by deployment target** (`local/`, `cloud/`, `ci/`). Reads naturally at
  first and puts related files together, but guarantees the same logic is written more
  than once and then diverges.

## Status

Accepted. See `docs/specs/2026-09-12-architecture-and-roadmap.md` §3.
