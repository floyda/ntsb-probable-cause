"""``ntsb-record run``: the entrypoint's control flow (Task 10).

``run_night`` itself is fully exercised in ``tests/test_recorder_run.py``; every test here
monkeypatches ``apps.recorder.__main__.run_night`` so it never touches the network, and asserts
only what the app *around* it does: which store path it opens, whether it pulls/pushes, and how
it reports the three failure shapes (a bad commit identity, a missing API key, an unexpected
exception from the night itself).
"""

import logging
import subprocess
from pathlib import Path

import apps.recorder.__main__ as app
import pytest

from ntsb_probable_cause.recorder.run import NightInputs
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import RunSummary, Store
from ntsb_probable_cause.store.sync import Location


def _fake_summary() -> RunSummary:
    return RunSummary(
        cases_polled=1,
        cases_changed=0,
        new_documents=0,
        failures=0,
        suspected_renumbers=0,
        minutes=0.1,
    )


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A clean environment per test: a real API key, a local store under ``tmp_path``, and a
    real, fixed commit SHA -- so a test that does not care about one of these three things
    still runs (git works in this checkout) without touching the developer's real .env."""
    monkeypatch.setenv("NTSB_API_KEY", "test-key")
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_STORE", str(tmp_path / "data" / "recorder.sqlite"))
    monkeypatch.delenv("NTSB_COMMIT_SHA", raising=False)


def test_dry_run_completes_and_does_not_push(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[NightInputs] = []
    pushes: list[Location] = []

    def _fake_run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
        calls.append(inputs)
        return _fake_summary()

    monkeypatch.setattr(app, "run_night", _fake_run_night)
    monkeypatch.setattr(app, "push", lambda local, location, **_: pushes.append(location))

    assert app.main(["run", "--dry-run"]) == 0
    assert len(calls) == 1
    assert pushes == []


def test_a_completed_run_pushes_when_not_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pushed: list[tuple[Path, Location]] = []

    def _fake_run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
        return _fake_summary()

    def _fake_push(local: Path, location: Location, **_: object) -> None:
        pushed.append((local, location))

    monkeypatch.setattr(app, "run_night", _fake_run_night)
    monkeypatch.setattr(app, "push", _fake_push)

    assert app.main(["run"]) == 0
    assert len(pushed) == 1
    local, location = pushed[0]
    assert location.raw == str(tmp_path / "data" / "recorder.sqlite")
    assert local == Path(location.raw)  # a local store: the local path IS the store


def test_run_night_exception_returns_1_does_not_push_and_closes_the_store(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    closed: list[Store] = []
    pushed: list[Location] = []
    real_close = Store.close

    def _closing_close(self: Store) -> None:
        closed.append(self)
        real_close(self)

    def _fake_run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
        raise ValueError("something inside the night broke")

    monkeypatch.setattr(app, "run_night", _fake_run_night)
    monkeypatch.setattr(app, "push", lambda local, location, **_: pushed.append(location))
    monkeypatch.setattr(Store, "close", _closing_close)

    with caplog.at_level(logging.ERROR, logger="apps.recorder.__main__"):
        assert app.main(["run"]) == 1

    assert pushed == []
    assert len(closed) == 1
    assert "run failed" in caplog.text
    assert "ValueError" in caplog.text  # the traceback landed in the log, not just a bare line


def test_explicit_commit_sha_is_used_and_git_is_never_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NTSB_COMMIT_SHA", "deadbee")
    captured: list[NightInputs] = []

    def _fake_run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
        captured.append(inputs)
        return _fake_summary()

    def _git_must_not_run() -> tuple[str, bool]:
        raise AssertionError("git must not be called when NTSB_COMMIT_SHA is set")

    monkeypatch.setattr(app, "run_night", _fake_run_night)
    monkeypatch.setattr(app, "commit_state", _git_must_not_run)
    monkeypatch.setattr(app, "push", lambda *a, **k: None)

    assert app.main(["run", "--dry-run"]) == 0
    assert captured[0].commit_sha == "deadbee"
    assert captured[0].dirty is False


def test_unset_commit_sha_falls_back_to_git(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[NightInputs] = []

    def _fake_run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
        captured.append(inputs)
        return _fake_summary()

    def _fake_commit_state() -> tuple[str, bool]:
        return "abc1234", True

    monkeypatch.setattr(app, "run_night", _fake_run_night)
    monkeypatch.setattr(app, "commit_state", _fake_commit_state)
    monkeypatch.setattr(app, "push", lambda *a, **k: None)

    assert app.main(["run", "--dry-run"]) == 0
    assert captured[0].commit_sha == "abc1234"
    assert captured[0].dirty is True


def test_git_failure_with_no_commit_sha_exits_1_and_never_fabricates_a_sha(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _broken_git() -> tuple[str, bool]:
        raise subprocess.CalledProcessError(128, ["git", "rev-parse"])

    called: list[bool] = []

    def _run_night_must_not_run(*_a: object, **_k: object) -> RunSummary:
        called.append(True)
        return _fake_summary()

    monkeypatch.setattr(app, "commit_state", _broken_git)
    monkeypatch.setattr(app, "run_night", _run_night_must_not_run)

    assert app.main(["run"]) == 1
    assert called == []
    err = capsys.readouterr().err
    assert "commit" in err
    assert "git" in err.lower()


def test_no_api_key_gives_a_clean_exit_and_never_prints_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NTSB_API_KEY", raising=False)

    called: list[bool] = []

    def _run_night_must_not_run(*_a: object, **_k: object) -> RunSummary:
        called.append(True)
        return _fake_summary()

    monkeypatch.setattr(app, "run_night", _run_night_must_not_run)

    assert app.main(["run"]) == 1
    assert called == []
    out, err = capsys.readouterr()
    combined = out + err
    assert "key=" not in combined
    assert "test-key" not in combined


def test_s3_store_pulls_and_pushes_a_work_file_under_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NTSB_STORE", "s3://a-bucket/recorder.sqlite")
    data_dir = tmp_path / "data"

    pulled: list[tuple[Location, Path]] = []
    pushed: list[tuple[Path, Location]] = []

    def _fake_pull(location: Location, local: Path, **_: object) -> None:
        pulled.append((location, local))

    def _fake_push(local: Path, location: Location, **_: object) -> None:
        pushed.append((local, location))

    def _fake_run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
        return _fake_summary()

    monkeypatch.setattr(app, "pull", _fake_pull)
    monkeypatch.setattr(app, "push", _fake_push)
    monkeypatch.setattr(app, "run_night", _fake_run_night)

    assert app.main(["run"]) == 0
    assert pulled[0][0].raw == "s3://a-bucket/recorder.sqlite"
    assert pulled[0][1] == data_dir / "recorder-work.sqlite"
    assert pushed[0][0] == data_dir / "recorder-work.sqlite"


def test_verbose_flag_is_forwarded_to_run_night(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def _fake_run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
        seen.append(verbose)
        return _fake_summary()

    monkeypatch.setattr(app, "run_night", _fake_run_night)
    monkeypatch.setattr(app, "push", lambda *a, **k: None)

    assert app.main(["run", "--verbose"]) == 0
    assert seen == [True]


def test_local_path_helper_uses_data_dir_only_for_s3(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    local_location = Location(str(tmp_path / "somewhere" / "r.sqlite"))
    s3_location = Location("s3://bucket/key")

    assert app._local_path(settings, local_location) == Path(local_location.raw)
    assert app._local_path(settings, s3_location) == settings.data_dir / "recorder-work.sqlite"
