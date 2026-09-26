# 0097 — Jev is admitted as an ordering-check model, on development cases only

Amends [0009](0009-model-access-via-openrouter.md) (one transport) for this one role.

## Context

TypeSafe's Jev is a "System One" model: it answers typed questions (a Choice among up to 255
labels, with a probability per label) and writes no text. Its request shape is not chat
completions, so it cannot go through OpenRouter. A September experiment, kept on the
`typesafe-probe` branch and never merged (its record and results there:
`docs/results/typesafe-jev-dev400.md` at commit `0c5d24c`), asked it to diagnose `dev-400`
cases alone, from the evidence: composed top-1 9.7% [7.2%, 13.0%], below the no-model baseline,
and not calibrated (expected calibration error 0.318). It was declined for that role.

The ordering check (0096) asks a narrower question: of at most eight candidate codes, which
would the NTSB flag as defining, given the model's own narrative and the historical counts. That
is a single Choice, the shape Jev is built for, and a much easier task than diagnosis.

## Decision

1. Jev is one of the four ways of Round 1 (0096 item 4), on development cases only: one Choice
   over the candidate labels, the state being the same text GPT-6 Luna receives; the ranking is
   its returned probabilities.
2. A second transport is admitted for this role only. `TYPESAFE_API_KEY` and the base URL join
   `Settings`; the price joins `sources.py`, dated and marked self-reported. The client is
   ported from the `typesafe-probe` branch, and that branch's saved replies are the authority for
   the wire shape (rule 2). Every reply's resolved model version is recorded.
3. The Jev client refuses any call that is not the ordering check on a development run, and a
   test proves it refuses.
4. Jev is kept only by 0096 item 5's rule: it must beat the plain rule on both answer sets.
   Its probabilities are not used as a confidence anywhere.

## Why

1. **The question fits the model class**, and the September result was on a harder question.
2. **It costs a fraction of a cent** at its self-reported price, and the rule it must beat is
   free.
3. **Confining the transport to one declared role** keeps 0009's argument for the product: the
   evaluated agent and the deployed agent share one transport unless a record says otherwise.

## What this rules out

- **Jev anywhere else**, including as the agent, the judge, or on held-out or open cases.
- **Using Jev's confidence** as a stopping rule or a calibration claim; the September experiment
  found it not calibrated.
- **Depending on the vendor's SDK.** The wire shape is in the saved replies; `httpx` sends it.

## Status

Proposed, 2026-09-26: written with the S2.7 specification (Andy proposed Jev as one of the four
ways of the ordering check). Accepted when Andy approves the specification.
