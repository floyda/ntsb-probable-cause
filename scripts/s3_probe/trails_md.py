"""scripts/s3_probe/trails_md.py: one readable Markdown trail per case, for Andy (Task 6).

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

Unlike ``report.py``, these files are allowed to carry a case ID, docket-document facts, the
agent's own reasons and expected effects, and tool result text -- they are private reading
material for the project owner, written under the job folder alone
(``<data_dir>/probes/s3-probe/<job_id>/trails/<n>.md``) and never committed (``constraints.md``,
"No case text in git"). They hold no docket *text*: only the measured facts already in the
trail (kind, pages, estimated tokens) and the agent's own words about them.
"""

from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.records import read_jsonl
from scripts.s3_probe.trail import (
    CallRecord,
    CaseTrail,
    CodingStep,
    ReadChoiceRecord,
    Stage,
    TrailDocument,
)

TRAILS_RELATIVE = Path("trails")


def _occurrence_line(tables: CodeTables, guess: OccurrenceGuess) -> str:
    code = tables.compose_occurrence(guess.phase, guess.event)
    phase_label = tables.phases.get(guess.phase, "?")
    event_label = tables.events.get(guess.event, "?")
    return f"{code}: {phase_label} / {event_label} (p={guess.probability:.2f})"


def _finding_line(tables: CodeTables, guess: FindingGuess) -> str:
    category_label = tables.categories.get(guess.category6, "?")
    modifier_label = tables.modifiers.get(guess.modifier, "?")
    item = f", item {tables.items.get(guess.item8, '?')}" if guess.item8 is not None else ""
    return (
        f"{guess.category6}/{guess.modifier}: {category_label} — {modifier_label}{item} "
        f"(p={guess.probability:.2f})"
    )


def _document_line(document: TrailDocument) -> str:
    return (
        f"- {document.index}: kind={document.kind or 'unknown'}, pages={document.pages}, "
        f"readable={document.readable_pages}, estimated_tokens={document.estimated_tokens}, "
        f"transcribed_pages={document.transcribed_pages}, attachable={document.attachable}"
    )


def _answer_lines(tables: CodeTables, hypothesis: Hypothesis) -> list[str]:
    lines = ["occurrence:"]
    lines += [f"- {_occurrence_line(tables, g)}" for g in hypothesis.occurrence]
    lines.append("findings:")
    lines += [f"- {_finding_line(tables, g)}" for g in hypothesis.findings] or ["- none"]
    lines.append(f"confidence: {hypothesis.confidence:.2f}")
    lines.append(f"abstain: {hypothesis.abstain}")
    return lines


def _stage_block(tables: CodeTables, title: str, stage: Stage) -> list[str]:
    lines = [f"### {title}"]
    if stage.hypothesis is None:
        lines.append(f"(absent: {stage.note or 'not reached'})")
        if stage.detail is not None:
            lines.append(f"detail: {stage.detail}")
        return lines
    lines += _answer_lines(tables, stage.hypothesis)
    if stage.scores is not None:
        recall = (
            f", finding recall@10 {stage.scores.finding_recall_10:.1%}"
            if stage.scores.finding_recall_10 is not None
            else ""
        )
        lines.append(
            f"scored: top-1 {stage.scores.occurrence_top1}, top-3 {stage.scores.occurrence_top3}"
            f"{recall}"
        )
    if stage.note is not None:
        lines.append(f"note: {stage.note}")
    return lines


def _choice_block(title: str, record: ReadChoiceRecord | None, note: str | None) -> list[str]:
    lines = [f"### {title}"]
    if record is None:
        lines.append(f"(not reached: {note or 'not reached'})")
        return lines
    lines.append(f"reason: {record.reason}")
    for document in record.documents:
        state = "read" if document.read else "not read"
        lines.append(f"- {document.index}: {state} — expected effect: {document.expected_effect}")
    return lines


def _coding_block(tables: CodeTables, steps: Sequence[CodingStep]) -> list[str]:
    lines = ["### Coding checks"]
    if not steps:
        lines.append("(none)")
        return lines
    for number, step in enumerate(steps, start=1):
        if step.tool is None:
            lines.append(f"{number}. done — reason: {step.reason}")
        else:
            lines.append(f"{number}. {step.tool}(kind={step.kind}, codes={list(step.codes)})")
            lines.append(f"   reason: {step.reason}")
            lines.append(f"   expected effect: {step.expected_effect}")
            lines.append(f"   argument errors: {step.argument_errors}")
            if step.result_text is not None:
                indented = step.result_text.replace("\n", "\n   ")
                lines.append(f"   result:\n   {indented}")
        top3 = "; ".join(_occurrence_line(tables, g) for g in step.top3)
        lines.append(f"   top3: {top3}")
    return lines


def _calls_block(calls: Sequence[CallRecord]) -> list[str]:
    lines = ["### Calls"]
    if not calls:
        lines.append("(none)")
        return lines
    for call in calls:
        lines.append(
            f"- {call.phase}: prompt={call.prompt_tokens}, completion={call.completion_tokens}, "
            f"reasoning={call.reasoning_tokens}, cost=${call.cost_usd:.4f}, "
            f"seconds={call.seconds:.2f}, finish={call.finish_reason}, retry={call.parse_retry}"
        )
    return lines


def _truth_block(tables: CodeTables, trail: CaseTrail) -> list[str]:
    lines = ["### Truth"]
    if trail.true_primary is not None:
        phase_label = tables.phases.get(trail.true_primary[:3], "?")
        event_label = tables.events.get(trail.true_primary[3:], "?")
        lines.append(
            f"true primary occurrence: {trail.true_primary}: {phase_label} / {event_label}"
        )
    else:
        lines.append("true primary occurrence: unavailable (the verdict was never split)")
    if trail.true_findings:
        lines.append("true flagged findings:")
        for code in trail.true_findings:
            item8, modifier = code[:8], code[8:]
            item_label = tables.items.get(item8, "?")
            modifier_label = tables.modifiers.get(modifier, "?")
            lines.append(f"- {code}: {item_label} — {modifier_label}")
    else:
        lines.append("true flagged findings: none")
    lines.append(f"true primary occurrence among coding-tool codes: {trail.true_in_arguments}")
    return lines


def render_trail(tables: CodeTables, trail: CaseTrail) -> str:
    """Render one case's readable Markdown trail.

    Args:
        tables: the code tables (for labels).
        trail: the case's :class:`~scripts.s3_probe.trail.CaseTrail`.

    Returns:
        The Markdown text, ending in one newline.
    """
    lines = [
        f"# {trail.case_id}",
        "",
        f"fatal: {trail.fatal}",
        f"has_scan: {trail.has_scan}",
        f"stop_reason: {trail.stop_reason}",
        f"coding_stop: {trail.coding_stop}",
        f"total cost: ${trail.cost_usd:.4f}",
        "",
        "## Documents",
    ]
    lines += [_document_line(d) for d in trail.documents] or ["(none)"]
    lines.append("")
    lines.append("## Flow")
    lines.append("")
    lines += _stage_block(tables, "H0", trail.h0)
    lines.append("")
    lines += _choice_block("Read choice 1", trail.choice1, trail.choice1_note)
    lines.append("")
    lines += _stage_block(tables, "H1", trail.h1)
    lines.append("")
    lines += _choice_block("Read choice 2", trail.choice2, trail.choice2_note)
    lines.append("")
    lines += _stage_block(tables, "H2", trail.h2)
    lines.append("")
    lines += _stage_block(tables, "H_all (skip regret)", trail.h_all)
    lines.append("")
    lines += _coding_block(tables, trail.coding_steps)
    lines.append("")
    lines += _stage_block(tables, "Final", trail.final)
    lines.append("")
    lines += _stage_block(tables, "Refined", trail.refined)
    lines.append("")
    lines += _truth_block(tables, trail)
    lines.append("")
    lines += _calls_block(trail.calls)
    if trail.leak is not None:
        lines.append("")
        lines.append(f"leak: {trail.leak}")
    if trail.failure is not None:
        lines.append(f"failure: {trail.failure}")
    return "\n".join(lines) + "\n"


def write_trails(job_dir: Path) -> int:
    """Write one Markdown file per case, ``trails/<n>.md`` in run order, under ``job_dir``.

    Args:
        job_dir: ``<data_dir>/probes/s3-probe/<job_id>``; must already hold ``trails.jsonl``.

    Returns:
        The number of files written.
    """
    trails = read_jsonl(job_dir / "trails.jsonl", CaseTrail)
    tables = load_tables()
    out_dir = job_dir / TRAILS_RELATIVE
    out_dir.mkdir(parents=True, exist_ok=True)
    for number, trail in enumerate(trails, start=1):
        (out_dir / f"{number}.md").write_text(render_trail(tables, trail))
    return len(trails)
