"""scripts/round_result.py: decision 0098 item 4."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import round_result as rr
from tests.test_occurrence_misses import _SCORES, _case

from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl


def _cases(top1: list[bool], recall: list[float]) -> list[CaseResult]:
    return [
        _case(f"C{i}", ("452240",), ("452240",)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=t, finding_recall_10=r)}
        )
        for i, (t, r) in enumerate(zip(top1, recall, strict=True))
    ]


def test_a_round_is_kept_above_the_noise_with_no_harm() -> None:
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 40 for i in range(n)], [0.1] * n)  # +20 points, no finding change
    noise_a = _cases([False] * n, [0.1] * n)
    noise_b = _cases([i < 2 for i in range(n)], [0.1] * n)  # 1 point of noise
    reading = rr.read(run, reference, noise_a, noise_b, finding_round=False)
    assert reading.kept
    assert abs(reading.noise - 0.01) < 1e-9


def test_a_round_inside_the_noise_is_dropped() -> None:
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 4 for i in range(n)], [0.1] * n)  # +2 points
    noise_b = _cases([i < 10 for i in range(n)], [0.1] * n)  # 5 points of noise
    reading = rr.read(run, reference, reference, noise_b, finding_round=False)
    assert not reading.kept


def test_a_gain_that_harms_the_other_score_is_dropped() -> None:
    n = 200
    reference = _cases([False] * n, [0.5] * n)
    run = _cases([i < 40 for i in range(n)], [0.0] * n)  # top-1 up, finding recall down everywhere
    reading = rr.read(run, reference, reference, reference, finding_round=False)
    assert not reading.kept
    assert "harm" in reading.reason


def test_push_line_counts_first_codes_moved_toward_a_more_common_option() -> None:
    stats = build(
        [PoolCase(2012, "Maneuvering", ("452240",))] * 30
        + [PoolCase(2013, "Maneuvering", ("452241",))] * 5,
        built_from="test",
    )
    reference = [_case("C1", ("452240",), ("452241",)), _case("C2", ("452240",), ("452240",))]
    run = [
        _case("C1", ("452240",), ("452240",)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=True)}
        ),
        _case("C2", ("452240",), ("452241",)),
    ]
    reference[1] = reference[1].model_copy(
        update={"scores": replace(_SCORES, occurrence_top1=True)}
    )
    text = rr.push_line(run, reference, {"C1": "Maneuvering", "C2": "Maneuvering"}, stats)
    assert "first codes changed: 2; toward a more common option: 1, fixes 1, breaks 0" in text


def _run_record(run_id: str, *, sample: str = "dev-400", arm: str = "B") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        sample=sample,
        arm=arm,
        evidence_version="v1",
        exclusions=(),
        includes=(),
        prompt_version="s1-v5",
        model="m",
        price_variant="batch",
        cap_usd=0.05,
        budget_usd=40.0,
        commit_sha="abc1234",
        dirty=False,
        started=datetime(2026, 9, 27, tzinfo=UTC),
        finished=datetime(2026, 9, 27, 1, tzinfo=UTC),
        cases=1,
        cost_usd=0.01,
    )


# 2026-09-27 addition beyond the brief: round_result._load mirrors the sibling scripts on this
# branch (judge_outcomes._load, round0_handread._run, round1_report._load), which check
# run.jsonl's recorded sample before cases.jsonl is read at all.
def test_a_run_recorded_on_a_held_out_sample_is_refused_before_its_cases_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    folder = runs_dir / "renamed-run"
    write_jsonl(folder / "run.jsonl", [_run_record("renamed-run", sample="heldout-400")])
    with pytest.raises(SystemExit, match="held-out run"):
        rr._load("renamed-run")
    assert not (folder / "cases.jsonl").exists()


def test_main_prints_the_outcome_and_append_writes_it_to_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 40 for i in range(n)], [0.1] * n)
    noise_a = _cases([False] * n, [0.1] * n)
    noise_b = _cases([i < 2 for i in range(n)], [0.1] * n)
    for run_id, cases in (
        ("run-id", run),
        ("ref-id", reference),
        ("noise-a", noise_a),
        ("noise-b", noise_b),
    ):
        folder = runs_dir / run_id
        write_jsonl(folder / "run.jsonl", [_run_record(run_id)])
        write_jsonl(folder / "cases.jsonl", cases)
    monkeypatch.setattr(rr, "_groups", lambda cases: {c.case_id: None for c in cases})
    out = tmp_path / "registration.md"
    out.write_text("# a round\n")
    assert (
        rr.main(
            [
                "--run",
                "run-id",
                "--reference",
                "ref-id",
                "--noise",
                "noise-a",
                "noise-b",
                "--append",
                str(out),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "outcome: kept" in printed
    assert out.read_text() == "# a round\n" + "\n" + printed
