"""``ntsb-live``: the entrypoint builds the morning's dependencies and runs it (S3.3 Task 9)."""

import fcntl
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import apps.live.__main__ as app
import pytest

from ntsb_probable_cause.errors import (
    BatchCancelledError,
    BudgetError,
    ConfigurationError,
    DocketError,
)
from ntsb_probable_cause.live.fetch import FetchError
from ntsb_probable_cause.live.local import STORE_WORK_FILENAME
from ntsb_probable_cause.live.morning import MorningDeps, MorningSummary, NightOutcome
from ntsb_probable_cause.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def _summary() -> MorningSummary:
    return MorningSummary(
        run_id="20261007T040000Z-abc-live-C",
        coded=2,
        not_coded={"no docket": 1},
        returned=0,
        queued=4,
        cost_usd=0.05,
        billed_usd=0.04,
        minutes=12.5,
        freed_bytes=1000,
        warnings=("late start",),
        held_back=0,
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_STORE", "s3://bucket/key.sqlite")
    monkeypatch.setenv("NTSB_API_KEY", "test-key")
    for name in ("NTSB_COMMIT_SHA", "NTSB_LIVE_BUCKET", "NTSB_LIVE_ALERT_TOPIC_ARN"):
        monkeypatch.delenv(name, raising=False)


@dataclass
class _Calls:
    deps: MorningDeps | None = None
    kwargs: dict[str, Any] | None = None


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    seen = _Calls()

    def fake(deps: MorningDeps, **kwargs: Any) -> NightOutcome:
        seen.deps, seen.kwargs = deps, kwargs
        return NightOutcome(_summary(), ("money-held-back",))

    monkeypatch.setattr(app, "run_morning", fake)
    return seen


def test_dry_run_builds_the_deps_from_settings_and_prints_the_summary(
    calls: _Calls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made: dict[str, tuple[Any, ...]] = {}

    class FakeSource:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            made["store"] = args

    class FakeSpend:
        def __init__(self, *args: Any) -> None:
            made["spend"] = args

    class FakeSink:
        def __init__(self, *args: Any) -> None:
            made["sink"] = args

    monkeypatch.setattr(app, "S3StoreSource", FakeSource)
    monkeypatch.setattr(app, "LocalSpend", FakeSpend)
    monkeypatch.setattr(app, "LocalFolderSink", FakeSink)
    assert app.main(["run", "--dry-run"]) == 0
    settings = Settings()
    assert calls.kwargs == {"dry_run": True, "limit": None}
    assert calls.deps is not None
    assert calls.deps.settings == settings
    assert made["store"][0].raw == settings.store
    assert made["store"][1] == settings.data_dir / STORE_WORK_FILENAME
    assert made["spend"] == (settings.runs_dir,)
    assert made["sink"] == (settings.runs_dir,)
    assert calls.deps.now().tzinfo is UTC
    out = capsys.readouterr().out
    assert "coded: 2" in out
    assert "no docket: 1" in out
    assert "late start" in out


def test_a_sync_run_summary_has_no_billed_part() -> None:
    sync = replace(_summary(), billed_usd=None)
    assert "cost: $0.0500\n" in app.format_summary(sync) + "\n"
    assert "billed" not in app.format_summary(sync)
    assert "cost: $0.0500 (billed: $0.0400)" in app.format_summary(_summary())


def test_the_factories_build_the_real_clients_from_settings(
    calls: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    seen: dict[str, Any] = {}

    class Ntsb:
        def __init__(self, key: str, *, requests_per_minute: int) -> None:
            seen["ntsb"] = (key, requests_per_minute)

    class Docket:
        def __init__(self, directory: Path, *, seconds_per_request: float) -> None:
            seen["docket"] = (directory, seconds_per_request)

    class Http:
        def __init__(self, key: str, *, base_url: str) -> None:
            seen["http"] = (key, base_url)

    monkeypatch.setattr(app, "NtsbClient", Ntsb)
    monkeypatch.setattr(app, "DocketClient", Docket)
    monkeypatch.setattr(app, "OpenRouterClient", Http)
    assert app.main(["run", "--dry-run", "--limit", "3"]) == 0
    assert calls.kwargs == {"dry_run": True, "limit": 3}
    deps = calls.deps
    assert deps is not None
    settings = Settings()
    deps.ntsb()
    deps.docket()
    _http, batch = deps.models()
    assert seen["ntsb"] == ("test-key", settings.requests_per_minute)
    assert seen["docket"] == (settings.live_docket_dir, settings.docket_seconds_per_request)
    assert seen["docket"][0] != settings.docket_dir
    assert seen["http"] == ("or-key", settings.openrouter_base_url)
    assert batch is None  # decision 0165: live runs are sync, so no batch client is built


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_a_limit_below_one_is_refused_by_the_parser(value: str) -> None:
    with pytest.raises(SystemExit) as stop:
        app.main(["run", "--limit", value])
    assert stop.value.code == 2


def test_uv_lock_sha256_reads_the_repository_lockfile() -> None:
    assert app.uv_lock_sha256() == hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()


def test_a_refusal_is_one_line_and_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(deps: MorningDeps, **kwargs: Any) -> MorningSummary:
        raise BudgetError("the month is at its cap")

    monkeypatch.setattr(app, "run_morning", refuse)
    assert app.main(["run", "--dry-run"]) == 1
    assert "the month is at its cap" in capsys.readouterr().err


def _raising(error: Exception) -> Any:
    def raiser(deps: MorningDeps, **kwargs: Any) -> MorningSummary:
        raise error

    return raiser


def _aws_error(name: str, *, code: str | None = None, module: str = "botocore.exceptions") -> Any:
    cls = type(name, (Exception,), {"__module__": module})
    error = cls("boom")
    if code is not None:
        error.response = {"Error": {"Code": code}}
    return error


@pytest.mark.parametrize(
    "error",
    [
        _aws_error("TokenRetrievalError"),
        _aws_error("UnauthorizedSSOTokenError"),
        _aws_error("SSOTokenLoadError"),
        _aws_error("LoginRefreshRequired"),
        _aws_error("LoginTokenLoadError"),
        _aws_error("ClientError", code="ExpiredToken"),
        _aws_error("ClientError", code="ExpiredTokenException"),
        _aws_error("ClientError", code="RequestExpired"),
        _aws_error("ClientError", code="InvalidClientTokenId"),
    ],
)
def test_an_expired_login_says_to_log_in_again(
    error: Exception, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app, "run_morning", _raising(error))
    assert app.main(["run", "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "`aws login`" in err
    assert "ntsb-live" in err
    assert "pass" in err
    assert "--profile" not in err


@pytest.mark.parametrize(
    "error",
    [
        _aws_error("NoCredentialsError"),
        _aws_error("ProfileNotFound"),
        _aws_error("MissingDependencyException"),
        _aws_error("EndpointConnectionError"),
        _aws_error("ClientError", code="AccessDenied"),
        _aws_error("ClientError", code="NoSuchBucket"),
        _aws_error("S3TransferFailedError", module="boto3.exceptions"),
    ],
)
def test_any_other_aws_error_is_named_and_does_not_say_to_log_in(
    error: Exception, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app, "run_morning", _raising(error))
    assert app.main(["run", "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert f"AWS error ({type(error).__name__})" in err
    assert "boom" in err
    assert "aws login" not in err


def test_a_cancelled_batch_stops_the_morning_and_says_to_run_it_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app, "run_morning", _raising(BatchCancelledError("batch x cancelled")))
    assert app.main(["run", "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "batch x cancelled" in err
    assert "has no --resume option" in err


def test_an_error_that_is_not_aws_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "run_morning", _raising(RuntimeError("bug")))
    with pytest.raises(RuntimeError):
        app.main(["run", "--dry-run"])


def test_a_second_morning_is_refused_while_the_first_holds_the_lock(
    calls: _Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = Settings().runs_dir
    runs.mkdir(parents=True)
    with (runs / "live.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert app.main(["run", "--dry-run"]) == 1
    assert calls.deps is None  # nothing else was done
    assert "another morning" in capsys.readouterr().err
    assert app.main(["run", "--dry-run"]) == 0  # the lock is free again


def test_report_calls_the_s4_script_with_its_three_inputs_and_needs_no_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import scripts.s4_live_report as script  # noqa: PLC0415

    seen: list[list[str]] = []

    def fake_main(argv: list[str] | None = None) -> int:
        seen.append(list(argv or []))
        return 0

    monkeypatch.setattr(script, "main", fake_main)
    base = ["report", "--mirror", "m", "--export", "e", "--ledger", "l"]
    assert app.main(base) == 0
    assert app.main([*base, "--out", "x.txt"]) == 0
    core = ["--mirror", "m", "--export", "e", "--ledger", "l"]
    assert app.main([*base, "--attest", "a.json"]) == 0
    assert seen == [core, [*core, "--out", "x.txt"], [*core, "--attest", "a.json"]]
    with app.morning_lock(Settings().runs_dir):
        assert app.main(base) == 0  # it reads local files only, so it does not take the lock


def test_report_needs_its_three_inputs() -> None:
    with pytest.raises(SystemExit):
        app.main(["report"])


@pytest.mark.parametrize("error_class", [FetchError, DocketError])
def test_a_fetch_or_docket_error_is_reported_by_its_class_alone(
    error_class: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1: on a resume or a completion these escape ``morning`` with the docket key in the text."""
    monkeypatch.setattr(
        app, "run_morning", _raising(error_class("docket 9876543: listing not read (XXX26LA001)"))
    )
    assert app.main(["run", "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert error_class.__name__ in err
    assert "9876543" not in err
    assert "XXX26LA001" not in err
    assert err.rstrip().endswith("See the runbook, 'fetch-failed'.")  # decision 0175
    assert "Tell Claude" not in err


@pytest.mark.parametrize(
    ("text", "kept", "gone"),
    [
        ("XXX26LA001: no mKey, so no docket", "no mKey, so no docket", "XXX26LA001"),
        (
            "the docket read for XXX26LA002 is docket 111, not its own 222",
            "is docket",
            "XXX26LA002",
        ),
        (
            "the docket read for XXX26LA002 is docket 1112223, not its own 2223334",
            "not its own",
            "1112223",
        ),
        ("mkey 5550001 unreadable", "unreadable", "5550001"),
        ("batch abc cancelled, run 20261007T040000-abc1234-live-C", "20261007T040000", "<none>"),
    ],
)
def test_every_error_line_is_scrubbed_of_case_numbers_and_keys(
    text: str,
    kept: str,
    gone: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(app, "run_morning", _raising(ConfigurationError(text)))
    assert app.main(["run", "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert kept in err
    assert gone not in err
    assert not app._CASE_NUMBER.search(err)
    assert app.scrubbed("nothing to hide here: $0.015") == "nothing to hide here: $0.015"


def test_the_lock_message_is_scrubbed_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "XXX26LA003"))
    runs = Settings().runs_dir
    runs.mkdir(parents=True)
    with (runs / "live.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert app.main(["run", "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "another morning is running" in err
    assert "XXX26LA003" not in err


def test_export_writes_the_files_and_prints_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    from tests.test_live_board import _mirror  # noqa: PLC0415

    mirror = _mirror(tmp_path)
    out = tmp_path / "export"
    assert app.main(["export", "--from", str(mirror), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert re.search(r"[A-Z]{3}\d{2}[A-Z]{2}\d{3}", printed) is None
    assert "cases: 8" in printed
    assert "grade, same_first: 2" in printed
    assert json.loads((out / "index.json").read_text())["format"] == "board/1"
    assert len(list((out / "cases").glob("*.json"))) == 8


def test_export_from_a_missing_folder_is_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert app.main(["export", "--from", str(tmp_path / "nope"), "--out", str(tmp_path)]) == 1
    assert "is not a folder" in capsys.readouterr().err


def test_export_refuses_a_target_inside_the_checkout_that_git_does_not_ignore(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.test_live_board import _mirror  # noqa: PLC0415

    mirror = _mirror(tmp_path)
    before = Path("tests/fixtures/board/index.json").read_text()
    assert app.main(["export", "--from", str(mirror), "--out", "tests/fixtures/board"]) == 1
    assert "does not ignore it" in capsys.readouterr().err
    assert Path("tests/fixtures/board/index.json").read_text() == before


def test_export_allows_an_ignored_target_inside_the_checkout(tmp_path: Path) -> None:
    app._check_export_target(Path("data/export-check"))  # data/ is git-ignored
    app._check_export_target(tmp_path / "outside")


# --- S4 Task 10: paid nights only in the image (decision 0171) ---------------------------------

IMAGE_ONLY = (
    "ntsb-live run: paid nights run only in the live image (decision 0171); use --dry-run here."
)


@pytest.mark.parametrize(
    "env",
    [{}, {"NTSB_COMMIT_SHA": "abc1234"}, {"NTSB_LIVE_BUCKET": "live-bucket"}],
)
def test_a_paid_run_outside_the_image_refuses_and_calls_nothing(
    env: dict[str, str],
    calls: _Calls,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    nights: list[Any] = []
    monkeypatch.setattr(app, "run_night", lambda *a, **k: nights.append(a))
    monkeypatch.setattr(app, "_aws_clients", lambda: nights.append("aws"))
    assert app.main(["run"]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == IMAGE_ONLY
    assert captured.out == ""
    assert calls.deps is None
    assert nights == []
    assert not Settings().runs_dir.exists()  # not even the lock file


class _Paginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.asked: list[dict[str, str]] = []

    def paginate(self, **kwargs: str) -> list[dict[str, Any]]:
        self.asked.append(kwargs)
        return self.pages


class _S3:
    """A boto3 S3 client as far as the wrapper uses it."""

    def __init__(self, pages: list[dict[str, Any]] | None = None) -> None:
        self.paginator = _Paginator(pages or [])
        self.puts: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.answers: list[Exception | None] = []
        self.transfers: list[tuple[str, ...]] = []

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return self.paginator

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        if self.answers:  # one scripted answer per call: an error to raise, or None for 200
            answer = self.answers.pop(0)
            if answer is not None:
                raise answer
            return {}
        if self.error is not None:
            raise self.error
        return {}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.transfers.append(("down", bucket, key, filename))

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.transfers.append(("up", filename, bucket, key))


def _client_error(code: str, status: int) -> Exception:
    error: Exception = _aws_error("ClientError", code=code)
    error.response["ResponseMetadata"] = {"HTTPStatusCode": status}  # type: ignore[attr-defined]
    return error


def test_the_bucket_lists_every_page_not_only_the_first() -> None:
    """Carried ruling 6: ``list_objects_v2`` stops at 1,000 keys a page."""
    first = [{"Key": f"runs/r/{n}.json", "Size": n} for n in range(1000)]
    pages = [{"Contents": first}, {"Contents": [{"Key": "runs/r/last.json", "Size": 7}]}, {}]
    s3 = _S3(pages)
    keys = app.S3Bucket(s3).list_keys("live-bucket", "runs/")
    assert len(keys) == 1001
    assert keys[-1] == ("runs/r/last.json", 7)
    assert s3.paginator.asked == [{"Bucket": "live-bucket", "Prefix": "runs/"}]


def test_the_bucket_passes_transfers_through() -> None:
    s3 = _S3()
    bucket = app.S3Bucket(s3)
    bucket.download_file("b", "runs/x", "local-x")
    bucket.upload_file("local-y", "b", "runs/y")
    assert s3.transfers == [("down", "b", "runs/x", "local-x"), ("up", "local-y", "b", "runs/y")]


def test_the_marker_is_a_conditional_put_and_a_precondition_failure_is_false() -> None:
    """Carried ruling 9: ``IfNoneMatch="*"``; HTTP 412 means the day was already claimed."""
    s3 = _S3()
    bucket = app.S3Bucket(s3)
    assert bucket.put_if_absent("b", "nights/2026-10-12/started", b"") is True
    assert s3.puts == [
        {"Bucket": "b", "Key": "nights/2026-10-12/started", "Body": b"", "IfNoneMatch": "*"}
    ]
    s3.error = _client_error("PreconditionFailed", 412)
    assert bucket.put_if_absent("b", "nights/2026-10-12/started", b"") is False


def _conflict() -> Exception:
    return _client_error("ConditionalRequestConflict", 409)


@pytest.mark.parametrize(
    ("answers", "claimed", "puts"),
    [
        ([_conflict(), _client_error("PreconditionFailed", 412)], False, 2),  # the other won
        ([_conflict(), None], True, 2),  # the other write was not to this day after all
        ([_conflict(), _conflict(), _conflict()], False, 3),  # still in conflict: fail closed
    ],
    ids=["409-then-412", "409-then-200", "409-three-times"],
)
def test_a_conflicting_conditional_write_is_retried_then_fails_closed(
    answers: list[Exception | None], claimed: bool, puts: int
) -> None:
    """Fix round 1, item 4: S3's guide says to retry a 409 to a conditional write."""
    s3 = _S3()
    s3.answers = list(answers)
    pauses: list[float] = []
    bucket = app.S3Bucket(s3, sleep=pauses.append)
    assert bucket.put_if_absent("b", "nights/2026-10-12/started", b"") is claimed
    assert len(s3.puts) == puts
    assert all(put["IfNoneMatch"] == "*" for put in s3.puts)
    assert pauses == [0.5, 1.0][: puts - 1]


@pytest.mark.parametrize(
    "error", [_client_error("AccessDenied", 403), _client_error("InternalError", 500), OSError()]
)
def test_any_other_put_error_is_raised(error: Exception) -> None:
    s3 = _S3()
    s3.error = error
    with pytest.raises(type(error)):
        app.S3Bucket(s3).put_if_absent("b", "nights/2026-10-12/started", b"")


def test_a_read_only_bucket_refuses_every_write() -> None:
    s3 = _S3([{"Contents": [{"Key": "runs/a", "Size": 1}]}])
    bucket = app.ReadOnlyBucket(app.S3Bucket(s3))
    assert bucket.list_keys("b", "runs/") == [("runs/a", 1)]
    bucket.download_file("b", "runs/a", "local-a")
    with pytest.raises(ConfigurationError, match="dry run"):
        bucket.upload_file("local-a", "b", "runs/a")
    with pytest.raises(ConfigurationError, match="dry run"):
        bucket.put_if_absent("b", "nights/x/started", b"")
    assert s3.puts == []
    assert [t[0] for t in s3.transfers] == ["down"]


def test_the_http_get_returns_the_status_and_the_decoded_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx  # noqa: PLC0415

    seen: list[tuple[str, Any]] = []

    def get(url: str, **kwargs: Any) -> httpx.Response:
        seen.append((url, kwargs))
        body = b'{"data": {"limit": 10}}' if "ok" in url else b"<html>"
        return httpx.Response(200 if "ok" in url else 502, content=body)

    monkeypatch.setattr(httpx, "get", get)
    assert app.http_get("https://x/ok", headers={"A": "b"}) == (200, {"data": {"limit": 10}})
    assert app.http_get("https://x/bad", headers={}) == (502, None)
    assert seen[0][1]["headers"] == {"A": "b"}
    assert seen[0][1]["timeout"] > 0


@dataclass
class _Night:
    deps: Any = None
    kwargs: dict[str, Any] | None = None
    report: Any = None


def _image_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_COMMIT_SHA", "abc1234")
    monkeypatch.setenv("NTSB_LIVE_BUCKET", "live-bucket")
    monkeypatch.setenv("NTSB_LIVE_ALERT_TOPIC_ARN", "arn:aws:sns:eu-west-2:1:alerts")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-live-key")


@pytest.fixture
def image(monkeypatch: pytest.MonkeyPatch) -> _Night:
    """The image's environment, with fake AWS clients and a fake ``run_night``."""
    _image_env(monkeypatch)
    seen = _Night()
    clients = (_S3(), _FakeSns(), _FakeMetric())
    monkeypatch.setattr(app, "_aws_clients", lambda: clients)

    def fake(deps: Any, **kwargs: Any) -> Any:
        seen.deps, seen.kwargs = deps, kwargs
        return seen.report

    monkeypatch.setattr(app, "run_night", fake)
    return seen


class _FakeSns:
    def publish(self, **kwargs: str) -> object:
        return {}


class _FakeMetric:
    def put_metric_data(self, **kwargs: object) -> object:
        return {}


def test_in_the_image_run_builds_the_night_on_the_mirror_and_runs_it(
    image: _Night, capsys: pytest.CaptureFixture[str]
) -> None:
    from ntsb_probable_cause.live.cloud import (  # noqa: PLC0415
        BucketMirror,
        MirrorSink,
        OpenRouterKeySpend,
        SnsAlerts,
    )
    from ntsb_probable_cause.live.night import NightReport  # noqa: PLC0415

    image.report = NightReport(
        started=True,
        outcome=NightOutcome(_summary(), ("money-held-back",)),
        alerts=("money-held-back",),
        later_scored=1,
    )
    assert app.main(["run"]) == 0
    deps = image.deps
    assert image.kwargs == {"limit": None}
    settings = Settings()
    mirror = deps.mirror
    assert isinstance(mirror, BucketMirror)
    assert mirror.local == settings.data_dir / "live-mirror"
    assert deps.morning.settings.runs_dir == mirror.local / "runs"
    assert isinstance(deps.morning.sink, MirrorSink)
    assert isinstance(deps.morning.spend, OpenRouterKeySpend)
    assert isinstance(deps.alerts, SnsAlerts)
    assert deps.metric is not None
    assert deps.morning.commit() == ("abc1234", False)
    out = capsys.readouterr().out
    assert "coded: 2" in out
    assert "alert: money-held-back" in out
    assert "later scores: 1" in out


def test_in_the_image_a_stopped_night_exits_one_and_a_second_start_zero(
    image: _Night, capsys: pytest.CaptureFixture[str]
) -> None:
    from ntsb_probable_cause.live.night import NightReport  # noqa: PLC0415

    image.report = NightReport(
        started=True, outcome=None, alerts=("key-unreachable",), later_scored=0
    )
    assert app.main(["run"]) == 1
    assert "night stopped: key-unreachable" in capsys.readouterr().out
    image.report = NightReport(started=False, outcome=None, alerts=(), later_scored=0)
    assert app.main(["run"]) == 0


def test_in_the_image_a_missing_alert_topic_is_one_line(
    image: _Night, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NTSB_LIVE_ALERT_TOPIC_ARN")
    assert app.main(["run"]) == 1
    assert "NTSB_LIVE_ALERT_TOPIC_ARN" in capsys.readouterr().err
    assert image.deps is None


def test_the_nights_export_binds_the_store_the_commit_and_the_day(
    image: _Night, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ntsb_probable_cause.live.night import NightReport  # noqa: PLC0415

    image.report = NightReport(started=False, outcome=None, alerts=(), later_scored=0)
    app.main(["run"])
    seen: dict[str, Any] = {}
    events: list[str] = []

    class Source:
        def __init__(self, location: Any, work: Path) -> None:
            seen["work"] = work

        def open(self) -> str:
            events.append("open")
            return "store"

        def discard(self) -> None:
            events.append("discard")

    def build(mirror: Path, out: Path, **kwargs: Any) -> Path:
        seen.update(mirror=mirror, out=out, **kwargs)
        return out

    monkeypatch.setattr(app, "S3StoreSource", Source)
    monkeypatch.setattr(app, "build_export", build)
    settings = Settings()
    at = datetime(2026, 10, 12, 23, 59, tzinfo=UTC)
    out = image.deps.export(tmp_path / "m", at.date(), at)
    assert out == settings.data_dir / "live-export"
    assert seen["mirror"] == tmp_path / "m"
    assert seen["store"] == "store"
    assert seen["commit"] == "abc1234"
    assert (seen["today"], seen["now"]) == (at.date(), at)  # the night's, not the export's own
    assert seen["work"] != settings.data_dir / STORE_WORK_FILENAME  # not the morning's copy
    assert events == ["open", "discard"]


def test_a_cloud_dry_run_reads_the_bucket_into_a_temporary_mirror_and_writes_nothing(
    calls: _Calls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ntsb_probable_cause.live.cloud import MirrorSink, OpenRouterKeySpend  # noqa: PLC0415

    monkeypatch.setenv("NTSB_LIVE_BUCKET", "live-bucket")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-live-key")
    s3 = _S3([{"Contents": [{"Key": "runs/r1/spec.json", "Size": 2}]}])
    monkeypatch.setattr(app, "_aws_clients", lambda: (s3, _FakeSns(), _FakeMetric()))
    pulled: list[Path] = []

    def download(bucket: str, key: str, filename: str) -> None:
        pulled.append(Path(filename))
        Path(filename).write_text("{}")

    s3.download_file = download  # type: ignore[method-assign]
    assert app.main(["run", "--dry-run"]) == 0
    assert calls.kwargs == {"dry_run": True, "limit": None, "check_resume": False}
    deps = calls.deps
    assert deps is not None
    assert isinstance(deps.sink, MirrorSink)
    assert isinstance(deps.spend, OpenRouterKeySpend)
    (path,) = pulled
    assert deps.settings.runs_dir == path.parent.parent
    assert not path.exists()  # the temporary mirror is gone afterwards
    assert path.parents[4] == Settings().data_dir  # data/live-dry-run-*/mirror/runs/r1
    assert s3.puts == []
    assert [t for t in s3.transfers if t[0] == "up"] == []
    out = capsys.readouterr().out
    assert "alert: money-held-back" in out
    assert "does not check whether an unfinished run began at another commit" in out


def test_a_cloud_dry_run_holds_the_same_lock_as_the_local_run(
    calls: _Calls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1, item 8: it replaces the local run's store work file, so it takes the lock."""
    monkeypatch.setenv("NTSB_LIVE_BUCKET", "live-bucket")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-live-key")
    built: list[str] = []

    def clients() -> tuple[Any, ...]:
        built.append("aws")
        return _S3(), _FakeSns(), _FakeMetric()

    monkeypatch.setattr(app, "_aws_clients", clients)
    runs = Settings().runs_dir
    runs.mkdir(parents=True)
    with (runs / "live.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert app.main(["run", "--dry-run"]) == 1
    assert "another morning" in capsys.readouterr().err
    assert built == []  # refused before any client or pull
    assert calls.deps is None
    assert app.main(["run", "--dry-run"]) == 0  # the lock is free again
    assert built == ["aws"]


def _ledger_fixture(tmp_path: Path) -> tuple[Path, Path]:
    from ntsb_probable_cause.live import records  # noqa: PLC0415
    from ntsb_probable_cause.live.ledger import new_lines, render_line  # noqa: PLC0415

    mirror = tmp_path / "mirror"
    folder = mirror / "runs" / "r1"
    folder.mkdir(parents=True)
    (folder / "run.jsonl").write_text("row\n")
    records.write_manifest(folder)
    key = "runs/r1/manifest.json"
    lines = new_lines([], {key: (folder / "manifest.json").read_bytes()}, datetime.now(UTC))
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(render_line(line) for line in lines))
    return mirror, ledger


def test_verify_ledger_is_clean_then_names_the_key_of_a_changed_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, ledger = _ledger_fixture(tmp_path)
    args = ["verify-ledger", "--ledger", str(ledger), "--mirror", str(mirror)]
    assert app.main(args) == 0
    assert capsys.readouterr().out == "ledger lines: 1; problems: 0\n"
    (mirror / "runs/r1/run.jsonl").write_text("other\n")
    assert app.main(args) == 1
    assert capsys.readouterr().out == "runs/r1: run.jsonl: changed\nledger lines: 1; problems: 1\n"


def test_verify_ledger_refuses_a_missing_ledger_or_mirror(tmp_path: Path) -> None:
    mirror, ledger = _ledger_fixture(tmp_path)
    assert (
        app.main(["verify-ledger", "--ledger", str(tmp_path / "no"), "--mirror", str(mirror)]) == 1
    )
    assert (
        app.main(["verify-ledger", "--ledger", str(ledger), "--mirror", str(tmp_path / "no")]) == 1
    )


def test_verify_ledger_defaults_to_the_live_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mirror, ledger = _ledger_fixture(tmp_path)
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    (tmp_path / "mirror").rename(tmp_path / "live-mirror")
    assert app.main(["verify-ledger", "--ledger", str(ledger)]) == 0
    assert "problems: 0" in capsys.readouterr().out


def test_verify_ledger_on_a_malformed_ledger_fails_in_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, ledger = _ledger_fixture(tmp_path)
    ledger.write_text("not json\n")
    assert app.main(["verify-ledger", "--ledger", str(ledger), "--mirror", str(mirror)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
