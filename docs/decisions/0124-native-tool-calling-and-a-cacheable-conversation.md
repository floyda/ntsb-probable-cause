# 0124 — Native tool calling, with a stable tool set, `tool_choice` per step and an append-only conversation

From the S3 design session (2026-09-29 to 2026-09-30): native tools, and packaging choice A.
Detail: [the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §5.2 to §5.5.

## Context

The learning probe asked for one structured reply per step, with a field that named the tool.
On its first run, 3 of 20 cases failed at the coding step because the model returned two JSON
objects in one reply, and 25 of 235 calls needed a parse retry (`docs/results/s3-probe-dev.txt`;
`docs/plans/2026-09-29-s3-learning-probe.md`, Deviations). The probe rebuilt its evidence block
after each read. From the first call to the last coding call, the prompt grew by a mean ratio of
4.78 and 4.83 in the two runs (scripted, the probe reports).

**Prompt caching** discounts a prompt that starts the same way as a recent one. The match runs
from the start: tool definitions, then system text, then messages. Everything after the first
difference is paid at full price.

The controller recommended keeping the probe's structured-reply shape. Andy chose native tool
calling (2026-09-29): "there is no reason not to use native tool, it is expected within the
industry for production systems".

## Decision

1. **Native tool calling.** The model returns tool calls as a separate field of its reply. The
   probe's structured reply with a tool field is not carried forward.
2. **One tool set for every call of a run.** Each tool is defined once: a name, a fixed one-line
   description and a strict JSON schema. The definitions are byte-identical on every call, for
   every case in a run.
3. **`tool_choice` picks the step's tool.** A read step forces `choose_documents`; a checkpoint
   forces `record_hypothesis`; the coding step requires any tool. After the sixth coding call,
   `submit_answer` is forced.
4. **The system text is identical for every case**: the code tables and the two guidance files,
   the largest fixed block.
5. **The documents on offer are listed in the message**, not in a tool description or schema.
   Each read step ends with a numbered list of the unread documents and their measured facts,
   for example `[3] Pilot/operator accident report: 6 pages, text layer, about 2,100 tokens`.
   Titles pass the same guard as the rest of the evidence. Document numbers in the schema are
   plain integers. Code checks that each is on offer and that every offered document has a
   decision; a wrong number comes back to the agent as a message, with one retry.
6. **The conversation is append-only.** Case evidence follows the system text. Each document
   read arrives as a tool result at the end. No earlier message is rebuilt.
7. **The tools are in-process Python functions**, each with its native definition beside it.
   The loop runs them between calls. A later MCP server would be a thin wrapper over the same
   functions. A public, read-only MCP server of the coding tools may be an S4 artefact; that is
   a separate decision.
8. **A shape probe tests this on the provider first** (spec §5.5), at standard price and then
   batch. Among its six checks: whether strict schemas are accepted, whether forced and required
   tool calls are honoured, whether a multi-turn tool conversation works on batch, and whether
   changing `tool_choice` keeps the cache. If batch refuses tools, work stops and Andy chooses between standard calls at about
   twice the cost and a batch-only fallback. If forcing a tool breaks the cache, the fallback is
   "require any tool", with the step named in the message.

## Why

1. **Andy's choice**, quoted in the Context: native tool calling is what production systems use.
2. **It removes the probe's commonest break.** Tool calls arrive as separate items, so two calls
   in one reply are two readable calls, not a reply that fails to parse.
3. **A stable prefix can be cached.** The same tools, the same system text and an append-only
   conversation let each call reuse the one before it, up to its newest message. The cost
   estimates do not rely on this (spec §20). The noise floor measures the cached share
   ([0130](0130-the-loops-noise-floor-and-format-gate.md)).
4. **In-process tools keep control in the loop.** The loop enforces the cost cap and the step
   limits, and logs each tool result as it passes the guard. Tool results keep `mypy --strict`'s
   checks.

## What this rules out

- **The probe's structured reply with a tool field** (the controller's recommendation). Its
  strongest case: it ran in the probe; structured replies have run on batch in the evaluations
  since S1; one schema per step validates the whole reply; and it does not depend on tool
  support on batch, which is not yet tested. Rejected by Andy (Why 1).
- **Allowed document numbers as a per-case enum in the schema.** It would make a wrong number
  impossible. Rejected: each case's prompt would differ from the first byte of the tools, so no
  case could share a cached prefix. Code catches a wrong number instead.
- **A tool set that changes by step** (only the step's own tools offered). The simplest way to
  limit a step. Rejected: tool definitions come first in the cache match, so every change would
  break the cache.
- **The document list in a tool description.** Rejected for the same reason: it differs by case.
- **Rebuilding the evidence block after each read** (the probe's way). Rejected: nothing past
  the system text could be reused.
- **A local MCP server from the start.** Ready for other clients. Rejected: a second process
  and a serialisation boundary, and tool results lose `mypy --strict`'s checks, for no new
  capability now.
- **Provider-hosted MCP**, where the provider calls the tools during a request. Fewer round
  trips. Rejected: the loop would lose its step-by-step control of the cost cap, the step limit
  and the logging of each tool result as it passes the guard.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
