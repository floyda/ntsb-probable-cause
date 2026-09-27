"""S2.7 track 2, Tasks 5-7: the model-list filter, the reasoning rule and the probe."""

import json
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from scripts import transcriber_shortlist as ts

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import BudgetError, ModelError
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    Usage,
)
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.settings import Settings

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
        (
            {"pricing": {"prompt": "0", "completion": "0.00000013"}},
            "free or unpriced listing",
        ),
        (
            {"pricing": {"prompt": "-1", "completion": "0.00000013"}},
            "free or unpriced listing",
        ),
        (
            {"pricing": {"prompt": "not-a-number", "completion": "0.00000013"}},
            "free or unpriced listing",
        ),
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


def test_a_free_listing_is_refused_and_does_not_bump_its_paid_sibling() -> None:
    entries = [
        _entry("v/paid", canonical_slug="v/model-2026"),
        _entry(
            "v/paid:free",
            canonical_slug="v/model-2026",
            pricing={"prompt": "0", "completion": "0"},
        ),
    ]
    listed, refused = ts.shortlist(entries)
    assert [x.model_id for x in listed] == ["v/paid"]
    assert refused["free or unpriced listing"] == 1
    assert "same model as a cheaper listing" not in refused


def test_a_batch_variant_in_the_list_is_noted() -> None:
    listed, _ = ts.shortlist([_entry("v/m"), _entry("v/m:batch")])
    assert [x.model_id for x in listed] == ["v/m"]
    assert listed[0].batch_variant is True


def test_prices_are_computed_exactly_not_by_float_arithmetic() -> None:
    listed, _ = ts.shortlist(
        [_entry("v/m", pricing={"prompt": "0.0000001", "completion": "0.0000002"})]
    )
    assert listed[0].input_usd_per_mtok == 0.1
    assert listed[0].output_usd_per_mtok == 0.2
    rendered = ts.render_shortlist(listed, Counter(), source=Path("x.json"), fetched="2026-09-27")
    assert "$0.1/$0.2" in rendered


@respx.mock
def test_fetch_saves_the_list_it_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    respx.get(ts.MODELS_URL).mock(return_value=httpx.Response(200, json={"data": [_entry("v/m")]}))
    assert ts.main(["fetch", "--date", "2026-09-27"]) == 0
    saved = tmp_path / "s27" / "openrouter-models-2026-09-27.json"
    assert json.loads(saved.read_text())["data"][0]["id"] == "v/m"


def test_the_shortlist_constant_matches_the_committed_results_file() -> None:
    lines = Path("docs/results/s27-transcriber-shortlist.txt").read_text().splitlines()
    listed = [line.split()[2] for line in lines if line.startswith(("candidate ", "reserve "))]
    assert list(ts.S27_SHORTLIST) == listed


def test_every_shortlisted_model_is_priced_and_has_a_reasoning_level() -> None:
    for model in ts.S27_SHORTLIST:
        price = sources.price_of(model)
        assert "OpenRouter models API, 2026-09" in price.source
        assert model in sources.LOWEST_REASONING


# ---------------------------------------------------------------------------------------
# Task 7: the probe.
# ---------------------------------------------------------------------------------------


def _with_reasoning(monkeypatch: pytest.MonkeyPatch, *models: str) -> None:
    """Give each fake model id a reasoning level, so ``settings_for`` does not raise."""
    monkeypatch.setattr(
        sources, "LOWEST_REASONING", {**sources.LOWEST_REASONING, **dict.fromkeys(models, "none")}
    )


def _reply(content: str) -> ModelReply:
    return ModelReply(
        content=content,
        # A reported cost, so `cost_usd` (cmd_probe) never has to price a made-up model id.
        usage=Usage(prompt_tokens=10, completion_tokens=5, reported_cost_usd=0.001),
        model="m",
        response_id="r",
    )


_GOOD = json.dumps({"page_kind": "typed text", "text": "Engine sputtered at 800 ft."})


def test_the_probe_replaces_a_failure_by_the_next_model_until_enough_pass() -> None:
    def complete(model: str) -> ModelReply:
        if model == "b/fails":
            raise ModelError("400 reasoning effort not supported")
        if model == "c/bad-json":
            return _reply("not json")
        return _reply(_GOOD)

    passed, lines = ts.probe(("a/ok", "b/fails", "c/bad-json", "d/ok", "e/ok"), complete, wanted=3)
    assert passed == ["a/ok", "d/ok", "e/ok"]
    assert any("b/fails: FAILED" in line for line in lines)
    assert any("c/bad-json: the reply did not parse" in line for line in lines)


def test_the_probe_stops_once_enough_pass() -> None:
    called: list[str] = []

    def complete(model: str) -> ModelReply:
        called.append(model)
        return _reply(_GOOD)

    passed, _ = ts.probe(("a", "b", "c"), complete, wanted=2)
    assert passed == ["a", "b"]
    assert called == ["a", "b"]


class _FakeCompleter:
    """A ``ModelClient`` stub whose reply depends on the model id (``cmd_probe``'s tests)."""

    def __init__(
        self, *, bad: frozenset[str] = frozenset(), fails: frozenset[str] = frozenset()
    ) -> None:
        self._bad = bad
        self._fails = fails
        self.calls: list[str] = []

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        del payload, system, history
        self.calls.append(settings.model)
        if settings.model in self._fails:
            raise ModelError("400 reasoning effort not supported")
        if settings.model in self._bad:
            return _reply("not json")
        return _reply(_GOOD)


def _factory_for(
    client: _FakeCompleter,
) -> Callable[[Settings], Callable[[ExitStack], Callable[[], ModelClient]]]:
    def factory(_settings: Settings) -> Callable[[ExitStack], Callable[[], ModelClient]]:
        def per_job(_stack: ExitStack) -> Callable[[], ModelClient]:
            return lambda: client

        return per_job

    return factory


def test_cmd_probe_saves_every_reply_and_fixtures_only_the_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ts, "S27_SHORTLIST", ("a/ok", "b/fails", "c/bad", "d/ok"))
    monkeypatch.setattr(ts, "PROBE_WANTED", 2)
    monkeypatch.setattr(ts, "FIXTURES", tmp_path / "fixtures")
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    _with_reasoning(monkeypatch, "a/ok", "b/fails", "c/bad", "d/ok")
    client = _FakeCompleter(bad=frozenset({"c/bad"}), fails=frozenset({"b/fails"}))
    monkeypatch.setattr(ts, "openrouter_clients", _factory_for(client))
    settings = Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs")

    result = ts.cmd_probe(settings)

    assert client.calls == ["a/ok", "b/fails", "c/bad", "d/ok"]
    saved = {p.name for p in (tmp_path / "s27" / "probe-replies").glob("*.json")}
    # b/fails never returns a reply at all, so nothing is saved for it anywhere.
    assert saved == {"a__ok.json", "c__bad.json", "d__ok.json"}
    fixtured = {p.name for p in (tmp_path / "fixtures").glob("*.json")}
    assert fixtured == {"a__ok.json", "d__ok.json"}
    assert "passed (2): a/ok, d/ok" in result


def test_cmd_probe_reserves_settles_and_writes_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ts, "S27_SHORTLIST", ("a/ok",))
    monkeypatch.setattr(ts, "FIXTURES", tmp_path / "fixtures")
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    _with_reasoning(monkeypatch, "a/ok")
    client = _FakeCompleter()
    monkeypatch.setattr(ts, "openrouter_clients", _factory_for(client))
    settings = Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs")

    ts.cmd_probe(settings)

    assert open_reservations(settings.runs_dir) == {}
    assert month_spent(settings.runs_dir, now=datetime.now(UTC)) > 0


def test_cmd_probe_refuses_over_budget_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ts, "S27_SHORTLIST", ("a/ok", "b/ok"))
    monkeypatch.setattr(ts, "FIXTURES", tmp_path / "fixtures")
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    client = _FakeCompleter()
    monkeypatch.setattr(ts, "openrouter_clients", _factory_for(client))
    settings = Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs", monthly_budget_usd=0.001)

    with pytest.raises(BudgetError):
        ts.cmd_probe(settings)
    assert client.calls == []


# ---------------------------------------------------------------------------------------
# Task 7: the batch-with-image call.
# ---------------------------------------------------------------------------------------

_BATCHES = "https://openrouter.ai/api/beta/batches"


def test_cmd_batch_image_reserves_writes_spend_and_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(_BATCHES).mock(return_value=httpx.Response(200, json={"id": "batch-1"}))
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    _with_reasoning(monkeypatch, "vendor/model")
    settings = Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs", openrouter_api_key="k")

    result = ts.cmd_batch_image(settings, "vendor/model")

    assert "accepted as batch batch-1" in result
    assert open_reservations(settings.runs_dir) == {}
    assert len(list(settings.runs_dir.glob("*/spend.jsonl"))) == 1


def test_cmd_batch_image_refused_still_settles_and_records_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(_BATCHES).mock(
        return_value=httpx.Response(400, json={"error": {"message": "images not supported"}})
    )
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    _with_reasoning(monkeypatch, "vendor/model")
    settings = Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs", openrouter_api_key="k")

    result = ts.cmd_batch_image(settings, "vendor/model")

    assert "refused" in result
    assert open_reservations(settings.runs_dir) == {}
    assert len(list(settings.runs_dir.glob("*/spend.jsonl"))) == 1


def test_cmd_batch_image_refuses_over_budget_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(_BATCHES).mock(return_value=httpx.Response(200, json={"id": "b"}))
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    _with_reasoning(monkeypatch, "vendor/model")
    settings = Settings(
        data_dir=tmp_path,
        runs_dir=tmp_path / "runs",
        openrouter_api_key="k",
        monthly_budget_usd=0.0001,
    )

    with pytest.raises(BudgetError):
        ts.cmd_batch_image(settings, "vendor/model")
    assert not route.called


def test_cmd_batch_poll_records_spend_once_cost_is_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{_BATCHES}/batch-1").mock(
        return_value=httpx.Response(
            200, json={"status": "completed", "results": [], "usage": {"cost": 0.002}}
        )
    )
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    settings = Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs", openrouter_api_key="k")

    result = ts.cmd_batch_poll(settings, "batch-1")

    assert "cost 0.002" in result
    spend_files = list(settings.runs_dir.glob("*/spend.jsonl"))
    assert len(spend_files) == 1
    assert "batch-1-poll" in spend_files[0].parent.name


def test_cmd_batch_poll_writes_no_spend_before_the_cost_is_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{_BATCHES}/batch-1").mock(
        return_value=httpx.Response(200, json={"status": "validating", "results": []})
    )
    monkeypatch.setattr(ts, "commit_state", lambda: ("abcd123", False))
    settings = Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs", openrouter_api_key="k")

    result = ts.cmd_batch_poll(settings, "batch-1")

    assert "no result yet" in result
    assert list(settings.runs_dir.glob("*/spend.jsonl")) == []


# ---------------------------------------------------------------------------------------
# Task 7: the CLI wiring.
# ---------------------------------------------------------------------------------------


def test_main_probe_dispatches_to_cmd_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Settings] = []

    def fake(settings: Settings) -> str:
        captured.append(settings)
        return "ok"

    monkeypatch.setattr(ts, "cmd_probe", fake)
    assert ts.main(["probe"]) == 0
    assert len(captured) == 1


def test_main_batch_image_dispatches_with_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[Settings, str]] = []

    def fake(settings: Settings, model: str) -> str:
        captured.append((settings, model))
        return "ok"

    monkeypatch.setattr(ts, "cmd_batch_image", fake)
    assert ts.main(["batch-image", "--model", "vendor/model"]) == 0
    assert captured[0][1] == "vendor/model"


def test_main_batch_poll_dispatches_with_the_batch_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[Settings, str]] = []

    def fake(settings: Settings, batch_id: str) -> str:
        captured.append((settings, batch_id))
        return "ok"

    monkeypatch.setattr(ts, "cmd_batch_poll", fake)
    assert ts.main(["batch-poll", "--batch-id", "b-1"]) == 0
    assert captured[0][1] == "b-1"
