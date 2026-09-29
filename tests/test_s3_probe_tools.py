"""Tests for ``scripts/s3_probe/tools.py``: the three coding-check tools, offline."""

from scripts.s3_probe.tools import (
    TOOL_NAMES,
    ToolResult,
    describe_codes,
    occurrence_usage,
    past_findings,
    run_tool,
)

from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, PoolCase, build

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


def test_tool_names() -> None:
    assert TOOL_NAMES == ("describe_codes", "occurrence_usage", "past_findings")


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

    def test_invalid_kind(self) -> None:
        result = describe_codes(TABLES, "bogus", [LOC])
        assert result.argument_errors == 1
        assert "kind" in result.text

    def test_missing_kind(self) -> None:
        result = describe_codes(TABLES, None, [LOC])
        assert result.argument_errors == 1

    def test_zero_codes_is_one_argument_error(self) -> None:
        result = describe_codes(TABLES, "occurrence", [])
        assert result == ToolResult("describe_codes: no codes given.", 1)

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
        result = occurrence_usage(TABLES, stats, "occurrence", [LOC])
        assert result.argument_errors == 0
        expected = (
            f"{LOC}: {TABLES.phases['452']} / {TABLES.events['240']}\n"
            "  present: 3; defining: 2 (67% of present)\n"
            f"  top phases for event 240: {TABLES.phases['452']} (452): 2"
        )
        assert result.text == expected

    def test_kind_none_is_treated_as_occurrence(self) -> None:
        stats = _stats()
        assert occurrence_usage(TABLES, stats, None, [LOC]) == occurrence_usage(
            TABLES, stats, "occurrence", [LOC]
        )

    def test_pair_section_same_phase(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, "occurrence", [LOC, STALL])
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
        result = occurrence_usage(TABLES, stats, "occurrence", [LOC, same_event_other_phase])
        assert "across phases" not in result.text

    def test_pair_section_uses_event_pair_when_phases_differ(self) -> None:
        stats = build(
            [
                PoolCase(year=2010, group="Enroute", sequence=("402192", "402341")),
                PoolCase(year=2016, group="Approach", sequence=("500192", "502341")),
            ],
            built_from="test",
        )
        result = occurrence_usage(TABLES, stats, "occurrence", ["402192", "502341"])
        assert "events 192 & 341 across phases:" in result.text

    def test_present_but_never_defining_shows_zero_percent(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, "occurrence", [CFIT])
        assert "present: 2; defining: 1 (50% of present)" in result.text

    def test_code_absent_from_pool_shows_no_pool_cases(self) -> None:
        stats = _stats()
        code = "552341"
        assert stats.present_n(code) == 0
        result = occurrence_usage(TABLES, stats, "occurrence", [code])
        assert "present: 0; defining: 0 (no pool cases present)" in result.text
        assert "top phases for event 341: none" in result.text

    def test_unknown_code(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, "occurrence", ["999999"])
        assert result == ToolResult("unknown occurrence code: 999999", 1)

    def test_invalid_kind(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, "finding_category", [LOC])
        assert result.argument_errors == 1
        assert "kind" in result.text

    def test_zero_codes(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, "occurrence", [])
        assert result == ToolResult("occurrence_usage: no codes given.", 1)

    def test_excess_codes_dropped_and_counted(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, "occurrence", [LOC, STALL, CFIT, "552300"])
        assert result.argument_errors == 1
        assert "552300" not in result.text

    def test_duplicate_code_is_deduplicated_no_self_pair_and_counted(self) -> None:
        stats = _stats()
        result = occurrence_usage(TABLES, stats, "occurrence", [LOC, LOC])
        one_code = occurrence_usage(TABLES, stats, "occurrence", [LOC])
        assert result.text == one_code.text
        assert result.argument_errors == one_code.argument_errors + 1
        # One block only, no self-pair line.
        assert result.text.count(LOC) == 1
        assert "&" not in result.text


class TestPastFindings:
    def test_top_findings_with_share(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "occurrence", [LOC])
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
        result = past_findings(TABLES, stats, "occurrence", [LOC])
        assert "Fewer than 20" not in result.text

    def test_no_findings_recorded(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "occurrence", ["552300"])
        assert "no findings recorded for this event." in result.text

    def test_unknown_code(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "occurrence", ["999999"])
        assert result == ToolResult("unknown occurrence code: 999999", 1)

    def test_wrong_digit_count(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "occurrence", ["1"])
        assert result == ToolResult("unknown occurrence code: 1", 1)

    def test_zero_codes(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "occurrence", [])
        assert result == ToolResult("past_findings: no codes given.", 1)

    def test_excess_codes_dropped_and_counted(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "occurrence", [LOC, STALL])
        one_code = past_findings(TABLES, stats, "occurrence", [LOC])
        # Only LOC (the first, kept) code's findings appear; STALL just adds one error.
        assert result.text == one_code.text
        assert result.argument_errors == one_code.argument_errors + 1

    def test_invalid_kind(self) -> None:
        stats = _stats()
        result = past_findings(TABLES, stats, "item", [LOC])
        assert result.argument_errors == 1
        assert "kind" in result.text


class TestRunTool:
    def test_dispatches_to_each_tool(self) -> None:
        stats = _stats()
        assert run_tool(
            "describe_codes", "occurrence", [LOC], tables=TABLES, stats=stats
        ) == describe_codes(TABLES, "occurrence", [LOC])
        assert run_tool(
            "occurrence_usage", "occurrence", [LOC], tables=TABLES, stats=stats
        ) == occurrence_usage(TABLES, stats, "occurrence", [LOC])
        assert run_tool(
            "past_findings", "occurrence", [LOC], tables=TABLES, stats=stats
        ) == past_findings(TABLES, stats, "occurrence", [LOC])

    def test_unknown_tool_name_returns_error_not_exception(self) -> None:
        stats = _stats()
        result = run_tool("bogus_tool", "occurrence", [LOC], tables=TABLES, stats=stats)
        assert result.argument_errors == 1
        assert "bogus_tool" in result.text
