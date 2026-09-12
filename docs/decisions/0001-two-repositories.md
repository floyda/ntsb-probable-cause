# 0001 — Two repositories: frozen spike, one build repo

## Context

The spike is complete and its decision (build) is signed off. Its value is its record:
an assumptions register, a report, labelling sheets, and a script behind every number.
The build needs tests, a scheduler, storage and a user interface that the spike layout
has no place for. Build brief §7 recommended a new repository but left it open.

## Decision

Two repositories, no more. `ntsb-spike` is frozen and receives no new work. Everything
built from here lives in `ntsb-probable-cause`: library, entrypoints, infrastructure and
site generator together.

## Why

1. The project's central claim is that the agent measured on the held-out set is the
   agent running live. If the deployed code lives in a different repository from the
   evaluated code, the two can drift and a reader has no way to check. They would have to
   take the claim on trust, which is what this project exists to avoid.
2. One repository lets every prediction row carry the commit identifier that produced it.
   A reader can check out that commit and re-run the case. The property is structural
   rather than a matter of discipline.
3. The spike's numbers stay citable only if its history stops moving.

## What this rules out

- **Publishing the agent as a package consumed by a separate deployment repository.** This
  is how a team with several consumers would do it, and it gives a cleaner boundary. Here
  it introduces version skew between the measured artefact and the deployed one — the
  exact failure the demonstration cannot afford.
- **Folding the spike into the build repository.** One history and one link to share, but
  it mixes one-off measurement scripts with product code and weakens the claim that the
  spike's record is frozen.

## Status

Accepted. See `docs/specs/2026-09-12-architecture-and-roadmap.md` §2.
