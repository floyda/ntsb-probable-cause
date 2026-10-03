"""The agent's four coding tools: pure functions over the code tables and the statistics pool.

Ported from the S3 learning probe's tools (``scripts/s3_probe/tools.py``, text formats
unchanged), with ``suggest_codes`` added (decision 0125). Each tool describes a code, looks up how
the NTSB has coded past accidents, or lists the events most often defining one phase-of-flight
group. Every line returned is a code label, a count, a share or a fixed sentence: no case is
ever read or named here, and a tool's text goes to the model as a
:class:`~ntsb_probable_cause.model.tool_text.ToolText`, the type that carries no evidence. It is
imported from ``model.tool_text``, not ``model.client``, so this module reaches no case record by
any import chain (S3.1 Task 10's contract).

The counts describe what is usual across past cases; they are not evidence about the accident
under analysis, and the text of ``suggest_codes`` says so.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import get_args

from pydantic import BaseModel

from ntsb_probable_cause.agent.schemas import (
    PHASE_GROUPS,
    CodingToolName,
    DescribeCodes,
    DescribeKind,
    OccurrenceUsage,
    PastFindings,
    SuggestCodes,
)
from ntsb_probable_cause.model.tool_text import ToolText
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats

_MAX_DESCRIBE_CODES = 6
_MAX_USAGE_CODES = 3

_OCCURRENCE_CODE_LEN = 6
_FINDING_CATEGORY_LEN = 6
_ITEM_CODE_LEN = 8
_MAX_ITEMS_SHOWN = 20
_TOP_PHASES = 5
_TOP_FINDINGS = 10
_FEW_CASES = 20
_TOP_EVENTS = 5


@dataclass(frozen=True)
class ToolResult:
    """A tool call's outcome: text for the model, and how many argument errors it made."""

    text: str
    argument_errors: int

    def as_tool_text(self) -> ToolText:
        """The text as a :class:`~ntsb_probable_cause.model.client.ToolText`."""
        return ToolText.of(self.text)


def _limit_codes(codes: Sequence[str], limit: int) -> tuple[tuple[str, ...], int]:
    """Deduplicate (first-seen order), then keep at most ``limit`` codes.

    Zero codes is one error. Each duplicate dropped by deduplication, and each code beyond
    the limit, is counted as one argument error.
    """
    if not codes:
        return (), 1
    deduped: list[str] = []
    seen: set[str] = set()
    duplicate_errors = 0
    for code in codes:
        if code in seen:
            duplicate_errors += 1
            continue
        seen.add(code)
        deduped.append(code)
    kept = tuple(deduped[:limit])
    excess_errors = max(0, len(deduped) - limit)
    return kept, duplicate_errors + excess_errors


def _valid_occurrence(tables: CodeTables, code: str) -> bool:
    return (
        len(code) == _OCCURRENCE_CODE_LEN
        and code.isdigit()
        and code[:3] in tables.phases
        and code[3:] in tables.events
    )


def _phase_counts_for_event(stats: CodingStats, event: str) -> list[tuple[str, int]]:
    """Cases whose defining code has event suffix ``event``, by phase prefix, top 5 first."""
    totals: Counter[str] = Counter()
    for half in stats.group_defining.values():
        for codes in half.values():
            for code, n in codes.items():
                if code[3:] == event:
                    totals[code[:3]] += n
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_PHASES]


def _occurrence_label(tables: CodeTables, code: str) -> str:
    """The one-line ``"{code}: {phase label} / {event label}"`` an occurrence code renders as."""
    return f"{code}: {tables.phases[code[:3]]} / {tables.events[code[3:]]}"


def _describe_occurrence(tables: CodeTables, code: str) -> tuple[int, str]:
    if not _valid_occurrence(tables, code):
        return 1, f"unknown occurrence code: {code}"
    return 0, _occurrence_label(tables, code)


def _describe_finding_category(tables: CodeTables, code: str) -> tuple[int, str]:
    if len(code) != _FINDING_CATEGORY_LEN or not code.isdigit() or code not in tables.categories:
        return 1, f"unknown finding_category code: {code}"
    items = sorted(tables.items_under(code).items())
    lines = [f"{code}: {tables.categories[code]}"]
    lines += [f"  {item_code}: {label}" for item_code, label in items[:_MAX_ITEMS_SHOWN]]
    if len(items) > _MAX_ITEMS_SHOWN:
        lines.append(f"  ... and {len(items) - _MAX_ITEMS_SHOWN} more")
    return 0, "\n".join(lines)


def _describe_item(tables: CodeTables, code: str) -> tuple[int, str]:
    if len(code) != _ITEM_CODE_LEN or not code.isdigit() or code not in tables.items:
        return 1, f"unknown item code: {code}"
    return 0, f"{code}: {tables.items[code]}"


_DESCRIBERS: dict[str, Callable[[CodeTables, str], tuple[int, str]]] = {
    "occurrence": _describe_occurrence,
    "finding_category": _describe_finding_category,
    "item": _describe_item,
}


def describe_codes(tables: CodeTables, kind: DescribeKind, codes: Sequence[str]) -> ToolResult:
    """Look up each code's label(s) in the code tables.

    Args:
        tables: the code tables.
        kind: one of ``"occurrence"``, ``"finding_category"`` or ``"item"``.
        codes: the codes to describe (1-6; excess codes are dropped and counted as errors).

    Returns:
        One block of text per code, and the number of argument errors made. An occurrence code
        shows its phase and event labels, a finding category its label and up to 20 items under
        it, and an item its label.
    """
    describe_one = _DESCRIBERS.get(kind)
    if describe_one is None:
        return ToolResult(
            f"describe_codes: kind must be one of {get_args(DescribeKind)}, got {kind!r}", 1
        )
    kept, errors = _limit_codes(codes, _MAX_DESCRIBE_CODES)
    if not kept:
        return ToolResult("describe_codes: no codes given.", errors)
    lines: list[str] = []
    for code in kept:
        code_errors, text = describe_one(tables, code)
        errors += code_errors
        lines.append(text)
    return ToolResult("\n".join(lines), errors)


def _occurrence_line(tables: CodeTables, stats: CodingStats, code: str) -> str:
    event = code[3:]
    present = stats.present_n(code)
    defining = stats.defining_n(code)
    share = f"{defining / present:.0%} of present" if present else "no pool cases present"
    phase_counts = _phase_counts_for_event(stats, event)
    phases_text = (
        "; ".join(f"{tables.phases.get(phase, phase)} ({phase}): {n}" for phase, n in phase_counts)
        or "none"
    )
    return (
        f"{_occurrence_label(tables, code)}\n"
        f"  present: {present}; defining: {defining} ({share})\n"
        f"  top phases for event {event}: {phases_text}"
    )


def _pair_lines(stats: CodingStats, a: str, b: str) -> str:
    """One code pair's usage line, plus an event-pair line only when phase and event both differ.

    Two codes sharing an event under different phases (``a[3:] == b[3:]``) already have that
    event's usage in each code's own block above; a same-event pair line would repeat it under
    a label ("across phases") that implies two different events, so it is added only when the
    codes' phases *and* events both differ.
    """
    counts = stats.pair(a, b)
    lines = [
        f"{a} & {b}: both in {counts.get('both', 0)}; "
        f"{a} defining in {counts.get(a, 0)}; {b} defining in {counts.get(b, 0)}"
    ]
    if a[:3] != b[:3] and a[3:] != b[3:]:
        event_counts = stats.event_pair(a[3:], b[3:])
        lines.append(
            f"  events {a[3:]} & {b[3:]} across phases: both in {event_counts.get('both', 0)}; "
            f"{a[3:]} defining in {event_counts.get(a[3:], 0)}; "
            f"{b[3:]} defining in {event_counts.get(b[3:], 0)}"
        )
    return "\n".join(lines)


def occurrence_usage(tables: CodeTables, stats: CodingStats, codes: Sequence[str]) -> ToolResult:
    """Look up how often each occurrence code, and each pair given, appears in the pool.

    Args:
        tables: the code tables.
        stats: the statistics pool.
        codes: 1-3 six-digit occurrence codes (excess codes are dropped and counted as errors).

    Returns:
        For each code: how many pool cases contain it, how many it defines, the share of those
        it defines, and the phases under which its event is most often the defining one. For
        every pair among the valid codes: how often both appear together and how often each is
        the defining code, plus the same comparison by event when the two codes' phases and
        events both differ. The number of argument errors made.
    """
    kept, errors = _limit_codes(codes, _MAX_USAGE_CODES)
    if not kept:
        return ToolResult("occurrence_usage: no codes given.", errors)
    valid: list[str] = []
    lines: list[str] = []
    for code in kept:
        if not _valid_occurrence(tables, code):
            errors += 1
            lines.append(f"unknown occurrence code: {code}")
            continue
        valid.append(code)
        lines.append(_occurrence_line(tables, stats, code))
    for i, a in enumerate(valid):
        for b in valid[i + 1 :]:
            lines.append(_pair_lines(stats, a, b))
    return ToolResult("\n".join(lines), errors)


def past_findings(tables: CodeTables, stats: CodingStats, occurrence: str) -> ToolResult:
    """Look up the flagged findings most often recorded under one occurrence code's event.

    Args:
        tables: the code tables.
        stats: the statistics pool.
        occurrence: one six-digit occurrence code.

    Returns:
        The top 10 flagged findings, each with its share of the cases whose defining code has
        that event; a fewer-than-20-cases warning where it applies; and the number of argument
        errors made.
    """
    if not _valid_occurrence(tables, occurrence):
        return ToolResult(f"unknown occurrence code: {occurrence}", 1)
    cases, findings = stats.findings_given_event(occurrence[3:])
    lines: list[str] = []
    if cases < _FEW_CASES:
        lines.append(
            "Fewer than 20 past cases with this defining event; the counts are unreliable."
        )
    top = sorted(findings.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_FINDINGS]
    if not top:
        lines.append("no findings recorded for this event.")
    for finding10, n in top:
        item_label = tables.items.get(finding10[:_ITEM_CODE_LEN], finding10[:_ITEM_CODE_LEN])
        modifier_label = tables.modifiers.get(
            finding10[_ITEM_CODE_LEN:], finding10[_ITEM_CODE_LEN:]
        )
        share = n / cases if cases else 0.0
        lines.append(
            f"{finding10}: {item_label} — {modifier_label}: {n} of {cases} cases ({share:.0%})"
        )
    return ToolResult("\n".join(lines), 0)


def suggest_codes(tables: CodeTables, stats: CodingStats, phase_group: str) -> ToolResult:
    """List the defining events most often coded in past accidents of one phase-of-flight group.

    Args:
        tables: the code tables.
        stats: the statistics pool.
        phase_group: one of :data:`~ntsb_probable_cause.agent.schemas.PHASE_GROUPS`.

    Returns:
        The five commonest defining occurrence codes of the group, each with its label, the
        number of the group's pool cases it defines and its share of them. A group the pool
        holds no cases of gets one line saying so; a name that is not one of the groups counts
        as an argument error as well.
    """
    no_cases = f"No past {phase_group} accidents in the pool."
    if phase_group not in PHASE_GROUPS:
        return ToolResult(no_cases, 1)
    group_n = stats.group_n(phase_group)
    if not group_n:
        return ToolResult(no_cases, 0)
    lines = [
        f"The five commonest defining events in past {phase_group} accidents. "
        "These are counts, not evidence about this accident."
    ]
    for code in stats.group_top(phase_group, _TOP_EVENTS):
        n = stats.group_defining_n(phase_group, code)
        lines.append(
            f"{_occurrence_label(tables, code)}: defining in {n} of {group_n} "
            f"{phase_group} cases ({n / group_n:.0%})"
        )
    return ToolResult("\n".join(lines), 0)


def run_coding_tool(
    name: CodingToolName, arguments: BaseModel, *, tables: CodeTables, stats: CodingStats
) -> ToolResult:
    """Run the coding tool ``name`` on its parsed arguments.

    Args:
        name: one of the four coding tools.
        arguments: the argument model :func:`~ntsb_probable_cause.agent.schemas.parse_call`
            returned for ``name``.
        tables: the code tables.
        stats: the statistics pool.

    Returns:
        The tool's result.

    Raises:
        TypeError: ``name`` is not a coding tool, or ``arguments`` is not its argument model. The
            loop parses before it runs, so either is a bug in the caller, not a model error.
    """
    if name == "describe_codes" and isinstance(arguments, DescribeCodes):
        return describe_codes(tables, arguments.kind, arguments.codes)
    if name == "occurrence_usage" and isinstance(arguments, OccurrenceUsage):
        return occurrence_usage(tables, stats, arguments.codes)
    if name == "past_findings" and isinstance(arguments, PastFindings):
        return past_findings(tables, stats, arguments.occurrence)
    if name == "suggest_codes" and isinstance(arguments, SuggestCodes):
        return suggest_codes(tables, stats, arguments.phase_group)
    raise TypeError(f"cannot run {name!r} with {type(arguments).__name__} arguments")
