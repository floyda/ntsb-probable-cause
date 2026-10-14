# 0202 — The Claude API is a second transport for learning calls, paid from plan credits

From Andy, 2026-10-14. Amends [0009](0009-model-access-via-openrouter.md) (one transport) for
this one role, as [0097](0097-jev-as-an-ordering-check-model-on-development-cases.md) did for Jev.
Detail: `docs/specs/2026-10-08-coding-memory-design.md` §8.

## Context

1. **Andy's Claude plan includes a monthly Claude API credit** of $100, claimed; it expires at the
   end of each billing cycle and does not roll over (external: Anthropic's page "API credits for
   Max and Team plans", read 2026-10-08). It cannot be spent through OpenRouter.
2. **Learning calls are small**: a batch of cause sentences and codes plus the memory. Answering
   calls carry the docket. At Anthropic's published batch prices (read 2026-10-08) an arm B run on
   `dev-400` would cost about $49 on Sonnet 5.5 against $2.43 measured on GPT-6 Luna (an
   estimate, scaling the measured cost by the price ratio).
3. **Two learning jobs differ in difficulty and volume.** Proposing and revising lessons needs
   judgement and runs a few dozen times a period; deciding which lessons apply to a case is a
   yes or no and runs once per case.

## Decision

1. **The Claude API is admitted for learning calls only**: propose, apply and revise, on
   learning-part cases ([0200](0200-a-model-may-read-development-verdicts-to-learn-coding-lessons.md)).
   Its client refuses any other call and any case outside the learning part, and a test proves
   each refusal.
2. **Models and effort** (Andy, 2026-10-14): Sonnet 5.5 proposes and revises, at effort
   `high`; Haiku 5.5 decides which lessons apply, at effort `low`, once it passes the agreement
   check of [0204](0204-the-coding-test-and-the-pilots-stop-rule.md) (which may move it to
   `medium`, or hand applying to Sonnet). Thinking stays on, as these models require; effort is
   the control. Every call states its effort, never relying on a model's default, and every
   spend row records it. One effort per job, so the cached memory prefix is reused. Opus 5.5 is
   not used in the pilot.
3. **Answering and the coding test stay on GPT-6 Luna through OpenRouter**, on the development
   key, under its $40 monthly guard ([0083](0083-the-monthly-budget-is-forty-dollars-in-development.md)).
   S4's live key is never used.
4. **The key** is read inside a script from `pass` and never printed or committed; prices join
   `sources.py`, dated, with their source page.
5. **Wire shapes come from Anthropic's documentation and the saved replies of a shape probe**
   (rule 2), run first, at a cost of cents. The Message Batches API is used wherever a call need
   not be answered at once.
6. **Spend** is written as its own kind of spend row, with its transport, at its real price, never
   as zero. It is fenced by a monthly line in the budget guard no larger than the month's credit,
   and by a spend limit on its own Claude Console workspace.

## Why

1. **It turns an expiring credit into the experiment's learning budget**, where calls are small
   enough for Claude's prices (context 2).
2. **The memory is measured on the model that uses it.** Only the learner is on the new
   transport; the coding test and every answer stay on the product's model and transport, so
   0009's argument holds where it matters.
3. **Each job gets the cheapest model that can do it**, and the agreement check proves the cheap
   one before its answers count.

## What this rules out

- **Learning through OpenRouter.** One transport. Rejected: the credit cannot be spent there, and
  the project's monthly line would carry the cost.
- **Scripted Claude Code (`claude -p`) under the subscription.** No new key. Rejected: the credit
  does not cover Claude Code, usage limits are not published in tokens, and the calls would carry
  Claude Code's own system prompt.
- **Answering on Claude.** Rejected for cost (context 2) and because the bar and the agent are
  compared on one model (0022, 0031).

## Status

Accepted.
