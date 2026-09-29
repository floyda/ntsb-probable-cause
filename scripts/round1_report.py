"""Round 1's results: the four ways on two answer sets, and decision 0096's reading rule.

Status
    Live for S2.7 (spec §5.4), free: reads the source runs and their derived check folders
    (``ntsb-eval check``); counts only. Writes docs/results/s27-round1-dev.txt.

Why
    The rule was fixed before any check ran: a way works if it beats "no check" on both answer
    sets; a model must also beat the free rule on both, or the rule is kept.

Usage
    uv run python -m scripts.round1_report --answers RUN_A RUN_B [--out PATH]
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.checkpass import WAYS, derived_id
from ntsb_probable_cause.scoring.metrics import paired_difference
from ntsb_probable_cause.scoring.misses import MISS_GROUPS, miss_group
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings

__all__ = ["Paired", "choose", "derived_id", "main", "paired", "push"]

MODEL_WAYS = ("luna", "jev")
# A checked case carries the source's answer step plus the check's own step (decision 0101 item 4).
_CHECKED_STEPS = 2


@dataclass(frozen=True)
class Paired:
    """A paired top-1 difference (a - b) with its interval, and fixes and breaks."""

    mean: float
    low: float
    high: float
    n: int
    fixes: int
    breaks: int


def paired(
    a: Mapping[str, bool], b: Mapping[str, bool], ids: Sequence[str] | None = None
) -> Paired:
    """Paired over the shared ids (or ``ids``).

    ``fixes`` = right in ``a`` only, ``breaks`` = right in ``b`` only.
    """
    shared = sorted(set(a) & set(b)) if ids is None else [i for i in ids if i in a and i in b]
    if not shared:
        return Paired(0.0, 0.0, 0.0, 0, 0, 0)
    mean, low, high = paired_difference([a[i] for i in shared], [b[i] for i in shared])
    fixes = sum(a[i] and not b[i] for i in shared)
    breaks = sum(b[i] and not a[i] for i in shared)
    return Paired(mean, low, high, len(shared), fixes, breaks)


def choose(results: Mapping[str, Mapping[str, tuple[Paired, Paired | None]]]) -> str:
    """Decision 0096 item 5, over every answer set in ``results``."""
    sets = list(results.values())

    def everywhere(way: str, index: int) -> bool:
        return all(way in s and (p := s[way][index]) is not None and p.low > 0 for s in sets)

    def gain(s: Mapping[str, tuple[Paired, Paired | None]], way: str) -> float:
        vs_rule = s[way][1]
        return vs_rule.mean if vs_rule is not None else 0.0

    winners = [w for w in MODEL_WAYS if everywhere(w, 1)]
    if winners:
        return max(winners, key=lambda w: sum(gain(s, w) for s in sets))
    return "rule" if everywhere("rule", 0) else "no check"


def _top1(cases: Sequence[CaseResult]) -> dict[str, bool]:
    return {c.case_id: c.scores.occurrence_top1 for c in cases if c.scores is not None and c.steps}


def push(checked: Sequence[CaseResult], none: Mapping[str, bool]) -> tuple[int, int, int, int]:
    """Decision 0101 item 4.

    Returns (first codes changed, of which toward a more common option, fixes among those,
    breaks among those).
    """
    changed = toward = fixes = breaks = 0
    for case in checked:
        not_checked = len(case.steps) < _CHECKED_STEPS or case.steps[-1].tool != "ordering_check"
        if not_checked or case.scores is None:
            continue
        before = case.steps[0].hypothesis.occurrence[0]
        after = case.steps[-1].hypothesis.occurrence[0]
        if (before.phase, before.event) == (after.phase, after.event):
            continue
        changed += 1
        if case.steps[-1].arguments.get("toward_more_common") is True:
            toward += 1
            fixes += case.scores.occurrence_top1 and not none.get(case.case_id, False)
            breaks += none.get(case.case_id, False) and not case.scores.occurrence_top1
    return changed, toward, fixes, breaks


def _line(label: str, p: Paired) -> str:
    return (
        f"  {label}: {p.mean:+.1%} [{p.low:+.1%}, {p.high:+.1%}] on n={p.n}; "
        f"fixes {p.fixes}, breaks {p.breaks}"
    )


def _record(runs: Path, source: str) -> RunRecord:
    """A source's own record, after every refusal but the per-case split.

    Held-out, sealed, finished. 2026-09-27 addition beyond the brief: every sibling script on
    this branch (``judge_outcomes._load``, ``round0_handread._run``) refuses a non-development
    run by reading ``run.jsonl``'s recorded sample before ``cases.jsonl`` is read at all, on
    top of the run-id substring check -- so a source whose id does not say "heldout" but whose
    recorded sample is held-out is still refused before any per-case data is touched. The
    sealed sample is refused too, until its registration is committed (decision 0095). Final
    review, Minor 3: a source whose ``finished`` is ``None`` (a dead check pass) is refused
    before its cases are read at all.
    """
    try:
        samples.refuse_unless_development(source, None)
        record = read_jsonl(runs / source / "run.jsonl", RunRecord)[0]
        samples.refuse_unless_development(source, record.sample)
    except ConfigurationError as error:
        raise SystemExit(f"round1_report: {error}") from error
    if record.finished is None:
        raise SystemExit(f"round1_report: {source} has not finished: it did not complete a pass")
    return record


def _load(runs: Path, source: str) -> list[CaseResult]:
    """A development run's cases, after every refusal (held-out, sealed, finished, split)."""
    _record(runs, source)
    cases = read_jsonl(runs / source / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        raise SystemExit(f"round1_report: {source} holds a case outside the development split")
    return cases


def main(argv: Sequence[str] | None = None) -> int:
    """Print every way on both answer sets, then the rule's outcome."""
    parser = argparse.ArgumentParser(prog="round1_report")
    parser.add_argument("--answers", nargs=2, required=True, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    runs = Settings().runs_dir
    a_record, b_record = (_record(runs, source) for source in args.answers)
    for attribute in ("sample", "arm", "evidence_version"):
        a_value, b_value = getattr(a_record, attribute), getattr(b_record, attribute)
        if a_value != b_value:
            raise SystemExit(
                f"round1_report: {args.answers[0]} {attribute}={a_value!r} does not match "
                f"{args.answers[1]} {attribute}={b_value!r}"
            )
    lines = ["Round 1: the ordering check (scripts/round1_report.py; counts only, decision 0096)"]
    results: dict[str, dict[str, tuple[Paired, Paired | None]]] = {}
    for source in args.answers:
        base = _load(runs, source)
        none = _top1(base)
        groups = {
            c.case_id: miss_group(
                tuple(g.phase + g.event for g in c.steps[-1].hypothesis.occurrence),
                c.verdict_occurrence,
                abstain=c.steps[-1].hypothesis.abstain,
            )
            for c in base
            if c.scores is not None and c.steps
        }
        fatal = {c.case_id for c in base if c.fatal}
        lines += ["", f"## answer set {source}"]
        loaded: dict[str, dict[str, bool]] = {}
        pushes: dict[str, tuple[int, int, int, int]] = {}
        for check_way in WAYS:
            folder = runs / derived_id(source, check_way)
            if not (folder / "cases.jsonl").exists():
                lines.append(f"- {check_way}: not run")
                continue
            derived = read_jsonl(folder / "cases.jsonl", CaseResult)
            loaded[check_way] = _top1(derived)
            pushes[check_way] = push(derived, none)
        results[source] = {}
        for way, top1 in loaded.items():
            vs_none = paired(top1, none)
            vs_rule = paired(top1, loaded["rule"]) if way != "rule" and "rule" in loaded else None
            results[source][way] = (vs_none, vs_rule)
            lines.append(f"- {way}")
            lines.append(_line("against no check", vs_none))
            if vs_rule is not None:
                lines.append(_line("against the plain rule", vs_rule))
            changed, toward, t_fixes, t_breaks = pushes[way]
            lines.append(
                f"  first codes changed: {changed}; toward a more common option (decision 0101): "
                f"{toward}, fixes {t_fixes}, breaks {t_breaks}"
            )
            lines.append(_line("fatal, against no check", paired(top1, none, sorted(fatal))))
            lines.append(
                _line("non-fatal, against no check", paired(top1, none, sorted(set(none) - fatal)))
            )
            for group in ("exact", *MISS_GROUPS):
                members = sorted(i for i, g in groups.items() if g == group)
                p = paired(top1, none, members)
                lines.append(f"    {group}: fixes {p.fixes}, breaks {p.breaks} of {p.n}")
    outcome = choose(results)
    lines += ["", f"outcome (decision 0096 item 5): {outcome}"]
    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
