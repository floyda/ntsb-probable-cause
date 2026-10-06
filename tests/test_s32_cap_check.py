"""scripts/s32_cap_check.py: cases whose coding the $0.15 cap cut short (S3.2 Task 9, spec §5).

Made-up run folders under ``tmp_path``; no real data. Offline.
"""

from pathlib import Path

import pytest
from scripts import s32_cap_check as cc
from tests.test_s3_noise_floor import (
    _IDS,
    _RUN_A,
    _RUN_B,
    _call,
    _plain,
    _write,
)

from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring import samples

_STOP = "STOP: the cap goes back to Andy before any S3.2 run (spec §5)"
_STANDS = "the $0.30 cap stands (decision 144)"


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, with ``dev-400`` taken to be the made-up ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _row(case_id: str, step: str, tool: str | None, index: int, **changes: object) -> AgentCall:
    row = _call(case_id, tool, index=index).model_copy(update={"step": step})
    return row.model_copy(update=changes)


def _coding(case_id: str, n: int, *, start: int = 0) -> list[AgentCall]:
    return [_row(case_id, "coding", "describe_codes", start + i) for i in range(n)]


def test_six_coding_calls_then_the_answer_is_the_ordinary_route() -> None:
    calls = [*_coding("c1", 6), _row("c1", "answer", "submit_answer", 6)]
    assert cc.cut_short(calls) == (1, 0)


def test_two_coding_calls_then_the_answer_is_a_forced_answer() -> None:
    calls = [*_coding("c1", 2), _row("c1", "answer", "submit_answer", 2)]
    assert cc.cut_short(calls) == (1, 1)


def test_submitting_the_answer_during_coding_is_not_counted() -> None:
    calls = [*_coding("c1", 2), _row("c1", "coding", "submit_answer", 2)]
    assert cc.cut_short(calls) == (1, 0)


def test_a_rejected_coding_call_does_not_count_towards_the_six() -> None:
    bad = [_row("c1", "coding", "describe_codes", 6 + i, protocol_error="bad") for i in range(2)]
    calls = [*_coding("c1", 5), *bad, _row("c1", "answer", "submit_answer", 8)]
    assert cc.cut_short(calls) == (1, 1)


def test_a_retried_answer_counts_the_case_once() -> None:
    calls = [
        *_coding("c1", 1),
        _row("c1", "answer", None, 1, protocol_error="no tool call"),
        _row("c1", "answer", "submit_answer", 2, retry=True),
    ]
    assert cc.cut_short(calls) == (1, 1)


def test_a_case_with_no_answer_call_is_counted_but_not_forced() -> None:
    assert cc.cut_short([_row("c1", "h0", "record_hypothesis", 0)]) == (1, 0)


def test_the_decision_line_for_none_and_for_some() -> None:
    assert cc.decision_line(0) == f"cap check: 0 cases had coding cut short at $0.15 -> {_STANDS}"
    assert cc.decision_line(2) == f"cap check: 2 cases had coding cut short at $0.15 -> {_STOP}"


def _both(runs_dir: Path, a_calls: list[AgentCall], b_calls: list[AgentCall]) -> None:
    _write(runs_dir, _RUN_A, _plain(), a_calls)
    _write(runs_dir, _RUN_B, _plain(), b_calls)


def test_main_prints_each_run_and_the_decision(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = [*_coding(_IDS[0], 6), _row(_IDS[0], "answer", "submit_answer", 6)]
    forced = [*_coding(_IDS[1], 1), _row(_IDS[1], "answer", "submit_answer", 1)]
    _both(runs, ok, forced)
    assert cc.main([_RUN_A, _RUN_B]) == 0
    out = capsys.readouterr().out
    assert "run a: 1 cases counted, 0 forced to answer by the cap" in out
    assert "run b: 1 cases counted, 1 forced to answer by the cap" in out
    assert out.rstrip().endswith(f"cap check: 1 cases had coding cut short at $0.15 -> {_STOP}")
    assert "ZQX" not in out


def test_main_writes_the_file_and_names_no_case(
    runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _both(runs, [], [])
    out_path = tmp_path / "results" / "cap.txt"
    assert cc.main([_RUN_A, _RUN_B, "--out", str(out_path)]) == 0
    text = out_path.read_text()
    assert _STANDS in text
    assert "ZQX" not in text


def test_a_missing_run_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    with pytest.raises(SystemExit, match=r"no run\.jsonl"):
        cc.main([_RUN_A, _RUN_B])


def test_a_held_out_run_is_refused(runs: Path) -> None:
    with pytest.raises(SystemExit, match="held-out"):
        cc.main(["20261002T020000-abc1234-heldout-400-C"])
