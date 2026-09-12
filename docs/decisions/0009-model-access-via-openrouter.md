# 0009 — Model access for evaluation and live calls goes through OpenRouter

**Supersedes the "All model calls use Claude exclusively" rule** in both `CLAUDE.md`
files, and replaces the two-implementation model-client plan in decision 0002's spec
(`docs/specs/2026-09-12-architecture-and-roadmap.md` §4).

## Context

The spike ran every model call through the `claude` command-line tool on a personal
subscription, where the marginal cost is nil but calls cannot be scheduled. The plan for
this repository was therefore two transports: the subscription for local evaluation, the
Anthropic API for scheduled cloud jobs. Andy has an OpenRouter account and key.

## Decision

- **Claude Code is used for developing and maintaining this project.** Unchanged.
- **Every model call the product makes — evaluation runs and live scheduled calls alike
  — goes through OpenRouter** (`https://openrouter.ai/api/v1/chat/completions`, bearer
  token). One transport for both.
- The agent's model stays `anthropic/claude-sonnet-5` initially, so the spike's
  configuration remains the starting point. Model choice becomes a tunable parameter of
  the harness rather than a constant.

## Why

1. **One transport removes a risk the previous plan carried.** Subscription locally and
   API in the cloud meant the same code could behave differently in the two places the
   project claims are equivalent. A single transport makes "the evaluated agent is the
   deployed agent" true at the transport layer too.
2. **Model choice becomes measurable.** With 27 Anthropic models plus others reachable
   through one interface, accuracy against cost across models becomes an evaluation axis
   rather than an assumption. For a project whose subject is judging when capability is
   warranted, that is a useful thing to be able to show.
3. Andy already holds the key. The alternative required opening a second billing
   relationship for roughly £5 a month.

## What was checked before accepting it

The concern was that OpenRouter is an OpenAI-compatible layer, and that Sonnet 5 has
specific constraints the spike recorded: thinking depth is set by an effort control, and
`temperature` / `top_p` / `top_k` / `budget_tokens` are rejected. Sending the wrong shape
would change both cost and accuracy silently.

Queried from `https://openrouter.ai/api/v1/models` on 2026-09-12, `anthropic/claude-sonnet-5`
reports `supported_parameters` of `reasoning`, `reasoning_effort`, `response_format`,
`structured_outputs`, `tools`, `tool_choice`, `max_tokens`, `stop`, `verbosity`,
`include_reasoning` — and **not** `temperature`, `top_p` or `top_k`. By contrast
`anthropic/claude-haiku-4.5` reports `temperature`, `top_k` and `top_p` but no
`reasoning_effort`. The metadata tracks each model's real constraints rather than
flattening them, which is the evidence that the translation is faithful for this model.

**Still owed: one live probe.** Metadata is not a response. Before any measurement is
trusted, S1 makes one real call and confirms that effort control and structured output
behave as documented. Rule 2 — never guess API details — is satisfied by a saved real
response, not by a capability list.

## Consequences

- **The spike's £0.034 per case and 57% top-1 become historical reference points, not
  bars.** They were measured on a different transport. S1 was already re-measuring the
  ceiling because output is now code-constrained; the transport change rides along with
  it. The bar the agent must beat is whatever S1 measures on the stack that will actually
  run. Attribution between the two changes is not needed, because bar and agent are
  measured identically.
- **`config.yaml`'s price constants are wrong.** It records Sonnet 5 at $3/$15 per
  million tokens. OpenRouter lists `anthropic/claude-sonnet-5` at **$2/$10**, matching the
  current first-party rate; $3/$15 is Sonnet 4.6. Correct in S0.
- **Batch pricing is available and relevant.** `anthropic/claude-sonnet-5:batch` is
  $1/$5 per million tokens — half price. Evaluation runs are offline and have no latency
  requirement, so the harness should use the batch variant and the live path should not.
  This roughly halves the cost of every large evaluation.
- Cost per call is reported in the response `usage`, which is what the per-case cap and
  the trajectory log read.

## What this rules out

- **Anthropic API directly.** Keeps first-party parameter fidelity with no translation
  layer, and no third party between the project and the model. Rejected because it needs a
  second billing relationship and reintroduces the two-transport split.
- **Subscription CLI for evaluation.** Free, and it is what produced the spike's numbers.
  Rejected because it cannot be scheduled, so production would necessarily differ.

## Status

Accepted, 2026-09-12. Supersedes the exclusivity rule.
