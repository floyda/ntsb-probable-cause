"""scripts/exploratory/s3_finding_consistency.py: how far the cause sentence settles the findings.

S3.1 Task 15, exploratory. A processed file of invented cases (invented ids, invented words, real
code labels), whose twins, flagged findings, predictions and measures are worked out by hand in
the comments. Offline: no network, no model.
"""

import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest
from scripts import coding_stats as cs
from scripts.exploratory import s3_coding_consistency as cc
from scripts.exploratory import s3_finding_consistency as fc
from scripts.exploratory import s3_precedent_probe as pp
from scripts.s3_trail_pages import REPOSITORY
from tests.test_coding_stats import _CASE_NUMBER
from tests.test_s3_precedent_probe import _processed

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import load_tables

_FA = "0101051001"  # Time limits / Failure
_FB = "0101051000"  # the same item, Unknown/Not determined: same first 8 digits as _FA
_FC = "0101052001"  # another item of the same category: same first 6 digits as _FA only
_FD = "0102271001"  # Aileron control system / Failure
_FE = "0201101001"  # Size / Failure
# Sorted: _FB < _FA < _FC < _FD < _FE.

_CITED = "12 of 40 (30.0%) [17.5%, 46.1%]"
_SEALED = "ZQS001"
# Invented words: none is in the code tables' labels, so "no text in the output" is testable.
_WORDS = (
    "zephyrine",
    "marrowfat",
    "tangle",
    "gallimaufry",
    "stoat",
    "thistlecomb",
    "quillfern",
    "brambleton",
    "quillwort",
    "thistlebrook",
    "zorvexine",
)


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _case(case_id: str, day: str, *flagged: str, codes: str = "552230") -> pp.PoolText:
    return pp.PoolText(case_id, _day(day), "w", (codes,), tuple(flagged))


# --------------------------------------------------------------------------------------------
# The pool reader gives each case's flagged findings
# --------------------------------------------------------------------------------------------

type _Row = tuple[str, str, str, str, dict[str, object]]


def _raw(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    day: str,
    cause: str,
    codes: Sequence[str],
    *,
    flagged: Sequence[str],
    unflagged: Sequence[str] = (),
) -> dict[str, object]:
    findings: list[dict[str, object]] = [
        {"findingNumber": n, "findingCode": code, "inProbableCause": True}
        for n, code in enumerate(flagged, start=1)
    ]
    findings += [
        {"findingNumber": len(flagged) + n, "findingCode": code, "inProbableCause": False}
        for n, code in enumerate(unflagged, start=1)
    ]
    findings.reverse()  # the record's list is not in finding-number order
    events: list[dict[str, object]] = [
        {"eventCode": code, "isDefiningEvent": i == 0, "sequenceNumber": i + 1}
        for i, code in enumerate(codes)
    ]
    return {
        "ntsbNumber": case_id,
        "eventDate": f"{day}T00:00:00Z",
        "narratives": [{"probableCause": cause}],
        "aircrafts": [{"events": events, "findings": findings}],
    }


def _row(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    day: str,
    cause: str,
    flagged: Sequence[str],
    *,
    codes: Sequence[str] = ("552230",),
    unflagged: Sequence[str] = (),
    split: str = "dev",
    klass: str = "C",
) -> _Row:
    return (
        case_id,
        day,
        split,
        klass,
        _raw(case_id, day, cause, codes, flagged=flagged, unflagged=unflagged),
    )


# Kept pool, 17 cases (the statistics pool holds 19: one has no text, one no occurrence code):
#   exact (and loose) twins "The zephyrine's marrowfat tangle", spelled differently:
#     A001 2010 {FA, FD}; A002 2011 {FD, FA} (the same set); A005 2012 {FA}; A006 2013 {FA};
#     A003 2016 {FA}; A004 2017 none flagged (an unflagged finding FE is not a flagged one)
#   E001 2014-12-31 {FC} and E002 2015-01-01 {FC, FE}: "Gallimaufry stoat", across the eras' border
#   T001 2012 {FD}, T002 2013 {FE}, T003 2014 none: "Thistlecomb quillfern"
#   U001 2011 {FB}, U002 2012 {FA}: "Marrowfat gallimaufry"
#   B001 2012 {FA}, B002 2013 {FB}, C001 2010 {FD}: loose twins of three, in three word orders
#   D001 2015 {FA}: "Zorvexine", alone
# Left out of the pool: N001 (no text) and N002 (no occurrence code), both flagged {FA}, N002
# with the E sentence; ZQS001 (a sealed sample's case), I001 (class I) and H001 (held-out), all
# with the A sentence and {FE}, which would make the A group seven.
_A_TEXT = "The zephyrine\u2019s marrowfat tangle."


def _rows(*, with_u: bool = True) -> list[_Row]:
    rows = [
        _row("ZQA001", "2010-03-01", _A_TEXT, (_FA, _FD)),
        _row("ZQA002", "2011-03-01", "the ZEPHYRINE'S marrowfat   tangle", (_FD, _FA)),
        _row("ZQA005", "2012-03-01", "The zephyrine's marrowfat tangle", (_FA,)),
        _row("ZQA006", "2013-03-01", "The zephyrine\u2019s marrowfat tangle!", (_FA,)),
        _row("ZQA003", "2016-03-01", "The zephyrine's  marrowfat   tangle", (_FA,)),
        _row("ZQA004", "2017-03-01", _A_TEXT, (), unflagged=(_FE,)),
        _row("ZQB001", "2012-04-01", "Brambleton quillwort thistlebrook", (_FA,)),
        _row("ZQB002", "2013-04-01", "Quillwort brambleton thistlebrook", (_FB,)),
        _row("ZQC001", "2010-06-01", "Quillwort thistlebrook of the brambleton", (_FD,)),
        _row("ZQD001", "2015-03-01", "Zorvexine", (_FA,)),
        _row("ZQE001", "2014-12-31", "Gallimaufry stoat", (_FC,)),
        _row("ZQE002", "2015-01-01", "Gallimaufry stoat.", (_FC, _FE)),
        _row("ZQT001", "2012-05-01", "Thistlecomb quillfern", (_FD,)),
        _row("ZQT002", "2013-05-01", "Thistlecomb quillfern", (_FE,)),
        _row("ZQT003", "2014-05-01", "Thistlecomb quillfern", ()),
        _row("ZQN001", "2012-07-01", "", (_FA,), codes=("402192",)),
        _row("ZQN002", "2012-08-01", "Gallimaufry stoat", (_FA,), codes=()),
        _row(_SEALED, "2012-09-01", _A_TEXT, (_FE,)),
        _row("ZQI001", "2012-10-01", _A_TEXT, (_FE,), klass="I"),
        _row("ZQH001", "2021-01-01", _A_TEXT, (_FE,), split="heldout"),
    ]
    if with_u:
        rows += [
            _row("ZQU001", "2011-05-01", "Marrowfat gallimaufry", (_FB,)),
            _row("ZQU002", "2012-06-01", "Marrowfat gallimaufry.", (_FA,)),
        ]
    return rows


def _sample_ids(name: str) -> tuple[str, ...]:
    return {"dev-seal-s3-400": (_SEALED,)}.get(name, ())


def _install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: Sequence[_Row]) -> Path:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(samples, "sample_ids", _sample_ids)
    _processed(tmp_path, rows)
    return tmp_path


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The processed file of invented cases, under a temporary data folder."""
    return _install(tmp_path, monkeypatch, _rows())


def _results(tmp_path: Path, figure: str = _CITED) -> Path:
    path = tmp_path / "coding.txt"
    path.write_text(
        "S3.1 coding-consistency probe\n\n## The expectation\n\n"
        f"Headline: exact twins, all years, leave-one-out agreement on the six-digit first code: "
        f"{figure}\nexpectation met\n",
        encoding="utf-8",
    )
    return path


def _main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *argv: str, figure: str = _CITED
) -> str:
    """Run the script; return the printed report."""
    assert fc.main(list(argv), results=_results(tmp_path, figure)) == 0
    return capsys.readouterr().out.removesuffix("\n")


def _section(text: str, start: str, end: str | None = None) -> str:
    begin = text.index(start)
    stop = text.find(end, begin + 1) if end is not None else -1
    return text[begin : stop if stop != -1 else len(text)]


class TestPoolReader:
    def test_each_kept_case_carries_its_flagged_findings_by_finding_number(
        self, data: Path
    ) -> None:
        kept, _dates, counts = pp.read_pool_texts(data / "processed")
        by_id = {c.case_id: c for c in kept}
        assert len(kept) == 17
        assert counts == {"statistics pool": 19, "no text": 1, "no code": 1}
        assert by_id["ZQA001"].findings == (_FA, _FD)  # numbers 1 and 2
        assert by_id["ZQA002"].findings == (_FD, _FA)  # numbered the other way round
        assert by_id["ZQE002"].findings == (_FC, _FE)
        assert by_id["ZQA004"].findings == ()  # one finding, not flagged as cause
        assert by_id["ZQT003"].findings == ()

    def test_they_are_what_fields_reads_from_each_record(self, data: Path) -> None:
        kept, _dates, _counts = pp.read_pool_texts(data / "processed")
        raws = {row[0]: row[4] for row in _rows()}
        assert kept
        for case in kept:
            assert case.findings == fields.finding_codes_in_cause(raws[case.case_id])

    def test_a_pool_holding_a_sample_case_raises_through_check_pool_before_any_finding_is_read(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pool built without the exclusions holds the sealed case: refused, nothing read."""
        calls: list[str] = []
        real = fields.finding_codes_in_cause

        def spy(raw: Mapping[str, object]) -> tuple[str, ...]:
            calls.append("read")
            return real(raw)

        monkeypatch.setattr(
            pp, "pool_cases", lambda rows, *, excluded: cs.pool_cases(rows, excluded=frozenset())
        )
        monkeypatch.setattr(fields, "finding_codes_in_cause", spy)
        with pytest.raises(LeakageError, match=_SEALED):
            pp.read_pool_texts(data / "processed")
        # Only the pool's own pass (one read for each of its 20 cases) ran, not the pass after
        # check_pool that reads the texts and the findings again.
        assert len(calls) == 20


# --------------------------------------------------------------------------------------------
# The predicted set
# --------------------------------------------------------------------------------------------


class TestCommonestSet:
    def test_the_highest_count_wins(self) -> None:
        assert fc.commonest_set({(_FD,): 1, (_FA,): 3, (_FA, _FD): 2}) == (_FA,)

    def test_ties_go_to_the_smallest_sorted_tuple(self) -> None:
        assert fc.commonest_set({(_FD,): 2, (_FA, _FD): 2, (_FA,): 2}) == (_FA,)  # shorter first
        assert fc.commonest_set({(_FE,): 1, (_FD,): 1}) == (_FD,)

    def test_the_empty_set_wins_a_tie_and_loses_a_count(self) -> None:
        assert fc.commonest_set({(): 1, (_FA,): 1}) == ()
        assert fc.commonest_set({(): 1, (_FA,): 2}) == (_FA,)
        assert fc.commonest_set({(): 2, (_FA,): 1}) == ()

    def test_no_counts_is_none(self) -> None:
        assert fc.commonest_set({}) is None

    def test_a_case_flagged_set_is_sorted_and_without_repeats(self) -> None:
        assert fc.flagged(_case("ZQ1", "2010-01-01", _FD, _FA, _FD)) == (_FA, _FD)
        assert fc.flagged(_case("ZQ2", "2010-01-01")) == ()


class TestTwinSets:
    def test_the_commonest_set_among_the_others_with_ties_to_the_smallest(self) -> None:
        """Group A's six members: two {FA, FD}, three {FA}, one with none."""
        sets = [(_FA, _FD), (_FA, _FD), (_FA,), (_FA,), (_FA,), ()]
        predicted = fc.twin_sets(sets)
        assert predicted[(_FA, _FD)] == (_FA,)  # the others: {FA, FD} once, {FA} three times
        assert predicted[(_FA,)] == (_FA,)  # {FA, FD} twice and {FA} twice tie: {FA} is smaller
        assert predicted[()] == (_FA,)  # {FA} three times

    def test_the_empty_set_of_a_member_with_none_is_a_candidate_and_wins_a_tie(self) -> None:
        predicted = fc.twin_sets([(_FD,), (_FE,), ()])
        assert predicted[(_FD,)] == ()  # the others: {FE} and {} once each: {} is smaller
        assert predicted[(_FE,)] == ()
        assert predicted[()] == (_FD,)  # the others: {FD} and {FE}: {FD} is smaller

    def test_a_case_never_counts_among_its_own_others(self) -> None:
        # With the case itself, {FA} (twice) would win for the first; without it, {FD} does.
        assert fc.twin_sets([(_FA,), (_FA,), (_FD,), (_FD,)])[(_FA,)] == (_FD,)

    def test_a_pair_predicts_each_the_others_set_and_a_group_of_one_predicts_nothing(self) -> None:
        assert fc.twin_sets([(_FA,), (_FD, _FE)]) == {(_FA,): (_FD, _FE), (_FD, _FE): (_FA,)}
        assert fc.twin_sets([(_FA,)]) == {(_FA,): ()}


class TestTwinSingles:
    def test_the_commonest_code_among_the_others_each_member_counting_it_once(self) -> None:
        singles = fc.twin_singles([(_FA, _FD), (_FA, _FD), (_FA,), (_FA,), (_FA,), ()])
        assert singles[(_FA, _FD)] == _FA  # others hold FA four times and FD once
        assert singles[(_FA,)] == _FA  # FA four times (two {FA, FD}, two {FA}) and FD twice
        assert singles[()] == _FA

    def test_ties_go_to_the_smallest_code(self) -> None:
        assert fc.twin_singles([(_FE,), (_FD,), (_FB, _FA)])[(_FE,)] == _FB  # FD, FB, FA once each
        assert fc.twin_singles([(_FD,), (_FE,), ()])[()] == _FD

    def test_the_case_itself_does_not_count_and_none_is_none(self) -> None:
        assert fc.twin_singles([(_FA,), (_FA,), (_FD,)])[(_FD,)] == _FA
        assert fc.twin_singles([(_FA,), (_FA,), (_FD,)])[(_FA,)] == _FA  # the other {FA}, {FD}: tie
        assert fc.twin_singles([(_FA,), (), ()])[(_FA,)] is None  # nobody else holds a finding
        assert fc.twin_singles([(_FA,), (), ()])[()] == _FA


def _brute_set(pool: Sequence[tuple[str, ...]], index: int) -> tuple[str, ...]:
    others = Counter(s for i, s in enumerate(pool) if i != index and s)
    return min(others, key=lambda s: (-others[s], s)) if others else ()


def _brute_code(pool: Sequence[tuple[str, ...]], index: int) -> str | None:
    others = Counter(code for i, s in enumerate(pool) if i != index for code in s)
    return min(others, key=lambda c: (-others[c], c)) if others else None


class TestControl:
    def test_it_takes_the_case_itself_away(self) -> None:
        pool = [
            _case(f"ZQ{n}", "2010-01-01", *codes)
            for n, codes in enumerate([(_FA,)] * 2 + [(_FD,)] * 2)
        ]
        control = fc.Control(pool)
        # With itself, {FA} and {FD} tie at two and {FA} wins; without, {FD} leads {FA} 2 to 1.
        assert control.predicted((_FA,)) == (_FD,)
        assert control.predicted((_FD,)) == (_FA,)
        assert control.single((_FA,)) == _FD
        assert control.single((_FD,)) == _FA

    def test_empty_sets_are_never_the_predicted_set(self) -> None:
        pool = [
            _case(f"ZQ{n}", "2010-01-01", *codes) for n, codes in enumerate([(), (), (), (_FA,)])
        ]
        control = fc.Control(pool)
        assert control.predicted((_FA,)) == ()  # only empty sets are left: no prediction
        assert control.single((_FA,)) is None
        assert fc.Control(pool).predicted((_FD,)) == (_FA,)  # a case outside the pool

    def test_ties_go_to_the_smallest_set_and_code(self) -> None:
        pool = [
            _case(f"ZQ{n}", "2010-01-01", *codes)
            for n, codes in enumerate([(_FE,), (_FD,), (_FB,)])
        ]
        control = fc.Control(pool)
        assert control.predicted((_FE,)) == (_FB,)  # the others: {FD} and {FB}
        assert control.single((_FE,)) == _FB
        assert control.predicted((_FB,)) == (_FD,)

    def test_it_agrees_with_a_brute_force_loop_on_a_random_pool(self) -> None:
        rng = random.Random(20261002)  # noqa: S311 -- a seeded test pool, not security
        codes = [_FA, _FB, _FC, _FD, _FE]
        sets = [tuple(sorted(rng.sample(codes, rng.randint(0, 3)))) for _ in range(60)]
        # Make the commonest set and the commonest code each belong to many cases.
        sets += [(_FA,)] * 15 + [(_FA, _FD)] * 6
        pool = [_case(f"ZQ{n}", "2010-01-01", *s) for n, s in enumerate(sets)]
        control = fc.Control(pool)
        assert len(sets) == 81
        for index, own in enumerate(sets):
            if own:
                assert control.predicted(own) == _brute_set(sets, index), index
                assert control.single(own) == _brute_code(sets, index), index
        # The winner itself, when it is the case: the next best takes over.
        winners = Counter(s for s in sets if s)
        best = min(winners, key=lambda s: (-winners[s], s))
        assert best == (_FA,)
        assert control.predicted(best) == _brute_set(sets, sets.index(best))


# --------------------------------------------------------------------------------------------
# The measures
# --------------------------------------------------------------------------------------------


class TestAnalyse:
    @staticmethod
    def _pool() -> list[pp.PoolText]:
        """Six early cases flagged {FA}, alone; late twins and two late singles flagged {FE}."""
        early = [
            pp.PoolText(f"ZQ{n}", _day("2010-01-01"), f"early word {n}", ("552230",), (_FA,))
            for n in range(6)
        ]
        late = [
            pp.PoolText("ZQL1", _day("2016-01-01"), "late twin", ("552230",), (_FE,)),
            pp.PoolText("ZQL2", _day("2016-02-01"), "late twin", ("552230",), (_FE,)),
            pp.PoolText("ZQL3", _day("2017-01-01"), "late word 3", ("552230",), (_FE,)),
            pp.PoolText("ZQL4", _day("2017-02-01"), "late word 4", ("552230",), (_FE,)),
        ]
        return early + late

    def test_the_control_is_the_eras_own_pool_less_the_case(self) -> None:
        found = fc.analyse(self._pool())
        late = found[("exact", "2015\u20132019")].block
        assert (late.groups, late.cases, late.scored, late.pool) == (1, 2, 2, 4)
        # The late pool's commonest set is {FE}, held by four; less the case itself, by three.
        assert late.control.recall[10] == (1.0, 1.0)
        assert late.twins.recall[10] == (1.0, 1.0)
        # Over all years {FA} (six cases) leads {FE} (four): the same twins, a worse control.
        every = found[("exact", "all years")].block
        assert (every.groups, every.cases, every.scored, every.pool) == (1, 2, 2, 10)
        assert every.control.recall[10] == (0.0, 0.0)
        assert every.twins.recall[10] == (1.0, 1.0)
        # There is no early twin group at all.
        assert found[("exact", "2009\u20132014")].block.groups == 0

    def test_a_group_with_no_scored_case_has_nothing_to_measure(self) -> None:
        pool = [
            pp.PoolText("ZQ1", _day("2010-01-01"), "same", ("552230",), ()),
            pp.PoolText("ZQ2", _day("2010-01-01"), "same", ("552230",), ()),
        ]
        block = fc.analyse(pool)[("exact", "all years")].block
        assert (block.groups, block.cases, block.scored) == (1, 2, 0)
        assert block.twins.scored == 0
        assert fc.measure_lines("twins", block.twins) == ["twins", "- no scored case"]


class TestOutcome:
    def test_precision_and_recall_at_each_digit_count(self) -> None:
        # Predicted {FA, FD}, own {FA}: both at ten, eight and six digits.
        got = fc.outcome((_FA, _FD), (_FA,), _FA)
        assert got.precision == {10: 0.5, 8: 0.5, 6: 0.5}
        assert got.recall == {10: 1.0, 8: 1.0, 6: 1.0}
        assert got.whole is False
        assert got.single == {10: True, 8: True, 6: True}

    def test_a_match_on_fewer_digits_only(self) -> None:
        item = fc.outcome((_FB,), (_FA,), _FB)  # same item, another modifier
        assert item.precision == {10: 0.0, 8: 1.0, 6: 1.0}
        assert item.recall == {10: 0.0, 8: 1.0, 6: 1.0}
        assert item.single == {10: False, 8: True, 6: True}
        category = fc.outcome((_FC,), (_FA,), _FC)  # same category, another item
        assert category.precision == {10: 0.0, 8: 0.0, 6: 1.0}
        assert category.recall == {10: 0.0, 8: 0.0, 6: 1.0}
        assert category.single == {10: False, 8: False, 6: True}
        other = fc.outcome((_FD,), (_FA,), _FD)
        assert other.single == {10: False, 8: False, 6: False}

    def test_an_empty_predicted_set_has_no_precision_and_a_recall_of_zero(self) -> None:
        got = fc.outcome((), (_FA, _FD), None)
        assert got.precision == {10: None, 8: None, 6: None}
        assert got.recall == {10: 0.0, 8: 0.0, 6: 0.0}
        assert got.single == {10: False, 8: False, 6: False}
        assert got.whole is False

    def test_the_whole_set_is_equal_or_not(self) -> None:
        assert fc.outcome((_FA, _FD), (_FA, _FD), None).whole is True
        assert fc.outcome((_FA,), (_FA, _FD), None).whole is False
        assert fc.outcome((_FA, _FD), (_FA,), None).whole is False

    def test_it_is_scoring_metrics_own_count_not_a_copy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[tuple[tuple[str, ...], tuple[str, ...], int]] = []

        def spy(
            predicted: Sequence[str], truth: Sequence[str], digits: int
        ) -> tuple[float | None, float | None]:
            seen.append((tuple(predicted), tuple(truth), digits))
            return 0.123, 0.456

        monkeypatch.setattr(fc, "_precision_recall", spy)
        got = fc.outcome((_FD,), (_FA,), None)
        assert seen == [((_FD,), (_FA,), 10), ((_FD,), (_FA,), 8), ((_FD,), (_FA,), 6)]
        assert got.precision == {10: 0.123, 8: 0.123, 6: 0.123}
        assert got.recall == {10: 0.456, 8: 0.456, 6: 0.456}

    def test_a_case_with_no_flagged_finding_is_not_scored(self) -> None:
        with pytest.raises(ValueError, match="at least one flagged finding"):
            fc.outcome((_FA,), (), _FA)


class TestSummarise:
    def test_no_prediction_is_counted_and_left_out_of_the_precision_lists(self) -> None:
        outcomes = [
            fc.outcome((_FA, _FD), (_FA,), _FA),
            fc.outcome((), (_FD,), None),
            fc.outcome((_FD,), (_FD,), _FD),
        ]
        got = fc.summarise(outcomes)
        assert got.scored == 3
        assert got.no_prediction == 1
        assert got.precision[10] == (0.5, 1.0)  # the case with no prediction is not a zero
        assert got.recall[10] == (1.0, 0.0, 1.0)  # but its recall is
        assert got.whole == 1
        assert got.single == {10: 2, 8: 2, 6: 2}

    def test_nothing_scored(self) -> None:
        got = fc.summarise([])
        assert got.scored == 0
        assert got.recall[10] == ()
        assert got.no_prediction == 0


class TestExpectationRule:
    def test_exactly_one_half_is_not_met_and_just_above_is(self) -> None:
        assert fc.meets_expectation([1.0, 0.0]) is False
        assert fc.meets_expectation([0.5, 0.5, 0.5]) is False
        assert fc.meets_expectation([1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.5]) is False
        assert fc.meets_expectation([0.5] * 1000 + [0.6]) is True  # 50.02%
        assert fc.meets_expectation([1.0, 0.0, 1.0]) is True

    def test_it_is_decided_on_the_fraction_not_a_float_sum(self) -> None:
        thirds = [1 / 3, 2 / 3, 1 / 3, 2 / 3, 1 / 3, 2 / 3]  # exactly one half
        assert fc.exact_mean(thirds) == Fraction(1, 2)
        assert fc.meets_expectation(thirds) is False
        assert fc.exact_mean([1 / 7, 3 / 7]) == Fraction(2, 7)

    def test_no_case_does_not_meet_it(self) -> None:
        assert fc.meets_expectation([]) is False


def _block(recalls: Sequence[float]) -> fc.Block:
    n = len(recalls)
    measures = fc.Measures(
        scored=n,
        recall={10: tuple(recalls), 8: tuple(recalls), 6: tuple(recalls)},
        precision={10: (), 8: (), 6: ()},
        no_prediction=0,
        whole=0,
        single={10: 0, 8: 0, 6: 0},
    )
    return fc.Block(groups=1, cases=n, scored=n, pool=n, twins=measures, control=measures)


class TestExpectationLines:
    def test_the_committed_sentence_is_printed_verbatim_before_the_headline(self) -> None:
        lines = fc.expectation_lines(_block([1.0, 0.0, 1.0]), _CITED)
        assert lines[0] == "## The expectation (committed in 211c50e, before this script existed)"
        assert lines[2] == (
            "Expectation (decides nothing). Findings are more consistent than first codes: "
            "among exact twins, all years, the mean recall of the predicted set at 10 digits is "
            "above 50%, against the occurrence probe's 37.5%."
        )
        assert lines[3].startswith(
            "Headline: exact twins, all years, mean recall at 10 digits of the predicted set: "
            "66.7% ["
        )
        assert lines[3].endswith("over 3 scored cases")

    def test_one_half_exactly_is_not_met_and_just_above_is_met(self) -> None:
        at = fc.expectation_lines(_block([1.0, 0.0]), _CITED)
        assert at[3].startswith("Headline: exact twins, all years, mean recall at 10 digits of")
        assert "50.0% [" in at[3]
        assert at[4] == "expectation not met"
        above = fc.expectation_lines(_block([0.5] * 1000 + [0.6]), _CITED)
        assert "50.0% [" in above[3]  # prints as one half, and is above it
        assert above[4] == "expectation met"
        below = fc.expectation_lines(_block([0.5] * 1000 + [0.4]), _CITED)
        assert below[4] == "expectation not met"

    def test_the_occurrence_figure_is_the_one_given_not_the_one_in_the_sentence(self) -> None:
        lines = fc.expectation_lines(_block([1.0]), _CITED)
        assert lines[-1] == (
            "The occurrence probe's figure, read from docs/results/s3-coding-consistency-dev.txt: "
            "leave-one-out agreement on the six-digit first code among exact twins, all years, "
            f"{_CITED}."
        )

    def test_no_scored_exact_twin_is_not_tested(self) -> None:
        lines = fc.expectation_lines(_block([]), _CITED)
        assert "expectation not tested: no scored exact-twin case" in lines
        assert "expectation met" not in lines
        assert "expectation not met" not in lines


# --------------------------------------------------------------------------------------------
# The occurrence probe's figure, read from its file
# --------------------------------------------------------------------------------------------


class TestOccurrenceFigure:
    def test_it_is_read_from_the_headline_line(self, tmp_path: Path) -> None:
        assert fc.occurrence_figure(_results(tmp_path)) == _CITED
        assert fc.occurrence_figure(_results(tmp_path, "7 of 9 (77.8%) [45.3%, 93.7%]")) == (
            "7 of 9 (77.8%) [45.3%, 93.7%]"
        )

    def test_it_reads_what_the_coding_consistency_probe_prints(self, tmp_path: Path) -> None:
        tally = cc.Tally(
            groups=1,
            cases=3,
            pool=3,
            sizes={},
            loo={"code": 1, "event": 0, "phase": 0},
            agreeing_pairs={"code": 0, "event": 0, "phase": 0},
            pairs=0,
        )
        path = tmp_path / "printed.txt"
        path.write_text("\n".join(cc.expectation_lines(tally)) + "\n", encoding="utf-8")
        assert fc.occurrence_figure(path).startswith("1 of 3 (33.3%) [")

    def test_the_committed_results_file_has_the_line(self) -> None:
        figure = fc.occurrence_figure(REPOSITORY / fc.OCCURRENCE_RESULTS)
        assert re.fullmatch(r"\d+ of \d+ \(\d+\.\d%\) \[\d+\.\d%, \d+\.\d%\]", figure)

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match=r"nope\.txt is missing"):
            fc.occurrence_figure(tmp_path / "nope.txt")

    def test_a_file_without_the_line_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "other.txt"
        path.write_text(
            "Headline: loose twins, all years, leave-one-out agreement on the six-digit first "
            "code: 1 of 2 (50.0%) [9.5%, 90.5%]\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="holds no line starting"):
            fc.occurrence_figure(path)
        path.write_text(
            "Headline: exact twins, all years, leave-one-out agreement on the "
            "six-digit first code: none\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="holds no line starting"):
            fc.occurrence_figure(path)

    def test_the_file_is_refused_before_the_pool_is_read(
        self, data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def unread(processed: Path) -> object:
            raise AssertionError(f"the pool was read: {processed}")

        monkeypatch.setattr(pp, "read_pool_texts", unread)
        with pytest.raises(SystemExit, match="is missing"):
            fc.main([], results=data / "nope.txt")
        assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------------------------
# The groups' findings that differ
# --------------------------------------------------------------------------------------------


class TestDiffering:
    def test_codes_held_by_some_members_and_missing_from_others_by_groups(self) -> None:
        groups = (
            (_case("ZQ1", "2010-01-01", _FA, _FD), _case("ZQ2", "2010-01-01", _FA)),  # FD differs
            (_case("ZQ3", "2010-01-01", _FA), _case("ZQ4", "2010-01-01", _FD)),  # FA, FD
            (_case("ZQ5", "2010-01-01", _FE), _case("ZQ6", "2010-01-01", _FE)),  # none
            (_case("ZQ7", "2010-01-01", _FE), _case("ZQ8", "2010-01-01")),  # FE: one has none
        )
        assert fc.differing(groups) == [(_FD, 2), (_FA, 1), (_FE, 1)]  # ties by code

    def test_a_group_counts_a_code_once_however_many_members_hold_it(self) -> None:
        group = (
            *(_case(f"ZQ{n}", "2010-01-01", _FA) for n in range(4)),
            _case("ZQ9", "2010-01-01", _FD),
        )
        assert fc.differing([group]) == [(_FA, 1), (_FD, 1)]

    def test_nothing_differs(self) -> None:
        group = (_case("ZQ1", "2010-01-01", _FA), _case("ZQ2", "2010-01-01", _FA))
        assert fc.differing([group]) == []
        assert fc.differing([]) == []

    def test_only_ten_are_printed_with_their_labels(self) -> None:
        codes = [f"01010510{n:02d}" for n in (0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12)]
        group = (
            *(_case(f"ZQ{n}", "2010-01-01", code) for n, code in enumerate(codes)),
            _case("ZQ99", "2010-01-01"),
        )
        lines = fc.differing_lines([group], load_tables())
        numbered = [line for line in lines if re.match(r"\d+\. ", line)]
        assert len(numbered) == 10
        assert not any(line.startswith("11. ") for line in lines)
        assert "12 codes differ in at least one of 1 group." in lines[2]
        assert numbered[0] == (
            "1. 0101051000 Aircraft — Aircraft handling/service — Maintenance/inspections — "
            "Time limits / Unknown/Not determined: 1 group"
        )

    def test_none_is_said(self) -> None:
        assert fc.differing_lines([], load_tables())[-1] == (
            "none: no flagged finding differs within a group"
        )

    def test_a_code_not_in_the_tables_is_labelled_as_such(self) -> None:
        assert fc.finding_label(load_tables(), "9999999998") == (
            "not in the code tables / not in the code tables"
        )
        assert fc.finding_label(load_tables(), _FD) == (
            "Aircraft — Aircraft systems — Flight control system — Aileron control system / Failure"
        )


# --------------------------------------------------------------------------------------------
# The whole script, on a processed file of invented cases
# --------------------------------------------------------------------------------------------
#
# Exact twins, all years: groups A (six), E (two), T (three), U (two): 13 cases of 17, 11 scored,
# 2 unscored (A004, T003). The predicted set, case by case:
#   A001, A002 ({FA, FD}): the others hold {FA} three times: {FA}; precision 1, recall 1/2
#   A003, A005, A006 ({FA}): {FA, FD} twice and {FA} twice tie, {FA} is smaller: {FA}, equal
#     whole; precision 1, recall 1
#   E001 ({FC}): {FC, FE}: precision 1/2, recall 1; E002 ({FC, FE}): {FC}: precision 1, recall 1/2
#   T001 ({FD}), T002 ({FE}): the others are {the other} and {}, the empty set wins the tie: no
#     prediction, recall 0
#   U001 ({FB}) predicted {FA}, U002 ({FA}) predicted {FB}: nothing at ten digits, all of it at
#     eight and six (the same item)
# Recall at 10: 1/2 1/2 1 1 1 1 1/2 0 0 0 0 = 5.5 of 11 cases, exactly one half.
# The control predicts {FA} (six of the 15 non-empty sets in the pool) for every case.


class TestReport:
    def test_the_head_comes_first_then_the_expectation_the_method_and_the_groupings(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _main(tmp_path, capsys)
        assert text.startswith("S3.1 finding-consistency probe on the development pool (scripts/")
        order = [
            "## The expectation (committed in 211c50e",
            "## Method",
            "## exact twins\n",
            "## loose twins\n",
            "## exact twins, all years: the 10 flagged findings that most often differ",
        ]
        positions = [text.index(heading) for heading in order]
        assert positions == sorted(positions)

    def test_the_expectation_the_headline_at_one_half_and_the_figure_read_from_the_file(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _main(tmp_path, capsys)
        expectation = _section(text, "## The expectation", "## Method")
        assert fc.EXPECTATION in expectation
        assert (
            "Headline: exact twins, all years, mean recall at 10 digits of the predicted set: "
            "50.0% ["
        ) in expectation
        assert "over 11 scored cases" in expectation
        assert "expectation not met" in expectation  # exactly one half is not above one half
        assert expectation.rstrip().endswith(f"all years, {_CITED}.")
        other = _main(tmp_path, capsys, figure="3 of 8 (37.5%) [13.7%, 69.4%]")
        assert (
            "all years, 3 of 8 (37.5%) [13.7%, 69.4%]." in other
        )  # from the file, whatever it holds

    def test_the_expectation_is_met_when_the_mean_is_above_one_half(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install(tmp_path, monkeypatch, _rows(with_u=False))  # nine scored cases, 5.5 of 9
        text = _main(tmp_path, capsys)
        expectation = _section(text, "## The expectation", "## Method")
        assert "50.0% [" not in expectation
        assert "61.1% [" in expectation
        assert "over 9 scored cases" in expectation
        assert "expectation met" in expectation
        assert "expectation not met" not in expectation

    def test_the_method_counts_the_pool_and_states_the_tie_rule(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        method = _section(_main(tmp_path, capsys), "## Method", "## exact twins\n")
        assert (
            f"the S3 statistics pool, {cs.STAGES['s3'].built_from}: 19 cases; kept, each with an "
            "NTSB probable-cause text and at least one occurrence code: 17 (event years "
            "2010-2017); left out: 1 with no probable-cause text, 1 more with no occurrence code."
        ) in method
        assert f"{len(pp.STOP_WORDS)} stop words" in method
        assert "Ties go to the smallest tuple of the set's sorted codes, so the empty set" in method
        assert "wins a tie" in method
        assert "``scoring.metrics._precision_recall`` itself" in method
        assert "``mean_cell``" in method
        assert "Control (no twins)" in method

    def test_exact_twins_all_years(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _main(tmp_path, capsys)
        block = _section(text, "### exact twins, all years", "### exact twins, 2009\u20132014")
        assert block.startswith(
            "### exact twins, all years\n"
            "groups: 4; cases in groups: 13 of 17 (76.5%) of the era's pool cases\n"
            "scored cases (at least one flagged finding): 11; unscored cases (none): 2\n"
            "twins: the predicted set is the commonest flagged-finding set among the other "
            "members of the case's group\n"
        )
        twins, control = block.split("\ncontrol (no twins)")
        assert "- mean recall at 10 digits: 50.0% [" in twins
        assert "- mean recall at 8 digits: 68.2% [" in twins
        assert "- mean recall at 6 digits: 68.2% [" in twins
        assert "- mean precision at 10 digits: 72.2% [" in twins
        assert "(n = 9 cases with a prediction)" in twins
        assert "- mean precision at 8 digits: 94.4% [" in twins
        assert "- mean precision at 6 digits: 94.4% [" in twins
        assert (
            "- no prediction: 2 of 11 scored cases (an empty predicted set; left out of the "
            "precision means, scored 0 in the recall means)"
        ) in twins
        assert "- own flagged set equals the predicted set whole: 3 of 11 (27.3%) [" in twins
        assert "  - at 10 digits: 7 of 11 (63.6%) [" in twins
        assert "  - at 8 digits: 9 of 11 (81.8%) [" in twins
        assert "  - at 6 digits: 9 of 11 (81.8%) [" in twins
        assert "- mean recall at 10 digits: 45.5% [" in control
        assert "- mean recall at 8 digits: 54.5% [" in control
        assert "- mean recall at 6 digits: 68.2% [" in control
        assert "- mean precision at 10 digits: 54.5% [" in control
        assert "- mean precision at 8 digits: 63.6% [" in control
        assert "- mean precision at 6 digits: 81.8% [" in control
        assert "- no prediction: 0 of 11 scored cases" in control
        assert "- own flagged set equals the predicted set whole: 4 of 11 (36.4%) [" in control
        assert "  - at 10 digits: 6 of 11 (54.5%) [" in control
        assert "  - at 8 digits: 7 of 11 (63.6%) [" in control
        assert "  - at 6 digits: 9 of 11 (81.8%) [" in control

    def test_exact_twins_are_formed_again_inside_each_era(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _main(tmp_path, capsys)
        early = _section(text, "### exact twins, 2009\u20132014", "### exact twins, 2015\u20132019")
        assert early.startswith(
            "### exact twins, 2009\u20132014 (groups formed among cases with event years "
            "2009 to 2014 only)\n"
            "groups: 3; cases in groups: 9 of 13 (69.2%) of the era's pool cases\n"
            "scored cases (at least one flagged finding): 8; unscored cases (none): 1\n"
        )
        # The A group has four members here (A003 and A004 are later), E is no group.
        twins, control = early.split("\ncontrol (no twins)")
        assert "- mean recall at 10 digits: 37.5% [" in twins
        assert "- mean recall at 8 digits: 62.5% [" in twins
        assert "- mean precision at 10 digits: 50.0% [" in twins
        assert "(n = 6 cases with a prediction)" in twins
        assert "- mean precision at 8 digits: 83.3% [" in twins
        assert "- no prediction: 2 of 8 scored cases" in twins
        assert "predicted set whole: 0 of 8 (0.0%) [" in twins
        assert "  - at 10 digits: 4 of 8 (50.0%) [" in twins
        assert "  - at 8 digits: 6 of 8 (75.0%) [" in twins
        assert "- mean recall at 10 digits: 50.0% [" in control
        assert "- mean recall at 8 digits: 62.5% [" in control
        assert "predicted set whole: 3 of 8 (37.5%) [" in control
        assert "  - at 10 digits: 5 of 8 (62.5%) [" in control
        assert "  - at 8 digits: 6 of 8 (75.0%) [" in control
        late = _section(text, "### exact twins, 2015\u20132019", "## loose twins")
        assert late.startswith(
            "### exact twins, 2015\u20132019 (groups formed among cases with event years "
            "2015 to 2019 only)\n"
            "groups: 1; cases in groups: 2 of 4 (50.0%) of the era's pool cases\n"
            "scored cases (at least one flagged finding): 1; unscored cases (none): 1\n"
        )
        # A003's only other member has no flagged finding: the empty set is the prediction.
        twins, control = late.split("\ncontrol (no twins)")
        assert "- mean recall at 10 digits: 0.0% [0.0%, 0.0%] (n = 1)" in twins
        assert "- mean precision at 10 digits: none (n = 0 cases with a prediction)" in twins
        assert "- no prediction: 1 of 1 scored cases" in twins
        assert "predicted set whole: 0 of 1 (0.0%) [" in twins
        assert "  - at 10 digits: 0 of 1 (0.0%) [" in twins
        # The control: the pool's {FA} (twice) less the case itself ties with {FC, FE}: {FA}.
        assert "- mean recall at 10 digits: 100.0% [100.0%, 100.0%] (n = 1)" in control
        assert "predicted set whole: 1 of 1 (100.0%) [" in control

    def test_loose_twins_all_years(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _main(tmp_path, capsys)
        block = _section(text, "### loose twins, all years", "### loose twins, 2009\u20132014")
        # A, E, T, U and the three loose twins B001, B002 and C001; D001 is alone.
        assert block.startswith(
            "### loose twins, all years\n"
            "groups: 5; cases in groups: 16 of 17 (94.1%) of the era's pool cases\n"
            "scored cases (at least one flagged finding): 14; unscored cases (none): 2\n"
        )
        twins, control = block.split("\ncontrol (no twins)")
        # The three add: B001 {FA} predicted {FB}, B002 {FB} predicted {FA} (the others tie and
        # the smaller set wins), C001 {FD} predicted {FB}.
        assert "- mean recall at 10 digits: 39.3% [" in twins  # 5.5 of 14
        assert "- mean recall at 8 digits: 67.9% [" in twins  # 9.5 of 14
        assert "- mean precision at 10 digits: 54.2% [" in twins  # 6.5 of 12
        assert "(n = 12 cases with a prediction)" in twins
        assert "- mean precision at 8 digits: 87.5% [" in twins
        assert "- no prediction: 2 of 14 scored cases" in twins
        assert "predicted set whole: 3 of 14 (21.4%) [" in twins
        assert "  - at 10 digits: 7 of 14 (50.0%) [" in twins
        assert "  - at 8 digits: 11 of 14 (78.6%) [" in twins
        assert "- mean recall at 10 digits: 42.9% [" in control  # 6 of 14
        assert "- mean recall at 8 digits: 57.1% [" in control
        assert "predicted set whole: 5 of 14 (35.7%) [" in control
        assert "  - at 6 digits: 11 of 14 (78.6%) [" in control

    def test_the_findings_that_most_often_differ_with_labels_and_no_text(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _main(tmp_path, capsys)
        found = _section(text, "## exact twins, all years: the 10 flagged findings")
        # A: FA and FD (one member has none); E: FE; T: FD and FE; U: FA and FB. Not FC (both
        # hold it), and not FE for A004, whose finding was never flagged.
        assert "4 codes differ in at least one of 4 groups" in found
        assert (
            "1. 0101051001 Aircraft — Aircraft handling/service — Maintenance/inspections — "
            "Time limits / Failure: 2 groups\n"
            "2. 0102271001 Aircraft — Aircraft systems — Flight control system — Aileron "
            "control system / Failure: 2 groups\n"
            "3. 0201101001 Personnel issues — Physical — Physical characteristic — Size / "
            "Failure: 2 groups\n"
            "4. 0101051000 Aircraft — Aircraft handling/service — Maintenance/inspections — "
            "Time limits / Unknown/Not determined: 1 group"
        ) in found
        assert "0101052001" not in found

    def test_the_sealed_the_wrong_class_and_the_held_out_cases_never_reach_the_pool(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Each holds the A sentence and {FE}: in the pool the A group would be nine."""
        text = _main(tmp_path, capsys)
        assert "cases in groups: 13 of 17 (76.5%)" in text
        assert "scored cases (at least one flagged finding): 11; unscored cases (none): 2" in text

    def test_no_case_number_no_case_id_and_no_record_text_is_printed(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _main(tmp_path, capsys)
        assert not _CASE_NUMBER.search(text)
        assert "ZQ" not in text
        for word in _WORDS:
            assert word not in text.lower()

    def test_out_writes_the_report_and_the_report_does_not_depend_on_it(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain = _main(tmp_path, capsys)
        out = tmp_path / "results" / "s3-finding-consistency-dev.txt"
        written = _main(tmp_path, capsys, "--out", str(out))
        assert written == plain
        assert out.read_text() == plain + "\n"

    def test_the_report_is_the_same_on_a_second_run(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _main(tmp_path, capsys) == _main(tmp_path, capsys)  # no time and no path in it


class TestPool:
    def test_a_pool_holding_a_sample_case_raises_through_check_pool_and_prints_nothing(
        self,
        data: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            pp, "pool_cases", lambda rows, *, excluded: cs.pool_cases(rows, excluded=frozenset())
        )
        with pytest.raises(LeakageError, match=_SEALED):
            fc.main([], results=_results(tmp_path))
        assert capsys.readouterr().out == ""
