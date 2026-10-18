"""``scripts/memory_embed.py`` against fake HTTP transports (decision 0213).

Nothing here calls the network, reads a key or opens a case file.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from scripts import memory_coding_test, memory_embed

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import checks, snapshots
from ntsb_probable_cause.memory.embeddings import VectorCache
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support
from ntsb_probable_cause.scoring import budget
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


def test_probe_writes_the_result_before_the_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fixtures sit in the repo, so written first they make the tree dirty and the result file
    # under docs/results/ is refused; they are still saved when that write fails.
    _committed(monkeypatch, registered=True)
    settings = _settings(tmp_path)
    _save_list(settings.data_dir, PRICES)
    fixtures = tmp_path / "fx"
    seen: list[bool] = []

    def refusing(prog: str, out: Path, text: str) -> None:
        seen.append(any(fixtures.glob("*.json")))
        raise SystemExit(1)

    monkeypatch.setattr(memory_embed, "write_result", refusing)
    with pytest.raises(SystemExit):
        memory_embed.main(
            ["probe", "--fixtures", str(fixtures), "--out", str(tmp_path / "probe.txt")],
            settings=settings,
            transport=httpx.MockTransport(_vectors_reply),
            now=lambda: NOW,
        )
    assert seen == [False]
    assert len(list(fixtures.glob("*.json"))) == len(memory_embed.CANDIDATES)


# --- embed -----------------------------------------------------------------------------------

LESSON_WORDS = {"L1": "one", "L2": "two", "L3": "three"}


def _lesson(lid: str) -> Lesson:
    return Lesson(
        lesson_id=lid,
        kind="evidence",
        statement=f"lesson {LESSON_WORDS[lid]}",
        scope="a scope",
        predicts=Prediction(finding_categories=("010101",)),
        written_in=2010,
        support=Support(applies=20, agrees=10),
    )


def _stamped_snapshot(directory: Path) -> str:
    directory.mkdir(parents=True)
    memory = Memory(
        name="t",
        periods=(2010,),
        lessons=(_lesson("L1"), _lesson("L2")),
        pushed_out=(_lesson("L3"),),
    )
    path = snapshots.save(memory, directory)
    stamp = checks.Stamp(
        snapshot="t",
        sha256=snapshots.sha256_of(path),
        withheld_texts_compared=1,
        causes_compared=1,
        checked_on=date(2026, 10, 17),
        commit="abc1234",
        dirty=False,
    )
    snapshots.stamp_path("t", directory).write_text(stamp.model_dump_json())
    return snapshots.sha256_of(path)


class Embedder:
    """A fake embeddings service: a two-number vector per text; texts in ``failing`` fail."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.failing = failing
        self.sent: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        self.sent.append(texts)
        if self.failing.intersection(texts):
            return httpx.Response(503, json={})
        data = [{"index": i, "embedding": [float(len(t)), 1.0]} for i, t in enumerate(texts)]
        usage = {"prompt_tokens": len(texts), "cost": 0.000001 * len(texts)}
        return httpx.Response(200, json={"data": data, "usage": usage})


class EmbedSetup:
    """A stamped snapshot, a saved model list and a sample of ``n`` cases with cause sentences."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, n: int = 5, sample: str = ""
    ) -> None:
        _committed(monkeypatch, registered=True)
        monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
        self.sha = _stamped_snapshot(tmp_path / "snapshots")
        self.settings = Settings(
            data_dir=tmp_path / "data", runs_dir=tmp_path / "runs", openrouter_api_key="test-key"
        )
        _save_list(self.settings.data_dir, PRICES)
        # Two cases share a sentence; the last case has none.
        self.causes: dict[str, str | None] = {
            f"ZZZ10LA{i:03d}": f"the pilot's cause sentence number {i // 2 if i < 2 else i}"
            for i in range(n - 1)
        }
        self.causes[f"ZZZ10LA{n - 1:03d}"] = None
        self.sample = sample or "dev-steer-400"
        monkeypatch.setattr(
            memory_coding_test, "causes", lambda processed, sample: dict(self.causes)
        )
        monkeypatch.setattr(memory_embed, "_sleep", lambda seconds: None)

    def run(self, transport: httpx.BaseTransport, *extra: str) -> int:
        argv = ["embed", "--model", "qwen/qwen3-embedding-8b", "--snapshot", "t", *extra]
        if self.sample != "dev-steer-400":
            argv += ["--sample", self.sample]
        return memory_embed.main(argv, settings=self.settings, transport=transport, now=lambda: NOW)

    def spend_rows(self) -> list[SpendRecord]:
        return [
            row
            for path in sorted(self.settings.runs_dir.glob(f"*/{SPEND_FILE}"))
            for row in read_jsonl(path, SpendRecord)
        ]

    def vectors(self) -> dict[str, object]:
        (path,) = self.settings.runs_dir.glob(f"*/{memory_embed.VECTORS_FILE}")
        body: dict[str, object] = json.loads(path.read_text())
        return body


def test_embed_sends_only_uncached_texts_and_records_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch)
    cached = "lesson two (scope: a scope)"
    VectorCache(setup.settings.runs_dir / memory_embed.CACHE_DIR, "qwen/qwen3-embedding-8b").put(
        cached, [9.0, 9.0]
    )
    reserved: list[float] = []
    real_reserve = budget.reserve_within_budget

    def reserve(
        runs_dir: Path, job_id: str, projected: float, cap: float, *, now: datetime
    ) -> None:
        reserved.append(projected)
        real_reserve(runs_dir, job_id, projected, cap, now=now)

    monkeypatch.setattr(budget, "reserve_within_budget", reserve)
    embedder = Embedder()
    assert setup.run(httpx.MockTransport(embedder)) == 0
    sent = [text for chunk in embedder.sent for text in chunk]
    assert cached not in sent
    assert sent == list(dict.fromkeys(sent))  # each text once: the shared sentence too
    assert len(sent) == 2 + 3  # two uncached lessons, three distinct cause sentences
    chars = sum(len(text) for text in sent)
    assert reserved == [pytest.approx(chars / 4 * 2.43 * 0.00000001)]
    body = setup.vectors()
    assert body["model"] == "qwen/qwen3-embedding-8b"
    assert (body["sample"], body["snapshot"], body["snapshot_sha256"]) == (
        "dev-steer-400",
        "t",
        setup.sha,
    )
    assert body["lessons"] == {
        "L1": [float(len("lesson one (scope: a scope)")), 1.0],
        "L2": [9.0, 9.0],
        "L3": [float(len("lesson three (scope: a scope)")), 1.0],
    }
    cases = body["cases"]
    assert isinstance(cases, dict)
    assert sorted(cases) == sorted(k for k, v in setup.causes.items() if v)
    assert body["failed_cases"] == []
    assert body["no_cause_cases"] == ["ZZZ10LA004"]
    (row,) = setup.spend_rows()
    assert (row.kind, row.model, row.calls) == ("embedding", "qwen/qwen3-embedding-8b", 1)
    assert row.cost_usd == pytest.approx(0.000001 * 5)
    assert not list(setup.settings.runs_dir.glob("*/reservation.json"))
    out = capsys.readouterr().out
    assert not any(cause in out for cause in setup.causes.values() if cause)
    assert "lesson one" not in out
    assert not any(case_id in out for case_id in setup.causes)


def test_embed_sends_chunks_of_sixty_four(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch, n=200)
    embedder = Embedder()
    assert setup.run(httpx.MockTransport(embedder)) == 0
    assert [len(chunk) for chunk in embedder.sent] == [64, 64, 64, 9]  # 3 lessons + 198 sentences
    assert setup.spend_rows()[0].calls == 4


def test_embed_rerun_sends_nothing_and_writes_a_zero_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch)
    assert setup.run(httpx.MockTransport(Embedder())) == 0
    first = setup.vectors()
    for path in setup.settings.runs_dir.glob(f"*/{memory_embed.VECTORS_FILE}"):
        path.unlink()

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("every text is cached")

    later = NOW.replace(minute=5)
    argv = ["embed", "--model", "qwen/qwen3-embedding-8b", "--snapshot", "t"]
    code = memory_embed.main(
        argv, settings=setup.settings, transport=httpx.MockTransport(never), now=lambda: later
    )
    assert code == 0
    assert setup.vectors() == first
    rows = setup.spend_rows()
    assert [(row.calls, row.cost_usd) for row in rows][1] == (0, 0.0)


def test_embed_stops_when_a_lesson_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch)
    failing = frozenset({"lesson three (scope: a scope)"})
    assert setup.run(httpx.MockTransport(Embedder(failing))) == 1
    assert "refused:" in capsys.readouterr().out
    assert not list(setup.settings.runs_dir.glob(f"*/{memory_embed.VECTORS_FILE}"))
    (row,) = setup.spend_rows()
    assert row.kind == "embedding"
    assert not list(setup.settings.runs_dir.glob("*/reservation.json"))


def _failing_causes(setup: EmbedSetup, count: int) -> frozenset[str]:
    return frozenset(cause for cause in list(setup.causes.values())[2 : 2 + count] if cause)


def test_embed_stops_past_two_percent_failed_causes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 9 of 400 cause sentences fail twice: refused, the vectors file is not written.
    setup = EmbedSetup(tmp_path, monkeypatch, n=401)
    monkeypatch.setattr(memory_embed, "CHUNK_SIZE", 1)
    assert setup.run(httpx.MockTransport(Embedder(_failing_causes(setup, 9)))) == 1
    out = capsys.readouterr().out
    assert "9 of 400" in out
    assert not list(setup.settings.runs_dir.glob(f"*/{memory_embed.VECTORS_FILE}"))


def test_embed_allows_eight_failed_causes_and_lists_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch, n=401)
    monkeypatch.setattr(memory_embed, "CHUNK_SIZE", 1)
    failing = _failing_causes(setup, 8)
    assert setup.run(httpx.MockTransport(Embedder(failing))) == 0
    body = setup.vectors()
    expected = sorted(case_id for case_id, cause in setup.causes.items() if cause in failing)
    assert body["failed_cases"] == expected
    assert len(expected) == 8
    cases = body["cases"]
    assert isinstance(cases, dict)
    assert not set(expected) & set(cases)


def test_embed_refuses_dev_seal_400_before_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch, sample="dev-seal-400")
    _committed(monkeypatch, registered=False)

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request before the registration is committed")

    assert setup.run(httpx.MockTransport(never)) == 1
    assert "memory-embed-lookup.md is not committed" in capsys.readouterr().out


def _steering_winner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, last: str) -> None:
    path = tmp_path / "memory-coverage-dev.txt"
    path.write_text(f"lesson coverage ...\n{last}\n")
    monkeypatch.setattr(memory_embed, "STEERING_READING", path)


def test_embed_runs_on_dev_seal_400_once_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch, sample="dev-seal-400")
    _steering_winner(tmp_path, monkeypatch, "winner: qwen/qwen3-embedding-8b")
    assert setup.run(httpx.MockTransport(Embedder())) == 0
    assert setup.vectors()["sample"] == "dev-seal-400"
    (folder,) = setup.settings.runs_dir.glob(f"*/{memory_embed.VECTORS_FILE}")
    assert folder.parent.name.endswith("-memory-embed-dev-seal-400-qwen-qwen3-embedding-8b")


def test_embed_refuses_dev_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch, sample="dev-400")
    assert setup.run(httpx.MockTransport(Embedder())) == 1
    assert "dev-400" in capsys.readouterr().out


def test_embed_refuses_a_model_not_in_the_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch)
    argv = ["embed", "--model", "another/embedder", "--snapshot", "t"]
    assert memory_embed.main(argv, settings=setup.settings, now=lambda: NOW) == 1
    assert "another/embedder is not a registered candidate" in capsys.readouterr().out


def test_embed_refuses_a_dirty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch)
    _committed(monkeypatch, registered=True, dirty=True)
    assert setup.run(httpx.MockTransport(Embedder())) == 1
    assert "uncommitted changes" in capsys.readouterr().out


def test_embed_on_dev_seal_400_runs_only_the_steering_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = EmbedSetup(tmp_path, monkeypatch, sample="dev-seal-400")
    _steering_winner(tmp_path, monkeypatch, "winner: openai/text-embedding-3-small")

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request for a model the steering slice did not choose")

    assert setup.run(httpx.MockTransport(never)) == 1
    assert "only the steering winner openai/text-embedding-3-small" in capsys.readouterr().out


@pytest.mark.parametrize("last", ["winner: none", "winner: another/model", "description only"])
def test_steering_winner_needs_a_registered_model_on_the_last_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, last: str
) -> None:
    _committed(monkeypatch, registered=True)
    _steering_winner(tmp_path, monkeypatch, last)
    with pytest.raises(ConfigurationError, match="names no embedding winner"):
        memory_embed.steering_winner()


def test_steering_winner_needs_the_reading_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _committed(monkeypatch, registered=False)
    _steering_winner(tmp_path, monkeypatch, "winner: qwen/qwen3-embedding-8b")
    with pytest.raises(ConfigurationError, match="is not committed"):
        memory_embed.steering_winner()


def test_steering_winner_reads_the_last_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _committed(monkeypatch, registered=True)
    _steering_winner(tmp_path, monkeypatch, "winner: openai/text-embedding-3-large")
    assert memory_embed.steering_winner() == "openai/text-embedding-3-large"


# Decision 0214: four candidates, and the winner read from the coding readings. --------------


def test_the_steering_winner_comes_from_0214s_coding_reading() -> None:
    assert Path("docs/results/memory-embed-coding-dev.txt") == memory_embed.STEERING_READING


@pytest.mark.parametrize(
    ("name", "split"),
    [
        ("openai/text-embedding-3-large", ("embedding", "openai/text-embedding-3-large")),
        ("pick:openai/text-embedding-3-large", ("pick", "openai/text-embedding-3-large")),
        ("fit:openai/text-embedding-3-large", ("fit", "openai/text-embedding-3-large")),
        ("fill:openai/text-embedding-3-large", ("fill", "openai/text-embedding-3-large")),
    ],
)
def test_split_candidate_names_its_method_and_model(name: str, split: tuple[str, str]) -> None:
    assert memory_embed.split_candidate(name) == split
    assert memory_embed.candidate_name(*split) == name


@pytest.mark.parametrize(
    "last", ["winner: fit:another/model", "winner: best:qwen/qwen3-embedding-8b"]
)
def test_steering_winner_refuses_an_unknown_method_or_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, last: str
) -> None:
    _committed(monkeypatch, registered=True)
    _steering_winner(tmp_path, monkeypatch, last)
    with pytest.raises(ConfigurationError, match="names no embedding winner"):
        memory_embed.steering_winner()


@pytest.mark.parametrize("method", ["fit", "fill"])
def test_on_dev_seal_400_only_the_winners_method_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    _committed(monkeypatch, registered=True)
    large = "openai/text-embedding-3-large"
    _steering_winner(tmp_path, monkeypatch, f"winner: {method}:{large}")
    memory_embed.refuse_other_than_winner(large, "dev-seal-400", method=method)
    memory_embed.refuse_other_than_winner(large, "dev-seal-400")
    for other in {"embedding", "pick", "fit", "fill"} - {method}:
        with pytest.raises(ConfigurationError, match="the steering winner is"):
            memory_embed.refuse_other_than_winner(large, "dev-seal-400", method=other)
