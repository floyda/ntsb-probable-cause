# 0169 — The model is pinned by name, and the replying model and provider are recorded

From the S4 design session with Andy, 2026-10-10. Amends
[0161](0161-the-rendered-text-fingerprint-and-the-version-1-check.md) (the settings version 1
pins). Detail: the S4 specification, §3.2.

## Context

1. **`VERSION_1_SETTINGS["model"]` is `LUNA_6.model_id`** (`live/morning.py`), the same constant
   `current_settings()` reads, so the check compares the constant with itself. A test catches an
   edit in CI, not the live check. S3.3 carried this to S4.
2. **OpenRouter returns the replying `model` and `provider` on each completion** (saved fixture
   `tests/fixtures/openrouter/s3/standard-armb.json`: `"model": "openai/gpt-6-luna"`,
   `"provider": "OpenAI"`). The code does not record them.

## Decision

1. The setting becomes the literal `"openai/gpt-6-luna"`.
2. Each trail row (`AgentCall`) gains the reply's `model` and `provider`, optional fields.
3. The S4 report counts calls whose replying model differs from the one asked for, and calls by
   provider. A difference is reported, never refused.

## Why

1. **A literal makes the check real**: an edit to `LUNA_6` no longer passes it silently.
2. **The request is what version 1 controls; the routing is OpenRouter's.** Recording the reply
   shows what actually answered, which a public board should be able to say.

## What this rules out

- **A SHA-256 of the id**, as S3.3 suggested. The same check, harder to read. Rejected for the
  literal.
- **Refusing a reply from another model or provider.** Stricter. Rejected: the cases would fail for
  a routing choice the project does not make, and the count already makes it visible.

## Status

Accepted, 2026-10-10 (Andy: "ok yes A").
