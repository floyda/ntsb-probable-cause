"""Tests for the S3.3 fingerprint continuity script: offline, no git, no subprocess."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
