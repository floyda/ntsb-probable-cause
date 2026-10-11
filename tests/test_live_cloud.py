import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.live.cloud import (
    METRIC_NAME,
    METRIC_NAMESPACE,
    BucketMirror,
    MirrorSink,
    OpenRouterKeySpend,
    PrintAlerts,
    SnsAlerts,
    publish_finished,
    push_order,
)
from ntsb_probable_cause.live.morning import LiveRefusal
from ntsb_probable_cause.live.seams import MonthSpend
from ntsb_probable_cause.live.state import Closed, NightState

KEY = "not-a-real-key-for-tests"
NOW = datetime(2026, 10, 11, tzinfo=UTC)


class FakeBucket:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})
        self.uploads: list[str] = []
        self.fail_uploads = False
        self.kill_on: Callable[[str], bool] | None = None  # a key whose upload kills the task

    def list_keys(self, bucket: str, prefix: str) -> list[tuple[str, int]]:
        return [(k, len(v)) for k, v in sorted(self.objects.items()) if k.startswith(prefix)]

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        Path(filename).write_bytes(self.objects[key])

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        if self.fail_uploads:
            raise OSError("down")
        if self.kill_on is not None and self.kill_on(key):
            self.kill_on = None  # one kill: the next task's uploads go through
            raise KeyboardInterrupt  # the task is stopped before this object is written
        self.objects[key] = Path(filename).read_bytes()
        self.uploads.append(key)

    def put_if_absent(self, bucket: str, key: str, body: bytes) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = body
        return True


def _mirror(tmp_path: Path, objects: dict[str, bytes]) -> tuple[BucketMirror, FakeBucket]:
    bucket = FakeBucket(objects)
    return BucketMirror("b", tmp_path, bucket), bucket


def test_pull_skips_export_and_push_uploads_only_changes(tmp_path: Path) -> None:
    mirror, bucket = _mirror(
        tmp_path,
        {
            "runs/r1/a.txt": b"a",
            "runs/r1/sub/b.txt": b"b",
            "scores/s.json": b"s",
            "nights/state.json": b"{}",
            "export/board-1/x.json": b"x",
        },
    )
    mirror.pull()
    assert (tmp_path / "runs/r1/sub/b.txt").read_bytes() == b"b"
    assert not (tmp_path / "export").exists()
    assert mirror.push(Path("runs")) == 0
    (tmp_path / "runs/r1/a.txt").write_text("changed")
    assert mirror.push(Path("runs/r1")) == 1
    assert bucket.objects["runs/r1/a.txt"] == b"changed"
    assert mirror.push(Path("runs")) == 0
    (tmp_path / "runs/r2").mkdir()
    (tmp_path / "runs/r2/new.txt").write_text("n")
    assert mirror.push(Path("runs/r2/new.txt")) == 1
    assert "runs/r2/new.txt" in bucket.objects


def test_push_export_uploads_every_file(tmp_path: Path) -> None:
    mirror, bucket = _mirror(tmp_path, {})
    out = tmp_path / "out"
    (out / "d").mkdir(parents=True)
    (out / "a.json").write_text("1")
    (out / "d" / "b.json").write_text("2")
    mirror.push_export(out)
    mirror.push_export(out)
    assert sorted(set(bucket.uploads)) == ["export/board-1/a.json", "export/board-1/d/b.json"]
    assert len(bucket.uploads) == 4


def test_mark_started_once_per_day(tmp_path: Path) -> None:
    mirror, bucket = _mirror(tmp_path, {})
    assert mirror.mark_started(date(2026, 10, 11)) is True
    assert mirror.mark_started(date(2026, 10, 11)) is False
    assert mirror.mark_started(date(2026, 10, 12)) is True
    assert "nights/2026-10-11/started" in bucket.objects


def test_a_run_folder_is_pushed_spec_then_run_record_last_and_never_its_reservation(
    tmp_path: Path,
) -> None:
    """Fix round 1, item 1: the order is explicit; ``run.jsonl`` is the commit point."""
    mirror, bucket = _mirror(tmp_path, {})
    folder = tmp_path / "runs" / "live-1"
    folder.mkdir(parents=True)
    names = [
        "trail.jsonl", "spec.json", "run.jsonl", "cases.jsonl", "replies.jsonl",
        "closures.jsonl", "manifest.json", "reservation.json", "steps.jsonl",
    ]  # fmt: skip
    for name in names:
        (folder / name).write_text(name)
    assert mirror.push(Path("runs/live-1")) == len(names) - 1
    pushed = [k.removeprefix("runs/live-1/") for k in bucket.uploads]
    assert pushed[-2:] == ["spec.json", "run.jsonl"]
    assert pushed[:-2] == sorted(pushed[:-2])
    assert "reservation.json" not in pushed
    (folder / "trail.jsonl").write_text("more")
    (folder / "run.jsonl").write_text("finished")
    bucket.uploads.clear()
    mirror.push(Path("runs/live-1"))
    assert bucket.uploads == ["runs/live-1/trail.jsonl", "runs/live-1/run.jsonl"]


def test_push_order_puts_specs_then_run_records_after_everything_else() -> None:
    paths = [Path(p) for p in ("b/run.jsonl", "a/spec.json", "a/z.txt", "b/a.txt", "a/run.jsonl")]
    assert [p.as_posix() for p in push_order(paths)] == [
        "a/z.txt",
        "b/a.txt",
        "a/spec.json",
        "a/run.jsonl",
        "b/run.jsonl",
    ]


def test_a_claimed_day_is_held_locally_and_never_uploaded_again(tmp_path: Path) -> None:
    mirror, bucket = _mirror(tmp_path, {})
    assert mirror.mark_started(date(2026, 10, 11)) is True
    assert (tmp_path / "nights/2026-10-11/started").read_bytes() == b""
    (tmp_path / "nights/2026-10-11/night.json").write_text("{}")
    mirror.push(Path("nights/2026-10-11"))
    assert bucket.uploads == ["nights/2026-10-11/night.json"]
    assert mirror.mark_started(date(2026, 10, 11)) is False


def test_mirror_sink_finds_a_half_written_run_and_pushes(tmp_path: Path) -> None:
    mirror, bucket = _mirror(
        tmp_path,
        {
            "runs/live-1/spec.json": b'{"sample": "live"}',
            "runs/live-1/replies.jsonl": b"",
        },
    )
    mirror.pull()
    sink = MirrorSink(mirror, tmp_path)
    assert sink.unfinished_run() == "live-1"
    assert sink.night_state() == NightState()
    state = NightState(
        failures={"X": 2},
        unreachable={"Y": Closed(mkey=1, event_date=date(2026, 1, 1), closed_on=date(2026, 2, 1))},
    )
    sink.write_night_state(state)
    assert "nights/state.json" in bucket.objects
    assert MirrorSink(mirror, tmp_path).night_state() == state
    sink.write("live-2", [], None)
    assert any(k.startswith("runs/live-2/") for k in bucket.objects)


class FakeHttp:
    def __init__(self, status: int, body: object) -> None:
        self.status, self.body = status, body
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def __call__(self, url: str, *, headers: Mapping[str, str]) -> tuple[int, object]:
        self.calls.append((url, headers))
        return self.status, self.body


def test_key_spend_reads_the_month() -> None:
    http = FakeHttp(200, {"data": {"usage_monthly": 0.71, "limit": 10}})
    spend = OpenRouterKeySpend(KEY, "https://openrouter.ai/", http).month(NOW)
    assert spend == MonthSpend(0.71, 10.0)
    url, headers = http.calls[0]
    assert url == "https://openrouter.ai/api/v1/key"
    assert headers["Authorization"] == f"Bearer {KEY}"


def _refused(body: object, status: int = 200) -> LiveRefusal:
    with pytest.raises(LiveRefusal) as caught:
        OpenRouterKeySpend(KEY, "https://x", FakeHttp(status, body)).month(NOW)
    assert caught.value.kind == "key-unreachable"
    assert KEY not in str(caught.value)
    return caught.value


def _data(usage: object = 0.7, limit: object = 10) -> dict[str, object]:
    return {"data": {"usage_monthly": usage, "limit": limit}}


def test_key_spend_refusals() -> None:
    _refused(_data(), status=500)
    _refused({})
    _refused([1, 2])
    _refused({"data": "x"})
    _refused(_data(usage="0.7"))
    _refused(_data(limit=None))
    _refused(_data(limit="10"))
    _refused(_data(usage=-0.01))
    for bad in (-1, math.nan, math.inf, -math.inf):
        _refused(_data(limit=bad))
    _refused(_data(usage=math.nan))
    _refused(_data(usage=True))
    _refused(_data(limit=True))


def test_key_spend_transport_error_hides_the_key() -> None:
    def boom(url: str, *, headers: Mapping[str, str]) -> tuple[int, object]:
        raise OSError(f"connection to {url} with {headers['Authorization']} failed")

    with pytest.raises(LiveRefusal) as caught:
        OpenRouterKeySpend(KEY, "https://x", boom).month(NOW)
    assert caught.value.kind == "key-unreachable"
    assert KEY not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


class FakeSns:
    def __init__(self) -> None:
        self.published: list[dict[str, str]] = []

    def publish(self, *, TopicArn: str, Subject: str, Message: str) -> object:  # noqa: N803
        self.published.append({"TopicArn": TopicArn, "Subject": Subject, "Message": Message})
        return {}


def test_sns_alert_carries_kinds_and_counts_only() -> None:
    sns = FakeSns()
    SnsAlerts("arn:t", sns).send(["outage"], {"cases": 3})
    SnsAlerts("arn:t", sns).send(["unreachable-3"] * 40, {"cases": 3, "failed": 1})
    first = sns.published[0]
    assert first == {
        "TopicArn": "arn:t",
        "Subject": "Ellery live night: outage",
        "Message": "kinds: outage\ncases: 3",
    }
    assert len(sns.published[1]["Subject"]) < 100
    assert sns.published[1]["Message"].endswith("\ncases: 3\nfailed: 1")
    pattern = re.compile(r"[A-Z]{3}\d{2}[A-Z]{2}\d{3}")
    assert not any(pattern.search(v) for p in sns.published for v in p.values())


def test_print_alerts(capsys: pytest.CaptureFixture[str]) -> None:
    PrintAlerts().send(["outage", "x"], {"cases": 2})
    PrintAlerts().send(["y"], {})
    assert capsys.readouterr().out == "alert: outage, x (cases: 2)\nalert: y\n"


class FakeMetric:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]]]] = []

    def put_metric_data(self, *, Namespace: str, MetricData: list[dict[str, object]]) -> object:  # noqa: N803
        self.calls.append((Namespace, MetricData))
        return {}


def test_publish_finished_sends_one_point() -> None:
    metric = FakeMetric()
    publish_finished(metric)
    assert len(metric.calls) == 1
    namespace, data = metric.calls[0]
    assert (namespace, METRIC_NAMESPACE) == ("Ntsb/Live", "Ntsb/Live")
    assert len(data) == 1
    assert data[0]["MetricName"] == METRIC_NAME == "NightFinished"
    assert data[0]["Value"] == 1


def test_sns_message_always_names_the_kinds() -> None:
    sns = FakeSns()
    SnsAlerts("arn:t", sns).send(["key-unreachable"], {})
    assert sns.published[0]["Message"] == "kinds: key-unreachable"
    long_kinds = [f"unreachable-kind-{i}" for i in range(20)]
    SnsAlerts("arn:t", sns).send(long_kinds, {"cases": 2})
    last = sns.published[1]
    assert len(last["Subject"]) < 100
    assert last["Message"] == f"kinds: {', '.join(long_kinds)}\ncases: 2"


def test_alerts_refuse_anything_but_kinds_and_integers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sns = FakeSns()
    for alerts in (SnsAlerts("arn:t", sns), PrintAlerts()):
        for kinds, counts in (
            (["CEN24FA123"], {}),
            (["outage"], {"CEN24FA123": 1}),
            (["outage"], {"cases": 1.5}),
            (["outage"], {"cases": True}),
            (["Outage"], {}),
        ):
            with pytest.raises(ValueError, match="alert"):
                alerts.send(kinds, counts)  # type: ignore[arg-type]
    assert sns.published == []
    assert capsys.readouterr().out == ""


def test_push_refuses_paths_outside_the_mirrored_folders(tmp_path: Path) -> None:
    mirror, bucket = _mirror(tmp_path, {})
    (tmp_path / "other").mkdir()
    (tmp_path / "other/x.txt").write_text("x")
    for bad in (Path(), Path("../x"), Path("other"), Path("export")):
        with pytest.raises(ValueError, match="outside"):
            mirror.push(bad)
    assert bucket.uploads == []


def test_pull_skips_a_key_that_would_leave_the_folder(tmp_path: Path) -> None:
    local = tmp_path / "local"
    mirror, _ = _mirror(local, {"runs/ok.txt": b"1", "runs/../../escape.txt": b"2"})
    assert mirror.pull() == 1
    assert (local / "runs/ok.txt").is_file()
    assert not (tmp_path / "escape.txt").exists()


def test_a_failed_upload_is_retried_by_the_next_push(tmp_path: Path) -> None:
    mirror, bucket = _mirror(tmp_path, {})
    (tmp_path / "runs/r").mkdir(parents=True)
    (tmp_path / "runs/r/a.txt").write_text("a")
    bucket.fail_uploads = True
    with pytest.raises(OSError, match="down"):
        mirror.push(Path("runs/r"))
    bucket.fail_uploads = False
    assert mirror.push(Path("runs/r")) == 1
    assert bucket.objects["runs/r/a.txt"] == b"a"


def test_push_of_a_missing_path_uploads_nothing(tmp_path: Path) -> None:
    mirror, _ = _mirror(tmp_path, {})
    assert mirror.push(Path("runs/none")) == 0
    assert mirror.push(Path("runs/none/file.txt")) == 0
