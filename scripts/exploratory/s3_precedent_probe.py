"""Whether earlier closed cases, found from the loop's own words, hold the NTSB's first code.

Status
    Exploratory (decision 0059), S3.1 Task 15, free and offline: no model call, no network. It
    sets no bar and tunes nothing. Its prediction was committed before it existed (commit
    a0c6cc6, the S3.1 plan's entry "A precedent probe before round 1"), and it applies that
    rule and prints the outcome at the top. ``make s3-precedent-probe`` writes its output to
    ``docs/results/s3-precedent-probe-dev.txt``, first on 2026-10-02 over the two arm C
    noise-floor runs.

Why
    An NTSB investigator codes a case knowing years of earlier ones; the loop sees earlier cases
    only as counts (``occurrence_usage``, ``past_findings``). Similar-case search is outside
    S3.1, and the roadmap (§10) allows it only as a declared experiment limited to earlier
    accidents. Before any design, this measures whether the earlier cases nearest to the loop's
    own words would even hold the NTSB's first occurrence code, against a control that needs no
    search. Tuning round 1 waits for its result.

What it measures
    Judged cases: arm C's "always wrong" group (the headline), its "always right" group, and
    every case of each run, from a ``groups.json`` written by ``scripts/s3_case_groups.py``.
    Queries: the final answer's ``probable_cause`` and, separately, its ``evidence_narrative``,
    from each run. A case counted as failed (decision 0136 item 1) has no query and is not
    found; it stays in the denominator. Pool: the S3 statistics pool exactly as
    ``scripts/coding_stats.py`` builds it (``processed_rows``, ``pool_cases``, ``check_pool``,
    ``STAGES["s3"]``), each case with an NTSB probable-cause text and at least one occurrence
    code. Search: BM25 (k1 = 1.2, b = 0.75) over lower-cased word tokens of the pool's
    probable-cause texts, less a fixed stop-word list; the five highest-ranked, ties by case
    id. Two pools per judged case: only cases strictly earlier than its event date (the
    headline; N, df and the average length over that set), and every case but those on its
    event date. Measures: found@5, nearest@1, majority@5 and event-only@5; a control (the five
    commonest first codes of the same pool) and a phase-aware control (the same within the
    loop's own answer's phase). Counts only (decision 0024's rule): no case number and no text
    from any record. Every count has its denominator.

Refusals
    The runs through ``scripts/s3_case_groups.py``'s own checks (``load``): a held-out run id; a
    folder with no ``run.jsonl``, or whose record names another run; any sample but ``dev-400``
    (held-out, open and the sealed samples); a run that has not finished; a case outside the
    development split; a run that is not exactly ``dev-400``'s cases. Then: any arm but C; a
    run named twice. The groups file through ``scripts/s3_trail_pages.py``'s own checks
    (``read_group``): missing, not on ``dev-400``, not drawn over both runs, or without arm C
    groups. Then a group case the runs do not hold, a judged case whose verdict holds no
    occurrence code, and a judged case with no event date in the processed file. The pool
    through ``check_pool``: a sample case or a non-development case raises ``LeakageError``
    before any pool text is read.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.exploratory.s3_precedent_probe \
        --runs RUN_A RUN_B --groups PATH [--out PATH]
"""

import argparse
import heapq
import re
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import accumulate
from math import log
from pathlib import Path
from typing import Final, Literal, NoReturn

from scripts import s3_case_groups
from scripts.coding_stats import STAGES, Row, check_pool, pool_cases, processed_rows
from scripts.miss_kinds import answer_codes, scored_answer
from scripts.s3_case_groups import Run
from scripts.s3_trail_pages import read_group

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.records import CaseResult
from ntsb_probable_cause.settings import Settings

type Pool = Literal["earlier", "whole"]
type Query = Literal["probable cause", "evidence narrative"]
type Group = Literal["always wrong", "always right"]

ARM: Final = "C"
SPLIT: Final = "arm C"
STAGE: Final = "s3"
GROUPS: Final[tuple[Group, ...]] = ("always wrong", "always right")
HEADLINE: Final[Group] = "always wrong"
POOLS: Final[tuple[Pool, ...]] = ("earlier", "whole")
QUERIES: Final[tuple[Query, ...]] = ("probable cause", "evidence narrative")

K1: Final = 1.2
B: Final = 0.75
TOP: Final = 5

# The committed rule (plan entry "A precedent probe before round 1", commit a0c6cc6).
PREDICTED_CASES: Final = 266
PROMISING_AT: Final = 67
NOT_PROMISING_BELOW: Final = 27
PREDICTION: Final = (
    "Prediction (Andy, 2026-10-02). Read on run a, with the better of the two queries: "
    "promising if found in at least 67 of the 266 cases (25%) and the found count is above the "
    "control's count; not promising if found in fewer than 27 (10%), or the found count is not "
    "above the control's; in between: read a sample of cases before deciding anything."
)

_WORD: Final = re.compile(r"[a-z0-9]+")
# Common English function words, fixed before the probe was run and not tuned on any case.
STOP_WORDS: Final = frozenset(
    {
        "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and",
        "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
        "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing", "down",
        "during", "each", "either", "few", "for", "from", "further", "had", "has", "have",
        "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i",
        "if", "in", "into", "is", "it", "its", "itself", "just", "may", "me", "might", "more",
        "most", "must", "my", "myself", "neither", "no", "nor", "not", "now", "of", "off",
        "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own",
        "same", "she", "should", "so", "some", "such", "than", "that", "the", "their",
        "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those",
        "through", "to", "too", "under", "until", "up", "upon", "very", "was", "we", "were",
        "what", "when", "where", "which", "while", "who", "whom", "whose", "why", "will",
        "with", "would", "you", "your", "yours", "yourself", "yourselves",
    }
)  # fmt: skip


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_precedent_probe: {message}")


# --- the search ---


def words(text: str) -> tuple[str, ...]:
    """Lower-cased word tokens (``[a-z0-9]+``) of ``text``, in order, stop words kept."""
    return tuple(_WORD.findall(text.lower()))


def tokens(text: str) -> tuple[str, ...]:
    """Lower-cased word tokens of ``text``, less the stop words, in order."""
    return tuple(word for word in words(text) if word not in STOP_WORDS)


@dataclass(frozen=True)
class Precedent:
    """One pool case as the search sees it: its id, event date, first code and words."""

    case_id: str
    event_date: date
    first_code: str
    words: tuple[str, ...]


def _spans(days: Sequence[int], day: int, pool: Pool) -> tuple[tuple[int, int], ...]:
    """The runs (start, stop) of sorted ``days`` a case on ``day`` may see in ``pool``."""
    before = bisect_left(days, day)
    if pool == "earlier":
        return ((0, before),)
    return ((0, before), (bisect_right(days, day), len(days)))


def ranked(codes: Iterable[str]) -> list[tuple[str, int]]:
    """Each code with its count, the commonest first, ties by code ascending."""
    return sorted(Counter(codes).items(), key=lambda item: (-item[1], item[0]))


class Index:
    """BM25 over the pool's words, sorted by event date, so any pool is two bisections away.

    Per word, the dates of the cases holding it are kept sorted beside its postings, so df for
    a date-limited pool is one ``bisect``; the average length comes from prefix sums.
    """

    def __init__(self, pool: Sequence[Precedent]) -> None:
        """Index ``pool``.

        Args:
            pool: the pool cases, in any order.
        """
        self.cases = tuple(sorted(pool, key=lambda p: (p.event_date, p.case_id)))
        self._days = [p.event_date.toordinal() for p in self.cases]
        self._lengths = [len(p.words) for p in self.cases]
        self._prefix = list(accumulate(self._lengths, initial=0))
        postings: dict[str, list[tuple[int, int]]] = {}
        for position, case in enumerate(self.cases):
            for word, count in Counter(case.words).items():
                postings.setdefault(word, []).append((position, count))
        self._postings = postings
        self._word_days = {w: [self._days[p] for p, _ in rows] for w, rows in postings.items()}
        self._commonest: dict[tuple[int, Pool, str | None], tuple[str, ...]] = {}

    def size(self, day: date, pool: Pool) -> int:
        """How many pool cases a judged case on ``day`` may see."""
        return sum(stop - start for start, stop in _spans(self._days, day.toordinal(), pool))

    def scores(self, query: Sequence[str], day: date, pool: Pool) -> dict[str, float]:
        """BM25 scores of the cases a judged case on ``day`` may see that share a query word.

        N, df and the average length are taken over those cases only. Each distinct query word
        counts once; a case sharing no word with the query has no score.

        Args:
            query: the query's tokens.
            day: the judged case's event date.
            pool: ``earlier`` (strictly earlier dates) or ``whole`` (every other date).

        Returns:
            Case id to score.
        """
        return {self.cases[p].case_id: score for p, score in self._scored(query, day, pool).items()}

    def _scored(self, query: Sequence[str], day: date, pool: Pool) -> dict[int, float]:
        """:meth:`scores`, keyed by position in date order."""
        ordinal = day.toordinal()
        spans = _spans(self._days, ordinal, pool)
        n = sum(stop - start for start, stop in spans)
        if not n:
            return {}
        average = sum(self._prefix[stop] - self._prefix[start] for start, stop in spans) / n
        totals: dict[int, float] = {}
        for word in dict.fromkeys(query):
            rows = self._postings.get(word)
            if rows is None:
                continue
            parts = [rows[a:b] for a, b in _spans(self._word_days[word], ordinal, pool)]
            df = sum(len(part) for part in parts)
            if not df:
                continue
            idf = log(1 + (n - df + 0.5) / (df + 0.5))
            for part in parts:
                for position, count in part:
                    norm = K1 * (1 - B + B * self._lengths[position] / average)
                    gain = idf * count * (K1 + 1) / (count + norm)
                    totals[position] = totals.get(position, 0.0) + gain
        return totals

    def search(self, query: Sequence[str], day: date, pool: Pool) -> tuple[Precedent, ...]:
        """The five highest-ranked cases, ties by case id ascending; fewer if fewer match.

        Args:
            query: the query's tokens.
            day: the judged case's event date.
            pool: ``earlier`` or ``whole``.

        Returns:
            The cases, best first.
        """
        scored = self._scored(query, day, pool)
        best = heapq.nsmallest(
            TOP, scored.items(), key=lambda item: (-item[1], self.cases[item[0]].case_id)
        )
        return tuple(self.cases[position] for position, _ in best)

    def commonest(self, day: date, pool: Pool, phase: str | None = None) -> tuple[str, ...]:
        """The five commonest first codes a judged case on ``day`` may see, ties by code.

        Args:
            day: the judged case's event date.
            pool: ``earlier`` or ``whole``.
            phase: when given, only the cases whose first code has this three-digit phase.

        Returns:
            Up to five codes.
        """
        key = (day.toordinal(), pool, phase)
        if key not in self._commonest:
            codes = (
                self.cases[i].first_code
                for start, stop in _spans(self._days, key[0], pool)
                for i in range(start, stop)
            )
            chosen = (c for c in codes if phase is None or c[:3] == phase)
            self._commonest[key] = tuple(code for code, _ in ranked(chosen)[:TOP])
        return self._commonest[key]


# --- the measures ---


@dataclass(frozen=True)
class Hits:
    """One judged case, one query, one pool: which measures hold the NTSB's first code."""

    found: bool  # found@5: the first code of at least one of the five
    nearest: bool  # nearest@1: the first code of the highest-ranked case
    majority: bool  # majority@5: the commonest first code of the five, ties by rank
    event: bool  # event-only@5: the event (last three digits) of one of the five's first codes


MISSED: Final = Hits(found=False, nearest=False, majority=False, event=False)
FOUND: Final = "found@5"
MEASURES: Final[tuple[tuple[str, Callable[[Hits], bool]], ...]] = (
    (FOUND, lambda hits: hits.found),
    ("nearest@1", lambda hits: hits.nearest),
    ("majority@5", lambda hits: hits.majority),
    ("event-only@5", lambda hits: hits.event),
)


def measure(first: str, five: Sequence[Precedent]) -> Hits:
    """Each measure for one judged case.

    Args:
        first: the NTSB's first occurrence code (six digits).
        five: the search's cases, best first (maybe fewer than five, maybe none).

    Returns:
        Which measures hold ``first``.
    """
    codes = [p.first_code for p in five]
    if not codes:
        return MISSED
    counts = Counter(codes)
    most = max(counts.values())
    majority = next(code for code in codes if counts[code] == most)
    return Hits(
        found=first in codes,
        nearest=codes[0] == first,
        majority=majority == first,
        event=first[3:] in {code[3:] for code in codes},
    )


def query_text(case: CaseResult, query: Query) -> str | None:
    """The answer's text for ``query``; None for a case counted as failed (decision 0136)."""
    answer = scored_answer(case)
    if answer is None:
        return None
    return answer.probable_cause if query == "probable cause" else answer.evidence_narrative


def search_hits(index: Index, case: CaseResult, day: date, query: Query, pool: Pool) -> Hits:
    """The measures for one case: searched from the loop's own words, or missed with no query."""
    text = query_text(case, query)
    if text is None:
        return MISSED
    return measure(case.verdict_occurrence[0], index.search(tokens(text), day, pool))


def control(index: Index, case: CaseResult, day: date, pool: Pool) -> bool:
    """Whether the NTSB's first code is among the pool's five commonest; no answer needed."""
    return case.verdict_occurrence[0] in index.commonest(day, pool)


def phase_codes(index: Index, case: CaseResult, day: date, pool: Pool) -> tuple[str, ...]:
    """The phase-aware control's codes; none for a case with no answer.

    The five commonest first codes of the pool among the cases whose first code has the phase of
    the loop's own answer's first code, ties by code.
    """
    answer = scored_answer(case)
    if answer is None:
        return ()
    return index.commonest(day, pool, answer_codes(answer)[0][:3])


def phase_control(index: Index, case: CaseResult, day: date, pool: Pool) -> bool:
    """The control within the loop's own answer's phase; a case with no answer is not found."""
    return case.verdict_occurrence[0] in phase_codes(index, case, day, pool)


def outcome(found: int, control_count: int) -> str:
    """The committed rule's word for a found count and the control's count."""
    if found < NOT_PROMISING_BELOW or found <= control_count:
        return "not promising"
    if found >= PROMISING_AT:
        return "promising"
    return "in between"


# --- the results ---


@dataclass(frozen=True)
class Results:
    """Every judged case's measures, keyed by (run number, query, pool) and (pool)."""

    hits: Mapping[tuple[int, Query, Pool], Mapping[str, Hits]]
    controls: Mapping[Pool, Mapping[str, bool]]
    phase_controls: Mapping[tuple[int, Pool], Mapping[str, bool]]
    no_query: Mapping[int, frozenset[str]]


def compute(index: Index, runs: Sequence[Run], days: Mapping[str, date]) -> Results:
    """Search and count for every case of every run, in both pools.

    Args:
        index: the pool, indexed.
        runs: run a, then run b.
        days: each judged case's event date.

    Returns:
        The results.
    """
    hits: dict[tuple[int, Query, Pool], dict[str, Hits]] = {}
    phases: dict[tuple[int, Pool], dict[str, bool]] = {}
    controls: dict[Pool, dict[str, bool]] = {pool: {} for pool in POOLS}
    for number, run in enumerate(runs, 1):
        for case in run.cases:
            day = days[case.case_id]
            for pool in POOLS:
                controls[pool][case.case_id] = control(index, case, day, pool)
                phases.setdefault((number, pool), {})[case.case_id] = phase_control(
                    index, case, day, pool
                )
                for query in QUERIES:
                    hits.setdefault((number, query, pool), {})[case.case_id] = search_hits(
                        index, case, day, query, pool
                    )
    no_query = {
        number: frozenset(c.case_id for c in run.cases if scored_answer(c) is None)
        for number, run in enumerate(runs, 1)
    }
    return Results(hits, controls, phases, no_query)


# --- the lines ---


def share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.1%})" if whole else f"{part} of {whole}"


def with_interval(part: int, whole: int) -> str:
    if not whole:
        return share(part, whole)
    low, high = wilson(part, whole)
    return f"{share(part, whole)} [{low:.1%}, {high:.1%}]"


def _split(
    ids: Sequence[str], fatal: Mapping[str, bool], flags: Mapping[str, bool], *, interval: bool
) -> str:
    """How many of ``ids`` are flagged: all, then fatal, then non-fatal, each of its whole."""
    show = with_interval if interval else share
    parts = [
        show(sum(flags[i] for i in chosen), len(chosen))
        for chosen in (ids, [i for i in ids if fatal[i]], [i for i in ids if not fatal[i]])
    ]
    return f"{parts[0]}; fatal {parts[1]}; non-fatal {parts[2]}"


def _whole(ids: Sequence[str], fatal: Mapping[str, bool]) -> str:
    deaths = sum(fatal[i] for i in ids)
    return f"{len(ids)} cases ({deaths} fatal, {len(ids) - deaths} non-fatal)"


def _label(code: str, tables: CodeTables) -> str:
    return f"{code} {tables.phases.get(code[:3], '?')} / {tables.events.get(code[3:], '?')}"


def rule_lines(results: Results, ids: Sequence[str], run_ids: Sequence[str]) -> list[str]:
    """The committed rule applied on run a's headline group; run b beside it.

    Args:
        results: every case's measures.
        ids: the headline group's case ids.
        run_ids: run a's and run b's ids.

    Returns:
        The lines.
    """
    n = len(ids)
    found = {
        (number, query): sum(results.hits[(number, query, "earlier")][i].found for i in ids)
        for number in (1, 2)
        for query in QUERIES
    }
    controlled = sum(results.controls["earlier"][i] for i in ids)
    pc, en = found[(1, "probable cause")], found[(1, "evidence narrative")]
    better: Query = "probable cause" if pc >= en else "evidence narrative"
    chosen = found[(1, better)]
    lines = [
        "## The rule (committed in a0c6cc6, before this script existed)",
        "",
        PREDICTION,
    ]
    if n != PREDICTED_CASES:
        lines.append(
            f"Note: the prediction names {PREDICTED_CASES} cases; this group holds {n}. The "
            "thresholds are applied as written."
        )
    lines += [
        f'Run a ({run_ids[0]}), "{HEADLINE}", date-limited pool (earlier cases only):',
        f"- found@5, probable-cause query: {with_interval(pc, n)}",
        f"- found@5, evidence-narrative query: {with_interval(en, n)}",
        f"- control (the pool's five commonest first codes, no search): {with_interval(controlled, n)}",
        f"- the better query (a tie goes to the probable cause): {better}, found in "
        f"{chosen} of {n}, against the control's {controlled}",
        f"Run b ({run_ids[1]}), beside it, decides nothing: found@5 probable-cause query "
        f"{share(found[(2, 'probable cause')], n)}, evidence-narrative query "
        f"{share(found[(2, 'evidence narrative')], n)}; control {share(controlled, n)}",
        f"Outcome: {outcome(chosen, controlled)}",
    ]
    return lines


def method_lines(pool: Mapping[str, int], index: Index, tables: CodeTables) -> list[str]:
    """How the pool was built and searched, with its counts and its commonest first codes.

    Args:
        pool: the pool's counts (``statistics pool``, ``no text``, ``no code``).
        index: the kept pool, indexed.
        tables: the code tables, for labels.

    Returns:
        The lines.
    """
    years = sorted({p.event_date.year for p in index.cases})
    span = f"event years {years[0]}-{years[-1]}" if years else "no case"
    commonest = ranked(p.first_code for p in index.cases)[:TOP]
    return [
        "## Method",
        "",
        f"Pool: the S3 statistics pool, {STAGES[STAGE].built_from}: "
        f"{pool['statistics pool']} cases; kept, each with an NTSB probable-cause text and at "
        f"least one occurrence code: {len(index.cases)} ({span}); left out: {pool['no text']} "
        f"with no probable-cause text, {pool['no code']} more with no occurrence code. The "
        "judged cases' event dates come from the same processed file.",
        f"Search: BM25 (k1 = {K1}, b = {B}; IDF = ln(1 + (N - df + 0.5) / (df + 0.5))) over "
        "the lower-cased word tokens ([a-z0-9]+) of the pool's NTSB probable-cause texts, less "
        f"a fixed list of {len(STOP_WORDS)} English stop words. Each distinct query word counts "
        "once; a pool case sharing no word with the query is not ranked. The five "
        "highest-ranked, ties by case id ascending.",
        "Date-limited pool (the headline): only pool cases whose event date is strictly earlier "
        "than the judged case's; N, df and the average length over that set.",
        "Whole pool: every pool case except those on the judged case's event date; statistics "
        "over that set.",
        "Queries: the final answer's probable cause and, separately, its evidence narrative. A "
        "case counted as failed (decision 0136 item 1) has no query and is not found; it stays "
        "in the denominator.",
        "Measures: found@5, the NTSB's first occurrence code (six digits) is the first code of "
        "at least one of the five; nearest@1, of the highest-ranked; majority@5, the commonest "
        "first code among the five (ties by rank) is it; event-only@5, its event (last three "
        "digits) is that of one of the five's first codes.",
        "Control (no search): the NTSB's first code is among the five commonest first codes of "
        "the same pool (ties by code ascending); every case counts, failed or not, as it needs "
        "no answer. Phase-aware control: the five commonest first codes among the pool cases "
        "whose first code has the phase of the loop's own answer's first code; a case with no "
        "answer is not found.",
        "The five commonest first codes of the kept pool, for reference: "
        + "; ".join(f"{_label(code, tables)} ({count})" for code, count in commonest)
        + ".",
    ]


def _block(
    results: Results, key: tuple[int, Query, Pool], ids: Sequence[str], fatal: Mapping[str, bool]
) -> list[str]:
    hits = results.hits[key]
    lines = []
    for name, held in MEASURES:
        flags = {i: held(hits[i]) for i in ids}
        lines.append(f"  - {name}: {_split(ids, fatal, flags, interval=name == FOUND)}")
    return lines


def _away(
    results: Results, key: tuple[int, Query, Pool], ids: Sequence[str], fatal: Mapping[str, bool]
) -> list[str]:
    """On cases the loop got right: how often the precedents point away from the answer."""
    hits = results.hits[key]
    return [
        "  - the nearest case's first code differs from the NTSB's (= the loop's) first code: "
        + _split(ids, fatal, {i: not hits[i].nearest for i in ids}, interval=False),
        "  - the NTSB's first code is not among the five: "
        + _split(ids, fatal, {i: not hits[i].found for i in ids}, interval=False),
    ]


_POOL_TITLES: Final[Mapping[Pool, str]] = {
    "earlier": "date-limited pool (only cases strictly earlier than the judged case)",
    "whole": "whole pool (cases on the judged case's event date left out)",
}


def set_lines(  # noqa: PLR0913 -- one keyword per piece of the set's report.
    title: str,
    ids: Sequence[str],
    *,
    results: Results,
    fatal: Mapping[str, bool],
    days: Mapping[str, date],
    index: Index,
    run_ids: Sequence[str],
    right: bool,
) -> list[str]:
    """One set of judged cases: each pool, each run, each query, every measure.

    Args:
        title: the set's name.
        ids: its case ids.
        results: every case's measures.
        fatal: whether each case is fatal.
        days: each case's event date.
        index: the pool, indexed (for the sizes).
        run_ids: run a's and run b's ids.
        right: whether the loop's first code is the NTSB's in every case (always right).

    Returns:
        The lines.
    """
    thin = sum(index.size(days[i], "earlier") < TOP for i in ids)
    lines = [
        f"## {title}: {_whole(ids, fatal)}",
        "",
        f"Cases whose date-limited pool holds fewer than {TOP} cases: {share(thin, len(ids))}",
    ]
    for pool in POOLS:
        controls = results.controls[pool]
        lines += [
            "",
            f"### {_POOL_TITLES[pool]}",
            f"control (no search): {_split(ids, fatal, controls, interval=True)}",
        ]
        for number, run_id in enumerate(run_ids, 1):
            missing = sum(i in results.no_query[number] for i in ids)
            lines.append(
                f"run {'ab'[number - 1]} ({run_id}); no query (failed or not scored): "
                f"{share(missing, len(ids))}"
            )
            for query in QUERIES:
                key = (number, query, pool)
                lines.append(f"  {query} query:")
                lines += _block(results, key, ids, fatal)
                if right:
                    lines += _away(results, key, ids, fatal)
            phases = results.phase_controls[(number, pool)]
            lines.append(f"  phase-aware control: {_split(ids, fatal, phases, interval=True)}")
    return lines


def report(  # noqa: PLR0913 -- one keyword per piece of the report.
    runs: Sequence[Run],
    groups: Mapping[Group, Sequence[str]],
    *,
    results: Results,
    days: Mapping[str, date],
    index: Index,
    pool: Mapping[str, int],
    source: str,
    tables: CodeTables,
) -> str:
    """The whole report: the head, the rule, the method, then each set of judged cases.

    Args:
        runs: run a, then run b.
        groups: the arm C groups' case ids.
        results: every case's measures.
        days: each judged case's event date.
        index: the kept pool, indexed.
        pool: the pool's counts.
        source: where the groups file is, for the head.
        tables: the code tables.

    Returns:
        The report's text.
    """
    run_ids = [run.run_id for run in runs]
    fatal = {c.case_id: c.fatal for c in runs[0].cases}
    every = sorted(fatal)
    head = [
        "S3.1 precedent probe on dev-400 (scripts/exploratory/s3_precedent_probe.py; S3.1 Task 15)",
        "Exploratory (decision 0059): free and offline, no model call; it sets no bar and tunes "
        "nothing. Whether earlier closed cases, found from the loop's own words, hold the "
        "NTSB's first occurrence code.",
        "Counts only: no case number and no text from any record. Every count is printed with "
        "its denominator; found@5 and the controls with a 95% Wilson interval.",
        f"run a = {run_ids[0]}",
        f"run b = {run_ids[1]} (printed beside run a; decides nothing)",
        f"Groups: {SPLIT}, from {source}: "
        + "; ".join(f"{name} {_whole(groups[name], fatal)}" for name in GROUPS),
    ]
    blocks = [
        "\n".join(head),
        "\n".join(rule_lines(results, groups[HEADLINE], run_ids)),
        "\n".join(method_lines(pool, index, tables)),
    ]
    sets: list[tuple[str, Sequence[str], bool]] = [
        (f"{SPLIT}, {name}", groups[name], name == "always right") for name in GROUPS
    ]
    sets.append(("all cases (failed cases counted as not found)", every, False))
    blocks += [
        "\n".join(
            set_lines(
                title,
                ids,
                results=results,
                fatal=fatal,
                days=days,
                index=index,
                run_ids=run_ids,
                right=right,
            )
        )
        for title, ids, right in sets
    ]
    return "\n\n".join(blocks)


# --- reading ---


def load_run(run_id: str) -> Run:
    """One finished ``dev-400`` arm C run, through ``s3_case_groups``' own refusals."""
    run = s3_case_groups.load(run_id)
    if run.arm != ARM:
        _refuse(f"{run_id} is arm {run.arm}; the precedent probe reads arm C runs only")
    return run


def read_groups(path: Path, runs: Sequence[Run]) -> dict[Group, Sequence[str]]:
    """The arm C groups of a ``groups.json`` drawn over every run, after their refusals.

    Through ``read_group``: a missing groups file, one not on ``dev-400``, one not drawn over
    every run, one without arm C groups. Then a group case the runs do not hold, and any case of
    the runs whose verdict holds no occurrence code.

    Args:
        path: the groups file ``scripts/s3_case_groups.py`` wrote.
        runs: the runs read, run a first; the groups' case ids are read as drawn over run a.

    Returns:
        Each arm C group's case ids, sorted.
    """
    groups: dict[Group, Sequence[str]] = {}
    for name in GROUPS:
        listed = [read_group(path, split=SPLIT, group=name, run_id=run.run_id) for run in runs]
        groups[name] = listed[0]
    held = {c.case_id for c in runs[0].cases}
    absent = sorted({i for ids in groups.values() for i in ids} - held)
    if absent:
        _refuse(f"the runs do not hold {len(absent)} case(s) of the groups")
    if any(not c.verdict_occurrence for run in runs for c in run.cases):
        _refuse("a judged case holds no NTSB occurrence code, so no first code to look for")
    return groups


@dataclass(frozen=True)
class PoolText:
    """One kept pool case as read: its id, event date, probable-cause text and occurrence codes.

    ``findings`` are the finding codes the NTSB flagged as in the probable cause, by finding
    number (``fields.finding_codes_in_cause``; empty when none is flagged), read in the same
    pass as the text, after ``check_pool``. The precedent probe never uses them; the
    finding-consistency probe does.
    """

    case_id: str
    event_date: date
    text: str
    sequence: tuple[str, ...]
    findings: tuple[str, ...] = ()


def read_pool_texts(processed: Path) -> tuple[list[PoolText], dict[str, str], dict[str, int]]:
    """The S3 statistics pool with its texts, every development case's event date, and counts.

    Two streaming passes over the processed file. The first is ``coding_stats``' own pool
    (``pool_cases``, guarded by ``check_pool`` before any text is read); the second reads the
    NTSB probable-cause text and the flagged-as-cause finding codes of the pool's cases only.
    Kept: a case with a probable-cause text and at least one occurrence code.

    Args:
        processed: the processed folder.

    Returns:
        The kept pool cases, in the pool's order; each development case's ISO event date by id
        (a judged case is not in the pool, so its date is found here); and the counts
        (``statistics pool``, ``no text``, ``no code``).

    Raises:
        LeakageError: the pool holds a sample case or a non-development case.
    """
    names = STAGES[STAGE].excluded
    excluded = frozenset(i for name in names for i in samples.sample_ids(name))
    splits: dict[str, str] = {}
    dates: dict[str, str] = {}

    def tapped() -> Iterator[Row]:
        for row in processed_rows(processed):
            splits[row[0]] = row[2]
            if row[2] == "dev":
                dates[row[0]] = row[1]
            yield row

    cases, ids = pool_cases(tapped(), excluded=excluded)
    check_pool(ids, excluded=excluded, splits=splits)
    sequences = {case_id: case.sequence for case_id, case in zip(ids, cases, strict=True)}
    texts: dict[str, str | None] = {}
    flagged: dict[str, tuple[str, ...]] = {}
    for case_id, _date, _split, _class, raw in processed_rows(processed):
        if case_id in sequences:
            texts[case_id] = fields.probable_cause(raw)
            flagged[case_id] = fields.finding_codes_in_cause(raw)
    kept = [
        PoolText(i, date.fromisoformat(dates[i]), text, sequences[i], flagged[i])
        for i in ids
        if (text := texts.get(i)) and sequences[i]
    ]
    no_text = sum(not texts.get(i) for i in ids)
    counts = {
        "statistics pool": len(ids),
        "no text": no_text,
        "no code": len(ids) - no_text - len(kept),
    }
    return kept, dates, counts


def read_pool(
    processed: Path, judged: Iterable[str]
) -> tuple[list[Precedent], dict[str, date], dict[str, int]]:
    """The S3 statistics pool as precedents, the judged cases' event dates, and the pool's counts.

    ``read_pool_texts``, with each kept case's text cut into the search's words.

    Args:
        processed: the processed folder.
        judged: the judged cases' ids.

    Returns:
        The kept pool cases, the judged cases' dates, and the counts.

    Raises:
        LeakageError: the pool holds a sample case or a non-development case.
    """
    wanted = frozenset(judged)
    texts, dates, counts = read_pool_texts(processed)
    kept = [Precedent(c.case_id, c.event_date, c.sequence[0], tokens(c.text)) for c in texts]
    absent = sorted(i for i in wanted if i not in dates)
    if absent:
        _refuse(f"{len(absent)} judged case(s) have no event date in the processed file")
    return kept, {i: date.fromisoformat(dates[i]) for i in wanted}, counts


def _source(path: Path) -> str:
    """The groups file as the report names it: under the runs folder, or by its name alone."""
    runs_dir = Settings().runs_dir.resolve()
    resolved = path.resolve()
    return (
        resolved.relative_to(runs_dir).as_posix()
        if resolved.is_relative_to(runs_dir)
        else path.name
    )


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="s3_precedent_probe")
    parser.add_argument("--runs", nargs=2, required=True, metavar=("RUN_A", "RUN_B"))
    parser.add_argument("--groups", type=Path, required=True, help="s3_case_groups' groups.json")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the probe's counts and the rule's outcome.

    Args:
        argv: the command line.

    Returns:
        0.
    """
    args = _arguments(argv)
    if args.runs[0] == args.runs[1]:
        _refuse("a run is named twice; run a and run b are two different runs")
    runs = [load_run(run_id) for run_id in args.runs]
    groups = read_groups(args.groups, runs)
    held = {c.case_id for c in runs[0].cases}
    kept, days, pool = read_pool(Settings().data_dir / "processed", held)
    index = Index(kept)
    text = report(
        runs,
        groups,
        results=compute(index, runs, days),
        days=days,
        index=index,
        pool=pool,
        source=_source(args.groups),
        tables=load_tables(),
    )
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
