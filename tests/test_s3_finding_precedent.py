"""scripts/exploratory/s3_finding_precedent.py: would precedent findings beat the loop's own.

S3.1 Task 15, exploratory. Synthetic run folders built from ``CaseResult`` objects and a processed
file of invented cases (invented ids, invented words, real finding codes), whose five nearest
earlier cases, predicted sets and scores are worked out by hand in the comments. Offline: no
network, no model.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import ClassVar

import pytest
from scripts import coding_stats as cs
from scripts.exploratory import s3_finding_precedent as fp
from scripts.exploratory import s3_precedent_probe as pp
from tests.test_coding_stats import _CASE_NUMBER
from tests.test_occurrence_misses import _SCORES, _case
from tests.test_s3_finding_consistency import _FA, _FB, _FC, _FD, _FE, _Row, _row
from tests.test_s3_precedent_probe import _processed, _write_run

from ntsb_probable_cause import fields, gitinfo
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.scoring import report as scoring_report
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.metrics import CaseScores, bootstrap_mean, paired_difference
from ntsb_probable_cause.scoring.records import CaseResult

_RUN_A = "20261001T201506-fd6053f-dev-400-C"
_RUN_B = "20261001T201648-fd6053f-dev-400-C"
_DAY = "2016-06-01"
_IDS = tuple(f"ZQX{n:03d}" for n in range(8))
_FATAL = frozenset({"ZQX000", "ZQX001", "ZQX006", "ZQX007"})
_SEALED = "ZQS001"
# Invented words: none is in the code tables' labels or in the report's own text.
_WORDS = (
    "brambleton",
    "gallimaufry",
    "stoat",
    "tangle",
    "quillfern",
    "zorvexine",
    "zephyrine",
    "marrowfat",
    "thistlebrook",
    "thistlecomb",
)
# Sorted: FB < FA < FC < FD < FE. FA and FB share their item (01010510); FC has another item of
# the same category (010105); FD is category 010227; FE is category 020110.


def _flagged(*codes: str) -> fp.Flagged:
    return frozenset(codes)


def _day(text: str) -> date:
    return date.fromisoformat(text)


# --------------------------------------------------------------------------------------------
# The predictors
# --------------------------------------------------------------------------------------------

_NONE: fp.Flagged = frozenset()


class TestCommonestSet:
    def test_the_set_held_by_most_of_the_five(self) -> None:
        five = [_flagged(_FA), _flagged(_FB), _flagged(_FA), _flagged(_FC, _FD), _flagged(_FB)]
        assert fp.commonest_set(five) == _flagged(_FA)  # FA twice, FB twice: FA is ranked first

    def test_a_tie_goes_to_the_set_whose_first_holder_is_ranked_highest(self) -> None:
        # Not to the smaller code or the smaller set: FB sorts below FA, but FA is ranked first.
        assert fp.commonest_set([_flagged(_FA), _flagged(_FB), _flagged(_FB), _flagged(_FA)]) == (
            _flagged(_FA)
        )
        assert fp.commonest_set([_flagged(_FB), _flagged(_FA), _flagged(_FA), _flagged(_FB)]) == (
            _flagged(_FB)
        )

    def test_a_set_is_compared_whole(self) -> None:
        assert fp.commonest_set([_flagged(_FA), _flagged(_FA, _FB), _flagged(_FA)]) == (
            _flagged(_FA)
        )
        # {FA} once, {FA, FB} twice: the two-code set is the commonest, not FA.
        assert fp.commonest_set([_flagged(_FA), _flagged(_FA, _FB), _flagged(_FA, _FB)]) == (
            _flagged(_FA, _FB)
        )

    def test_an_empty_set_never_counts_and_never_wins(self) -> None:
        # Three empty sets are the most held; the non-empty set held once is the answer.
        assert fp.commonest_set([_NONE, _NONE, _flagged(_FC), _NONE]) == _flagged(_FC)

    def test_none_when_all_are_empty_or_there_are_no_cases(self) -> None:
        assert fp.commonest_set([_NONE] * 5) is None
        assert fp.commonest_set([]) is None


class TestNearest:
    def test_the_highest_ranked_non_empty_set(self) -> None:
        assert fp.nearest([_NONE, _NONE, _flagged(_FD), _flagged(_FA)]) == _flagged(_FD)
        assert fp.nearest([_flagged(_FA, _FB), _flagged(_FC)]) == _flagged(_FA, _FB)

    def test_none_when_all_are_empty_or_there_are_no_cases(self) -> None:
        assert fp.nearest([_NONE] * 5) is None
        assert fp.nearest([]) is None


class TestAtLeastTwo:
    def test_the_codes_flagged_in_two_or_more_of_the_five(self) -> None:
        five = [_flagged(_FA, _FD), _flagged(_FE), _flagged(_FA), _flagged(_FA), _flagged(_FE)]
        assert fp.at_least_two(five) == _flagged(_FA, _FE)  # FA in three cases, FE in two

    def test_a_code_in_one_case_is_not_enough_however_many_codes_it_has(self) -> None:
        assert fp.at_least_two([_flagged(_FA, _FB, _FC, _FD), _flagged(_FE), _NONE]) is None

    def test_a_code_counts_once_for_a_case(self) -> None:
        # The frozenset holds a code once, so one case cannot be two.
        assert fp.at_least_two([_flagged(_FA), _NONE]) is None

    def test_none_when_all_are_empty_or_there_are_no_cases(self) -> None:
        assert fp.at_least_two([_NONE] * 5) is None
        assert fp.at_least_two([]) is None


class TestPredictorList:
    def test_the_three_predictors_are_named_in_the_committed_order(self) -> None:
        assert [name for name, _predict in fp.PREDICTORS] == [
            "commonest set",
            "nearest",
            "at least two",
        ]
        assert fp.HEADLINE_PREDICTOR == "commonest set"
        assert fp.HEADLINE_QUERY == "probable cause"


# --------------------------------------------------------------------------------------------
# Scoring a predicted set
# --------------------------------------------------------------------------------------------


class TestScore:
    OWN = (_FB, _FC, _FD)

    def test_precision_and_recall_at_each_digit_count(self) -> None:
        # {FA, FD} against {FB, FC, FD}: at 10 digits FD only; at 8, the items 01010510 and
        # 01022710 are both held; at 6, the categories 010105 and 010227 both are.
        found = fp.score(_flagged(_FA, _FD), self.OWN)
        assert found.recall == {10: 1 / 3, 8: 2 / 3, 6: 1.0}
        assert found.precision == {10: 1 / 2, 8: 1.0, 6: 1.0}

    def test_no_set_has_a_recall_of_zero_and_no_precision(self) -> None:
        found = fp.score(None, self.OWN)
        assert found.recall == {10: 0.0, 8: 0.0, 6: 0.0}
        assert found.precision == {10: None, 8: None, 6: None}

    def test_it_is_scoring_metrics_own_count_not_a_copy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[list[str], int]] = []

        def fake(
            predicted: Sequence[str], truth: Sequence[str], digits: int
        ) -> tuple[float | None, float | None]:
            calls.append((list(predicted), digits))
            return 0.25, 0.75

        monkeypatch.setattr(fp, "_precision_recall", fake)
        found = fp.score(_flagged(_FA), self.OWN)
        assert [digits for _codes, digits in calls] == [10, 8, 6]
        assert found.precision == {10: 0.25, 8: 0.25, 6: 0.25}
        assert found.recall == {10: 0.75, 8: 0.75, 6: 0.75}

    def test_a_case_with_no_flagged_finding_cannot_be_scored(self) -> None:
        with pytest.raises(ValueError, match="at least one flagged finding"):
            fp.score(_flagged(_FA), ())


# --------------------------------------------------------------------------------------------
# The case split
# --------------------------------------------------------------------------------------------


def _loop(  # noqa: PLR0913, PLR0917 -- a test-only builder, the six stored scores.
    r10: float | None = 1.0,
    p10: float | None = 1.0,
    r8: float | None = 1.0,
    p8: float | None = 1.0,
    r6: float | None = 1.0,
    p6: float | None = 1.0,
) -> CaseScores:
    return replace(
        _SCORES,
        finding_recall_10=r10,
        finding_precision_10=p10,
        finding_recall_8=r8,
        finding_precision_8=p8,
        finding_recall_6=r6,
        finding_precision_6=p6,
    )


def _one(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    own: Sequence[str] = (_FA,),
    *,
    cause: str = "",
    narrative: str = "",
    loop: CaseScores | None = None,
    abstain: bool = False,
    failed: bool = False,
    fatal: bool | None = None,
) -> CaseResult:
    """A case of a run: its verdict's flagged findings, its answer's texts, its stored scores."""
    case = _case(case_id, ("552230",), ("552230",), abstain=abstain, scored=not failed).model_copy(
        update={
            "fatal": case_id in _FATAL if fatal is None else fatal,
            "verdict_findings_in_cause": tuple(own),
        }
    )
    if failed:
        return case
    step = case.steps[0]
    hypothesis = step.hypothesis.model_copy(
        update={"probable_cause": cause, "evidence_narrative": narrative}
    )
    scores = replace(loop if loop is not None else _loop(), abstained=abstain)
    return case.model_copy(
        update={"steps": (step.model_copy(update={"hypothesis": hypothesis}),), "scores": scores}
    )


class TestSortCases:
    def test_each_case_is_counted_once_and_the_judged_ones_are_kept(self) -> None:
        cases = [
            _one("ZQX000"),  # judged
            _one("ZQX001", failed=True),  # failed
            _one("ZQX002", abstain=True),  # abstained, with a flagged finding
            _one("ZQX003", ()),  # scored, answered, no flagged finding
            _one("ZQX004", (_FB, _FC)),  # judged
        ]
        split = fp.sort_cases(cases)
        assert (split.total, split.failed, split.abstained, split.no_flagged) == (5, 1, 1, 1)
        assert [j.case_id for j in split.judged] == ["ZQX000", "ZQX004"]
        assert split.failed + split.abstained + split.no_flagged + len(split.judged) == split.total

    def test_a_failed_case_is_failed_whatever_else_holds_of_it(self) -> None:
        # Failed with no flagged finding: failed. Abstained with none: abstained.
        cases = [_one("ZQX000", (), failed=True), _one("ZQX001", (), abstain=True)]
        split = fp.sort_cases(cases)
        assert (split.failed, split.abstained, split.no_flagged, len(split.judged)) == (1, 1, 0, 0)

    def test_a_case_with_a_failure_text_or_no_score_is_counted_as_failed(self) -> None:
        # Decision 0136 item 1: a failure, or no score, whatever the steps hold.
        failure = _one("ZQX000").model_copy(update={"failure": "failed: coding"})
        unscored = _one("ZQX001").model_copy(update={"scores": None})
        split = fp.sort_cases([failure, unscored, _one("ZQX002")])
        assert (split.failed, len(split.judged)) == (2, 1)

    def test_the_abstain_flag_is_the_final_answers_not_the_stored_scores(self) -> None:
        case = _one("ZQX000", abstain=True).model_copy(update={"scores": _one("ZQX000").scores})
        assert fp.sort_cases([case]).abstained == 1

    def test_the_loops_stored_scores_ride_with_the_judged_case(self) -> None:
        loop = _loop(0.5, None, 0.25, 0.75, 1.0, None)
        (judged,) = fp.sort_cases([_one("ZQX000", loop=loop)]).judged
        assert judged.recall == {10: 0.5, 8: 0.25, 6: 1.0}
        assert judged.precision == {10: None, 8: 0.75, 6: None}
        assert judged.own == (_FA,)

    def test_a_judged_case_whose_stored_recall_is_none_is_refused(self) -> None:
        case = _one("ZQX000", loop=_loop(r8=None))
        with pytest.raises(SystemExit, match="hold no finding recall"):
            fp.sort_cases([case])

    def test_no_case(self) -> None:
        split = fp.sort_cases([])
        assert (split.total, split.failed, split.abstained, split.no_flagged) == (0, 0, 0, 0)
        assert split.judged == ()


# --------------------------------------------------------------------------------------------
# The comparison and the rule
# --------------------------------------------------------------------------------------------


def _judged(
    case_id: str, recall: Sequence[float], precision: Sequence[float | None], *, fatal: bool = False
) -> fp.Judged:
    return fp.Judged(
        _one(case_id, fatal=fatal),
        dict(zip(fp.DIGITS, recall, strict=True)),
        dict(zip(fp.DIGITS, precision, strict=True)),
    )


def _scored(recall: Sequence[float], precision: Sequence[float | None]) -> fp.Scored:
    return fp.Scored(
        dict(zip(fp.DIGITS, recall, strict=True)), dict(zip(fp.DIGITS, precision, strict=True))
    )


def _cell(values: Sequence[float]) -> tuple[float, float, float]:
    return bootstrap_mean(list(values))


class TestCompare:
    def test_the_paired_difference_is_the_projects_on_the_same_cases(self) -> None:
        # Recall in {0, 1} on both sides: scoring.metrics.paired_difference itself applies.
        pred = [1.0, 0.0, 1.0, 1.0, 0.0, 0.0]
        loop = [0.0, 0.0, 1.0, 0.0, 1.0, 1.0]
        cases = [_judged(f"ZQX00{n}", [loop[n]] * 3, [0.5] * 3) for n in range(6)]
        scored = {f"ZQX00{n}": _scored([pred[n]] * 3, [0.5] * 3) for n in range(6)}
        found = fp.compare(cases, scored)
        expected = paired_difference([bool(x) for x in pred], [bool(x) for x in loop])
        assert (
            found.recall_diff[10].value,
            found.recall_diff[10].low,
            found.recall_diff[10].high,
        ) == (expected)
        assert found.recall_diff[10].n == 6
        # Precision differs by exactly zero on every case: the interval is a point at zero.
        assert (found.precision_diff[10].value, found.precision_diff[10].high) == (0.0, 0.0)

    def test_fractional_scores_are_paired_case_by_case_not_by_position_in_the_mapping(self) -> None:
        cases = [
            _judged("ZQX000", [0.5, 1 / 3, 1.0], [0.5, 0.5, 0.5]),
            _judged("ZQX001", [0.0, 0.0, 0.25], [0.5, 0.5, 0.5]),
            _judged("ZQX002", [1.0, 1.0, 1.0], [0.5, 0.5, 0.5]),
        ]
        # The mapping holds the cases in another order: the pairing is by case id.
        scored = {
            "ZQX002": _scored([0.25, 0.5, 0.75], [0.5] * 3),
            "ZQX000": _scored([0.0, 0.0, 0.5], [0.5] * 3),
            "ZQX001": _scored([0.5, 1.0, 1.0], [0.5] * 3),
        }
        found = fp.compare(cases, scored)
        want = _cell([0.0 - 0.5, 0.5 - 0.0, 0.25 - 1.0])
        got = found.recall_diff[10]
        assert (got.value, got.low, got.high, got.n) == (*want, 3)
        want8 = _cell([0.0 - 1 / 3, 1.0 - 0.0, 0.5 - 1.0])
        assert (found.recall_diff[8].value, found.recall_diff[8].low) == want8[:2]
        want6 = _cell([0.5 - 1.0, 1.0 - 0.25, 0.75 - 1.0])
        assert found.recall_diff[6].high == want6[2]
        mean10 = _cell([0.0, 0.5, 0.25])
        assert (found.recall[10].value, found.recall[10].low, found.recall[10].high) == mean10

    def test_a_precision_of_none_is_left_out_on_each_side_and_counted(self) -> None:
        # Case 0: the predictor has none. Case 1: the loop named nothing. Case 2: both defined.
        # Case 3: neither is defined.
        cases = [
            _judged("ZQX000", [0.5] * 3, [0.5] * 3),
            _judged("ZQX001", [0.5] * 3, [None] * 3),
            _judged("ZQX002", [0.5] * 3, [0.25] * 3),
            _judged("ZQX003", [0.5] * 3, [None] * 3),
        ]
        scored = {
            "ZQX000": _scored([0.0] * 3, [None] * 3),
            "ZQX001": _scored([0.5] * 3, [1.0] * 3),
            "ZQX002": _scored([0.5] * 3, [0.75] * 3),
            "ZQX003": _scored([0.0] * 3, [None] * 3),
        }
        found = fp.compare(cases, scored)
        assert found.n == 4
        assert found.no_prediction == 2
        # The predictor's own precision: cases 1 and 2.
        assert found.precision[10].n == 2
        assert found.precision[10].value == 0.875
        # Paired: only case 2 has both: 0.75 - 0.25.
        assert (found.precision_diff[10].n, found.precision_diff[10].value) == (1, 0.5)
        # Recall is paired on all four: a predictor with none scores 0.
        assert found.recall_diff[10].n == 4
        assert found.recall_diff[10].value == (-0.5 + 0.0 + 0.0 - 0.5) / 4

    def test_the_loops_own_precision_leaves_out_a_none_and_counts_it(self) -> None:
        cases = [
            _judged("ZQX000", [0.0] * 3, [None] * 3),
            _judged("ZQX001", [1.0] * 3, [0.5] * 3),
            _judged("ZQX002", [0.5] * 3, [1.0] * 3),
        ]
        found = fp.loop_own(cases)
        assert found.n == 3
        assert found.precision[10].n == 2
        assert found.precision[10].value == 0.75
        assert found.recall[10].n == 3
        assert found.recall[10].value == 0.5

    def test_higher_equal_and_lower_count_recall_at_ten_digits(self) -> None:
        cases = [
            _judged(f"ZQX00{n}", [loop] * 3, [0.5] * 3)
            for n, loop in enumerate((0.5, 1 / 3, 0.0, 1.0))
        ]
        scored = {
            f"ZQX00{n}": _scored([mine] * 3, [0.5] * 3)
            for n, mine in enumerate((0.5, 2 / 6, 0.5, 0.0))
        }
        found = fp.compare(cases, scored)
        # 0.5 = 0.5; 2/6 = 1/3 exactly the same float; 0.5 > 0.0; 0.0 < 1.0.
        assert (found.higher, found.equal, found.lower) == (1, 2, 1)

    def test_no_case(self) -> None:
        found = fp.compare([], {})
        assert found.n == 0
        assert found.recall_diff[10].n == 0
        assert fp.comparison_lines(found) == ["- no judged case"]
        assert fp.own_lines(fp.loop_own([])) == ["- no judged case"]


def _spread_world(n: int = 15) -> tuple[list[fp.Judged], dict[str, fp.Scored]]:
    """``n`` judged cases with varied recall and precision (some precisions None), by case id."""
    rng = random.Random(7)  # noqa: S311 -- a fixed test draw, not security
    levels = (0.0, 0.25, 1 / 3, 0.5, 2 / 3, 1.0)
    cases: list[fp.Judged] = []
    scored: dict[str, fp.Scored] = {}
    for number in range(n):
        case_id = f"ZQX{number:03d}"
        loop_precision = [rng.choice((*levels, None)) for _ in fp.DIGITS]
        mine_precision = [rng.choice((*levels, None)) for _ in fp.DIGITS]
        cases.append(
            _judged(
                case_id,
                [rng.choice(levels) for _ in fp.DIGITS],
                loop_precision,
                fatal=number % 2 == 0,
            )
        )
        scored[case_id] = _scored([rng.choice(levels) for _ in fp.DIGITS], mine_precision)
    return cases, scored


class TestOrderOfTheCases:
    """A bootstrap resamples by position: the intervals are taken in case-id order."""

    def test_the_premise_a_bootstrap_depends_on_the_order_of_its_values(self) -> None:
        values = [0.0, 1.0, 0.25, 0.5, 1 / 3, 1.0, 0.0, 0.5, 2 / 3, 0.25, 1.0, 0.0]
        assert bootstrap_mean(values) != bootstrap_mean(values[::-1])

    def test_shuffling_the_cases_changes_no_interval(self) -> None:
        cases, scored = _spread_world()
        want = fp.compare(cases, scored)
        want_own = fp.loop_own(cases)
        rng = random.Random(11)  # noqa: S311 -- a fixed test draw, not security
        for _ in range(5):
            shuffled = list(cases)
            rng.shuffle(shuffled)
            assert shuffled != cases
            assert fp.compare(shuffled, scored) == want
            assert fp.loop_own(shuffled) == want_own
        assert fp.compare(cases[::-1], scored) == want

    def test_the_fatal_and_non_fatal_sets_are_ordered_the_same_way(self) -> None:
        cases, scored = _spread_world()
        fatal = [j for j in cases if j.case.fatal]
        assert fp.compare(fatal[::-1], scored) == fp.compare(fatal, scored)

    def test_the_recall_difference_is_the_one_the_report_prints_for_the_same_pairs(self) -> None:
        cases, scored = _spread_world()
        mine = [_one(j.case_id, loop=_loop(r10=scored[j.case_id].recall[10])) for j in cases]
        loop = [_one(j.case_id, loop=_loop(r10=j.recall[10])) for j in cases]
        # The report is given the cases in another order and still orders its pairs by id.
        text = scoring_report.compare(mine[::-1], loop)
        found = fp.compare(cases[::-1], scored).recall_diff[10]
        assert (
            f"- finding recall@10: {found.value:+.1%} [{found.low:+.1%}, {found.high:+.1%}] "
            f"on n={found.n} cases"
        ) in text

    def test_the_report_is_the_same_whatever_order_a_run_holds_its_cases_in(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain = _report(_argv(), capsys)
        _write_run(runs, _RUN_A, _run_a()[::-1])
        _write_run(runs, _RUN_B, _run_b()[::-1])
        assert _report(_argv(), capsys) == plain


class TestOutcome:
    @pytest.mark.parametrize(
        ("recall_low", "precision_high", "word"),
        [
            (0.01, 0.01, "promising"),
            (0.01, 0.0, "promising"),  # a high end of exactly zero is not below zero
            (0.01, -0.01, "mixed"),
            (0.01, None, "promising"),  # no case with both precisions: no interval below zero
            (0.0, 0.5, "not promising"),  # a low end of exactly zero is not above zero
            (0.0, -0.5, "not promising"),
            (-0.01, 0.5, "not promising"),
            (-0.5, -0.5, "not promising"),
            (1e-12, 0.0, "promising"),
            (1e-12, -1e-12, "mixed"),
        ],
    )
    def test_the_rule_at_its_edges(
        self, recall_low: float, precision_high: float | None, word: str
    ) -> None:
        assert fp.outcome(recall_low, precision_high) == word


def _result(
    run_id: str,
    recall: Sequence[float],
    loop_recall: Sequence[float],
    precision: float | None,
    loop_precision: float | None,
) -> fp.RunResult:
    """A run whose judged cases score the given recall at 10 digits against the loop's."""
    ids = [f"ZQX{n:03d}" for n in range(len(recall))]
    cases = [
        _judged(case_id, [loop] * 3, [loop_precision] * 3)
        for case_id, loop in zip(ids, loop_recall, strict=True)
    ]
    scored = {
        case_id: _scored([mine] * 3, [precision] * 3)
        for case_id, mine in zip(ids, recall, strict=True)
    }
    split = fp.CaseSplit(len(ids), 0, 0, 0, tuple(cases))
    return fp.RunResult(
        run_id,
        split,
        {(query, name): scored for query in pp.QUERIES for name, _predict in fp.PREDICTORS},
    )


def _paired_result(
    run_id: str,
    recall: Sequence[tuple[float, float]],
    precision: Sequence[tuple[float, float]],
) -> fp.RunResult:
    """A run whose judged cases hold (predictor, loop) pairs of recall and of precision.

    Each pair is the same at 10, 8 and 6 digits. The differences between the pairs spread, so the
    bootstrap interval of their mean has a low end below its high end.
    """
    ids = [f"ZQX{n:03d}" for n in range(len(recall))]
    cases = []
    scored = {}
    for case_id, (mine_r, loop_r), (mine_p, loop_p) in zip(ids, recall, precision, strict=True):
        cases.append(_judged(case_id, [loop_r] * 3, [loop_p] * 3))
        scored[case_id] = _scored([mine_r] * 3, [mine_p] * 3)
    split = fp.CaseSplit(len(ids), 0, 0, 0, tuple(cases))
    return fp.RunResult(
        run_id,
        split,
        {(query, name): scored for query in pp.QUERIES for name, _predict in fp.PREDICTORS},
    )


def _around(base: float, differences: Sequence[float]) -> list[tuple[float, float]]:
    """(predictor, loop) pairs whose loop score is ``base`` and whose differences are given."""
    return [(base + difference, base) for difference in differences]


# Differences of recall at 10 digits, predictor less loop, and of precision, for the rule's words.
_RECALL_SPREAD_ZERO = [0.5, 0.5, 0.5, 0.5, -0.5, -0.5, -0.5, 0, 0, 0, 0, 0]  # mean above zero
_RECALL_ABOVE = [0.5, 0.25, 0.75, 0.5, 0.25, 0.5, 0.75, 0.5, 0.25, 0.5]
_PRECISION_ACROSS = [0.5, -0.5, 0.25, -0.25, 0, 0.5, -0.5, 0.25, -0.25, -0.25]  # mean below zero
_PRECISION_BELOW = [-0.25, -0.5, -0.75, -0.5, -0.25, -0.5, -0.75, -0.5, -0.25, -0.5]


class TestRuleLinesWithSpread:
    """Intervals with a low end below the high end: the rule reads the right end of each."""

    @staticmethod
    def _headline(result: fp.RunResult) -> fp.Comparison:
        return fp.compare(
            result.split.judged, result.scored[(fp.HEADLINE_QUERY, fp.HEADLINE_PREDICTOR)]
        )

    @staticmethod
    def _lines(a: fp.RunResult) -> str:
        return "\n".join(fp.rule_lines([a, _result(_RUN_B, [0.0], [1.0], 0.0, 1.0)]))

    def test_a_recall_interval_across_zero_is_not_promising(self) -> None:
        # The mean difference is above zero and the high end is, but the low end is not: the
        # interval is not above zero. (Reading the high end would give "promising".)
        result = _paired_result(_RUN_A, _around(0.5, _RECALL_SPREAD_ZERO), _around(0.5, [0.0] * 12))
        recall = self._headline(result).recall_diff[10]
        assert recall.value > 0
        assert recall.low <= 0 < recall.high
        text = self._lines(result)
        assert "Outcome: not promising" in text
        assert "The expectation was not met." in text

    def test_a_precision_interval_across_zero_is_not_below_zero(self) -> None:
        # Recall is entirely above zero. Precision has a low end below zero and a high end at
        # or above it: not entirely below zero, so promising and not mixed. (Reading the low end
        # of the precision interval would give "mixed".)
        result = _paired_result(
            _RUN_A, _around(0.25, _RECALL_ABOVE), _around(0.5, _PRECISION_ACROSS)
        )
        found = self._headline(result)
        assert found.recall_diff[10].low > 0
        precision = found.precision_diff[10]
        assert precision.value < 0
        assert precision.low < 0 <= precision.high
        text = self._lines(result)
        assert "Outcome: promising" in text
        assert "The expectation was met." in text

    def test_a_precision_interval_entirely_below_zero_is_mixed(self) -> None:
        result = _paired_result(
            _RUN_A, _around(0.25, _RECALL_ABOVE), _around(1.0, _PRECISION_BELOW)
        )
        found = self._headline(result)
        assert found.recall_diff[10].low > 0
        assert found.precision_diff[10].low < found.precision_diff[10].high < 0
        assert "Outcome: mixed" in self._lines(result)

    def test_the_rule_reads_the_unrounded_ends_of_the_intervals_it_prints(self) -> None:
        result = _paired_result(
            _RUN_A, _around(0.25, _RECALL_ABOVE), _around(0.5, _PRECISION_ACROSS)
        )
        found = self._headline(result)
        text = self._lines(result)
        assert f"{found.recall_diff[10].low:+.1%}" in text
        assert f"{found.precision_diff[10].high:+.1%}" in text


class TestRuleLines:
    def _lines(self, a: fp.RunResult) -> str:
        return "\n".join(fp.rule_lines([a, _result(_RUN_B, [0.0], [1.0], 0.0, 1.0)]))

    def test_promising_when_recall_is_above_zero_and_precision_is_not_below(self) -> None:
        # Every case's recall is 0.5 above the loop's: the interval is a point above zero.
        # Every case's precision equals the loop's: a point at exactly zero, not below it.
        text = self._lines(_result(_RUN_A, [1.0] * 5, [0.5] * 5, 0.5, 0.5))
        assert text.endswith("Outcome: promising\n" + fp.EXPECTATION + "\nThe expectation was met.")
        assert "predictor less loop: +50.0% [+50.0%, +50.0%] (n = 5 cases)" in text
        assert "predictor less loop: +0.0% [+0.0%, +0.0%] (n = 5 cases where both" in text

    def test_mixed_when_precision_is_entirely_below_zero(self) -> None:
        text = self._lines(_result(_RUN_A, [1.0] * 5, [0.5] * 5, 0.25, 0.5))
        assert "Outcome: mixed" in text
        assert "The expectation was not met." in text

    def test_not_promising_when_the_recall_interval_only_touches_zero(self) -> None:
        # No difference at all: the low end is exactly zero, which is not above it.
        text = self._lines(_result(_RUN_A, [0.5] * 5, [0.5] * 5, 0.5, 0.5))
        assert "Outcome: not promising" in text

    def test_not_promising_when_recall_is_below(self) -> None:
        text = self._lines(_result(_RUN_A, [0.0] * 5, [0.5] * 5, 0.5, 0.5))
        assert "Outcome: not promising" in text
        assert (
            "recall at 10 digits against the loop's, case by case: higher in 0, equal in 0, "
            "lower in 5 of 5 judged cases"
        ) in text

    def test_no_precision_pair_is_said_and_read_as_not_below_zero(self) -> None:
        text = self._lines(_result(_RUN_A, [1.0] * 5, [0.5] * 5, None, 0.5))
        assert "Note: no case has both precisions, so the precision interval is read as not" in text
        assert "Outcome: promising" in text
        assert "(n = 0 cases where both precisions are defined)" in text

    def test_run_b_is_printed_and_does_not_decide(self) -> None:
        # Run a is not promising; run b would be, and the word is run a's.
        b = _result(_RUN_B, [1.0] * 5, [0.5] * 5, 0.5, 0.5)
        a = _result(_RUN_A, [0.0] * 5, [0.5] * 5, 0.5, 0.5)
        text = "\n".join(fp.rule_lines([a, b]))
        assert text.count("Outcome:") == 1
        assert "Outcome: not promising" in text
        assert f"Run b ({_RUN_B}), beside it, decides nothing: recall difference +50.0%" in text

    def test_the_committed_rule_is_printed_verbatim(self) -> None:
        text = self._lines(_result(_RUN_A, [1.0], [0.5], 0.5, 0.5))
        assert fp.RULE in text
        assert fp.RULE.startswith(
            "Rule (Andy, 2026-10-02). Read on run a, the probable-cause query"
        )
        assert (
            "promising if the paired difference in mean recall at 10 digits has its interval "
            "above zero and the paired difference in mean precision at 10 digits does not have "
            "its interval below zero; mixed if the recall difference's interval is above zero "
            "and the precision difference's interval is below zero; not promising otherwise."
        ) in fp.RULE
        assert fp.RULE.endswith("a findings tool the loop may call), not a tool.")
        assert fp.EXPECTATION == "Expectation (decides nothing). Promising."
        assert "committed in 1c44b9d, before this script existed" in text


# --------------------------------------------------------------------------------------------
# The committed rule block is unchanged by the whole pool; its second reading is a block of its own
# --------------------------------------------------------------------------------------------

# The committed rule block as the script printed it before the whole pool was added (captured from
# the script at commit bb5155b, on the two results built in ``_old_block_results``): the text and
# the word of the earlier-only block must not move.
_OLD_RULE_PROMISING = "\n".join(
    [
        "## The rule (committed in 1c44b9d, before this script existed)",
        "",
        (
            "Rule (Andy, 2026-10-02). Read on run a, the probable-cause query, the headline"
            " predictor: promising if the paired difference in mean recall at 10 digits has"
            " its interval above zero and the paired difference in mean precision at 10"
            " digits does not have its interval below zero; mixed if the recall difference's"
            " interval is above zero and the precision difference's interval is below zero;"
            " not promising otherwise. The script applies the rule and prints the word."
            " Either result is published as it stands; a promising result starts a round's"
            " design (a findings tool the loop may call), not a tool."
        ),
        (
            "Run a (20261001T201506-fd6053f-dev-400-C), the probable-cause query, the"
            " commonest-set predictor, all judged cases (10 of 10 cases):"
        ),
        (
            "- paired difference in mean recall at 10 digits, predictor less loop: +47.5%"
            " [+37.5%, +57.5%] (n = 10 cases)"
        ),
        (
            "- paired difference in mean precision at 10 digits, predictor less loop: -2.5%"
            " [-25.0%, +20.0%] (n = 10 cases where both precisions are defined)"
        ),
        (
            "- recall at 10 digits against the loop's, case by case: higher in 10, equal in"
            " 0, lower in 0 of 10 judged cases"
        ),
        (
            "Run b (20261001T201648-fd6053f-dev-400-C), beside it, decides nothing: recall"
            " difference -100.0% [-100.0%, -100.0%] (n = 1); precision difference -100.0%"
            " [-100.0%, -100.0%] (n = 1)"
        ),
        "Outcome: promising",
        "Expectation (decides nothing). Promising.",
        "The expectation was met.",
    ]
)

_OLD_RULE_NOT_PROMISING = "\n".join(
    [
        "## The rule (committed in 1c44b9d, before this script existed)",
        "",
        (
            "Rule (Andy, 2026-10-02). Read on run a, the probable-cause query, the headline"
            " predictor: promising if the paired difference in mean recall at 10 digits has"
            " its interval above zero and the paired difference in mean precision at 10"
            " digits does not have its interval below zero; mixed if the recall difference's"
            " interval is above zero and the precision difference's interval is below zero;"
            " not promising otherwise. The script applies the rule and prints the word."
            " Either result is published as it stands; a promising result starts a round's"
            " design (a findings tool the loop may call), not a tool."
        ),
        (
            "Run a (20261001T201506-fd6053f-dev-400-C), the probable-cause query, the"
            " commonest-set predictor, all judged cases (5 of 5 cases):"
        ),
        (
            "- paired difference in mean recall at 10 digits, predictor less loop: -50.0%"
            " [-50.0%, -50.0%] (n = 5 cases)"
        ),
        (
            "- paired difference in mean precision at 10 digits, predictor less loop: +0.0%"
            " [+0.0%, +0.0%] (n = 5 cases where both precisions are defined)"
        ),
        (
            "- recall at 10 digits against the loop's, case by case: higher in 0, equal in 0,"
            " lower in 5 of 5 judged cases"
        ),
        (
            "Run b (20261001T201648-fd6053f-dev-400-C), beside it, decides nothing: recall"
            " difference -100.0% [-100.0%, -100.0%] (n = 1); precision difference -100.0%"
            " [-100.0%, -100.0%] (n = 1)"
        ),
        "Outcome: not promising",
        "Expectation (decides nothing). Promising.",
        "The expectation was not met.",
    ]
)


def _earlier_only(result: fp.RunResult) -> fp.RunResult:
    """``result`` with the date-limited figures only: reading the whole pool raises a KeyError."""
    return replace(result, whole={})


def _whole_only(result: fp.RunResult) -> fp.RunResult:
    """``result``'s figures as the whole pool's, with none for the date-limited pool."""
    return replace(result, scored={}, whole=result.scored)


def _old_block_results() -> tuple[fp.RunResult, fp.RunResult, fp.RunResult]:
    spread = _paired_result(_RUN_A, _around(0.25, _RECALL_ABOVE), _around(0.5, _PRECISION_ACROSS))
    below = _result(_RUN_A, [0.0] * 5, [0.5] * 5, 0.5, 0.5)
    run_b = _result(_RUN_B, [0.0], [1.0], 0.0, 1.0)
    return spread, below, run_b


class TestEarlierRuleBlockUnchanged:
    """Adding the whole pool does not change the committed rule block: its text and its word."""

    def test_the_promising_block_is_the_text_it_was_before(self) -> None:
        spread, _below, run_b = _old_block_results()
        assert "\n".join(fp.rule_lines([spread, run_b])) == _OLD_RULE_PROMISING

    def test_the_not_promising_block_is_the_text_it_was_before(self) -> None:
        _spread, below, run_b = _old_block_results()
        assert "\n".join(fp.rule_lines([below, run_b])) == _OLD_RULE_NOT_PROMISING

    def test_whole_pool_figures_never_reach_the_committed_block(self) -> None:
        # Whole-pool figures that would give the opposite words, and another run b: the block is
        # the same text. With none at all it is the same text again.
        spread, below, run_b = _old_block_results()
        opposite_a = replace(spread, whole=below.scored)
        opposite_b = replace(run_b, whole=_result(_RUN_B, [1.0] * 5, [0.0] * 5, 1.0, 0.0).scored)
        assert "\n".join(fp.rule_lines([opposite_a, opposite_b])) == _OLD_RULE_PROMISING
        assert "\n".join(fp.rule_lines([_earlier_only(spread), _earlier_only(run_b)])) == (
            _OLD_RULE_PROMISING
        )
        opposite_below = replace(below, whole=spread.scored)
        assert "\n".join(fp.rule_lines([opposite_below, run_b])) == _OLD_RULE_NOT_PROMISING

    def test_only_the_committed_block_has_an_expectation(self) -> None:
        spread, _below, run_b = _old_block_results()
        first = "\n".join(fp.rule_lines([spread, run_b]))
        second = "\n".join(fp.whole_rule_lines([_whole_only(spread), _whole_only(run_b)]))
        assert fp.EXPECTATION in first
        assert "The expectation was met." in first
        assert "xpectation" not in second.replace("No expectation was committed for it.", "")
        assert fp.RULE not in second  # the rule is printed once, in the committed block


class TestWholePoolRuleLines:
    """The second reading: the same rule, read on the whole-pool figures, with no expectation."""

    @staticmethod
    def _lines(a: fp.RunResult, b: fp.RunResult | None = None) -> str:
        run_b = b if b is not None else _result(_RUN_B, [0.0], [1.0], 0.0, 1.0)
        return "\n".join(fp.whole_rule_lines([_whole_only(a), _whole_only(run_b)]))

    def test_it_is_headed_as_a_second_reading_registered_after_the_first_result(self) -> None:
        text = self._lines(_result(_RUN_A, [1.0] * 5, [0.5] * 5, 0.5, 0.5))
        assert text.startswith(
            "## Second reading under the whole pool (registered in bb5155b, after the first "
            "result was seen)\n"
        )
        assert "applied again without change to the whole pool" in text
        assert "every pool case except those on the judged case's own event date" in text
        assert "stays the committed outcome" in text
        assert "No expectation was committed for it." in text

    def test_promising_when_recall_is_above_zero_and_precision_is_not_below(self) -> None:
        text = self._lines(_result(_RUN_A, [1.0] * 5, [0.5] * 5, 0.5, 0.5))
        assert text.endswith("Second reading outcome: promising")
        assert (
            "all judged cases (5 of 5 cases), whole pool:\n"
            "- paired difference in mean recall at 10 digits, predictor less loop: "
            "+50.0% [+50.0%, +50.0%] (n = 5 cases)"
        ) in text
        assert "predictor less loop: +0.0% [+0.0%, +0.0%] (n = 5 cases where both" in text

    def test_mixed_when_precision_is_entirely_below_zero(self) -> None:
        text = self._lines(_result(_RUN_A, [1.0] * 5, [0.5] * 5, 0.25, 0.5))
        assert text.endswith("Second reading outcome: mixed")

    def test_not_promising_when_the_recall_interval_only_touches_zero(self) -> None:
        text = self._lines(_result(_RUN_A, [0.5] * 5, [0.5] * 5, 0.5, 0.5))
        assert text.endswith("Second reading outcome: not promising")

    def test_not_promising_when_recall_is_below(self) -> None:
        text = self._lines(_result(_RUN_A, [0.0] * 5, [0.5] * 5, 0.5, 0.5))
        assert text.endswith("Second reading outcome: not promising")
        assert (
            "recall at 10 digits against the loop's, case by case: higher in 0, equal in 0, "
            "lower in 5 of 5 judged cases"
        ) in text

    def test_no_precision_pair_is_said_and_read_as_not_below_zero(self) -> None:
        text = self._lines(_result(_RUN_A, [1.0] * 5, [0.5] * 5, None, 0.5))
        assert "Note: no case has both precisions, so the precision interval is read as not" in text
        assert text.endswith("Second reading outcome: promising")

    def test_run_b_is_printed_beside_and_does_not_decide(self) -> None:
        b = _result(_RUN_B, [1.0] * 5, [0.5] * 5, 0.5, 0.5)
        a = _result(_RUN_A, [0.0] * 5, [0.5] * 5, 0.5, 0.5)
        text = self._lines(a, b)
        assert text.count("outcome:") == 1
        assert text.endswith("Second reading outcome: not promising")
        assert f"Run b ({_RUN_B}), beside it, decides nothing: recall difference +50.0%" in text

    def test_it_reads_the_whole_pool_figures_and_never_the_date_limited_ones(self) -> None:
        # Date-limited figures that would be promising, whole-pool figures that are not: the
        # committed block says promising and the second reading says not promising, and the other
        # way about. (A result with no date-limited figures cannot be read for them at all.)
        promising = _result(_RUN_A, [1.0] * 5, [0.5] * 5, 0.5, 0.5)
        not_promising = _result(_RUN_A, [0.0] * 5, [0.5] * 5, 0.5, 0.5)
        run_b = _result(_RUN_B, [0.0], [1.0], 0.0, 1.0)
        for earlier, whole, first, second in (
            (promising, not_promising, "promising", "not promising"),
            (not_promising, promising, "not promising", "promising"),
        ):
            a = replace(earlier, whole=whole.scored)
            b = replace(run_b, whole=run_b.scored)
            assert f"Outcome: {first}\n" in "\n".join(fp.rule_lines([a, b]))
            assert "\n".join(fp.whole_rule_lines([a, b])).endswith(
                f"Second reading outcome: {second}"
            )

    @pytest.mark.parametrize(
        ("recall", "precision", "word"),
        [
            (_around(0.5, _RECALL_SPREAD_ZERO), _around(0.5, [0.0] * 12), "not promising"),
            (_around(0.25, _RECALL_ABOVE), _around(0.5, _PRECISION_ACROSS), "promising"),
            (_around(0.25, _RECALL_ABOVE), _around(1.0, _PRECISION_BELOW), "mixed"),
        ],
        ids=["recall across zero", "precision across zero", "precision below zero"],
    )
    def test_the_word_is_read_from_the_right_end_of_each_interval(
        self, recall: list[tuple[float, float]], precision: list[tuple[float, float]], word: str
    ) -> None:
        # The same three cases as the committed rule's spread tests: reading the high end of
        # the recall interval, or the low end of the precision interval, would change the word.
        result = _paired_result(_RUN_A, recall, precision)
        found = fp.compare(result.split.judged, result.scored[(fp.HEADLINE_QUERY, "commonest set")])
        text = self._lines(result)
        assert text.endswith(f"Second reading outcome: {word}")
        # And it prints the unrounded ends the word was read from.
        assert f"{found.recall_diff[10].low:+.1%}" in text
        assert f"{found.precision_diff[10].high:+.1%}" in text


# --------------------------------------------------------------------------------------------
# The reused search: the date limit reaches through the index
# --------------------------------------------------------------------------------------------


def _precedent(case_id: str, day: str, words: Sequence[str]) -> pp.Precedent:
    return pp.Precedent(case_id, _day(day), "552230", tuple(words))


class TestFiveSets:
    POOL = (
        _precedent("ZQP001", "2012-01-01", ("fuel",)),
        _precedent("ZQP002", "2013-01-01", ("fuel", "tank")),
        _precedent("ZQP003", _DAY, ("fuel",)),  # the same day: never ranked
        _precedent("ZQP004", "2017-01-01", ("fuel",)),  # later: never ranked
    )
    FLAGS: ClassVar[Mapping[str, fp.Flagged]] = {
        "ZQP001": _flagged(_FA),
        "ZQP002": _NONE,
        "ZQP003": _flagged(_FB),
        "ZQP004": _flagged(_FC),
    }

    def _five(self, text: str, query: pp.Query = "probable cause") -> tuple[fp.Flagged, ...]:
        """The five for ``text`` as the answer's probable cause, or as its evidence narrative."""
        other = "unrelated"
        answer = _one(
            "ZQX000",
            cause=text if query == "probable cause" else other,
            narrative=text if query == "evidence narrative" else other,
        )
        (judged,) = fp.sort_cases([answer]).judged
        return fp.five_sets(pp.Index(self.POOL), self.FLAGS, judged, _day(_DAY), query)

    def test_only_strictly_earlier_cases_are_ranked_best_first(self) -> None:
        assert self._five("fuel") == (_flagged(_FA), _NONE)

    def test_the_other_query_is_the_evidence_narrative(self) -> None:
        assert self._five("fuel", "evidence narrative") == (_flagged(_FA), _NONE)
        assert self._five("tank", "evidence narrative") == (_NONE,)

    def test_a_query_sharing_no_word_ranks_nothing(self) -> None:
        assert self._five("thistlecomb") == ()
        assert self._five("") == ()

    def test_only_five_are_kept(self) -> None:
        pool = [_precedent(f"ZQP{n:03d}", f"2012-0{n}-01", ("fuel",)) for n in range(1, 8)]
        flags = {p.case_id: _flagged(_FA) for p in pool}
        (judged,) = fp.sort_cases([_one("ZQX000", cause="fuel")]).judged
        assert len(fp.five_sets(pp.Index(pool), flags, judged, _day(_DAY), "probable cause")) == 5

    def test_a_failed_case_has_no_answer_to_search_with(self) -> None:
        failed = fp.Judged(_one("ZQX000", failed=True), {10: 0.0, 8: 0.0, 6: 0.0}, {})
        with pytest.raises(ValueError, match="final answer"):
            fp.five_sets(pp.Index(self.POOL), self.FLAGS, failed, _day(_DAY), "probable cause")

    def test_the_pool_cases_as_the_search_sees_them(self) -> None:
        text = pp.PoolText(
            "ZQP001", _day("2012-01-01"), "The Fuel, and tanks.", ("552230", "300230")
        )
        assert pp.precedents([text]) == [
            pp.Precedent("ZQP001", _day("2012-01-01"), "552230", ("fuel", "tanks"))
        ]

    def test_the_whole_pool_ranks_a_later_case_and_never_one_on_the_judged_date(self) -> None:
        # P001 (earlier) and P004 (later) tie at length 1, ranked by id; then P002. P003, on the
        # judged date, is never ranked although it matches as well as P001 does.
        (judged,) = fp.sort_cases([_one("ZQX000", cause="fuel")]).judged
        index = pp.Index(self.POOL)
        whole = fp.five_sets(index, self.FLAGS, judged, _day(_DAY), "probable cause", pool="whole")
        assert whole == (_flagged(_FA), _flagged(_FC), _NONE)
        assert _flagged(_FB) not in whole  # P003's set
        # The default, and "earlier" by name, are the date-limited pool: no later case.
        earlier = (_flagged(_FA), _NONE)
        assert fp.five_sets(index, self.FLAGS, judged, _day(_DAY), "probable cause") == earlier
        assert (
            fp.five_sets(index, self.FLAGS, judged, _day(_DAY), "probable cause", pool="earlier")
            == earlier
        )

    def test_a_later_case_can_be_the_only_one_ranked_on_the_whole_pool(self) -> None:
        pool = (*self.POOL, _precedent("ZQP005", "2018-01-01", ("zorvexine",)))
        flags = {**self.FLAGS, "ZQP005": _flagged(_FD)}
        index = pp.Index(pool)
        (judged,) = fp.sort_cases([_one("ZQX000", cause="zorvexine")]).judged
        assert fp.five_sets(index, flags, judged, _day(_DAY), "probable cause") == ()
        whole = fp.five_sets(index, flags, judged, _day(_DAY), "probable cause", pool="whole")
        assert whole == (_flagged(_FD),)

    def test_the_whole_pool_other_query_and_the_five_limit(self) -> None:
        pool = [_precedent(f"ZQP{n:03d}", f"2012-0{n}-01", ("fuel",)) for n in range(1, 8)]
        pool.append(_precedent("ZQP008", "2019-01-01", ("fuel",)))
        flags = {p.case_id: _flagged(_FA) for p in pool}
        index = pp.Index(pool)
        (judged,) = fp.sort_cases([_one("ZQX000", cause="x", narrative="fuel")]).judged
        five = fp.five_sets(index, flags, judged, _day(_DAY), "evidence narrative", pool="whole")
        assert len(five) == 5

    def test_the_search_is_the_precedent_probes_own_on_each_pool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """analyse searches through ``Index.search`` once per case, query and pool; no copy."""
        calls: list[tuple[date, pp.Pool]] = []
        real = pp.Index.search

        def spy(
            self: pp.Index, query: Sequence[str], day: date, pool: pp.Pool
        ) -> tuple[pp.Precedent, ...]:
            calls.append((day, pool))
            return real(self, query, day, pool)

        monkeypatch.setattr(pp.Index, "search", spy)
        split = fp.sort_cases([_one("ZQX000", cause="fuel"), _one("ZQX001", cause="tank")])
        result = fp.analyse(
            "run",
            split,
            index=pp.Index(self.POOL),
            flags=self.FLAGS,
            days={"ZQX000": _day(_DAY), "ZQX001": _day("2014-01-01")},
        )
        # Two queries, two cases, each searched on the date-limited pool and then the whole pool.
        assert len(calls) == 8
        assert sorted({pool for _day_, pool in calls}) == ["earlier", "whole"]
        assert calls.count((_day(_DAY), "whole")) == 2
        assert calls.count((_day("2014-01-01"), "earlier")) == 2
        assert set(result.scored) == set(result.whole)
        assert result.scores("earlier") is result.scored
        assert result.scores("whole") is result.whole


# --------------------------------------------------------------------------------------------
# The whole script, on synthetic runs and a processed file
# --------------------------------------------------------------------------------------------
#
# The pool (kept: ZQP001-ZQP006, ZQP012, ZQP013, ZQP021, ZQP022, ZQP031, ZQP032, ZQP007, ZQP008).
# Judged cases are all on 2016-06-01. Words: B = brambleton, shorter text ranks higher.
#   B group, earlier: P001 "B" {FA, FD}; P002 {FE}; P003 {FA}; P004 {FA}; P005 {FE, FC} (lengths
#     1..5, so ranked in that order); P006 (length 6, the sixth: never in the five) {FB, FD, FC}
#   P007 (2017) and P008 (the judged day), both "B" {FB}: never ranked
#   marrowfat: P013 "marrowfat" {} (ranked first), P012 "zephyrine marrowfat" {FA}
#   thistlebrook: P021 {} and P022 {}: all empty
#   thistlecomb: P031 (2017) {FA} and P032 (the judged day) {FA}: never ranked
# Left out of the pool: a case with no text, one with no code, the sealed sample's case, a
# class I case and a held-out case, the last three with the text "brambleton" and {FB}, which
# would rank among the five.
#
# Run a (cases 0, 1, 6, 7 fatal): the judged are ZQX000, ZQX004, ZQX005, ZQX006.
#   ZQX000 own {FB, FC, FD}; probable cause "brambleton"; evidence narrative "quillfern" (P005,
#     P006); the loop named no finding (recall 0, precision None)
#   ZQX004 own {FA, FB}; "thistlebrook"; the loop 0.5/0.5, 0.5/0.5, 1/1
#   ZQX005 own {FD}; "thistlecomb" (nothing earlier); narrative "brambleton"; the loop 1 throughout
#   ZQX006 own {FA}; "marrowfat"; the loop recall 1 and precision 0.5 at each level
#   ZQX001 failed; ZQX002 abstained; ZQX003 no flagged finding; ZQX007 failed with none
# Run b: ZQX005's probable cause is "marrowfat" and ZQX006 failed.
#
# The five nearest, as flagged sets, for ZQX000's probable cause: {FA, FD}, {FE}, {FA}, {FA},
# {FE, FC}. Commonest set {FA}; nearest {FA, FD}; at least two {FA, FE} (FA three times, FE two).
# Against own {FB, FC, FD}:
#   {FA}      recall 0, 1/3, 1/2; precision 0, 1, 1
#   {FA, FD}  recall 1/3, 2/3, 1; precision 1/2, 1, 1
#   {FA, FE}  recall 0, 1/3, 1/2; precision 0, 1/2, 1/2
# ZQX006's probable cause finds P013 {} and P012 {FA}: commonest {FA}, nearest {FA}, no code
# twice: none. ZQX004 and ZQX005 find no flagged set at all: none for all three predictors.
#
# The whole pool leaves out only P008 and P032, the pool cases on the judged day (2016-06-01), and
# ranks the later ones, P007 and P031 (2017):
#   ZQX000's probable cause "brambleton": P001 and P007 tie at length 1 (by id, P001 first), then
#     P002, P003, P004; P005 and P006 drop out of the five; P008 (the judged day, {FB}, which would
#     rank third) is never ranked. The five: {FA, FD}, {FB}, {FE}, {FA}, {FA}. Commonest {FA};
#     nearest {FA, FD}; at least two {FA} (three cases hold it). Against own {FB, FC, FD}:
#     {FA, FD} as above, and {FA} as above: recall 0, 1/3, 1/2; precision 0, 1, 1.
#   ZQX005's probable cause "thistlecomb": only P031 (2017, {FA}) is ranked; P032, the judged
#     day, is not. Commonest {FA}, nearest {FA}, at least two none. Against own {FD}: recall 0,
#     precision 0 at each digit count.
#   ZQX004 ("thistlebrook") and ZQX006 ("marrowfat") find what they found before.
# Evidence narratives: ZQX000's "quillfern" and ZQX006's "marrowfat" as before; ZQX005's
#   "brambleton" finds the same five as ZQX000's probable cause.


def _pool_rows() -> list[_Row]:
    return [
        _row("ZQP001", "2010-03-01", "brambleton", (_FA, _FD)),
        _row("ZQP002", "2011-03-01", "brambleton gallimaufry", (_FE,)),
        _row("ZQP003", "2012-03-01", "brambleton gallimaufry stoat", (_FA,)),
        _row("ZQP004", "2013-03-01", "brambleton gallimaufry stoat tangle", (_FA,)),
        _row("ZQP005", "2014-03-01", "brambleton gallimaufry stoat tangle quillfern", (_FE, _FC)),
        _row(
            "ZQP006",
            "2015-03-01",
            "brambleton gallimaufry stoat tangle quillfern zorvexine",
            (_FB, _FD, _FC),
        ),
        _row("ZQP007", "2017-03-01", "brambleton", (_FB,)),
        _row("ZQP008", _DAY, "brambleton", (_FB,)),
        _row("ZQP012", "2011-05-01", "zephyrine marrowfat", (_FA,)),
        _row("ZQP013", "2012-05-01", "marrowfat", ()),
        _row("ZQP021", "2010-05-01", "thistlebrook", ()),
        _row("ZQP022", "2011-06-01", "thistlebrook stoat", ()),
        _row("ZQP031", "2017-05-01", "thistlecomb", (_FA,)),
        _row("ZQP032", _DAY, "thistlecomb", (_FA,)),
        _row("ZQN001", "2012-07-01", "", (_FA,)),
        _row("ZQN002", "2012-08-01", "brambleton", (_FA,), codes=()),
        _row(_SEALED, "2012-09-01", "brambleton", (_FB,)),
        _row("ZQI001", "2012-10-01", "brambleton", (_FB,), klass="I"),
        _row("ZQH001", "2021-01-01", "brambleton", (_FB,), split="heldout"),
    ]


def _all_rows() -> list[_Row]:
    return [*_pool_rows(), *(_row(case_id, _DAY, "judged", (_FA,)) for case_id in _IDS)]


def _run_a() -> list[CaseResult]:
    return [
        _one(
            "ZQX000",
            (_FB, _FC, _FD),
            cause="brambleton",
            narrative="quillfern",
            loop=_loop(0.0, None, 0.0, None, 0.0, None),
        ),
        _one("ZQX001", failed=True),
        _one("ZQX002", abstain=True, cause="brambleton"),
        _one("ZQX003", (), cause="brambleton"),
        _one(
            "ZQX004",
            (_FA, _FB),
            cause="thistlebrook",
            narrative="thistlebrook",
            loop=_loop(0.5, 0.5, 0.5, 0.5, 1.0, 1.0),
        ),
        _one("ZQX005", (_FD,), cause="thistlecomb", narrative="brambleton"),
        _one(
            "ZQX006",
            (_FA,),
            cause="marrowfat",
            narrative="marrowfat",
            loop=_loop(1.0, 0.5, 1.0, 0.5, 1.0, 0.5),
        ),
        _one("ZQX007", (), failed=True),
    ]


def _run_b() -> list[CaseResult]:
    cases = _run_a()
    cases[5] = _one("ZQX005", (_FD,), cause="marrowfat", narrative="marrowfat")
    cases[6] = _one("ZQX006", (_FA,), failed=True)
    return cases


def _sample_ids(name: str) -> tuple[str, ...]:
    return {"dev-400": _IDS, "dev-seal-400": (), "dev-seal-s3-400": (_SEALED,)}.get(name, ())


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run a and run b under the runs folder, the processed file, and the sample lists."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", _sample_ids)
    _processed(tmp_path, _all_rows())
    _write_run(folder, _RUN_A, _run_a())
    _write_run(folder, _RUN_B, _run_b())
    return folder


def _argv(*extra: str) -> list[str]:
    return ["--runs", _RUN_A, _RUN_B, *extra]


def _report(argv: Sequence[str], capsys: pytest.CaptureFixture[str]) -> str:
    assert fp.main(argv) == 0
    return capsys.readouterr().out


def _section(text: str, start: str, end: str | None = None) -> str:
    begin = text.index(start)
    stop = text.find(end, begin + 1) if end is not None else -1
    return text[begin : stop if stop != -1 else len(text)]


def _pct(values: Sequence[float]) -> str:
    mean, low, high = bootstrap_mean(list(values))
    return f"{mean:.1%} [{low:.1%}, {high:.1%}]"


def _signed(values: Sequence[float]) -> str:
    mean, low, high = bootstrap_mean(list(values))
    return f"{mean:+.1%} [{low:+.1%}, {high:+.1%}]"


def _diff(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [x - y for x, y in zip(a, b, strict=True)]


class TestReport:
    def test_the_head_comes_first_then_the_rule_the_method_and_each_run(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        assert text.startswith(
            "S3.1 findings-from-precedent probe on dev-400 (scripts/exploratory/"
        )
        assert f"run a = {_RUN_A}\nrun b = {_RUN_B} (printed beside run a; decides nothing)" in text
        marks = [
            "## The rule",
            "## Second reading under the whole pool",
            "## Method",
            f"## Run a ({_RUN_A})\n",
            f"## Run a ({_RUN_A}), whole pool\n",
            f"## Run b ({_RUN_B}), beside run a; decides nothing\n",
            f"## Run b ({_RUN_B}), beside run a; decides nothing, whole pool\n",
        ]
        positions = [text.index(mark) for mark in marks]
        assert positions == sorted(positions)
        assert len(set(positions)) == len(marks)

    def test_the_rule_is_applied_to_run_a_and_the_word_printed(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rule = _section(_report(_argv(), capsys), "## The rule", "## Second reading")
        assert fp.RULE in rule
        assert (
            "the probable-cause query, the commonest-set predictor, all judged cases "
            "(4 of 8 cases):"
        ) in rule
        # Recall at 10 digits, probable cause, commonest set {FA}: 0 0 0 1 against the loop's
        # 0 0.5 1 1. Precision, where both are defined: ZQX006 only, 1 against 0.5.
        assert (
            f"predictor less loop: {_signed(_diff([0, 0, 0, 1], [0, 0.5, 1, 1]))} (n = 4 cases)"
            in rule
        )
        assert "predictor less loop: +50.0% [+50.0%, +50.0%] (n = 1 cases where both" in rule
        assert "higher in 0, equal in 2, lower in 2 of 4 judged cases" in rule
        assert rule.count("Outcome:") == 1
        assert "Outcome: not promising" in rule
        assert "The expectation was not met." in rule

    def test_the_cases_of_each_run_are_counted_once_each(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        a = _section(text, f"## Run a ({_RUN_A})", "## Run b")
        assert (
            "Cases in the run: 8, each counted once, in this order: failed 2; abstained 1; "
            "no flagged finding 1; judged 4 (2 fatal, 2 non-fatal)." in a
        )
        b = _section(text, "## Run b")
        assert (
            "Cases in the run: 8, each counted once, in this order: failed 3; abstained 1; "
            "no flagged finding 1; judged 3 (1 fatal, 2 non-fatal)." in b
        )

    def test_the_loops_own_scores_are_the_stored_ones_on_the_judged_cases(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), "### All judged cases", "### Fatal cases")
        own = _section(a, "The loop's own findings", "probable cause query")
        assert f"- mean recall at 10 digits: {_pct([0, 0.5, 1, 1])} (n = 4)" in own
        assert f"- mean recall at 6 digits: {_pct([0, 1, 1, 1])} (n = 4)" in own
        # ZQX000's precision is None (the loop named nothing): left out and counted.
        assert (
            f"- mean precision at 10 digits: {_pct([0.5, 1, 0.5])} "
            "(n = 3 cases where the loop named a finding; 1 left out)" in own
        )

    def test_the_headline_block_is_scored_case_by_case(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), "### All judged cases", "### Fatal cases")
        block = _section(a, "probable cause query, commonest set predictor (headline):", "nearest")
        loop10, loop8, loop6 = [0, 0.5, 1, 1], [0, 0.5, 1, 1], [0, 1, 1, 1]
        for digits, mine, loop in (
            (10, [0, 0, 0, 1], loop10),
            (8, [1 / 3, 0, 0, 1], loop8),
            (6, [1 / 2, 0, 0, 1], loop6),
        ):
            assert (
                f"- mean recall at {digits} digits: {_pct(mine)} (n = 4); paired difference, "
                f"predictor less loop: {_signed(_diff(mine, loop))} (n = 4)"
            ) in block
        # Precision: the predictor has a set for ZQX000 and ZQX006 only. Paired with the loop's
        # where both are defined: ZQX006 (the loop's is 0.5).
        assert (
            f"- mean precision at 10 digits: {_pct([0, 1])} (n = 2 cases with a prediction); "
            f"paired difference, predictor less loop: {_signed([0.5])} "
            "(n = 1 cases where both are defined)"
        ) in block
        assert (
            f"- mean precision at 8 digits: {_pct([1, 1])} (n = 2 cases with a prediction); "
            f"paired difference, predictor less loop: {_signed([0.5])} "
        ) in block
        assert (
            "- no prediction: 2 of 4 judged cases (recall counted 0, precision left out)" in block
        )

    def test_the_nearest_and_the_at_least_two_predictors(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), "### All judged cases", "### Fatal cases")
        near = _section(a, "probable cause query, nearest predictor:", "probable cause query, at")
        loop = [0, 0.5, 1, 1]
        assert (
            f"- mean recall at 10 digits: {_pct([1 / 3, 0, 0, 1])} (n = 4); paired difference, "
            f"predictor less loop: {_signed(_diff([1 / 3, 0, 0, 1], loop))}" in near
        )
        assert f"- mean recall at 8 digits: {_pct([2 / 3, 0, 0, 1])} (n = 4)" in near
        assert f"- mean precision at 10 digits: {_pct([1 / 2, 1])} (n = 2 cases" in near
        assert "- no prediction: 2 of 4 judged cases" in near
        two = _section(
            a, "probable cause query, at least two predictor:", "evidence narrative query"
        )
        assert f"- mean recall at 8 digits: {_pct([1 / 3, 0, 0, 0])} (n = 4)" in two
        assert (
            f"- mean precision at 8 digits: {_pct([1 / 2])} (n = 1 cases with a prediction)" in two
        )
        # The one case with a set has no loop precision: no pair at all.
        assert "predictor less loop: none (n = 0 cases where both are defined)" in two
        assert "- no prediction: 3 of 4 judged cases" in two

    def test_the_evidence_narrative_is_the_other_query(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), "### All judged cases", "### Fatal cases")
        block = _section(
            a,
            "evidence narrative query, commonest set predictor:",
            "evidence narrative query, nearest",
        )
        # ZQX000 (quillfern: P005 and P006 tie once each, P005 ranked first: {FE, FC}) recall
        # 1/3 at 10 digits; ZQX004 none; ZQX005 (brambleton: {FA}) 0; ZQX006 {FA} 1.
        assert f"- mean recall at 10 digits: {_pct([1 / 3, 0, 0, 1])} (n = 4)" in block

    def test_fatal_and_non_fatal_cases_are_measured_apart(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        a = _section(text, f"## Run a ({_RUN_A})", "## Run b")
        fatal = _section(a, "### Fatal cases: 2 judged", "### Non-fatal cases")
        non_fatal = _section(a, "### Non-fatal cases: 2 judged", None)
        own = _section(fatal, "The loop's own findings", "probable cause query")
        assert f"- mean recall at 10 digits: {_pct([0, 1])} (n = 2)" in own
        head = _section(
            fatal, "probable cause query, commonest set predictor (headline):", "nearest"
        )
        # ZQX000 and ZQX006: recall 0 and 1 against the loop's 0 and 1: no difference.
        assert f"- mean recall at 10 digits: {_pct([0, 1])} (n = 2); paired difference" in head
        assert f"predictor less loop: {_signed([0, 0])} (n = 2)" in head
        assert "- no prediction: 0 of 2 judged cases" in head
        quiet = _section(
            non_fatal, "probable cause query, commonest set predictor (headline):", "nearest"
        )
        # ZQX004 and ZQX005 have no set: recall 0 against the loop's 0.5 and 1.
        assert f"predictor less loop: {_signed([-0.5, -1])} (n = 2)" in quiet
        assert "- mean precision at 10 digits: none (n = 0 cases with a prediction)" in quiet
        assert "- no prediction: 2 of 2 judged cases" in quiet

    def test_run_b_is_scored_on_its_own_judged_cases(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        b = _section(_report(_argv(), capsys), f"## Run b ({_RUN_B})")
        head = _section(
            _section(b, "### All judged cases", "### Fatal cases"),
            "probable cause query, commonest set predictor (headline):",
            "nearest",
        )
        # Judged: ZQX000 {FA} against own {FB, FC, FD}: recall 0; ZQX004 none; ZQX005 now finds
        # {FA} (marrowfat) against own {FD}: recall 0. The loop's recall: 0, 0.5, 1.
        loop = [0, 0.5, 1]
        assert (
            f"- mean recall at 10 digits: {_pct([0, 0, 0])} (n = 3); paired difference, "
            f"predictor less loop: {_signed(_diff([0, 0, 0], loop))} (n = 3)"
        ) in head
        # Precision: ZQX000 and ZQX005 have a set, with precision 0 at 10 digits; paired where
        # the loop's is defined: ZQX005 only (the loop's is 1).
        assert (
            f"- mean precision at 10 digits: {_pct([0, 0])} (n = 2 cases with a prediction); "
            f"paired difference, predictor less loop: {_signed([-1.0])} "
        ) in head
        assert "- no prediction: 1 of 3 judged cases" in head

    def test_the_date_limit_reaches_the_search_through_the_reused_index(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # ZQX005's probable cause words are only in a later and a same-day pool case: no
        # earlier case, so its commonest set is none. If they were ranked, {FA} would be
        # predicted and only one case (ZQX004's all-empty five) would have none.
        a = _section(_report(_argv(), capsys), "### All judged cases", "### Fatal cases")
        block = _section(a, "probable cause query, commonest set predictor (headline):", "nearest")
        assert "- no prediction: 2 of 4 judged cases" in block

    def test_the_sealed_the_wrong_class_and_the_held_out_cases_never_reach_the_pool(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Their "brambleton" and {FB} would rank among ZQX000's five and change its sets."""
        text = _report(_argv(), capsys)
        method = _section(text, "## Method", "## Run a")
        assert f"the S3 statistics pool, {cs.STAGES['s3'].built_from}: 16 cases;" in method
        assert "occurrence code: 14 (event years 2010-2017); left out: 1 with no" in method
        assert "1 more with no occurrence code." in method
        assert "Of the kept cases 11 have at least one finding flagged as cause." in method
        # ZQX000's commonest set is {FA}: recall 0 at 10 digits, 1/3 at 8; with {FB} it would
        # be held by the extra cases and win.
        a = _section(text, "### All judged cases", "### Fatal cases")
        block = _section(a, "probable cause query, commonest set predictor (headline):", "nearest")
        assert f"- mean recall at 8 digits: {_pct([1 / 3, 0, 0, 1])} (n = 4)" in block

    def test_the_method_states_the_search_the_predictors_and_the_scores(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        method = _section(_report(_argv(), capsys), "## Method", "## Run a")
        assert "BM25 (k1 = 1.2, b = 0.75)" in method
        assert f"less {len(pp.STOP_WORDS)} English stop words" in method
        assert "strictly earlier than the judged case's" in method
        for name, meaning in fp.PREDICTOR_MEANINGS.items():
            assert f"- {name}: {meaning}" in method
        assert "``scoring.metrics._precision_recall``" in method
        assert "the date limit uses the event date" in method.lower()

    def test_no_case_number_no_case_id_no_code_and_no_record_text_is_printed(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        assert not _CASE_NUMBER.search(text)
        assert "ZQ" not in text
        for word in _WORDS:
            assert word not in text.lower()
        for code in (_FA, _FB, _FC, _FD, _FE):
            assert code not in text
            assert code[:8] not in text

    def test_out_writes_the_same_text_and_the_text_does_not_depend_on_it(
        self, runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain = _report(_argv(), capsys)
        out = tmp_path / "results" / "s3-finding-precedent-dev.txt"
        written = _report(_argv("--out", str(out)), capsys)
        assert written == plain
        assert out.read_text() == plain

    def test_the_report_is_the_same_on_a_second_run(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _report(_argv(), capsys) == _report(_argv(), capsys)


def _run_block(text: str, letter: str, *, whole: bool) -> str:
    """Run ``letter``'s block of the report on one pool: from its ``## Run`` heading to the next."""
    lines = text.split("\n")
    start = next(
        i
        for i, line in enumerate(lines)
        if line.startswith(f"## Run {letter} (") and line.endswith(", whole pool") == whole
    )
    stop = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:stop])


def _whole_pool(text: str, letter: str = "a") -> str:
    """Run ``letter``'s whole-pool block."""
    return _run_block(text, letter, whole=True)


class TestReportWholePool:
    """The whole-pool figures, for every run, query and predictor, scored case by case."""

    def test_the_second_reading_is_applied_to_the_whole_pool_figures_of_run_a(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        reading = _section(text, "## Second reading under the whole pool", "## Method")
        assert (
            "the probable-cause query, the commonest-set predictor, all judged cases "
            "(4 of 8 cases), whole pool:"
        ) in reading
        # Recall at 10 digits is the date-limited figure's again (ZQX005 has a set, {FA}, but
        # recall 0 as with none); the precision pairs are not: ZQX005's {FA} has precision 0
        # against the loop's 1, and ZQX006's 1 against 0.5; ZQX000's loop named nothing.
        assert (
            f"predictor less loop: {_signed(_diff([0, 0, 0, 1], [0, 0.5, 1, 1]))} (n = 4 cases)"
            in reading
        )
        assert (
            f"predictor less loop: {_signed([-1.0, 0.5])} (n = 2 cases where both precisions"
            in reading
        )
        assert "higher in 0, equal in 2, lower in 2 of 4 judged cases" in reading
        # Run b, beside: ZQX000, ZQX004 and ZQX005 judged; recall 0 0 0 against 0 0.5 1; the one
        # precision pair is ZQX005's, 0 against 1.
        assert (
            f"Run b ({_RUN_B}), beside it, decides nothing: recall difference "
            f"{_signed(_diff([0, 0, 0], [0, 0.5, 1]))} (n = 3); precision difference "
            f"{_signed([-1.0])} (n = 1)"
        ) in reading
        assert reading.count("outcome:") == 1
        assert "Second reading outcome: not promising" in reading
        assert "Outcome:" not in reading
        assert fp.EXPECTATION not in reading
        assert "The expectation was" not in reading

    def test_the_committed_rule_block_is_still_the_date_limited_reading(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rule = _section(_report(_argv(), capsys), "## The rule", "## Second reading")
        # ZQX005's words are only in a later and a same-day case: no date-limited precedent, so
        # the precision pair is ZQX006's alone, as before the whole pool existed.
        assert "predictor less loop: +50.0% [+50.0%, +50.0%] (n = 1 cases where both" in rule
        assert "Outcome: not promising" in rule

    def test_both_pools_are_printed_for_each_run_with_every_set_of_cases(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        for letter, ids in (("a", (4, 2, 2)), ("b", (3, 1, 2))):
            whole = _whole_pool(text, letter)
            assert whole.startswith(f"## Run {letter} (")
            assert "Pool: the whole pool, a second reading (registered in bb5155b" in whole
            assert "the same as in the date-limited block." in whole
            headings = [line for line in whole.splitlines() if line.startswith("### ")]
            assert headings == [
                f"### All judged cases: {ids[0]} judged",
                f"### Fatal cases: {ids[1]} judged",
                f"### Non-fatal cases: {ids[2]} judged",
            ]
            # Every set of cases holds the loop's own findings and the six query and predictor
            # blocks.
            assert whole.count("The loop's own findings, from its stored scores:") == 3
            for query in ("probable cause", "evidence narrative"):
                for name in ("commonest set", "nearest", "at least two"):
                    assert whole.count(f"{query} query, {name} predictor") == 3
            date_limited = _run_block(text, letter, whole=False)
            assert "Pool: the date-limited pool, as committed" in date_limited
            assert date_limited != whole

    def test_the_headline_block_is_scored_case_by_case_on_the_whole_pool(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _whole_pool(_report(_argv(), capsys))
        a = _section(text, "### All judged cases", "### Fatal cases")
        block = _section(a, "probable cause query, commonest set predictor (headline):", "nearest")
        loop10, loop8, loop6 = [0, 0.5, 1, 1], [0, 0.5, 1, 1], [0, 1, 1, 1]
        # ZQX000 {FA} (the same day's {FB} not ranked: with it the commonest set would be {FB}
        # and recall at 10 digits 1/3); ZQX004 none; ZQX005 {FA}, from the later case; ZQX006 {FA}.
        for digits, mine, loop in (
            (10, [0, 0, 0, 1], loop10),
            (8, [1 / 3, 0, 0, 1], loop8),
            (6, [1 / 2, 0, 0, 1], loop6),
        ):
            assert (
                f"- mean recall at {digits} digits: {_pct(mine)} (n = 4); paired difference, "
                f"predictor less loop: {_signed(_diff(mine, loop))} (n = 4)"
            ) in block
        # Precision: the predictor has a set for ZQX000 (0 at 10 digits), ZQX005 (0) and ZQX006
        # (1); paired where both are defined: ZQX005 (0 against 1) and ZQX006 (1 against 0.5).
        assert (
            f"- mean precision at 10 digits: {_pct([0, 0, 1])} (n = 3 cases with a prediction); "
            f"paired difference, predictor less loop: {_signed([-1.0, 0.5])} "
            "(n = 2 cases where both are defined)"
        ) in block
        assert (
            f"- mean precision at 8 digits: {_pct([1, 0, 1])} (n = 3 cases with a prediction); "
            f"paired difference, predictor less loop: {_signed([-1.0, 0.5])} "
        ) in block
        assert (
            "- no prediction: 1 of 4 judged cases (recall counted 0, precision left out)" in block
        )

    def test_the_nearest_and_the_at_least_two_predictors_on_the_whole_pool(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_whole_pool(_report(_argv(), capsys)), "### All judged cases", "### Fatal")
        near = _section(a, "probable cause query, nearest predictor:", "probable cause query, at")
        loop = [0, 0.5, 1, 1]
        assert (
            f"- mean recall at 10 digits: {_pct([1 / 3, 0, 0, 1])} (n = 4); paired difference, "
            f"predictor less loop: {_signed(_diff([1 / 3, 0, 0, 1], loop))}" in near
        )
        assert f"- mean precision at 10 digits: {_pct([1 / 2, 0, 1])} (n = 3 cases" in near
        assert "- no prediction: 1 of 4 judged cases" in near
        two = _section(
            a, "probable cause query, at least two predictor:", "evidence narrative query"
        )
        # ZQX000's {FA} is held by three of its five (P001, P003, P004): at least two. The date
        # limit gave {FA, FE}, whose precision at 8 digits was 1/2. ZQX005's one later case
        # gives no code twice, and the same-day case is not ranked (with it, {FA} would be two).
        assert f"- mean recall at 8 digits: {_pct([1 / 3, 0, 0, 0])} (n = 4)" in two
        assert f"- mean precision at 8 digits: {_pct([1])} (n = 1 cases with a prediction)" in two
        assert "predictor less loop: none (n = 0 cases where both are defined)" in two
        assert "- no prediction: 3 of 4 judged cases" in two

    def test_the_evidence_narrative_is_the_other_query_on_the_whole_pool(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_whole_pool(_report(_argv(), capsys)), "### All judged cases", "### Fatal")
        block = _section(
            a,
            "evidence narrative query, commonest set predictor:",
            "evidence narrative query, nearest",
        )
        # ZQX000 (quillfern: {FE, FC}) 1/3; ZQX004 none; ZQX005 (brambleton: {FA}) 0; ZQX006 1.
        assert f"- mean recall at 10 digits: {_pct([1 / 3, 0, 0, 1])} (n = 4)" in block

    def test_fatal_and_non_fatal_cases_are_measured_apart_on_the_whole_pool(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _whole_pool(_report(_argv(), capsys))
        fatal = _section(a, "### Fatal cases: 2 judged", "### Non-fatal cases")
        non_fatal = _section(a, "### Non-fatal cases: 2 judged", None)
        head = _section(
            fatal, "probable cause query, commonest set predictor (headline):", "nearest"
        )
        # ZQX000 and ZQX006: recall 0 and 1 against the loop's 0 and 1.
        assert f"predictor less loop: {_signed([0, 0])} (n = 2)" in head
        assert "- no prediction: 0 of 2 judged cases" in head
        quiet = _section(
            non_fatal, "probable cause query, commonest set predictor (headline):", "nearest"
        )
        # ZQX004 has no set; ZQX005 has {FA} from the later case (recall 0, precision 0): recall 0
        # against the loop's 0.5 and 1; the one precision pair is ZQX005's, 0 against 1.
        assert f"predictor less loop: {_signed([-0.5, -1])} (n = 2)" in quiet
        assert (
            f"- mean precision at 10 digits: {_pct([0])} (n = 1 cases with a prediction)" in quiet
        )
        assert f"paired difference, predictor less loop: {_signed([-1.0])} " in quiet
        assert "- no prediction: 1 of 2 judged cases" in quiet

    def test_run_b_is_scored_on_its_own_judged_cases_on_the_whole_pool(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        b = _whole_pool(_report(_argv(), capsys), "b")
        head = _section(
            _section(b, "### All judged cases", "### Fatal cases"),
            "probable cause query, commonest set predictor (headline):",
            "nearest",
        )
        loop = [0, 0.5, 1]
        assert (
            f"- mean recall at 10 digits: {_pct([0, 0, 0])} (n = 3); paired difference, "
            f"predictor less loop: {_signed(_diff([0, 0, 0], loop))} (n = 3)"
        ) in head
        assert (
            f"- mean precision at 10 digits: {_pct([0, 0])} (n = 2 cases with a prediction); "
            f"paired difference, predictor less loop: {_signed([-1.0])} "
        ) in head
        assert "- no prediction: 1 of 3 judged cases" in head

    def test_a_pool_case_on_the_judged_date_is_never_ranked_and_a_later_one_can_be(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        whole = _section(_whole_pool(text), "### All judged cases", "### Fatal cases")
        early = _section(_run_block(text, "a", whole=False), "### All judged", "### Fatal cases")
        # Later cases: ZQX005 has a precedent on the whole pool (P031) and not on the
        # date-limited one: one fewer case without a prediction.
        assert "- no prediction: 2 of 4 judged cases (recall" in _section(
            early, "headline", "nearest"
        )
        assert "- no prediction: 1 of 4 judged cases (recall" in _section(
            whole, "headline", "nearest"
        )
        # The same-day cases, P008 and P032, are not ranked: P032 would be a second case holding
        # {FA} for ZQX005 (so ``at least two`` would give a set and 2 of 4 no prediction), and P008
        # would make ZQX000's commonest set {FB} (recall 1/3 at 10 digits, not 0).
        assert "- no prediction: 3 of 4 judged cases" in _section(
            whole, "probable cause query, at least two predictor:", "evidence narrative query"
        )
        assert f"- mean recall at 10 digits: {_pct([0, 0, 0, 1])} (n = 4)" in _section(
            whole, "headline", "nearest"
        )

    def test_the_method_states_the_whole_pool_definition(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        method = _section(_report(_argv(), capsys), "## Method", "## Run a")
        assert (
            "Whole pool (a second reading, registered in bb5155b after the first result" in method
        )
        assert "development work reads the whole pool" in method
        assert "the date-limited figures staying beside as a sensitivity check" in method
        assert "over every pool case except those on the judged case's own event date" in method
        assert "N, df and the average length over that set" in method
        assert "`Index.search` on its `whole` pool, not rewritten here" in method
        assert "The second reading, above, applies that rule again on the whole pool" in method
        # The committed definition and its limits are still there, word for word.
        assert "strictly earlier than the judged case's (N, df and the average length" in method
        assert "the date limit uses the event date" in method.lower()


# --------------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------------


class TestRefusals:
    def test_an_arm_b_run_is_refused(self, runs: Path) -> None:
        _write_run(runs, _RUN_B, _run_b(), arm="B")
        with pytest.raises(SystemExit, match="arm B; the precedent probe reads arm C runs only"):
            fp.main(_argv())

    def test_a_run_named_twice_is_refused(self, runs: Path) -> None:
        with pytest.raises(SystemExit, match="named twice"):
            fp.main(["--runs", _RUN_A, _RUN_A])

    def test_one_run_is_a_usage_error(self, runs: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            fp.main(["--runs", _RUN_A])
        assert raised.value.code == 2

    def test_a_held_out_run_id_is_refused(self, runs: Path) -> None:
        with pytest.raises(SystemExit, match="held-out"):
            fp.main(["--runs", "20260101T000000-abc1234-heldout-400-C", _RUN_B])

    def test_a_run_whose_record_names_the_held_out_sample_is_refused(self, runs: Path) -> None:
        _write_run(runs, _RUN_B, _run_b(), sample="heldout-400")
        with pytest.raises(SystemExit, match="held-out"):
            fp.main(_argv())

    def test_a_sealed_sample_not_yet_opened_is_refused_as_sealed(
        self, runs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
        _write_run(runs, _RUN_B, _run_b(), sample="dev-seal-s3-400")
        with pytest.raises(SystemExit, match="sealed"):
            fp.main(_argv())

    @pytest.mark.parametrize("sample", ["dev-seal-400", "dev-seal-s3-400"])
    def test_a_sealed_sample_is_refused_even_once_its_registration_is_committed(
        self, runs: Path, monkeypatch: pytest.MonkeyPatch, sample: str
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
        _write_run(runs, _RUN_B, _run_b(), sample=sample)
        with pytest.raises(SystemExit, match="dev-400 only"):
            fp.main(_argv())

    def test_an_unfinished_run_is_refused(self, runs: Path) -> None:
        _write_run(runs, _RUN_A, _run_a(), finished=None)
        with pytest.raises(SystemExit, match="has not finished"):
            fp.main(_argv())

    def test_a_partial_run_is_refused(self, runs: Path) -> None:
        _write_run(runs, _RUN_A, _run_a()[:-1])
        with pytest.raises(SystemExit, match="not the whole of dev-400"):
            fp.main(_argv())

    def test_a_run_holding_a_case_outside_the_development_split_is_refused(
        self, runs: Path
    ) -> None:
        cases = _run_a()
        cases[0] = cases[0].model_copy(update={"split": "heldout"})
        _write_run(runs, _RUN_A, cases)
        with pytest.raises(SystemExit, match="outside the dev split"):
            fp.main(_argv())

    def test_a_missing_run_folder_is_refused(self, runs: Path) -> None:
        with pytest.raises(SystemExit, match=r"no run\.jsonl"):
            fp.main(["--runs", _RUN_A, "20261001T999999-fd6053f-dev-400-C"])

    def test_a_judged_case_with_no_event_date_is_refused(self, runs: Path, tmp_path: Path) -> None:
        _processed(tmp_path, [row for row in _all_rows() if row[0] != "ZQX004"])
        with pytest.raises(SystemExit, match="1 judged case"):
            fp.main(_argv())

    def test_a_case_not_judged_needs_no_event_date(
        self, runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # ZQX003 has no flagged finding: it is counted, not searched, so its date is not needed.
        _processed(tmp_path, [row for row in _all_rows() if row[0] != "ZQX003"])
        assert "no flagged finding 1; judged 4" in _report(_argv(), capsys)

    def test_a_judged_case_with_no_stored_recall_is_refused(self, runs: Path) -> None:
        cases = _run_a()
        cases[4] = _one("ZQX004", (_FA, _FB), cause="thistlebrook", loop=_loop(r10=None))
        _write_run(runs, _RUN_A, cases)
        with pytest.raises(SystemExit, match="hold no finding recall"):
            fp.main(_argv())

    def test_a_pool_holding_a_sample_case_raises_through_check_pool_and_prints_nothing(
        self,
        runs: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A pool built without the exclusions holds dev-400 and the sealed case: refused."""
        texts: list[str] = []
        findings: list[str] = []
        real_text, real_findings = fields.probable_cause, fields.finding_codes_in_cause

        def text_spy(raw: Mapping[str, object]) -> str | None:
            texts.append("read")
            return real_text(raw)

        def findings_spy(raw: Mapping[str, object]) -> tuple[str, ...]:
            findings.append("read")
            return real_findings(raw)

        monkeypatch.setattr(
            pp, "pool_cases", lambda rows, *, excluded: cs.pool_cases(rows, excluded=frozenset())
        )
        monkeypatch.setattr(fields, "probable_cause", text_spy)
        monkeypatch.setattr(fields, "finding_codes_in_cause", findings_spy)
        with pytest.raises(LeakageError, match=_SEALED):
            fp.main(_argv())
        assert capsys.readouterr().out == ""
        assert texts == []  # no pool text was read
        # Only the pool's own pass read findings, one case each (development, class C/F/L), not
        # the pass after check_pool that reads the kept cases' texts and findings again.
        in_pool = sum(1 for row in _all_rows() if row[2] == "dev" and row[3] in {"C", "F", "L"})
        assert len(findings) == in_pool
