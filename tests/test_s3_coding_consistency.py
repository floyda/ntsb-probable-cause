"""scripts/exploratory/s3_coding_consistency.py: how far the cause sentence settles the first code.

S3.1 Task 15, exploratory. A processed file of invented cases (invented ids, invented words, real
code labels), whose twins, eras, agreements and pairs are worked out by hand in the comments.
Offline: no network, no model.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from scripts import coding_stats as cs
from scripts.exploratory import s3_coding_consistency as cc
from scripts.exploratory import s3_precedent_probe as pp
from tests.test_coding_stats import _CASE_NUMBER
from tests.test_s3_precedent_pages import _raw, _row
from tests.test_s3_precedent_probe import _processed

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import load_tables

_SEALED = "ZQS001"
_WHEN = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
_STAMP = "20261002T120000"
_OWNER = "Zorvex Quillbright"
# Invented words: none is in the code tables' labels, so "no text in the output" is testable.
_WORDS = (
    "zephyrine",
    "marrowfat",
    "brambleton",
    "quillwort",
    "thistlebrook",
    "thistlecomb",
    "gallimaufry",
    "zorvex",
)
_A_TEXT = "The zephyrine\u2019s marrowfat tangle"


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _case(case_id: str, day: str, text: str, *codes: str) -> pp.PoolText:
    return pp.PoolText(case_id, _day(day), text, codes)


# --------------------------------------------------------------------------------------------
# The twins
# --------------------------------------------------------------------------------------------


class TestKeys:
    def test_exact_keeps_every_token_in_order_and_ignores_case_and_punctuation(self) -> None:
        assert cc.twin_key("The Pilot's 2 FEET; 100LL!", "exact") == (
            "the",
            "pilot",
            "s",
            "2",
            "feet",
            "100ll",
        )

    def test_a_curly_and_a_straight_apostrophe_make_the_same_key(self) -> None:
        assert cc.twin_key("The pilot\u2019s failure", "exact") == cc.twin_key(
            "THE PILOT'S  failure.", "exact"
        )

    def test_loose_is_the_set_of_tokens_less_the_stop_words(self) -> None:
        assert cc.twin_key("The failure of the engine, the engine!", "loose") == frozenset(
            {"failure", "engine"}
        )
        assert cc.twin_key("Engine failure", "loose") == cc.twin_key(
            "failure of THE engine", "loose"
        )

    def test_a_text_with_no_token_has_an_empty_key(self) -> None:
        assert cc.twin_key("...  !!", "exact") == ()
        assert cc.twin_key("Not of the", "loose") == frozenset()  # all stop words
        assert cc.twin_key("Not of the", "exact") == ("not", "of", "the")


class TestGroups:
    def test_exact_twins_ignore_case_punctuation_and_apostrophes(self) -> None:
        cases = [
            _case("ZQ3", "2010-01-01", "The zephyrine\u2019s marrowfat tangle.", "552230"),
            _case("ZQ1", "2011-01-01", "the ZEPHYRINE'S marrowfat   tangle", "552230"),
            _case("ZQ2", "2012-01-01", "The zephyrine\u2019s marrowfat tangle!", "550230"),
        ]
        groups = cc.form_groups(cases, "exact")
        assert [[c.case_id for c in g] for g in groups] == [["ZQ1", "ZQ2", "ZQ3"]]  # by case id

    def test_exact_twins_need_the_same_order_and_the_same_stop_words(self) -> None:
        cases = [
            _case("ZQ1", "2010-01-01", "Brambleton quillwort", "402192"),
            _case("ZQ2", "2010-01-01", "Quillwort brambleton", "402192"),
            _case("ZQ3", "2010-01-01", "The brambleton quillwort", "402192"),
        ]
        assert cc.form_groups(cases, "exact") == ()

    def test_loose_twins_ignore_order_and_stop_words(self) -> None:
        cases = [
            _case("ZQ1", "2010-01-01", "Brambleton quillwort", "402192"),
            _case("ZQ2", "2010-01-01", "Quillwort brambleton", "402192"),
            _case("ZQ3", "2010-01-01", "The brambleton OF quillwort", "402192"),
            _case("ZQ4", "2010-01-01", "Brambleton quillwort quillwort", "402192"),  # a set
            _case("ZQ5", "2010-01-01", "Brambleton thistlecomb", "402192"),
        ]
        groups = cc.form_groups(cases, "loose")
        assert [[c.case_id for c in g] for g in groups] == [["ZQ1", "ZQ2", "ZQ3", "ZQ4"]]

    def test_an_empty_key_never_makes_a_group_and_one_case_is_not_a_group(self) -> None:
        cases = [
            _case("ZQ1", "2010-01-01", "...", "402192"),
            _case("ZQ2", "2010-01-01", "!!", "402192"),
            _case("ZQ3", "2010-01-01", "Not of the", "402192"),
            _case("ZQ4", "2010-01-01", "Of the not", "402192"),
            _case("ZQ5", "2010-01-01", "Thistlecomb", "402192"),
        ]
        assert cc.form_groups(cases, "exact") == ()  # ZQ3 and ZQ4 differ in order
        assert cc.form_groups(cases, "loose") == ()  # ZQ3 and ZQ4 share only an empty key

    def test_groups_come_back_ordered_by_their_first_member(self) -> None:
        cases = [
            _case("ZQ9", "2010-01-01", "Quillwort", "402192"),
            _case("ZQ1", "2010-01-01", "Brambleton", "402192"),
            _case("ZQ5", "2010-01-01", "Quillwort", "402192"),
            _case("ZQ3", "2010-01-01", "Brambleton", "402192"),
        ]
        groups = cc.form_groups(cases, "exact")
        assert [[c.case_id for c in g] for g in groups] == [["ZQ1", "ZQ3"], ["ZQ5", "ZQ9"]]

    def test_the_first_code_is_the_first_of_the_sequence_and_values_cut_it(self) -> None:
        assert cc.value("552230", "code") == "552230"
        assert cc.value("552230", "event") == "230"
        assert cc.value("552230", "phase") == "552"


class TestEras:
    def test_an_era_holds_its_years_inclusive_and_all_years_holds_every_year(self) -> None:
        early, late = cc.ERAS[1], cc.ERAS[2]
        assert (early.name, late.name) == ("2009\u20132014", "2015\u20132019")
        assert [early.holds(y) for y in (2008, 2009, 2014, 2015)] == [False, True, True, False]
        assert [late.holds(y) for y in (2014, 2015, 2019, 2020)] == [False, True, True, False]
        assert all(cc.ALL_YEARS.holds(y) for y in (1990, 2009, 2019, 2030))

    def test_groups_are_formed_again_within_each_era(self) -> None:
        cases = [
            _case("ZQ1", "2010-05-01", "Quillwort", "552230"),
            _case("ZQ2", "2014-12-31", "Quillwort", "552230"),
            _case("ZQ3", "2015-01-01", "Quillwort", "552230"),
            _case("ZQ4", "2019-01-01", "Quillwort", "550230"),
            _case("ZQ5", "2012-01-01", "Brambleton", "402192"),
            _case("ZQ6", "2016-01-01", "Brambleton", "402192"),  # one in each era: no pair
        ]
        found = cc.analyse(cases)
        members = {
            key: [[c.case_id for c in g] for g in value.groups] for key, value in found.items()
        }
        assert members[("exact", "all years")] == [["ZQ1", "ZQ2", "ZQ3", "ZQ4"], ["ZQ5", "ZQ6"]]
        assert members[("exact", "2009\u20132014")] == [["ZQ1", "ZQ2"]]
        assert members[("exact", "2015\u20132019")] == [["ZQ3", "ZQ4"]]
        # The era's pool cases are the share's denominator: ZQ1, ZQ2, ZQ5; and ZQ3, ZQ4, ZQ6.
        assert found[("exact", "2009\u20132014")].tally.pool == 3
        assert found[("exact", "2015\u20132019")].tally.pool == 3
        assert found[("exact", "all years")].tally.pool == 6


# --------------------------------------------------------------------------------------------
# The measures
# --------------------------------------------------------------------------------------------


class TestLeaveOneOut:
    @pytest.mark.parametrize(
        ("values", "agreeing"),
        [
            (["A", "A"], 2),
            (["A", "B"], 0),  # each is alone against the other
            (["A", "A", "B"], 2),  # the two A's see an A and a B: a tie goes to A
            (["A", "A", "A", "B"], 3),  # the B sees three A's
            (["B", "A", "C"], 0),  # every case sees a tie of the two others, never its own
            (["A", "A", "B", "C"], 2),  # an A sees A, B, C tied: the smallest is A
            (["B", "B", "A", "C"], 0),  # a B sees B, A, C tied: the smallest is A, not B
            (["9", "9", "10", "11"], 0),  # smallest as a string: "10" comes before "9"
            (["B", "B", "B", "A"], 3),  # a B sees B, B, A: B; the A sees three B's
        ],
    )
    def test_the_commonest_among_the_others_with_ties_to_the_smallest_string(
        self, values: list[str], agreeing: int
    ) -> None:
        assert cc.leave_one_out(values) == agreeing

    def test_a_lone_value_has_no_others_to_agree_with(self) -> None:
        assert cc.leave_one_out(["A"]) == 0

    def test_commonest_ties_to_the_smallest_value_as_a_string(self) -> None:
        assert cc.commonest({"9": 1, "10": 1}) == "10"
        assert cc.commonest({"B": 2, "A": 1}) == "B"
        assert cc.commonest({}) is None


class TestPairwise:
    @pytest.mark.parametrize(
        ("values", "agreeing", "pairs"),
        [
            (["A", "A"], 1, 1),
            (["A", "B"], 0, 1),
            (["A", "A", "A", "B"], 3, 6),
            (["A", "A", "B", "B"], 2, 6),
            (["A", "B", "C"], 0, 3),
            (["A"] * 5, 10, 10),
        ],
    )
    def test_agreeing_pairs_and_all_pairs(
        self, values: list[str], agreeing: int, pairs: int
    ) -> None:
        assert cc.pairwise(values) == (agreeing, pairs)


class TestSizes:
    @pytest.mark.parametrize(
        ("size", "name"),
        [
            (2, "2"),
            (3, "3-5"),
            (5, "3-5"),
            (6, "6-10"),
            (10, "6-10"),
            (11, "11+"),
            (400, "11+"),
        ],
    )
    def test_the_bucket_edges(self, size: int, name: str) -> None:
        assert cc.bucket(size) == name

    def test_the_size_distribution_counts_groups_and_the_cases_in_them(self) -> None:
        sizes = (2, 2, 3, 5, 6, 10, 11, 12)
        groups = [
            tuple(_case(f"ZQ{g}x{m:02d}", "2010-01-01", f"w{g}", "552230") for m in range(n))
            for g, n in enumerate(sizes)
        ]
        found = cc.tally(groups, pool=100)
        assert found.sizes == {"2": (2, 4), "3-5": (2, 8), "6-10": (2, 16), "11+": (2, 23)}
        assert (found.groups, found.cases, found.pool) == (8, 51, 100)
        assert found.pairs == sum(n * (n - 1) // 2 for n in sizes)

    def test_the_tally_counts_each_level_over_cases_and_over_pairs(self) -> None:
        # Only the first code of each sequence counts: the later codes would change every figure.
        group = (
            _case("ZQ1", "2010-01-01", "w", "552230", "402192"),
            _case("ZQ2", "2010-01-01", "w", "552230", "300230"),
            _case("ZQ3", "2010-01-01", "w", "550230", "552230"),
            _case("ZQ4", "2010-01-01", "w", "552230", "550230"),
        )
        found = cc.tally([group], pool=4)
        assert found.loo == {"code": 3, "event": 4, "phase": 3}
        assert found.agreeing_pairs == {"code": 3, "event": 6, "phase": 3}
        assert found.pairs == 6


class TestDisagreeingPairs:
    def test_each_group_adds_the_product_of_the_counts_of_two_codes(self) -> None:
        one = tuple(
            _case(f"ZQA{n}", "2010-01-01", "a", code, "300230")  # a second code, never counted
            for n, code in enumerate(("552230", "552230", "552230", "550230", "552300"))
        )
        two = tuple(
            _case(f"ZQB{n}", "2010-01-01", "b", code)
            for n, code in enumerate(("550230", "552230", "552230"))
        )
        # Group one: 552230 x3, 550230 x1, 552300 x1: (550230, 552230) 3, (552230, 552300) 3,
        # (550230, 552300) 1. Group two: 550230 x1, 552230 x2: (550230, 552230) 2.
        assert cc.disagreeing_pairs([one, two]) == [
            ("550230", "552230", 5),
            ("552230", "552300", 3),
            ("550230", "552300", 1),
        ]

    def test_ties_go_to_the_smaller_first_code_then_the_smaller_second(self) -> None:
        group = tuple(
            _case(f"ZQ{n}", "2010-01-01", "w", code)
            for n, code in enumerate(("300230", "402192", "552230"))
        )
        assert cc.disagreeing_pairs([group]) == [
            ("300230", "402192", 1),
            ("300230", "552230", 1),
            ("402192", "552230", 1),
        ]

    def test_a_group_that_agrees_adds_nothing(self) -> None:
        group = tuple(_case(f"ZQ{n}", "2010-01-01", "w", "552230") for n in range(4))
        assert cc.disagreeing_pairs([group]) == []

    def test_only_the_ten_commonest_are_printed(self) -> None:
        codes = [f"{n:03d}230" for n in range(100, 105)] + ["552230", "552231"]
        group = tuple(_case(f"ZQ{n}", "2010-01-01", "w", c) for n, c in enumerate(codes))
        lines = cc.pair_lines([group], load_tables())
        assert len(cc.disagreeing_pairs([group])) == 21
        assert len([line for line in lines if re.match(r"\d+\. ", line)]) == 10
        assert not any(line.startswith("11. ") for line in lines)
        assert "(21 disagreeing pairs in all, of 21 pairs within groups)" in lines[2]

    def test_no_disagreement_is_said(self) -> None:
        group = tuple(_case(f"ZQ{n}", "2010-01-01", "w", "552230") for n in range(3))
        assert cc.pair_lines([group], load_tables())[-1] == (
            "none: no pair of twins disagrees on the first code"
        )


class TestExpectation:
    @staticmethod
    def _tally(agreeing: int, cases: int) -> cc.Tally:
        return cc.Tally(
            groups=1,
            cases=cases,
            pool=cases,
            sizes={},
            loo={"code": agreeing, "event": 0, "phase": 0},
            agreeing_pairs={"code": 0, "event": 0, "phase": 0},
            pairs=0,
        )

    def test_below_eighty_percent_is_met_and_eighty_is_not(self) -> None:
        met = cc.expectation_lines(self._tally(799, 1000))
        not_met = cc.expectation_lines(self._tally(800, 1000))
        assert met[-1] == "expectation met"
        assert not_met[-1] == "expectation not met"
        assert "799 of 1000 (79.9%) [" in met[-2]
        assert "800 of 1000 (80.0%) [" in not_met[-2]

    def test_the_edge_is_exact_not_rounded(self) -> None:
        # 79.96% prints as 80.0% but is below 80%.
        assert cc.meets_expectation(7996, 10000) is True
        assert cc.expectation_lines(self._tally(7996, 10000))[-1] == "expectation met"
        assert cc.meets_expectation(8000, 10000) is False
        assert cc.meets_expectation(0, 1) is True
        assert cc.meets_expectation(1, 1) is False

    def test_the_committed_sentence_is_printed_verbatim_before_the_headline(self) -> None:
        lines = cc.expectation_lines(self._tally(1, 3))
        assert lines[2] == (
            "Expectation (decides nothing). Leave-one-out agreement on the six-digit first code "
            "among exact twins, all years: below 80%, that is, at least one in five identical "
            "cause sentences coded differently from the majority of its twins."
        )
        assert lines[3].startswith(
            "Headline: exact twins, all years, leave-one-out agreement on the six-digit first "
            "code: 1 of 3 (33.3%) ["
        )

    def test_no_exact_twins_is_not_tested(self) -> None:
        lines = cc.expectation_lines(self._tally(0, 0))
        assert lines[-1] == "expectation not tested: no exact twins"
        assert "expectation met" not in lines[-1]


# --------------------------------------------------------------------------------------------
# The whole script, on a processed file of invented cases
# --------------------------------------------------------------------------------------------
#
# Kept pool, 14 cases (the statistics pool holds 16: one has no text, one no code):
#   exact twins "The zephyrine's marrowfat tangle", four spellings of one sentence:
#     ZQA001 2010 552230, ZQA002 2011 552230, ZQA003 2016 550230, ZQA004 2017 552230
#   ZQB001 2012 402192 "Brambleton quillwort thistlebrook"; ZQB002 2013 402341 the same words in
#     another order; ZQC001 2010 402192 the same words and stop words: loose twins of three
#   ZQE001 2014-12-31 and ZQE002 2015-01-01, both 500241 "Gallimaufry stoat": exact twins that
#     cross the eras' border
#   ZQD001 2015 300230 "Thistlecomb" alone; ZQP001 2009 "...", ZQP002 2018 "!!" (empty keys);
#     ZQP003 2012 "Not of the", ZQP004 2013 "Of the not" (loose key empty, exact keys differ)
# Left out of the pool: ZQS001 (a sealed sample's case, with the A sentence), ZQI001 (class I),
# ZQH001 (held-out), all with the A sentence, which would make the A group five.

_B_TEXT = "Brambleton quillwort thistlebrook"
_ROWS = [
    _row("ZQA001", "2010-03-01", "The zephyrine\u2019s marrowfat tangle.", ("552230",)),
    _row("ZQA002", "2011-03-01", "the ZEPHYRINE'S marrowfat tangle", ("552230",)),
    _row("ZQA003", "2016-03-01", "The zephyrine's  marrowfat   tangle", ("550230",)),
    _row("ZQA004", "2017-03-01", "The zephyrine\u2019s marrowfat tangle!", ("552230",)),
    _row("ZQB001", "2012-03-01", _B_TEXT, ("402192",)),
    _row("ZQB002", "2013-03-01", "Quillwort brambleton thistlebrook", ("402341",)),
    _row("ZQC001", "2010-06-01", "Quillwort thistlebrook of the brambleton", ("402192",)),
    _row("ZQD001", "2015-03-01", "Thistlecomb", ("300230",)),
    _row("ZQE001", "2014-12-31", "Gallimaufry stoat", ("500241",)),
    _row("ZQE002", "2015-01-01", "Gallimaufry stoat.", ("500241",)),
    _row("ZQP001", "2009-05-01", "...", ("402192",)),
    _row("ZQP002", "2018-05-01", "!!", ("402192",)),
    _row("ZQP003", "2012-05-01", "Not of the", ("402192",)),
    _row("ZQP004", "2013-05-01", "Of the not", ("402192",)),
    (
        "ZQN001",
        "2012-07-01",
        "dev",
        "C",
        {**_raw("ZQN001", "2012-07-01", "", ("402192",)), "narratives": []},
    ),
    _row("ZQN002", "2012-08-01", "Gallimaufry stoat", ()),
    _row(_SEALED, "2012-09-01", _A_TEXT, ("300230",)),
    ("ZQI001", "2012-10-01", "dev", "I", _raw("ZQI001", "2012-10-01", _A_TEXT, ("300230",))),
    ("ZQH001", "2021-01-01", "heldout", "C", _raw("ZQH001", "2021-01-01", _A_TEXT, ("300230",))),
]


def _sample_ids(name: str) -> tuple[str, ...]:
    return {"dev-seal-s3-400": (_SEALED,)}.get(name, ())


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The processed file and the runs folder, under a temporary data folder."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(samples, "sample_ids", _sample_ids)
    _processed(tmp_path, _ROWS)
    return tmp_path


def _main(
    capsys: pytest.CaptureFixture[str], *argv: str, when: datetime = _WHEN
) -> tuple[str, str]:
    """Run the script; return the report and the printed folder line."""
    assert cc.main(list(argv), now=lambda: when) == 0
    printed = capsys.readouterr().out
    text, _, folder = printed.rstrip("\n").rpartition("\n")
    return text, folder


def _section(text: str, start: str, end: str | None = None) -> str:
    begin = text.index(start)
    stop = text.find(end, begin + 1) if end is not None else -1
    return text[begin : stop if stop != -1 else len(text)]


class TestReport:
    def test_the_head_comes_first_then_the_expectation_the_method_and_the_groupings(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text, _ = _main(capsys)
        assert text.startswith("S3.1 coding-consistency probe on the development pool (scripts/")
        order = [
            "## The expectation (committed in 700afda",
            "## Method",
            "## exact twins\n",
            "## loose twins\n",
            "## exact twins, all years: the 10 first-code pairs that most often disagree",
            "The 25 largest exact-twin groups",
        ]
        positions = [text.index(heading) for heading in order]
        assert positions == sorted(positions)

    def test_the_expectation_is_verbatim_with_the_headline_and_whether_it_is_met(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text, _ = _main(capsys)
        expectation = _section(text, "## The expectation", "## Method")
        assert cc.EXPECTATION in expectation
        assert cc.EXPECTATION.startswith("Expectation (decides nothing). Leave-one-out agreement")
        # Exact twins, all years: the A group's 3 of 4 and the E group's 2 of 2.
        assert (
            "leave-one-out agreement on the six-digit first code: 5 of 6 (83.3%) [" in expectation
        )
        assert expectation.rstrip().endswith("expectation not met")

    def test_the_method_counts_the_pool(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        method = _section(_main(capsys)[0], "## Method", "## exact twins\n")
        assert (
            f"the S3 statistics pool, {cs.STAGES['s3'].built_from}: 16 cases; kept, each with an "
            "NTSB probable-cause text and at least one occurrence code: 14 (event years "
            "2009-2018); left out: 1 with no probable-cause text, 1 more with no occurrence code."
        ) in method
        assert f"{len(pp.STOP_WORDS)} stop words" in method

    def test_exact_twins_all_years(self, data: Path, capsys: pytest.CaptureFixture[str]) -> None:
        text, _ = _main(capsys)
        block = _section(text, "### exact twins, all years", "### exact twins, 2009\u20132014")
        assert block.startswith(
            "### exact twins, all years\n"
            "groups: 2; cases in groups: 6 of 14 (42.9%) of the era's pool cases\n"
            "group sizes, groups (cases in them): 2: 1 (2 cases); 3-5: 1 (4 cases); "
            "6-10: 0 (0 cases); 11+: 0 (0 cases)\n"
            "leave-one-out agreement (denominator: the 6 cases in groups):\n"
            "- six-digit first code: 5 of 6 (83.3%) ["
        )
        assert "- event (last three digits): 6 of 6 (100.0%) [" in block
        assert "- phase (first three digits): 5 of 6 (83.3%) [" in block
        assert "pairwise agreement (denominator: the 7 pairs within groups):" in block
        pairwise = _section(block, "pairwise agreement")
        assert "- six-digit first code: 4 of 7 (57.1%) [" in pairwise
        assert "- event (last three digits): 7 of 7 (100.0%) [" in pairwise
        assert "- phase (first three digits): 4 of 7 (57.1%) [" in pairwise

    def test_exact_twins_are_formed_again_inside_each_era(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text, _ = _main(capsys)
        early = _section(text, "### exact twins, 2009\u20132014", "### exact twins, 2015\u20132019")
        assert early.startswith(
            "### exact twins, 2009\u20132014 (groups formed among cases with event years "
            "2009 to 2014 only)\n"
            "groups: 1; cases in groups: 2 of 9 (22.2%) of the era's pool cases"
        )
        assert "leave-one-out agreement (denominator: the 2 cases in groups):" in early
        assert "- six-digit first code: 2 of 2 (100.0%) [" in early
        assert "pairwise agreement (denominator: the 1 pairs within groups):" in early
        late = _section(text, "### exact twins, 2015\u20132019", "## loose twins")
        assert "groups: 1; cases in groups: 2 of 5 (40.0%) of the era's pool cases" in late
        assert "- six-digit first code: 0 of 2 (0.0%) [" in late
        assert "- event (last three digits): 2 of 2 (100.0%) [" in late
        assert "- phase (first three digits): 0 of 2 (0.0%) [" in late
        assert "- six-digit first code: 0 of 1 (0.0%) [" in _section(late, "pairwise")
        # The two cases either side of the border (2014-12-31 and 2015-01-01) are a group in
        # all years only.
        assert "groups: 2;" in _section(text, "### exact twins, all years", "### exact twins, 2009")

    def test_loose_twins_all_years_and_by_era(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text, _ = _main(capsys)
        allyears = _section(text, "### loose twins, all years", "### loose twins, 2009\u20132014")
        assert allyears.startswith(
            "### loose twins, all years\n"
            "groups: 3; cases in groups: 9 of 14 (64.3%) of the era's pool cases\n"
            "group sizes, groups (cases in them): 2: 1 (2 cases); 3-5: 2 (7 cases); "
            "6-10: 0 (0 cases); 11+: 0 (0 cases)\n"
        )
        # A: 3 + 4 + 3, the B/C group of three: 2 (a code tie goes to 402192) + 2 + 3, E: 2.
        assert "- six-digit first code: 7 of 9 (77.8%) [" in allyears
        assert "- event (last three digits): 8 of 9 (88.9%) [" in allyears
        assert "- phase (first three digits): 8 of 9 (88.9%) [" in allyears
        pairs = _section(allyears, "pairwise")
        assert "the 10 pairs within groups" in pairs
        assert "- six-digit first code: 5 of 10 (50.0%) [" in pairs
        assert "- event (last three digits): 8 of 10 (80.0%) [" in pairs
        assert "- phase (first three digits): 7 of 10 (70.0%) [" in pairs
        early = _section(text, "### loose twins, 2009\u20132014", "### loose twins, 2015\u20132019")
        assert "groups: 2; cases in groups: 5 of 9 (55.6%) of the era's pool cases" in early
        assert "2: 1 (2 cases); 3-5: 1 (3 cases)" in early
        assert "- six-digit first code: 4 of 5 (80.0%) [" in early
        assert "- phase (first three digits): 5 of 5 (100.0%) [" in early
        late = _section(
            text, "### loose twins, 2015\u20132019", "## exact twins, all years: the 10"
        )
        assert "groups: 1; cases in groups: 2 of 5 (40.0%) of the era's pool cases" in late

    def test_the_first_code_pairs_that_disagree_with_labels_and_no_text(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text, _ = _main(capsys)
        pairs = _section(text, "## exact twins, all years: the 10", "The 25 largest")
        assert "(3 disagreeing pairs in all, of 7 pairs within groups)" in pairs
        assert (
            "1. 550230 Landing / Loss of control on ground vs 552230 Landing-Landing Roll / "
            "Loss of control on ground: 3 pairs"
        ) in pairs
        assert "2. " not in pairs

    def test_the_sealed_the_wrong_class_and_the_held_out_cases_never_reach_the_pool(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Each holds the A sentence: in the pool, the A group would be five, not four."""
        text, _ = _main(capsys)
        assert "3-5: 1 (4 cases)" in text
        assert "6 of 14 (42.9%)" in text  # the pool is 14 cases, not 17

    def test_no_case_number_no_case_id_and_no_record_text_is_printed(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text, folder = _main(capsys)
        assert not _CASE_NUMBER.search(text)
        assert "ZQ" not in text + folder
        for word in _WORDS:
            assert word not in text.lower()

    def test_out_writes_the_report_and_the_report_does_not_depend_on_it(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain, _ = _main(capsys)
        out = tmp_path / "results" / "s3-coding-consistency-dev.txt"
        written, _ = _main(capsys, "--out", str(out), when=_WHEN.replace(second=1))
        assert written == plain
        assert out.read_text() == plain + "\n"

    def test_the_report_is_the_same_on_a_second_run(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        first, _ = _main(capsys)
        second, _ = _main(capsys, when=_WHEN.replace(second=1))
        assert first == second  # no time, no path: the committed file can be recomputed


# --------------------------------------------------------------------------------------------
# The private file
# --------------------------------------------------------------------------------------------


class TestLargest:
    def test_the_twenty_five_largest_with_ties_to_the_first_members_id(self) -> None:
        sizes = [2 + (n % 6) for n in range(30)]  # 2..7, five of each
        groups = [
            tuple(_case(f"ZQ{n:02d}x{m}", "2010-01-01", f"w{n}", "552230") for m in range(size))
            for n, size in enumerate(sizes)
        ]
        chosen = cc.largest(groups)
        assert cc.LARGEST == 25
        assert len(chosen) == 25
        assert [len(g) for g in chosen] == sorted((len(g) for g in chosen), reverse=True)
        assert min(len(g) for g in chosen) == 3  # every group of 2 left out: 25 groups hold 3+
        sevens = [g[0].case_id for g in chosen if len(g) == 7]
        assert sevens == sorted(sevens)  # ties by the first member's id
        assert [len(g) for g in cc.largest(groups, 3)] == [7, 7, 7]


class TestMarkdown:
    def test_each_group_has_its_text_size_and_first_code_counts_with_labels(self) -> None:
        group = (
            _case("ZQ1", "2010-01-01", "The  zephyrine\u2019s\nmarrowfat tangle.", "552230"),
            _case("ZQ2", "2010-01-01", "the zephyrine's marrowfat tangle", "552230"),
            _case("ZQ3", "2010-01-01", "The zephyrine's marrowfat tangle!", "550230"),
        )
        raw = _raw("ZQ1", "2010-01-01", group[0].text, ("552230",))
        markdown = cc.groups_markdown([group], [raw], load_tables())
        assert "## Group 1: 3 cases\n\n> The zephyrine\u2019s marrowfat tangle.\n" in markdown
        assert (
            "First codes:\n"
            "- 552230 Landing-Landing Roll / Loss of control on ground: 2\n"
            "- 550230 Landing / Loss of control on ground: 1\n"
        ) in markdown
        assert "ZQ" not in markdown
        assert not _CASE_NUMBER.search(markdown)

    def test_groups_are_numbered_in_the_order_given(self) -> None:
        big = tuple(_case(f"ZQA{n}", "2010-01-01", "quillwort", "552230") for n in range(3))
        small = tuple(_case(f"ZQB{n}", "2010-01-01", "brambleton", "402192") for n in range(2))
        raws = [_raw("ZQA0", "2010-01-01", "quillwort", ()), _raw("ZQB0", "2010-01-01", "x", ())]
        markdown = cc.groups_markdown([big, small], raws, load_tables())
        assert markdown.index("## Group 1: 3 cases") < markdown.index("## Group 2: 2 cases")
        assert markdown.index("> quillwort") < markdown.index("> brambleton")

    def test_names_the_record_holds_are_replaced(self) -> None:
        text = f"{_OWNER} let the tank run dry."
        group = (
            _case("ZQ1", "2010-01-01", text, "552230"),
            _case("ZQ2", "2010-01-01", text, "552230"),
        )
        raw = _raw("ZQ1", "2010-01-01", text, ("552230",), owner=_OWNER)
        markdown = cc.groups_markdown([group], [raw], load_tables())
        assert "> Owner or operator let the tank run dry." in markdown
        assert "zorvex" not in markdown.lower()

    def test_no_group_is_said(self) -> None:
        assert "No exact-twin group." in cc.groups_markdown([], [], load_tables())


class TestPrivateFile:
    def test_the_default_folder_is_under_the_runs_folder_and_only_it_is_printed(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, folder = _main(capsys)
        assert folder == f"s3-coding-consistency/{_STAMP}"
        made = data / "runs" / "s3-coding-consistency" / _STAMP
        assert [p.name for p in made.iterdir()] == ["largest-groups.md"]

    def test_the_file_holds_the_largest_groups_with_text_and_counts_but_no_case_number(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main(capsys)
        markdown = (
            data / "runs" / "s3-coding-consistency" / _STAMP / "largest-groups.md"
        ).read_text(encoding="utf-8")
        assert markdown.index("## Group 1: 4 cases") < markdown.index("## Group 2: 2 cases")
        assert "> The zephyrine\u2019s marrowfat tangle.\n" in markdown  # the first member's, by id
        assert "- 552230 Landing-Landing Roll / Loss of control on ground: 3\n" in markdown
        assert "- 550230 Landing / Loss of control on ground: 1\n" in markdown
        assert "> Gallimaufry stoat\n" in markdown  # ZQE001's, not ZQE002's with its full stop
        assert "ZQ" not in markdown
        assert not _CASE_NUMBER.search(markdown)

    def test_a_groups_out_dir_is_used_and_printed_relative_to_the_runs_folder_or_by_its_name(
        self, data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        inside = data / "runs" / "elsewhere" / "consistency"
        _, printed = _main(capsys, "--groups-out-dir", str(inside))
        assert printed == "elsewhere/consistency"
        assert (inside / "largest-groups.md").is_file()
        outside = tmp_path / "away" / "here"
        _, printed = _main(capsys, "--groups-out-dir", str(outside))
        assert printed == "here"
        assert (outside / "largest-groups.md").is_file()

    def test_a_folder_inside_the_repository_is_refused_before_anything_is_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def unread(processed: Path) -> object:
            raise AssertionError(f"the pool was read: {processed}")

        monkeypatch.setattr(pp, "read_pool_texts", unread)
        monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
        inside = Path(__file__).resolve().parents[1] / "docs" / "zz-consistency-test"
        with pytest.raises(SystemExit, match="inside the repository"):
            cc.main(["--groups-out-dir", str(inside)], now=lambda: _WHEN)
        assert not inside.exists()
        # The default folder is refused the same way when the runs folder is inside it.
        monkeypatch.setenv("NTSB_RUNS_DIR", str(inside))
        with pytest.raises(SystemExit, match="inside the repository"):
            cc.main([], now=lambda: _WHEN)
        assert not inside.exists()
        assert capsys.readouterr().out == ""

    def test_a_second_folder_in_the_same_second_and_an_existing_file_are_refused(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main(capsys)
        with pytest.raises(SystemExit, match="already exists"):
            cc.main([], now=lambda: _WHEN)
        mine = data / "mine"
        _main(capsys, "--groups-out-dir", str(mine))
        written = (mine / "largest-groups.md").read_text(encoding="utf-8")
        (mine / "largest-groups.md").write_text("kept", encoding="utf-8")
        with pytest.raises(SystemExit, match="never written over"):
            cc.main(["--groups-out-dir", str(mine)], now=lambda: _WHEN)
        assert (mine / "largest-groups.md").read_text(encoding="utf-8") == "kept"
        assert written.startswith("# The 25 largest exact-twin groups")

    def test_nothing_is_printed_or_written_when_a_record_is_not_the_one_the_pool_read(
        self, data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        real = samples.load_cases

        def changed(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]:
            return [
                {**raw, "narratives": [{"probableCause": "Another sentence entirely."}]}
                for raw in real(processed, ids)
            ]

        monkeypatch.setattr(samples, "load_cases", changed)
        with pytest.raises(SystemExit, match="is not the text the pool read"):
            cc.main([], now=lambda: _WHEN)
        assert capsys.readouterr().out == ""
        assert not (data / "runs" / "s3-coding-consistency").exists()

    def test_a_record_of_another_case_is_refused(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def other(processed: Path, ids: Sequence[str]) -> list[Mapping[str, object]]:
            return [_raw("ZQX999", "2010-03-01", _A_TEXT, ("552230",)) for _ in ids]

        monkeypatch.setattr(samples, "load_cases", other)
        with pytest.raises(SystemExit, match="ZQX999's, not its own"):
            cc.main([], now=lambda: _WHEN)


# --------------------------------------------------------------------------------------------
# The pool
# --------------------------------------------------------------------------------------------


class TestPool:
    def test_a_pool_holding_a_sample_case_raises_through_check_pool_before_any_text_is_read(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pool built without the exclusions holds the sealed case: refused."""
        texts_read: list[str] = []
        real = fields.probable_cause

        def spy(raw: Mapping[str, object]) -> str | None:
            texts_read.append("read")
            return real(raw)

        monkeypatch.setattr(
            pp, "pool_cases", lambda rows, *, excluded: cs.pool_cases(rows, excluded=frozenset())
        )
        monkeypatch.setattr(fields, "probable_cause", spy)
        with pytest.raises(LeakageError, match=_SEALED):
            cc.main([], now=lambda: _WHEN)
        assert texts_read == []  # refused before any pool text was read
        assert not (data / "runs").exists()

    def test_the_pool_is_the_precedent_probes_own_reader(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        kept, dates, counts = pp.read_pool_texts(data / "processed")
        assert sorted(c.case_id for c in kept) == sorted(
            r[0] for r in _ROWS if r[0].startswith(("ZQA", "ZQB", "ZQC", "ZQD", "ZQE", "ZQP"))
        )
        assert counts == {"statistics pool": 16, "no text": 1, "no code": 1}
        assert dates["ZQE001"] == "2014-12-31"
