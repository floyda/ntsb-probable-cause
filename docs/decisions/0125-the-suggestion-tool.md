# 0125 — The suggestion tool: the pool's five commonest defining events for a phase group, called by choice

From the S3 design session (2026-09-29 to 2026-09-30): candidates choice C. Detail:
[the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §5.1, and §2 lesson 1.

## Context

In the learning probe, the agent checked only codes it already held. The true primary
occurrence code was among the codes it passed to a tool on 9 of 20 and 11 of 20 cases
(scripted, `docs/results/s3-probe-dev.txt`, `docs/results/s3-probe-dev-run2.txt`). Adding the
statistics pool's five commonest defining events for the case's phase-of-flight group would have
put it in reach on 13 and 14 of 20 (exploratory, `scripts/exploratory/s3_probe_candidates.py`).
Reach is an upper bound: the true code was among the codes looked at, not the code chosen.

## Decision

1. The loop has a coding tool, **`suggest_codes(phase_group)`**. It returns the pool's five
   commonest defining events for a phase-of-flight group, with counts. It reads S3's statistics
   file ([0129](0129-s3s-sealed-sample-and-statistics.md)) and returns codes, labels and counts
   only, never case text.
2. **It is a separate tool that the agent chooses to call**, not a list added to every check.
   The agent decides whether and when to call it. Each call is logged in the trail.
3. **Arm B calls it once**, for the phase group of its first code, after the other coding tools
   ([0127](0127-arms-ablations-and-the-ordering-check-in-arm-b.md)).
4. **Removing it is an ablation** on `dev-400` (0127). If the agent never calls it, that is a
   finding, and it is reported.

## Why

1. **The agent cannot check a code it never names.** In the probe, the true code was missing
   from the agent's checks on about half the cases. The pool's commonest events for the phase
   group would have reached it more often (an upper bound, on both runs).
2. **A choice can be measured; an automatic list cannot.** The trail shows whether and when the
   agent asks, and the ablation shows what asking adds.
3. **Counts from the pool carry no case text**, so the tool adds nothing that the leakage guard
   has to check (0094).

## What this rules out

- **Adding the pool's suggestions to every coding tool's result.** The agent would always see
  them. Rejected: their use could not be seen in the trail, and removing them would change every
  tool's output, not one tool.
- **No suggestions.** The simplest loop. Rejected by the probe's reach figures (Context): an
  upper bound, but it points the same way on both runs.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
