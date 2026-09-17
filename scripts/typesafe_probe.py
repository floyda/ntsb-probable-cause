"""One-off probe of TypeSafe's System One reply shape (decision 0036). Costs cents. Needs a key.

Usage:
    uv run python -m scripts.typesafe_probe [--model jev-latest]

Sends the evidence payload of one redacted development fixture as the ``state`` with the
phase, event and modifier tables as Choice questions, one Noul per finding category, and one
Score, in two requests. Writes tests/fixtures/typesafe/{models,choices,nouls}.json and a
README.md. Every saved body passes through ``redact`` so no id or key is committed. The wire
shape comes from the vendor's OpenAPI file as generated into ``typesafe-sdk`` 0.6.0; the
saved replies are what the project trusts.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.settings import Settings
from scripts.openrouter_probe import redact

OUT = Path("tests/fixtures/typesafe")
FIXTURE = Path("tests/fixtures/records/ANC09CA020.json")

_CHOICE_TABLES: tuple[tuple[str, str, str], ...] = (
    (
        "phase",
        "phases",
        "Which phase of flight was the aircraft in when the defining event of this accident "
        "occurred? Each label is the NTSB's three-digit phase prefix.",
    ),
    (
        "event",
        "events",
        "Which event defines this accident, in the NTSB's sense of the occurrence that the "
        "probable cause explains? Each label is the NTSB's three-digit event suffix.",
    ),
    (
        "modifier",
        "modifiers",
        "Who or what does the principal finding of this accident concern? Each label is the "
        "NTSB's two-digit finding modifier.",
    ),
)
_EVIDENCE_DETAIL_LEVELS = (
    "The evidence names the aircraft and the injury level and little else.",
    "The evidence includes the pilot's experience or the weather, but not both.",
    "The evidence includes the pilot's experience, the weather and a weather report.",
)


def payload_text() -> str:
    """The evidence payload of the fixture, built the only way a payload is built (0016)."""
    record = json.loads(FIXTURE.read_text())["record"]
    evidence, _, _ = split_record(record)
    return Payload.from_evidence(evidence).text


def choice_questions(tables: CodeTables) -> dict[str, dict[str, object]]:
    """Three Choice questions, one per short table, and one Score question."""
    questions: dict[str, dict[str, object]] = {}
    for name, table, instructions in _CHOICE_TABLES:
        criteria = dict(getattr(tables, table))
        if len(criteria) > sources.TYPESAFE_MAX_CHOICE_LABELS:
            raise ValueError(f"{table}: {len(criteria)} labels exceed the Choice limit")
        questions[name] = {"type": "choice", "instructions": instructions, "criteria": criteria}
    questions["evidence_detail"] = {
        "type": "score",
        "instructions": "How much does the evidence say about the circumstances?",
        "criteria": list(_EVIDENCE_DETAIL_LEVELS),
    }
    return questions


def noul_questions(tables: CodeTables) -> dict[str, dict[str, object]]:
    """One Noul per finding category: is it among the findings in the probable cause?"""
    return {
        f"category_{code}": {
            "type": "noul",
            "instructions": (
                f"Is the finding category {code}, {label!r}, among the findings the NTSB "
                "would flag as being in the probable cause of this accident?"
            ),
        }
        for code, label in sorted(tables.categories.items())
    }


def request_bodies(state: str, tables: CodeTables, model: str) -> dict[str, dict[str, object]]:
    """The two request bodies the probe sends, keyed by the fixture name each is saved under."""
    return {
        "choices": {"state": state, "model": model, "questions": choice_questions(tables)},
        "nouls": {"state": state, "model": model, "questions": noul_questions(tables)},
    }


def _get(http: httpx.Client, path: str) -> Any:
    """GET and return the parsed body; ``Any`` because the shape is what this probe discovers."""
    response = http.get(path)
    response.raise_for_status()
    return response.json()


def _post(http: httpx.Client, path: str, body: dict[str, object]) -> Any:
    """POST and return the parsed body; ``Any`` because the shape is what this probe discovers."""
    response = http.post(path, json=body)
    response.raise_for_status()
    return response.json()


def _save(name: str, request: dict[str, object] | None, response: dict[str, object]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    saved = {"response": redact(response)}
    if request is not None:
        saved = {"request": redact(request), **saved}
    (OUT / f"{name}.json").write_text(json.dumps(saved, indent=1) + "\n")
    print(f"saved {OUT / name}.json")


def _estimated_cost(usage: dict[str, object]) -> str:
    tokens = usage.get("input_tokens")
    if not isinstance(tokens, int):
        return "input_tokens not reported"
    return f"${tokens * sources.JEV.input_usd_per_mtok / 1_000_000:.6f} at the published price"


def main(argv: list[str]) -> int:
    """Run the three requests and write the fixtures."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=sources.JEV.model_id)
    args = parser.parse_args(argv)
    settings = Settings()
    http = httpx.Client(
        base_url=settings.typesafe_base_url,
        headers={"Authorization": f"Bearer {settings.require_typesafe_key()}"},
        timeout=60.0,
    )
    _save("models", None, _get(http, sources.TYPESAFE_MODELS))
    usages: dict[str, dict[str, object]] = {}
    for name, body in request_bodies(payload_text(), load_tables(), args.model).items():
        response = _post(http, sources.TYPESAFE_SYSTEM_ONE, body)
        _save(name, body, response)
        usages[name] = response.get("usage", {})
        print(f"{name}: usage {json.dumps(usages[name])}; {_estimated_cost(usages[name])}")
    (OUT / "README.md").write_text(
        f"# Saved TypeSafe responses\n\nWritten by `scripts/typesafe_probe.py` on "
        f"{datetime.now(UTC).date()} with model `{args.model}` (decision 0036). Ids and key "
        f"material are redacted. Usage blocks: `{json.dumps(usages)}`.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
