"""Tests for ``agent/tools.py``: the four coding tools, offline (S3.1 Task 6).

The pool, cases and expected text are ported from ``tests/test_s3_probe_tools.py``; the three
tools lose the probe's ``kind`` argument on ``occurrence_usage`` and ``past_findings``, and
``suggest_codes`` is new.
"""

from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest
from pydantic import BaseModel

from ntsb_probable_cause.agent.schemas import (
    PHASE_GROUPS,
    DescribeCodes,
    OccurrenceUsage,
    PastFindings,
    SuggestCodes,
)
from ntsb_probable_cause.agent.tools import (
    ToolResult,
    describe_codes,
    occurrence_usage,
    past_findings,
    run_coding_tool,
    suggest_codes,
)
from ntsb_probable_cause.model.client import ToolText
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import (
    CodingStats,
    PoolCase,
    StatsName,
    build,
    load_stats,
)

TABLES = load_tables()

LOC, STALL, CFIT = "452240", "452241", "452120"
AIRCRAFT_CONTROL, AIRSPEED = "0206304044", "0106201020"

CASES = [
    PoolCase(year=2010, group="Maneuvering", sequence=(LOC, STALL), findings=(AIRCRAFT_CONTROL,)),
    PoolCase(
        year=2012,
        group="Maneuvering",
        sequence=(LOC, STALL, CFIT),
        findings=(AIRCRAFT_CONTROL, AIRSPEED),
    ),
    PoolCase(year=2016, group="Maneuvering", sequence=(STALL, LOC), findings=(AIRSPEED,)),
    PoolCase(year=2017, group="Landing", sequence=("552300",)),
    PoolCase(year=2018, group=None, sequence=(CFIT,)),
]


def _stats() -> CodingStats:
    return build(CASES, built_from="test")


class TestToolResult:
    def test_as_tool_text_wraps_the_text(self) -> None:
        result = ToolResult("a label: 3", 0)
        tool_text = result.as_tool_text()
        assert isinstance(tool_text, ToolText)
        assert tool_text == ToolText.of("a label: 3")
        assert tool_text.text == "a label: 3"

    def test_is_frozen(self) -> None:
        result = ToolResult("text", 0)
        with pytest.raises(FrozenInstanceError):
            result.text = "other"  # type: ignore[misc]


class TestDescribeCodes:
    def test_occurrence_code(self) -> None:
        result = describe_codes(TABLES, "occurrence", [LOC])
        assert result == ToolResult(f"{LOC}: {TABLES.phases['452']} / {TABLES.events['240']}", 0)

    def test_finding_category(self) -> None:
        category = AIRCRAFT_CONTROL[:6]
        result = describe_codes(TABLES, "finding_category", [category])
        items = sorted(TABLES.items_under(category).items())
        expected_lines = [f"{category}: {TABLES.categories[category]}"]
        expected_lines += [f"  {code}: {label}" for code, label in items[:20]]
        if len(items) > 20:
            expected_lines.append(f"  ... and {len(items) - 20} more")
        assert result.text == "\n".join(expected_lines)
        assert result.argument_errors == 0

    def test_finding_category_with_more_than_twenty_items_says_how_many_more(self) -> None:
        category = next(c for c in TABLES.categories if len(TABLES.items_under(c)) > 20)
        result = describe_codes(TABLES, "finding_category", [category])
        more = len(TABLES.items_under(category)) - 20
        assert result.text.splitlines()[-1] == f"  ... and {more} more"
        assert result.text.count("\n") == 21  # the label, 20 items, the "and more" line

    def test_item(self) -> None:
        item = AIRCRAFT_CONTROL[:8]
        result = describe_codes(TABLES, "item", [item])
        assert result == ToolResult(f"{item}: {TABLES.items[item]}", 0)

    def test_multiple_codes_in_one_call(self) -> None:
        result = describe_codes(TABLES, "occurrence", [LOC, STALL])
        assert result.text.count("\n") >= 1
        assert result.argument_errors == 0
        assert LOC in result.text
        assert STALL in result.text

    def test_unknown_code(self) -> None:
        result = describe_codes(TABLES, "occurrence", ["999999"])
        assert result == ToolResult("unknown occurrence code: 999999", 1)

    def test_wrong_digit_count(self) -> None:
        result = describe_codes(TABLES, "occurrence", ["123"])
        assert result == ToolResult("unknown occurrence code: 123", 1)

    def test_unknown_finding_category(self) -> None:
        result = describe_codes(TABLES, "finding_category", ["999999"])
        assert result == ToolResult("unknown finding_category code: 999999", 1)

    def test_unknown_item(self) -> None:
        result = describe_codes(TABLES, "item", ["99999999"])
        assert result == ToolResult("unknown item code: 99999999", 1)

    def test_non_digit_code_is_unknown(self) -> None:
        result = describe_codes(TABLES, "item", ["abcdefgh"])
        assert result == ToolResult("unknown item code: abcdefgh", 1)

    def test_a_kind_outside_the_three_is_one_argument_error(self) -> None:
        result = describe_codes(TABLES, cast(Any, "bogus"), [LOC])
        assert result.argument_errors == 1
        assert "kind must be one of" in result.text
        assert "bogus" in result.text

    def test_zero_codes_is_one_argument_error(self) -> None:
        result = describe_codes(TABLES, "occurrence", [])
        assert result == ToolResult("describe_codes: no codes given.", 1)

    def test_six_codes_are_all_kept(self) -> None:
        six = sorted(
            f"{phase}{event}"
            for phase in list(TABLES.phases)[:1]
            for event in list(TABLES.events)[:6]
        )
        result = describe_codes(TABLES, "occurrence", six)
        assert result.text.count("\n") == 5
        assert result.argument_errors == 0

    def test_excess_codes_dropped_and_counted(self) -> None:
        seven_occurrence_codes = sorted(
            f"{phase}{event}"
            for phase in list(TABLES.phases)[:1]
            for event in list(TABLES.events)[:7]
        )
        result = describe_codes(TABLES, "occurrence", seven_occurrence_codes)
        assert result.text.count("\n") == 5  # 6 lines kept
        assert result.argument_errors == 1

    def test_duplicate_code_is_deduplicated_and_counted(self) -> None:
        result = describe_codes(TABLES, "occurrence", [LOC, LOC])
        one_code = describe_codes(TABLES, "occurrence", [LOC])
        assert result.text == one_code.text
        assert result.argument_errors == one_code.argument_errors + 1


class TestOccurrenceUsage:
    def test_single_code(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [LOC])
        assert result.argument_errors == 0
        expected = (
            f"{LOC}: {TABLES.phases['452']} / {TABLES.events['240']}\n"
            "  present: 3; defining: 2 (67% of present)\n"
            f"  top phases for event 240: {TABLES.phases['452']} (452): 2"
        )
        assert result.text == expected

    def test_pair_section_same_phase(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [LOC, STALL])
        assert f"{LOC} & {STALL}: both in 3; {LOC} defining in 2; {STALL} defining in 1" in (
            result.text
        )
        # Same phase (452) on both codes: no event-pair line.
        assert "across phases" not in result.text

    def test_pair_section_omits_event_pair_when_only_the_event_is_shared(self) -> None:
        # Same event (240), different phase: the per-code blocks above already give event 240's
        # usage, so the "across phases" line -- which would otherwise read as if 240 and 240
        # were two different events -- must not appear (final review, F1).
        stats = _stats()
        same_event_other_phase = "500240"
        result = occurrence_usage(TABLES, stats, [LOC, same_event_other_phase])
        assert "across phases" not in result.text

    def test_pair_section_uses_event_pair_when_phases_differ(self) -> None:
        stats = build(
            [
                PoolCase(year=2010, group="Enroute", sequence=("402192", "402341")),
                PoolCase(year=2016, group="Approach", sequence=("500192", "502341")),
            ],
            built_from="test",
        )
        result = occurrence_usage(TABLES, stats, ["402192", "502341"])
        assert "events 192 & 341 across phases:" in result.text

    def test_present_but_never_defining_shows_zero_percent(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [CFIT])
        assert "present: 2; defining: 1 (50% of present)" in result.text

    def test_code_absent_from_pool_shows_no_pool_cases(self) -> None:
        stats = _stats()
        code = "552341"
        assert stats.present_n(code) == 0
        result = occurrence_usage(TABLES, stats, [code])
        assert "present: 0; defining: 0 (no pool cases present)" in result.text
        assert "top phases for event 341: none" in result.text

    def test_unknown_code(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, ["999999"])
        assert result == ToolResult("unknown occurrence code: 999999", 1)

    def test_one_unknown_among_good_codes_is_counted_and_not_paired(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [LOC, "999999", STALL])
        assert result.argument_errors == 1
        assert "unknown occurrence code: 999999" in result.text
        assert f"{LOC} & {STALL}:" in result.text
        assert "999999 &" not in result.text
        assert "& 999999" not in result.text

    def test_zero_codes(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [])
        assert result == ToolResult("occurrence_usage: no codes given.", 1)

    def test_three_codes_are_all_kept(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [LOC, STALL, CFIT])
        assert result.argument_errors == 0
        assert f"{LOC} & {CFIT}:" in result.text
        assert f"{STALL} & {CFIT}:" in result.text

    def test_excess_codes_dropped_and_counted(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [LOC, STALL, CFIT, "552300"])
        assert result.argument_errors == 1
        assert "552300" not in result.text

    def test_duplicate_code_is_deduplicated_no_self_pair_and_counted(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, [LOC, LOC])
        one_code = occurrence_usage(TABLES, stats, [LOC])
        assert result.text == one_code.text
        assert result.argument_errors == one_code.argument_errors + 1
        # One block only, no self-pair line.
        assert result.text.count(LOC) == 1
        assert "&" not in result.text


class TestPastFindings:
    def test_top_findings_with_share(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, LOC)
        cases, findings = stats.findings_given_event("240")
        assert cases == 2
        assert findings == {AIRCRAFT_CONTROL: 2, AIRSPEED: 1}
        expected_lines = [
            "Fewer than 20 past cases with this defining event; the counts are unreliable.",
            (
                f"{AIRCRAFT_CONTROL}: {TABLES.items[AIRCRAFT_CONTROL[:8]]} — "
                f"{TABLES.modifiers[AIRCRAFT_CONTROL[8:]]}: 2 of 2 cases (100%)"
            ),
            (
                f"{AIRSPEED}: {TABLES.items[AIRSPEED[:8]]} — "
                f"{TABLES.modifiers[AIRSPEED[8:]]}: 1 of 2 cases (50%)"
            ),
        ]
        assert result.text == "\n".join(expected_lines)
        assert result.argument_errors == 0

    def test_fewer_than_20_cases_warning_absent_when_enough_cases(self) -> None:
        many_cases = [
            PoolCase(year=2010 + (i % 10), group="Maneuvering", sequence=(LOC,)) for i in range(20)
        ]
        stats = build(many_cases, built_from="test")
        result = past_findings(TABLES, stats, LOC)
        assert "Fewer than 20" not in result.text

    def test_only_ten_findings_are_listed(self) -> None:
        eleven = tuple(f"{i:010d}" for i in range(11))
        stats = build(
            [PoolCase(year=2010, group="Maneuvering", sequence=(LOC,), findings=eleven)],
            built_from="test",
        )
        result = past_findings(TABLES, stats, LOC)
        # The warning line, then ten finding lines.
        assert result.text.count("\n") == 10

    def test_no_findings_recorded(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "552300")
        assert "no findings recorded for this event." in result.text

    def test_unknown_code(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "999999")
        assert result == ToolResult("unknown occurrence code: 999999", 1)

    def test_wrong_digit_count(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "1")
        assert result == ToolResult("unknown occurrence code: 1", 1)

    def test_empty_code_is_unknown(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "")
        assert result.argument_errors == 1
        assert result.text.startswith("unknown occurrence code")


class TestSuggestCodes:
    def test_landing_lists_the_groups_commonest_defining_events(self) -> None:
        stats = _stats()
        top = stats.group_top("Landing", 5)
        assert top == ["552300"]
        result = suggest_codes(TABLES, stats, "Landing")
        expected = [
            "The five commonest defining events in past Landing accidents. "
            "These are counts, not evidence about this accident.",
            f"552300: {TABLES.phases['552']} / {TABLES.events['300']}: "
            "defining in 1 of 1 Landing cases (100%)",
        ]
        assert result == ToolResult("\n".join(expected), 0)

    def test_lines_follow_group_top_with_counts_and_shares(self) -> None:
        stats = _stats()
        result = suggest_codes(TABLES, stats, "Maneuvering")
        lines = result.text.splitlines()
        assert lines[0] == (
            "The five commonest defining events in past Maneuvering accidents. "
            "These are counts, not evidence about this accident."
        )
        top = stats.group_top("Maneuvering", 5)
        assert top == [LOC, STALL]
        assert len(lines) == 1 + len(top)
        group_n = stats.group_n("Maneuvering")
        assert group_n == 3
        for line, code in zip(lines[1:], top, strict=True):
            n = stats.group_defining_n("Maneuvering", code)
            phase, event = TABLES.phases[code[:3]], TABLES.events[code[3:]]
            assert line == (
                f"{code}: {phase} / {event}: defining in {n} of {group_n} Maneuvering cases "
                f"({n / group_n:.0%})"
            )
        assert lines[1].endswith("defining in 2 of 3 Maneuvering cases (67%)")
        assert lines[2].endswith("defining in 1 of 3 Maneuvering cases (33%)")

    def test_at_most_five_lines_of_events(self) -> None:
        sequences = [f"452{event}" for event in sorted(TABLES.events)[:7]]
        stats = build(
            [PoolCase(year=2010, group="Landing", sequence=(code,)) for code in sequences],
            built_from="test",
        )
        assert len(set(sequences)) == 7
        result = suggest_codes(TABLES, stats, "Landing")
        assert len(result.text.splitlines()) == 1 + 5

    def test_a_group_with_no_cases_returns_the_no_cases_line(self) -> None:
        stats = _stats()
        assert stats.group_n("Standing") == 0
        result = suggest_codes(TABLES, stats, "Standing")
        assert result == ToolResult("No past Standing accidents in the pool.", 0)

    def test_an_unknown_group_returns_the_no_cases_line_and_counts_an_error(self) -> None:
        stats = _stats()
        result = suggest_codes(TABLES, stats, "Hovering")
        assert result == ToolResult("No past Hovering accidents in the pool.", 1)

    def test_an_empty_group_name_returns_the_no_cases_line_and_counts_an_error(self) -> None:
        stats = _stats()
        result = suggest_codes(TABLES, stats, "")
        assert result.argument_errors == 1
        assert result.text == "No past  accidents in the pool."

    @pytest.mark.parametrize("name", ["s27", "s3"])
    def test_every_phase_group_renders_from_the_committed_counts(self, name: StatsName) -> None:
        """Every code the pool holds has a label, so no group's answer can raise."""
        stats = load_stats(name)
        for group in PHASE_GROUPS:
            result = suggest_codes(TABLES, stats, group)
            assert result.argument_errors == 0
            lines = result.text.splitlines()
            assert lines[0].startswith(f"The five commonest defining events in past {group} ")
            assert 2 <= len(lines) <= 6
            for line in lines[1:]:
                assert f" of {stats.group_n(group)} {group} cases (" in line


class TestRunCodingTool:
    def test_dispatches_to_each_tool(self) -> None:
        stats = _stats()
        why: dict[str, str] = {"reason": "r", "expected_effect": "e"}
        assert run_coding_tool(
            "describe_codes",
            DescribeCodes(kind="occurrence", codes=(LOC,), **why),
            tables=TABLES,
            stats=stats,
        ) == describe_codes(TABLES, "occurrence", [LOC])
        assert run_coding_tool(
            "occurrence_usage",
            OccurrenceUsage(codes=(LOC, STALL), **why),
            tables=TABLES,
            stats=stats,
        ) == occurrence_usage(TABLES, stats, [LOC, STALL])
        assert run_coding_tool(
            "past_findings", PastFindings(occurrence=LOC, **why), tables=TABLES, stats=stats
        ) == past_findings(TABLES, stats, LOC)
        assert run_coding_tool(
            "suggest_codes",
            SuggestCodes(phase_group="Landing", **why),
            tables=TABLES,
            stats=stats,
        ) == suggest_codes(TABLES, stats, "Landing")

    def test_arguments_of_the_wrong_model_are_refused(self) -> None:
        stats = _stats()
        wrong = PastFindings(reason="r", expected_effect="e", occurrence=LOC)
        with pytest.raises(TypeError, match="describe_codes"):
            run_coding_tool("describe_codes", wrong, tables=TABLES, stats=stats)

    def test_an_unknown_tool_name_is_refused(self) -> None:
        stats = _stats()
        wrong = PastFindings(reason="r", expected_effect="e", occurrence=LOC)
        with pytest.raises(TypeError, match="bogus_tool"):
            run_coding_tool(cast(Any, "bogus_tool"), wrong, tables=TABLES, stats=stats)

    def test_arguments_that_are_not_a_tool_model_are_refused(self) -> None:
        stats = _stats()

        class Other(BaseModel):
            x: int = 1

        with pytest.raises(TypeError, match="suggest_codes"):
            run_coding_tool("suggest_codes", Other(), tables=TABLES, stats=stats)
