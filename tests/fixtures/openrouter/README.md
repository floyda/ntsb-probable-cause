# Saved OpenRouter responses

Written by `scripts/openrouter_probe.py` on 2026-09-15 with model `openai/gpt-5.6-luna` (batch: `openai/gpt-5.6-luna:batch`). Ids and key material are redacted. Batch usage block: `{"prompt_tokens": 1665, "completion_tokens": 1763, "total_tokens": 3428, "cost": 0.0012243, "is_byok": false}`.

## Observed

Both `openai/gpt-5.6-luna` and `openai/gpt-5.6-luna-pro` were probed (Andy's key; total cost
about $0.014). `openai/gpt-5.6-luna` is the variant saved here; its ten-request batch had 7 of
10 replies parse against the mini schema. See the plan's Deviations section
(`docs/plans/2026-09-15-s1-scoring-and-evaluation.md`, dated 2026-09-15) for the full comparison
and why `luna` was chosen over `luna-pro` despite that.

- **Usage fields** (sync `response.usage`): `prompt_tokens`, `completion_tokens`,
  `total_tokens`, `cost` (USD), `completion_tokens_details.reasoning_tokens`,
  `prompt_tokens_details.cached_tokens`.
- **Structured output**: `response_format` with `json_schema` (`strict: true`) was honoured —
  every reply that finished with content parsed as the mini schema.
- **Tool calls**: work as expected — `finish_reason: "tool_calls"`, arguments `"{}"` for the
  no-parameter tool; the two-turn exchange (assistant tool call, then a `role: "tool"` message)
  round-trips correctly.
- **Batch**: submitted, then polled — first poll returned a null status, then `"in_progress"`,
  then `"completed"` after about 3 minutes (luna: 20:53 -> 20:56 UTC; luna-pro: about 4
  minutes). Results live under `results[].response.body` (a full chat completion) and
  `results[].response.status_code`. The batch-level `usage.cost` is present (see above); the
  per-result `body.usage.cost` is null. The batch's own `model` field is a dated id
  (`openai/gpt-5.6-luna-20260709`), while each individual result's `body.model` is
  `openai/gpt-5.6-luna:batch`. `request_counts` reports `{total, completed, failed}`.
