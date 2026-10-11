"""Tests for the cloud night (S4 Task 10): ``live/night.py``, decisions 0171, 0175, 0177.

Every seam is a fake. The bucket is ``tests.test_live_cloud.FakeBucket`` (in memory); the NTSB
client replays the redacted development fixture records the S3.1 runner tests use; the model is
the sync driver tests' scripted client, so the real ``AgentRunner`` and sync driver run; the key
endpoint is an ``OpenRouterKeySpend`` over a fake GET; alerts go through ``SnsAlerts`` to a fake
SNS client, so the test reads the very text an email would hold. Each night gets a new local
folder, as each Fargate task starts with an empty disk. No test reaches the network.
"""

import copy
import dataclasses
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import pytest
from tests.test_agent_drive import _scripts, _sync_replies
from tests.test_agent_loop import STATS, TABLES
from tests.test_agent_run import RAWS, Dockets, _mkey
from tests.test_live_cloud import FakeBucket
from tests.test_live_morning import _Client, _docket, _Recording, _Source, _Store

from ntsb_probable_cause.agent.run import AgentRunner
from ntsb_probable_cause.data.api import Page
from ntsb_probable_cause.errors import ApiError, ConfigurationError, LeakageError
from ntsb_probable_cause.live import cloud, later, morning, night, state
from ntsb_probable_cause.live.board import build_export
from ntsb_probable_cause.live.cloud import (
    METRIC_NAME,
    BucketMirror,
    MirrorSink,
    OpenRouterKeySpend,
    SnsAlerts,
)
from ntsb_probable_cause.live.later import LaterScore
from ntsb_probable_cause.live.morning import ALERT_KINDS, MorningDeps, NightOutcome
from ntsb_probable_cause.live.night import (
    NIGHT_FORMAT,
    NIGHT_MANIFEST_FORMAT,
    NightDeps,
    NightReport,
    run_night,
)
from ntsb_probable_cause.live.records import (
    CLOSURES_FILE,
    INPUTS_FILE,
    ClosureRecord,
    verify_manifest,
)
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import Closure

CASE_NUMBER = re.compile(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}\b")  # apps/live's own pattern
DAY_1 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
DAY_2 = DAY_1 + timedelta(days=1)
ALL_CALLS = len(_sync_replies(_scripts()))  # 10: the first case's 8, the second's 2


class FakeNtsb:
    """An ``NtsbClient`` that replays fixed records for any date; or fails like an outage."""

    def __init__(self, records: Sequence[Mapping[str, object]], *, down: bool = False) -> None:
        self.records = [dict(r) for r in records]
        self.down = down
        self.opened = 0

    def __call__(self) -> Self:
        self.opened += 1
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, _k: type[BaseException] | None, _v: BaseException | None, _t: TracebackType | None
    ) -> None:
        return None

    def cases_by_date_range(self, start: date, end: date) -> Iterator[Page]:
        if self.down:
            raise ApiError("service unavailable", status=503)
        yield Page(
            number=1,
            content=b"[]",
            records=tuple(copy.deepcopy(self.records)),
            has_more=False,
            next_marker=None,
        )


class FakeSns:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def publish(self, *, TopicArn: str, Subject: str, Message: str) -> object:  # noqa: N803
        self.sent.append({"Subject": Subject, "Message": Message})
        return {}


class FakeMetric:
    def __init__(self) -> None:
        self.points: list[list[dict[str, object]]] = []

    def put_metric_data(self, *, Namespace: str, MetricData: list[dict[str, object]]) -> object:  # noqa: N803
        self.points.append(MetricData)
        return {}


class KillOnCall(_Recording):
    """A scripted client that dies, as a killed task does, on one call."""

    def __init__(self, replies: Sequence[Any], *, kill_at: int | None = None) -> None:
        super().__init__(replies)
        self.kill_at = kill_at

    def complete(self, payload: Any, settings: Any, *, system: str = "", history: Any = ()) -> Any:
        if self.calls + 1 == self.kill_at:
            self.calls += 1
            raise KeyboardInterrupt
        return super().complete(payload, settings, system=system, history=history)


def _key(usage: object = 0.5, limit: object = 10.0, *, fail: bool = False) -> Any:
    def get(url: str, *, headers: Mapping[str, str]) -> tuple[int, object]:
        if fail:
            raise OSError("no route")
        return 200, {"data": {"usage_monthly": usage, "limit": limit}}

    return get


def _closures(raws: Sequence[Mapping[str, object]]) -> list[Closure]:
    return [
        Closure(
            mkey=_mkey(r),
            ntsb_number=str(r["ntsbNumber"]),
            event_date="2026-09-01",
            closure_run=n,
            closed_on="2026-10-05",
            closed_as="Completed",
        )
        for n, r in enumerate(raws, start=1)
    ]


def _without_codes(raw: Mapping[str, object]) -> dict[str, Any]:
    stripped: dict[str, Any] = copy.deepcopy(dict(raw))
    for aircraft in stripped.get("aircrafts") or []:
        aircraft["events"] = []
    assert not split_record(stripped)[2].occurrence_codes
    return stripped


@dataclass
class World:
    """The bucket and the outside world, shared by every night of a test."""

    tmp: Path
    monkeypatch: pytest.MonkeyPatch
    bucket: FakeBucket = field(default_factory=FakeBucket)
    events: list[str] = field(default_factory=list)
    sns: FakeSns = field(default_factory=FakeSns)
    metric: FakeMetric = field(default_factory=FakeMetric)
    exports: list[Path] = field(default_factory=list)
    export_dates: list[tuple[date, datetime]] = field(default_factory=list)
    nights: int = 0
    finished: bool = True
    store_closures: list[Closure] = field(default_factory=lambda: _closures(RAWS))

    def night(  # noqa: PLR0913 -- one night's seams
        self,
        now: datetime,
        *,
        model: _Recording | None = None,
        ntsb: FakeNtsb | None = None,
        key: Any = None,
        export: Any = None,
        local: Path | None = None,
        commit: str = "abc1234",
        step: timedelta = timedelta(seconds=1),
    ) -> tuple[NightReport, NightDeps, _Recording]:
        """One night on a fresh local folder (a new task), over the shared bucket."""
        self.nights += 1
        local = local if local is not None else self.tmp / f"task-{self.nights}" / "mirror"
        data = local.parent / "data"
        settings = Settings(data_dir=data, runs_dir=local / "runs")
        mirror = BucketMirror("live-bucket", local, self.bucket)
        fake = model if model is not None else _Recording(_sync_replies(_scripts()))
        ntsb = ntsb if ntsb is not None else FakeNtsb(RAWS)
        store_file = self.tmp / f"store-{self.nights}.sqlite"
        store_file.write_bytes(b"x")
        store = _Store(store_file, self.store_closures, finished=self.finished)
        ticks = iter(now + step * n for n in range(100000))

        def build(client: ModelClient, **kwargs: Any) -> AgentRunner:
            return AgentRunner(
                fake,
                batch=None,
                tables=TABLES,
                stats=STATS,
                seen_pairs=frozenset({"552230"}),
                runs_dir=kwargs["runs_dir"],
                month_spent_usd=kwargs["month_spent_usd"],
                commit=kwargs["commit"],
                docket=Dockets(),
                now=kwargs["now"],
                pass_reasoning=False,
                on_reply=kwargs["on_reply"],
            )

        self.monkeypatch.setattr(morning, "AgentRunner", build)

        def exported(folder: Path, today: date, at: datetime) -> Path:
            out = data / "live-export"
            self.exports.append(folder)
            self.export_dates.append((today, at))
            return build_export(folder, out, store=None, today=today, commit=commit, now=at)

        deps = NightDeps(
            morning=MorningDeps(
                settings=settings,
                now=lambda: next(ticks),
                store=_Source(self.events, store),
                spend=OpenRouterKeySpend("k", "https://or.example", key or _key()),
                sink=MirrorSink(mirror, local),
                ntsb=ntsb,  # type: ignore[arg-type]
                docket=_Client,  # type: ignore[arg-type]
                models=lambda: (fake, None),
                commit=lambda: (commit, False),
                uv_lock_sha256=lambda: "f" * 64,
            ),
            mirror=mirror,
            alerts=SnsAlerts("arn:aws:sns:eu-west-2:1:t", self.sns),
            metric=self.metric,
            ntsb=ntsb,  # type: ignore[arg-type]
            export=export if export is not None else exported,
        )
        return run_night(deps), deps, fake

    def keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.bucket.objects if k.startswith(prefix))

    def text(self, key: str) -> str:
        return self.bucket.objects[key].decode()

    def json(self, key: str) -> Any:
        return json.loads(self.text(key))

    def run_ids(self) -> list[str]:
        return sorted({k.split("/")[1] for k in self.keys("runs/")})

    def closure_ids(self) -> list[str]:
        ids: list[str] = []
        for key in self.keys("runs/"):
            if key.endswith(f"/{CLOSURES_FILE}"):
                ids += [
                    ClosureRecord.model_validate_json(x).case_id
                    for x in self.text(key).splitlines()
                ]
        return ids

    def alerts(self) -> list[str]:
        return [m["Message"].splitlines()[0].removeprefix("kinds: ") for m in self.sns.sent]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    def prefetch_docket(client: object, mkey: int, *, known_documents: int) -> Any:
        return _docket(mkey, {1: "read", 2: "read"})

    monkeypatch.setattr(morning, "prefetch_docket", prefetch_docket)
    monkeypatch.setattr(morning, "CachedDocketReader", lambda client, readings: object())
    monkeypatch.setattr(morning, "load_tables", lambda: TABLES)
    monkeypatch.setattr(morning, "load_stats", lambda name: STATS)
    monkeypatch.setattr(morning, "load_seen_pairs", frozenset)
    return World(tmp_path, monkeypatch)


def test_a_normal_night_codes_pushes_records_publishes_and_exports(world: World) -> None:
    report, _, fake = world.night(DAY_1)
    assert report.started is True
    assert report.outcome is not None
    assert report.outcome.summary.coded == 2
    assert fake.calls == ALL_CALLS
    assert "nights/2026-10-12/started" in world.bucket.objects
    (run_id,) = world.run_ids()
    folder = f"runs/{run_id}/"
    assert {folder + CLOSURES_FILE, folder + "manifest.json", folder + INPUTS_FILE} <= set(
        world.keys(folder)
    )
    assert folder + "reservation.json" not in world.bucket.objects
    assert {folder + "replies.jsonl", folder + "trail.jsonl", folder + "run.jsonl"} <= set(
        world.keys(folder)
    )
    fresh = world.tmp / "fresh"
    BucketMirror("live-bucket", fresh, world.bucket).pull()
    assert verify_manifest(fresh / "runs" / run_id) == []  # what the ledger's check reads
    record = world.json("nights/2026-10-12/night.json")
    assert record["format"] == NIGHT_FORMAT
    assert record["date"] == "2026-10-12"
    assert record["coded"] == 2
    assert record["alerts"] == []
    manifest = world.json("nights/2026-10-12/manifest.json")
    assert manifest["format"] == NIGHT_MANIFEST_FORMAT
    assert manifest["finished"] is True
    assert manifest["counts"]["coded"] == 2
    assert all(isinstance(v, int) for v in manifest["counts"].values())
    covered = {e["path"] for e in manifest["night_files"]}
    assert folder + "manifest.json" in covered
    assert "nights/state.json" in covered
    assert {e["path"] for e in manifest["files"]} == {"night.json", "started"}
    for entry in manifest["night_files"]:
        assert world.bucket.objects[entry["path"]].__len__() == entry["size"]
    assert len(world.metric.points) == 1
    assert world.metric.points[0][0]["MetricName"] == METRIC_NAME
    assert len(world.exports) == 1
    assert "export/board-1/index.json" in world.bucket.objects
    assert world.sns.sent == []
    assert report.alerts == ()


def test_a_kill_after_the_first_pushed_reply_resumes_next_night_and_codes_no_case_twice(
    world: World,
) -> None:
    """Review Focus 1: the bucket holds what a resume needs; only unanswered calls go again."""
    replies = _sync_replies(_scripts())
    killed = KillOnCall(replies, kill_at=2)
    with pytest.raises(KeyboardInterrupt):
        world.night(DAY_1, model=killed)
    (run_id,) = world.run_ids()
    folder = f"runs/{run_id}/"
    assert world.text(folder + INPUTS_FILE).count("\n") == 2
    assert len(world.text(folder + "replies.jsonl").splitlines()) == 1
    assert folder + "run.jsonl" not in world.bucket.objects  # killed: never finished, never sent
    assert world.keys("nights/2026-10-12/") == ["nights/2026-10-12/started"]

    rest = _Recording(replies[1:])
    report, _, _ = world.night(DAY_2, model=rest)
    assert rest.calls == ALL_CALLS - 1  # only the unanswered calls
    assert report.outcome is not None
    assert report.outcome.summary.run_id == run_id
    assert world.run_ids() == [run_id]
    ids = world.closure_ids()
    assert sorted(ids) == sorted(str(r["ntsbNumber"]) for r in RAWS)
    assert len(ids) == len(set(ids))  # no case coded twice
    assert len(world.text(folder + "replies.jsonl").splitlines()) == ALL_CALLS

    third, _, idle = world.night(DAY_2 + timedelta(days=1))
    assert idle.calls == 0
    assert third.outcome is not None
    assert third.outcome.summary.coded == 0
    assert len(world.closure_ids()) == len(RAWS)


def test_a_kill_before_the_first_reply_still_leaves_the_inputs_in_the_bucket(world: World) -> None:
    replies = _sync_replies(_scripts())
    with pytest.raises(KeyboardInterrupt):
        world.night(DAY_1, model=KillOnCall(replies, kill_at=1))
    (run_id,) = world.run_ids()
    assert f"runs/{run_id}/{INPUTS_FILE}" in world.bucket.objects
    assert f"runs/{run_id}/backfill.json" in world.bucket.objects
    again = _Recording(replies)
    world.night(DAY_2, model=again)
    assert again.calls == ALL_CALLS
    assert world.run_ids() == [run_id]


def test_a_second_start_on_the_same_day_stops_before_the_store(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review Focus 5: the marker's conditional write is refused, so nothing else happens."""
    world.bucket.objects["nights/2026-10-12/started"] = b""
    ntsb = FakeNtsb(RAWS)
    report, _, fake = world.night(DAY_1, ntsb=ntsb)
    assert report == NightReport(started=False, outcome=None, alerts=(), later_scored=0)
    assert "open" not in world.events
    assert fake.calls == 0
    assert ntsb.opened == 0
    assert world.sns.sent == []
    assert world.metric.points == []
    assert world.exports == []
    assert world.bucket.uploads == []
    # Pulled before the claim (fix round 1, item 5): a pull only reads the bucket.
    assert (world.tmp / "task-1" / "mirror" / "nights/2026-10-12/started").is_file()
    assert "a night already started today" in capsys.readouterr().out


def test_a_pull_that_fails_leaves_the_day_unclaimed(world: World) -> None:
    """Fix round 1, item 5: the pull comes before the marker, so a rerun today can claim it."""
    world.bucket.objects["runs/r/x.json"] = b"{}"
    real = world.bucket.download_file

    def broken(bucket: str, key: str, filename: str) -> None:
        raise OSError("the bucket could not be read")

    world.bucket.download_file = broken  # type: ignore[method-assign]
    with pytest.raises(OSError, match="could not be read"):
        world.night(DAY_1)
    assert "nights/2026-10-12/started" not in world.bucket.objects
    assert world.alerts() == ["night-crashed"]
    assert "open" not in world.events
    world.bucket.download_file = real  # type: ignore[method-assign]
    report, _, _ = world.night(DAY_1)
    assert report.started is True


def test_an_outage_night_alerts_once_and_counts_no_failure(world: World) -> None:
    report, _, fake = world.night(DAY_1, ntsb=FakeNtsb(RAWS, down=True))
    assert report.alerts == ("outage",)
    assert world.alerts() == ["outage"]
    assert fake.calls == 0
    record = world.json("nights/2026-10-12/night.json")
    assert record["failures_counted"] == 0
    assert record["alerts"] == ["outage"]
    assert world.json("nights/state.json")["failures"] == {}
    assert len(world.metric.points) == 1  # an outage is not a refusal: the night finished


def test_a_key_that_fails_spends_nothing_and_publishes_no_metric(world: World) -> None:
    report, _, fake = world.night(DAY_1, key=_key(fail=True))
    assert report.outcome is None
    assert report.alerts == ("key-unreachable",)
    assert world.alerts() == ["key-unreachable"]
    assert fake.calls == 0
    assert "open" not in world.events
    assert world.metric.points == []
    assert world.run_ids() == []
    record = world.json("nights/2026-10-12/night.json")
    assert record["alerts"] == ["key-unreachable"]
    assert world.json("nights/2026-10-12/manifest.json")["finished"] is False
    assert len(world.exports) == 1  # the export needs no key


def test_a_recorder_not_finished_is_a_refusal_alert(world: World) -> None:
    world.finished = False
    report, _, fake = world.night(DAY_1)
    assert report.alerts == ("recorder-not-finished",)
    assert world.alerts() == ["recorder-not-finished"]
    assert fake.calls == 0
    assert world.metric.points == []


def test_money_held_back_sends_its_own_count(world: World) -> None:
    report, _, _ = world.night(DAY_1, key=_key(usage=8.5))  # room $0.50: one case
    assert report.alerts == ("money-held-back",)
    (sent,) = world.sns.sent
    assert "held-back: 1" in sent["Message"]
    assert len(world.metric.points) == 1


def test_a_case_coded_before_its_codes_is_scored_on_a_later_night(world: World) -> None:
    first = RAWS[0]
    stripped = [_without_codes(first), *RAWS[1:]]
    world.night(DAY_1, ntsb=FakeNtsb(stripped))
    assert world.keys("scores/") == []
    report, _, _ = world.night(DAY_2, ntsb=FakeNtsb(RAWS))
    assert report.later_scored == 1
    (key,) = world.keys("scores/")
    assert key == "scores/2026-10-13.jsonl"
    (line,) = world.text(key).splitlines()
    assert LaterScore.model_validate_json(line).case_id == str(first["ntsbNumber"])
    assert world.json("nights/2026-10-13/night.json")["later_scored"] == 1
    covered = {e["path"] for e in world.json("nights/2026-10-13/manifest.json")["night_files"]}
    assert key in covered
    again, _, _ = world.night(DAY_2 + timedelta(days=1), ntsb=FakeNtsb(RAWS))
    assert again.later_scored == 0  # a score, once written, stands


def test_a_case_still_without_codes_after_seven_nights_alerts(world: World) -> None:
    stripped = [_without_codes(RAWS[0]), *RAWS[1:]]
    world.night(DAY_1, ntsb=FakeNtsb(stripped))
    report, _, _ = world.night(DAY_1 + timedelta(days=7), ntsb=FakeNtsb(stripped))
    assert report.alerts == ("awaiting-codes-7",)
    (sent,) = world.sns.sent
    assert "overdue: 1" in sent["Message"]


def test_one_bad_record_does_not_stop_later_scoring(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carried ruling 5 (Task 8): the error is counted by kind and the others are scored."""
    stripped = [_without_codes(r) if split_record(r)[2].occurrence_codes else r for r in RAWS]
    world.night(DAY_1, ntsb=FakeNtsb(stripped))
    first = str(RAWS[0]["ntsbNumber"])
    real = later.score_later

    def flaky(raw: Mapping[str, object], case: Any, today: date) -> Any:
        if case.case_id == first:
            raise LeakageError("the guard refused a field of XXX26LA001")
        return real(raw, case, today)

    monkeypatch.setattr(night, "score_later", flaky)
    report, _, _ = world.night(DAY_2, ntsb=FakeNtsb(RAWS))
    record = world.json("nights/2026-10-13/night.json")
    assert record["later_errors"] == {"leakage": 1}
    scored = sum(1 for r in RAWS if split_record(r)[2].occurrence_codes) - 1
    assert report.later_scored == scored
    assert not CASE_NUMBER.search(json.dumps(record))
    # Fix round 1, item 6: its own alert, counted by error class.
    assert report.alerts == ("later-score-failed",)
    (sent,) = world.sns.sent
    assert sent["Message"] == "kinds: later-score-failed\nleakage-error: 1"
    assert record["alerts"] == ["later-score-failed"]
    assert len(world.metric.points) == 2  # not a refusal: both nights finished


def test_a_damaged_mirror_alerts_export_failed_and_pushes_no_export(world: World) -> None:
    def broken(folder: Path, today: date, at: datetime) -> Path:
        raise ConfigurationError("export refused: the mirror is damaged (1 cases: no raw record)")

    report, _, _ = world.night(DAY_1, export=broken)
    assert report.alerts == ("export-failed",)
    assert world.alerts() == ["export-failed"]
    assert world.keys("export/") == []
    assert world.json("nights/2026-10-12/night.json")["alerts"] == ["export-failed"]
    assert len(world.metric.points) == 1


def test_the_export_pushes_only_its_own_folder(world: World, tmp_path: Path) -> None:
    def export(folder: Path, today: date, at: datetime) -> Path:
        out = tmp_path / "work" / "live-export"
        (out / "cases").mkdir(parents=True)
        (out / "index.json").write_text("{}")
        (out.parent / ".live-export-build-x").mkdir()
        (out.parent / ".live-export-build-x" / "leftover.json").write_text("{}")
        return out

    world.night(DAY_1, export=export)
    assert world.keys("export/") == ["export/board-1/index.json"]


def test_a_crash_sends_night_crashed_with_no_counts_and_reraises(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("a bug")

    monkeypatch.setattr(night, "run_morning", crash)
    with pytest.raises(RuntimeError, match="a bug"):
        world.night(DAY_1)
    assert world.sns.sent == [
        {"Subject": "Ellery live night: night-crashed", "Message": "kinds: night-crashed"}
    ]
    assert world.metric.points == []


def test_a_fetch_error_that_escapes_the_morning_stops_the_night_as_fetch_failed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ntsb_probable_cause.live.fetch import FetchError  # noqa: PLC0415

    def fails(*_args: Any, **_kwargs: Any) -> Any:
        raise FetchError("docket 1234567: listing not read (XXX26LA001)")

    monkeypatch.setattr(night, "run_morning", fails)
    report, _, _ = world.night(DAY_1)
    assert report.outcome is None
    assert report.alerts == ("fetch-failed",)
    assert world.metric.points == []


def test_the_runs_folder_must_be_the_mirrors(world: World, tmp_path: Path) -> None:
    _, deps, _ = world.night(DAY_1)
    marked = world.bucket.put_if_absent
    claims: list[str] = []

    def claim(bucket: str, key: str, body: bytes) -> bool:
        claims.append(key)
        return marked(bucket, key, body)

    world.bucket.put_if_absent = claim  # type: ignore[method-assign]
    wrong = MorningDeps(
        **{**deps.morning.__dict__, "settings": Settings(data_dir=tmp_path / "elsewhere")}
    )
    with pytest.raises(ConfigurationError, match="runs"):
        run_night(NightDeps(**{**deps.__dict__, "morning": wrong}))
    assert world.alerts()[-1] == "night-crashed"
    assert claims == []  # the day was never claimed


def test_no_record_manifest_alert_or_printed_line_holds_a_case_number(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Carried ruling 14: kinds, counts, dates and hashes only (decision 0024)."""
    stripped = [_without_codes(RAWS[0]), *RAWS[1:]]
    world.night(DAY_1, ntsb=FakeNtsb(stripped), key=_key(usage=8.5))
    world.night(DAY_1 + timedelta(days=7), ntsb=FakeNtsb(stripped), key=_key(fail=True))
    texts = [world.text(k) for k in world.keys("nights/")]
    texts += [m["Subject"] + m["Message"] for m in world.sns.sent]
    texts.append(capsys.readouterr().out)
    assert world.sns.sent, "alerts were sent"
    for text in texts:
        assert not CASE_NUMBER.search(text), text


def test_every_kind_the_night_and_morning_raise_is_listed() -> None:
    """Carried ruling 13: one constant holds every kind; Task 14's runbook test imports it."""

    def source(module: Any) -> str:
        return Path(module.__file__).read_text()

    raised = set(re.findall(r'LiveRefusal\(\s*"([a-z0-9-]+)"', source(morning) + source(cloud)))
    raised |= set(re.findall(r'alerts\.append\("([a-z0-9-]+)"\)', source(morning)))
    raised |= set(re.findall(r'"(outage|unreachable-[a-z0-9]+)"', source(state)))
    raised |= set(night.NIGHT_KINDS)
    assert {"key-unreachable", "outage", "unreachable-final", "night-crashed"} <= raised
    assert raised <= set(ALERT_KINDS)


def test_a_later_fetch_that_fails_is_counted_and_the_night_goes_on(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    stripped = [_without_codes(RAWS[0]), *RAWS[1:]]
    world.night(DAY_1, ntsb=FakeNtsb(stripped))
    report, _, _ = world.night(DAY_2, ntsb=FakeNtsb(RAWS, down=True))  # nothing queued tonight
    assert report.alerts == ("later-score-failed",)
    assert world.json("nights/2026-10-13/night.json")["later_errors"] == {"fetch-failed": 1}
    assert world.sns.sent[-1]["Message"] == "kinds: later-score-failed\nfetch-error: 1"

    def broken(raw: Mapping[str, object], case: Any, today: date) -> Any:
        raise ValueError("an unexpected shape")

    monkeypatch.setattr(night, "score_later", broken)
    world.night(DAY_2 + timedelta(days=1), ntsb=FakeNtsb(RAWS))
    assert world.json("nights/2026-10-14/night.json")["later_errors"] == {"error": 1}
    assert world.sns.sent[-1]["Message"] == "kinds: later-score-failed\nvalue-error: 1"


def test_each_alert_carries_the_counts_of_its_own_condition() -> None:
    from tests.test_live_app import _summary  # noqa: PLC0415

    summary = dataclasses.replace(_summary(), failures_counted=3, held_back=2, returned=4)
    outcome = NightOutcome(summary, ())
    later = night._Later(scored=0, overdue=5, errors={}, path=None)
    assert night._alert_counts("unreachable-3", outcome, later) == {"failures-counted": 3}
    assert night._alert_counts("unreachable-final", outcome, later) == {"failures-counted": 3}
    assert night._alert_counts("outage", outcome, later) == {"returned": 4}
    assert night._alert_counts("money-held-back", outcome, later) == {"held-back": 2, "coded": 2}
    assert night._alert_counts("awaiting-codes-7", None, later) == {"overdue": 5}
    assert night._alert_counts("key-unreachable", None, later) == {}


def test_a_kind_not_in_the_list_is_refused_before_anything_is_sent() -> None:
    with pytest.raises(ConfigurationError, match="ALERT_KINDS"):
        night._check_kinds(["outage", "Not A Kind"])
    night._check_kinds(list(ALERT_KINDS))


def test_a_kill_before_the_run_record_is_pushed_leaves_a_run_the_next_night_completes(
    world: World,
) -> None:
    """Fix round 1, item 1: ``run.jsonl`` goes up last, so a run never reads finished but short."""
    world.bucket.kill_on = lambda key: key.endswith("/run.jsonl")
    with pytest.raises(KeyboardInterrupt):
        world.night(DAY_1)
    (run_id,) = world.run_ids()
    folder = f"runs/{run_id}/"
    assert folder + "run.jsonl" not in world.bucket.objects
    assert {folder + "trail.jsonl", folder + CLOSURES_FILE, folder + "manifest.json"} <= set(
        world.keys(folder)
    )
    fresh = world.tmp / "half"
    BucketMirror("live-bucket", fresh, world.bucket).pull()
    assert MirrorSink(BucketMirror("b", fresh, FakeBucket()), fresh).unfinished_run() == run_id

    idle = _Recording([])
    report, _, _ = world.night(DAY_2, model=idle)
    assert idle.calls == 0  # every reply is in the bucket: nothing is paid for again
    assert report.outcome is not None
    assert report.outcome.summary.run_id == run_id
    assert report.outcome.summary.coded == 2
    assert folder + "run.jsonl" in world.bucket.objects
    assert world.run_ids() == [run_id]
    ids = world.closure_ids()
    assert sorted(ids) == sorted(str(r["ntsbNumber"]) for r in RAWS)
    again = world.tmp / "again"
    BucketMirror("live-bucket", again, world.bucket).pull()
    assert verify_manifest(again / "runs" / run_id) == []
    assert MirrorSink(BucketMirror("b", again, FakeBucket()), again).unfinished_run() is None


def test_a_kill_before_the_first_spec_leaves_no_live_run_and_nothing_sent(world: World) -> None:
    """Fix round 1, item 1: on a folder's first push ``spec.json`` goes last, before any call."""
    world.bucket.kill_on = lambda key: key.startswith("runs/") and key.endswith("/spec.json")
    first = _Recording(_sync_replies(_scripts()))
    with pytest.raises(KeyboardInterrupt):
        world.night(DAY_1, model=first)
    assert first.calls == 0  # the first push precedes the first request
    (dead,) = world.run_ids()
    assert f"runs/{dead}/{INPUTS_FILE}" in world.bucket.objects
    assert f"runs/{dead}/spec.json" not in world.bucket.objects
    fresh = world.tmp / "half"
    BucketMirror("live-bucket", fresh, world.bucket).pull()
    sink = MirrorSink(BucketMirror("b", fresh, FakeBucket()), fresh)
    assert sink.unfinished_run() is None  # not taken for a live run
    assert sink.done_case_ids() == frozenset()

    again = _Recording(_sync_replies(_scripts()))
    report, _, _ = world.night(DAY_2, model=again)
    assert again.calls == ALL_CALLS
    assert report.outcome is not None
    assert report.outcome.summary.coded == 2
    assert report.outcome.summary.run_id != dead
    ids = world.closure_ids()
    assert sorted(ids) == sorted(str(r["ntsbNumber"]) for r in RAWS)  # each case once


def test_an_export_that_raises_anything_is_export_failed_and_the_night_record_still_goes_up(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1, item 2: not only ``ConfigurationError``; the class is printed, not the text."""

    def broken(folder: Path, today: date, at: datetime) -> Path:
        raise OSError("/data/live-export-store.sqlite: no space left (XXX26LA001)")

    report, _, _ = world.night(DAY_1, export=broken)
    assert report.outcome is not None
    assert report.alerts == ("export-failed",)
    assert world.alerts() == ["export-failed"]
    assert world.json("nights/2026-10-12/night.json")["alerts"] == ["export-failed"]
    assert world.json("nights/2026-10-12/manifest.json")["finished"] is True
    assert len(world.metric.points) == 1  # an export failure is not a refusal
    out = capsys.readouterr().out
    assert "the export failed (OSError)" in out
    assert "no space" not in out
    assert not CASE_NUMBER.search(out)


def test_a_push_of_the_export_that_fails_is_export_failed_too(world: World) -> None:
    real = world.bucket.upload_file

    def upload(filename: str, bucket: str, key: str) -> None:
        if key.startswith("export/"):
            raise OSError("down")
        real(filename, bucket, key)

    world.bucket.upload_file = upload  # type: ignore[method-assign]
    report, _, _ = world.night(DAY_1)
    assert report.alerts == ("export-failed",)
    assert "nights/2026-10-12/night.json" in world.bucket.objects
    assert len(world.metric.points) == 1


def test_an_unfinished_run_from_another_commit_is_refused_before_the_store(world: World) -> None:
    """Fix round 1, item 3: never a resume across commits (decisions 0018, 0033)."""
    replies = _sync_replies(_scripts())
    with pytest.raises(KeyboardInterrupt):
        world.night(DAY_1, model=KillOnCall(replies, kill_at=2))
    (run_id,) = world.run_ids()
    opened = world.events.count("open")

    other = _Recording(replies[1:])
    report, _, _ = world.night(DAY_2, model=other, commit="def5678")
    assert report.outcome is None
    assert report.alerts == ("resume-refused",)
    assert world.alerts() == ["resume-refused"]
    assert other.calls == 0
    assert world.events.count("open") == opened  # the store is not opened tonight
    assert world.metric.points == []  # a refusal stopped the night
    assert world.json("nights/2026-10-13/night.json")["alerts"] == ["resume-refused"]
    assert world.json("nights/2026-10-13/manifest.json")["finished"] is False
    assert len(world.exports) == 1  # the steps that need no store still run
    assert world.run_ids() == [run_id]

    same = _Recording(replies[1:])
    later_night, _, _ = world.night(DAY_2 + timedelta(days=1), model=same)
    assert same.calls == ALL_CALLS - 1  # the run's own commit resumes it
    assert later_night.outcome is not None
    assert later_night.outcome.summary.run_id == run_id


def test_a_night_past_midnight_dates_everything_by_its_start(world: World) -> None:
    """Fix round 1, item 7: the export takes the night's day and clock reading."""
    start = datetime(2026, 10, 12, 23, 59, 30, tzinfo=UTC)
    report, _, _ = world.night(start, step=timedelta(minutes=1))
    assert report.outcome is not None
    run_id = report.outcome.summary.run_id
    assert run_id is not None
    assert run_id.startswith("20261013T")  # the clock did pass midnight during the night
    assert world.export_dates == [(start.date(), start)]
    assert "nights/2026-10-12/night.json" in world.bucket.objects
    assert world.keys("nights/2026-10-13/") == []
