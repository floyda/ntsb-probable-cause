# 0031 — The default model is GPT-5.6 Luna; the model axis is measured after S3

## Context

The roadmap starts the agent's model at `anthropic/claude-sonnet-5` for continuity with the
spike, says model choice is a harness parameter rather than a constant, and names accuracy
against cost across models as an evaluation axis without assigning it to a stage. The
spike's numbers are already history (0006, 0013), so continuity of model buys nothing: the
ceiling is re-measured from scratch. Andy's limit is $25 a month (0030). OpenRouter's public
model list on 2026-09-15 prices `openai/gpt-5.6-luna` batch at $0.10 per million input
tokens and $0.60 per million output tokens, against $1.00 and $5.00 for Sonnet 5 batch;
both advertise a JSON schema on the reply and tool calls.

## Decision

1. The default model for evaluation and, later, the live board is `openai/gpt-5.6-luna`,
   batch variant for evaluation. The probe tries `luna` and `luna-pro` on ten development
   cases and the S1 plan records which is used and why.
2. The bar is measured on one model, and the agent is compared with the bar on the same
   model (0022). A table across models is separate, labelled by model, and never mixed into
   the bar.
3. S1 runs one comparison, Sonnet 5 against Luna, ceiling only, on `dev-400`, as a sanity
   check. It is reported and changes nothing unless the gap is large, in which case Andy
   decides before any held-out run.
4. The model axis proper — which model gains most from reading the docket — needs arms B
   and C and is placed after S3. The roadmap's S3 entry says so.

## Why

1. **Ten times cheaper, same capabilities.** All of S1 fits in one month's budget with room
   for re-runs; on Sonnet 5 it would take two months and a smaller sample.
2. **The claim does not depend on the model being strong.** "The agent beats a single call
   of the same model" holds for any model, and a weaker model has more to gain from the
   docket, which is measured.
3. **A sanity check on development cases costs about $5** and catches a model that fails the
   format rather than the task.

## What this rules out

- **Sonnet 5 as the default.** Continuity with a number that is already history is not worth
  ten times the cost.
- **Switching models between the bar and the agent.** Would let the agent "win" by model
  choice.
- **The model axis in S1.** One-call accuracy across models is not the interesting question;
  gain from agency is, and it needs S3.

## Status

Accepted.
