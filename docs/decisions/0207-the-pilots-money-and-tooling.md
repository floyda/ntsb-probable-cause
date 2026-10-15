# 0207 — The pilot's money and tooling

From Andy, 2026-10-15. Detail: `docs/specs/2026-10-08-coding-memory-design.md` §6 to §8.

## Context

1. **The learner is the project's second transport.** [0202](0202-the-claude-api-for-learning-calls-paid-from-plan-credits.md)
   admits the Claude API for learning calls, paid from Andy's plan credits.
2. **Rule 2 says wire shapes come from the provider's documentation.** The official `anthropic`
   Python SDK is that documentation's interface.
3. **[0097](0097-jev-as-an-ordering-check-model-on-development-cases.md) chose plain HTTP** for a vendor
   whose SDK was not needed. That reasoning does not carry to this transport.
4. **Two kinds of spend need two lines.** Learner calls are paid from credits that are not the
   project's money. The coding test is paid through OpenRouter, like every other run.
5. **A refused call needs a stated rule.** Anthropic's model-migration guidance, as bundled with the
   claude-api skill (read 2026-10-15), advises opting in to `fallbacks: "default"` by default. On
   Sonnet 5.5 that retries only `cyber` and `frontier_llm` declines, on Sonnet 5 without Sonnet
   5.5's thinking. Haiku 5.5 has no server-side fallback. The learner's prompts never ask the model
   to write out its reasoning, which invites `reasoning_extraction` declines.

## Decision

1. **The SDK.** The official `anthropic` Python SDK is a runtime dependency. Among `src/`, `apps/`
   and `scripts/`, only `memory/claude.py` imports it; a grimp test proves it. Scripts get a client
   through `memory.claude.sdk_from_key`.
2. **Learner spend.** Rows are kind `learning`. They count against a separate monthly line,
   `NTSB_LEARNING_MONTHLY_BUDGET_USD`, default $90: under the $100 credit, with a margin for the
   gap between a reply and its billing. It is checked under the budget lock before each job. The
   $40 OpenRouter guard never counts them. The Console workspace's spend limit is the hard stop.
3. **Coding-test spend.** Rows are kind `coding-test`. They are counted by the $40 guard and by a
   side-track line of $10, `scripts.stage_spend --stage mem`, counted by commit on branches named
   `coding-memory*` that hold the branch's first commit `938bd83`.
4. **No refusal fallback.** Learner calls send none, so every lesson keeps the model that wrote it.
   A refused call is a failed call, recorded with its `stop_details` category. The pilot's reading
   counts refusals by category. The wire names are confirmed against the shape probe's saved
   replies before use (rule 2).

## Why

1. **The SDK is the documented interface** (context 2), and less wire detail is written by hand.
2. **A separate line keeps credit spend apart from the project's money.** The hard stop sits at the
   provider, where the money is.
3. **The side-track line bounds the coding test alone**, as S3.3's line bounded the live runs
   ([0163](0163-the-live-shadows-caps.md)).
4. **A fallback would mix models inside one memory.** Without it, a lesson's author is always the
   model that was asked, and a refusal is counted, not hidden.

## What this rules out

- **Plain HTTP.** Rejected: more wire detail to get right by hand.
- **Counting credit spend against the $40 line.** Rejected: it would crowd out S4 development runs
  for money that is not the project's.
- **Server-side refusal fallback on learner calls.** Rejected: see Why 4.

## Status

Accepted; amends 0097's precedent for this transport only, and adds to 0202 item 6 and to
[0083](0083-the-monthly-budget-is-forty-dollars-in-development.md)'s guard. Approved by Andy, 2026-10-15.
