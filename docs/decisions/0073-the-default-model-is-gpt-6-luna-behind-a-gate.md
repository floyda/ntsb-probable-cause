# 0073 — The default model is GPT-6 Luna, behind a gate, at a recorded reasoning level

Replaces item 1 of [0031](0031-default-model-gpt-luna-model-axis-after-s3.md). Items 2 to 4 of
0031 stand.

## Context

0031 made `openai/gpt-5.6-luna` the default model, batch for evaluation, for its price. On
2026-09-22 OpenRouter listed `openai/gpt-6-luna` at about half that price — batch $0.05 / $0.25
per million tokens against $0.10 / $0.60 — with the same structured outputs, tool calls and batch
variant. Most of the project's model spending is ahead of it, in S2.6 and in S3's loop.

0031 item 2 requires the bar and the agent to share one model, so a switch re-measures the bars.
Doing it before S2.6 measures its bar avoids re-measuring that bar a second time.

Both models reason by default at a provider-chosen level, listed as `medium`. The code has never
set the level, and no run records it.

## Decision

1. A one-case **shape probe** first: both stages of the exchange, standard and batch. A rejected
   shape or empty content stops the stage.
2. A **gate** on `dev-400`: the ceiling with GPT-6 Luna fails the reply format on at most 1% of
   cases (4 of 401), each failure listed. The score is recorded, not gated, unless its paired
   interval against GPT-5.6 Luna lies wholly below zero, when Andy decides.
3. If both pass, the default model becomes `openai/gpt-6-luna`, named by one constant.
4. The **reasoning level** is set to `medium` on every request and recorded in every run's spec.
   Comparing levels is part of the model axis after S3.
5. The ceiling and arm B run once each on `heldout-400` with GPT-6 Luna and S2's guard, and are
   entered in the held-out ledger. Arm B on GPT-6 Luna is the bar until S2.6 replaces it. The
   GPT-5.6 Luna results stay in the record as history.
6. If the probe or the gate fails, the default stays GPT-5.6 Luna and held-out is not touched.

Detail: `docs/specs/2026-09-23-s24-model-switch-design.md`.

## Why

1. **Half the price for the same capabilities**, before most of the spending.
2. **One change per stage.** The evidence and the guard are untouched, so the held-out comparison
   isolates the model.
3. **The gate is on our task, not on reputation.** The model was a day old when chosen.
4. **An unrecorded setting is a silent variable.** Pinning the level makes a provider's change of
   default visible rather than a drift in results.

## What this rules out

- **Switching inside S2.6.** Two changes in one held-out comparison.
- **Switching after S2.6.** S2.6's bar would be re-measured a second time.
- **"No worse than GPT-5.6" as the gate.** GPT-5.6 failed 0 of 401 on development, so one stray
  reply would decide the stage.
- **Choosing a new reasoning level now.** Would change two things at once; deferred to the model
  axis (Andy: "make sure it is looked at when we look closer at the model").

## Status

Accepted, 2026-09-23 (Andy), conditional on the probe and the gate (items 1 and 2).
