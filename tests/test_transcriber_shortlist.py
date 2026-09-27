"""S2.7 track 2, Tasks 5-7: the model-list filter, the reasoning rule and the probe."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from scripts import transcriber_shortlist as ts

_JUNE = int(datetime(2026, 7, 1, tzinfo=UTC).timestamp())
_MAY = int(datetime(2026, 5, 1, tzinfo=UTC).timestamp())


def _entry(model_id: str, **over: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": model_id,
        "canonical_slug": model_id + "-20260701",
        "created": _JUNE,
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        "pricing": {"prompt": "0.00000003", "completion": "0.00000013"},
        "supported_parameters": ["reasoning", "response_format", "max_tokens"],
        "reasoning": {"mandatory": False, "default_enabled": True},
    }
    entry.update(over)
    return entry


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"id": "vendor/model:batch"}, "batch variant"),
        ({"id": "~vendor/model-latest"}, "alias"),
        ({"alias_target": "vendor/model"}, "alias"),
        (
            {"architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
            "no image input",
        ),
        (
            {
                "architecture": {
                    "input_modalities": ["text", "image"],
                    "output_modalities": ["text", "image"],
                }
            },
            "not text-only output",
        ),
        ({"created": _MAY}, "released before 2026-06-01"),
        (
            {"pricing": {"prompt": "0.0000003", "completion": "0.000001"}},
            "input price above Qwen3.5 122B's",
        ),
        ({"id": "qwen/qwen3.5-122b-a10b"}, "an S2.6 candidate"),
        ({"supported_parameters": ["reasoning"]}, "no structured output"),
    ],
)
def test_the_filter_refuses_with_the_first_reason_that_applies(
    over: dict[str, object], reason: str
) -> None:
    assert ts.refusal(_entry("vendor/model", **over), ids=frozenset()) == reason


def test_an_eligible_entry_is_not_refused() -> None:
    assert ts.refusal(_entry("vendor/model"), ids=frozenset()) is None


def test_the_shortlist_orders_by_price_and_keeps_one_per_slug() -> None:
    entries = [
        _entry("b/cheap", pricing={"prompt": "0.00000002", "completion": "0.0000001"}),
        _entry("a/dear", pricing={"prompt": "0.0000002", "completion": "0.0000001"}),
        _entry(
            "c/cheap-again",
            canonical_slug="b/cheap-20260701",
            pricing={"prompt": "0.00000002", "completion": "0.0000002"},
        ),
        _entry("d/old", created=_MAY),
    ]
    listed, refused = ts.shortlist(entries)
    assert [x.model_id for x in listed] == ["b/cheap", "a/dear"]
    assert refused["released before 2026-06-01"] == 1
    assert refused["same model as a cheaper listing"] == 1
    assert listed[0].input_usd_per_mtok == pytest.approx(0.02)


@pytest.mark.parametrize(
    ("reasoning", "params", "lowest"),
    [
        (
            {"mandatory": False, "supported_efforts": ["low", "minimal", "high"]},
            ["reasoning"],
            "minimal",
        ),
        ({"mandatory": True}, ["reasoning"], "minimal"),
        ({"mandatory": False}, ["reasoning"], "none"),
        (None, ["max_tokens"], "none"),
    ],
)
def test_the_lowest_reasoning_rule(
    reasoning: dict[str, object] | None, params: list[str], lowest: str
) -> None:
    entry = _entry("vendor/model", supported_parameters=params)
    entry["reasoning"] = reasoning
    assert ts.lowest_reasoning(entry) == lowest


def test_a_batch_variant_in_the_list_is_noted() -> None:
    listed, _ = ts.shortlist([_entry("v/m"), _entry("v/m:batch")])
    assert [x.model_id for x in listed] == ["v/m"]
    assert listed[0].batch_variant is True


@respx.mock
def test_fetch_saves_the_list_it_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    respx.get(ts.MODELS_URL).mock(return_value=httpx.Response(200, json={"data": [_entry("v/m")]}))
    assert ts.main(["fetch", "--date", "2026-09-27"]) == 0
    saved = tmp_path / "s27" / "openrouter-models-2026-09-27.json"
    assert json.loads(saved.read_text())["data"][0]["id"] == "v/m"
