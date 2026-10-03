"""scripts/s32_noise.py: the noise-floor pair under the claim's rule (S3.2 Task 9, spec §7.3).

Made-up run folders under ``tmp_path``; no real data. Offline.
"""

from pathlib import Path

import pytest
from scripts import s32_noise as sn
from tests.test_s3_noise_floor import (
    _IDS,
    _LEAK,
    _RUN_A,
    _RUN_B,
    _failed,
    _scored,
    _write,
)

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, with ``dev-400`` taken to be the made-up ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _pair(a: list[CaseResult], b: list[CaseResult], runs_dir: Path) -> None:
    _write(runs_dir, _RUN_A, a)
    _write(runs_dir, _RUN_B, b)


def _fill(head_a: list[CaseResult], head_b: list[CaseResult]) -> tuple[list, list]:  # type: ignore[type-arg]
    """Pad two runs to the twenty ids with the same wrong-and-answered cases."""
    n = len(head_a)
    rest = [_scored(i) for i in _IDS[n:]]
    return [*head_a, *rest], [*head_b, *rest]


def test_a_guard_refusal_in_one_run_removes_the_case_from_both(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = _fill(
        [_scored(_IDS[0], top1=True), _failed(_IDS[1], f"leak: {_IDS[1]}: {_LEAK}")],
        [_scored(_IDS[0], top1=False), _scored(_IDS[1], top1=True)],
    )
    _pair(a, b, runs)
    assert sn.main([_RUN_A, _RUN_B]) == 0
    out = capsys.readouterr().out
    assert "guard refusals removed from both runs: 1" in out
    assert "occurrence top-1, all: " in out
    assert "n=19" in out  # 20 cases, one removed


def test_a_coding_failure_counts_as_a_miss(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = _fill(
        [_scored(_IDS[0], top1=True), _failed(_IDS[1], "failed: coding")],
        [_scored(_IDS[0], top1=True), _scored(_IDS[1], top1=True)],
    )
    _pair(a, b, runs)
    assert sn.main([_RUN_A, _RUN_B]) == 0
    out = capsys.readouterr().out
    assert "failures counted wrong: run a 1, run b 0" in out
    # paired on 20 cases: a is 1 right (+0), b is 2 right -> -1/20 = -5.0 points
    assert "occurrence top-1, all: a - b = -5.0 points" in out
    assert "n=20" in out
    # on the 19 cases both answered the difference is 0
    assert "both answered +0.0 points" in out
    assert "n=19" in out


def test_the_difference_is_read_for_fatal_and_non_fatal(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = _fill(
        [_scored(_IDS[0], top1=True, fatal=True)],
        [_scored(_IDS[0], top1=False, fatal=True)],
    )
    _pair(a, b, runs)
    sn.main([_RUN_A, _RUN_B])
    out = capsys.readouterr().out
    assert "occurrence top-1, fatal: a - b = +100.0 points" in out
    assert "occurrence top-1, non-fatal: a - b = +0.0 points" in out
    assert "n=1" in out
    for metric in ("occurrence top-1", "occurrence top-3", "finding recall@10"):
        assert f"{metric}, all:" in out


def test_an_empty_slice_is_said_not_raised(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = _fill([_scored(_IDS[0])], [_scored(_IDS[0])])
    _pair(a, b, runs)
    sn.main([_RUN_A, _RUN_B])
    assert "fatal: no case is left to pair" in capsys.readouterr().out


def test_exactly_two_runs_are_taken(runs: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        sn.main([_RUN_A])
    assert raised.value.code == 2


def test_the_output_file_has_no_case_id(runs: Path, tmp_path: Path) -> None:
    a, b = _fill([_failed(_IDS[0], f"leak: {_IDS[0]}: {_LEAK}")], [_scored(_IDS[0])])
    _pair(a, b, runs)
    out_path = tmp_path / "out" / "noise.txt"
    assert sn.main([_RUN_A, _RUN_B, "--out", str(out_path)]) == 0
    assert "ZQX" not in out_path.read_text()


def test_runs_over_different_cases_are_refused(runs: Path) -> None:
    a, b = _fill([], [])
    _write(runs, _RUN_A, a)
    _write(runs, _RUN_B, [*b[:-1], _scored("ZQX999")])
    with pytest.raises(SystemExit):
        sn.main([_RUN_A, _RUN_B])
