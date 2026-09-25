"""scripts/reply_budget.py: the cause, confirmed or not, and the new budget by a fixed rule."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import reply_budget as rb

from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, write_jsonl

_HYPOTHESIS = Hypothesis(
    evidence_narrative="n",
    occurrence=(OccurrenceGuess(phase="552", event="230", probability=0.5),),
    findings=(),
    probable_cause="p",
    lay_explanation="l",
    confidence=0.5,
    abstain=False,
    evidence_used=(),
)

_SCORES = CaseScores(
    occurrence_top1=True,
    occurrence_top3=True,
    event_match=True,
    pair_unseen=False,
    finding_precision_10=1.0,
    finding_recall_10=1.0,
    finding_precision_8=1.0,
    finding_recall_8=1.0,
    finding_precision_6=1.0,
    finding_recall_6=1.0,
    finding_precision_all_10=1.0,
    finding_recall_all_10=1.0,
    abstained=False,
    confidence=0.5,
)


def test_the_new_budget_is_the_smallest_that_doubles_the_p99() -> None:
    successful = [900] * 98 + [1_800, 2_100]  # p99 = 1,800 -> needs 3,600 -> 4,000
    assert rb.new_budget(successful, failed_reasoning=[1_950]) == 4_000


def test_a_failed_reply_above_the_step_moves_the_budget_up() -> None:
    assert rb.new_budget([900] * 100, failed_reasoning=[4_500]) == 8_000


def test_nothing_fits_means_no_budget() -> None:
    assert rb.new_budget([9_000] * 100, failed_reasoning=[]) is None


def test_the_cause_is_confirmed_by_half_the_failures() -> None:
    failures = [("length", 1_900), ("length", 1_200), ("stop", 10), ("length", 300)]
    assert rb.cause_confirmed(failures, budget=2_000)  # 2 of 4 are length with >= 1,000
    assert not rb.cause_confirmed(failures[1:], budget=2_000)  # 1 of 3


# --- parsing the failure text's trailing bracket ---


def test_parse_detail_reads_the_trailing_bracket() -> None:
    detail = rb._parse_detail(
        "schema: reply is not a Hypothesis: bad json "
        "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1900)"
    )
    assert detail.finish_reason == "length"
    assert detail.reasoning_tokens == 1900


def test_parse_detail_reads_a_none_reasoning_tokens_as_none() -> None:
    detail = rb._parse_detail(
        "schema: bad json (finish_reason=stop, completion_tokens=5, reasoning_tokens=None)"
    )
    assert detail.finish_reason == "stop"
    assert detail.reasoning_tokens is None


def test_parse_detail_of_a_pre_task_9a_failure_text_is_unrecorded_not_a_crash() -> None:
    """A run from before S2.6 Task 9A recorded no trailing bracket at all."""
    detail = rb._parse_detail("schema: reply is not a Hypothesis: Expecting value")
    assert detail.finish_reason == "unrecorded"
    assert detail.reasoning_tokens is None


# --- summarise() ---


def _step(*, completion_tokens: int, reasoning_tokens: int | None) -> StepRecord:
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
        hypothesis=_HYPOTHESIS,
        observed_effect="",
        stop_reason="answered",
        model="openai/gpt-6-luna",
        price_variant="batch",
        prompt_tokens=1000,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        cost_usd=0.001,
        cumulative_cost_usd=0.001,
        commit_sha="abc1234",
        dirty=False,
    )


def _successful_case(
    case_id: str, *, completion_tokens: int, reasoning_tokens: int | None
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        split="dev",
        fatal=False,
        investigation_class="L",
        report_flavour=None,
        verdict_occurrence=("111230",),
        verdict_findings=("0206304044",),
        verdict_findings_in_cause=("0206304044",),
        steps=(_step(completion_tokens=completion_tokens, reasoning_tokens=reasoning_tokens),),
        scores=_SCORES,
        cost_usd=0.001,
        failure=None,
    )


def _failed_case(case_id: str, failure: str) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        split="dev",
        fatal=False,
        investigation_class="L",
        report_flavour=None,
        verdict_occurrence=("111230",),
        verdict_findings=("0206304044",),
        verdict_findings_in_cause=("0206304044",),
        steps=(),
        scores=None,
        cost_usd=0.001,
        failure=failure,
    )


def test_summarise_counts_cases_and_reuses_failure_summary() -> None:
    cases = [
        _successful_case("c1", completion_tokens=900, reasoning_tokens=100),
        _failed_case(
            "c2", "leak: sentence from analysis_narrative in evidence_narrative (12 chars withheld)"
        ),
    ]
    text = rb.summarise(cases)
    assert "cases: 2" in text
    assert "failures by reason: leak (analysis_narrative) 1" in text


def test_summarise_reports_reply_format_failures_by_finish_reason_and_reasoning_tokens() -> None:
    cases = [
        _failed_case(
            "c1",
            "schema: bad json "
            "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1900)",
        ),
        _failed_case(
            "c2",
            "schema: bad json "
            "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1200)",
        ),
        _failed_case("c3", "schema: bad json"),  # pre-Task-9A: no bracket
    ]
    text = rb.summarise(cases, budget=2_000)
    assert "reply-format failures by finish_reason: length 2, unrecorded 1" in text
    assert "n=2 median=1200" in text  # only the two with a reasoning-token figure (nearest-rank)
    assert "cause CONFIRMED against budget=2000 (2 of 3" in text
    assert "new max_output_tokens: 4000" in text


def test_summarise_reports_not_confirmed_when_fewer_than_half_are_length() -> None:
    cases = [
        _failed_case(
            "c1",
            "schema: bad json "
            "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1900)",
        ),
        _failed_case(
            "c2",
            "schema: bad json (finish_reason=stop, completion_tokens=5, reasoning_tokens=10)",
        ),
        _failed_case(
            "c3",
            "schema: bad json (finish_reason=stop, completion_tokens=5, reasoning_tokens=10)",
        ),
    ]
    text = rb.summarise(cases, budget=2_000)
    assert "cause NOT CONFIRMED" in text
    assert "new max_output_tokens" not in text


def test_summarise_shows_successful_cases_token_spread() -> None:
    cases = [
        _successful_case("c1", completion_tokens=900, reasoning_tokens=100),
        _successful_case("c2", completion_tokens=1_100, reasoning_tokens=None),
    ]
    text = rb.summarise(cases)
    assert "total (completion_tokens): n=2" in text
    assert "reasoning tokens alone: n=1" in text  # c2's None is excluded, not counted as 0


def test_summarise_with_no_failures_and_no_successes_says_so() -> None:
    text = rb.summarise([])
    assert "cases: 0" in text
    assert "failures by reason: none" in text
    assert "reply-format failures by finish_reason: none" in text
    assert "no data" in text
    assert "cause NOT CONFIRMED" in text  # an empty failures list is never confirmed


# --- main() ---


def test_main_reads_a_run_folder_and_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    folder = runs_dir / "20260925T000000-abc1234-dev-400-B"
    write_jsonl(
        folder / "cases.jsonl",
        [
            _successful_case("c1", completion_tokens=900, reasoning_tokens=100),
            _failed_case(
                "c2",
                "schema: bad json "
                "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1900)",
            ),
        ],
    )
    write_jsonl(
        folder / "run.jsonl",
        [
            RunRecord(
                run_id=folder.name,
                sample="dev-400",
                arm="B",
                exclusions=(),
                includes=(),
                prompt_version="v1",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=25.0,
                max_output_tokens=2000,
                commit_sha="abc1234",
                dirty=False,
                started=datetime(2026, 9, 25, tzinfo=UTC),
                finished=datetime(2026, 9, 25, 1, tzinfo=UTC),
                cases=2,
                cost_usd=0.01,
            )
        ],
    )
    out = tmp_path / "out.txt"
    code = rb.main(["--run", folder.name, "--out", str(out)])
    assert code == 0
    text = out.read_text()
    assert "cases: 2" in text
    assert "cause CONFIRMED" in text  # budget read from run.jsonl (2000), not hardcoded
