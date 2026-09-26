"""Where an arm B run's first occurrence guess lands in the NTSB's own ordered sequence.

Status
    Repeatable, free: reads one finished run folder, makes no model call. Counts and code
    labels only (decision 0024): no case number, no title, no prose. Written for the S2.6
    final review (I6), which found decision 0089 quoting these counts before any committed
    script produced them.

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
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.scoring.report import provenance
from ntsb_probable_cause.settings import Settings

TOP_MISSES = 12
_PHASE = slice(0, 3)
_EVENT = slice(3, 6)


def _share(count: int, total: int) -> str:
    return f"{count} of {total} ({count / total:.1%})" if total else f"{count} of 0"


def _refuse_unless_development_arm_b(run_id: str, record: RunRecord) -> None:
    """Held-out runs never feed this script (CLAUDE.md rule 5); nor does any arm but B."""
    if "heldout" in run_id or record.sample.startswith("heldout"):
        raise SystemExit(
            f"occurrence_misses: {run_id} is a held-out run ({record.sample}); this script "
            "reads development runs only"
        )
    if not record.sample.startswith("dev"):
        raise SystemExit(f"occurrence_misses: {record.sample} is not a development sample")
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


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, one run's counts."""
    parser = argparse.ArgumentParser(prog="occurrence_misses")
    parser.add_argument("--run", required=True, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    folder = Settings().runs_dir / args.run
    if "heldout" in args.run:
        raise SystemExit(
            f"occurrence_misses: {args.run} is a held-out run; this script reads development "
            "runs only"
        )
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    _refuse_unless_development_arm_b(args.run, record)
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(case.split != "dev" for case in cases):
        raise SystemExit(f"occurrence_misses: {args.run} holds a case outside the dev split")
    text = (
        "occurrence misses (scripts/occurrence_misses.py; counts only, decision 0024)\n"
        + provenance(record).rstrip("\n")
        + "\n\n"
        + summarise(cases, load_tables())
    )
    print(text)
    if args.out is not None:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
