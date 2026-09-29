"""scripts/sealed_report.py: the prediction of decision 0098 item 7, scored."""

from dataclasses import replace
from pathlib import Path

import pytest
from scripts import sealed_report as sr
from tests.test_occurrence_misses import _SCORES, _case

from ntsb_probable_cause.scoring.records import write_jsonl


def test_prediction_lines_score_each_part() -> None:
    lines = sr.prediction_lines(dev_top1=0.33, sealed_top1=0.30, misread_moved=False)
    assert "top-1 on dev-400 between 30% and 36%: 33.0% -- met" in lines
    assert "sealed below dev-400 by less than 5 points: 3.0 points -- met" in lines
    assert "misread share did not move beyond label churn: met" in lines


def test_prediction_lines_report_a_miss_plainly() -> None:
    lines = sr.prediction_lines(dev_top1=0.25, sealed_top1=0.26, misread_moved=None)
    assert "top-1 on dev-400 between 30% and 36%: 25.0% -- not met" in lines
    assert "sealed below dev-400 by less than 5 points: -1.0 points -- not met" in lines
    assert "misread share: not scored (the narrative label was not validated)" in lines


def _write(runs: Path, run_id: str, top1: list[bool], recall: list[float]) -> None:
    cases = [
        _case(f"C{i}", ("452240",), ("452240",)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=t, finding_recall_10=r)}
        )
        for i, (t, r) in enumerate(zip(top1, recall, strict=True))
    ]
    write_jsonl(runs / run_id / "cases.jsonl", cases)


def test_main_prints_both_runs_and_the_prediction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    _write(runs, "dev-run", [True, True, False, False], [0.5, 0.5, 0.0, 0.0])
    _write(runs, "sealed-run", [True, False, False, False], [0.5, 0.0, 0.0, 0.0])
    out = tmp_path / "sealed.txt"
    assert (
        sr.main(
            [
                "--dev",
                "dev-run",
                "--sealed",
                "sealed-run",
                "--misread-moved",
                "unvalidated",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "dev-400 (dev-run): top-1 50.0%" in text
    assert "dev-seal-400 (sealed-run): top-1 25.0%" in text
    assert "finding recall@10 25.0%" in text
    assert "top-1 on dev-400 between 30% and 36%: 50.0% -- not met" in text
    assert out.read_text() == text


def test_a_held_out_run_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    with pytest.raises(SystemExit, match="held-out"):
        sr.main(["--dev", "x-heldout-400-B", "--sealed", "y", "--misread-moved", "unvalidated"])
