"""scripts/s3_probe/tools.py: the coding-check tools the agent loop calls in Task 4.

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

Three tools, each a pure function of the code tables (:mod:`ntsb_probable_cause.scoring.codes`)
and the statistics pool (:mod:`ntsb_probable_cause.scoring.coding_stats`): describe a code,
look up how an occurrence code is used across the pool, and look up the findings flagged after
a defining event. Every line returned is a code label or a pool count -- no case ever named or
read here (``constraints.md``, "The coding tools").
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats

TOOL_NAMES = ("describe_codes", "occurrence_usage", "past_findings")

_DESCRIBE_KINDS = ("occurrence", "finding_category", "item")
_USAGE_KINDS = (None, "occurrence")
_MAX_CODES: dict[str, int] = {"describe_codes": 6, "occurrence_usage": 3, "past_findings": 1}

_OCCURRENCE_CODE_LEN = 6
_FINDING_CATEGORY_LEN = 6
_ITEM_CODE_LEN = 8
_MAX_ITEMS_SHOWN = 20
_TOP_PHASES = 5
_TOP_FINDINGS = 10
_FEW_CASES = 20

TOOL_DESCRIPTIONS = """\
describe_codes(kind, codes): kind is "occurrence", "finding_category" or "item"; 1-6 codes.
  Returns each code's label from the code tables -- an occurrence code's phase and event
  labels, a finding category's label and up to 20 items under it, or one item's label.
occurrence_usage(codes): 1-3 six-digit occurrence codes; kind "occurrence" or omitted.
  For each code: how many pool cases contain it, how many it defines, the share of those
  it defines, and the phases under which its event is most often the defining one. For
  every pair among the codes given: how often both appear together and how often each is
  the defining code, plus the same comparison by event when the two codes' phases differ.
past_findings(code): one six-digit occurrence code; kind "occurrence" or omitted.
  The ten flagged findings most often recorded when that code's event is the defining one,
  each with its share of those cases. Warns when fewer than 20 past cases share the event.
The counts describe what is usual across past cases; they are not evidence about this
accident.
"""


@dataclass(frozen=True)
class ToolResult:
    """A tool call's outcome: text for the model, and how many argument errors it made."""

    text: str
    argument_errors: int


def _limit_codes(tool: str, codes: Sequence[str]) -> tuple[tuple[str, ...], int]:
    """Deduplicate (first-seen order), then keep at most the tool's code limit.

    Zero codes is one error. Each duplicate dropped by deduplication, and each code beyond
    the tool's limit, is counted as one argument error.
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
    high = _MAX_CODES[tool]
    kept = tuple(deduped[:high])
    excess_errors = max(0, len(deduped) - high)
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


def describe_codes(tables: CodeTables, kind: str | None, codes: Sequence[str]) -> ToolResult:
    """Look up each code's label(s) in the code tables.

    Args:
        tables: the code tables.
        kind: one of ``"occurrence"``, ``"finding_category"`` or ``"item"``.
        codes: the codes to describe (1-6; excess codes are dropped and counted as errors).

    Returns:
        One block of text per code, and the number of argument errors made.
    """
    if kind not in _DESCRIBE_KINDS:
        return ToolResult(f"describe_codes: kind must be one of {_DESCRIBE_KINDS}, got {kind!r}", 1)
    kept, errors = _limit_codes("describe_codes", codes)
    if not kept:
        return ToolResult("describe_codes: no codes given.", errors)
    describe_one = {
        "occurrence": _describe_occurrence,
        "finding_category": _describe_finding_category,
        "item": _describe_item,
    }[kind]
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
    codes' phases *and* events both differ (final review, F1).
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


def occurrence_usage(
    tables: CodeTables, stats: CodingStats, kind: str | None, codes: Sequence[str]
) -> ToolResult:
    """Look up how often each occurrence code, and each pair given, appears in the pool.

    Args:
        tables: the code tables.
        stats: the statistics pool.
        kind: ``"occurrence"`` or ``None``.
        codes: 1-3 six-digit occurrence codes (excess codes are dropped and counted as errors).

    Returns:
        Usage lines per code, pair lines for every pair, and the number of argument errors.
    """
    if kind not in _USAGE_KINDS:
        return ToolResult(
            f"occurrence_usage: kind must be 'occurrence' or omitted, got {kind!r}", 1
        )
    kept, errors = _limit_codes("occurrence_usage", codes)
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


def past_findings(
    tables: CodeTables, stats: CodingStats, kind: str | None, codes: Sequence[str]
) -> ToolResult:
    """Look up the flagged findings most often recorded under one occurrence code's event.

    Args:
        tables: the code tables.
        stats: the statistics pool.
        kind: ``"occurrence"`` or ``None``.
        codes: exactly 1 six-digit occurrence code (excess codes are dropped and counted as
            errors).

    Returns:
        The top 10 flagged findings, a fewer-than-20-cases warning where it applies, and the
        number of argument errors.
    """
    if kind not in _USAGE_KINDS:
        return ToolResult(f"past_findings: kind must be 'occurrence' or omitted, got {kind!r}", 1)
    kept, errors = _limit_codes("past_findings", codes)
    if not kept:
        return ToolResult("past_findings: no codes given.", errors)
    code = kept[0]
    if not _valid_occurrence(tables, code):
        return ToolResult(f"unknown occurrence code: {code}", errors + 1)
    cases, findings = stats.findings_given_event(code[3:])
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
    return ToolResult("\n".join(lines), errors)


def run_tool(
    name: str, kind: str | None, codes: Sequence[str], *, tables: CodeTables, stats: CodingStats
) -> ToolResult:
    """Dispatch to one of the three tools by name.

    Args:
        name: one of :data:`TOOL_NAMES`.
        kind: the tool's ``kind`` argument.
        codes: the tool's ``codes`` argument.
        tables: the code tables.
        stats: the statistics pool.

    Returns:
        An unknown ``name`` returns an error :class:`ToolResult` rather than raising.
    """
    if name == "describe_codes":
        return describe_codes(tables, kind, codes)
    if name == "occurrence_usage":
        return occurrence_usage(tables, stats, kind, codes)
    if name == "past_findings":
        return past_findings(tables, stats, kind, codes)
    return ToolResult(f"unknown tool: {name}", 1)
