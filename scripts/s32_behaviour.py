"""Results 1 and 4, counted from the noise-floor trails (S3.2 Task 9).

Status
    Live measurement for S3.2 (spec §9.1 and §9.4), free: reads finished ``dev-400`` arm C run
    folders and makes no model call. Counts only (decision 0024): the stated effects are
    counted, never printed. Its output is ``docs/results/s32-behaviour-dev.txt``
    (``make s32-behaviour-dev RUNS="<a> <b>"``). Task 11 imports :func:`read_counts` and
    :func:`effects_naming_codes` and :func:`result1_holds` to read the held-out loop run with
    the same code.

Result 1: a pipeline in disguise (spec §9.1)
    The result holds when the loop reads every offered document on more than half of the cases,
    or calls the coding tools in arm B's fixed order on more than half.

    * **Counted:** every case with a row in the trail. This is the denominator of the fixed
      order. The two shares have two denominators, as the spec's own early figures did.
    * **Reads everything:** the documents offered are the union of ``AgentCall.offered`` over the
      two read-choice steps (``choice1``, ``choice2``). A document is read when an accepted
      ``choose_documents`` call decided ``read`` on it and it was in that call's ``offered``: a
      decision on a document not on offer reads nothing (decision 0134), and a rejected call
      reads nothing. The case reads everything when something was on offer and every offered
      document was read. A case with nothing on offer leaves this count (``with_offer`` is its
      denominator).
    * **Fixed order:** the order in which the case first used each coding tool (accepted calls,
      in call order) is exactly ``describe_codes``, ``occurrence_usage``, ``past_findings``,
      ``suggest_codes``.
    * The counts are repeated by fatal and non-fatal (from ``cases.jsonl``) and by the number of
      documents offered (none, 1, 2 to 4, 5 or more).

Result 4: the stated effects (spec §9.4)
    Of the ``expected_effect`` texts given for documents that were read, how many name an event
    or a finding category. The effect, lower-cased, must contain one of three things:

    * an event label of 6 characters or more, lower-cased (the event route);
    * the *leaf* of a category label, lower-cased: the text after the last `` — `` of a label such
      as "Aircraft — Aircraft systems — Fuel system". The leaf must be 6 characters or more and
      not "(general)" (the category route). The whole label is a three-part path that free text
      never contains, so matching it could never fire (controller's ruling, Task 9 review);
    * an event code as a whole word (the code route).

    Printed as a count and a share of the effects, with how many effects matched each route
    (an effect that matches two routes is in both counts, and once in the total).

Usage
    uv run python -m scripts.s32_behaviour RUN_ID [RUN_ID ...] [--out PATH]
"""

import argparse
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ntsb_probable_cause.agent.schemas import CODING_TOOLS, ChooseDocuments
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.records import CaseResult
from scripts._s3_runs import load_runs, write_result

PROG: Final = "s32_behaviour"
FIXED_ORDER: Final = ("describe_codes", "occurrence_usage", "past_findings", "suggest_codes")
_CHOICES: Final = frozenset({"choice1", "choice2"})
_MIN_LABEL: Final = 6
_BUCKETS: Final = ("none", "1", "2-4", "5 or more")


@dataclass(frozen=True)
class Tally:
    """The three counts of result 1 over some cases.

    Attributes:
        counted: the cases with a row in the trail.
        with_offer: of those, the cases with at least one document on offer.
        read_everything: of ``with_offer``, the cases that read every document offered.
        fixed_order: of ``counted``, the cases that first used the coding tools in arm B's order.
    """

    counted: int = 0
    with_offer: int = 0
    read_everything: int = 0
    fixed_order: int = 0


@dataclass(frozen=True)
class ReadCounts:
    """Result 1's counts over a run, and the same counts by fatal and by documents offered."""

    counted: int
    with_offer: int
    read_everything: int
    fixed_order: int
    by_fatal: dict[str, Tally] = field(default_factory=dict)
    by_offered: dict[str, Tally] = field(default_factory=dict)


def _offered_and_read(rows: Sequence[AgentCall]) -> tuple[set[int], set[int]]:
    offered: set[int] = set()
    read: set[int] = set()
    for call in rows:
        if call.step not in _CHOICES:
            continue
        offered |= set(call.offered)
        if call.tool == "choose_documents" and call.protocol_error is None:
            decisions = ChooseDocuments.model_validate(call.arguments).decisions
            read |= {d.document for d in decisions if d.read and d.document in call.offered}
    return offered, read


def _first_use_order(rows: Sequence[AgentCall]) -> tuple[str, ...]:
    order: list[str] = []
    for call in rows:
        if call.tool in CODING_TOOLS and call.protocol_error is None and call.tool not in order:
            order.append(call.tool)
    return tuple(order)


def _bucket(offered: int) -> str:
    if offered == 0:
        return "none"
    if offered == 1:
        return "1"
    return "2-4" if offered <= 4 else "5 or more"  # noqa: PLR2004 -- the spec's bands


def _add(tally: Tally, with_offer: bool, everything: bool, fixed: bool) -> Tally:
    return Tally(
        tally.counted + 1,
        tally.with_offer + with_offer,
        tally.read_everything + everything,
        tally.fixed_order + fixed,
    )


def read_counts(calls: Sequence[AgentCall], cases: Sequence[CaseResult]) -> ReadCounts:
    """Result 1's counts for one run (spec §9.1).

    Args:
        calls: the run's ``trail.jsonl`` rows.
        cases: the run's case results, for fatal and non-fatal. A case with no row in the trail
            is not counted.

    Returns:
        The counts overall, by fatal and non-fatal, and by documents offered.
    """
    by_case: dict[str, list[AgentCall]] = defaultdict(list)
    for call in calls:
        by_case[call.case_id].append(call)
    total = Tally()
    by_fatal = {"fatal": Tally(), "non-fatal": Tally()}
    by_offered = {name: Tally() for name in _BUCKETS}
    for case in cases:
        if case.case_id not in by_case:
            continue
        rows = sorted(by_case[case.case_id], key=lambda c: (c.trigger, c.call_index))
        offered, read = _offered_and_read(rows)
        args = (
            bool(offered),
            bool(offered) and offered <= read,
            _first_use_order(rows) == FIXED_ORDER,
        )
        total = _add(total, *args)
        key = "fatal" if case.fatal else "non-fatal"
        by_fatal[key] = _add(by_fatal[key], *args)
        name = _bucket(len(offered))
        by_offered[name] = _add(by_offered[name], *args)
    return ReadCounts(
        total.counted,
        total.with_offer,
        total.read_everything,
        total.fixed_order,
        by_fatal,
        by_offered,
    )


@dataclass(frozen=True)
class Routes:
    """Result 4's counts: the effects on documents read, and how many name an event or category.

    Attributes:
        total: the stated effects on documents read.
        naming: of those, the effects that match at least one route.
        event_label: effects that contain an event label.
        category_leaf: effects that contain a category label's leaf.
        event_code: effects that contain an event code as a whole word.
    """

    total: int
    naming: int
    event_label: int
    category_leaf: int
    event_code: int


def category_leaves(tables: CodeTables) -> list[str]:
    """The lower-cased leaf of each category label that can be searched for in free text.

    The leaf is the text after the last `` — ``. A leaf shorter than 6 characters or equal to
    ``(general)`` is left out, and a leaf shared by two categories is listed once.
    """
    leaves = {label.rsplit(" — ", 1)[-1].lower() for label in tables.categories.values()}
    return sorted(leaf for leaf in leaves if len(leaf) >= _MIN_LABEL and leaf != "(general)")


def effect_routes(calls: Sequence[AgentCall], tables: CodeTables) -> Routes:
    """Result 4's measure by route (spec §9.4).

    Args:
        calls: a run's ``trail.jsonl`` rows.
        tables: the code tables, for the labels and the event codes.

    Returns:
        The counts. The effects are those of accepted read choices, on documents that were on
        offer and decided ``read``.
    """
    events = [label.lower() for label in tables.events.values() if len(label) >= _MIN_LABEL]
    leaves = category_leaves(tables)
    codes = re.compile(r"\b(?:" + "|".join(re.escape(c) for c in tables.events) + r")\b")
    total = naming = by_event = by_category = by_code = 0
    for call in calls:
        if call.step not in _CHOICES or call.tool != "choose_documents" or call.protocol_error:
            continue
        for decision in ChooseDocuments.model_validate(call.arguments).decisions:
            if not (decision.read and decision.document in call.offered):
                continue
            lowered = decision.expected_effect.lower()
            hit = (
                any(label in lowered for label in events),
                any(leaf in lowered for leaf in leaves),
                codes.search(decision.expected_effect) is not None,
            )
            total += 1
            naming += any(hit)
            by_event += hit[0]
            by_category += hit[1]
            by_code += hit[2]
    return Routes(total, naming, by_event, by_category, by_code)


def effects_naming_codes(calls: Sequence[AgentCall], tables: CodeTables) -> tuple[int, int]:
    """Result 4's measure: the stated effects that name an event or a category (spec §9.4).

    Returns:
        ``(effects naming an event or category, effects on documents read)``; see
        :func:`effect_routes` for the three routes and what an effect is.
    """
    routes = effect_routes(calls, tables)
    return routes.naming, routes.total


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.1%})" if whole else f"{part} of {whole}"


def _more_than_half(part: int, whole: int) -> bool:
    return 2 * part > whole


def _tally_line(name: str, t: Tally) -> str:
    return (
        f"- {name}: {t.counted} counted; read every document on offer "
        f"{_share(t.read_everything, t.with_offer)} of those with documents on offer; "
        f"fixed order {_share(t.fixed_order, t.counted)}"
    )


def result1_holds(counts: ReadCounts) -> bool:
    """Whether result 1 holds: more than half on either reading (spec §9.1).

    The loop reads every offered document on more than half of the cases *with documents on
    offer* (``with_offer`` is that share's denominator: a case with nothing on offer leaves the
    count), or it first uses the coding tools in arm B's order on more than half of *all cases
    counted* (``counted`` is that share's denominator). "More than half" is strict: exactly half
    does not hold.
    """
    return _more_than_half(counts.read_everything, counts.with_offer) or _more_than_half(
        counts.fixed_order, counts.counted
    )


def run_lines(label: str, counts: ReadCounts, routes: Routes) -> list[str]:
    """One run's block: result 1 with its slices, then result 4's measure."""
    holds = result1_holds(counts)
    return [
        f"## run {label}",
        f"run {label}: {counts.counted} cases counted, {counts.with_offer} of them with documents "
        "on offer",
        f"read every document on offer: {_share(counts.read_everything, counts.with_offer)} of "
        "the cases with documents on offer",
        f"first used the coding tools in arm B's fixed order: "
        f"{_share(counts.fixed_order, counts.counted)} of the cases counted",
        f"result 1: {'holds' if holds else 'does not hold'} (more than half on either)",
        "by fatal and non-fatal:",
        *(_tally_line(name, t) for name, t in counts.by_fatal.items()),
        "by documents offered:",
        *(_tally_line(name, t) for name, t in counts.by_offered.items()),
        f"result 4's measure: {_share(routes.naming, routes.total)} stated effects on documents "
        "read name an event or a finding category (an event label, a category label's leaf, or "
        "an event code as a whole word)",
        f"by route (an effect can match more than one): event label {routes.event_label}, "
        f"category leaf {routes.category_leaf}, event code {routes.event_code}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, results 1 and 4 for each run."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("runs", nargs="+", metavar="RUN_ID", help="finished dev-400 arm C run ids")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    runs = load_runs(PROG, args.runs)
    tables = load_tables()
    lines = [
        "S3.2 behaviour counts (scripts/s32_behaviour.py; spec §9.1 and §9.4)",
        "Counts only: no case number, and the stated effects are counted, never printed.",
        *(f"run {run.label} = {run.record.run_id}" for run in runs),
    ]
    for run in runs:
        counts = read_counts(run.calls, run.cases)
        lines += ["", *run_lines(run.label, counts, effect_routes(run.calls, tables))]
    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
