"""scripts/round_comparisons.py: decision 0106's and Round 6's cited numbers, from code."""

from dataclasses import replace
from pathlib import Path

import pytest
from scripts import round_comparisons as rc
from tests.test_occurrence_misses import _SCORES, _case, _write_run  # shared builders

from ntsb_probable_cause.scoring.records import CaseResult, write_jsonl


def _cases(top1: list[bool], recall: list[float]) -> list[CaseResult]:
    return [
        _case(f"C{i}", ("452240",), ("452240",)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=t, finding_recall_10=r)}
        )
        for i, (t, r) in enumerate(zip(top1, recall, strict=True))
    ]


def test_build_reproduces_each_runs_own_score_and_round_6_pairings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    n = 100
    all_ids = (rc.B_V1, rc.REPEAT, rc.ROUND2, rc.ROUND3, rc.ROUND4, rc.ROUND5, rc.ROUND6)
    for run_id in all_ids:
        folder = _write_run(runs_dir, run_id)
        write_jsonl(folder / "cases.jsonl", _cases([True] * 40 + [False] * 60, [0.5] * n))
    text = rc.build()
    assert "## Each run's own checked score" in text
    assert f"- B-v1 ({rc.B_V1}): top-1 40.0%" in text
    assert f"- Round 6 ({rc.ROUND6}): top-1 40.0%" in text
    assert "finding recall@10 50.0%" in text
    assert "## Round 6 paired against" in text
    assert "- Round 3 (reference): top-1 +0.0%" in text
    assert "- Round 4: top-1 +0.0%" in text
    assert "- Round 5: top-1 +0.0%" in text
    assert "- the repeat: top-1 +0.0%" in text
    assert "## Decision 0105 item 4 supplement (Round 6 against Round 3)" in text
    assert "cases whose NTSB sequence holds a code decision 0105 added: 0" in text


def test_main_prints_and_writes_the_comparisons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    all_ids = (rc.B_V1, rc.REPEAT, rc.ROUND2, rc.ROUND3, rc.ROUND4, rc.ROUND5, rc.ROUND6)
    for run_id in all_ids:
        folder = _write_run(runs_dir, run_id)
        write_jsonl(folder / "cases.jsonl", _cases([True, False], [1.0, 0.0]))
    out = tmp_path / "results" / "comparisons.txt"
    assert rc.main(["--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert out.read_text() == printed
    assert "S2.7 round comparisons" in printed


def test_a_run_recorded_on_a_held_out_sample_is_refused_before_its_cases_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    _write_run(runs_dir, rc.B_V1, sample="heldout-400")  # no cases.jsonl written
    with pytest.raises(SystemExit, match="held-out run"):
        rc.build()
