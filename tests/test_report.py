"""Report tables, slices, comparisons and the threshold rule (spec §4, §6.3, §9)."""

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ntsb_probable_cause.scoring import report
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord
from ntsb_probable_cause.splits import Split

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

_SCHEMA = pa.schema(
    [
        ("ntsb_number", pa.string()),
        ("event_date", pa.date32()),
        ("split", pa.string()),
        ("investigation_class", pa.string()),
        ("raw_json", pa.string()),
    ]
)


def _scores(*, top1: bool, confidence: float, abstained: bool = False) -> CaseScores:
    value = 1.0 if top1 else 0.0
    return CaseScores(
        occurrence_top1=top1,
        occurrence_top3=top1,
        event_match=top1,
        pair_unseen=False,
        finding_precision_10=value,
        finding_recall_10=value,
        finding_precision_8=value,
        finding_recall_8=value,
        finding_precision_6=value,
        finding_recall_6=value,
        finding_precision_all_10=value,
        finding_recall_all_10=value,
        abstained=abstained,
        confidence=confidence,
    )


def _step(case_id: str, not_read: tuple[str, ...]) -> StepRecord:
    """A minimal step, carrying only what ``cap_summary`` reads."""
    return StepRecord(
        case_id=case_id,
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
        documents_not_read=not_read,
        payload_fingerprint="x",
        hypothesis=_HYPOTHESIS,
        observed_effect="",
        stop_reason="",
        model="m",
        price_variant="batch",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        cumulative_cost_usd=0.0,
        commit_sha="abc1234",
        dirty=False,
    )


def _case(  # noqa: PLR0913 -- a test-only builder, one keyword per CaseResult field varied.
    case_id: str,
    *,
    top1: bool = True,
    confidence: float = 0.5,
    fatal: bool = False,
    cls: str | None = "L",
    flavour: str | None = None,
    abstained: bool = False,
    cost: float = 0.001,
    failure: str | None = None,
    scores: CaseScores | None = None,
    not_read: tuple[str, ...] = (),
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        split="heldout",
        fatal=fatal,
        investigation_class=cls,
        report_flavour=flavour,
        verdict_occurrence=("111230",),
        verdict_findings=("0206304044",),
        verdict_findings_in_cause=("0206304044",),
        # A case that failed before any model call (mirroring ``_failed(ctx, "cap", 0.0)``,
        # which always passes ``steps=()``) never gets a step either, even if it dropped
        # documents -- ``documents_not_read`` below is the only place that survives for it.
        steps=(_step(case_id, not_read),) if not_read and not failure else (),
        scores=None
        if failure
        else (scores or _scores(top1=top1, confidence=confidence, abstained=abstained)),
        cost_usd=cost,
        failure=failure,
        documents_not_read=not_read,
    )


def make_results(*, conf: Sequence[float], right: Sequence[bool]) -> list[CaseResult]:
    return [
        _case(f"c{i}", top1=r, confidence=c)
        for i, (c, r) in enumerate(zip(conf, right, strict=True))
    ]


def test_fmt_n_includes_the_count() -> None:
    cell = report.Cell(value=0.575, low=0.421, high=0.715, n=40)
    assert report.fmt_n(cell) == f"{report.fmt(cell)} (n=40)"


def test_provenance_shows_status_commit_and_totals(run_record: RunRecord) -> None:
    text = report.provenance(run_record)
    assert text.startswith(f"run {run_record.run_id} [complete]")
    assert "sample=heldout-40 arm=ceiling model=openai/gpt-5.6-luna" in text
    assert f"commit={run_record.commit_sha} " in text
    assert "cases=40 total_cost_usd=1.2300" in text


def test_provenance_marks_an_aborted_run_and_a_dirty_commit(run_record: RunRecord) -> None:
    aborted = run_record.model_copy(update={"finished": None, "dirty": True})
    text = report.provenance(aborted)
    assert "[ABORTED (partial results)]" in text
    assert f"commit={aborted.commit_sha}*" in text
    assert "finished=-" in text


def test_proportion_cell_has_wilson_interval() -> None:
    cell = report.proportion([True] * 23 + [False] * 17)
    # 0.4217... to four places; the Wilson formula itself gives 0.422 to three places, not
    # the brief's 0.421 (controller resolution 1, same correction as Task 7).
    assert cell.n == 40
    assert round(cell.low, 3) == 0.422


def test_proportion_of_empty_sequence_is_zero() -> None:
    cell = report.proportion([])
    assert cell == report.Cell(value=0.0, low=0.0, high=0.0, n=0)


def test_mean_cell_reports_bootstrap_interval() -> None:
    cell = report.mean_cell([0.0, 0.5, 1.0, 0.5])
    assert cell.n == 4
    assert cell.value == pytest.approx(0.5)
    assert cell.low <= cell.value <= cell.high


def test_choose_threshold_by_hand() -> None:
    results = make_results(conf=[0.9, 0.9, 0.2, 0.2], right=[True, True, False, False])
    curve = dict(report.threshold_curve(results))
    assert curve[0.05] == 0.0  # answer all: (2 - 2)/4
    assert curve[0.5] == 0.5  # abstain the two low ones: (2 - 0)/4
    assert report.choose_threshold(results) == 0.25  # smallest t reaching the maximum


def test_threshold_curve_abstains_do_not_count_as_wrong() -> None:
    results = [
        _case("a", top1=True, confidence=0.9),
        _case("b", top1=False, confidence=0.1, abstained=True),
    ]
    curve = dict(report.threshold_curve(results))
    assert curve[0.05] == 0.5  # the abstained case scores 0, not -1: (1 + 0) / 2


def test_threshold_curve_divides_by_every_case_not_only_scored_ones() -> None:
    # Spec §9: "the mean score" over the cases, not only the ones that produced a hypothesis.
    # A failed case (no scores) contributes 0 to the numerator but still counts in n.
    results = [
        _case("right", top1=True, confidence=0.9),
        _case("failed", top1=True, failure="model: no reply"),
    ]
    curve = dict(report.threshold_curve(results))
    assert curve[0.05] == pytest.approx(0.5)  # (1 - 0) / 2, not (1 - 0) / 1


def test_slices_are_ordered_fatal_class_then_flavour() -> None:
    results = [
        _case("f1", top1=True, fatal=True, cls="C", flavour="Basic (no factual)"),
        _case("n1", top1=True, fatal=False, cls="L", flavour="Full"),
    ]
    grouped = report.slices(results)
    assert list(grouped) == [
        "all",
        "fatal",
        "non-fatal",
        "class C",
        "class F",
        "class L",
        "flavour Basic (no factual)",
        "flavour Full",
    ]
    assert grouped["fatal"] == [results[0]]
    assert grouped["non-fatal"] == [results[1]]
    assert grouped["class C"] == [results[0]]
    assert grouped["class F"] == []


def test_slices_with_no_flavours_lists_none() -> None:
    grouped = report.slices([_case("a", top1=True)])
    assert not any(name.startswith("flavour") for name in grouped)


def test_weighted_headline_combines_fatal_and_non_fatal_by_share() -> None:
    results = [_case(f"f{i}", top1=True, fatal=True) for i in range(2)]
    results += [_case(f"n{i}", top1=False, fatal=False) for i in range(2)]
    cell = report.weighted_headline(results, fatal_share=0.25)
    assert cell.value == pytest.approx(0.25)
    assert cell.n == 4
    assert cell.low <= cell.value <= cell.high


def test_weighted_headline_falls_back_when_one_stratum_is_empty() -> None:
    results = [_case("f0", top1=True, fatal=True)]
    cell = report.weighted_headline(results)
    assert cell.value == pytest.approx(1.0)
    assert cell.n == 1


def test_compare_reports_paired_differences_on_shared_cases() -> None:
    a = [_case("x", top1=True), _case("y", top1=False), _case("only_a", top1=True)]
    b = [_case("x", top1=True), _case("y", top1=True), _case("only_b", top1=False)]
    text = report.compare(a, b)
    assert "on 2 shared, scored cases" in text
    assert "occurrence top-1" in text
    assert "occurrence top-3" in text
    assert "finding recall@10" in text


def test_compare_with_no_shared_finding_truth_says_so() -> None:
    a = [_case("x", top1=True, scores=_scores(top1=True, confidence=0.5))]
    no_truth = CaseScores(
        occurrence_top1=True,
        occurrence_top3=True,
        event_match=True,
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
    b = [_case("x", top1=True, scores=no_truth)]
    text = report.compare(a, b)
    assert "no shared cases have a truth finding set" in text


def test_compare_ignores_failed_cases_without_scores() -> None:
    a = [_case("x", top1=True), _case("failed", top1=True, failure="model: no reply")]
    b = [_case("x", top1=True)]
    text = report.compare(a, b)
    assert "on 1 shared, scored cases" in text


def test_summarise_prints_a_markdown_table_with_floor() -> None:
    results = [_case("a", top1=True), _case("b", top1=False, failure="cap")]
    text = report.summarise(results, floor={"top-1": 0.162})
    assert text.startswith("| slice | n |")
    assert "| all | 1 |" in text  # the failed case has no scores and is excluded from n
    assert "1 of 2" in text  # failed column
    assert "Baseline floor (honest baseline, spec §6.3" in text
    assert "top-1 16.2%" in text


def test_summarise_marks_answered_top1_dash_when_all_abstained() -> None:
    results = [_case("a", top1=False, abstained=True)]
    text = report.summarise(results)
    lines = [line for line in text.splitlines() if line.startswith("| all |")]
    assert lines
    assert " | - | " in lines[0]


def _write_cases(
    tmp_path: Path, rows: Sequence[tuple[str, str, str, str, dict[str, object]]]
) -> Path:
    processed = tmp_path / "processed"
    processed.mkdir()
    ids, dates, splits, classes, raws = zip(*rows, strict=True)
    table = pa.table(
        {
            "ntsb_number": pa.array(ids, type=pa.string()),
            "event_date": pa.array([date.fromisoformat(d) for d in dates], type=pa.date32()),
            "split": pa.array(splits, type=pa.string()),
            "investigation_class": pa.array(classes, type=pa.string()),
            "raw_json": pa.array([json.dumps(r) for r in raws], type=pa.string()),
        },
        schema=_SCHEMA,
    )
    pq.write_table(table, processed / "cases.parquet")
    return processed


def _raw(
    ntsb_number: str,
    *,
    phase: str,
    weather: str,
    primary_code: str,
    finding_codes: Sequence[tuple[str, bool]] = (),
) -> dict[str, object]:
    return {
        "ntsbNumber": ntsb_number,
        "aircrafts": [
            {
                "events": [
                    {
                        "isDefiningEvent": True,
                        "sequenceNumber": 1,
                        "cicttPhaseSOEGroup": phase,
                        "eventCode": primary_code,
                    }
                ],
                "findings": [
                    {"findingNumber": i + 1, "findingCode": code, "inProbableCause": flag}
                    for i, (code, flag) in enumerate(finding_codes)
                ],
            }
        ],
        "weatherConditions": [{"accidentSiteCondition": weather}],
    }


def test_raws_of_split_crosses_a_batch_boundary(tmp_path: Path) -> None:
    # _raws_of_split streams in batches of 256 rows; dev rows on both sides of that boundary,
    # interleaved with heldout rows, is the property streaming is most likely to break.
    rows = [
        (
            f"D{i}" if i % 2 == 0 else f"H{i}",
            "2018-01-01" if i % 2 == 0 else "2021-01-01",
            "dev" if i % 2 == 0 else "heldout",
            "L",
            _raw(
                f"D{i}" if i % 2 == 0 else f"H{i}",
                phase="TAKEOFF",
                weather="VMC",
                primary_code="AAAAAA",
            ),
        )
        for i in range(600)
    ]
    processed = _write_cases(tmp_path, rows)
    dev_rows = report._raws_of_split(processed, Split.DEV)
    assert len(dev_rows) == 300
    assert {r["ntsbNumber"] for r in dev_rows} == {f"D{i}" for i in range(0, 600, 2)}


def test_baseline_report_reproduces_and_scores_the_honest_floor(tmp_path: Path) -> None:
    rows = []
    for i in range(6):
        code = "AAAAAA" if i % 2 == 0 else "BBBBBB"
        raw = _raw(
            f"D{i}",
            phase="TAKEOFF",
            weather="VMC",
            primary_code=code,
            finding_codes=[("0206304044", True)],
        )
        rows.append((f"D{i}", "2018-01-01", "dev", "L", raw))
    for i in range(6):
        code = "AAAAAA" if i % 2 == 0 else "CCCCCC"
        raw = _raw(
            f"H{i}",
            phase="TAKEOFF",
            weather="VMC",
            primary_code=code,
            finding_codes=[("0206304044", True)],
        )
        rows.append((f"H{i}", "2021-01-01", "heldout", "L", raw))
    processed = _write_cases(tmp_path, rows)

    text = report.baseline_report(processed, None, load_tables())
    assert "Reproduction" in text
    assert "n=6" in text  # the reproduction draw, clamped to the 6 held-out cases available
    assert "Honest baseline" in text
    assert "n=6" in text  # scored on the whole held-out split


def test_baseline_report_adds_a_row_for_a_given_sample(tmp_path: Path) -> None:
    rows = [
        (
            f"D{i}",
            "2018-01-01",
            "dev",
            "L",
            _raw(f"D{i}", phase="TAKEOFF", weather="VMC", primary_code="AAAAAA"),
        )
        for i in range(3)
    ]
    rows += [
        (
            f"H{i}",
            "2021-01-01",
            "heldout",
            "L",
            _raw(f"H{i}", phase="TAKEOFF", weather="VMC", primary_code="AAAAAA"),
        )
        for i in range(3)
    ]
    processed = _write_cases(tmp_path, rows)

    text = report.baseline_report(processed, ["H0", "H1"], load_tables())
    assert "Honest baseline on the given sample (n=2)" in text


def test_honest_baseline_floor_returns_the_headline_figures_as_plain_floats(
    tmp_path: Path,
) -> None:
    rows = [
        (
            f"D{i}",
            "2018-01-01",
            "dev",
            "L",
            _raw(f"D{i}", phase="TAKEOFF", weather="VMC", primary_code="AAAAAA"),
        )
        for i in range(3)
    ]
    rows += [
        (
            f"H{i}",
            "2021-01-01",
            "heldout",
            "L",
            _raw(
                f"H{i}",
                phase="TAKEOFF",
                weather="VMC",
                primary_code="AAAAAA",
                finding_codes=[("0206304044", True)],
            ),
        )
        for i in range(3)
    ]
    processed = _write_cases(tmp_path, rows)

    floor = report.honest_baseline_floor(processed)
    assert floor["top-1"] == pytest.approx(1.0)  # every held-out case's key matches dev's
    assert set(floor) == {
        "top-1",
        "top-3",
        "finding recall@10 (flagged)",
        "finding recall@10 (all)",
    }
    assert all(isinstance(v, float) for v in floor.values())


def test_cap_summary_counts_cases_and_documents_by_fatal() -> None:
    fatal_hit = _case("A", fatal=True, not_read=("2: cap, 9000 tokens", "3: cap, 500 tokens"))
    fatal_clear = _case("B", fatal=True)
    non_fatal_hit = _case("C", fatal=False, not_read=("1: cap, 100 tokens",))
    text = report.cap_summary([fatal_hit, fatal_clear, non_fatal_hit])
    assert text == (
        "cap: 2 of 3 cases hit the cap; 3 documents not read "
        "(fatal 1 cases/2 documents, non-fatal 1/1)"
    )


def test_cap_summary_counts_a_case_that_failed_before_any_step() -> None:
    """Fix round 1, Finding 4: a base prompt already over the cap fails via ``_failed``
    before any step is recorded (``steps=()``) -- the worst case, where nothing of the
    docket was read, must not be invisible in the count."""
    failed_before_any_step = _case(
        "Z", fatal=True, not_read=("1: cap, 500 tokens", "2: cap, 300 tokens"), failure="cap"
    )
    assert failed_before_any_step.steps == ()  # no model call was ever made
    text = report.cap_summary([failed_before_any_step])
    assert text == (
        "cap: 1 of 1 cases hit the cap; 2 documents not read "
        "(fatal 1 cases/2 documents, non-fatal 0/0)"
    )


def test_provenance_shows_the_reasoning_level(run_record: RunRecord) -> None:
    """A run from before S2.4 never recorded its level; the header says so plainly."""
    assert "reasoning=provider default" in report.provenance(run_record)
    stated = run_record.model_copy(update={"reasoning_effort": "medium"})
    assert "reasoning=medium" in report.provenance(stated)
