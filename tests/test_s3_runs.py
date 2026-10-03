"""scripts/_s3_runs.py: the shared run loader's one write path (S3.2 Task 9).

``write_result`` refuses a dirty tree under ``docs/results/``. The repository's state is faked.
"""

import subprocess
from pathlib import Path

import pytest
from scripts import _s3_runs as sr


def test_a_result_under_docs_results_is_refused_from_a_dirty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sr, "changed_files", lambda: ["src/ntsb_probable_cause/x.py"])
    with pytest.raises(SystemExit, match="1 uncommitted change"):
        sr.write_result("prog", Path("docs/results/a.txt"), "text")
    assert not Path("docs/results/a.txt").exists()


def test_the_free_readings_own_outputs_do_not_make_the_tree_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sr,
        "changed_files",
        lambda: ["docs/results/s32-cap-check-dev.txt"],
    )
    sr.write_result("prog", Path("docs/results/a.txt"), "text")
    assert Path("docs/results/a.txt").read_text() == "text\n"


def test_an_uncommitted_curve_edit_is_refused_except_for_the_calibration_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sr, "changed_files", lambda: [sr.CURVE_PATH])
    with pytest.raises(SystemExit, match="1 uncommitted change"):
        sr.write_result("prog", Path("docs/results/a.txt"), "text")
    assert not Path("docs/results/a.txt").exists()
    sr.write_result("s32_calibration", Path("docs/results/a.txt"), "text", own_curve=True)
    assert Path("docs/results/a.txt").read_text() == "text\n"


def test_a_result_elsewhere_is_written_whatever_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def boom() -> list[str]:
        raise AssertionError("git must not be asked")

    monkeypatch.setattr(sr, "changed_files", boom)
    sr.write_result("prog", tmp_path / "elsewhere" / "a.txt", "text")
    assert (tmp_path / "elsewhere" / "a.txt").read_text() == "text\n"


def test_changed_files_reads_git_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Done:
        stdout = " M a.py\n?? docs/results/b.txt\nR  old.py -> new.py\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert sr.changed_files() == ["a.py", "docs/results/b.txt", "new.py"]


def test_the_early_refusal_is_the_same_rule_as_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sr, "changed_files", lambda: ["src/ntsb_probable_cause/x.py"])
    with pytest.raises(SystemExit, match="1 uncommitted change"):
        sr.refuse_unclean_results("prog", Path("docs/results/a.txt"))
    sr.refuse_unclean_results("prog", tmp_path / "elsewhere" / "a.txt")  # not under results
