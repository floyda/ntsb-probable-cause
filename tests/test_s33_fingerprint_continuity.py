"""Tests for the S3.3 fingerprint continuity script: offline, no git, no subprocess."""

import shutil
import subprocess
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from scripts import s33_fingerprint_continuity as cont

from ntsb_probable_cause.agent.version import SOURCE_LABEL_V1

FROZEN_TREE = Path("/frozen")
HEAD_TREE = cont.REPO_ROOT
HEX_A = "c6497367ee94" + "0" * 52
HEX_B = "1234567890ab" + "f" * 52


@contextmanager
def _frozen_tree() -> Iterator[Path]:
    yield FROZEN_TREE


def _run(tmp_path: Path, hexes: dict[Path, str]) -> tuple[int, str]:
    out = tmp_path / "out.txt"

    def runner(tree: Path) -> str:
        return hexes[tree]

    code = cont.main(
        ["--out", str(out)], checkout=_frozen_tree, runner=runner, head=lambda: "abc1234"
    )
    return code, out.read_text()


def test_match_writes_every_value_and_returns_zero(tmp_path: Path) -> None:
    code, text = _run(tmp_path, {FROZEN_TREE: HEX_A, HEAD_TREE: HEX_A})
    assert code == 0
    assert "fd6053f" in text
    assert SOURCE_LABEL_V1 in text
    assert text.count("c6497367ee94") >= 2
    assert HEX_A in text
    assert "abc1234" in text
    assert "match: yes" in text


def test_mismatch_writes_no_and_returns_one(tmp_path: Path) -> None:
    code, text = _run(tmp_path, {FROZEN_TREE: HEX_A, HEAD_TREE: HEX_B})
    assert code == 1
    assert "match: no" in text
    assert HEX_A in text
    assert HEX_B in text


def test_failure_on_frozen_commit_returns_two_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"

    def runner(tree: Path) -> str:
        raise cont.RunFailedError("ImportError: no module")

    code = cont.main(["--out", str(out)], checkout=_frozen_tree, runner=runner, head=lambda: "x")
    assert code == 2
    assert not out.exists()


def _failing_checkout(exc: Exception) -> Callable[[], AbstractContextManager[Path]]:
    @contextmanager
    def checkout() -> Iterator[Path]:
        raise exc
        yield FROZEN_TREE  # pragma: no cover

    return checkout


@pytest.mark.parametrize(
    "exc",
    [subprocess.CalledProcessError(128, ["git"], stderr="bad commit"), FileNotFoundError("x")],
)
def test_setup_failure_returns_two_and_writes_nothing(
    tmp_path: Path, exc: Exception, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.txt"
    code = cont.main(
        ["--out", str(out)],
        checkout=_failing_checkout(exc),
        runner=lambda tree: HEX_A,
        head=lambda: "x",
    )
    assert code == 2
    assert not out.exists()
    assert "fd6053f" in capsys.readouterr().err


def test_head_run_failure_returns_two_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.txt"

    def runner(tree: Path) -> str:
        if tree == FROZEN_TREE:
            return HEX_A
        raise cont.RunFailedError("boom on head")

    code = cont.main(["--out", str(out)], checkout=_frozen_tree, runner=runner, head=lambda: "x")
    assert code == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "HEAD" in err
    assert "boom on head" in err


def _recording_git(calls: list[tuple[str, ...]]) -> Callable[..., str]:
    def git(*args: str) -> str:
        calls.append(args)
        return ""

    return git


def test_cleanup_order_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "copyfile", lambda src, dst: None)
    calls: list[tuple[str, ...]] = []
    with cont.frozen_checkout(git=_recording_git(calls)) as tree:
        assert calls[0][:3] == ("worktree", "add", "--detach")
        assert calls[0][-1] == "fd6053f"
        added = calls[0][3]
        assert str(tree) == added
    assert [c[:2] for c in calls] == [
        ("worktree", "add"),
        ("worktree", "remove"),
        ("worktree", "prune"),
    ]
    assert calls[1] == ("worktree", "remove", "--force", added)


def test_cleanup_order_when_body_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "copyfile", lambda src, dst: None)
    calls: list[tuple[str, ...]] = []
    with pytest.raises(RuntimeError), cont.frozen_checkout(git=_recording_git(calls)):
        raise RuntimeError("body")
    assert [c[:2] for c in calls] == [
        ("worktree", "add"),
        ("worktree", "remove"),
        ("worktree", "prune"),
    ]


def test_cleanup_runs_when_copy_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_copy(src: object, dst: object) -> None:
        raise OSError("no")

    monkeypatch.setattr(shutil, "copyfile", bad_copy)
    calls: list[tuple[str, ...]] = []
    with pytest.raises(OSError, match="no"), cont.frozen_checkout(git=_recording_git(calls)):
        pass
    assert [c[:2] for c in calls] == [
        ("worktree", "add"),
        ("worktree", "remove"),
        ("worktree", "prune"),
    ]
