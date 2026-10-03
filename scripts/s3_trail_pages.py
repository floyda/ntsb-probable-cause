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

The selection
    The chosen group's case ids, then, in this order:

    1. Exclusions. Each ``--exclude-from`` names an earlier page's folder (its ``cases.json``)
       or that manifest itself; every case id it lists is left out. Repeatable.
    2. A pattern. With ``--pattern NAME``, only the cases whose patterns in run a (``--run``),
       as ``scripts/miss_kinds.py`` classifies them, include that pattern are kept. ``NAME`` is
       the classifier's own pattern name in lower case, each run of other characters made one
       underscore (``generic consequence`` is ``generic_consequence``; ``PATTERN_OPTIONS``).
    3. The cases left are the eligible ones, split into fatal and non-fatal by the run's own
       ``cases.jsonl``. Then ``--fatal`` fatal cases and ``--nonfatal`` non-fatal ones are
       chosen, and each slice is shown sorted, fatal first. A slice smaller than asked is shown
       whole.

    Without ``--spread-by``, the choice is a draw: from the sorted eligible ids, ``--fatal``
    cases from the fatal ones and then ``--nonfatal`` from the rest, with one
    ``random.Random(--seed)``. With no exclusion and no pattern, this is the draw the page made
    before selections existed, so the same arguments still draw the same cases.

    With ``--spread-by ntsb_first_event``, the choice is spread over the NTSB's first events
    (the event, the last three digits, of the NTSB's first occurrence code):

    1. The eligible cases are grouped by that event. In each group the case ids are sorted and
       split into fatal and non-fatal; both lists are shuffled, fatal first, by one generator
       for the group, ``random.Random(f"{seed}:{event}")`` (a string seed, so the same in every
       process), and a case is always taken from the front of its list.
    2. The groups are put in order once: the most eligible cases first, ties by event code.
    3. Rounds follow. Each round visits every group in that order and takes at most one case
       from it: of the kind whose turn it is if the group still holds one and that kind's count
       is not yet reached, else of the other kind on the same terms, else none. The turn starts
       at fatal and, after each case taken, passes to the kind not taken. The rounds stop when a
       whole round takes nothing: both counts are reached, or no eligible case is left.

    So every event that can still give a case gives one before any event gives a second, the
    largest events first, and fatal and non-fatal cases alternate wherever a group holds both.
    The same arguments always choose the same cases and write the same page.

What the page shows, at its top
    The runs; the group; the selection (the exclusions and how many cases they left out, the
    pattern and what it means, how many cases were eligible, fatal and non-fatal, and how the
    shown ones were chosen; with a spread, each first event among the eligible cases, in the
    order the spread visits them, with how many were eligible and shown); then the kinds and the
    patterns among the cases shown (run a), counted, as ``scripts/miss_kinds.py`` classifies
    them; then a legend of the marks.

The marks
    Wherever the page lists an occurrence code of the loop (every checkpoint's hypothesis: H0,
    H1, H2, a retry, the answer; the final answer; the loop's first code, each checkpoint's row
    and run b's first code in "Differences at a glance") or a finding, a mark leads the line: a
    colour, and words that read without it. An occurrence code of the loop at rank r is a match
    (green, "✓ match") when the NTSB's code at rank r is the same code; in the wrong place
    (amber, "↕ wrong place: the NTSB's rank k") when the NTSB lists it at another rank k; and no
    match (red, "✗ not in the NTSB's") when the NTSB does not list it. The NTSB's own codes,
    against the loop's answer, are marked the same way round ("the loop's rank k", "not in the
    loop's"); so is each checkpoint's row for the NTSB's first code. A finding of the loop is
    marked at the deepest level it reaches against any NTSB finding: exact, item and modifier
    (green, "✓ exact"); item only or category only (amber, "≈ partial: item only", "≈ partial:
    category only"); none (red, "✗ matches no NTSB finding"); "(cause)" follows when an NTSB
    finding it reaches at that level is flagged as in the probable cause. Each finding the NTSB
    flags as cause is marked by how deep the loop's findings reach it, the same levels, and
    "✗ missed" for none. The NTSB's verdict section and the coding calls' arguments carry no
    mark. Colours are tokens, on ``:root`` for light and redefined for dark both under
    ``prefers-color-scheme: dark`` and under ``data-theme="dark"``; the Markdown copy carries
    the words only.

The manifest
    Beside the page, ``cases.json`` names the case ids shown (in page order), the runs, the
    groups file, the split and group, the seed, the counts asked for, and the selection
    (exclusion manifests read, cases they left out, pattern, spread, how many cases the group
    held and how many were eligible). A later page reads it through ``--exclude-from``.

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
    asked for; an ``--exclude-from`` with no manifest, or naming a file that is not one this
    script wrote; a group case the run does not hold; with ``--pattern`` or ``--spread-by``, a
    case left after the exclusions whose verdict holds no occurrence code (no pattern or first
    event to select by); no eligible case; a drawn case whose verdict holds no occurrence code
    (no defining event to compare). Then, per case: a record outside the
    development split or for another case; a docket not wholly in the cache (nothing is
    fetched); a docket whose key is not the record's; a read choice whose offer the cached
    docket could not have made. A second page in the same second is refused rather than written
    over.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.s3_trail_pages --run RUN [--compare RUN] \
        --groups PATH --group always_wrong --arm C --fatal N --nonfatal N --seed S \
        [--pattern NAME] [--spread-by ntsb_first_event] [--exclude-from PATH ...] \
        [--out-dir DIR]

    Prints one line: the page's folder, relative to the folder it was made in (the runs folder
    by default). The folder holds ``trails.html``, its Markdown copy ``trails.md``, and the
    manifest ``cases.json``.
"""

import argparse
import html
import json
import logging
import random
import re
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from string import Template
from typing import Final, Literal, NoReturn, cast

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
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, load_stats
from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split, split_of
from scripts.miss_kinds import (
    KINDS,
    PATTERN_MEANINGS,
    PATTERNS,
    Pattern,
    answer_codes,
    case_difference,
    scored_answer,
)

SAMPLE: Final = "dev-400"
ARM: Final = "C"
FOLDER: Final = "s3-trail-pages"
HTML_FILE: Final = "trails.html"
MARKDOWN_FILE: Final = "trails.md"
# The manifest beside the page, and the mark that says this script wrote it.
MANIFEST_FILE: Final = "cases.json"
MANIFEST_KIND: Final = "s3_trail_pages"
SPREAD_FIRST_EVENT: Final = "ntsb_first_event"


def _option(name: str) -> str:
    """A classifier name as a command-line word: lower case, other characters one underscore."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ``--pattern``'s words, each naming one of the classifier's patterns.
PATTERN_OPTIONS: Final[Mapping[str, Pattern]] = {_option(p): p for p in PATTERNS}
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


type State = Literal["match", "near", "miss"]


@dataclass(frozen=True)
class Mark:
    """A match state: green, amber or red in HTML, and always words that read without colour."""

    state: State
    text: str


MATCH: Final = Mark("match", "✓ match")


@dataclass(frozen=True)
class Marked:
    """A list item led by its mark."""

    text: str
    mark: Mark


type Line = str | Marked


@dataclass(frozen=True)
class Para:
    """A paragraph, led by a bold label when it has one; ``warn`` marks a call not accepted.

    ``mark``, when given, leads the text.
    """

    text: str
    label: str = ""
    warn: bool = False
    mark: Mark | None = None


@dataclass(frozen=True)
class Items:
    """A list, led by a label when it has one; an item may be led by its mark."""

    items: tuple[Line, ...]
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


def _event_order(events: Mapping[str, str], ids: Collection[str]) -> list[str]:
    """The events of ``ids``, the most cases first, ties by event code."""
    counts = Counter(events[i] for i in set(ids))
    return sorted(counts, key=lambda event: (-counts[event], event))


def spread(  # noqa: PLR0913 -- the draw's arguments, and the event each case is grouped by
    ids: Sequence[str],
    fatal: Mapping[str, bool],
    events: Mapping[str, str],
    *,
    per_fatal: int,
    per_nonfatal: int,
    seed: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The fatal and non-fatal cases to show, spread over the events, each slice sorted.

    The module docstring's "The selection" states the rule: cases grouped by event; in each
    group, the sorted fatal and then non-fatal ids shuffled by ``random.Random(f"{seed}:
    {event}")``; groups visited the most cases first (ties by event code), round after round,
    at most one case per group per visit, of the kind whose turn it is where the group holds
    one and that kind's count is not reached, else of the other; the turn starts at fatal and
    passes to the kind not taken; the rounds stop when one takes nothing.

    Args:
        ids: the eligible case ids, in any order.
        fatal: whether each case is fatal.
        events: each case's group: the NTSB's first event.
        per_fatal: how many fatal cases to choose; fewer are taken whole.
        per_nonfatal: how many non-fatal cases to choose, likewise.
        seed: the seed each group's generator is made from, with the group's event.

    Returns:
        The fatal cases, then the non-fatal ones.
    """
    queues: dict[str, dict[bool, list[str]]] = {}
    order = _event_order(events, ids)
    for event in order:
        rng = random.Random(f"{seed}:{event}")  # noqa: S311 -- reproducible sampling
        members = sorted({i for i in ids if events[i] == event})
        queues[event] = {}
        for kind in (True, False):
            queue = [i for i in members if fatal[i] is kind]
            rng.shuffle(queue)
            queues[event][kind] = queue
    wanted = {True: per_fatal, False: per_nonfatal}
    chosen: dict[bool, list[str]] = {True: [], False: []}
    turn, took = True, True
    while took:
        took = False
        for event in order:
            for kind in (turn, not turn):
                queue = queues[event][kind]
                if queue and len(chosen[kind]) < wanted[kind]:
                    chosen[kind].append(queue.pop(0))
                    turn, took = not kind, True
                    break
    return tuple(sorted(chosen[True])), tuple(sorted(chosen[False]))


def read_manifest(path: Path) -> tuple[Path, frozenset[str]]:
    """The case ids an earlier page showed, from its folder or from its manifest.

    Args:
        path: a page folder this script wrote, or its ``cases.json``.

    Returns:
        The manifest read, and the case ids it lists.
    """
    file = path / MANIFEST_FILE if path.is_dir() else path
    if not file.is_file():
        _refuse(
            f"no page manifest at {file}: --exclude-from takes a page folder this script wrote, "
            f"or its {MANIFEST_FILE}"
        )
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _refuse(f"{file} is not JSON")
    ids = data.get("cases") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("manifest") != MANIFEST_KIND
        or not isinstance(ids, list)
        or not all(isinstance(i, str) for i in ids)
    ):
        _refuse(f"{file} is not a trail page manifest (scripts/s3_trail_pages.py)")
    return file, frozenset(cast(list[str], ids))


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


# --- marks ---

_NTSB: Final = "the NTSB's"
_LOOP: Final = "the loop's"
# A finding's levels of match, deepest first, as ``scoring.misses.finding_depth`` counts them.
_EXACT, _ITEM, _CATEGORY = 0, 1, 2
_DEPTHS: Final[Mapping[int, str]] = {_ITEM: "item only", _CATEGORY: "category only"}


def occurrence_mark(code: str, rank: int, reference: Sequence[str], *, whose: str) -> Mark:
    """How an occurrence code at ``rank`` of one list stands in the other list.

    Args:
        code: the six-digit code.
        rank: its rank in its own list, from 1.
        reference: the other list, in its order.
        whose: the other list's owner as the mark names it, ``"the NTSB's"`` or ``"the loop's"``.

    Returns:
        A match when the other list holds the code at the same rank; in the wrong place (its
        rank there named) when at another rank; no match when not at all.
    """
    if rank <= len(reference) and reference[rank - 1] == code:
        return MATCH
    if code in reference:
        return Mark("near", f"↕ wrong place: {whose} rank {reference.index(code) + 1}")
    return Mark("miss", f"✗ not in {whose}")


def _depth(guess: FindingGuess, code: str) -> int | None:
    """How deep a finding of the loop reaches one NTSB finding (ten digits), or None."""
    if guess.item8 is not None and guess.item8 + guess.modifier == code:
        return _EXACT
    if guess.item8 is not None and guess.item8 == code[:8]:
        return _ITEM
    return _CATEGORY if guess.category6 == code[:6] else None


def finding_mark(guess: FindingGuess, findings: Sequence[str], in_cause: Collection[str]) -> Mark:
    """A finding of the loop's, at the deepest level it reaches against any NTSB finding.

    Args:
        guess: the loop's finding.
        findings: the NTSB's findings, ten digits each.
        in_cause: those flagged as in the probable cause.

    Returns:
        A match when exact (item and modifier); partial, naming the level, when item only or
        category only; no match when it reaches none. "(cause)" follows when an NTSB finding
        it reaches at that level is flagged as cause.
    """
    reached = [(depth, code) for code in findings if (depth := _depth(guess, code)) is not None]
    if not reached:
        return Mark("miss", "✗ matches no NTSB finding")
    best = min(depth for depth, _ in reached)
    cause = " (cause)" if any(d == best and c in in_cause for d, c in reached) else ""
    if best == _EXACT:
        return Mark("match", f"✓ exact{cause}")
    return Mark("near", f"≈ partial: {_DEPTHS[best]}{cause}")


def occurrence_lines(
    tables: CodeTables, guesses: Sequence[OccurrenceGuess], ntsb: Sequence[str]
) -> tuple[Marked, ...]:
    """A hypothesis's occurrence codes with labels, each marked against the NTSB's sequence."""
    return tuple(
        Marked(_guess(tables, g), occurrence_mark(g.phase + g.event, rank, ntsb, whose=_NTSB))
        for rank, g in enumerate(guesses, start=1)
    )


def _findings(
    tables: CodeTables, guesses: Sequence[FindingGuess], result: CaseResult
) -> tuple[Line, ...]:
    """A hypothesis's findings with labels, each marked against the NTSB's; or "none"."""
    findings, in_cause = result.verdict_findings, set(result.verdict_findings_in_cause)
    marked = tuple(
        Marked(_finding(tables, g), finding_mark(g, findings, in_cause)) for g in guesses
    )
    return marked or ("none",)


def legend_blocks() -> list[Block]:
    """The marks, each with its colour and its words, as the page's top explains them.

    Returns:
        One list: the three states, then what "(cause)" adds.
    """
    return [
        Items(
            (
                Marked(
                    "the same occurrence code at the same rank in the loop's list and the "
                    "NTSB's; a finding matched exactly, item and modifier (✓ exact)",
                    MATCH,
                ),
                Marked(
                    "an occurrence code in the other list at another rank, which the mark "
                    "names; a finding matched at item or category level only, which the mark "
                    "says",
                    Mark("near", "↕ wrong place / ≈ partial"),
                ),
                Marked(
                    "an occurrence code not in the other list; a flagged finding the loop "
                    "missed, or a finding of the loop's that matches no NTSB finding",
                    Mark("miss", "✗ no match"),
                ),
                "(cause) after a finding's mark: an NTSB finding it matches at that level is "
                "flagged as in the probable cause",
                "Scoring reads only the NTSB's first code: a green mark below rank 1 means the "
                "same code at the same rank, not that the case was scored right; each case's "
                '"This run" line gives its score',
            ),
            "Marks: green, amber and red, each with words that read without colour",
        )
    ]


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


def clean(text: str, raw: Mapping[str, object]) -> str:
    """The attach step's replacements: an amateur-built make and model, owner/operator names."""
    text, _ = amateur_built_replace(text, raw)
    text, _ = redact_known_names(text, raw)
    return text


def _hypothesis_blocks(tables: CodeTables, hypothesis: Hypothesis, case: _Case) -> list[Block]:
    raw, result = case.raw, case.result
    return [
        Items(
            occurrence_lines(tables, hypothesis.occurrence, result.verdict_occurrence),
            label="Occurrence codes",
            ordered=True,
        ),
        Items(_findings(tables, hypothesis.findings, result), "Findings"),
        Para(
            f"{hypothesis.confidence:.2f}; abstain: {'yes' if hypothesis.abstain else 'no'}",
            "Confidence",
        ),
        Para(clean(hypothesis.evidence_narrative, raw), "Evidence narrative (the agent's own)"),
        Para(clean(hypothesis.probable_cause, raw), "Working cause"),
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
            f"[{index}] {clean(titles[index], raw)} ({_pages(docket.record(index).pages)}): "
            f"{'read' if decision.read else 'skip'}. Expected: "
            f"{clean(decision.expected_effect, raw)}"
        )
    blocks: list[Block] = [
        Para(clean(choice.arguments.reason, raw), "Reason for the choice"),
        Items(tuple(lines), "Documents on offer, in offer order"),
    ]
    if choice.extras:
        answers = extras_lines(choice.extras).splitlines()
        extras = []
        for extra, answer in zip(choice.extras, answers, strict=True):
            asked = next(d for d in choice.arguments.decisions if d.document == extra.document)
            extras.append(
                f"[{extra.document}] asked to {'read' if asked.read else 'skip'}; expected: "
                f"{clean(asked.expected_effect, raw)}. Answered: {answer}"
            )
        blocks.append(Items(tuple(extras), "Decisions on documents not on offer (never acted on)"))
    return blocks


def _coding_blocks(case: _Case, call: AgentCall, reading: _Reading) -> list[Block]:
    raw, tables = case.raw, reading.tables
    text = rebuilt_tool_text(call, tables, reading.stats)
    blocks: list[Block] = [
        Items(_argument_lines(tables, _parsed(call, tables)), "Arguments"),
        Para(clean(str(call.arguments.get("reason", "")), raw), "Reason"),
        Para(clean(str(call.arguments.get("expected_effect", "")), raw), "Expected effect"),
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
    tables = reading.tables
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
            findings = _findings(tables, call.hypothesis.findings, case.result)
            blocks.append(Items(findings, "Finding items chosen (the final answer is below)"))
        elif call.hypothesis is not None:
            blocks += _hypothesis_blocks(tables, call.hypothesis, case)
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


def _closeness(result: CaseResult, code: str) -> tuple[tuple[Line, ...], str]:
    """Per checkpoint, where the loop held ``code``, marked; then how close it came, in one line."""
    found = _checkpoint_hypotheses(result)
    rows: list[Line] = []
    present: list[tuple[str, tuple[int, float] | None]] = []
    for kind, name in _CHECKPOINTS:
        hypothesis = found.get(kind)
        if hypothesis is None:
            rows.append(f"{name}: no such checkpoint in this case")
            continue
        place = _rank(hypothesis, code)
        present.append((name, place))
        row = (
            f"{name}: not among its codes"
            if place is None
            else f"{name}: rank {place[0]} (p {place[1]:.2f})"
        )
        rows.append(Marked(row, occurrence_mark(code, 1, answer_codes(hypothesis), whose=_LOOP)))
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


def _finding_match(tables: CodeTables, code: str, guesses: Sequence[FindingGuess]) -> Marked:
    """How deep the loop's findings reach a flagged finding, as ``finding_depth`` counts it."""
    text = _verdict_finding(tables, code, cause=False)
    if any(_depth(g, code) == _EXACT for g in guesses):
        return Marked(f"{text}: exact (item and modifier)", Mark("match", "✓ exact"))
    item = next((g for g in guesses if _depth(g, code) == _ITEM), None)
    if item is not None:
        modifier = tables.modifiers.get(item.modifier, _UNKNOWN)
        return Marked(
            f"{text}: item only; the loop's modifier {item.modifier} [{modifier}]",
            Mark("near", "≈ partial: item only"),
        )
    category = next((g for g in guesses if _depth(g, code) == _CATEGORY), None)
    if category is None:
        return Marked(f"{text}: missed", Mark("miss", "✗ missed"))
    partial = Mark("near", "≈ partial: category only")
    if category.item8 is None:
        return Marked(f"{text}: category only; the loop named no item", partial)
    return Marked(
        f"{text}: category only; the loop's item {category.item8} "
        f"{tables.items.get(category.item8, _UNKNOWN)}",
        partial,
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
        _finding_match(tables, code, answer.findings) for code in result.verdict_findings_in_cause
    )
    categories = {code[:6] for code in result.verdict_findings}
    unmatched = tuple(
        Marked(_finding(tables, g), Mark("miss", "✗ matches no NTSB finding"))
        for g in answer.findings
        if g.category6 not in categories
    )
    return [
        Items(flagged or ("none flagged",), flagged_label),
        Items(unmatched or ("none",), unmatched_label),
    ]


def _run_b_line(other: Run, case_id: str, tables: CodeTables, ntsb: Sequence[str]) -> Para:
    """The other run's first code for the case and its kind, in one line, its code marked."""
    label = f"Run b ({other.run_id}), defining event"
    result = other.cases.get(case_id)
    if result is None:
        return Para("the run holds no such case", label)
    kind = case_difference(result).kind
    answer = scored_answer(result)
    if answer is None:
        return Para(f"no answer ({result.failure or 'no score'}); kind: {kind}", label)
    first = answer.occurrence[0]
    return Para(
        f"first code {_guess(tables, first)}; kind: {kind}",
        label,
        mark=occurrence_mark(first.phase + first.event, 1, ntsb, whose=_NTSB),
    )


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
    loop's findings that match none; with ``other``, run b's first code and kind. Each code or
    finding compared carries its mark (``occurrence_mark``; a finding's level), run b's first
    code against this run's NTSB sequence.

    Args:
        result: the case in this run; its verdict holds at least one occurrence code.
        calls: the case's calls in this run, in call order.
        tables: the code tables.
        stats: the statistics pool the run's tools counted in, to rebuild the tools' text.
        other: run b, or None.

    Returns:
        The block.
    """
    ntsb = result.verdict_occurrence
    first = ntsb[0]
    difference = case_difference(result)
    answer = scored_answer(result)
    loop: Line
    if answer is None:
        loop = (
            f"The loop's first code: none; the case did not answer ({result.failure or 'no score'})"
        )
    else:
        top = answer.occurrence[0]
        loop = Marked(
            f"The loop's first code: {_guess(tables, top)}",
            occurrence_mark(top.phase + top.event, 1, ntsb, whose=_NTSB),
        )
    rows, summary = _closeness(result, first)
    named, listed = _mentions(calls, first, tables, stats)
    codes = None if answer is None else answer_codes(answer)

    def against(rank: int, code: str) -> Line:
        text = f"{code}: {occurrence_label(tables, code)}"
        if codes is None:
            return f"{text}: no answer to compare"
        where = (
            f"in the answer at rank {codes.index(code) + 1}"
            if code in codes
            else ("not in the answer")
        )
        return Marked(f"{text}: {where}", occurrence_mark(code, rank, codes, whose=_LOOP))

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
            tuple(against(rank, code) for rank, code in enumerate(ntsb, start=1)),
            "The NTSB's occurrence codes, in its order, against the loop's answer",
            ordered=True,
        ),
        *_finding_blocks(tables, result, answer),
    ]
    if other is not None:
        blocks.append(_run_b_line(other, result.case_id, tables, ntsb))
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


def ntsb_verdict(raw: Mapping[str, object]) -> Verdict:
    """The NTSB's verdict for a case, from ``split_record`` over its record less any docket."""
    _, _, verdict = split_record({k: v for k, v in raw.items() if k != DOCKET_KEY})
    return verdict


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
                    f"[{f.index}] {clean(titles[f.index], raw)} ({f.status})"
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
            Items(
                occurrence_lines(tables, final.occurrence, result.verdict_occurrence),
                "Occurrence codes",
                ordered=True,
            ),
            Items(_findings(tables, final.findings, result), "Findings"),
            Para(
                f"{final.confidence:.2f}; abstain: {'yes' if final.abstain else 'no'}",
                "Confidence",
            ),
            Para(clean(final.probable_cause, raw), "Working cause"),
        ]
    verdict = ntsb_verdict(raw)
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
        Para(clean(verdict.probable_cause or "(none)", raw), "Probable cause"),
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

# Every colour is a token: defined on bare ``:root`` for light, then redefined for dark under
# the system's dark preference (unless the page is set light) and again when set dark. Each mark
# is a tinted chip with a strong text colour, readable in both.
_LIGHT: Final[Mapping[str, str]] = {
    "bg": "#fbfbf9",
    "fg": "#1c1c1a",
    "muted": "#5d5d58",
    "rule": "#d4d4cd",
    "panel": "#f1f1ec",
    "warn": "#8a3b12",
    "match-bg": "#ddf0de",
    "match-fg": "#185c27",
    "near-bg": "#fbebcb",
    "near-fg": "#7a4700",
    "miss-bg": "#f9dede",
    "miss-fg": "#8e1c1c",
}
_DARK: Final[Mapping[str, str]] = {
    "bg": "#171716",
    "fg": "#e6e6e0",
    "muted": "#a4a49d",
    "rule": "#3b3b37",
    "panel": "#222220",
    "warn": "#f0a070",
    "match-bg": "#173a20",
    "match-fg": "#a6e3ae",
    "near-bg": "#3d2c0c",
    "near-fg": "#f2c66d",
    "miss-bg": "#4a1c1c",
    "miss-fg": "#f5a8a8",
}


def _tokens(values: Mapping[str, str]) -> str:
    return ";".join(f"--{name}:{value}" for name, value in values.items())


_THEME: Final = (
    f":root{{color-scheme:light dark;{_tokens(_LIGHT)}}}\n"
    "@media (prefers-color-scheme: dark){"
    f':root:not([data-theme="light"]){{{_tokens(_DARK)}}}}}\n'
    f':root[data-theme="dark"]{{{_tokens(_DARK)}}}'
)
_STATES: Final[tuple[State, ...]] = ("match", "near", "miss")
_CHIPS: Final = "".join(
    f".mk-{state}{{background:var(--{state}-bg);color:var(--{state}-fg)}}" for state in _STATES
)

_PAGE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
$theme
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
.mk{display:inline-block;padding:0 .35em;border:1px solid currentColor;border-radius:4px;
font-size:.85em;font-weight:600;line-height:1.45;white-space:nowrap}
$chips
</style></head><body>
$body
</body></html>
"""
)


def chip_html(mark: Mark | None) -> str:
    """A mark as a coloured chip with its words, followed by a space; nothing for no mark."""
    if mark is None:
        return ""
    return f'<span class="mk mk-{mark.state}">{html.escape(mark.text)}</span> '


def _line_html(line: Line) -> str:
    if isinstance(line, Marked):
        return chip_html(line.mark) + html.escape(line.text)
    return html.escape(line)


def block_html(block: Block) -> str:
    """One block as HTML, every piece of its text escaped."""
    esc = html.escape
    match block:
        case Heading(level, text, anchor):
            ident = f' id="{esc(anchor)}"' if anchor else ""
            return f"<h{level}{ident}>{esc(text)}</h{level}>"
        case Para(text, label, warn, mark):
            css = ' class="warn"' if warn else ""
            lead = f"<b>{esc(label)}:</b> " if label else ""
            return f"<p{css}>{lead}{chip_html(mark)}{esc(text)}</p>"
        case Items(items, label, ordered):
            tag = "ol" if ordered else "ul"
            lead = f'<p class="label">{esc(label)}:</p>' if label else ""
            return f"{lead}<{tag}>{''.join(f'<li>{_line_html(i)}</li>' for i in items)}</{tag}>"
        case Pre(text, summary):
            return (
                f"<details open><summary>{esc(summary)}</summary><pre>{esc(text)}</pre></details>"
            )
        case Contents(entries):
            links = "".join(f'<li><a href="#{esc(a)}">{esc(t)}</a></li>' for a, t in entries)
            return f"<ol>{links}</ol>"


def page_html(title: str, body: str) -> str:
    """The self-contained page around ``body``: no script, no external file, light or dark.

    Args:
        title: the page's title, escaped here.
        body: the page's body, already HTML, every piece of text in it already escaped.

    Returns:
        The page.
    """
    return _PAGE.substitute(title=html.escape(title), theme=_THEME, chips=_CHIPS, body=body)


def render_html(title: str, blocks: Sequence[Block]) -> str:
    """The self-contained page: no script, no external file, readable light or dark."""
    return page_html(title, "\n".join(block_html(b) for b in blocks))


def _fence(text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return fence


def _words(mark: Mark | None) -> str:
    """A mark in the Markdown copy: its words only, in brackets, followed by a space."""
    return "" if mark is None else f"[{mark.text}] "


def _line_markdown(line: Line) -> str:
    if isinstance(line, Marked):
        return _words(line.mark) + line.text.replace("\n", " ")
    return line.replace("\n", " ")


def _markdown(block: Block) -> str:
    match block:
        case Heading(level, text, _anchor):
            return f"{'#' * level} {text}"
        case Para(text, label, _warn, mark):
            text = _words(mark) + text
            return f"**{label}:** {text}" if label else text
        case Items(items, label, ordered):
            lines = [
                f"{f'{n}.' if ordered else '-'} {_line_markdown(item)}"
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
class Selection:
    """How the cases shown were chosen from the group: the page's top and its manifest say so."""

    exclude_from: tuple[Path, ...]
    excluded: int
    pattern: Pattern | None
    spread: str | None
    eligible: tuple[str, ...]


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
    asked: tuple[int, int]
    selection: Selection


def first_event(result: CaseResult) -> str:
    """The NTSB's first event: the last three digits of its first occurrence code."""
    return result.verdict_occurrence[0][3:]


def _count(run: Run, ids: Sequence[str], noun: str = "cases") -> str:
    fatal = sum(run.cases[i].fatal for i in ids)
    return f"{len(ids)} {noun} ({fatal} fatal, {len(ids) - fatal} non-fatal)"


def _selection_blocks(request: _Request, tables: CodeTables) -> list[Block]:
    """The exclusions, the pattern, the eligible cases, how the shown ones were chosen."""
    run, selection = request.run, request.selection
    names = "; ".join(f"{p.parent.name}/{p.name}" for p in selection.exclude_from)
    pattern = selection.pattern
    chosen = (
        f"drawn with seed {request.seed} from the sorted eligible ids"
        if selection.spread is None
        else (
            f"spread by the NTSB's first event with seed {request.seed}: the eligible cases "
            "grouped by the event of the NTSB's first occurrence code; the groups visited the "
            "most cases first, round after round, one case per group per visit, fatal and "
            "non-fatal in turn where a group holds both; each group's cases shuffled by its own "
            f'generator, seeded "{request.seed}:<event>"'
        )
    )
    blocks: list[Block] = [
        Items(
            (
                f"Excluded: {selection.excluded} of the group's cases, shown on earlier pages "
                f"({names})"
                if selection.exclude_from
                else "Excluded: none",
                "Pattern: none asked"
                if pattern is None
                else f"Pattern: {pattern} (--pattern {_option(pattern)}), in run a: "
                f"{PATTERN_MEANINGS[pattern]}",
                f"Eligible: {_count(run, selection.eligible)}",
                f"Shown: {len(request.fatal)} fatal and {len(request.nonfatal)} non-fatal, "
                f"{chosen}",
            ),
            "Selection",
        )
    ]
    if selection.spread is not None:
        events = {i: first_event(run.cases[i]) for i in selection.eligible}
        shown = Counter(events[i] for i in (*request.fatal, *request.nonfatal))
        lines = []
        for event in _event_order(events, selection.eligible):
            ids = [i for i in selection.eligible if events[i] == event]
            lines.append(
                f"{event}: {tables.events.get(event, _UNKNOWN)}: "
                f"{_count(run, ids, 'eligible')}, {shown[event]} shown"
            )
        blocks.append(
            Items(
                tuple(lines),
                "The NTSB's first events among the eligible cases, in the order the spread "
                "visits them",
            )
        )
    return blocks


def _intro(request: _Request, reading: _Reading) -> list[Block]:
    run, pool = request.run, request.pool
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
            f"{request.split}, {request.group}, from {request.groups.name}: {_count(run, pool)}.",
            "Group",
        ),
        *_selection_blocks(request, reading.tables),
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
        *legend_blocks(),
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


def check_record(case_id: str, raw: Mapping[str, object]) -> None:
    """Refuse a record read for ``case_id`` that is another case's, or outside development."""
    if raw.get("ntsbNumber") != case_id:
        _refuse(f"{case_id}: the record read for it is {raw.get('ntsbNumber')}'s, not its own")
    if split_of(date.fromisoformat(str(raw.get("eventDate"))[:10])) is not Split.DEV:
        _refuse(f"{case_id}: its record is outside the development split")


def _cases(
    request: _Request,
    raws: Sequence[Mapping[str, object]],
    reader: Callable[[int], Docket],
) -> list[_Case]:
    """Each case to show, after the refusals that need its record and its docket."""
    run = request.run
    cases = []
    for case_id, raw in zip([*request.fatal, *request.nonfatal], raws, strict=True):
        check_record(case_id, raw)
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


def select(
    run: Run,
    pool: Sequence[str],
    manifests: Sequence[tuple[Path, frozenset[str]]],
    *,
    pattern: Pattern | None,
    spread_by: str | None,
) -> Selection:
    """The group's eligible cases: the exclusions left out, then the pattern's cases kept.

    Args:
        run: run a; its cases give each case's patterns and first event.
        pool: the group's case ids, sorted; every one is in the run.
        manifests: each ``--exclude-from`` read: the manifest and its case ids.
        pattern: keep only the cases whose patterns in ``run`` include it; None keeps all.
        spread_by: the spread asked for, or None for the draw.

    Returns:
        The selection.
    """
    left_out = {i for _, ids in manifests for i in ids}
    remaining = tuple(i for i in pool if i not in left_out)
    if pattern is not None or spread_by is not None:
        uncoded = [i for i in remaining if not run.cases[i].verdict_occurrence]
        if uncoded:
            _refuse(
                f"{len(uncoded)} case(s) of the group hold no NTSB occurrence code: no pattern or "
                "first event to select by"
            )
    eligible = (
        remaining
        if pattern is None
        else tuple(i for i in remaining if pattern in case_difference(run.cases[i]).patterns)
    )
    if not eligible:
        _refuse("no case of the group is eligible after the exclusions and the pattern")
    return Selection(
        tuple(path for path, _ in manifests),
        len(pool) - len(remaining),
        pattern,
        spread_by,
        eligible,
    )


def choose(
    run: Run, selection: Selection, *, per_fatal: int, per_nonfatal: int, seed: int
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The fatal and the non-fatal cases to show: drawn, or spread by the NTSB's first event.

    Args:
        run: run a, for each case's fatality and first event.
        selection: the eligible cases and the spread asked for.
        per_fatal: how many fatal cases to show.
        per_nonfatal: how many non-fatal cases to show.
        seed: the seed.

    Returns:
        The fatal cases, then the non-fatal ones, each sorted.
    """
    eligible = selection.eligible
    fatal = {i: run.cases[i].fatal for i in eligible}
    if selection.spread is None:
        return draw(eligible, fatal, per_fatal=per_fatal, per_nonfatal=per_nonfatal, seed=seed)
    events = {i: first_event(run.cases[i]) for i in eligible}
    return spread(
        eligible, fatal, events, per_fatal=per_fatal, per_nonfatal=per_nonfatal, seed=seed
    )


def page_manifest(request: _Request, other: Run | None) -> dict[str, object]:
    """What ``cases.json`` holds: the cases shown, in page order, and how they were chosen.

    Args:
        request: the page's request.
        other: run b, or None.

    Returns:
        The manifest, ready for ``json.dumps``.
    """
    selection = request.selection
    return {
        "manifest": MANIFEST_KIND,
        "sample": SAMPLE,
        "run": request.run.run_id,
        "compare": None if other is None else other.run_id,
        "groups": str(request.groups.resolve()),
        "split": request.split,
        "group": request.group,
        "seed": request.seed,
        "fatal_asked": request.asked[0],
        "nonfatal_asked": request.asked[1],
        "exclude_from": [str(p.resolve()) for p in selection.exclude_from],
        "excluded": selection.excluded,
        "pattern": None if selection.pattern is None else _option(selection.pattern),
        "spread_by": selection.spread,
        "group_cases": len(request.pool),
        "eligible": len(selection.eligible),
        "cases": [*request.fatal, *request.nonfatal],
    }


def new_folder(base: Path, when: datetime) -> Path:
    """A new folder ``base/<UTC time>``; one that already exists is refused, never written over."""
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
    parser.add_argument(
        "--pattern",
        choices=list(PATTERN_OPTIONS),
        default=None,
        help="keep only the cases whose patterns in --run include this one (scripts/miss_kinds)",
    )
    parser.add_argument(
        "--spread-by",
        choices=[SPREAD_FIRST_EVENT],
        default=None,
        help="spread the cases shown over the NTSB's first events, in place of the draw",
    )
    parser.add_argument(
        "--exclude-from",
        type=Path,
        action="append",
        default=None,
        help="an earlier page's folder or its cases.json: its cases are left out (repeatable)",
    )
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
    read = [read_manifest(path) for path in args.exclude_from or ()]
    run = load_run(settings.runs_dir, args.run)
    other = None if args.compare is None else load_run(settings.runs_dir, args.compare)
    split, group = SPLITS[args.arm], GROUPS[args.group]
    pool = read_group(args.groups, split=split, group=group, run_id=run.run_id)
    absent = [i for i in pool if i not in run.cases]
    if absent:
        _refuse(f"{run.run_id} does not hold {len(absent)} case(s) of the group")
    selection = select(
        run,
        pool,
        read,
        pattern=None if args.pattern is None else PATTERN_OPTIONS[args.pattern],
        spread_by=args.spread_by,
    )
    fatal, nonfatal = choose(
        run, selection, per_fatal=args.fatal, per_nonfatal=args.nonfatal, seed=args.seed
    )
    uncoded = [i for i in (*fatal, *nonfatal) if not run.cases[i].verdict_occurrence]
    if uncoded:
        _refuse(
            f"{len(uncoded)} drawn case(s) hold no NTSB occurrence code: no defining event to "
            "compare"
        )
    request = _Request(
        run,
        args.groups,
        split,
        group,
        pool,
        fatal,
        nonfatal,
        args.seed,
        (args.fatal, args.nonfatal),
        selection,
    )
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
    folder = new_folder(base, now())
    title = f"S3.1 trails: {split}, {group}"
    (folder / HTML_FILE).write_text(render_html(title, blocks), encoding="utf-8")
    (folder / MARKDOWN_FILE).write_text(render_markdown(blocks), encoding="utf-8")
    (folder / MANIFEST_FILE).write_text(
        json.dumps(page_manifest(request, other), indent=1) + "\n", encoding="utf-8"
    )
    print(folder.relative_to(base.parent).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
