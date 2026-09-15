"""One-off probe of OpenRouter's response shapes (spec §7.1). Costs under $1. Needs a key.

Usage:
    uv run python -m scripts.openrouter_probe [--model openai/gpt-5.6-luna] [--cases 10]

Writes tests/fixtures/openrouter/{structured,tool_call,two_turn,batch}.json and README.md.
Every saved response is passed through ``redact`` so no request id or key is committed.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.settings import Settings

OUT = Path("tests/fixtures/openrouter")
FIXTURE = Path("tests/fixtures/records/ANC09CA020.json")
_REDACT_KEYS = frozenset(
    {"id", "authorization", "x-api-key", "api_key", "request_id", "tool_call_id"}
)
SYSTEM = (
    "You are an aviation accident analyst. From the evidence, name the phase of flight and the "
    "event that define the accident. Reply only with JSON matching the schema."
)
MINI_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["phase", "event", "confidence"],
    "properties": {
        "phase": {"type": "string"},
        "event": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}
TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Return the recorded weather for the case.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


def redact(value: object) -> object:
    """Replace ids and key material anywhere in a JSON structure."""
    if isinstance(value, dict):
        return {
            k: ("redacted" if k.lower() in _REDACT_KEYS else redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _payload() -> str:
    record = json.loads(FIXTURE.read_text())["record"]
    evidence, _, _ = split_record(record)
    return Payload.from_evidence(evidence).text


def _post(http: httpx.Client, path: str, body: dict[str, object]) -> Any:
    """POST and return the parsed body; ``Any`` because the shape is what this probe discovers."""
    response = http.post(path, json=body)
    response.raise_for_status()
    return response.json()


def _save(name: str, request: dict[str, object], response: dict[str, object]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps({"request": redact(request), "response": redact(response)}, indent=1) + "\n"
    )
    print(f"saved {OUT / name}.json")


def main(argv: list[str]) -> int:
    """Run the four probes and write the fixtures."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=sources.LUNA.model_id)
    parser.add_argument("--cases", type=int, default=10)
    args = parser.parse_args(argv)
    settings = Settings()
    http = httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.require_openrouter_key()}"},
        timeout=120.0,
    )
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _payload()}]
    structured: dict[str, object] = {
        "model": args.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 300,
        "usage": {"include": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "mini", "strict": True, "schema": MINI_SCHEMA},
        },
    }
    _save("structured", structured, _post(http, sources.CHAT_COMPLETIONS, structured))

    tool_call = {**structured, "tools": [TOOL], "tool_choice": "required"}
    tool_call.pop("response_format")
    first = _post(http, sources.CHAT_COMPLETIONS, tool_call)
    _save("tool_call", tool_call, first)

    assistant = first["choices"][0]["message"]
    call_id = assistant["tool_calls"][0]["id"]
    two_turn = {
        **structured,
        "messages": [
            *messages,
            assistant,
            {"role": "tool", "tool_call_id": call_id, "content": '{"weather_condition": "VMC"}'},
        ],
        "tools": [TOOL],
    }
    _save("two_turn", two_turn, _post(http, sources.CHAT_COMPLETIONS, two_turn))

    batch_model = f"{args.model}:batch"
    body: dict[str, object] = {
        "endpoint": "/v1/chat/completions",
        "model": batch_model,
        "requests": [
            {"custom_id": f"probe-{i}", "body": {**structured, "model": batch_model}}
            for i in range(args.cases)
        ],
    }
    submitted = _post(http, sources.BATCHES, body)
    batch_id = submitted["id"]
    while True:
        status = http.get(f"{sources.BATCHES}/{batch_id}").json()
        print(f"batch {status.get('status')}")
        if status.get("status") in {"completed", "failed", "expired", "cancelled"}:
            break
        time.sleep(30)
    _save("batch", body, status)

    usage = status.get("usage", {})
    (OUT / "README.md").write_text(
        f"# Saved OpenRouter responses\n\nWritten by `scripts/openrouter_probe.py` on "
        f"{datetime.now(UTC).date()} with model `{args.model}` (batch: `{batch_model}`). "
        f"Ids and key material are redacted. Batch usage block: `{json.dumps(usage)}`.\n"
    )
    structured_response = json.loads((OUT / "structured.json").read_text())["response"]
    print("sync usage:", json.dumps(redact(structured_response["usage"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
