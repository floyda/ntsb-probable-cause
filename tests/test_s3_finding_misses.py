"""scripts/exploratory/s3_finding_misses.py: where the loop's findings go wrong.

S3.1 Task 15, exploratory. Synthetic run folders built from ``CaseResult`` objects and a processed
file of invented cases (invented ids, invented words, real finding codes), whose classes, habits
and counts are worked out by hand in the comments. Offline: no network, no model.
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from scripts import coding_stats as cs
from scripts.exploratory import s3_finding_misses as fm
from scripts.exploratory import s3_finding_precedent as fp
from scripts.exploratory import s3_precedent_probe as pp
from tests.test_coding_stats import _CASE_NUMBER
from tests.test_s3_finding_consistency import _Row, _row
from tests.test_s3_finding_precedent import _IDS, _loop, _one
from tests.test_s3_precedent_probe import _processed, _write_run

from ntsb_probable_cause import fields, gitinfo
from ntsb_probable_cause.errors import LeakageError, SchemaError
from ntsb_probable_cause.scoring import misses, samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import FindingGuess
from ntsb_probable_cause.scoring.records import CaseResult

_RUN_A = "20261001T201506-fd6053f-dev-400-C"
_RUN_B = "20261001T201648-fd6053f-dev-400-C"
_SEALED = "ZQS001"
_TABLES = load_tables()

# Real codes of the committed tables; ten digits are category (6), item (8) and modifier (2).
_A1 = "0101051001"  # 010105 Maintenance/inspections, item 01010510 Time limits, Failure
_A0 = "0101051000"  # the same item, Unknown/Not determined
_A2 = "0101051002"  # the same item, Malfunction
_C1 = "0101052001"  # the same category, item 01010520 Scheduled maint checks, Failure
_C3 = "0101053001"  # the same category, item 01010530 Return to service, Failure
_C5 = "0101055001"  # the same category, item 01010550 Unscheduled maint checks, Failure
_D1 = "0102271001"  # 010227 Flight control system, item 01022710 Aileron control system, Failure
_DM = "0102271002"  # the same item, Malfunction
_DR = "0102272001"  # the same category, item 01022720 Rudder control system, Failure
_P44 = "0201101044"  # 020110 Physical characteristic, item 02011010 Size, Pilot
_WA = "0303404082"  # 030340 Wind, item 03034040 Crosswind, Effect on operation
_WG = "0303404582"  # the same category, item 03034045 Gusts, Effect on operation
_X = "0401101081"  # 040110 Design, item 04011010 Equipment design, Effect on equipment
_N5 = "0500000000"  # 050000 Not determined, item 05000000, Unknown/Not determined
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
_ALL_CODES = (_A1, _A0, _A2, _C1, _C3, _C5, _D1, _DM, _DR, _P44, _WA, _WG, _X, _N5)


def _item(code: str) -> str:
    return f"{code}: {_TABLES.items[code]}"


def _modifier(code: str) -> str:
    return f"{code}: {_TABLES.modifiers[code]}"


def _category(code: str) -> str:
    return f"{code}: {_TABLES.categories[code]}"


# --------------------------------------------------------------------------------------------
# The class of one flagged finding
# --------------------------------------------------------------------------------------------


class TestLevelOf:
    def test_exact_when_the_loop_holds_the_code(self) -> None:
        assert fm.level_of([_C3, _A1], _A1) == "exact"

    def test_item_right_when_only_the_modifier_differs(self) -> None:
        assert fm.level_of([_A2], _A1) == "item right, modifier wrong"

    def test_category_right_when_only_the_first_six_digits_are_shared(self) -> None:
        assert fm.level_of([_C1], _A1) == "category right, item wrong"

    def test_category_missed_when_no_loop_finding_shares_its_category(self) -> None:
        assert fm.level_of([_D1, _WA], _A1) == "category missed"
        assert fm.level_of([], _A1) == "category missed"

    def test_the_deepest_level_any_loop_finding_reaches_wins(self) -> None:
        # Another item of the category (C1) and the right item with another modifier (A2): item.
        assert fm.level_of([_C1, _A2], _A1) == "item right, modifier wrong"
        assert fm.level_of([_A2, _C1], _A1) == "item right, modifier wrong"
        # The exact code among others of its item and its category: exact.
        assert fm.level_of([_C1, _A2, _A1], _A1) == "exact"

    def test_it_is_finding_depth_itself_not_a_copy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        real = misses.finding_depth

        def spy(predicted: Sequence[str], flagged: Sequence[str]) -> object:
            calls.append((tuple(predicted), tuple(flagged)))
            return real(predicted, flagged)

        monkeypatch.setattr(fm, "finding_depth", spy)
        fm.level_of([_A2, _C1], _A1)
        assert calls == [((_A2, _C1), (_A1,))]  # one finding at a time, against the loop's list

    def test_the_four_classes_in_their_order(self) -> None:
        assert fm.LEVELS == (
            "exact",
            "item right, modifier wrong",
            "category right, item wrong",
            "category missed",
        )


# --------------------------------------------------------------------------------------------
# The pool's habits
# --------------------------------------------------------------------------------------------


class TestHabits:
    def test_the_commonest_value_under_each_key_and_its_count(self) -> None:
        # Category 010105: items 01010510 three times, 01010520 once. Category 010227: one item.
        codes = [_A1, _A2, _A0, _C1, _D1]
        found = fm.habits(codes, fm.ITEM.key, fm.ITEM.value)
        assert found == {
            "010105": fm.Habit("01010510", 3, 4, 2),
            "010227": fm.Habit("01022710", 1, 1, 1),
        }

    def test_the_modifier_is_the_commonest_under_each_item(self) -> None:
        codes = [_A1, _A1, _A2, _A0, _C1]
        found = fm.habits(codes, fm.MODIFIER.key, fm.MODIFIER.value)
        # 01010510: 01 twice, 02 once, 00 once. 01010520: 01 once.
        assert found == {
            "01010510": fm.Habit("01", 2, 4, 3),
            "01010520": fm.Habit("01", 1, 1, 1),
        }

    def test_a_tie_goes_to_the_smallest_code_not_the_first_or_the_last_seen(self) -> None:
        # Items 01010520 and 01010510 once each, in both orders: the smaller, 01010510.
        for codes in ([_C1, _A1], [_A1, _C1]):
            found = fm.habits(codes, fm.ITEM.key, fm.ITEM.value)
            assert found["010105"] == fm.Habit("01010510", 1, 2, 2)
        # Modifiers 02 and 01 and 00 once each: 00. Three-way tie, smallest code.
        for codes in ([_A2, _A1, _A0], [_A0, _A1, _A2], [_A1, _A0, _A2]):
            found = fm.habits(codes, fm.MODIFIER.key, fm.MODIFIER.value)
            assert found["01010510"] == fm.Habit("00", 1, 3, 3)

    def test_a_tie_is_broken_among_the_tied_only(self) -> None:
        # 02 twice, 00 once, 01 once: 02 is commonest although it is the largest code.
        found = fm.habits([_A2, _A2, _A0, _A1], fm.MODIFIER.key, fm.MODIFIER.value)
        assert found["01010510"] == fm.Habit("02", 2, 4, 3)

    def test_no_code_no_habit(self) -> None:
        assert fm.habits([], fm.ITEM.key, fm.ITEM.value) == {}

    def test_commonest_value_count_total_and_variety(self) -> None:
        assert fm.commonest({"b": 2, "a": 2, "c": 1}) == fm.Habit("a", 2, 5, 3)


class TestReadPool:
    def test_each_case_counts_each_distinct_code_once(self) -> None:
        # Case one holds A1 twice (one finding), case two holds A1 and C1, case three none.
        pool = fm.read_pool([(_A1, _A1), (_C1, _A1), ()])
        assert (pool.cases, pool.findings) == (2, 3)
        # 010105 holds A1 twice and C1 once: the item 01010510 has 2 of 3.
        assert pool.items["010105"] == fm.Habit("01010510", 2, 3, 2)
        assert pool.modifiers["01010510"] == fm.Habit("01", 2, 2, 1)

    def test_a_case_with_no_flagged_finding_is_not_counted(self) -> None:
        pool = fm.read_pool([(), ()])
        assert (pool.cases, pool.findings) == (0, 0)
        assert pool.items == {}
        assert pool.modifiers == {}

    def test_the_order_of_a_cases_codes_does_not_matter(self) -> None:
        assert fm.read_pool([(_A1, _C1, _A2)]) == fm.read_pool([(_A2, _A1, _C1)])


def _habit_map(shares: Sequence[tuple[int, int, int]]) -> dict[str, fm.Habit]:
    """A habit map: one key per (count, total, distinct)."""
    return {f"key{n}": fm.Habit("v", c, t, d) for n, (c, t, d) in enumerate(shares)}


class TestSummarise:
    def test_the_findings_weighted_share_is_the_sum_of_commonest_over_the_sum_of_findings(
        self,
    ) -> None:
        found = fm.summarise(_habit_map([(4, 6, 2), (1, 1, 1), (10, 20, 3)]))
        assert (found.keys, found.top, found.findings) == (3, 15, 27)  # not a mean of the shares

    def test_a_key_needs_at_least_ten_pool_findings_to_be_read(self) -> None:
        # Nine findings, all one value: not read. Ten: read. Eleven: read.
        found = fm.summarise(_habit_map([(9, 9, 1), (10, 10, 1), (11, 11, 1)]))
        assert (found.big, found.high) == (2, 2)

    def test_exactly_eighty_percent_counts_and_just_under_does_not(self) -> None:
        found = fm.summarise(_habit_map([(8, 10, 2), (16, 20, 2), (7, 10, 2), (15, 20, 2)]))
        assert (found.big, found.high) == (4, 2)

    def test_a_key_under_the_threshold_is_not_high_whatever_its_share(self) -> None:
        found = fm.summarise(_habit_map([(5, 5, 1), (4, 5, 2), (9, 9, 1)]))
        assert (found.big, found.high) == (0, 0)

    def test_those_with_one_value_only_are_counted_among_the_high_ones(self) -> None:
        found = fm.summarise(_habit_map([(12, 12, 1), (9, 10, 2), (10, 10, 1), (5, 10, 4)]))
        assert (found.big, found.high, found.single) == (4, 3, 2)

    def test_an_empty_map(self) -> None:
        assert fm.summarise({}) == fm.Summary(0, 0, 0, 0, 0, 0)


class TestSummaryLines:
    def test_the_two_lines_for_the_item_and_for_the_modifier(self) -> None:
        pool = fm.Pool(
            cases=9,
            findings=40,
            items=_habit_map([(18, 20, 2), (10, 12, 1), (5, 8, 3)]),
            modifiers=_habit_map([(8, 10, 2), (3, 4, 2)]),
        )
        lines = fm.summary_lines(pool)
        text = "\n".join(lines)
        assert "Pool findings: 40 in 9 cases" in text
        item = text[text.index("The commonest item") : text.index("The commonest modifier")]
        assert "(3 categories hold a pool finding)" in item
        assert (
            "findings-weighted mean of the commonest item's share across categories, that is the "
            "pool's findings carrying their category's commonest item: 33 of 40 (82.5%)"
        ) in item
        assert (
            "categories with at least 10 pool findings: 2 of 3; of those, with a commonest item "
            "carrying at least 80% of the category's findings: 2 of 2 (100.0%), of which 1 hold "
            "one item only in the pool"
        ) in item
        modifier = text[text.index("The commonest modifier") :]
        assert "(2 items hold a pool finding)" in modifier
        assert "carrying their item's commonest modifier: 11 of 14 (78.6%)" in modifier
        assert (
            "items with at least 10 pool findings: 1 of 2; of those, with a commonest modifier "
            "carrying at least 80% of the item's findings: 1 of 1 (100.0%), of which 0 hold one "
            "modifier only in the pool"
        ) in modifier


# --------------------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------------------


class TestNextStep:
    def test_exactly_half_goes_to_the_usual_item_line(self) -> None:
        assert fm.next_step(5, 10) == "next: an offline 'use the usual item' test"
        assert fm.next_step(1, 2) == fm.USE_USUAL

    def test_just_under_half_goes_to_the_case_specific_line(self) -> None:
        assert fm.next_step(4, 10) == (
            "next: item choice read as case-specific; report findings at the category level "
            "beside the full code"
        )
        assert fm.next_step(2, 5) == fm.CASE_SPECIFIC  # 2 * 2 = 4 < 5
        assert fm.next_step(0, 1) == fm.CASE_SPECIFIC

    def test_more_than_half_and_all(self) -> None:
        assert fm.next_step(6, 10) == fm.USE_USUAL
        assert fm.next_step(3, 5) == fm.USE_USUAL  # an odd total: 3 * 2 = 6 >= 5
        assert fm.next_step(7, 7) == fm.USE_USUAL

    def test_none_of_none_is_not_at_least_half(self) -> None:
        assert not fm.at_least_half(0, 0)
        assert fm.next_step(0, 0) == fm.CASE_SPECIFIC

    def test_at_least_half(self) -> None:
        assert fm.at_least_half(5, 10)
        assert not fm.at_least_half(4, 10)
        assert fm.at_least_half(2, 3)
        assert not fm.at_least_half(1, 3)


def _misses(total: int, usual: int) -> fm.Misses:
    return fm.Misses(total, usual, 0, 0, {}, {})


def _reading(run_id: str, item: fm.Misses, modifier: fm.Misses) -> fm.RunReading:
    return fm.RunReading(run_id, fp.CaseSplit(0, 0, 0, 0, ()), (), 0, {}, {}, item, modifier)


def _rule(a: tuple[int, int, int], b: tuple[int, int, int]) -> list[str]:
    """The rule's lines for run a and run b, each given as (item misses, usual, modifier misses)."""
    return fm.rule_lines(
        [
            _reading("run-a-id", _misses(a[0], a[1]), _misses(a[2], 0)),
            _reading("run-b-id", _misses(b[0], b[1]), _misses(b[2], 0)),
        ]
    )


class TestRuleLines:
    def test_the_committed_rule_and_the_expectation_are_printed_verbatim(self) -> None:
        lines = _rule((10, 5, 3), (10, 0, 3))
        assert lines[2] == (
            'Next-step rule (Andy, 2026-10-03). On run a: if, among the "category right, item '
            "wrong\" findings, the NTSB's item is the pool's commonest item for that category "
            'in at least half, the next step is an offline test of a "use the usual item" step '
            "(registered before it is computed); otherwise item choice is read as case-specific "
            "judgement, and findings are reported at the category level beside the full code. "
            "The script applies the rule and prints which."
        )
        assert (
            "Expectation (decides nothing). The item step loses more of the loop's findings "
            "than the modifier step, and the NTSB's item is the pool's commonest item in at "
            "least half of the item misses."
        ) in lines

    def test_exactly_half_prints_the_usual_item_line_with_the_count_and_total(self) -> None:
        lines = _rule((10, 5, 3), (10, 0, 3))
        assert "next: an offline 'use the usual item' test" in lines
        assert (
            "next: item choice read as case-specific; report findings at the category level"
            not in ("\n".join(lines))
        )
        assert (
            'Run a (run-a-id): among the 10 findings classed "category right, item wrong", the '
            "NTSB's item is the pool's commonest item for its category in 5 of 10 (50.0%)."
        ) in lines

    def test_just_under_half_prints_the_case_specific_line(self) -> None:
        lines = _rule((10, 4, 3), (10, 10, 3))
        assert (
            "next: item choice read as case-specific; report findings at the category level "
            "beside the full code"
        ) in lines
        assert "next: an offline 'use the usual item' test" not in lines

    def test_exactly_one_next_line_in_the_block(self) -> None:
        for numbers in ((10, 5, 3), (10, 4, 3), (0, 0, 2)):
            lines = _rule(numbers, (10, 10, 3))
            assert sum(line.startswith("next:") for line in lines) == 1

    def test_the_line_is_read_on_run_a_only_run_b_decides_nothing(self) -> None:
        lines = _rule((10, 2, 3), (10, 9, 3))  # run b is far above half; run a is not
        assert fm.CASE_SPECIFIC in lines
        assert fm.USE_USUAL not in lines
        assert (
            "Run b (run-b-id), beside it, decides nothing: the NTSB's item is the pool's "
            "commonest in 9 of 10 (90.0%)."
        ) in lines
        lines = _rule((10, 6, 3), (10, 0, 3))
        assert fm.USE_USUAL in lines
        assert fm.CASE_SPECIFIC not in lines

    def test_expectation_part_one_is_strict_the_item_step_must_lose_more(self) -> None:
        part = 'on run a: "category right, item wrong" 4 against "item right, modifier wrong" 3'
        lines = _rule((4, 4, 3), (1, 1, 1))
        assert (
            f"- the item step loses more of the loop's findings than the modifier step, {part}: met"
            in lines
        )
        part = 'on run a: "category right, item wrong" 3 against "item right, modifier wrong" 3'
        lines = _rule((3, 3, 3), (1, 1, 1))
        assert (
            f"- the item step loses more of the loop's findings than the modifier step, {part}: "
            "not met"
        ) in lines
        part = 'on run a: "category right, item wrong" 2 against "item right, modifier wrong" 3'
        lines = _rule((2, 2, 3), (1, 1, 1))
        assert f"than the modifier step, {part}: not met" in "\n".join(lines)

    def test_expectation_part_two_is_the_at_least_half_part_on_run_a(self) -> None:
        met = "- the NTSB's item is the pool's commonest item in at least half of the item misses"
        lines = _rule((10, 5, 3), (10, 0, 3))
        assert f"{met}, on run a, 5 of 10 (50.0%): met" in lines
        lines = _rule((10, 4, 3), (10, 10, 3))
        assert f"{met}, on run a, 4 of 10 (40.0%): not met" in lines

    def test_the_two_parts_are_judged_apart(self) -> None:
        # Part one met (10 > 3), part two not met (1 of 10).
        text = "\n".join(_rule((10, 1, 3), (10, 10, 3)))
        assert 'modifier wrong" 3: met' in text
        assert "1 of 10 (10.0%): not met" in text
        # Part one not met (2 < 5), part two met (2 of 2).
        text = "\n".join(_rule((2, 2, 5), (10, 0, 3)))
        assert 'modifier wrong" 5: not met' in text
        assert "2 of 2 (100.0%): met" in text

    def test_no_item_miss_reads_the_second_branch_and_says_so(self) -> None:
        lines = _rule((0, 0, 2), (5, 5, 2))
        assert fm.CASE_SPECIFIC in lines
        assert any(line.startswith("Note: no finding is classed") for line in lines)
        assert "0 of 0: not met" in "\n".join(lines)
        assert not any(line.startswith("Note:") for line in _rule((4, 2, 2), (5, 5, 2)))


# --------------------------------------------------------------------------------------------
# Reading the misses
# --------------------------------------------------------------------------------------------


def _flag(code: str, level: fm.Level, loop: Sequence[str] = (), *, fatal: bool = False) -> fm.Flag:
    return fm.Flag(code, level, fatal, tuple(loop))


_POOL_ITEMS = {"010105": fm.Habit("01010510", 4, 6, 2), "010227": fm.Habit("01022710", 2, 2, 1)}
_POOL_MODIFIERS = {
    "01010510": fm.Habit("01", 3, 4, 2),
    "01010520": fm.Habit("01", 2, 2, 1),
}


class TestReadMisses:
    def test_the_ntsb_item_is_or_is_not_the_pools_commonest(self) -> None:
        flags = [
            _flag(_A1, "category right, item wrong", [_C3]),  # NTSB item 01010510: the commonest
            _flag(_C1, "category right, item wrong", [_C3]),  # 01010520: not
            _flag(
                _D1, "category right, item wrong", [_DR]
            ),  # 01022710, the only item: the commonest
        ]
        found = fm.read_misses(flags, fm.ITEM, _POOL_ITEMS)
        assert (found.total, found.ntsb_usual, found.loop_usual, found.no_habit) == (3, 2, 0, 0)

    def test_the_loops_item_is_or_is_not_the_pools_commonest(self) -> None:
        flags = [
            _flag(_C1, "category right, item wrong", [_A1]),  # the loop used 01010510: usual
            _flag(_C1, "category right, item wrong", [_C3]),  # 01010530: not
            _flag(_D1, "category right, item wrong", [_DR]),  # 01022720 against 01022710: not
        ]
        found = fm.read_misses(flags, fm.ITEM, _POOL_ITEMS)
        assert (found.ntsb_usual, found.loop_usual) == (1, 1)

    def test_several_loop_findings_in_the_category_count_as_usual_if_any_carries_it(self) -> None:
        flags = [_flag(_C1, "category right, item wrong", [_C3, _C5, _A2])]
        found = fm.read_misses(flags, fm.ITEM, _POOL_ITEMS)
        assert found.loop_usual == 1  # A2 is item 01010510
        flags = [_flag(_C1, "category right, item wrong", [_C3, _C5])]
        assert fm.read_misses(flags, fm.ITEM, _POOL_ITEMS).loop_usual == 0

    def test_each_finding_counts_once_for_the_usual_counts_however_many_loop_findings(
        self,
    ) -> None:
        flags = [_flag(_C1, "category right, item wrong", [_A1, _A2, _A0])]  # three usual items
        found = fm.read_misses(flags, fm.ITEM, _POOL_ITEMS)
        assert (found.total, found.loop_usual) == (1, 1)

    def test_a_category_the_pool_holds_nothing_in_is_counted_apart(self) -> None:
        flags = [
            _flag(_WA, "category right, item wrong", [_WG]),  # 030340 is not in this pool
            _flag(_C1, "category right, item wrong", [_C3]),
        ]
        found = fm.read_misses(flags, fm.ITEM, _POOL_ITEMS)
        assert (found.total, found.no_habit, found.ntsb_usual, found.loop_usual) == (2, 1, 0, 0)

    def test_only_the_findings_of_the_step_are_read(self) -> None:
        flags = [
            _flag(_A1, "exact", [_A1]),
            _flag(_A1, "item right, modifier wrong", [_A2]),
            _flag(_C1, "category right, item wrong", [_C3]),
            _flag(_P44, "category missed", []),
        ]
        assert fm.read_misses(flags, fm.ITEM, _POOL_ITEMS).total == 1
        assert fm.read_misses(flags, fm.MODIFIER, _POOL_MODIFIERS).total == 1

    def test_a_pair_per_different_loop_item_in_the_category(self) -> None:
        flags = [
            _flag(_C1, "category right, item wrong", [_C3, _C5, _C3]),  # C3's item twice: once
            _flag(_C1, "category right, item wrong", [_C3]),
        ]
        found = fm.read_misses(flags, fm.ITEM, _POOL_ITEMS)
        assert found.pairs == {("01010520", "01010530"): 2, ("01010520", "01010550"): 1}

    def test_the_keys_with_their_misses_and_those_whose_ntsb_item_is_usual(self) -> None:
        flags = [
            _flag(_A1, "category right, item wrong", [_C3]),  # 010105, usual
            _flag(_C1, "category right, item wrong", [_C3]),  # 010105, not
            _flag(_D1, "category right, item wrong", [_DR]),  # 010227, usual
        ]
        found = fm.read_misses(flags, fm.ITEM, _POOL_ITEMS)
        assert found.keys == {"010105": (2, 1), "010227": (1, 1)}

    def test_the_modifier_step_reads_the_modifier_under_the_item(self) -> None:
        flags = [
            _flag(_A2, "item right, modifier wrong", [_A1]),  # NTSB 02, loop 01: loop usual
            _flag(_A1, "item right, modifier wrong", [_A2]),  # NTSB 01 usual, loop 02: not
            _flag(_A0, "item right, modifier wrong", [_A1]),  # NTSB 00: not usual; loop usual
        ]
        found = fm.read_misses(flags, fm.MODIFIER, _POOL_MODIFIERS)
        assert (found.total, found.ntsb_usual, found.loop_usual, found.no_habit) == (3, 1, 2, 0)
        assert found.pairs == {("02", "01"): 1, ("01", "02"): 1, ("00", "01"): 1}
        assert found.keys == {"01010510": (3, 1)}

    def test_the_modifier_step_ignores_the_loops_other_items_of_the_category(self) -> None:
        # The loop also named another item of the category (C3, modifier 01): not a modifier of
        # the NTSB's item, so it gives no pair and cannot make the loop's modifier "usual".
        flags = [_flag(_A2, "item right, modifier wrong", [_C3, _A0])]
        found = fm.read_misses(flags, fm.MODIFIER, {"01010510": fm.Habit("01", 3, 4, 2)})
        assert found.pairs == {("02", "00"): 1}
        assert found.loop_usual == 0

    def test_an_item_the_pool_holds_nothing_in_is_counted_apart_at_the_modifier_step(self) -> None:
        flags = [_flag(_WA, "item right, modifier wrong", [_WA[:8] + "81"])]
        found = fm.read_misses(flags, fm.MODIFIER, _POOL_MODIFIERS)
        assert (found.total, found.no_habit) == (1, 1)

    def test_no_miss_at_a_step(self) -> None:
        found = fm.read_misses([_flag(_A1, "exact", [_A1])], fm.ITEM, _POOL_ITEMS)
        assert found == fm.Misses(0, 0, 0, 0, {}, {})

    def test_a_pair_never_names_the_same_value_twice(self) -> None:
        # By the classes: the loop's value under a miss differs from the NTSB's.
        flags = [
            _flag(_C1, "category right, item wrong", [_C3, _A1]),
            _flag(_A2, "item right, modifier wrong", [_A1, _A0]),
        ]
        for step, pool in ((fm.ITEM, _POOL_ITEMS), (fm.MODIFIER, _POOL_MODIFIERS)):
            found = fm.read_misses(flags, step, pool)
            assert all(theirs != ours for theirs, ours in found.pairs)


# --------------------------------------------------------------------------------------------
# The lines of one step
# --------------------------------------------------------------------------------------------


class TestStepLines:
    def _twelve(self) -> fm.Misses:
        # Twelve different pairs, counts 12 down to 1 and a tie at 1: only ten are printed, the
        # commonest first, ties by the codes.
        pairs = {("01010510", f"010105{n:02d}"): 13 - n for n in range(1, 13)}
        pairs[("01010510", "01010599")] = 1
        keys = {f"0102{n:02d}": (n, 0) for n in range(1, 13)}
        return fm.Misses(sum(pairs.values()), 0, 0, 0, pairs, keys)

    def test_only_the_ten_commonest_pairs_are_printed_commonest_first(self) -> None:
        lines = fm._step_lines(self._twelve(), fm.ITEM, {}, _TABLES)
        start = next(n for n, line in enumerate(lines) if line.startswith("The 10 commonest"))
        block = lines[start + 1 : lines.index("", start)]  # ends at the blank line before the keys
        assert len(block) == 10
        counts = [int(line.split()[1]) for line in block]
        assert counts == sorted(counts, reverse=True)
        assert counts[0] == 12
        assert "(13 different pairs, from" in lines[start]

    def test_only_the_ten_keys_with_the_most_misses_are_printed_most_first(self) -> None:
        lines = fm._step_lines(self._twelve(), fm.ITEM, {}, _TABLES)
        start = next(n for n, line in enumerate(lines) if "categories with the most item" in line)
        block = lines[start + 1 :]
        assert len(block) == 10
        assert [int(line.split()[1]) for line in block] == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3]
        assert "(12 categories lose a finding at this step)" in lines[start]

    def test_ties_among_pairs_and_keys_go_to_the_smaller_code(self) -> None:
        found = fm.Misses(
            3,
            0,
            0,
            0,
            {("01010520", "01010550"): 1, ("01010510", "01010530"): 1, ("01010510", "01010520"): 1},
            {"010227": (1, 0), "010105": (1, 0)},
        )
        lines = fm._step_lines(found, fm.ITEM, {}, _TABLES)
        arrows = [line for line in lines if " -> " in line]
        assert [line.split(" -> ")[0].split(": ")[0].split()[-1] for line in arrows] == [
            "01010510",
            "01010510",
            "01010520",
        ]
        assert arrows[0].endswith(_item("01010520"))
        keys = [line for line in lines if "the NTSB's item is the pool's commonest in" in line]
        assert [line.split()[2] for line in keys] == ["010105:", "010227:"]

    def test_no_miss_prints_one_line(self) -> None:
        assert fm._step_lines(fm.Misses(0, 0, 0, 0, {}, {}), fm.ITEM, {}, _TABLES) == [
            '- no finding is classed "category right, item wrong"'
        ]

    def test_a_key_the_pool_holds_nothing_under_says_so(self) -> None:
        found = fm.Misses(1, 0, 0, 1, {("03034040", "03034045"): 1}, {"030340": (1, 0)})
        lines = fm._step_lines(found, fm.ITEM, {}, _TABLES)
        assert any(line.endswith("the pool holds no finding under it") for line in lines)


# --------------------------------------------------------------------------------------------
# The sections
# --------------------------------------------------------------------------------------------


class TestSectionLabels:
    def test_each_section_is_named_as_the_code_tables_name_it(self) -> None:
        assert fm.section_labels(_TABLES) == {
            "01": "Aircraft",
            "02": "Personnel issues",
            "03": "Environmental issues",
            "04": "Organizational issues",
            "05": "Not determined",
        }


# --------------------------------------------------------------------------------------------
# A synthetic world
# --------------------------------------------------------------------------------------------
#
# The pool (kept: a text and an occurrence code; 8 cases, 7 with a flagged finding; 12 findings,
# each case counting each distinct code once):
#   ZQP001 {A1, D1}   ZQP002 {A1, C1}   ZQP003 {A2, P44}   ZQP004 {C1}
#   ZQP005 {A1, A1}   (one finding)     ZQP006 {WA, X}     ZQP007 {WG, DM}    ZQP008 none
# Left out of the pool, each flagged {C5} and so visible if it leaked: ZQN001 (no text), ZQN002
# (no occurrence code), a sealed sample's case, a class I case, a held-out case, and every
# judged case's own row.
#
# Habits. Items under each category: 010105 holds A1 x3, A2, C1 x2 = 6 findings, 01010510 on 4;
# 010227 holds D1, DM: 01022710 on 2 of 2; 020110: 02011010 1 of 1; 030340 holds WA (03034040)
# and WG (03034045), a tie: 03034040, 1 of 2; 040110: 04011010 1 of 1. Top: 4+2+1+1+1 = 9 of 12.
# Modifiers under each item: 01010510: 01 on 3 of 4; 01010520: 01 on 2 of 2; 01022710: 01 and 02
# once each, a tie: 01, 1 of 2; 02011010: 44; 03034040: 82; 03034045: 82; 04011010: 81. Top:
# 3+2+1+1+1+1+1 = 10 of 12.
#
# Run a, cases (the loop's final findings in brackets), fatal ones marked *:
#   ZQX000*  NTSB {A1, D1, WA, P44}  loop [A1, DR, WG, X]
#   ZQX001*  failed                  ZQX002  abstained        ZQX003  no flagged finding
#   ZQX004   NTSB {A1, C1}           loop [A2, C3, C5]
#   ZQX005   NTSB {A0, D1, N5}       loop [C3]
#   ZQX006*  NTSB {WA, WA}           loop [WA, WA]
#   ZQX007*  failed
# Judged: 000, 004, 005, 006. Classes of the 10 flagged findings (the doubled WA once):
#   000: A1 exact; D1 item wrong (DR); WA item wrong (WG); P44 missed
#   004: A1 item right (A2); C1 item wrong (C3, C5, A2 are all of its category, none its item)
#   005: A0 item wrong (C3); D1 missed; N5 missed
#   006: WA exact
# So exact 2, item right 1, category right 4, missed 3. Item misses: D1 (usual item, the loop's
# not), WA (usual by the tie rule, the loop's not), C1 (not usual; the loop's items include the
# usual 01010510), A0 (usual; the loop's not): the NTSB's item usual in 3 of 4, the loop's in 1.
# The modifier miss: A1 (NTSB 01, the usual; the loop's 02).
#
# Run b: ZQX000's loop is [A1], ZQX005's [D1], ZQX006 failed. Judged: 000, 004, 005.


def _loop_findings(case: CaseResult, codes: Sequence[str]) -> CaseResult:
    """The case with its final answer's findings set to these ten-digit codes (item attached)."""
    step = case.steps[0]
    guesses = tuple(
        FindingGuess(category6=c[:6], modifier=c[8:], probability=0.5, item8=c[:8]) for c in codes
    )
    hypothesis = step.hypothesis.model_copy(update={"findings": guesses})
    return case.model_copy(update={"steps": (step.model_copy(update={"hypothesis": hypothesis}),)})


def _answered(
    case_id: str, own: Sequence[str], loop: Sequence[str], *, abstain: bool = False
) -> CaseResult:
    return _loop_findings(_one(case_id, own, abstain=abstain), loop)


def _run_a() -> list[CaseResult]:
    return [
        _answered("ZQX000", (_A1, _D1, _WA, _P44), (_A1, _DR, _WG, _X)),
        _one("ZQX001", failed=True),
        _answered("ZQX002", (_A1,), (_A1,), abstain=True),
        _answered("ZQX003", (), (_A1,)),
        _answered("ZQX004", (_A1, _C1), (_A2, _C3, _C5)),
        _answered("ZQX005", (_A0, _D1, _N5), (_C3,)),
        _answered("ZQX006", (_WA, _WA), (_WA, _WA)),
        _one("ZQX007", (), failed=True),
    ]


def _run_b() -> list[CaseResult]:
    cases = _run_a()
    cases[0] = _answered("ZQX000", (_A1, _D1, _WA, _P44), (_A1,))
    cases[5] = _answered("ZQX005", (_A0, _D1, _N5), (_D1,))
    cases[6] = _one("ZQX006", (_WA, _WA), failed=True)
    return cases


def _pool_rows() -> list[_Row]:
    return [
        _row("ZQP001", "2010-03-01", "brambleton", (_A1, _D1)),
        _row("ZQP002", "2011-03-01", "gallimaufry", (_A1, _C1)),
        _row("ZQP003", "2012-03-01", "stoat", (_A2, _P44)),
        _row("ZQP004", "2013-03-01", "tangle", (_C1,)),
        _row("ZQP005", "2014-03-01", "quillfern", (_A1, _A1)),
        _row("ZQP006", "2015-03-01", "zorvexine", (_WA, _X)),
        _row("ZQP007", "2016-03-01", "zephyrine", (_WG, _DM)),
        _row("ZQP008", "2017-03-01", "marrowfat", ()),
        _row("ZQN001", "2012-07-01", "", (_C5,)),
        _row("ZQN002", "2012-08-01", "thistlebrook", (_C5,), codes=()),
        _row(_SEALED, "2012-09-01", "thistlecomb", (_C5, _C5)),
        _row("ZQI001", "2012-10-01", "brambleton", (_C5,), klass="I"),
        _row("ZQH001", "2021-01-01", "brambleton", (_C5,), split="heldout"),
    ]


def _all_rows() -> list[_Row]:
    return [*_pool_rows(), *(_row(case_id, "2016-06-01", "judged", (_C5,)) for case_id in _IDS)]


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
    assert fm.main(argv) == 0
    return capsys.readouterr().out


def _section(text: str, start: str, end: str | None = None) -> str:
    begin = text.index(start)
    stop = text.find(end, begin + 1) if end is not None else -1
    return text[begin : stop if stop != -1 else len(text)]


def _lines(text: str) -> list[str]:
    return text.splitlines()


class TestReadRun:
    """The reading itself, without the text."""

    @staticmethod
    def _read(cases: Sequence[CaseResult], pool: fm.Pool | None = None) -> fm.RunReading:
        split = fp.sort_cases(cases)
        return fm.read_run(
            "run-id",
            split,
            _TABLES,
            fm.read_pool([(_A1, _D1), (_A1, _C1)]) if pool is None else pool,
        )

    def test_each_flagged_finding_is_classed_in_the_order_of_the_cases(self) -> None:
        found = self._read(_run_a())
        assert [(flag.code, flag.level) for flag in found.flags] == [
            (_A1, "exact"),
            (_D1, "category right, item wrong"),
            (_WA, "category right, item wrong"),
            (_P44, "category missed"),
            (_A1, "item right, modifier wrong"),
            (_C1, "category right, item wrong"),
            (_A0, "category right, item wrong"),
            (_D1, "category missed"),
            (_N5, "category missed"),
            (_WA, "exact"),
        ]

    def test_a_code_the_ntsb_flagged_twice_in_a_case_is_one_finding(self) -> None:
        found = self._read(_run_a())
        assert found.repeated == 1
        assert [flag.code for flag in found.flags].count(_WA) == 2  # ZQX000's, and ZQX006's once
        assert len(found.flags) == 10

    def test_the_loops_findings_in_the_flags_category_ride_with_the_flag(self) -> None:
        found = self._read(_run_a())
        by_position = [flag.loop for flag in found.flags]
        assert by_position[0] == (_A1,)  # A1: the loop's findings of 010105
        assert by_position[1] == (_DR,)
        assert by_position[3] == ()  # P44: none in 020110
        assert by_position[5] == (_A2, _C3, _C5)  # C1: every loop finding of 010105, in order
        assert by_position[9] == (_WA,)  # the loop's doubled WA is one

    def test_fatal_is_the_cases(self) -> None:
        found = self._read(_run_a())
        assert [flag.fatal for flag in found.flags] == [True] * 4 + [False] * 5 + [True]

    def test_the_loops_findings_by_section_and_those_reaching_no_flagged_finding(self) -> None:
        found = self._read(_run_a())
        assert found.loop_by_section == {"01": 6, "03": 2, "04": 1}
        assert found.unmatched_by_section == {"04": 1}

    def test_a_loop_finding_is_unmatched_at_the_category_not_the_item(self) -> None:
        # The loop's C5 is another item of the NTSB's category 010105: matched at 6 digits.
        found = self._read([_answered("ZQX000", (_A1,), (_C5, _DR))])
        assert found.unmatched_by_section == {"01": 1}  # DR is 010227; the NTSB flagged 010105
        assert found.loop_by_section == {"01": 2}

    def test_a_finding_the_loop_named_without_an_item_is_not_one_of_its_final_findings(
        self,
    ) -> None:
        case = _answered("ZQX000", (_A1,), (_A1,))
        step = case.steps[0]
        guesses = (
            *step.hypothesis.findings,
            FindingGuess(category6="010227", modifier="01", probability=0.2, item8=None),
        )
        hypothesis = step.hypothesis.model_copy(update={"findings": guesses})
        case = case.model_copy(
            update={"steps": (step.model_copy(update={"hypothesis": hypothesis}),)}
        )
        found = self._read([case])
        assert found.loop_by_section == {"01": 1}  # the scored findings only
        assert found.unmatched_by_section == {}

    def test_the_final_answer_is_the_last_step_not_the_first(self) -> None:
        first = _answered("ZQX000", (_A1,), (_DR,))  # an early answer that misses
        last = _answered("ZQX000", (_A1,), (_A1,)).steps[0]
        case = first.model_copy(update={"steps": (*first.steps, last)})
        found = self._read([case])
        assert [flag.level for flag in found.flags] == ["exact"]

    def test_failed_abstained_and_unflagged_cases_are_not_read(self) -> None:
        cases = [
            _one("ZQX001", failed=True),
            _answered("ZQX002", (_A1,), (_A1,), abstain=True),
            _answered("ZQX003", (), (_A1,)),
        ]
        found = self._read(cases)
        assert found.flags == ()
        assert (found.loop_by_section, found.repeated) == ({}, 0)

    def test_the_two_steps_are_read_against_the_pools_habits(self) -> None:
        pool = fm.read_pool(
            [(_A1, _D1), (_A1, _C1), (_A2, _P44), (_C1,), (_A1,), (_WA, _X), (_WG, _DM)]
        )
        found = self._read(_run_a(), pool)
        assert (found.item.total, found.item.ntsb_usual, found.item.loop_usual) == (4, 3, 1)
        assert (found.modifier.total, found.modifier.ntsb_usual) == (1, 1)

    def test_a_loop_finding_with_an_item_outside_the_tables_is_refused(self) -> None:
        case = _answered("ZQX000", (_A1,), (_A1,))
        step = case.steps[0]
        bad = FindingGuess(category6="999999", modifier="01", probability=0.5, item8="99999999")
        hypothesis = step.hypothesis.model_copy(update={"findings": (bad,)})
        case = case.model_copy(
            update={"steps": (step.model_copy(update={"hypothesis": hypothesis}),)}
        )
        with pytest.raises(SchemaError, match="unknown finding item"):
            self._read([case])


# --------------------------------------------------------------------------------------------
# The whole report
# --------------------------------------------------------------------------------------------


class TestReport:
    def test_the_head_comes_first_then_the_rule_the_method_the_habits_and_each_run(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        assert text.startswith(
            "S3.1 where-the-findings-go-wrong probe on dev-400 (scripts/exploratory/"
        )
        assert f"run a = {_RUN_A}\nrun b = {_RUN_B} (printed beside run a; decides nothing)" in text
        marks = [
            "## The rule",
            "## Method",
            "## The pool's habits",
            f"## Run a ({_RUN_A})",
            f"## Run b ({_RUN_B}), beside",
        ]
        assert [text.index(mark) for mark in marks] == sorted(text.index(mark) for mark in marks)

    def test_the_rule_is_applied_to_run_a_and_the_line_printed(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rule = _section(_report(_argv(), capsys), "## The rule", "## Method")
        assert rule.startswith("## The rule (committed in ef25347, before this script existed)")
        assert fm.RULE in rule
        assert (
            f'Run a ({_RUN_A}): among the 4 findings classed "category right, item wrong", the '
            "NTSB's item is the pool's commonest item for its category in 3 of 4 (75.0%)."
        ) in rule
        assert (
            f"Run b ({_RUN_B}), beside it, decides nothing: the NTSB's item is the pool's "
            "commonest in 0 of 1 (0.0%)."
        ) in rule
        assert "next: an offline 'use the usual item' test" in _lines(rule)
        assert fm.CASE_SPECIFIC not in rule
        assert 'wrong" 4 against "item right, modifier wrong" 1: met' in rule
        assert "3 of 4 (75.0%): met" in rule
        assert "not met" not in rule

    def test_run_b_in_the_other_position_flips_the_line_and_the_expectation(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Run b read as run a: one item miss, whose item is not the usual one; the modifier step
        # loses one finding too, so the item step does not lose more.
        rule = _section(_report(["--runs", _RUN_B, _RUN_A], capsys), "## The rule", "## Method")
        assert fm.CASE_SPECIFIC in _lines(rule)
        assert fm.USE_USUAL not in _lines(rule)
        assert 'wrong" 1 against "item right, modifier wrong" 1: not met' in rule
        assert "0 of 1 (0.0%): not met" in rule

    def test_the_method_states_the_definitions_the_pool_and_the_choices(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        method = _section(_report(_argv(), capsys), "## Method", "## The pool's habits")
        assert f"the S3 statistics pool, {cs.STAGES['s3'].built_from}: 10 cases;" in method
        assert "occurrence code: 8 (event years 2010-2017); left out: 1 with no" in method
        assert "1 more with no occurrence code." in method
        assert (
            "Of the kept cases 7 have at least one finding flagged as cause, holding 12" in method
        )
        assert "`scoring.misses.finding_depth`" in method
        assert "`s3_finding_precedent.sort_cases`" in method
        assert "the first eight digits, not all ten" in method
        assert "A tie goes to the smallest code." in method
        assert "Wilson 95% intervals treat findings as independent" in method
        assert "not the trail pages' 'matches no NTSB finding'" in method
        assert "The rule is applied above on run a." in method

    def test_the_pools_habits_are_counted_once_per_case_and_leave_out_the_other_cases(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        habits = _section(_report(_argv(), capsys), "## The pool's habits", "## Run a")
        assert "Pool findings: 12 in 7 cases" in habits
        assert (
            "The commonest item under each category (5 categories hold a pool finding):" in habits
        )
        assert (
            "the pool's findings carrying their category's commonest item: 9 of 12 (75.0%)"
        ) in habits
        assert (
            "categories with at least 10 pool findings: 0 of 5; of those, with a commonest item "
            "carrying at least 80% of the category's findings: 0 of 0, of which 0 hold one item "
            "only in the pool"
        ) in habits
        assert "The commonest modifier under each item (7 items hold a pool finding):" in habits
        assert (
            "the pool's findings carrying their item's commonest modifier: 10 of 12 (83.3%)"
        ) in habits

    def test_the_cases_of_each_run_are_counted_once_each(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        a = _section(text, f"## Run a ({_RUN_A})", "## Run b")
        assert (
            "Cases in the run: 8, each counted once, in this order: failed 2; abstained 1; "
            "no flagged finding 1; judged 4 (2 fatal, 2 non-fatal)." in a
        )
        assert (
            "The NTSB's flagged findings of the judged cases: 10 (each ten-digit code once per "
            "case; a code flagged twice in one case, left out once: 1)." in a
        )
        b = _section(text, "## Run b")
        assert (
            "Cases in the run: 8, each counted once, in this order: failed 3; abstained 1; "
            "no flagged finding 1; judged 3 (1 fatal, 2 non-fatal)." in b
        )
        assert "left out once: 0)." in b

    def test_the_four_classes_overall_with_wilson_intervals(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), f"## Run a ({_RUN_A})", "## Run b")
        overall = _section(a, "### All judged cases", "### Section")
        assert "### All judged cases: 10 flagged findings in 4 cases" in overall
        assert f"- exact: {pp.with_interval(2, 10)}" in overall
        assert f"- item right, modifier wrong: {pp.with_interval(1, 10)}" in overall
        assert f"- category right, item wrong: {pp.with_interval(4, 10)}" in overall
        assert f"- category missed: {pp.with_interval(3, 10)}" in overall
        assert "- exact: 2 of 10 (20.0%) [5.7%, 51.0%]" in overall
        assert [line.split(":")[0] for line in _lines(overall) if line.startswith("- ")] == [
            "- exact",
            "- item right, modifier wrong",
            "- category right, item wrong",
            "- category missed",
        ]

    def test_each_section_that_occurs_is_a_row_named_by_the_tables(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), f"## Run a ({_RUN_A})", "## Run b")
        titles = [line for line in _lines(a) if line.startswith("### Section")]
        # 01 Aircraft: 6; 02 Personnel: 1 (P44); 03 Environmental: 2 (WA twice); 05: 1 (N5). The
        # organisational section holds no NTSB flagged finding, so it has no row.
        assert titles == [
            "### Section 01 Aircraft: 6 flagged findings",
            "### Section 02 Personnel issues: 1 flagged findings",
            "### Section 03 Environmental issues: 2 flagged findings",
            "### Section 05 Not determined: 1 flagged findings",
        ]
        aircraft = _section(a, "### Section 01", "### Section 02")
        # A1 exact (000); D1 item (000); A1 modifier (004); C1 item (004); A0 item (005); D1 missed
        assert f"- exact: {pp.with_interval(1, 6)}" in aircraft
        assert f"- item right, modifier wrong: {pp.with_interval(1, 6)}" in aircraft
        assert f"- category right, item wrong: {pp.with_interval(3, 6)}" in aircraft
        assert f"- category missed: {pp.with_interval(1, 6)}" in aircraft
        personnel = _section(a, "### Section 02", "### Section 03")
        assert f"- category missed: {pp.with_interval(1, 1)}" in personnel
        assert f"- exact: {pp.with_interval(0, 1)}" in personnel
        environmental = _section(a, "### Section 03", "### Section 05")
        assert f"- exact: {pp.with_interval(1, 2)}" in environmental
        assert f"- category right, item wrong: {pp.with_interval(1, 2)}" in environmental
        undetermined = _section(a, "### Section 05", "### Fatal cases")
        assert f"- category missed: {pp.with_interval(1, 1)}" in undetermined

    def test_fatal_and_non_fatal_cases_apart(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), f"## Run a ({_RUN_A})", "## Run b")
        fatal = _section(a, "### Fatal cases", "### Non-fatal cases")
        # 000 and 006: A1 exact, D1 item, WA item, P44 missed, WA exact.
        assert "### Fatal cases: 5 flagged findings in 2 cases" in fatal
        assert f"- exact: {pp.with_interval(2, 5)}" in fatal
        assert f"- item right, modifier wrong: {pp.with_interval(0, 5)}" in fatal
        assert f"- category right, item wrong: {pp.with_interval(2, 5)}" in fatal
        assert f"- category missed: {pp.with_interval(1, 5)}" in fatal
        non = _section(a, "### Non-fatal cases", "### category right")
        # 004 and 005: A1 modifier, C1 item, A0 item, D1 missed, N5 missed.
        assert "### Non-fatal cases: 5 flagged findings in 2 cases" in non
        assert f"- exact: {pp.with_interval(0, 5)}" in non
        assert f"- item right, modifier wrong: {pp.with_interval(1, 5)}" in non
        assert f"- category right, item wrong: {pp.with_interval(2, 5)}" in non
        assert f"- category missed: {pp.with_interval(2, 5)}" in non

    def test_the_item_misses_against_the_pools_habit(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), f"## Run a ({_RUN_A})", "## Run b")
        block = _section(a, "### category right, item wrong", "### item right, modifier wrong")
        assert '- findings classed "category right, item wrong": 4' in block
        assert (
            f"- the NTSB's item is the pool's commonest item for its category: "
            f"{pp.with_interval(3, 4)}"
        ) in block
        assert (
            "- the loop's item is it (any of the loop's findings under the category carrying "
            f"it): {pp.with_interval(1, 4)}"
        ) in block
        assert (
            f"- the pool holds no finding under the category, so neither can be: {pp.share(0, 4)}"
        ) in block
        assert (
            "The 10 commonest (NTSB item, loop item) pairs (6 different pairs, from 4 findings; "
            "a finding counts once under each different loop item in its category):"
        ) in block
        pairs = [line for line in _lines(block) if " -> " in line]
        assert pairs == [
            f"- 1  {_item('01010510')} -> {_item('01010530')}",
            f"- 1  {_item('01010520')} -> {_item('01010510')}",
            f"- 1  {_item('01010520')} -> {_item('01010530')}",
            f"- 1  {_item('01010520')} -> {_item('01010550')}",
            f"- 1  {_item('01022710')} -> {_item('01022720')}",
            f"- 1  {_item('03034040')} -> {_item('03034045')}",
        ]
        assert "The 10 categories with the most item misses (3 categories lose a finding" in block
        keys = [
            line for line in _lines(block) if "the NTSB's item is the pool's commonest in" in line
        ]
        assert keys == [
            f"- 2  {_category('010105')}: the NTSB's item is the pool's commonest in 1 of them; "
            f"the pool's commonest item is {_item('01010510')}, 4 of 6 (66.7%) of its findings",
            f"- 1  {_category('010227')}: the NTSB's item is the pool's commonest in 1 of them; "
            f"the pool's commonest item is {_item('01022710')}, 2 of 2 (100.0%) of its findings",
            f"- 1  {_category('030340')}: the NTSB's item is the pool's commonest in 1 of them; "
            f"the pool's commonest item is {_item('03034040')}, 1 of 2 (50.0%) of its findings",
        ]

    def test_the_modifier_misses_against_the_pools_habit(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), f"## Run a ({_RUN_A})", "## Run b")
        block = _section(a, "### item right, modifier wrong", "### Beside")
        assert '- findings classed "item right, modifier wrong": 1' in block
        assert (
            "- the NTSB's modifier is the pool's commonest modifier for its item: "
            f"{pp.with_interval(1, 1)}"
        ) in block
        assert (
            "- the loop's modifier is it (any of the loop's findings under the item carrying "
            f"it): {pp.with_interval(0, 1)}"
        ) in block
        assert (
            "The 10 commonest (NTSB modifier, loop modifier) pairs (1 different pairs, from 1 "
            "findings; a finding counts once under each different loop modifier in its item):"
        ) in block
        assert f"- 1  {_modifier('01')} -> {_modifier('02')}" in _lines(block)
        assert "The 10 items with the most modifier misses (1 items lose a finding" in block
        assert (
            f"- 1  {_item('01010510')}: the NTSB's modifier is the pool's commonest in 1 of "
            f"them; the pool's commonest modifier is {_modifier('01')}, 3 of 4 (75.0%) of its "
            "findings"
        ) in _lines(block)

    def test_the_loops_findings_that_reach_no_ntsb_flagged_finding_by_section(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = _section(_report(_argv(), capsys), f"## Run a ({_RUN_A})", "## Run b")
        beside = _section(a, "### Beside")
        assert (
            f"reaching no NTSB flagged finding of their case even at 6 digits: {pp.share(1, 9)}"
        ) in beside
        assert [line for line in _lines(beside) if line.startswith("- 0")] == [
            "- 01 Aircraft: 0 of 6 (0.0%)",
            "- 03 Environmental issues: 0 of 2 (0.0%)",
            "- 04 Organizational issues: 1 of 1 (100.0%)",
        ]

    def test_run_b_is_read_on_its_own_cases(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        b = _section(_report(_argv(), capsys), f"## Run b ({_RUN_B})")
        # Judged 000, 004, 005: exact A1 and D1; modifier A1; item C1; missed D1, WA, P44, A0, N5.
        assert "### All judged cases: 9 flagged findings in 3 cases" in b
        assert f"- exact: {pp.with_interval(2, 9)}" in b
        assert f"- item right, modifier wrong: {pp.with_interval(1, 9)}" in b
        assert f"- category right, item wrong: {pp.with_interval(1, 9)}" in b
        assert f"- category missed: {pp.with_interval(5, 9)}" in b
        # The one item miss, C1: the NTSB's item is not the usual one, the loop's is.
        block = _section(b, "### category right, item wrong", "### item right, modifier wrong")
        assert f"commonest item for its category: {pp.with_interval(0, 1)}" in block
        assert f"carrying it): {pp.with_interval(1, 1)}" in block
        beside = _section(b, "### Beside")
        assert f"even at 6 digits: {pp.share(0, 5)}" in beside
        assert "- 01 Aircraft: 0 of 5 (0.0%)" in beside
        # Section 03 holds ZQX000's WA only: ZQX006, with the other, failed in this run.
        assert "### Section 03 Environmental issues: 1 flagged findings" in b

    def test_the_counts_of_every_run_agree_with_the_findings_they_class(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        for run_total in (10, 9):
            block = _section(text, f"### All judged cases: {run_total} flagged")
            shares = re.findall(
                r"^- [a-z ,]+: (\d+) of (\d+) \(", block.split("### Section")[0], re.M
            )
            assert sum(int(n) for n, _total in shares) == run_total
            assert {total for _n, total in shares} == {str(run_total)}

    def test_no_case_number_no_case_id_no_ten_digit_code_and_no_record_text_is_printed(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(), capsys)
        assert not _CASE_NUMBER.search(text)
        assert "ZQ" not in text
        assert not re.search(r"\b\d{10}\b", text)
        for code in _ALL_CODES:
            assert code not in text
        for word in _WORDS:
            assert word not in text.lower()

    def test_out_writes_the_same_text_and_the_text_does_not_depend_on_it(
        self, runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain = _report(_argv(), capsys)
        out = tmp_path / "results" / "s3-finding-misses-dev.txt"
        written = _report(_argv("--out", str(out)), capsys)
        assert written == plain
        assert out.read_text() == plain

    def test_the_report_is_the_same_on_a_second_run(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _report(_argv(), capsys) == _report(_argv(), capsys)

    def test_the_report_does_not_depend_on_the_order_the_run_holds_its_cases_in(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain = _report(_argv(), capsys)
        _write_run(runs, _RUN_A, list(reversed(_run_a())))
        assert _report(_argv(), capsys) == plain

    def test_the_other_case_count_line_is_the_precedent_probes(self) -> None:
        split = fp.sort_cases(_run_a())
        assert fp.count_line(split) == (
            "Cases in the run: 8, each counted once, in this order: failed 2; abstained 1; "
            "no flagged finding 1; judged 4 (2 fatal, 2 non-fatal)."
        )


# --------------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------------


class TestRefusals:
    def test_an_arm_b_run_is_refused(self, runs: Path) -> None:
        _write_run(runs, _RUN_B, _run_b(), arm="B")
        with pytest.raises(SystemExit, match="arm B; the precedent probe reads arm C runs only"):
            fm.main(_argv())

    def test_a_run_named_twice_is_refused(self, runs: Path) -> None:
        with pytest.raises(SystemExit, match="named twice"):
            fm.main(["--runs", _RUN_A, _RUN_A])

    def test_one_run_is_a_usage_error(self, runs: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            fm.main(["--runs", _RUN_A])
        assert raised.value.code == 2

    def test_a_held_out_run_id_is_refused(self, runs: Path) -> None:
        with pytest.raises(SystemExit, match="held-out"):
            fm.main(["--runs", "20260101T000000-abc1234-heldout-400-C", _RUN_B])

    def test_a_sealed_sample_is_refused(self, runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
        _write_run(runs, _RUN_B, _run_b(), sample="dev-seal-s3-400")
        with pytest.raises(SystemExit, match="dev-400 only"):
            fm.main(_argv())

    def test_an_unfinished_run_is_refused(self, runs: Path) -> None:
        _write_run(runs, _RUN_A, _run_a(), finished=None)
        with pytest.raises(SystemExit, match="has not finished"):
            fm.main(_argv())

    def test_a_judged_case_with_no_stored_recall_is_refused(self, runs: Path) -> None:
        cases = _run_a()
        cases[4] = _loop_findings(_one("ZQX004", (_A1, _C1), loop=_loop(r10=None)), (_A2, _C3, _C5))
        _write_run(runs, _RUN_A, cases)
        with pytest.raises(SystemExit, match="hold no finding recall"):
            fm.main(_argv())

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
            fm.main(_argv())
        assert capsys.readouterr().out == ""
        assert texts == []  # no pool text was read
        # Only the pool's own pass read findings, one case each, not the pass after check_pool.
        in_pool = sum(1 for row in _all_rows() if row[2] == "dev" and row[3] in {"C", "F", "L"})
        assert len(findings) == in_pool
