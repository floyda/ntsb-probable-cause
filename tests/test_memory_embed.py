"""``scripts/memory_embed.py`` against fake HTTP transports (decision 0213).

Nothing here calls the network, reads a key or opens a case file.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from scripts import memory_embed

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.budget import SPEND_FILE, SpendRecord
from ntsb_probable_cause.scoring.records import read_jsonl
from ntsb_probable_cause.settings import Settings

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
PRICES = {
    "qwen/qwen3-embedding-8b": "0.00000001",
    "openai/text-embedding-3-small": "0.00000002",
    "openai/text-embedding-3-large": "0.00000013",
}


def _save_list(data_dir: Path, prices: dict[str, str]) -> None:
    path = data_dir / memory_embed.MODELS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"id": m, "pricing": {"prompt": p, "completion": "0"}} for m, p in prices.items()]
    path.write_text(json.dumps({"data": rows}))


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", openrouter_api_key="test-key")


def _committed(monkeypatch: pytest.MonkeyPatch, *, registered: bool, dirty: bool = False) -> None:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", dirty))
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): registered)


def _vectors_reply(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [
        {"object": "embedding", "index": i, "embedding": [0.1 * (i + 1), 0.2, 0.3]}
        for i, _ in enumerate(body["input"])
    ]
    usage = {"prompt_tokens": 12, "total_tokens": 12, "cost": 0.0000002}
    return httpx.Response(200, json={"object": "list", "data": data, "usage": usage})


def test_spend_record_accepts_embedding() -> None:
    row = SpendRecord(
        job_id="j",
        kind="embedding",
        model="m",
        started=NOW,
        calls=1,
        cost_usd=0.0,
        commit_sha="abc1234",
        dirty=False,
    )
    assert row.kind == "embedding"


def test_slug_names_a_model_for_a_path() -> None:
    assert memory_embed.slug("qwen/qwen3-embedding-8b") == "qwen-qwen3-embedding-8b"


def test_load_prices_reads_saved_list(tmp_path: Path) -> None:
    _save_list(tmp_path, PRICES)
    prices = memory_embed.load_prices(tmp_path)
    assert prices["openai/text-embedding-3-small"] == pytest.approx(2e-08)
    assert set(prices) == set(memory_embed.CANDIDATES)


def test_load_prices_refuses_a_missing_candidate(tmp_path: Path) -> None:
    _save_list(tmp_path, {"openai/text-embedding-3-small": "0.00000002"})
    with pytest.raises(ConfigurationError, match="qwen/qwen3-embedding-8b"):
        memory_embed.load_prices(tmp_path)


def test_load_prices_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="mem-embed-models"):
        memory_embed.load_prices(tmp_path)


def test_models_saves_the_list_verbatim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _committed(monkeypatch, registered=False)
    rows = [{"id": m, "pricing": {"prompt": p, "completion": "0"}} for m, p in PRICES.items()]

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/embeddings/models"
        return httpx.Response(200, json={"data": rows})

    settings = _settings(tmp_path)
    code = memory_embed.main(
        ["models"], settings=settings, transport=httpx.MockTransport(answer), now=lambda: NOW
    )
    assert code == 0
    saved = json.loads((settings.data_dir / memory_embed.MODELS_FILE).read_text())
    assert saved == {"data": rows}


def test_probe_refused_before_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _committed(monkeypatch, registered=False)

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request before the registration is committed")

    code = memory_embed.main(
        ["probe", "--fixtures", str(tmp_path / "fx")],
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(never),
        now=lambda: NOW,
    )
    assert code == 1
    assert "memory-embed-lookup.md is not committed" in capsys.readouterr().out


def test_probe_refuses_a_dirty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _committed(monkeypatch, registered=True, dirty=True)
    code = memory_embed.main(
        ["probe", "--fixtures", str(tmp_path / "fx")],
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(_vectors_reply),
        now=lambda: NOW,
    )
    assert code == 1
    assert "uncommitted changes" in capsys.readouterr().out


def test_probe_saves_each_reply_and_a_counts_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _committed(monkeypatch, registered=True)
    settings = _settings(tmp_path)
    _save_list(settings.data_dir, PRICES)
    sent: list[dict[str, object]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/api/v1/embeddings"
        sent.append(json.loads(request.content))
        return _vectors_reply(request)

    fixtures = tmp_path / "fx"
    out = tmp_path / "probe.txt"
    code = memory_embed.main(
        ["probe", "--fixtures", str(fixtures), "--out", str(out)],
        settings=settings,
        transport=httpx.MockTransport(answer),
        now=lambda: NOW,
    )
    assert code == 0
    assert [body["model"] for body in sent] == list(memory_embed.CANDIDATES)
    assert all(body["input"] == list(memory_embed.PROBE_TEXTS) for body in sent)
    for model in memory_embed.CANDIDATES:
        saved = json.loads((fixtures / f"{memory_embed.slug(model)}.json").read_text())
        assert len(saved["data"]) == 2
    text = capsys.readouterr().out
    assert out.read_text() == text
    assert text.count("vectors=2 length=3") == 3
    assert "check every reply holds one vector per text, of one length: ok" in text
    rows = [
        row
        for path in settings.runs_dir.glob(f"*/{SPEND_FILE}")
        for row in read_jsonl(path, SpendRecord)
    ]
    assert [row.kind for row in rows] == ["probe"]
    assert rows[0].calls == 3
    assert rows[0].cost_usd == pytest.approx(3 * 0.0000002)
    assert not list(settings.runs_dir.glob("*/reservation.json"))


def test_probe_reports_a_malformed_reply_and_returns_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _committed(monkeypatch, registered=True)
    settings = _settings(tmp_path)
    _save_list(settings.data_dir, PRICES)

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad model"}})

    code = memory_embed.main(
        ["probe", "--fixtures", str(tmp_path / "fx")],
        settings=settings,
        transport=httpx.MockTransport(answer),
        now=lambda: NOW,
    )
    assert code == 1
    text = capsys.readouterr().out
    assert "status=400" in text
    assert "check every reply holds one vector per text, of one length: FAILED" in text
