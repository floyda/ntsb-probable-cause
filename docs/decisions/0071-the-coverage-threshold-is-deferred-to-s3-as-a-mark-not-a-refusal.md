# 0071 — The leakage guard's coverage threshold is deferred to the start of S3, reframed as a mark rather than a refusal

## Context

S2's close-out measured the gap decision 0050 leaves: the tripwire skips factual-narrative
sentences inside docket documents, so only an exact whole-text copy of the narrative stops a
case, and a near-complete copy passes. `scripts/narrative_coverage.py` found two of 379
development cases with a single document carrying more than 90% of the narrative's sentences
and no held-out case above 74.6%. The close-out recommended a coverage threshold near 80%
and named it "the first item for S2.5", as Andy's decision.

## Decision

No threshold is set in S2.5. The question moves to the start of S3, reframed by Andy: cases
where a document carries a large share of the factual narrative are **marked, not refused**,
and the marked group is scored against the rest to see whether the difference is noticeable.

## Why

1. **The narrative quotes its sources.** 0050 already found that the factual narrative is
   written from the docket. A medical report copied into the narrative is the narrative
   reproducing evidence, not evidence reproducing the verdict. Refusing such cases could
   discard exactly the cases where the docket is richest.
2. **Marking measures what refusing would assume.** If the marked cases score much higher, the
   mark is doing the work; if they do not, the gap was not a gap.
3. **It is not a recorder decision.** It changes the guard and how the agent is scored, which
   is S3's ground. Calling it "small" was wrong.

## What this rules out

- **An 80% refusal threshold now.** Recorded as the close-out's recommendation; not taken.
- **Leaving the gap unexamined.** The measurement stands, and S3 opens with the question.

## Status

Accepted, 2026-09-22. Defers the item S2's As-built raised.
