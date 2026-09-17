"""Tests for the OpenRouter probe's redaction helper (spec §7.1, plan Task 2)."""

from scripts.openrouter_probe import redact


def test_redact_replaces_ids_and_keys_recursively() -> None:
    """``redact`` blanks id and key fields at every depth, leaving other values intact."""
    raw = {
        "id": "gen-123",
        "usage": {"cost": 0.0001},
        "choices": [{"id": "x", "message": {"content": "hi"}}],
        "headers": {"authorization": "Bearer sk-or-abc"},
        "messages": [{"role": "tool", "tool_call_id": "call_abc123", "content": "hi"}],
    }
    out = redact(raw)
    assert out["id"] == "redacted"  # type: ignore[index]
    assert out["choices"][0]["id"] == "redacted"  # type: ignore[index]
    assert out["headers"]["authorization"] == "redacted"  # type: ignore[index]
    assert out["usage"]["cost"] == 0.0001  # type: ignore[index]
    assert out["messages"][0]["tool_call_id"] == "redacted"  # type: ignore[index]
