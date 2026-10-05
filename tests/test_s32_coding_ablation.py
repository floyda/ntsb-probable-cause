"""scripts/s32_coding_ablation.py: the dev-400 coding ablation and prediction 6 (Task 11, §11).

Made-up run folders under ``tmp_path``; no real data. Offline.
"""

from pathlib import Path

import pytest
from scripts import s32_coding_ablation as ab
from tests.test_s3_noise_floor import _IDS, _failed, _scored, _spec_json, _write

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult

NOISE_A, NOISE_B = ab.NOISE_RUNS
ABLATION = "20261005T010000-abc1234-dev-400-C"


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, with ``dev-400`` taken to be the made-up ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _cases(hits: int, *, fatal_first: int = 0) -> list[CaseResult]:
    """Twenty cases, the first ``hits`` of them right; the first ``fatal_first`` fatal."""
    return [_scored(c, top1=n < hits, fatal=n < fatal_first) for n, c in enumerate(_IDS)]


def _put(
    runs: Path,
    ablation: list[CaseResult],
    noise: tuple[list[CaseResult], list[CaseResult]],
    *,
    without: list[str] | None = None,
) -> None:
    _write(
        runs,
        ABLATION,
        ablation,
        spec=_spec_json(
            [c.case_id for c in ablation], without=["coding"] if without is None else without
        ),
    )
    _write(runs, NOISE_A, noise[0])
    _write(runs, NOISE_B, noise[1])


def _args() -> list[str]:
    return [ABLATION, NOISE_A, NOISE_B]


def test_prediction_6_is_met_when_both_top_1_intervals_are_below_zero(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _put(runs, _cases(0), (_cases(20), _cases(20)))
    assert ab.main(_args()) == 0
    out = capsys.readouterr().out
    assert "prediction 6: met" in out
    assert "occurrence top-1, all: ablation - noise = -100.0 points" in out


def test_prediction_6_is_not_met_when_one_interval_reaches_zero(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # against noise b the ablation is level: the interval is [0, 0], and its top is not below 0
    _put(runs, _cases(0), (_cases(20), _cases(0)))
    ab.main(_args())
    assert "prediction 6: not met" in capsys.readouterr().out


def test_prediction_6_is_not_met_when_the_ablation_is_better(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _put(runs, _cases(20), (_cases(0), _cases(0)))
    ab.main(_args())
    assert "prediction 6: not met" in capsys.readouterr().out


def test_the_report_reads_each_metric_overall_and_by_fatal(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _put(runs, _cases(5, fatal_first=4), (_cases(10, fatal_first=4), _cases(10, fatal_first=4)))
    ab.main(_args())
    out = capsys.readouterr().out
    for name in (NOISE_A, NOISE_B):
        assert f"against {name}" in out
    for metric in ("occurrence top-1", "occurrence top-3", "finding recall@10"):
        for label in ("all", "fatal", "non-fatal"):
            assert f"{metric}, {label}:" in out
    assert "both answered" in out


def test_the_report_prints_provenance_the_ablation_line_and_the_format_gate(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _put(runs, _cases(0), (_cases(20), _cases(20)))
    ab.main(_args())
    out = capsys.readouterr().out
    assert f"run {ABLATION} [complete]" in out
    assert "ablation: without=coding" in out
    assert "format gate, run ablation: PASS" in out


def test_a_guard_refusal_is_removed_and_a_coding_failure_counts_wrong(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ablation = [
        _failed(_IDS[0], f"leak: {_IDS[0]}: verbatim"),
        _failed(_IDS[1], "failed: coding"),
        *_cases(0)[2:],
    ]
    _put(runs, ablation, (_cases(20), _cases(20)))
    ab.main(_args())
    out = capsys.readouterr().out
    assert "n=19" in out  # one case removed from both
    assert "-100.0 points" in out  # the failed case counts as wrong


def test_the_output_file_holds_no_case_id(runs: Path, tmp_path: Path) -> None:
    ablation = [_failed(_IDS[0], f"leak: {_IDS[0]}: verbatim"), *_cases(0)[1:]]
    _put(runs, ablation, (_cases(20), _cases(20)))
    out_path = tmp_path / "out" / "ablation.txt"
    assert ab.main([*_args(), "--out", str(out_path)]) == 0
    assert "ZQX" not in out_path.read_text()


def test_a_run_without_the_coding_ablation_is_refused(runs: Path) -> None:
    _put(runs, _cases(0), (_cases(20), _cases(20)), without=[])
    with pytest.raises(SystemExit, match="without"):
        ab.main(_args())


def test_other_noise_runs_are_refused(runs: Path) -> None:
    _put(runs, _cases(0), (_cases(20), _cases(20)))
    with pytest.raises(SystemExit, match="noise-floor"):
        ab.main([ABLATION, NOISE_A, ABLATION])


def test_a_held_out_run_is_refused(runs: Path) -> None:
    with pytest.raises(SystemExit, match="held-out"):
        ab.main(["20261005T010000-abc1234-heldout-400-C", NOISE_A, NOISE_B])


def test_an_ablation_run_of_a_different_loop_is_refused(runs: Path) -> None:
    _write(
        runs,
        ABLATION,
        _cases(0),
        spec=_spec_json(list(_IDS), without=["coding"], agent_prompt_version="s3-v1+other"),
    )
    _write(runs, NOISE_A, _cases(20))
    _write(runs, NOISE_B, _cases(20))
    with pytest.raises(SystemExit, match="agent_prompt_version"):
        ab.main(_args())


@pytest.mark.parametrize(
    "change",
    [
        {"model": "other/model"},
        {"reasoning_effort": "high"},
        {"max_output_tokens": 2000},
        {"guidance": ["r3-loc-stall"]},
        {"stats": "s27"},
    ],
)
def test_an_ablation_with_other_settings_than_the_noise_runs_is_refused(
    runs: Path, change: dict[str, object]
) -> None:
    key = next(iter(change))
    _write(
        runs,
        ABLATION,
        _cases(0),
        spec=_spec_json(list(_IDS), without=["coding"], **change),
    )
    _write(runs, NOISE_A, _cases(20))
    _write(runs, NOISE_B, _cases(20))
    with pytest.raises(SystemExit, match=key):
        ab.main(_args())
