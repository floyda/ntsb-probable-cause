"""scripts/s3_probe/report.py: the counts-only report (Task 6).

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

Reads one run's ``trails.jsonl`` and ``probe.json`` (``scripts/s3_probe/run.py``) and builds a
counts-only report: every number is a total or a ``k of n`` count with its denominator named,
one decimal on every rate, never a case number, a docket title or the agent's own words
(``constraints.md``, "No case text in git"). A case where a stage was skipped, never reached or
failed is excluded from that stage's denominator and counted separately by its own reason, so a
reader can tell "this never happens" from "this happens and loses". The report is committed
(``docs/results/s3-probe-dev.txt``); the trails this module reads are not.
"""

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from statistics import mean, median
from typing import Any

from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.records import read_jsonl
from scripts.s3_probe.trail import CaseTrail, Stage

HEADLINE = "Learning probe, not a result: n={n}; every figure below is a signal, not a finding."

# The estimated-token size bands the brief fixes; the middle band is closed on both ends. The
# en dash in the middle band's name is spelled by codepoint (ruff RUF001 flags a literal one as
# ambiguous with a hyphen).
_BAND_LOW = "< 2,000"
_BAND_HIGH = f"2,000{chr(0x2013)}10,000"
_BAND_TOP = "> 10,000"
SIZE_BANDS: tuple[str, ...] = (_BAND_LOW, _BAND_HIGH, _BAND_TOP)

_DASH = chr(0x2014)  # em dash: the "no denominator" marker the brief asks for


def load_job(job_dir: Path) -> tuple[Mapping[str, Any], list[CaseTrail]]:
    """Read one run's ``probe.json`` and ``trails.jsonl``.

    Args:
        job_dir: ``<data_dir>/probes/s3-probe/<job_id>``.

    Returns:
        The parsed settings object and every case's trail, in the order they finished.
    """
    probe = json.loads((job_dir / "probe.json").read_text())
    trails = read_jsonl(job_dir / "trails.jsonl", CaseTrail)
    return probe, trails


def _frac(k: int, n: int) -> str:
    """``k of n`` with its rate to one decimal; ``0 of 0`` and an em dash when ``n`` is 0."""
    if n == 0:
        return f"0 of 0 ({_DASH})"
    return f"{k} of {n} ({k / n:.1%})"


def _counter_line(counts: Counter[str]) -> str:
    """A ``Counter`` rendered as ``key: n, key: n``, sorted by key, or ``none`` when empty."""
    if not counts:
        return "none"
    return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))


def _band(estimated_tokens: int) -> str:
    """One of :data:`SIZE_BANDS` for a document's estimated tokens."""
    if estimated_tokens < 2000:  # noqa: PLR2004 -- the brief's own band edge
        return _BAND_LOW
    if estimated_tokens <= 10000:  # noqa: PLR2004 -- the brief's own band edge
        return _BAND_HIGH
    return _BAND_TOP


def _occurrence_code(tables: CodeTables, hypothesis: Hypothesis | None) -> str:
    """The composed top-1 occurrence code of one hypothesis; the caller has checked it exists."""
    if hypothesis is None:
        raise ValueError("no hypothesis to compose a code from")  # pragma: no cover -- guarded
    return hypothesis.occurrence_codes(tables)[0]


def _top1_correct(stage: Stage) -> bool:
    """Whether one stage's occurrence top-1 is correct; the caller has checked it was scored."""
    if stage.scores is None:
        raise ValueError("stage has no scores")  # pragma: no cover -- guarded by the caller
    return stage.scores.occurrence_top1


# --------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------


def _settings_lines(probe: Mapping[str, Any]) -> list[str]:
    """``probe.json``'s run settings, one line each -- never a case number."""
    guidance = probe.get("guidance") or []
    cells: Mapping[str, object] = probe.get("per_cell_counts") or {}
    cell_line = ", ".join(f"{key}={value}" for key, value in sorted(cells.items()))
    return [
        f"job_id: {probe['job_id']}",
        f"commit: {probe['commit_sha']} ({'dirty' if probe['dirty'] else 'clean'})",
        f"model: {probe['model']}",
        f"reasoning_effort: {probe['reasoning_effort']}",
        f"price_variant: {probe['price_variant']}",
        f"prompt_version: {probe['prompt_version']}",
        f"guidance: {', '.join(str(g) for g in guidance) or 'none'}",
        f"max_output_tokens: {probe['max_output_tokens']}",
        f"case_cap_usd: {probe['case_cap_usd']:.2f}",
        f"run_cap_usd: {probe['run_cap_usd']:.2f}",
        f"selection_seed: {probe['selection_seed']}",
        f"cases_selected: {probe['cases_selected']}",
        f"cases_run: {probe['cases_run']}",
        f"cells: {cell_line}",
        f"started: {probe['started']}",
        f"finished: {probe.get('finished', 'not finished')}",
    ]


# --------------------------------------------------------------------------------------------
# Case outcomes
# --------------------------------------------------------------------------------------------


def _outcomes_section(trails: Sequence[CaseTrail], probe: Mapping[str, Any]) -> list[str]:
    """Every case's ``stop_reason``, and how many selected cases produced no trail at all (F3).

    A case whose own thread raised an exception ``run_case`` could not recover from (a
    transport error, say) is caught by ``run.py``'s ``_run_cases`` and never reaches
    ``trails.jsonl`` -- so it is invisible to every count above that reads ``trails``, not
    ``probe.json``. ``cases_run - n`` names that gap.
    """
    lines = ["## Case outcomes", ""]
    reasons = Counter(t.stop_reason for t in trails)
    lines.append(f"case stop reasons: {_counter_line(reasons)}")
    cases_run = probe.get("cases_run")
    if isinstance(cases_run, int):
        missing = cases_run - len(trails)
        lines.append(f"cases with no trail (exception): {missing} of {cases_run}")
    return lines


# --------------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------------


def _document_events(trails: Sequence[CaseTrail]) -> list[dict[str, object]]:
    """One entry per attachable document, across every case, with its choice-1/2 outcome.

    ``kind`` is the document's kind *after* transcription (a transcribed handwritten page can
    become "born-digital" or "partial"), so it does not by itself say whether the document
    needed transcription; ``transcribed`` (``transcribed_pages > 0``) carries that fact
    separately (final review, F5).
    """
    events: list[dict[str, object]] = []
    for trail in trails:
        offered1 = set(trail.choice1.offered) if trail.choice1 is not None else set()
        chosen1 = set(trail.choice1.chosen) if trail.choice1 is not None else set()
        offered2 = set(trail.choice2.offered) if trail.choice2 is not None else set()
        chosen2 = set(trail.choice2.chosen) if trail.choice2 is not None else set()
        for document in trail.documents:
            if not document.attachable:
                continue
            events.append(
                {
                    "kind": document.kind or "unknown",
                    "band": _band(document.estimated_tokens),
                    "transcribed": document.transcribed_pages > 0,
                    "offered1": document.index in offered1,
                    "chosen1": document.index in chosen1,
                    "offered2": document.index in offered2,
                    "chosen2": document.index in chosen2,
                }
            )
    return events


def _breakdown(offered: Sequence[Mapping[str, object]], key: str, group_by: str) -> list[str]:
    """One line per value of ``group_by`` among ``offered``, with the ``key`` choice rate."""
    lines = []
    values = sorted({str(item[group_by]) for item in offered})
    for value in values:
        group = [item for item in offered if item[group_by] == value]
        chosen = sum(1 for item in group if item[key])
        lines.append(f"  {value}: {_frac(chosen, len(group))}")
    return lines


def _transcription_breakdown(
    events: Sequence[Mapping[str, object]], predicate: Callable[[Mapping[str, object]], bool]
) -> list[str]:
    """Read rates split by whether a document has any transcribed page (F5).

    ``predicate`` picks the read outcome to measure (chosen at choice 1, at choice 2, or at
    either); a "text layer only" document had nothing transcribed for it to read.
    """
    lines = []
    for has_transcribed, label in ((True, "has transcribed pages"), (False, "text layer only")):
        group = [e for e in events if e["transcribed"] is has_transcribed]
        read = sum(1 for e in group if predicate(e))
        lines.append(f"  {label}: {_frac(read, len(group))}")
    return lines


def _read_either(event: Mapping[str, object]) -> bool:
    """Whether an offered document was read at choice 1 or choice 2 (F6)."""
    return bool(event["chosen1"]) or bool(event["chosen2"])


def _size_band_breakdown(
    events: Sequence[Mapping[str, object]], predicate: Callable[[Mapping[str, object]], bool]
) -> list[str]:
    lines = []
    for band in SIZE_BANDS:
        group = [e for e in events if e["band"] == band]
        read = sum(1 for e in group if predicate(e))
        lines.append(f"  {band}: {_frac(read, len(group))}")
    return lines


def _documents_section(trails: Sequence[CaseTrail]) -> list[str]:
    events = _document_events(trails)
    offered1 = [e for e in events if e["offered1"]]
    offered2 = [e for e in events if e["offered2"]]
    chosen1 = sum(1 for e in offered1 if e["chosen1"])
    chosen2 = sum(1 for e in offered2 if e["chosen2"])
    lines = ["## Documents", ""]
    lines.append(f"documents offered at choice 1: {len(offered1)}")
    lines.append(f"documents chosen at choice 1: {_frac(chosen1, len(offered1))}")
    lines.append(f"documents offered at choice 2: {len(offered2)}")
    lines.append(f"documents chosen at choice 2: {_frac(chosen2, len(offered2))}")
    lines.append("")
    lines.append("choice 1, by kind (after transcription):")
    lines += _breakdown(offered1, "chosen1", "kind")
    lines.append("choice 1, by size band:")
    lines += _size_band_breakdown(offered1, lambda e: bool(e["chosen1"]))
    lines.append("choice 1, by transcription:")
    lines += _transcription_breakdown(offered1, lambda e: bool(e["chosen1"]))
    lines.append("")
    lines.append("choice 2, by kind (after transcription):")
    lines += _breakdown(offered2, "chosen2", "kind") or ["  (nothing offered at choice 2)"]
    lines.append("choice 2, by size band:")
    lines += _size_band_breakdown(offered2, lambda e: bool(e["chosen2"]))
    lines.append("choice 2, by transcription:")
    lines += _transcription_breakdown(offered2, lambda e: bool(e["chosen2"]))
    lines.append("")
    # F6: whether an offered document was ever read, at choice 1 or choice 2 -- every attachable
    # document is offered at choice 1 when the case reaches it, so `offered1` is the population.
    read_either = sum(1 for e in offered1 if _read_either(e))
    lines.append(f"read at either choice: {_frac(read_either, len(offered1))}")
    lines.append("  by transcription:")
    lines += [f"  {line}" for line in _transcription_breakdown(offered1, _read_either)]
    lines.append("  by size band:")
    lines += [f"  {line}" for line in _size_band_breakdown(offered1, _read_either)]
    lines.append("")
    # Whether the read-choice-2 step happened at all, distinguishing "no documents were left"
    # from "the case never got this far".
    ran = sum(1 for t in trails if t.choice2 is not None)
    skipped_empty = sum(1 for t in trails if t.choice2_note == "skipped: nothing left to offer")
    not_reached = len(trails) - ran - skipped_empty
    lines.append(
        f"read choice 2 happened: {_frac(ran, ran + skipped_empty)} of cases with documents left"
    )
    lines.append(f"  nothing left to offer: {skipped_empty}; not reached: {not_reached}")
    return lines


# --------------------------------------------------------------------------------------------
# Hypotheses
# --------------------------------------------------------------------------------------------

_STAGE_TITLES: tuple[tuple[str, Callable[[CaseTrail], Stage]], ...] = (
    ("H0", lambda t: t.h0),
    ("H1", lambda t: t.h1),
    ("H2", lambda t: t.h2),
    ("H_all", lambda t: t.h_all),
    ("final", lambda t: t.final),
    ("refined", lambda t: t.refined),
)


def _stage_counts(
    trails: Sequence[CaseTrail], get: Callable[[CaseTrail], Stage]
) -> tuple[int, int, int, Counter[str]]:
    """``(top1, top3, n scored, exclusion reasons)`` for one stage across every case."""
    top1 = top3 = scored = 0
    reasons: Counter[str] = Counter()
    for trail in trails:
        stage = get(trail)
        if stage.scores is not None:
            scored += 1
            top1 += int(stage.scores.occurrence_top1)
            top3 += int(stage.scores.occurrence_top3)
        else:
            reasons[stage.note or "not reached"] += 1
    return top1, top3, scored, reasons


def _hypotheses_section(trails: Sequence[CaseTrail]) -> list[str]:
    lines = ["## Hypotheses", ""]
    for name, get in _STAGE_TITLES:
        top1, top3, scored, reasons = _stage_counts(trails, get)
        lines.append(f"{name} occurrence top-1: {_frac(top1, scored)}")
        lines.append(f"{name} occurrence top-3: {_frac(top3, scored)}")
        if reasons:
            lines.append(f"  not scored ({sum(reasons.values())}): {_counter_line(reasons)}")
    lines.append("")
    recalls = [
        t.refined.scores.finding_recall_10
        for t in trails
        if t.refined.scores is not None and t.refined.scores.finding_recall_10 is not None
    ]
    if recalls:
        lines.append(f"finding recall@10 mean at refined: {mean(recalls):.1%} (n={len(recalls)})")
    else:
        lines.append("finding recall@10 mean at refined: n=0")
    return lines


# --------------------------------------------------------------------------------------------
# Skip regret
# --------------------------------------------------------------------------------------------


_CONTROL_NOTE = "control: all read"


def _regret_group_lines(title: str, group: Sequence[CaseTrail], tables: CodeTables) -> list[str]:
    paired = [t for t in group if t.h2.scores is not None]
    differs = [
        t
        for t in paired
        if _occurrence_code(tables, t.h_all.hypothesis) != _occurrence_code(tables, t.h2.hypothesis)
    ]
    lines = [f"{title}:", f"  H_all top-1 differs from H2: {_frac(len(differs), len(paired))}"]
    if differs:
        h_all_right = sum(1 for t in differs if _top1_correct(t.h_all) and not _top1_correct(t.h2))
        h2_right = sum(1 for t in differs if _top1_correct(t.h2) and not _top1_correct(t.h_all))
        lines.append(f"    H_all right, H2 wrong: {h_all_right} of {len(differs)}")
        lines.append(f"    H2 right, H_all wrong: {h2_right} of {len(differs)}")
    return lines


def _skip_regret_section(trails: Sequence[CaseTrail], tables: CodeTables) -> list[str]:
    """H_all vs H2, split into cases that actually skipped a document and the noise control.

    From F7, H_all runs even when the agent read every attachable document, noted
    ``"control: all read"``: there, a difference from H2 comes only from history/anchoring and
    run-to-run noise, not from evidence the agent chose not to read. Mixing the two groups
    would overstate skip regret by whatever share of "differs" is really just that noise, so
    they are reported separately, next to each other.
    """
    lines = ["## Skip regret", ""]
    ran = [t for t in trails if t.h_all.scores is not None]
    not_run: Counter[str] = Counter(
        t.h_all.note or "not reached" for t in trails if t.h_all.scores is None
    )
    lines.append(f"H_all ran: {_frac(len(ran), len(trails))}")
    if not_run:
        lines.append(f"  not run: {_counter_line(not_run)}")
    lines.append("")
    control = [t for t in ran if t.h_all.note == _CONTROL_NOTE]
    skipped = [t for t in ran if t.h_all.note != _CONTROL_NOTE]
    lines += _regret_group_lines(
        "skip-regret cases (a document was actually skipped)", skipped, tables
    )
    lines.append("")
    lines += _regret_group_lines(
        "control cases (agent read everything -- the difference rate expected from "
        "history and noise alone)",
        control,
        tables,
    )
    return lines


# --------------------------------------------------------------------------------------------
# Coding checks
# --------------------------------------------------------------------------------------------


def _coding_section(trails: Sequence[CaseTrail], tables: CodeTables) -> list[str]:
    lines = ["## Coding checks", ""]
    reached = [t for t in trails if t.coding_stop is not None]
    lines.append(f"cases that reached the coding checks: {_frac(len(reached), len(trails))}")
    calls_per_case = [sum(1 for s in t.coding_steps if s.tool is not None) for t in reached]
    if calls_per_case:
        lines.append(
            "tool calls per case: min "
            f"{min(calls_per_case)}, median {median(calls_per_case):.1f}, max "
            f"{max(calls_per_case)}"
        )
    else:
        lines.append("tool calls per case: n=0")
    by_tool: Counter[str] = Counter()
    total_calls = total_errors = 0
    for trail in trails:
        for step in trail.coding_steps:
            if step.tool is not None:
                by_tool[step.tool] += 1
                total_calls += 1
                total_errors += step.argument_errors
    lines.append(f"tool calls by tool: {_counter_line(by_tool)}")
    stop_reasons = Counter(t.coding_stop for t in trails if t.coding_stop is not None)
    lines.append(
        f"coding stop reasons: {_counter_line(stop_reasons)}"
        f"; not reached: {len(trails) - len(reached)}"
    )
    lines.append(f"argument errors: {_frac(total_errors, total_calls)} of tool calls")
    distinct_codes = {code for t in trails for s in t.coding_steps for code in s.codes}
    lines.append(f"distinct codes passed to coding tools: {len(distinct_codes)}")
    in_args = [t.true_in_arguments for t in trails if t.true_in_arguments is not None]
    lines.append(
        "cases where the true primary occurrence was among the codes passed: "
        f"{_frac(sum(in_args), len(in_args))}"
    )
    lines.append("")
    lines += _transition_lines(trails, tables)
    lines.append("")
    lines += _follow_pool_lines(trails)
    return lines


def _made_a_coding_call(trail: CaseTrail) -> bool:
    """Whether the case's coding checks called a tool at least once (F4)."""
    return any(step.tool is not None for step in trail.coding_steps)


def _transition_group_lines(
    title: str, group: Sequence[CaseTrail], tables: CodeTables
) -> list[str]:
    differs = [
        t
        for t in group
        if _occurrence_code(tables, t.h2.hypothesis) != _occurrence_code(tables, t.final.hypothesis)
    ]
    lines = [f"{title}:", f"  final top-1 differs from H2: {_frac(len(differs), len(group))}"]
    if differs:
        right_to_wrong = sum(
            1 for t in differs if _top1_correct(t.h2) and not _top1_correct(t.final)
        )
        wrong_to_right = sum(
            1 for t in differs if not _top1_correct(t.h2) and _top1_correct(t.final)
        )
        wrong_to_wrong = sum(
            1 for t in differs if not _top1_correct(t.h2) and not _top1_correct(t.final)
        )
        lines.append(f"    right to wrong: {right_to_wrong} of {len(differs)}")
        lines.append(f"    wrong to right: {wrong_to_right} of {len(differs)}")
        lines.append(f"    wrong to wrong: {wrong_to_wrong} of {len(differs)}")
    return lines


def _transition_lines(trails: Sequence[CaseTrail], tables: CodeTables) -> list[str]:
    """Final-vs-H2 transitions, split by whether the case made a coding tool call (F4).

    Cases with zero tool calls answered ``done`` at the coding checks' first reply without
    checking anything: any final-vs-H2 change there comes only from re-asking (the coding
    system text and the final instruction), not from a tool result -- the control group the
    "with calls" cases are read against.
    """
    paired = [t for t in trails if t.h2.scores is not None and t.final.scores is not None]
    with_calls = [t for t in paired if _made_a_coding_call(t)]
    without_calls = [t for t in paired if not _made_a_coding_call(t)]
    lines = _transition_group_lines("cases with at least one coding tool call", with_calls, tables)
    lines.append("")
    lines += _transition_group_lines(
        "cases with no coding tool call (re-asking control)", without_calls, tables
    )
    return lines


def _follow_pool_lines(trails: Sequence[CaseTrail]) -> list[str]:
    """Follow/override rates, restricted to a final top-3 with at least two distinct codes.

    A single-code top-3 makes ``follows_pool`` ``None`` (``loop.py``'s ``trail()``): the pool's
    top choice among one code is that code, so every such case would otherwise be counted as
    "followed" without a real override to measure. Those cases are reported on their own line
    instead (final review, F2).
    """
    with_final = [t for t in trails if t.final.scores is not None]
    scored = [t for t in with_final if t.follows_pool is not None]
    single_code = [t for t in with_final if t.follows_pool is None]
    follows = [t for t in scored if t.follows_pool]
    overrides = [t for t in scored if not t.follows_pool]
    follows_right = sum(1 for t in follows if _top1_correct(t.final))
    overrides_right = sum(1 for t in overrides if _top1_correct(t.final))
    single_right = sum(1 for t in single_code if _top1_correct(t.final))
    return [
        "followed the pool's top choice (final top-3 with 2+ distinct codes): "
        f"{_frac(len(follows), len(scored))}",
        f"  right when following: {_frac(follows_right, len(follows))}",
        f"  right when overriding: {_frac(overrides_right, len(overrides))}",
        f"single-code final top-3 (follow/override not applicable): "
        f"{_frac(len(single_code), len(with_final))}",
        f"  right: {_frac(single_right, len(single_code))}",
    ]


# --------------------------------------------------------------------------------------------
# Cost and reliability
# --------------------------------------------------------------------------------------------


def _cost_section(trails: Sequence[CaseTrail]) -> list[str]:
    lines = ["## Cost and reliability", ""]
    calls_per_case = [len(t.calls) for t in trails]
    if calls_per_case:
        lines.append(
            "calls per case: min "
            f"{min(calls_per_case)}, median {median(calls_per_case):.1f}, max "
            f"{max(calls_per_case)}"
        )
    costs = [t.cost_usd for t in trails]
    if costs:
        lines.append(f"cost per case: mean ${mean(costs):.4f}, max ${max(costs):.4f}")
        lines.append(f"total cost: ${sum(costs):.4f} (n={len(costs)} cases)")
    lines.append("")
    lines += _phase_token_lines(trails)
    lines.append("")
    lines += _growth_lines(trails)
    lines.append("")
    seconds = [c.seconds for t in trails for c in t.calls]
    if seconds:
        lines.append(
            f"seconds per call: mean {mean(seconds):.2f}, max {max(seconds):.2f} "
            f"(n={len(seconds)} calls)"
        )
    else:
        lines.append("seconds per call: n=0")
    retries: Counter[str] = Counter()
    for trail in trails:
        for call in trail.calls:
            if call.parse_retry:
                retries[call.phase] += 1
    lines.append(f"parse retries by phase: {_counter_line(retries)}")
    failures: Counter[str] = Counter()
    for trail in trails:
        if trail.stop_reason.startswith("failed:"):
            failures[trail.stop_reason.removeprefix("failed: ")] += 1
        if trail.h_all.note is not None and trail.h_all.note.startswith("failed:"):
            failures[f"h_all {trail.h_all.note.removeprefix('failed: ')}"] += 1
    lines.append(f"failures by phase: {_counter_line(failures)}")
    finish: Counter[str] = Counter()
    for trail in trails:
        for call in trail.calls:
            finish[call.finish_reason or "none"] += 1
    lines.append(f"finish reasons: {_counter_line(finish)}")
    return lines


def _phase_token_lines(trails: Sequence[CaseTrail]) -> list[str]:
    by_phase: dict[str, list[int]] = defaultdict(list)
    for trail in trails:
        for call in trail.calls:
            by_phase[call.phase].append(call.prompt_tokens)
    lines = ["prompt tokens per call by phase (mean, max):"]
    for phase in sorted(by_phase):
        tokens = by_phase[phase]
        lines.append(f"  {phase}: mean {mean(tokens):.0f}, max {max(tokens)} (n={len(tokens)})")
    return lines


def _growth_lines(trails: Sequence[CaseTrail]) -> list[str]:
    """Mean H0 prompt tokens, mean last-coding-call prompt tokens, and the mean per-case ratio."""
    h0_tokens: list[int] = []
    last_coding_tokens: list[int] = []
    ratios: list[float] = []
    for trail in trails:
        h0 = next((c.prompt_tokens for c in trail.calls if c.phase == "h0"), None)
        coding = [c.prompt_tokens for c in trail.calls if c.phase == "coding"]
        if h0 is not None:
            h0_tokens.append(h0)
        if coding:
            last_coding_tokens.append(coding[-1])
        if h0 is not None and coding and h0 > 0:
            ratios.append(coding[-1] / h0)
    lines = ["growth, H0 to last coding call, mean prompt tokens:"]
    if h0_tokens:
        lines.append(f"  H0: mean {mean(h0_tokens):.0f} (n={len(h0_tokens)})")
    else:
        lines.append("  H0: n=0")
    if last_coding_tokens:
        lines.append(
            f"  last coding call: mean {mean(last_coding_tokens):.0f} (n={len(last_coding_tokens)})"
        )
    else:
        lines.append("  last coding call: n=0")
    if ratios:
        lines.append(f"  mean ratio (last coding / H0): {mean(ratios):.2f} (n={len(ratios)})")
    else:
        lines.append("  mean ratio: n=0")
    return lines


# --------------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------------


def build_report(job_dir: Path) -> str:
    """The full counts-only report for one run.

    Args:
        job_dir: ``<data_dir>/probes/s3-probe/<job_id>``.

    Returns:
        The report text, ending in one newline.
    """
    probe, trails = load_job(job_dir)
    tables = load_tables()
    lines = [HEADLINE.format(n=len(trails)), ""]
    lines += _settings_lines(probe)
    lines.append("")
    lines += _outcomes_section(trails, probe)
    lines.append("")
    lines += _documents_section(trails)
    lines.append("")
    lines += _hypotheses_section(trails)
    lines.append("")
    lines += _skip_regret_section(trails, tables)
    lines.append("")
    lines += _coding_section(trails, tables)
    lines.append("")
    lines += _cost_section(trails)
    return "\n".join(lines) + "\n"


def cmd_report(job_dir: Path, *, out: Path | None) -> str:
    """Build the report, print it, and write it to ``out`` when given.

    Args:
        job_dir: ``<data_dir>/probes/s3-probe/<job_id>``.
        out: an optional path the report text is also written to (``docs/results/...``).

    Returns:
        The report text (so a caller, or a test, can inspect it without re-reading a file).
    """
    text = build_report(job_dir)
    print(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    return text
