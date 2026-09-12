# 0006 — Code-constrained output with a graded lay explanation

## Context

In the spike the model wrote free-text answers which Andy scored by hand. When a small
model was tried as a stand-in judge it agreed with him on only 62.5% of the same 40
answers, and its errors were one-sided: it rejected 14 of the 23 answers he had marked
correct (build brief §5). Separately, the demonstration criteria require a non-expert to
understand the output without leaving the page.

## Decision

The model picks occurrence and finding codes from a supplied list with their meanings,
rather than writing labels. The answer carries seven fields: occurrence code, finding
codes, probable cause, lay explanation, confidence, abstain flag, and the evidence it
rests on. The lay explanation is graded, not published unchecked.

## Why

1. Exact-match scoring needs no judge and no human, so the regression check that gates
   every change can run automatically. The 62.5% agreement figure is the concrete reason:
   a judge that unreliable cannot gate anything.
2. The presentation requirement propagates backwards into the schema. If the page must
   explain, the model must produce the explanation — and free text going public without a
   quality measure behind it is the kind of shortcut this project exists to avoid.

## Consequence to plan for

The 57% one-shot ceiling was measured on free text scored by a human. A model choosing
from 58 occurrence codes is doing a measurably different task, so 57% is **not** a
like-for-like bar. It must be re-measured under this schema on the same 40 cases before
the agent can claim to have beaten anything. Scheduled into stage S1.

## What this rules out

- **Free text scored by an LLM judge as the headline metric.** Cheaper to build and more
  forgiving of phrasing. Rejected on the measured calibration above; it survives only as a
  third scoring layer, checked against the deterministic ones.
- **Deriving the lay explanation mechanically from the code tables.** Nothing to grade and
  no risk of invention, but the text would be generic and would not reference the evidence
  in the case at hand.

## Status

Accepted. See `docs/specs/2026-09-12-architecture-and-roadmap.md` §7.
