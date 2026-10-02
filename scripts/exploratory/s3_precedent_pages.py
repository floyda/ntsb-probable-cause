"""A private page for reading the precedent probe's cases beside their five nearest earlier ones.

Status
    Exploratory (decision 0059), S3.1 Task 15, free and offline: no model call, no network (the
    docket is not read). A private reading aid: it sets no bar, tunes nothing, and no number on
    it is cited. ``make s3-precedent-pages`` writes one HTML page and its manifest under
    ``NTSB_RUNS_DIR`` (``s3-precedent-pages/<UTC time>/``), never inside the repository and never
    committed.

Why
    The precedent probe (``scripts/exploratory/s3_precedent_probe.py``; its result
    ``docs/results/s3-precedent-probe-dev.txt``, commit 6dae045) came out "in between" by its
    committed rule, and the rule says: read a sample of cases before deciding anything. Andy
    approved this sample. The page is read for one question: when the right code is among the
    five nearest earlier cases, could the loop tell from the cause sentences which one is right?

The search
    The probe's headline variant, through the probe's own code (``load_run``, ``read_groups``,
    ``read_pool`` and ``check_pool``, ``Index``, ``tokens``, ``query_text``, ``search_hits``,
    ``phase_codes``): run a (``--run``); the final answer's probable cause as the query; the
    date-limited pool, only S3 statistics pool cases strictly earlier than the judged case, N,
    df and the average length over that set; BM25 (k1 = 1.2, b = 0.75); the five
    highest-ranked, ties by case id. A case counted as failed (decision 0136 item 1) has no
    query and is in no set.

The selection
    Three sets of judged cases, their eligibility read from ``search_hits`` exactly as the probe
    counts it:

    - **A, found** (10 asked): arm C "always wrong" cases with a query whose NTSB first code is
      the first code of at least one of the five nearest (the probe's found@5).
    - **B, not found** (5 asked): arm C "always wrong" cases with a query whose NTSB first code
      is not among the five's first codes.
    - **C, right but pointed away** (5 asked): arm C "always right" cases (each has a query)
      whose nearest case's first code differs from the NTSB's first code (the probe's "the
      nearest case's first code differs" count; a search with no result counts, as there).

    Each set is drawn from its own eligible ids with one generator,
    ``random.Random(f"{seed}:{letter}")`` (a string seed, so the same in every process): the
    sorted fatal ids and then the sorted non-fatal ids are shuffled by it, and cases are taken
    from the front, a fatal case first, then non-fatal and fatal in turn while both remain, the
    other kind alone once one runs out. A set with fewer eligible cases than asked is shown
    whole, and the page says so. Within a set the cases are shown fatal first, each kind sorted
    by case number. The same arguments always choose the same cases and write the same page.

What the page shows
    At its top: what the page is (a private reading aid; the probe's result, 6dae045, "in
    between"; no number on it cited); the reading question, in bold; the run, the groups file
    and the search; each set's rule, eligible count (fatal and non-fatal) and how many are
    shown; how the sets were drawn; a legend of the marks; the cases, linked.

    Per case, in order: a header (the case number, which is fine here: the page is private and
    never committed; the set; the event date, the processed file's, which the date limit reads;
    fatal or non-fatal). The NTSB's verdict, from ``split_record`` as the trail pages get it:
    its occurrence codes in order with labels, and its probable-cause text. The loop's answer:
    its first three occurrence codes with labels and probabilities, each marked against the
    NTSB's codes exactly as the trail pages mark them (``occurrence_lines``), and the query, its
    probable-cause sentence. The five nearest earlier cases in rank order, each with its rank,
    its BM25 score (two decimals, from ``Index.scores`` over the same pool), its case number and
    event date, its NTSB probable-cause text with the query words it shares in bold, and its
    occurrence codes in order with labels, the first one marked against the judged case's NTSB
    first code. Then one line: the phase-aware control's five codes, the five commonest first
    codes among earlier pool cases in the phase of the loop's answer's first code, each marked
    the same way.

The marks
    The loop's codes carry the trail pages' marks: "✓ match" (green) when the NTSB lists the
    same code at the same rank, "↕ wrong place: the NTSB's rank k" (amber), "✗ not in the
    NTSB's" (red). An earlier case's first code, against the judged case's NTSB first code:
    "✓ same first code" (green); "≈ same event, other phase" (amber: the last three digits are
    equal); "↕ in its sequence, not first" (amber: the NTSB's first code is elsewhere in this
    earlier case's sequence); "✗ different" (red). The first that applies wins, in that order.
    A phase-aware control code is marked the same way, as a sequence of one code. The marks are
    the trail pages' chips and colour tokens (light, and dark both by preference and by
    ``data-theme``), each with words that read without colour.

Shared words
    An earlier case's text is cut at each run of ASCII letters and digits, and each run is passed
    through the probe's own ``tokens``, which lower-cases it and drops a stop word: a run whose
    token is one of the query's tokens is bold. On text whose letters are ASCII, the runs are
    exactly the tokeniser's words. Every piece of text is escaped before any tag is added, and a
    tag is only ever put around a piece, never into escaped text, so no record text can add
    markup or be bolded into an entity. The bolding reads the text as shown, after the name
    replacements below.

Names
    Every piece of prose passes through the attach step's own replacements, as the trail pages
    apply them (``clean``: ``amateur_built_replace``, ``redact_known_names``): the NTSB's
    probable cause and the loop's query with the judged case's record, and each earlier case's
    probable cause with that earlier case's own record. The earlier cases' texts and codes are
    read with ``fields.probable_cause`` and ``fields.occurrence_codes``, as the probe's pool
    reads them, not through ``split_record``, as they never reach a model. Other names are not
    detected.

Refusals
    An output folder inside the repository (outside its git-ignored ``data/``), first. Then
    everything the probe refuses, through its own loader and checks: a held-out run id; a folder
    with no ``run.jsonl``, or whose record names another run; any sample but ``dev-400``
    (held-out, open and the sealed samples); a run that has not finished; a case outside the
    development split; a run that is not exactly ``dev-400``'s cases; any arm but C. The groups
    file through ``read_group``: missing, not on ``dev-400``, not drawn over ``--run``, or
    without arm C groups. Then a group case the run does not hold; a case of the run whose
    verdict holds no occurrence code; a case of the run with no event date in the processed file;
    a pool holding a sample case or a non-development case (``LeakageError`` from
    ``check_pool``, before any pool text is read). Then, per case shown: a judged record that is
    another case's, or outside the development split (the trail pages' ``check_record``); an
    earlier case's record whose number, words or first code are not those the search ranked.
    A second page in the same second is refused rather than written over.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.exploratory.s3_precedent_pages --run RUN \
        --groups PATH [--seed 20261002] [--out-dir DIR]

    Prints one line: the page's folder, relative to the folder it was made in (the runs folder
    by default). The folder holds ``precedents.html`` and the manifest ``cases.json``.
"""

import argparse
import html
import json
import random
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, NoReturn

from scripts.exploratory import s3_precedent_probe as pp
from scripts.miss_kinds import answer_codes, scored_answer
from scripts.s3_case_groups import Run
from scripts.s3_trail_pages import (
    MATCH,
    Block,
    Contents,
    Heading,
    Items,
    Line,
    Mark,
    Marked,
    Para,
    block_html,
    check_record,
    chip_html,
    clean,
    new_folder,
    ntsb_verdict,
    occurrence_label,
    occurrence_lines,
    page_html,
    refuse_inside_repository,
)

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.records import CaseResult
from ntsb_probable_cause.settings import Settings

SAMPLE: Final = "dev-400"
FOLDER: Final = "s3-precedent-pages"
PAGE_FILE: Final = "precedents.html"
MANIFEST_FILE: Final = "cases.json"
MANIFEST_KIND: Final = "s3_precedent_pages"
TITLE: Final = "S3.1 precedent reading page"
DEFAULT_SEED: Final = 20261002
# The probe's headline variant.
QUERY: Final[pp.Query] = "probable cause"
POOL: Final[pp.Pool] = "earlier"
# The commit of docs/results/s3-precedent-probe-dev.txt, and the outcome its rule gave.
PROBE_RESULT: Final = "6dae045"
PROBE_OUTCOME: Final = "in between"
QUESTION: Final = (
    "When the right code is among the five nearest earlier cases, could the loop tell from the "
    "cause sentences which one is right?"
)


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_precedent_pages: {message}")


# --- the selection ---


@dataclass(frozen=True)
class CaseSet:
    """One set of judged cases: its letter, name, group, how many to show, and its rule."""

    letter: str
    name: str
    group: pp.Group
    asked: int
    rule: str


SETS: Final[tuple[CaseSet, ...]] = (
    CaseSet(
        "A",
        "found",
        "always wrong",
        10,
        'arm C "always wrong" cases with a query whose NTSB first code is the first code of at '
        "least one of the five nearest",
    ),
    CaseSet(
        "B",
        "not found",
        "always wrong",
        5,
        'arm C "always wrong" cases with a query whose NTSB first code is not among the five\'s '
        "first codes",
    ),
    CaseSet(
        "C",
        "right but pointed away",
        "always right",
        5,
        "arm C \"always right\" cases whose nearest case's first code differs from the NTSB's "
        "first code",
    ),
)


def eligible(
    cases: Mapping[str, CaseResult],
    groups: Mapping[pp.Group, Sequence[str]],
    index: pp.Index,
    days: Mapping[str, date],
) -> dict[str, tuple[str, ...]]:
    """Each set's eligible case ids, sorted, by the probe's own search and measures.

    Args:
        cases: run a's cases by id.
        groups: the arm C groups' case ids.
        index: the pool, indexed.
        days: each judged case's event date.

    Returns:
        Set letter to its eligible case ids.
    """

    def with_query(group: pp.Group) -> list[str]:
        return [i for i in groups[group] if pp.query_text(cases[i], QUERY) is not None]

    def hits(case_id: str) -> pp.Hits:
        return pp.search_hits(index, cases[case_id], days[case_id], QUERY, POOL)

    wrong = {i: hits(i) for i in with_query("always wrong")}
    right = {i: hits(i) for i in with_query("always right")}
    return {
        "A": tuple(sorted(i for i, h in wrong.items() if h.found)),
        "B": tuple(sorted(i for i, h in wrong.items() if not h.found)),
        "C": tuple(sorted(i for i, h in right.items() if not h.nearest)),
    }


def draw(
    ids: Collection[str], fatal: Mapping[str, bool], *, wanted: int, seed: int, letter: str
) -> tuple[str, ...]:
    """Up to ``wanted`` of ``ids``, in the order drawn; the same seed, the same cases.

    The sorted fatal ids, then the sorted non-fatal ids, are shuffled by one generator,
    ``random.Random(f"{seed}:{letter}")``. Cases are taken from the front of each list: a fatal
    case first, then the kinds in turn while both remain, the other kind alone once one runs
    out.

    Args:
        ids: the set's eligible case ids, in any order.
        fatal: whether each case is fatal.
        wanted: how many to take; a smaller set is taken whole.
        seed: the page's seed.
        letter: the set's letter, which makes its generator its own.

    Returns:
        The cases, in the order drawn.
    """
    rng = random.Random(f"{seed}:{letter}")  # noqa: S311 -- reproducible sampling, not security
    queues = {kind: [i for i in sorted(set(ids)) if fatal[i] is kind] for kind in (True, False)}
    for kind in (True, False):
        rng.shuffle(queues[kind])
    chosen: list[str] = []
    turn = True
    while len(chosen) < wanted and (queues[True] or queues[False]):
        kind = turn if queues[turn] else not turn
        chosen.append(queues[kind].pop(0))
        turn = not kind
    return tuple(chosen)


def page_order(ids: Collection[str], fatal: Mapping[str, bool]) -> tuple[str, ...]:
    """The cases of a set as the page shows them: fatal first, each kind sorted."""
    return tuple(sorted(ids, key=lambda i: (not fatal[i], i)))


# --- the marks ---

SAME: Final = Mark("match", "✓ same first code")
SAME_EVENT: Final = Mark("near", "≈ same event, other phase")
IN_SEQUENCE: Final = Mark("near", "↕ in its sequence, not first")
DIFFERENT: Final = Mark("miss", "✗ different")


def precedent_mark(sequence: Sequence[str], first: str) -> Mark:
    """An earlier case's first code against the judged case's NTSB first code.

    Args:
        sequence: the earlier case's occurrence codes, in its order (a control code alone).
        first: the judged case's NTSB first code (six digits).

    Returns:
        The first that applies: the same code; the same event (last three digits) in another
        phase; the NTSB's first code elsewhere in the sequence; different.
    """
    code = sequence[0]
    if code == first:
        return SAME
    if code[3:] == first[3:]:
        return SAME_EVENT
    if first in sequence[1:]:
        return IN_SEQUENCE
    return DIFFERENT


# --- text with bold words and marks ---


@dataclass(frozen=True)
class Bold:
    """A piece of text shown in bold."""

    text: str


type Piece = str | Bold | Mark


@dataclass(frozen=True)
class Spans:
    """A paragraph of plain pieces, bold pieces and marks, led by a bold label when it has one."""

    pieces: tuple[Piece, ...]
    label: str = ""


type PageBlock = Block | Spans

_LETTERS_AND_DIGITS: Final = re.compile(r"[A-Za-z0-9]+")


def shared_pieces(text: str, query: Collection[str]) -> tuple[str | Bold, ...]:
    """``text`` cut into plain pieces and bold ones: each word whose token the query holds.

    Args:
        text: the text, as shown.
        query: the query's tokens (``tokens``: lower-cased, stop words left out).

    Returns:
        The pieces, in order; joined, they are ``text``.
    """
    wanted = frozenset(query)
    pieces: list[str | Bold] = []
    last = 0
    for word in _LETTERS_AND_DIGITS.finditer(text):
        if not wanted.intersection(pp.tokens(word.group())):
            continue
        if word.start() > last:
            pieces.append(text[last : word.start()])
        pieces.append(Bold(word.group()))
        last = word.end()
    if last < len(text):
        pieces.append(text[last:])
    return tuple(pieces)


def _piece_html(piece: Piece) -> str:
    if isinstance(piece, Mark):
        return chip_html(piece)
    if isinstance(piece, Bold):
        return f"<b>{html.escape(piece.text)}</b>"
    return html.escape(piece)


def spans_html(block: Spans) -> str:
    """A ``Spans`` paragraph as HTML: each piece escaped first, tags only around pieces."""
    lead = f"<b>{html.escape(block.label)}:</b> " if block.label else ""
    return f"<p>{lead}{''.join(_piece_html(p) for p in block.pieces)}</p>"


def render(blocks: Sequence[PageBlock]) -> str:
    """The page: the trail pages' shell, theme and chips around these blocks."""
    body = "\n".join(spans_html(b) if isinstance(b, Spans) else block_html(b) for b in blocks)
    return page_html(TITLE, body)


# --- one case ---


@dataclass(frozen=True)
class Earlier:
    """One of the five nearest earlier cases, as the search ranked it, with its own record."""

    precedent: pp.Precedent
    score: float
    raw: Mapping[str, object]
    sequence: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Judged:
    """One judged case shown, with where it sits on the page and what was found for it."""

    case_set: CaseSet
    number: int
    total: int
    result: CaseResult
    day: date
    raw: Mapping[str, object]
    query: str
    five: tuple[Earlier, ...]
    phase: tuple[str, ...]

    @property
    def anchor(self) -> str:
        """The case's HTML id, its set letter and number."""
        return f"{self.case_set.letter}{self.number}"


def nearest(
    index: pp.Index, words: Sequence[str], day: date
) -> tuple[tuple[pp.Precedent, float], ...]:
    """The five nearest earlier cases, best first, each with its BM25 score.

    Args:
        index: the pool, indexed.
        words: the query's tokens.
        day: the judged case's event date.

    Returns:
        ``Index.search``'s cases, each with its score from ``Index.scores`` over the same pool.
    """
    scores = index.scores(words, day, POOL)
    return tuple((p, scores[p.case_id]) for p in index.search(words, day, POOL))


def earlier_case(precedent: pp.Precedent, score: float, raw: Mapping[str, object]) -> Earlier:
    """An earlier case with its record, refused unless the record is the one the search ranked.

    Args:
        precedent: the case as the index holds it.
        score: its BM25 score.
        raw: the record read for it.

    Returns:
        The earlier case, its text and its occurrence codes read as the pool reads them.
    """
    text = fields.probable_cause(raw) or ""
    sequence = fields.occurrence_codes(raw)
    if (
        raw.get("ntsbNumber") != precedent.case_id
        or pp.tokens(text) != precedent.words
        or sequence[:1] != (precedent.first_code,)
    ):
        _refuse(
            f"{precedent.case_id}: the record read for it is not the case the search ranked: "
            "the processed file changed between reads"
        )
    return Earlier(precedent, score, raw, sequence, text)


def _codes(tables: CodeTables, sequence: Sequence[str], first: str) -> tuple[Line, ...]:
    """An earlier case's occurrence codes with labels, its first code marked."""
    if not sequence:
        return ("none",)
    labelled = [f"{code}: {occurrence_label(tables, code)}" for code in sequence]
    return (Marked(labelled[0], precedent_mark(sequence, first)), *labelled[1:])


def _earlier_blocks(
    tables: CodeTables, rank: int, earlier: Earlier, query: Collection[str], first: str
) -> list[PageBlock]:
    precedent = earlier.precedent
    return [
        Heading(
            4,
            f"Rank {rank}: BM25 {earlier.score:.2f}, {precedent.case_id}, "
            f"{precedent.event_date.isoformat()}",
        ),
        Spans(shared_pieces(clean(earlier.text, earlier.raw), query), "Its probable cause"),
        Items(
            _codes(tables, earlier.sequence, first), "Its occurrence codes, in order", ordered=True
        ),
    ]


def _phase_line(tables: CodeTables, case: Judged, first: str) -> Spans:
    answer = scored_answer(case.result)
    phase = answer_codes(answer)[0][:3] if answer is not None else ""
    label = (
        f"Phase-aware control: the five commonest first codes among earlier pool cases in phase "
        f"{phase} ({tables.phases.get(phase, 'not in the code tables')}), the phase of the "
        "loop's first code"
    )
    pieces: list[Piece] = []
    for code in case.phase:
        if pieces:
            pieces.append("; ")
        pieces += [precedent_mark((code,), first), f"{code}: {occurrence_label(tables, code)}"]
    return Spans(tuple(pieces) or ("none",), label)


def case_blocks(case: Judged, tables: CodeTables) -> list[PageBlock]:
    """One case's section: the header, the NTSB's verdict, the loop's answer, the five, the line.

    Args:
        case: the judged case, with its five nearest and its phase-aware control.
        tables: the code tables, for labels.

    Returns:
        The blocks.
    """
    result, raw, case_set = case.result, case.raw, case.case_set
    ntsb = result.verdict_occurrence
    first = ntsb[0]
    verdict = ntsb_verdict(raw)
    answer = scored_answer(result)
    words = frozenset(pp.tokens(case.query))
    blocks: list[PageBlock] = [
        Heading(
            2,
            f"Set {case_set.letter} ({case_set.name}), case {case.number} of {case.total}: "
            f"{result.case_id}",
            case.anchor,
        ),
        Para(case.day.isoformat(), "Event date"),
        Para("fatal" if result.fatal else "non-fatal", "Injury"),
        Heading(3, "The NTSB's verdict"),
        Items(
            tuple(f"{c}: {occurrence_label(tables, c)}" for c in verdict.occurrence_codes)
            or ("none",),
            "Occurrence codes, in the NTSB's order",
            ordered=True,
        ),
        Para(clean(verdict.probable_cause or "(none)", raw), "Probable cause"),
        Heading(3, "The loop's answer (run a)"),
        Items(
            occurrence_lines(tables, answer.occurrence[:3], ntsb) if answer is not None else (),
            "Its first three occurrence codes, each against the NTSB's",
            ordered=True,
        ),
        Para(clean(case.query, raw), "The query (its probable cause)"),
        Heading(3, "The five nearest earlier cases"),
    ]
    if len(case.five) < pp.TOP:
        blocks.append(
            Para(f"{len(case.five)} earlier case(s) share a word with the query; no more.")
        )
    for rank, earlier in enumerate(case.five, start=1):
        blocks += _earlier_blocks(tables, rank, earlier, words, first)
    blocks.append(_phase_line(tables, case, first))
    return blocks


# --- the page's top ---


def _count(ids: Sequence[str], fatal: Mapping[str, bool]) -> str:
    fatal_cases = sum(fatal[i] for i in ids)
    return f"{len(ids)} ({fatal_cases} fatal, {len(ids) - fatal_cases} non-fatal)"


def legend_blocks() -> list[PageBlock]:
    """The marks, each with its colour and words, and what bold means."""
    return [
        Items(
            (
                Marked("the NTSB lists the same code at the same rank", MATCH),
                Marked(
                    "the NTSB lists it at another rank, which the mark names",
                    Mark("near", "↕ wrong place: the NTSB's rank k"),
                ),
                Marked("the NTSB does not list it", Mark("miss", "✗ not in the NTSB's")),
            ),
            "The loop's codes, as the trail pages mark them",
        ),
        Items(
            (
                Marked("its first code is the judged case's NTSB first code", SAME),
                Marked("the same event (last three digits), another phase", SAME_EVENT),
                Marked(
                    "the NTSB's first code is elsewhere in this earlier case's sequence",
                    IN_SEQUENCE,
                ),
                Marked("none of these", DIFFERENT),
                "The first that applies wins, in this order. A phase-aware control code is "
                "marked the same way, as a sequence of one code.",
            ),
            "An earlier case's first code, against the judged case's NTSB first code",
        ),
        Spans(
            (
                "the query words an earlier case's probable cause shares are ",
                Bold("bold"),
                ": the probe's own tokens (letters and digits, lower-cased), stop words left out",
            ),
            "Bold",
        ),
    ]


@dataclass(frozen=True)
class Chosen:
    """One set's eligible cases and the cases shown, in page order."""

    case_set: CaseSet
    eligible: tuple[str, ...]
    shown: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    """What the page's top and its manifest state: the run, the groups, the sets, the seed."""

    run_id: str
    groups_path: Path
    groups: Mapping[pp.Group, Sequence[str]]
    chosen: tuple[Chosen, ...]
    fatal: Mapping[str, bool]
    seed: int


def intro_blocks(selection: Selection) -> list[PageBlock]:
    """The page's top: what it is, the question, the search, the selection, the legend.

    Args:
        selection: the run, the groups, each set's eligible and shown cases, the seed.

    Returns:
        The blocks.
    """
    groups, fatal, seed = selection.groups, selection.fatal, selection.seed
    lines: list[Line] = []
    for c in selection.chosen:
        s = c.case_set
        line = (
            f"Set {s.letter}, {s.name}: {s.rule}. Eligible: {_count(c.eligible, fatal)}; "
            f"shown: {_count(c.shown, fatal)}"
        )
        if len(c.eligible) < s.asked:
            line += f"; fewer than the {s.asked} asked, so all are shown"
        lines.append(line)
    lines.append(
        f"Each set drawn with seed {seed}: its sorted fatal ids and then its sorted non-fatal ids "
        f'shuffled by one generator seeded "{seed}:<set letter>"; cases taken from the front, a '
        "fatal case first, then non-fatal and fatal in turn while both remain. Shown fatal first, "
        "each kind sorted by case number."
    )
    return [
        Heading(1, TITLE),
        Para(
            "A private reading aid for S3.1 Task 15: free and offline, built from run a's folder, "
            "the groups file and the processed records, with no model call. Never committed; no "
            "number on it is cited. The precedent probe (scripts/exploratory/s3_precedent_probe.py;"
            f" result docs/results/s3-precedent-probe-dev.txt, commit {PROBE_RESULT}) came out "
            f'"{PROBE_OUTCOME}" by its committed rule, which says to read a sample of cases before '
            "deciding anything: this page is that sample. Owner and operator names the records "
            "hold, and an amateur-built aircraft's make and model, are replaced, as in the "
            "agent's own text."
        ),
        Spans((Bold(QUESTION),), "The reading question"),
        Para(f"{selection.run_id} (arm C, {SAMPLE})", "Run a"),
        Para(
            f"arm C, from {selection.groups_path.name}: always wrong "
            f"{_count(groups['always wrong'], fatal)}; always right "
            f"{_count(groups['always right'], fatal)}",
            "Groups",
        ),
        Para(
            "the probe's headline variant: BM25 "
            f"(k1 = {pp.K1}, b = {pp.B}) over the NTSB probable-cause texts of the S3 statistics "
            "pool, only cases whose event date is strictly earlier than the judged case's (N, df "
            "and the average length over that set), the loop's final probable cause as the "
            "query, the five highest-ranked, ties by case id",
            "Search",
        ),
        Items(tuple(lines), "Selection"),
        *legend_blocks(),
        Contents(
            tuple(
                (f"{c.case_set.letter}{n}", f"{c.case_set.letter}{n}: {i} ({_kind(fatal[i])})")
                for c in selection.chosen
                for n, i in enumerate(c.shown, start=1)
            )
        ),
    ]


def _kind(fatal: bool) -> str:
    return "fatal" if fatal else "non-fatal"


def page_manifest(selection: Selection) -> dict[str, object]:
    """What ``cases.json`` holds: the cases shown per set, in page order, and how they were chosen.

    Args:
        selection: the run, the groups, each set's eligible and shown cases, the seed.

    Returns:
        The manifest, ready for ``json.dumps``.
    """

    def fatal_cases(ids: Sequence[str]) -> int:
        return sum(selection.fatal[i] for i in ids)

    return {
        "manifest": MANIFEST_KIND,
        "sample": SAMPLE,
        "run": selection.run_id,
        "groups": str(selection.groups_path.resolve()),
        "seed": selection.seed,
        "query": QUERY,
        "pool": POOL,
        "group_cases": {name: len(ids) for name, ids in selection.groups.items()},
        "sets": {
            c.case_set.letter: {
                "name": c.case_set.name,
                "group": c.case_set.group,
                "asked": c.case_set.asked,
                "eligible": len(c.eligible),
                "eligible_fatal": fatal_cases(c.eligible),
                "eligible_nonfatal": len(c.eligible) - fatal_cases(c.eligible),
                "shown": len(c.shown),
                "shown_fatal": fatal_cases(c.shown),
                "shown_nonfatal": len(c.shown) - fatal_cases(c.shown),
                "cases": list(c.shown),
            }
            for c in selection.chosen
        },
    }


# --- the whole page ---


def judged_cases(
    chosen: Sequence[Chosen],
    run: Run,
    *,
    index: pp.Index,
    days: Mapping[str, date],
    processed: Path,
) -> list[Judged]:
    """Each case shown, in page order, with its five nearest and its phase-aware control.

    The records, the judged cases' and the earlier cases', are read in one pass.

    Args:
        chosen: each set's shown cases, in page order.
        run: run a.
        index: the pool, indexed.
        days: each judged case's event date.
        processed: the processed folder.

    Returns:
        The judged cases.
    """
    cases = {c.case_id: c for c in run.cases}
    found: dict[str, tuple[str, tuple[tuple[pp.Precedent, float], ...]]] = {}
    for c in chosen:
        for case_id in c.shown:
            query = pp.query_text(cases[case_id], QUERY)
            if query is None:  # eligible() admits only cases with a query
                raise TypeError(f"{case_id} was shown with no query")
            found[case_id] = (query, nearest(index, pp.tokens(query), days[case_id]))
    earlier = (p.case_id for _, five in found.values() for p, _ in five)
    ids = list(dict.fromkeys([*found, *earlier]))
    raws = dict(zip(ids, samples.load_cases(processed, ids), strict=True))
    judged = []
    for c in chosen:
        for number, case_id in enumerate(c.shown, start=1):
            check_record(case_id, raws[case_id])
            query, five = found[case_id]
            result, day = cases[case_id], days[case_id]
            judged.append(
                Judged(
                    c.case_set,
                    number,
                    len(c.shown),
                    result,
                    day,
                    raws[case_id],
                    query,
                    tuple(earlier_case(p, score, raws[p.case_id]) for p, score in five),
                    pp.phase_codes(index, result, day, POOL),
                )
            )
    return judged


def _now() -> datetime:
    return datetime.now(UTC)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_precedent_pages")
    parser.add_argument("--run", required=True, help="run a: a finished dev-400 arm C run")
    parser.add_argument("--groups", type=Path, required=True, help="s3_case_groups' groups.json")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <runs>/" + FOLDER)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, now: Callable[[], datetime] = _now) -> int:
    """Write the page and its manifest; print the folder, relative to where it was made.

    Args:
        argv: the command line.
        now: the clock, for the folder's name only.

    Returns:
        0.
    """
    args = _arguments(argv)
    settings = Settings()
    base: Path = args.out_dir if args.out_dir is not None else settings.runs_dir / FOLDER
    refuse_inside_repository(base)
    run = pp.load_run(args.run)
    groups = pp.read_groups(args.groups, [run])
    processed = settings.data_dir / "processed"
    kept, days, _ = pp.read_pool(processed, [c.case_id for c in run.cases])
    index = pp.Index(kept)
    cases = {c.case_id: c for c in run.cases}
    fatal = {i: c.fatal for i, c in cases.items()}
    sets = eligible(cases, groups, index, days)
    chosen = tuple(
        Chosen(
            s,
            sets[s.letter],
            page_order(
                draw(sets[s.letter], fatal, wanted=s.asked, seed=args.seed, letter=s.letter),
                fatal,
            ),
        )
        for s in SETS
    )
    selection = Selection(run.run_id, args.groups, groups, chosen, fatal, args.seed)
    tables = load_tables()
    blocks = intro_blocks(selection)
    for case in judged_cases(chosen, run, index=index, days=days, processed=processed):
        blocks += case_blocks(case, tables)
    folder = new_folder(base, now())
    (folder / PAGE_FILE).write_text(render(blocks), encoding="utf-8")
    (folder / MANIFEST_FILE).write_text(
        json.dumps(page_manifest(selection), indent=1) + "\n", encoding="utf-8"
    )
    print(folder.relative_to(base.parent).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
