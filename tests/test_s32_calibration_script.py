"""scripts/s32_calibration.py: the curve fitted on the noise-floor runs and frozen (Task 9, §8.2).

Made-up run folders under ``tmp_path``; no real data. Offline.
"""

import json
from pathlib import Path

import pytest
from scripts import s32_calibration as sc
from tests.test_s3_noise_floor import (
    _IDS,
    _RUN_A,
    _RUN_B,
    _failed,
    _scored,
    _write,
)

from ntsb_probable_cause.scoring import calibration, samples
from ntsb_probable_cause.scoring.records import CaseResult


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, with ``dev-400`` taken to be the made-up ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _rising(ids: tuple[str, ...]) -> list[CaseResult]:
    """A run where a higher stated confidence is right more often: 0.2 rarely, 0.8 usually."""
    out = []
    for n, case_id in enumerate(ids):
        high = n % 2 == 0
        right = (n % 5 != 0) if high else (n % 5 == 0)
        out.append(_scored(case_id, top1=right, confidence=0.8 if high else 0.2))
    return out


def _both(runs_dir: Path, a: list[CaseResult], b: list[CaseResult]) -> None:
    _write(runs_dir, _RUN_A, a)
    _write(runs_dir, _RUN_B, b)


def test_the_curve_is_written_and_loads_back(
    runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _both(runs, _rising(_IDS), _rising(_IDS))
    curve_path = tmp_path / "curve" / "calibration_s3.json"
    assert sc.main([_RUN_A, _RUN_B, "--curve", str(curve_path)]) == 0
    stored = json.loads(curve_path.read_text())
    assert sorted(stored) == ["commit", "fitted", "intercept", "n", "runs", "slope"]
    assert stored["n"] == 40
    assert stored["runs"] == [_RUN_A, _RUN_B]
    assert curve_path.read_text().startswith('{\n  "commit"')  # sorted keys, 2-space indent
    curve = calibration.load_curve(curve_path)
    assert curve.slope > 0
    assert curve.intercept == stored["intercept"]
    out = capsys.readouterr().out
    assert f"intercept {stored['intercept']:.4f}, slope {stored['slope']:.4f}" in out
    assert "answers pooled: 40" in out
    for stated in ("0.1", "0.3", "0.5", "0.7", "0.9"):
        assert f"stated {stated}: " in out
    assert "ZQX" not in out


def test_failed_cases_have_no_answer_and_are_left_out(runs: Path, tmp_path: Path) -> None:
    a = [*_rising(_IDS[:19]), _failed(_IDS[19], "failed: coding")]
    _both(runs, a, _rising(_IDS))
    curve_path = tmp_path / "c.json"
    sc.main([_RUN_A, _RUN_B, "--curve", str(curve_path)])
    assert json.loads(curve_path.read_text())["n"] == 39


def test_an_abstained_answer_is_wrong(runs: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    a = [_scored(_IDS[0], top1=False, confidence=0.9, abstain=True), *_rising(_IDS[1:])]
    _both(runs, a, _rising(_IDS))
    sc.main([_RUN_A, _RUN_B, "--curve", str(tmp_path / "c.json")])
    assert "answers pooled: 40" in capsys.readouterr().out


def test_an_existing_curve_is_not_overwritten(runs: Path, tmp_path: Path) -> None:
    _both(runs, _rising(_IDS), _rising(_IDS))
    curve_path = tmp_path / "c.json"
    curve_path.write_text('{"intercept": 0.0, "slope": 1.0}')
    with pytest.raises(SystemExit, match="frozen"):
        sc.main([_RUN_A, _RUN_B, "--curve", str(curve_path)])
    assert curve_path.read_text() == '{"intercept": 0.0, "slope": 1.0}'
    assert sc.main([_RUN_A, _RUN_B, "--curve", str(curve_path), "--refit"]) == 0
    assert json.loads(curve_path.read_text())["n"] == 40


def test_a_curve_that_does_not_rise_is_not_written(runs: Path, tmp_path: Path) -> None:
    # high stated confidence is wrong, low is right: the slope is negative
    flipped = [
        _scored(i, top1=(n % 2 == 1) != (n % 5 == 0), confidence=0.8 if n % 2 == 0 else 0.2)
        for n, i in enumerate(_IDS)
    ]
    _both(runs, flipped, flipped)
    curve_path = tmp_path / "c.json"
    with pytest.raises(SystemExit, match="must rise"):
        sc.main([_RUN_A, _RUN_B, "--curve", str(curve_path)])
    assert not curve_path.exists()


def test_the_results_file_has_bands_and_the_abstain_count(runs: Path, tmp_path: Path) -> None:
    _both(runs, _rising(_IDS), _rising(_IDS))
    out_path = tmp_path / "out" / "cal.txt"
    sc.main([_RUN_A, _RUN_B, "--curve", str(tmp_path / "c.json"), "--out", str(out_path)])
    text = out_path.read_text()
    assert "<0.4: " in text
    assert "≥0.8: " in text
    assert f"below {calibration.ABSTAIN_BELOW}" in text
    assert "ZQX" not in text


def test_only_the_calibration_script_may_leave_the_curve_uncommitted(
    runs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _both(runs, _rising(_IDS), _rising(_IDS))
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(sc, "write_result", lambda *a, **k: seen.append(k))
    sc.main([_RUN_A, _RUN_B, "--curve", str(tmp_path / "c.json"), "--out", str(tmp_path / "o.txt")])
    assert seen == [{"own_curve": True}]
