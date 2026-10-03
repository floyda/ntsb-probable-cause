"""scoring/claims.py: the rules S3.2's registration fixes (spec §6, §7, §9.2, §10)."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from tests.test_occurrence_misses import _SCORES, _case

from ntsb_probable_cause.scoring import claims
from ntsb_probable_cause.scoring.claims import Billed, Outcome, Paired
from ntsb_probable_cause.scoring.metrics import bootstrap_mean
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord


def _scored(
    case_id: str, *, top1: bool = False, top3: bool = False, recall: float | None = None
) -> CaseResult:
    return _case(case_id, ("452240",), ("452240",)).model_copy(
        update={
            "scores": replace(
                _SCORES, occurrence_top1=top1, occurrence_top3=top3, finding_recall_10=recall
            )
        }
    )


def _failed(case_id: str, failure: str, *, flagged: bool = False) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        split="dev",
        fatal=False,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=("452240",),
        verdict_findings=(),
        verdict_findings_in_cause=("1234",) if flagged else (),
        steps=(),
        scores=None,
        cost_usd=0.0,
        failure=failure,
    )


def _abstained(case_id: str) -> CaseResult:
    return _case(case_id, ("452240",), ("452240",), abstain=True).model_copy(
        update={"scores": replace(_SCORES, abstained=True, occurrence_top1=False)}
    )


def _record(**update: object) -> RunRecord:
    base = RunRecord(
        run_id="r",
        sample="heldout-400",
        arm="B",
        exclusions=(),
        includes=(),
        prompt_version="s1-v5",
        model="m",
        price_variant="batch",
        cap_usd=0.3,
        budget_usd=40.0,
        commit_sha="abc1234",
        dirty=False,
        started=datetime(2026, 10, 3, tzinfo=UTC),
        cost_usd=2.0,
    )
    return base.model_copy(update=update)


class TestGuardRefusal:
    def test_a_leak_failure_from_arm_b_or_arm_c_is_a_refusal(self) -> None:
        # runner.leaked_case writes "leak: <message>" for both arms (agent/run.py keeps it).
        assert claims.is_guard_refusal(_failed("C1", "leak: docket document 3 (analysis)"))

    def test_the_loop_stop_reason_failed_leak_is_a_refusal(self) -> None:
        assert claims.is_guard_refusal(_failed("C1", "failed: leak"))

    def test_the_bare_word_leak_is_a_refusal(self) -> None:
        assert claims.is_guard_refusal(_failed("C1", "leak"))

    @pytest.mark.parametrize(
        "failure",
        ["failed: coding", "failed: rounds", "cap", "schema: x", "model: x", "aborted: e"],
    )
    def test_every_other_failure_is_not(self, failure: str) -> None:
        assert not claims.is_guard_refusal(_failed("C1", failure))

    def test_a_case_with_no_failure_is_not(self) -> None:
        assert not claims.is_guard_refusal(_scored("C1"))


class TestAnswered:
    def test_a_scored_case_with_steps_is_answered(self) -> None:
        case = _scored("C1", top1=True)
        assert claims.answered(case) is case.scores

    def test_a_failed_case_is_not(self) -> None:
        assert claims.answered(_failed("C1", "failed: coding")) is None

    def test_a_case_with_scores_but_a_failure_is_not(self) -> None:
        case = _scored("C1").model_copy(update={"failure": "cap"})
        assert claims.answered(case) is None

    def test_a_case_with_no_steps_is_not(self) -> None:
        case = _scored("C1").model_copy(update={"steps": ()})
        assert claims.answered(case) is None


class TestPerCase:
    def test_a_guard_refusal_is_absent(self) -> None:
        cases = [_failed("L1", "leak: x"), _failed("L2", "failed: leak"), _scored("C1", top1=True)]
        assert claims.per_case(cases, "top1") == {"C1": 1.0}

    def test_a_failed_case_counts_as_wrong(self) -> None:
        cases = [_failed("F1", "failed: coding"), _scored("C1", top1=True)]
        assert claims.per_case(cases, "top1") == {"F1": 0.0, "C1": 1.0}
        assert claims.per_case(cases, "top3") == {"F1": 0.0, "C1": 0.0}

    def test_an_abstained_scored_case_is_wrong_on_top1(self) -> None:
        # metrics.score_case sets occurrence_top1 = answered and ..., so an abstained case is
        # already False; nothing more is needed here.
        assert claims.per_case([_abstained("A1")], "top1") == {"A1": 0.0}

    def test_top3_reads_the_top3_score(self) -> None:
        cases = [_scored("C1", top1=False, top3=True), _scored("C2", top1=True, top3=True)]
        assert claims.per_case(cases, "top3") == {"C1": 1.0, "C2": 1.0}
        assert claims.per_case(cases, "top1") == {"C1": 0.0, "C2": 1.0}

    def test_recall10_gives_a_failed_case_zero_only_when_findings_are_flagged(self) -> None:
        cases = [
            _failed("F1", "failed: coding", flagged=True),
            _failed("F2", "failed: coding", flagged=False),
        ]
        assert claims.per_case(cases, "recall10") == {"F1": 0.0}

    def test_recall10_leaves_out_a_scored_case_with_no_recall(self) -> None:
        cases = [_scored("C1", recall=0.5), _scored("C2", recall=None)]
        assert claims.per_case(cases, "recall10") == {"C1": 0.5}

    def test_recall10_leaves_out_a_guard_refusal_even_with_flagged_findings(self) -> None:
        cases = [_failed("L1", "leak: x", flagged=True)]
        assert claims.per_case(cases, "recall10") == {}


class TestPaired:
    def test_a_case_refused_in_either_arm_is_in_neither(self) -> None:
        a = [_scored("C1", top1=True), _failed("C2", "leak: x"), _scored("C3", top1=True)]
        b = [_scored("C1"), _scored("C2", top1=True), _failed("C3", "leak: y")]
        d = claims.paired(a, b, "top1")
        assert d.n == 1
        assert d.mean == pytest.approx(1.0)

    def test_the_mean_is_a_minus_b_in_fractions_with_the_projects_bootstrap(self) -> None:
        a = [_scored(f"C{i}", top1=i < 3) for i in range(10)]
        b = [_scored(f"C{i}", top1=i < 1) for i in range(10)]
        d = claims.paired(a, b, "top1")
        mean, low, high = bootstrap_mean([1.0, 1.0] + [0.0] * 8)
        assert d == Paired(mean, low, high, 10)
        assert d.mean == pytest.approx(0.2)

    def test_a_failure_in_one_arm_counts_as_wrong_there(self) -> None:
        a = [_failed("C1", "failed: coding"), _scored("C2", top1=True)]
        b = [_scored("C1", top1=True), _scored("C2", top1=True)]
        d = claims.paired(a, b, "top1")
        assert d.n == 2
        assert d.mean == pytest.approx(-0.5)

    def test_an_empty_pairing_is_zero(self) -> None:
        assert claims.paired([], [], "top1") == Paired(0.0, 0.0, 0.0, 0)

    def test_cases_in_only_one_arm_are_left_out(self) -> None:
        d = claims.paired([_scored("C1"), _scored("C2")], [_scored("C1")], "top1")
        assert d.n == 1


class TestBothAnswered:
    def test_only_cases_answered_in_both_arms(self) -> None:
        a = [_scored("C1", top1=True), _failed("C2", "failed: coding"), _scored("C3", top1=True)]
        b = [_scored("C1"), _scored("C2", top1=True), _failed("C3", "cap")]
        d = claims.both_answered(a, b, "top1")
        assert d.n == 1
        assert d.mean == pytest.approx(1.0)

    def test_recall10_with_no_recall_on_a_case_leaves_it_out(self) -> None:
        a = [_scored("C1", recall=0.5), _scored("C2", recall=None)]
        b = [_scored("C1", recall=0.25), _scored("C2", recall=0.5)]
        d = claims.both_answered(a, b, "recall10")
        assert d.n == 1
        assert d.mean == pytest.approx(0.25)


class TestOutcome:
    @staticmethod
    def _of(low: float, high: float) -> Outcome:
        return claims.outcome(Paired(0.0, low, high, 100))

    def test_a_low_just_above_zero_beats(self) -> None:
        assert self._of(0.001, 0.1) == "beats"

    def test_a_low_of_zero_does_not_beat(self) -> None:
        assert self._of(0.0, 0.1) == "matches"

    def test_a_low_just_inside_the_margin_matches_even_with_a_high_below_zero(self) -> None:
        # The margin is tested before "worse" (spec §7.2's order).
        assert self._of(-0.0599, -0.01) == "matches"

    def test_a_low_at_the_margin_with_a_high_below_zero_is_worse(self) -> None:
        assert self._of(-0.06, -0.01) == "worse"

    def test_a_low_at_the_margin_with_a_high_above_zero_is_undecided(self) -> None:
        assert self._of(-0.06, 0.02) == "undecided"

    def test_a_low_beyond_the_margin_with_a_high_above_zero_is_undecided(self) -> None:
        assert self._of(-0.07, 0.05) == "undecided"

    def test_a_stricter_margin_can_be_passed(self) -> None:
        assert claims.outcome(Paired(0.0, -0.04, 0.05, 100), margin=0.03) == "undecided"


class TestCostBand:
    @pytest.mark.parametrize(
        ("loop", "band"),
        [(89.0, "lower"), (90.0, "equal"), (100.0, "equal"), (110.0, "equal"), (111.0, "greater")],
    )
    def test_the_band_at_its_edges(self, loop: float, band: str) -> None:
        assert claims.cost_band(loop, 100.0) == band

    def test_a_wider_band_can_be_passed(self) -> None:
        assert claims.cost_band(85.0, 100.0, band=0.2) == "equal"


class TestWarranted:
    @pytest.mark.parametrize(
        ("o", "band", "expected"),
        [
            ("beats", "lower", True),
            ("beats", "equal", True),
            ("matches", "lower", True),
            ("beats", "greater", False),
            ("matches", "equal", False),
            ("matches", "greater", False),
            ("worse", "lower", False),
            ("undecided", "lower", False),
        ],
    )
    def test_warranted(self, o: Outcome, band: claims.CostBand, expected: bool) -> None:
        assert claims.warranted(o, band) is expected


class TestResult2:
    @pytest.mark.parametrize(
        ("o", "band"),
        [
            ("matches", "equal"),
            ("matches", "greater"),
            ("worse", "greater"),
            ("undecided", "equal"),
        ],
    )
    def test_holds(self, o: Outcome, band: claims.CostBand) -> None:
        assert claims.result2_holds(o, band)

    @pytest.mark.parametrize("band", ["lower", "equal", "greater"])
    def test_does_not_hold_when_the_loop_beats(self, band: claims.CostBand) -> None:
        assert not claims.result2_holds("beats", band)

    @pytest.mark.parametrize("o", ["beats", "matches", "worse", "undecided"])
    def test_does_not_hold_when_the_loop_costs_less(self, o: Outcome) -> None:
        assert not claims.result2_holds(o, "lower")


class TestBilled:
    def test_a_reported_batch_cost_is_the_billed_figure(self) -> None:
        record = _record(reported_batch_cost_usd=1.1, batch_ids=("b1",))
        assert claims.billed(record) == Billed(1.1, 2.0, True)

    def test_a_synchronous_run_is_billed_at_its_computed_cost(self) -> None:
        assert claims.billed(_record()) == Billed(2.0, 2.0, True)

    def test_a_batch_run_with_no_reported_cost_stands_in_with_computed(self) -> None:
        record = _record(batch_ids=("b1",))
        assert claims.billed(record) == Billed(2.0, 2.0, False)


class TestSavingSplit:
    def test_the_three_differences(self) -> None:
        loop = [Billed(1.0, 4.0, True), Billed(0.5, 2.0, True)]
        armb = [Billed(1.0, 1.5, True), Billed(0.5, 1.0, True), Billed(0.25, 0.5, True)]
        split = claims.saving_split(loop, armb)
        assert split.work_usd == pytest.approx(6.0 - 3.0)
        assert split.loop_discount_usd == pytest.approx(6.0 - 1.5)
        assert split.armb_discount_usd == pytest.approx(3.0 - 1.75)

    def test_no_runs_give_zeros(self) -> None:
        assert claims.saving_split([], []) == claims.SavingSplit(0.0, 0.0, 0.0)


class TestHeadline:
    @pytest.mark.parametrize("band", ["lower", "equal"])
    def test_beats_at_equal_or_lower(self, band: claims.CostBand) -> None:
        assert claims.headline("beats", band) == (
            "On held-out cases, the loop beat the fixed pipeline at equal or lower cost."
        )

    def test_matches_at_lower(self) -> None:
        assert claims.headline("matches", "lower") == (
            "On held-out cases, the loop matched the fixed pipeline at lower cost."
        )

    def test_beats_only_at_greater_cost(self) -> None:
        assert claims.headline("beats", "greater") == (
            "On held-out cases, the loop was not shown to improve on the fixed pipeline: "
            "it beat it only at greater cost."
        )

    @pytest.mark.parametrize("band", ["equal", "greater"])
    def test_matches_at_equal_or_greater(self, band: claims.CostBand) -> None:
        assert claims.headline("matches", band) == (
            "On held-out cases, the loop was not shown to improve on the fixed pipeline: "
            "it matched it at equal or greater cost."
        )

    @pytest.mark.parametrize("band", ["lower", "equal", "greater"])
    def test_worse(self, band: claims.CostBand) -> None:
        assert claims.headline("worse", band) == (
            "On held-out cases, the loop was not shown to improve on the fixed pipeline: "
            "it was worse."
        )

    @pytest.mark.parametrize("band", ["lower", "equal", "greater"])
    def test_undecided(self, band: claims.CostBand) -> None:
        assert claims.headline("undecided", band) == (
            "On held-out cases, the loop was not shown to improve on the fixed pipeline: "
            "it was undecided."
        )
