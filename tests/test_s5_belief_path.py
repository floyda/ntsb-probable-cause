"""scripts/exploratory/s5_belief_path.py: decision 0186's counts, over made-up held-out runs.

The world is the held-out diagnosis's own (``tests/test_s32_heldout_diagnosis.py``), so its
answers can be worked out by hand from that module's docstring. Of 20 cases the loop answers 19
(case 19 fails). H0 is right on 0, 1 and 11. After reading: cases 0-14 record an H1, right on 0,
11, 12 and 13; cases 15-18 are offered nothing and record no belief after a read choice, so after
reading is their H0 (wrong). The answer is right on 0, 11 and 12.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from scripts import _s3_runs as sr
from scripts.exploratory import s5_belief_path as bp
from tests.test_s3_noise_floor import _IDS
from tests.test_s32_heldout_diagnosis import TEXT, _always, _argv, build, runs

__all__ = ["runs"]  # the fixture, imported for pytest

# The diagnosis's two lines this world's reading must agree with.
_DIAGNOSIS = (
    "- H0 right 3 of 19 (15.8%); answer right 3 of 19 (15.8%)\n"
    "- the loop, last hypothesis before coding -> answer: 19 cases; first code changed on 1 of 19 "
    "(5.3%); fixes 0, breaks 1 (net -1); score changed with the first code kept 0\n"
)


def _before_the_reading(path: Path) -> bool:
    """Everything committed but the reading's own result, as before its one run."""
    return path != bp.RESULT


def _read(
    capsys: pytest.CaptureFixture[str],
    diagnosis: str = _DIAGNOSIS,
    is_committed: Callable[[Path], bool] = _before_the_reading,
) -> str:
    assert bp.main(_argv(), is_committed=is_committed, diagnosis=lambda: diagnosis) == 0
    return capsys.readouterr().out


def test_the_three_checkpoints_and_the_moves(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = _read(capsys)
    assert "cases: the 19 the loop answered; left out, no belief before reading: 0" in out
    assert "(after reading is before reading): 4" in out
    assert "- before reading: 3\n- after reading: 4\n- the answer: 3" in out
    assert (
        "before reading -> after reading: stayed right 2, fixed 2, broken 1, stayed wrong 14" in out
    )
    assert "after reading -> the answer: stayed right 3, fixed 0, broken 1, stayed wrong 15" in out


def test_it_prints_these_and_no_others(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 0186 item 4: the right counts and the two moves, and nothing else.
    build(runs)
    out = _read(capsys)
    counted = [line for line in out.splitlines() if any(ch.isdigit() for ch in line)]
    allowed = (
        "S5 question 7",
        "the loop: ",
        "cases: ",
        "cases with no belief after a read choice",
        "right, of ",
        "- before reading: ",
        "- after reading: ",
        "- the answer: ",
        "before reading -> after reading: ",
        "after reading -> the answer: ",
        "Exploratory (decision 0059)",
        "checked against docs/results/s32-heldout-diagnosis.txt",
    )
    for line in counted:
        assert line.startswith(allowed), line


def test_no_case_number_or_model_text_appears(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = _read(capsys)
    assert TEXT not in out
    for case_id in _IDS:
        assert case_id not in out


def test_a_reading_that_disagrees_with_the_diagnosis_writes_nothing(
    runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 0186 item 5.
    build(runs)
    out = tmp_path / "result.txt"
    wrong = _DIAGNOSIS.replace("fixes 0, breaks 1", "fixes 0, breaks 2")
    with pytest.raises(SystemExit, match="does not match"):
        bp.main(
            [*_argv(), "--out", str(out)],
            is_committed=_before_the_reading,
            diagnosis=lambda: wrong,
        )
    assert not out.exists()


def test_an_uncommitted_decision_0186_is_refused_before_any_run_is_read(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No run folder exists: a refusal after reading would fail differently.
    with pytest.raises(SystemExit, match="0186"):
        _read(capsys, is_committed=lambda path: path not in {bp.DECISION, bp.RESULT})


def test_a_dirty_tree_is_refused_before_any_run_is_read(
    runs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sr, "changed_files", lambda: ["scripts/exploratory/s5_belief_path.py"])
    with pytest.raises(SystemExit, match="uncommitted"):
        _read(capsys)


def test_a_second_reading_is_refused_once_the_result_is_committed(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Decision 0186 allows one reading. No run folder exists, so a refusal after reading would
    # fail differently.
    with pytest.raises(SystemExit, match="one reading"):
        _read(capsys, is_committed=_always)
