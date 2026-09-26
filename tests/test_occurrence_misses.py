"""scripts/occurrence_misses.py: counts of where the first guess lands in the NTSB's sequence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import occurrence_misses as om

from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, write_jsonl

_SCORES = CaseScores(
    occurrence_top1=False,
    occurrence_top3=False,
    event_match=False,
    pair_unseen=False,
    finding_precision_10=None,
    finding_recall_10=None,
    finding_precision_8=None,
    finding_recall_8=None,
    finding_precision_6=None,
    finding_recall_6=None,
    finding_precision_all_10=None,
    finding_recall_all_10=None,
    abstained=False,
    confidence=0.5,
)


def _step(guesses: tuple[str, ...], *, abstain: bool) -> StepRecord:
    hypothesis = Hypothesis(
        evidence_narrative="n",
        occurrence=tuple(
            OccurrenceGuess(phase=code[:3], event=code[3:], probability=0.3) for code in guesses
        ),
        findings=(),
        probable_cause="p",
        lay_explanation="l",
        confidence=0.5,
        abstain=abstain,
        evidence_used=(),
    )
    return StepRecord(
        case_id="c",
        step=0,
        arm="B",
        condition="full",
        day=None,
        tool="docket",
        arguments={},
        reason="",
        expected_effect="",
        returned_roles=(),
        not_available=(),
        payload_fingerprint="x",
        hypothesis=hypothesis,
        observed_effect="",
        stop_reason="answered",
        model="m",
        price_variant="batch",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        cumulative_cost_usd=0.0,
        commit_sha="abc1234",
        dirty=False,
    )


def _case(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    truth: tuple[str, ...],
    guesses: tuple[str, ...],
    *,
    abstain: bool = False,
    scored: bool = True,
    split: str = "dev",
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        split=split,
        fatal=False,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=truth,
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(_step(guesses, abstain=abstain),) if scored else (),
        scores=_SCORES if scored else None,
        cost_usd=0.0,
        failure=None if scored else "leak",
    )


# 240 loss of control in flight; 241 aerodynamic stall/spin; 230 loss of control on ground;
# 192 fuel exhaustion. Phases 552 and 500 (landing roll, approach).
CASES = [
    _case("CASEA1", ("552240", "552241"), ("552240",)),  # first code
    _case("CASEB2", ("552240", "552241"), ("552241", "552230")),  # in the sequence, not first
    _case("CASEC3", ("500240",), ("552240",)),  # the right event, the wrong phase
    _case("CASED4", ("552192", "552230"), ("552240", "552230")),  # only a later guess is in it
    _case("CASEE5", ("552230",), ("552230",), abstain=True),  # abstained: a miss throughout
    _case("CASEF6", ("552230",), ("552230",), scored=False),  # failed: not counted at all
]


def test_summarise_counts_each_rate_over_the_scored_cases() -> None:
    text = om.summarise(CASES, load_tables())
    assert "scored cases: 5 (abstained, counted as misses on every rate: 1;" in text
    assert "first guess = the NTSB's first code: 1 of 5 (20.0%)" in text
    assert "first guess's event = the first event (any phase): 2 of 5 (40.0%)" in text
    assert "first guess's phase = the first phase: 3 of 5 (60.0%)" in text
    assert "first guess anywhere in the NTSB's sequence: 2 of 5 (40.0%)" in text
    assert "any of the 3 guesses anywhere in the NTSB's sequence: 3 of 5 (60.0%)" in text
    assert "NTSB sequence length (codes per case): 1: 2, 2: 3" in text
    assert "(the 2 commonest of 2 pairs; 2 cases whose first-guess event" in text
    assert "- 1  Loss of control in flight -> Aerodynamic stall/spin" in text
    assert "- 1  Fuel exhaustion -> Loss of control in flight" in text
    # Counts and code labels only: never a case number.
    assert "CASE" not in text


def _write_run(runs_dir: Path, run_id: str, *, sample: str = "dev-400", arm: str = "B") -> Path:
    folder = runs_dir / run_id
    write_jsonl(
        folder / "run.jsonl",
        [
            RunRecord(
                run_id=run_id,
                sample=sample,
                arm=arm,
                evidence_version="v2",
                exclusions=(),
                includes=(),
                prompt_version="s1-v5",
                model="m",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha="abc1234",
                dirty=False,
                started=datetime(2026, 9, 26, tzinfo=UTC),
                finished=datetime(2026, 9, 26, 1, tzinfo=UTC),
                cases=len(CASES),
                cost_usd=0.01,
            )
        ],
    )
    return folder


def test_main_prints_and_writes_the_counts_for_a_development_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    folder = _write_run(runs_dir, "20260926T000000-abc1234-dev-400-B")
    write_jsonl(folder / "cases.jsonl", CASES)
    out = tmp_path / "results" / "misses.txt"
    assert om.main(["--run", "20260926T000000-abc1234-dev-400-B", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "run 20260926T000000-abc1234-dev-400-B [complete]" in printed
    assert "first guess = the NTSB's first code: 1 of 5 (20.0%)" in printed
    assert out.read_text() == printed


def test_a_held_out_run_id_is_refused_before_anything_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path / "runs"))
    with pytest.raises(SystemExit, match="development runs only"):
        om.main(["--run", "20260926T000000-abc1234-heldout-400-B"])


def test_a_run_recorded_on_a_held_out_sample_is_refused_before_its_cases_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    _write_run(runs_dir, "renamed-run", sample="heldout-400")  # no cases.jsonl written
    with pytest.raises(SystemExit, match="held-out run"):
        om.main(["--run", "renamed-run"])


def test_a_run_that_is_not_arm_b_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    _write_run(runs_dir, "ceiling-run", arm="ceiling")
    with pytest.raises(SystemExit, match="not arm B"):
        om.main(["--run", "ceiling-run"])


def test_a_run_holding_a_case_outside_the_dev_split_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    folder = _write_run(runs_dir, "mixed-run")
    write_jsonl(
        folder / "cases.jsonl", [*CASES, _case("CASEH7", ("552240",), ("552240",), split="heldout")]
    )
    with pytest.raises(SystemExit, match="outside the dev split"):
        om.main(["--run", "mixed-run"])
    assert capsys.readouterr().out == ""
