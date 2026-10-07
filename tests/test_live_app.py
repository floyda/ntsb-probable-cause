"""``ntsb-live``: the entrypoint builds the morning's dependencies and runs it (S3.3 Task 9)."""

import fcntl
import hashlib
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

import apps.live.__main__ as app
import pytest

from ntsb_probable_cause.errors import BatchCancelledError, BudgetError
from ntsb_probable_cause.live.local import STORE_WORK_FILENAME
from ntsb_probable_cause.live.morning import MorningDeps, MorningSummary
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
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_STORE", "s3://bucket/key.sqlite")
    monkeypatch.setenv("NTSB_API_KEY", "test-key")


@dataclass
class _Calls:
    deps: MorningDeps | None = None
    kwargs: dict[str, Any] | None = None


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    seen = _Calls()

    def fake(deps: MorningDeps, **kwargs: Any) -> MorningSummary:
        seen.deps, seen.kwargs = deps, kwargs
        return _summary()

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

    class Batch:
        def __init__(self, http: object) -> None:
            seen["batch"] = http

    monkeypatch.setattr(app, "NtsbClient", Ntsb)
    monkeypatch.setattr(app, "DocketClient", Docket)
    monkeypatch.setattr(app, "OpenRouterClient", Http)
    monkeypatch.setattr(app, "BatchClient", Batch)
    assert app.main(["run", "--limit", "3"]) == 0
    assert calls.kwargs == {"dry_run": False, "limit": 3}
    deps = calls.deps
    assert deps is not None
    settings = Settings()
    deps.ntsb()
    deps.docket()
    http, batch = deps.models()
    assert seen["ntsb"] == ("test-key", settings.requests_per_minute)
    assert seen["docket"] == (settings.live_docket_dir, settings.docket_seconds_per_request)
    assert seen["docket"][0] != settings.docket_dir
    assert seen["http"] == ("or-key", settings.openrouter_base_url)
    assert seen["batch"] is http
    assert isinstance(batch, Batch)


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
    assert app.main(["run"]) == 1
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
    assert app.main(["run"]) == 1
    assert "aws login --profile ntsb" in capsys.readouterr().err


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
    assert app.main(["run"]) == 1
    err = capsys.readouterr().err
    assert f"AWS error ({type(error).__name__})" in err
    assert "boom" in err
    assert "aws login" not in err


def test_a_cancelled_batch_stops_the_morning_and_says_to_run_it_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app, "run_morning", _raising(BatchCancelledError("batch x cancelled")))
    assert app.main(["run"]) == 1
    err = capsys.readouterr().err
    assert "batch x cancelled" in err
    assert "has no --resume option" in err


def test_an_error_that_is_not_aws_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "run_morning", _raising(RuntimeError("bug")))
    with pytest.raises(RuntimeError):
        app.main(["run"])


def test_a_second_morning_is_refused_while_the_first_holds_the_lock(
    calls: _Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = Settings().runs_dir
    runs.mkdir(parents=True)
    with (runs / "live.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert app.main(["run"]) == 1
    assert calls.deps is None  # nothing else was done
    assert "another morning" in capsys.readouterr().err
    assert app.main(["run"]) == 0  # the lock is free again
