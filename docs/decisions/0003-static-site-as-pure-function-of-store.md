# 0003 — The public site is a pure function of the store

## Context

The live board is the public surface: open cases, standing predictions, evidence
timelines, trajectories and methods. It could be served dynamically from a database, or
generated ahead of time as files.

## Decision

The site is generated. `apps/site` reads the store and the evaluation artefacts and emits
HTML and JSON into a folder, published to S3 behind CloudFront. Nothing is computed when a
visitor arrives: no server, no request-time database, no API.

## Why

1. Hosting cost does not move with traffic. The demonstration criteria require cost to be
   bounded and instrumented; this makes it a property of the architecture rather than a
   claim in a README.
2. The site build runs locally and produces the same files continuous integration
   publishes. A wrong page is reproducible.
3. It removes an entire class of production concern — request handling, scaling, database
   availability — that this workload does not actually have.

## What this rules out

- **A live API behind the board.** Looks more like conventional production infrastructure
  and would allow interactive queries. It costs falsifiability (a reader cannot diff the
  output), adds surface, and makes hosting cost traffic-dependent.

## Status

Accepted. See `docs/specs/2026-09-12-architecture-and-roadmap.md` §5.
