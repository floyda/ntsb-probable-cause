"""A few arm C case trails as one private, readable page, for Andy to read before a round.

Status
    Live tool for S3.1's tuning rounds (plan Task 15), free: a private reading aid. It reads
    finished arm C run folders, a ``groups.json`` written by ``scripts/s3_case_groups.py``, the
    processed records and the docket cache; it makes no model call and fetches nothing. Its
    output is a page for the owner's own browser, written under ``NTSB_RUNS_DIR``
    (``s3-trail-pages/<UTC time>/``), never inside the repository and never committed. It is
    not a result: no number on it is cited anywhere.

Why
    A tuning round is designed from trails, and which trails are read decides what the designer
    sees. Andy chose to read them from a stated group, never picked by eye: the arm C "always
    wrong" cases (wrong on occurrence top-1, or failed, in both of the loop's identical
    noise-floor runs; decision 0136 item 1). ``trail.jsonl`` keeps every model call's parsed
    arguments, reasons and hypotheses, but not the text of the tool results; this page puts a
    case's calls in order beside the NTSB's verdict, with each coding tool's text rebuilt.

The draw
    The chosen group's case ids, sorted, split into fatal and non-fatal by the run's own
    ``cases.jsonl``; ``--fatal`` cases drawn from the fatal ones and then ``--nonfatal`` from
    the rest, with one ``random.Random(--seed)``, and each slice shown sorted, fatal first. A
    slice smaller than asked is shown whole. The same arguments always draw the same cases and
    write the same page.

What the page shows, at its top
    The runs, the group and the draw; then the kinds and the patterns among the cases shown
    (run a), counted, as ``scripts/miss_kinds.py`` classifies them.

What the page shows, per case
    A header (the case number, which is fine here: the page is private and never committed; the
    event date; fatal or not; the docket's documents listed, offered and read; how the case
    ended in the run). Then the differences at a glance, so a reader sees first whether the loop
    went wrong somewhere or never came close: the NTSB's first occurrence code (its defining
    event) against the loop's first code and its probability, with the kind and the patterns
    ``scripts/miss_kinds.py`` gives them; at each checkpoint (H0, H1, H2, the answer) whether
    the NTSB's first code was among the loop's codes, at which rank and probability, and one
    line: never in any hypothesis, held at a checkpoint then dropped, or in the answer at its
    rank; which accepted coding calls named that code in their arguments, and whose rebuilt
    text listed it; the NTSB's whole occurrence sequence, each code marked with its rank in the
    loop's answer or its absence; each finding flagged as cause, matched exactly (item and
    modifier), at item level only, at category level only, or missed (``finding_depth``'s
    levels), and the loop's findings whose category matches no NTSB finding, flagged or not;
    with ``--compare``, run b's first code and kind in one line.

    Then every model call in order: each checkpoint's hypothesis (occurrence codes with labels
    and probabilities, findings with labels, confidence, abstain, the agent's own evidence
    narrative and working cause); each read choice (per document on offer, in offer order: its
    listing index, title, pages, read or skip, and the agent's expected effect; the choice's
    reason; each decision on a document not on offer with the line the loop answered it with,
    ``texts.extras_lines``); each coding call (the tool, its arguments with labels, the agent's
    reason and expected effect, and the tool's text); each call the loop did not accept, with
    its sanitised error, and the retry after it. Then the final answer as scored (after
    refinement), the NTSB's verdict for comparison (occurrence codes in the NTSB's order with
    labels, finding codes with labels and which are flagged as in the probable cause, the
    probable-cause text, all from ``split_record``) and, with ``--compare``, the other run's
    final answer in one line.

Rebuilt, not recorded
    The coding tools are pure functions over the code tables and the statistics pool
    (``agent/tools.py``). Each coding call's text is rebuilt by parsing its recorded arguments
    as the loop does and running the tool again on ``load_tables()`` and ``load_stats("s3")``;
    the page says so, and prints the rebuilt length beside the characters the trail recorded as
    sent back for that reply (they differ only when the reply made a second tool call, which the
    loop answers with a fixed sentence). The documents offered are re-derived from the docket
    cache with ``agent/documents.py``'s ``docket_view`` and checked against the offer each read
    choice recorded; a cache that no longer matches is refused.

Names
    The page shows no record field but the event date and the injury level, no document text,
    and no owner or operator field. Every title and every piece of the agent's or the NTSB's
    prose passes through the attach step's own replacements (``amateur_built_replace``,
    ``redact_known_names``): an amateur-built aircraft's make and model, and every owner or
    operator name the record holds, are replaced as the agent's text had them replaced (decisions
    0044, 0046). Other names in the agent's prose are not detected.

Refusals, before any case is read where they can be
    An output folder inside the repository (outside its git-ignored ``data/``); a held-out run
    id; a folder with no ``run.jsonl``, or whose record names another run; a run on any sample
    but ``dev-400`` (held-out, open, and the sealed samples, a sealed one not yet opened refused
    as sealed first); a run of any arm but C; a run that has not finished; a run with no
    ``trail.jsonl``, or whose trail holds another run's call; a case outside the development
    split; ``--compare`` naming the run itself, or a run refused for any reason above; a groups
    file that is missing, not on ``dev-400``, not drawn over ``--run``, or without the split
    asked for; a group case the run does not hold; a drawn case whose verdict holds no
    occurrence code (no defining event to compare). Then, per case: a record outside the
    development split or for another case; a docket not wholly in the cache (nothing is
    fetched); a docket whose key is not the record's; a read choice whose offer the cached
    docket could not have made. A second page in the same second is refused rather than written
    over.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.s3_trail_pages --run RUN [--compare RUN] \
        --groups PATH --group always_wrong --arm C --fatal N --nonfatal N --seed S \
        [--out-dir DIR]

    Prints one line: the page's folder, relative to the folder it was made in (the runs folder
    by default). The folder holds ``trails.html`` and its Markdown copy ``trails.md``.
"""

import argparse
import html
import json
import logging
import random
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from string import Template
from typing import Final, NoReturn, cast

import httpx
from pydantic import BaseModel

from ntsb_probable_cause.agent.documents import DocketView, docket_view
from ntsb_probable_cause.agent.schemas import (
    CODING_TOOLS,
    CodingToolName,
    DescribeCodes,
    DocumentChoice,
    OccurrenceUsage,
    PastFindings,
    SuggestCodes,
    parse_call,
)
from ntsb_probable_cause.agent.texts import extras_lines
from ntsb_probable_cause.agent.tools import run_coding_tool
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket import manifest
from ntsb_probable_cause.docket.attach import DOCKET_KEY, amateur_built_replace, redact_known_names
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import ConfigurationError, SchemaError
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, load_stats
from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split, split_of
from scripts.miss_kinds import KINDS, PATTERNS, answer_codes, case_difference, scored_answer

SAMPLE: Final = "dev-400"
ARM: Final = "C"
FOLDER: Final = "s3-trail-pages"
HTML_FILE: Final = "trails.html"
MARKDOWN_FILE: Final = "trails.md"
# The command-line names of the groups and splits, and what ``groups.json`` calls them.
GROUPS: Final[Mapping[str, str]] = {
    "always_wrong": "always wrong",
    "always_right": "always right",
    "flipping": "flipping",
}
SPLITS: Final[Mapping[str, str]] = {"C": "arm C", "B": "arm B", "all": "all"}
# The repository this script lives in. Its ``data/`` is git-ignored (CLAUDE.md rule 4).
REPOSITORY: Final = Path(__file__).resolve().parents[1]
_STAMP: Final = "%Y%m%dT%H%M%S"
_UNKNOWN: Final = "not in the code tables"
_STEPS: Final[Mapping[str, str]] = {
    "h0": "first hypothesis (H0)",
    "choice1": "first read choice",
    "h1": "hypothesis after the first read (H1)",
    "choice2": "second look",
    "h2": "hypothesis after the second look (H2)",
    "coding": "coding step",
    "answer": "answer",
    "refine": "refinement",
}


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_trail_pages: {message}")


class CacheMissError(Exception):
    """A docket file the cache does not hold: this page reads the cache only, never the web."""


# --- the page's parts: one list of blocks, rendered as HTML and as Markdown ---


@dataclass(frozen=True)
class Heading:
    """A heading; ``anchor`` is its HTML id, if it has one."""

    level: int
    text: str
    anchor: str = ""


@dataclass(frozen=True)
class Para:
    """A paragraph, led by a bold label when it has one; ``warn`` marks a call not accepted."""

    text: str
    label: str = ""
    warn: bool = False


@dataclass(frozen=True)
class Items:
    """A list, led by a label when it has one."""

    items: tuple[str, ...]
    label: str = ""
    ordered: bool = False


@dataclass(frozen=True)
class Pre:
    """Text shown exactly as it is (a tool's result), under a summary line."""

    text: str
    summary: str


@dataclass(frozen=True)
class Contents:
    """The cases, linked: ``(anchor, text)`` pairs."""

    entries: tuple[tuple[str, str], ...]


type Block = Heading | Para | Items | Pre | Contents


# --- reading the runs and the groups ---


@dataclass(frozen=True)
class Run:
    """One finished arm C run: its cases and each case's calls, in call order."""

    run_id: str
    cases: Mapping[str, CaseResult]
    calls: Mapping[str, tuple[AgentCall, ...]]


def load_run(runs_dir: Path, run_id: str) -> Run:
    """A finished ``dev-400`` arm C run, after every refusal that applies to a run.

    Args:
        runs_dir: the runs folder.
        run_id: the run's id, its folder's name.

    Returns:
        The run.
    """
    try:
        samples.refuse_unless_development(run_id, None)
    except ConfigurationError as error:
        _refuse(str(error))
    folder = runs_dir / run_id
    if not (folder / "run.jsonl").is_file():
        _refuse(f"{run_id}: no run.jsonl in {folder}")
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    if record.run_id != run_id:
        _refuse(f"{run_id}: its run.jsonl names run {record.run_id}: a copied or renamed folder")
    try:
        samples.refuse_unless_development(run_id, record.sample)
    except ConfigurationError as error:
        _refuse(str(error))
    if record.sample != SAMPLE:
        _refuse(f"{run_id} is on {record.sample}; trail pages read {SAMPLE} runs only")
    if record.arm != ARM:
        _refuse(f"{run_id} is arm {record.arm}; trail pages read arm C runs only")
    if record.finished is None:
        _refuse(f"{run_id} has not finished: it did not complete a pass")
    if not (folder / "trail.jsonl").is_file():
        _refuse(f"{run_id}: no trail.jsonl in {folder}")
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != Split.DEV.value for c in cases):
        _refuse(f"{run_id} holds a case outside the dev split")
    calls: dict[str, list[AgentCall]] = {}
    for call in read_jsonl(folder / "trail.jsonl", AgentCall):
        if call.run_id != run_id:
            _refuse(f"{run_id}: its trail.jsonl holds a call of run {call.run_id}")
        calls.setdefault(call.case_id, []).append(call)
    return Run(
        run_id,
        {c.case_id: c for c in cases},
        {
            case_id: tuple(sorted(rows, key=lambda c: (c.trigger, c.call_index)))
            for case_id, rows in calls.items()
        },
    )


def read_group(path: Path, *, split: str, group: str, run_id: str) -> tuple[str, ...]:
    """One group's case ids, sorted, from a ``groups.json`` drawn over ``run_id``.

    Args:
        path: the groups file ``scripts/s3_case_groups.py`` wrote.
        split: ``"arm C"``, ``"arm B"`` or ``"all"``.
        group: ``"always wrong"``, ``"always right"`` or ``"flipping"``.
        run_id: the run whose trails are read; the groups must have been drawn over it.

    Returns:
        The case ids.
    """
    if not path.is_file():
        _refuse(f"no groups file at {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("sample") != SAMPLE:
        _refuse(f"{path} is not a {SAMPLE} groups file (scripts/s3_case_groups.py)")
    runs = data.get("runs")
    listed = (
        {r.get("run_id") for r in runs if isinstance(r, dict)} if isinstance(runs, list) else ()
    )
    if run_id not in listed:
        _refuse(f"{path} was not drawn over run {run_id}: read the groups the run was sorted into")
    groups = data.get("groups")
    chosen = groups.get(split) if isinstance(groups, dict) else None
    ids = chosen.get(group) if isinstance(chosen, dict) else None
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        _refuse(f"{path} holds no {split} groups")
    return tuple(sorted(cast(list[str], ids)))


def draw(
    ids: Sequence[str], fatal: Mapping[str, bool], *, per_fatal: int, per_nonfatal: int, seed: int
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The fatal and the non-fatal cases to show, each sorted; the same seed, the same cases.

    Args:
        ids: the group's case ids, in any order (sorted before drawing).
        fatal: whether each case is fatal.
        per_fatal: how many fatal cases to draw; a smaller pool is taken whole.
        per_nonfatal: how many non-fatal cases to draw, likewise.
        seed: the seed of the one generator both draws use, fatal first.

    Returns:
        The fatal cases, then the non-fatal ones.
    """
    rng = random.Random(seed)  # noqa: S311 -- reproducible sampling, not security
    ordered = sorted(set(ids))

    def take(pool: list[str], wanted: int) -> tuple[str, ...]:
        return tuple(sorted(pool if len(pool) <= wanted else rng.sample(pool, wanted)))

    return (
        take([i for i in ordered if fatal[i]], per_fatal),
        take([i for i in ordered if not fatal[i]], per_nonfatal),
    )


# --- labels ---


def occurrence_label(tables: CodeTables, code: str) -> str:
    """``phase / event`` for a six-digit occurrence code, or a note that it is not one."""
    phase, event = tables.phases.get(code[:3]), tables.events.get(code[3:])
    if len(code) != 6 or phase is None or event is None:  # noqa: PLR2004 -- six digits
        return _UNKNOWN
    return f"{phase} / {event}"


def _guess(tables: CodeTables, guess: OccurrenceGuess) -> str:
    code = guess.phase + guess.event
    return f"{code}: {occurrence_label(tables, code)} (p {guess.probability:.2f})"


def _finding(tables: CodeTables, guess: FindingGuess) -> str:
    text = (
        f"{guess.category6}/{guess.modifier}: {tables.categories.get(guess.category6, _UNKNOWN)} "
        f"[{tables.modifiers.get(guess.modifier, _UNKNOWN)}]"
    )
    if guess.item8 is not None:
        text += f"; item {guess.item8} {tables.items.get(guess.item8, _UNKNOWN)}"
    return f"{text} (p {guess.probability:.2f})"


def _verdict_finding(tables: CodeTables, code: str, *, cause: bool) -> str:
    item, modifier = tables.items.get(code[:8], _UNKNOWN), tables.modifiers.get(code[8:], _UNKNOWN)
    text = f"{code}: {item} [{modifier}]"
    return f"{text}; flagged as cause" if cause else text


def _answer_line(tables: CodeTables, hypothesis: Hypothesis) -> str:
    """A final answer in one line: occurrence codes, then findings."""
    codes = "; ".join(_guess(tables, g) for g in hypothesis.occurrence)
    findings = "; ".join(_finding(tables, g) for g in hypothesis.findings) or "none"
    return f"{codes}. Findings: {findings}"


def _pages(count: int) -> str:
    return f"{count} page" if count == 1 else f"{count} pages"


def _describe_label(tables: CodeTables, kind: str, code: str) -> str:
    if kind == "occurrence":
        return occurrence_label(tables, code)
    table = tables.categories if kind == "finding_category" else tables.items
    return table.get(code, _UNKNOWN)


def _argument_lines(tables: CodeTables, arguments: BaseModel) -> tuple[str, ...]:
    """A coding call's arguments, each code with its label."""
    if isinstance(arguments, DescribeCodes):
        return (
            f"kind: {arguments.kind}",
            *(f"{c}: {_describe_label(tables, arguments.kind, c)}" for c in arguments.codes),
        )
    if isinstance(arguments, OccurrenceUsage):
        return tuple(f"{c}: {occurrence_label(tables, c)}" for c in arguments.codes)
    if isinstance(arguments, PastFindings):
        return (f"{arguments.occurrence}: {occurrence_label(tables, arguments.occurrence)}",)
    if isinstance(arguments, SuggestCodes):
        return (f"phase group: {arguments.phase_group}",)
    raise TypeError(f"not a coding tool's arguments: {type(arguments).__name__}")


# --- one case ---


def _parsed(call: AgentCall, tables: CodeTables) -> BaseModel:
    """A coding call's recorded arguments, parsed as the loop parsed them."""
    try:
        return parse_call(str(call.tool), json.dumps(call.arguments), tables)
    except SchemaError as error:
        _refuse(f"{call.case_id}: call {call.call_index}: its arguments do not parse: {error}")


def rebuilt_tool_text(call: AgentCall, tables: CodeTables, stats: CodingStats) -> str:
    """The text a coding call's tool returned, rebuilt by running it again on its arguments.

    Args:
        call: an accepted coding call (``describe_codes``, ``occurrence_usage``,
            ``past_findings`` or ``suggest_codes``).
        tables: the code tables.
        stats: the statistics pool the run's tools counted in (``load_stats("s3")``).

    Returns:
        What ``run_coding_tool`` returns for the recorded arguments.
    """
    tool = cast(CodingToolName, call.tool)
    return run_coding_tool(tool, _parsed(call, tables), tables=tables, stats=stats).text


@dataclass(frozen=True)
class _Case:
    """What one case's section is built from."""

    case_id: str
    raw: Mapping[str, object]
    result: CaseResult
    calls: tuple[AgentCall, ...]
    docket: Docket
    view: DocketView


@dataclass(frozen=True)
class _Reading:
    """What every case is read with."""

    tables: CodeTables
    stats: CodingStats
    other: Run | None


def _clean(text: str, raw: Mapping[str, object]) -> str:
    """The attach step's replacements: an amateur-built make and model, owner/operator names."""
    text, _ = amateur_built_replace(text, raw)
    text, _ = redact_known_names(text, raw)
    return text


def _hypothesis_blocks(
    tables: CodeTables, hypothesis: Hypothesis, raw: Mapping[str, object]
) -> list[Block]:
    return [
        Items(
            tuple(_guess(tables, g) for g in hypothesis.occurrence),
            label="Occurrence codes",
            ordered=True,
        ),
        Items(tuple(_finding(tables, g) for g in hypothesis.findings) or ("none",), "Findings"),
        Para(
            f"{hypothesis.confidence:.2f}; abstain: {'yes' if hypothesis.abstain else 'no'}",
            "Confidence",
        ),
        Para(_clean(hypothesis.evidence_narrative, raw), "Evidence narrative (the agent's own)"),
        Para(_clean(hypothesis.probable_cause, raw), "Working cause"),
    ]


def _choice_blocks(case: _Case, choice: DocumentChoice, offered: Sequence[int]) -> list[Block]:
    """Each document on offer, in offer order, then each decision on one that was not."""
    raw, docket = case.raw, case.docket
    titles = {entry.index: entry.title for entry in docket.listing.entries}
    decided = {d.document: d for d in choice.decisions}
    lines = []
    for index in offered:
        decision = decided[index]
        lines.append(
            f"[{index}] {_clean(titles[index], raw)} ({_pages(docket.record(index).pages)}): "
            f"{'read' if decision.read else 'skip'}. Expected: "
            f"{_clean(decision.expected_effect, raw)}"
        )
    blocks: list[Block] = [
        Para(_clean(choice.arguments.reason, raw), "Reason for the choice"),
        Items(tuple(lines), "Documents on offer, in offer order"),
    ]
    if choice.extras:
        answers = extras_lines(choice.extras).splitlines()
        extras = []
        for extra, answer in zip(choice.extras, answers, strict=True):
            asked = next(d for d in choice.arguments.decisions if d.document == extra.document)
            extras.append(
                f"[{extra.document}] asked to {'read' if asked.read else 'skip'}; expected: "
                f"{_clean(asked.expected_effect, raw)}. Answered: {answer}"
            )
        blocks.append(Items(tuple(extras), "Decisions on documents not on offer (never acted on)"))
    return blocks


def _coding_blocks(case: _Case, call: AgentCall, reading: _Reading) -> list[Block]:
    raw, tables = case.raw, reading.tables
    text = rebuilt_tool_text(call, tables, reading.stats)
    blocks: list[Block] = [
        Items(_argument_lines(tables, _parsed(call, tables)), "Arguments"),
        Para(_clean(str(call.arguments.get("reason", "")), raw), "Reason"),
        Para(_clean(str(call.arguments.get("expected_effect", "")), raw), "Expected effect"),
    ]
    if call.argument_errors:
        blocks.append(Para(str(call.argument_errors), "Argument errors the tool counted"))
    blocks.append(
        Pre(
            text,
            f"Tool result, rebuilt by re-running {call.tool} on the recorded arguments "
            f"({len(text)} characters; the trail recorded {call.result_chars} sent back for this "
            "reply)",
        )
    )
    return blocks


def _trail_blocks(case: _Case, reading: _Reading) -> tuple[list[Block], int]:
    """Every call of the case, in order; and how many documents its choices read."""
    tables, raw = reading.tables, case.raw
    offerable = {f.index for f in case.view.offered}
    not_readable = tuple(f.index for f in case.view.not_readable)
    read: list[int] = []
    blocks: list[Block] = []
    for call in case.calls:
        tool = call.tool or ("reply" if call.step == "refine" else "no tool call")
        retry = ", retry" if call.retry else ""
        blocks.append(
            Heading(4, f"Call {call.call_index + 1}: {_STEPS[call.step]}{retry} — {tool}")
        )
        if call.protocol_error is not None:
            blocks.append(Para(call.protocol_error, "Not accepted", warn=True))
        elif call.step == "refine" and call.hypothesis is not None:
            findings = tuple(_finding(tables, g) for g in call.hypothesis.findings)
            blocks.append(Items(findings, "Finding items chosen (the final answer is below)"))
        elif call.hypothesis is not None:
            blocks += _hypothesis_blocks(tables, call.hypothesis, raw)
        elif call.tool == "choose_documents":
            if not set(call.offered) <= offerable:
                _refuse(
                    f"{case.case_id}: call {call.call_index} offered documents the cached docket "
                    "cannot offer: the docket cache no longer matches the run"
                )
            try:
                choice = parse_call(
                    "choose_documents",
                    json.dumps(call.arguments),
                    tables,
                    call.offered,
                    already_read=read,
                    not_readable=not_readable,
                )
            except SchemaError as error:
                _refuse(
                    f"{case.case_id}: call {call.call_index}: the choice does not re-sort: {error}"
                )
            if not isinstance(choice, DocumentChoice):  # parse_call returns one for this tool
                raise TypeError(f"choose_documents parsed to {type(choice).__name__}")
            blocks += _choice_blocks(case, choice, call.offered)
            read += [d.document for d in choice.decisions if d.read]
        elif call.tool in CODING_TOOLS:
            blocks += _coding_blocks(case, call, reading)
        else:
            blocks.append(Para("accepted; the trail records nothing further for it"))
    return blocks, len(read)


def _outcome(result: CaseResult) -> str:
    if result.failure is not None or result.scores is None:
        return f"did not answer ({result.failure or 'no score'})"
    scores = result.scores
    return (
        f"answered; occurrence top-1 {'right' if scores.occurrence_top1 else 'wrong'}, top-3 "
        f"{'right' if scores.occurrence_top3 else 'wrong'}"
    )


def _final(result: CaseResult) -> Hypothesis | None:
    """The answer the case was scored on: its last checkpoint, when it answered."""
    if result.failure is not None or not result.steps:
        return None
    return result.steps[-1].hypothesis


# --- differences at a glance ---

# The checkpoints the glance reads, in order, with the names it shows them by.
_CHECKPOINTS: Final[tuple[tuple[str, str], ...]] = (
    ("h0", "H0"),
    ("h1", "H1"),
    ("h2", "H2"),
    ("answer", "Answer"),
)
_CHECKPOINT: Final = "checkpoint:"


def _checkpoint_hypotheses(result: CaseResult) -> dict[str, Hypothesis]:
    """A case's checkpoints by kind (``h0`` .. ``refine``); a kind recorded twice keeps its last."""
    return {
        step.tool.removeprefix(_CHECKPOINT): step.hypothesis
        for step in result.steps
        if step.tool.startswith(_CHECKPOINT)
    }


def _rank(hypothesis: Hypothesis, code: str) -> tuple[int, float] | None:
    """Where ``code`` is among a hypothesis's occurrence codes: its rank and its probability."""
    return next(
        (
            (rank, guess.probability)
            for rank, guess in enumerate(hypothesis.occurrence, start=1)
            if guess.phase + guess.event == code
        ),
        None,
    )


def _and(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _closeness(result: CaseResult, code: str) -> tuple[tuple[str, ...], str]:
    """Per checkpoint, where the loop held ``code``; then how close it came, in one line."""
    found = _checkpoint_hypotheses(result)
    rows: list[str] = []
    present: list[tuple[str, tuple[int, float] | None]] = []
    for kind, name in _CHECKPOINTS:
        hypothesis = found.get(kind)
        if hypothesis is None:
            rows.append(f"{name}: no such checkpoint in this case")
            continue
        place = _rank(hypothesis, code)
        present.append((name, place))
        rows.append(
            f"{name}: not among its codes"
            if place is None
            else f"{name}: rank {place[0]} (p {place[1]:.2f})"
        )
    if not present:
        return tuple(rows), "no checkpoint: the case made no hypothesis"
    held = [name for name, place in present if place is not None]
    last, place = present[-1]
    if place is not None and last == "Answer":
        summary = f"in the answer at rank {place[0]}"
    elif place is not None:
        summary = f"held at {_and(held)}; the case reached no later checkpoint"
    elif held:
        summary = f"held at {_and(held)}, then dropped"
    else:
        summary = "never in any hypothesis"
    if scored_answer(result) is None:
        summary += "; the case failed, so nothing was scored"
    return tuple(rows), summary


def _occurrences_named(arguments: BaseModel) -> tuple[str, ...]:
    """The occurrence codes a coding call's arguments name (``suggest_codes`` names none)."""
    if isinstance(arguments, DescribeCodes):
        return arguments.codes if arguments.kind == "occurrence" else ()
    if isinstance(arguments, OccurrenceUsage):
        return arguments.codes
    if isinstance(arguments, PastFindings):
        return (arguments.occurrence,)
    return ()


def _mentions(
    calls: Sequence[AgentCall], code: str, tables: CodeTables, stats: CodingStats
) -> tuple[str, str]:
    """The accepted coding calls whose arguments name ``code``; those whose text lists it."""
    named: list[str] = []
    listed: list[str] = []
    line = re.compile(rf"^{re.escape(code)}:", re.MULTILINE)
    for call in calls:
        if call.protocol_error is not None or call.tool not in CODING_TOOLS:
            continue
        where = f"{call.tool} (call {call.call_index + 1})"
        if code in _occurrences_named(_parsed(call, tables)):
            named.append(where)
        if line.search(rebuilt_tool_text(call, tables, stats)):
            listed.append(where)
    return "; ".join(named) or "none", "; ".join(listed) or "none"


def _finding_match(tables: CodeTables, code: str, guesses: Sequence[FindingGuess]) -> str:
    """How deep the loop's findings reach a flagged finding, as ``finding_depth`` counts it."""
    if any(g.item8 is not None and g.item8 + g.modifier == code for g in guesses):
        return "exact (item and modifier)"
    item = next((g for g in guesses if g.item8 == code[:8]), None)
    if item is not None:
        modifier = tables.modifiers.get(item.modifier, _UNKNOWN)
        return f"item only; the loop's modifier {item.modifier} [{modifier}]"
    category = next((g for g in guesses if g.category6 == code[:6]), None)
    if category is None:
        return "missed"
    if category.item8 is None:
        return "category only; the loop named no item"
    return (
        f"category only; the loop's item {category.item8} "
        f"{tables.items.get(category.item8, _UNKNOWN)}"
    )


def _finding_blocks(
    tables: CodeTables, result: CaseResult, answer: Hypothesis | None
) -> list[Block]:
    """The flagged findings at their level of match, and the loop's findings that match none."""
    flagged_label = "Findings flagged as cause, against the loop's final findings"
    unmatched_label = (
        "The loop's findings that match no NTSB finding (no category in common, flagged or not)"
    )
    if answer is None:
        none = ("not compared: the case did not answer",)
        return [Items(none, flagged_label), Items(none, unmatched_label)]
    flagged = tuple(
        f"{_verdict_finding(tables, code, cause=False)}: "
        f"{_finding_match(tables, code, answer.findings)}"
        for code in result.verdict_findings_in_cause
    )
    categories = {code[:6] for code in result.verdict_findings}
    unmatched = tuple(_finding(tables, g) for g in answer.findings if g.category6 not in categories)
    return [
        Items(flagged or ("none flagged",), flagged_label),
        Items(unmatched or ("none",), unmatched_label),
    ]


def _run_b_line(other: Run, case_id: str, tables: CodeTables) -> Para:
    """The other run's first code for the case and its kind, in one line."""
    label = f"Run b ({other.run_id}), defining event"
    result = other.cases.get(case_id)
    if result is None:
        return Para("the run holds no such case", label)
    kind = case_difference(result).kind
    answer = scored_answer(result)
    if answer is None:
        return Para(f"no answer ({result.failure or 'no score'}); kind: {kind}", label)
    return Para(f"first code {_guess(tables, answer.occurrence[0])}; kind: {kind}", label)


def glance_blocks(
    result: CaseResult,
    calls: Sequence[AgentCall],
    *,
    tables: CodeTables,
    stats: CodingStats,
    other: Run | None,
) -> list[Block]:
    """A case's differences at a glance, read before its trail.

    The defining event (the NTSB's first code against the loop's, with the kind and patterns
    ``scripts/miss_kinds.py`` gives them); how close the loop came to the NTSB's first code at
    each checkpoint, and which coding calls named it or listed it; the NTSB's occurrence codes
    marked against the loop's answer; the flagged findings at their level of match, and the
    loop's findings that match none; with ``other``, run b's first code and kind.

    Args:
        result: the case in this run; its verdict holds at least one occurrence code.
        calls: the case's calls in this run, in call order.
        tables: the code tables.
        stats: the statistics pool the run's tools counted in, to rebuild the tools' text.
        other: run b, or None.

    Returns:
        The block.
    """
    first = result.verdict_occurrence[0]
    difference = case_difference(result)
    answer = scored_answer(result)
    loop = "The loop's first code: " + (
        _guess(tables, answer.occurrence[0])
        if answer is not None
        else f"none; the case did not answer ({result.failure or 'no score'})"
    )
    rows, summary = _closeness(result, first)
    named, listed = _mentions(calls, first, tables, stats)
    codes = None if answer is None else answer_codes(answer)

    def mark(code: str) -> str:
        if codes is None:
            return "no answer to compare"
        return (
            f"in the answer at rank {codes.index(code) + 1}"
            if code in codes
            else "not in the answer"
        )

    blocks: list[Block] = [
        Heading(3, "Differences at a glance"),
        Items(
            (
                f"The NTSB's first code: {first}: {occurrence_label(tables, first)}",
                loop,
                f"Kind: {difference.kind}",
                f"Patterns: {'; '.join(difference.patterns) or 'none'}",
            ),
            "Defining event",
        ),
        Items(rows, f"How close the loop came to the NTSB's first code, {first}"),
        Para(summary, "In short"),
        Para(named, "Coding calls naming it"),
        Para(listed, "Coding tool results listing it (rebuilt)"),
        Items(
            tuple(
                f"{code}: {occurrence_label(tables, code)}: {mark(code)}"
                for code in result.verdict_occurrence
            ),
            "The NTSB's occurrence codes, in its order, against the loop's answer",
            ordered=True,
        ),
        *_finding_blocks(tables, result, answer),
    ]
    if other is not None:
        blocks.append(_run_b_line(other, result.case_id, tables))
    return blocks


def summary_blocks(results: Sequence[CaseResult]) -> list[Block]:
    """The kinds and the patterns among the cases shown, counted: no case named.

    Args:
        results: the cases shown, in this run.

    Returns:
        Two lists: every kind with its count, then every pattern with its count.
    """
    differences = [case_difference(r) for r in results]
    kinds = Counter(d.kind for d in differences)
    patterns = Counter(p for d in differences for p in d.patterns)
    return [
        Items(
            tuple(f"{kind}: {kinds[kind]}" for kind in KINDS),
            f"Kinds among the {len(results)} cases shown, run a (counts only)",
        ),
        Items(tuple(f"{p}: {patterns[p]}" for p in PATTERNS), "Patterns among them"),
    ]


def case_blocks(number: int, total: int, case: _Case, reading: _Reading) -> list[Block]:
    """One case's section: the header, the glance, the trail, the answer, the verdict, run b."""
    tables, raw, result = reading.tables, case.raw, case.result
    trail, read = _trail_blocks(case, reading)
    docket, view = case.docket, case.view
    titles = {entry.index: entry.title for entry in docket.listing.entries}
    blocks: list[Block] = [
        Heading(2, f"Case {number} of {total}: {case.case_id}", f"case-{number}"),
        Para(str(raw.get("eventDate"))[:10], "Event date"),
        Para("fatal" if result.fatal else "non-fatal", "Injury"),
        Para(
            f"{len(docket.listing.entries)} listed; {len(view.offered)} offered (readable); "
            f"{read} read",
            "Docket",
        ),
    ]
    if view.not_readable:
        blocks.append(
            Items(
                tuple(
                    f"[{f.index}] {_clean(titles[f.index], raw)} ({f.status})"
                    for f in view.not_readable
                ),
                "Listed, not readable",
            )
        )
    blocks += [
        Para(
            f"{_outcome(result)}; {len(case.calls)} model calls; ${result.cost_usd:.4f}",
            "This run",
        ),
        *glance_blocks(result, case.calls, tables=tables, stats=reading.stats, other=reading.other),
        Heading(3, "Trail, in call order"),
    ]
    blocks += trail or [Para("No model call was made for this case in this run.")]
    blocks.append(Heading(3, "Final answer"))
    final = _final(result)
    if final is None:
        blocks.append(Para(f"None: the case did not answer in this run ({result.failure})."))
    else:
        blocks += [
            Items(tuple(_guess(tables, g) for g in final.occurrence), "Occurrence codes", True),
            Items(tuple(_finding(tables, g) for g in final.findings) or ("none",), "Findings"),
            Para(
                f"{final.confidence:.2f}; abstain: {'yes' if final.abstain else 'no'}",
                "Confidence",
            ),
            Para(_clean(final.probable_cause, raw), "Working cause"),
        ]
    _, _, verdict = split_record({k: v for k, v in raw.items() if k != DOCKET_KEY})
    in_cause = set(verdict.finding_codes_in_cause)
    blocks += [
        Heading(3, "The NTSB's verdict, for comparison"),
        Items(
            tuple(f"{c}: {occurrence_label(tables, c)}" for c in verdict.occurrence_codes)
            or ("none",),
            "Occurrence codes, in the NTSB's order",
            ordered=True,
        ),
        Items(
            tuple(_verdict_finding(tables, c, cause=c in in_cause) for c in verdict.finding_codes)
            or ("none",),
            "Finding codes",
        ),
        Para(_clean(verdict.probable_cause or "(none)", raw), "Probable cause"),
    ]
    if reading.other is not None:
        blocks.append(_compare(reading.other, case.case_id, tables))
    return blocks


def _compare(other: Run, case_id: str, tables: CodeTables) -> Para:
    """The other run's final answer for the case, in one line."""
    result = other.cases.get(case_id)
    label = f"Run b ({other.run_id}), final answer"
    if result is None:
        return Para("the run holds no such case", label)
    final = _final(result)
    if final is None:
        return Para(f"none ({result.failure or 'no score'})", label)
    return Para(_answer_line(tables, final), label)


# --- rendering ---

_PAGE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
:root{color-scheme:light dark;--bg:#fbfbf9;--fg:#1c1c1a;--muted:#5d5d58;--rule:#d4d4cd;
--panel:#f1f1ec;--warn:#8a3b12}
@media (prefers-color-scheme: dark){:root{--bg:#171716;--fg:#e6e6e0;--muted:#a4a49d;
--rule:#3b3b37;--panel:#222220;--warn:#f0a070}}
body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;max-width:64rem;
margin:0 auto;padding:1.5rem 1rem 4rem}
h1{font-size:1.5rem}h2{font-size:1.3rem;border-top:3px solid var(--rule);padding-top:1rem;
margin-top:3rem}h3{font-size:1.1rem;margin-top:2rem}
h4{font-size:1rem;margin:1.5rem 0 .25rem;padding-left:.5rem;border-left:3px solid var(--rule)}
p,li{white-space:pre-line;overflow-wrap:anywhere}p.label{margin-bottom:.25rem;font-weight:600}
p.warn{color:var(--warn)}
details{margin:.5rem 0}summary{color:var(--muted);cursor:pointer}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel);padding:.75rem;
border-radius:4px;font:13px/1.45 ui-monospace,monospace}
a{color:inherit}
</style></head><body>
$body
</body></html>
"""
)


def _html(block: Block) -> str:
    esc = html.escape
    match block:
        case Heading(level, text, anchor):
            ident = f' id="{esc(anchor)}"' if anchor else ""
            return f"<h{level}{ident}>{esc(text)}</h{level}>"
        case Para(text, label, warn):
            css = ' class="warn"' if warn else ""
            lead = f"<b>{esc(label)}:</b> " if label else ""
            return f"<p{css}>{lead}{esc(text)}</p>"
        case Items(items, label, ordered):
            tag = "ol" if ordered else "ul"
            lead = f'<p class="label">{esc(label)}:</p>' if label else ""
            return f"{lead}<{tag}>{''.join(f'<li>{esc(i)}</li>' for i in items)}</{tag}>"
        case Pre(text, summary):
            return (
                f"<details open><summary>{esc(summary)}</summary><pre>{esc(text)}</pre></details>"
            )
        case Contents(entries):
            links = "".join(f'<li><a href="#{esc(a)}">{esc(t)}</a></li>' for a, t in entries)
            return f"<ol>{links}</ol>"


def render_html(title: str, blocks: Sequence[Block]) -> str:
    """The self-contained page: no script, no external file, readable light or dark."""
    return _PAGE.substitute(title=html.escape(title), body="\n".join(_html(b) for b in blocks))


def _fence(text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return fence


def _markdown(block: Block) -> str:
    match block:
        case Heading(level, text, _anchor):
            return f"{'#' * level} {text}"
        case Para(text, label, _warn):
            return f"**{label}:** {text}" if label else text
        case Items(items, label, ordered):
            lines = [
                f"{f'{n}.' if ordered else '-'} {item.replace(chr(10), ' ')}"
                for n, item in enumerate(items, start=1)
            ]
            return "\n".join([f"**{label}:**", "", *lines] if label else lines)
        case Pre(text, summary):
            fence = _fence(text)
            return f"{summary}:\n\n{fence}text\n{text}\n{fence}"
        case Contents(entries):
            return "\n".join(f"{n}. {t}" for n, (_a, t) in enumerate(entries, start=1))


def render_markdown(blocks: Sequence[Block]) -> str:
    """The same page as Markdown."""
    return "\n\n".join(_markdown(b) for b in blocks) + "\n"


# --- the whole page ---


@dataclass(frozen=True)
class _Request:
    """The arguments the page states at its top."""

    run: Run
    groups: Path
    split: str
    group: str
    pool: Sequence[str]
    fatal: Sequence[str]
    nonfatal: Sequence[str]
    seed: int


def _intro(request: _Request, reading: _Reading) -> list[Block]:
    run, pool = request.run, request.pool
    pool_fatal = sum(run.cases[i].fatal for i in pool)
    other = reading.other
    return [
        Heading(1, f"S3.1 trail pages: {request.split}, {request.group}"),
        Para(
            "A private reading aid for S3.1 Task 15, before a tuning round is registered: free, "
            "built from finished run folders, the processed records and the docket cache, with no "
            "model call. Never committed; no number here is a result."
        ),
        Para(f"{run.run_id} (arm C, {SAMPLE})", "Run"),
        *([Para(f"{other.run_id} (arm C, {SAMPLE})", "Run b")] if other is not None else []),
        Para(
            f"{request.split}, {request.group}, from {request.groups.name}: {len(pool)} cases "
            f"({pool_fatal} fatal, {len(pool) - pool_fatal} non-fatal). Shown: "
            f"{len(request.fatal)} fatal and {len(request.nonfatal)} non-fatal, drawn with seed "
            f"{request.seed} from the sorted ids.",
            "Group",
        ),
        *summary_blocks([run.cases[i] for i in (*request.fatal, *request.nonfatal)]),
        Para(
            "Each case opens with its differences at a glance: the NTSB's defining event against "
            "the loop's first code, with the kind and patterns scripts/miss_kinds.py gives them "
            "(as scripts/exploratory/s3_miss_kinds.py counts them over a whole group); how close "
            "the loop came to that code at each checkpoint; the NTSB's occurrence codes and its "
            "flagged findings against the loop's answer. Then its calls in order, then the final "
            "answer it was scored on, then the "
            "NTSB's verdict. The trail does not keep the text of a tool's result: each coding "
            "call's text below is rebuilt by re-running the tool on the recorded arguments, and "
            "says so. Document titles are shown for reading; the agent saw them only in the "
            "listing. Owner and operator names the record holds are replaced, as in the agent's "
            "own text."
        ),
        Contents(
            tuple(
                (f"case-{n}", f"{case_id} ({'fatal' if run.cases[case_id].fatal else 'non-fatal'})")
                for n, case_id in enumerate([*request.fatal, *request.nonfatal], start=1)
            )
        ),
    ]


def _offline() -> httpx.BaseTransport:
    """A transport that refuses every request, so a cache miss is loud and fetches nothing.

    It raises :class:`CacheMissError`, not an ``httpx`` error: the docket client turns a
    transport error into a ``DocketError``, which ``read_docket`` records as a document that
    failed to fetch, and the page would show a docket the run never saw.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise CacheMissError(request.url.path)

    return httpx.MockTransport(refuse)


def _docket(case_id: str, raw: Mapping[str, object], reader: Callable[[int], Docket]) -> Docket:
    mkey = raw.get("mKey")
    if not isinstance(mkey, int):
        _refuse(f"{case_id}: no mKey, so no docket")
    try:
        docket = reader(mkey)
    except CacheMissError:
        _refuse(
            f"{case_id}: its docket is not all in the docket cache; this page reads the cache "
            "only and fetches nothing"
        )
    if docket.mkey != mkey:
        _refuse(f"{case_id}: the docket read for it is docket {docket.mkey}, not its own {mkey}")
    return docket


def _cases(
    request: _Request,
    raws: Sequence[Mapping[str, object]],
    reader: Callable[[int], Docket],
) -> list[_Case]:
    """Each case to show, after the refusals that need its record and its docket."""
    run = request.run
    cases = []
    for case_id, raw in zip([*request.fatal, *request.nonfatal], raws, strict=True):
        if raw.get("ntsbNumber") != case_id:
            _refuse(f"{case_id}: the record read for it is {raw.get('ntsbNumber')}'s, not its own")
        if split_of(date.fromisoformat(str(raw.get("eventDate"))[:10])) is not Split.DEV:
            _refuse(f"{case_id}: its record is outside the development split")
        docket = _docket(case_id, raw, reader)
        cases.append(
            _Case(
                case_id,
                raw,
                run.cases[case_id],
                run.calls.get(case_id, ()),
                docket,
                docket_view(raw, docket),
            )
        )
    return cases


def page_blocks(request: _Request, reading: _Reading, cases: Sequence[_Case]) -> list[Block]:
    """The whole page: the introduction, then each case."""
    blocks = _intro(request, reading)
    for number, case in enumerate(cases, start=1):
        blocks += case_blocks(number, len(cases), case, reading)
    return blocks


def refuse_inside_repository(folder: Path) -> None:
    """Refuse an output folder inside the repository, unless under its git-ignored ``data/``.

    Args:
        folder: where the page's folder would be made.
    """
    resolved = folder.resolve()
    if resolved.is_relative_to(REPOSITORY) and not resolved.is_relative_to(REPOSITORY / "data"):
        _refuse(
            f"{folder} is inside the repository: the page holds case text and is never "
            "committed; write it under the runs folder"
        )


def _folder(base: Path, when: datetime) -> Path:
    folder = base / when.astimezone(UTC).strftime(_STAMP)
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        _refuse(f"{folder} already exists; run again in a second, rather than write over it")
    return folder


def _now() -> datetime:
    return datetime.now(UTC)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_trail_pages")
    parser.add_argument("--run", required=True, help="a finished dev-400 arm C run")
    parser.add_argument("--compare", default=None, help="another one, its answers in one line")
    parser.add_argument("--groups", required=True, type=Path, help="s3_case_groups' groups.json")
    parser.add_argument("--group", required=True, choices=list(GROUPS))
    parser.add_argument("--arm", required=True, choices=list(SPLITS), help="the groups' split")
    parser.add_argument("--fatal", required=True, type=int, help="fatal cases to draw")
    parser.add_argument("--nonfatal", required=True, type=int, help="non-fatal cases to draw")
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <runs>/" + FOLDER)
    args = parser.parse_args(argv)
    if args.fatal < 0 or args.nonfatal < 0 or args.fatal + args.nonfatal == 0:
        parser.error("--fatal and --nonfatal are counts, not both 0")
    return args


def main(
    argv: Sequence[str] | None = None,
    *,
    now: Callable[[], datetime] = _now,
    load_raws: Callable[[Sequence[str]], list[dict[str, object]]] | None = None,
    read_docket: Callable[[int], Docket] | None = None,
) -> int:
    """Write the page and its Markdown copy; print the folder, relative to where it was made.

    Args:
        argv: the command line.
        now: the clock, for the folder's name only.
        load_raws: the records of the cases named, in order; the processed file by default.
        read_docket: a case's docket by its key; the docket cache by default, offline.

    Returns:
        0.
    """
    args = _arguments(argv)
    if args.compare == args.run:
        _refuse("--compare names the run itself; compare two different runs")
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # damaged-PDF notices, not ours to read
    settings = Settings()
    base: Path = args.out_dir if args.out_dir is not None else settings.runs_dir / FOLDER
    refuse_inside_repository(base)
    run = load_run(settings.runs_dir, args.run)
    other = None if args.compare is None else load_run(settings.runs_dir, args.compare)
    split, group = SPLITS[args.arm], GROUPS[args.group]
    pool = read_group(args.groups, split=split, group=group, run_id=run.run_id)
    absent = [i for i in pool if i not in run.cases]
    if absent:
        _refuse(f"{run.run_id} does not hold {len(absent)} case(s) of the group")
    fatal, nonfatal = draw(
        pool,
        {i: run.cases[i].fatal for i in pool},
        per_fatal=args.fatal,
        per_nonfatal=args.nonfatal,
        seed=args.seed,
    )
    uncoded = [i for i in (*fatal, *nonfatal) if not run.cases[i].verdict_occurrence]
    if uncoded:
        _refuse(
            f"{len(uncoded)} drawn case(s) hold no NTSB occurrence code: no defining event to "
            "compare"
        )
    request = _Request(run, args.groups, split, group, pool, fatal, nonfatal, args.seed)
    reading = _Reading(load_tables(), load_stats("s3"), other)
    if load_raws is None:
        processed = settings.data_dir / "processed"
        raws = samples.load_cases(processed, [*fatal, *nonfatal])
    else:
        raws = load_raws([*fatal, *nonfatal])
    if read_docket is None:
        transport = _offline()
        with DocketClient(settings.docket_dir, transport=transport, max_attempts=1) as client:
            cases = _cases(request, raws, lambda mkey: manifest.read_docket(client, mkey))
    else:
        cases = _cases(request, raws, read_docket)
    blocks = page_blocks(request, reading, cases)
    folder = _folder(base, now())
    (folder / HTML_FILE).write_text(render_html(f"S3.1 trails: {split}, {group}", blocks))
    (folder / MARKDOWN_FILE).write_text(render_markdown(blocks))
    print(folder.relative_to(base.parent).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
