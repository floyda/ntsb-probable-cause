"""Where an arm B run's first occurrence guess lands in the NTSB's own ordered sequence.

Status
    Repeatable, free: reads one finished run folder, makes no model call. Counts and code
    labels only (decision 0024): no case number, no title, no prose. Written for the S2.6
    final review (I6), which found decision 0089 quoting these counts before any committed
    script produced them. Extended in S2.7 (spec §4.1): the six groups, finding depth,
    confidence by group, the model's own words, and churn against a second run.

Why
    The NTSB codes every accident with an ordered sequence of occurrence codes; the first is
    the defining event, and it is the one the headline top-1 scores. A first guess that is
    somewhere in the sequence but not first is a different kind of miss from one that is
    nowhere in it: the model named an event the NTSB also recorded, but not the one the NTSB
    chose to put first. This script separates the two, and lists the most common pairs of
    (the NTSB's first event, the model's first-guess event) among the misses.

What it reads
    ``CaseResult.verdict_occurrence`` is the NTSB's ordered tuple (first = defining event);
    the model's guesses are ``steps[-1].hypothesis.occurrence`` (up to three, ranked; stage 2
    refines findings only). A six-digit occurrence code is a three-digit phase and a
    three-digit event. A case is counted when it was scored (``scores`` set, a step
    recorded). An abstained case counts as a miss on every rate, as in the run's own scores,
    and is left out of the table of misses.

Refusals
    Development runs only: a run whose id or recorded sample names a held-out sample, or any
    case outside the development split, is refused before its cases are read. Arm B only.

Usage
    uv run python -m scripts.occurrence_misses --run RUN_ID [--out PATH]
"""

import argparse
import statistics
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.misses import (
    GROUPS,
    FindingDepth,
    finding_depth,
    miss_group,
    names_event,
)
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.scoring.report import provenance
from ntsb_probable_cause.settings import Settings

TOP_MISSES = 12
_PHASE = slice(0, 3)
_EVENT = slice(3, 6)


def _share(count: int, total: int) -> str:
    return f"{count} of {total} ({count / total:.1%})" if total else f"{count} of 0"


def _refuse_unless_development_arm_b(run_id: str, record: RunRecord) -> None:
    """Held-out and sealed runs never feed this script; nor does any arm but B."""
    try:
        samples.refuse_unless_development(run_id, record.sample)
    except ConfigurationError as error:
        raise SystemExit(f"occurrence_misses: {error}") from error
    if record.arm != "B":
        raise SystemExit(f"occurrence_misses: {run_id} is arm {record.arm}, not arm B")


def summarise(cases: Sequence[CaseResult], tables: CodeTables) -> str:
    """The counts: rates over scored cases, sequence lengths, and the commonest misses."""
    scored = [c for c in cases if c.scores is not None and c.steps]
    total = len(scored)
    abstained = 0
    no_truth = 0
    first_code = first_event = first_phase = top1_anywhere = any3_anywhere = 0
    lengths: Counter[int] = Counter()
    misses: Counter[tuple[str, str]] = Counter()
    for case in scored:
        truth = case.verdict_occurrence
        lengths[len(truth)] += 1
        hypothesis = case.steps[-1].hypothesis
        codes = [g.phase + g.event for g in hypothesis.occurrence]
        top1 = codes[0]
        if hypothesis.abstain:
            abstained += 1
            continue
        if not truth:
            no_truth += 1
            continue
        first = truth[0]
        first_code += top1 == first
        first_event += top1[_EVENT] == first[_EVENT]
        first_phase += top1[_PHASE] == first[_PHASE]
        top1_anywhere += top1 in truth
        any3_anywhere += any(code in truth for code in codes)
        if top1[_EVENT] != first[_EVENT]:
            misses[(first[_EVENT], top1[_EVENT])] += 1

    def label(event: str) -> str:
        return tables.events.get(event, f"event {event}")

    lines = [
        f"scored cases: {total} (abstained, counted as misses on every rate: {abstained}; "
        f"NTSB sequence empty, counted as misses: {no_truth})",
        f"first guess = the NTSB's first code: {_share(first_code, total)}",
        f"first guess's event = the first event (any phase): {_share(first_event, total)}",
        f"first guess's phase = the first phase: {_share(first_phase, total)}",
        f"first guess anywhere in the NTSB's sequence: {_share(top1_anywhere, total)}",
        f"any of the 3 guesses anywhere in the NTSB's sequence: {_share(any3_anywhere, total)}",
        "NTSB sequence length (codes per case): "
        + ", ".join(f"{n}: {lengths[n]}" for n in sorted(lengths)),
        "",
        f"most common misses by event, NTSB's first event -> model's first-guess event "
        f"(the {min(TOP_MISSES, len(misses))} commonest of {len(misses)} pairs; "
        f"{sum(misses.values())} cases whose first-guess event is not the first event):",
    ]
    lines += [
        f"- {count}  {label(truth_event)} -> {label(guess_event)}"
        for (truth_event, guess_event), count in sorted(
            misses.items(), key=lambda item: (-item[1], item[0])
        )[:TOP_MISSES]
    ]
    return "\n".join(lines)


def _guesses(case: CaseResult) -> tuple[str, ...]:
    return tuple(g.phase + g.event for g in case.steps[-1].hypothesis.occurrence)


def _scored(cases: Sequence[CaseResult]) -> list[CaseResult]:
    return [c for c in cases if c.scores is not None and c.steps]


def detail(cases: Sequence[CaseResult], tables: CodeTables) -> str:
    """S2.7 §4.1: the six groups, confidence, finding depth, and the model's own words."""
    scored = _scored(cases)
    by_group: dict[str, list[CaseResult]] = {g: [] for g in GROUPS}
    depth = FindingDepth(0, 0, 0, 0, 0)
    named = asked = 0
    for case in scored:
        hypothesis = case.steps[-1].hypothesis
        group = miss_group(_guesses(case), case.verdict_occurrence, abstain=hypothesis.abstain)
        by_group[group].append(case)
        depth = depth + finding_depth(
            hypothesis.finding_codes(tables), case.verdict_findings_in_cause
        )
        if group not in ("exact", "abstained") and case.verdict_occurrence:
            said = names_event(
                f"{hypothesis.evidence_narrative} {hypothesis.probable_cause}",
                case.verdict_occurrence[0][3:],
            )
            if said is not None:
                asked += 1
                named += said
    total = len(scored)
    lines = ["", "## the six groups (first guess)"]
    for group in GROUPS:
        members = by_group[group]
        median = (
            f"{statistics.median(c.steps[-1].hypothesis.confidence for c in members):.2f}"
            if members
            else "-"
        )
        lines.append(f"- {group}: {_share(len(members), total)}; median confidence {median}")
    lines += [
        "",
        "## finding depth (the NTSB's flagged findings, each at its deepest match)",
        f"flagged {depth.flagged}: found {depth.found}; item right, modifier wrong "
        f"{depth.item_right_modifier_wrong}; category right, item wrong "
        f"{depth.category_right_item_wrong}; category wrong {depth.category_wrong}",
        "",
        "## the model's own words (misses whose NTSB event has a phrase list, "
        "scoring/misses.py:EVENT_PHRASES)",
        f"the model's narrative or cause names the NTSB's defining event: {_share(named, asked)}",
    ]
    return "\n".join(lines)


def churn(a: Sequence[CaseResult], b: Sequence[CaseResult]) -> str:
    """Two runs on the same cases: how many first guesses changed, and top-1 gained and lost."""
    right = {c.case_id: c for c in _scored(b)}
    pairs = [(c, right[c.case_id]) for c in _scored(a) if c.case_id in right]
    same = sum(_guesses(x)[:1] == _guesses(y)[:1] for x, y in pairs)
    gained = sum(
        bool(x.scores and x.scores.occurrence_top1) and not (y.scores and y.scores.occurrence_top1)
        for x, y in pairs
    )
    lost = sum(
        bool(y.scores and y.scores.occurrence_top1) and not (x.scores and x.scores.occurrence_top1)
        for x, y in pairs
    )
    return "\n".join(
        [
            "",
            "## churn against the second run (cases scored in both)",
            f"same first guess: {same} of {len(pairs)}",
            f"top-1 gained {gained}, lost {lost} (this run against the second)",
        ]
    )


def _read_run(run_id: str) -> tuple[RunRecord, list[CaseResult]]:
    """One development arm B run's record and cases, after every refusal."""
    folder = Settings().runs_dir / run_id
    try:
        samples.refuse_unless_development(run_id, None)
    except ConfigurationError as error:
        raise SystemExit(f"occurrence_misses: {error}") from error
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    _refuse_unless_development_arm_b(run_id, record)
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(case.split != "dev" for case in cases):
        raise SystemExit(f"occurrence_misses: {run_id} holds a case outside the dev split")
    return record, cases


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, one run's counts (and churn against a second)."""
    parser = argparse.ArgumentParser(prog="occurrence_misses")
    parser.add_argument("--run", required=True, metavar="RUN_ID")
    parser.add_argument("--against", default=None, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    record, cases = _read_run(args.run)
    tables = load_tables()
    text = (
        "occurrence misses (scripts/occurrence_misses.py; counts only, decision 0024)\n"
        + provenance(record).rstrip("\n")
        + "\n\n"
        + summarise(cases, tables)
        + "\n"
        + detail(cases, tables)
    )
    if args.against is not None:
        _other_record, other = _read_run(args.against)
        text += "\n" + churn(cases, other) + f"\nsecond run: {args.against}"
    print(text)
    if args.out is not None:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
