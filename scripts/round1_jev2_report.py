"""The second, registered Jev check (`jev2`): its comparisons and decision 0103's win rule.

Status
    Live for S2.7 (plan Task 12a), free: reads Round 1's two answer sets and their derived
    check folders (``ntsb-eval check``); counts only. Writes
    docs/results/s27-round1-jev2-dev.txt. Round 1's own report and results file are untouched.

Why
    ``jev2`` was designed after Round 1 from TypeSafe's documentation, and registered before
    any code or call (``docs/rounds/s27-round1-jev2.md``). A second attempt for one way could
    win by chance, so the win rule was fixed with it: ``jev2`` replaces GPT-6 Luna only if, on
    both answer sets, its paired top-1 difference has a lower 95% bound above zero against no
    check, against the plain rule and against GPT-6 Luna. Otherwise Luna stays.

Usage
    uv run python -m scripts.round1_jev2_report --answers RUN_A RUN_B [--out PATH]
"""

import argparse
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.checkpass import CHECK_TOOL, Way, derived_id
from ntsb_probable_cause.scoring.ordering import NONE_OF_THESE
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts.round1_report import Paired, paired, push

__all__ = ["jev2_wins", "main", "none_first", "outcome"]

# What jev2 is compared against: a label, and the way whose derived folder holds it (None: the
# source run itself, "no check").
COMPARED: tuple[tuple[str, Way | None], ...] = (
    ("no check", None),
    ("the plain rule", "rule"),
    ("GPT-6 Luna", "luna"),
    ("Round 1's Jev", "jev"),
)
# Decision 0103 item 3: the three comparisons the win rule reads.
WIN_AGAINST = ("no check", "the plain rule", "GPT-6 Luna")
# A checked case carries the source's answer step plus the check's own step.
_CHECKED_STEPS = 2


def jev2_wins(results: Mapping[str, Mapping[str, Paired | None]]) -> bool:
    """Decision 0103 item 3: all three lower bounds above zero, on both answer sets."""
    return len(results) == 2 and all(  # noqa: PLR2004 -- the registration's two answer sets.
        (p := against.get(label)) is not None and p.low > 0
        for against in results.values()
        for label in WIN_AGAINST
    )


def outcome(results: Mapping[str, Mapping[str, Paired | None]]) -> str:
    """The outcome line, by the rule fixed before the first call."""
    head = "outcome (decision 0103 item 3, fixed before the first call): "
    if jev2_wins(results):
        return head + (
            "jev2 replaces GPT-6 Luna as the kept check -- all three lower bounds are above zero "
            "on both answer sets; Andy records the replacement as a new decision before any "
            "guidance round uses it"
        )
    return head + "luna stays (CHECK=luna)"


def _checked_step_arguments(case: CaseResult) -> Mapping[str, object] | None:
    if len(case.steps) < _CHECKED_STEPS or case.steps[-1].tool != CHECK_TOOL:
        return None
    return case.steps[-1].arguments


def none_first(case: CaseResult) -> bool:
    """Whether ``none_of_these`` ranked first on this case's check.

    Read from ``jev_order``, Jev's full ranked option order after the tie rules, which
    ``jev2_checker`` records on every step -- never from the order a mapping was stored in.
    """
    arguments = _checked_step_arguments(case)
    order = arguments.get("jev_order") if arguments is not None else None
    return isinstance(order, list) and bool(order) and order[0] == NONE_OF_THESE


def _confidence(case: CaseResult) -> float | None:
    arguments = _checked_step_arguments(case)
    value = arguments.get("confidence") if arguments is not None else None
    return float(value) if isinstance(value, int | float) else None


def _top1(cases: Sequence[CaseResult]) -> dict[str, bool]:
    return {c.case_id: c.scores.occurrence_top1 for c in cases if c.scores is not None and c.steps}


def _refuse(runs: Path, run_id: str) -> None:
    """Every refusal that needs only the run's id and ``run.jsonl``: held-out, sealed.

    The sealed sample is refused until its registration is committed (decision 0095), as
    ``ntsb-eval`` refuses it; nothing here reads ``cases.jsonl``.
    """
    if "heldout" in run_id:
        raise SystemExit(f"round1_jev2_report: {run_id} is a held-out run; development runs only")
    record = read_jsonl(runs / run_id / "run.jsonl", RunRecord)[0]
    if not record.sample.startswith("dev"):
        raise SystemExit(
            f"round1_jev2_report: {run_id} is a held-out run ({record.sample}); "
            "development runs only"
        )
    try:
        samples.refuse_sealed(record.sample, is_committed=gitinfo.is_committed)
    except ConfigurationError as error:
        raise SystemExit(f"round1_jev2_report: {run_id}: {error}") from error


def _load(runs: Path, run_id: str) -> list[CaseResult]:
    """A development run's cases, after every refusal (held-out, sealed, then split).

    The recorded sample is read from ``run.jsonl`` before ``cases.jsonl`` is touched, as every
    S2.7 script does (``round1_report._load``).
    """
    _refuse(runs, run_id)
    cases = read_jsonl(runs / run_id / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        raise SystemExit(f"round1_jev2_report: {run_id} holds a case outside the development split")
    return cases


def _load_if_run(runs: Path, run_id: str) -> list[CaseResult] | None:
    return _load(runs, run_id) if (runs / run_id / "cases.jsonl").exists() else None


def _line(label: str, p: Paired) -> str:
    return (
        f"- jev2 against {label}: {p.mean:+.1%} [{p.low:+.1%}, {p.high:+.1%}] on n={p.n}; "
        f"fixes {p.fixes}, breaks {p.breaks}"
    )


def _median(values: Sequence[float]) -> str:
    return f"{statistics.median(values):.2f} (n={len(values)})" if values else "none (n=0)"


def _confidences(checked: Sequence[CaseResult], none: Mapping[str, bool]) -> str:
    groups: dict[str, list[float]] = {"fixed": [], "broken": [], "unchanged": []}
    for case in checked:
        confidence = _confidence(case)
        if confidence is None or case.scores is None or case.case_id not in none:
            continue
        right, before = case.scores.occurrence_top1, none[case.case_id]
        group = "fixed" if right and not before else "broken" if before and not right else None
        groups[group or "unchanged"].append(confidence)
    return (
        f"median Jev confidence: fixed {_median(groups['fixed'])}, "
        f"broken {_median(groups['broken'])}, "
        f"unchanged (top-1 the same as no check) {_median(groups['unchanged'])}"
    )


def _answer_set(runs: Path, source: str) -> tuple[list[str], dict[str, Paired | None] | None]:
    base = _load(runs, source)
    none = _top1(base)
    lines = ["", f"## answer set {source}"]
    checked = _load_if_run(runs, derived_id(source, "jev2"))
    if checked is None:
        lines.append("- jev2: not run")
        return lines, None
    top1 = _top1(checked)
    against: dict[str, Paired | None] = {}
    for label, way in COMPARED:
        other = [] if way is None else _load_if_run(runs, derived_id(source, way))
        if other is None:
            against[label] = None
            lines.append(f"- jev2 against {label}: not run")
            continue
        result = paired(top1, none if way is None else _top1(other))
        against[label] = result
        lines.append(_line(label, result))
    changed, toward, _fixes, _breaks = push(checked, none)
    stepped = [c for c in checked if _checked_step_arguments(c) is not None]
    lines += [
        f"first codes changed: {changed}; toward a more common option (decision 0101): {toward}",
        f"none_of_these ranked first (answer left unchanged): "
        f"{sum(none_first(c) for c in stepped)} of {len(stepped)} checked cases",
        _confidences(stepped, none),
    ]
    return lines, against


def main(argv: Sequence[str] | None = None) -> int:
    """Print jev2's comparisons on both answer sets, then the outcome by the fixed rule."""
    parser = argparse.ArgumentParser(prog="round1_jev2_report")
    parser.add_argument("--answers", nargs=2, required=True, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    runs = Settings().runs_dir
    lines = [
        "Round 1, second Jev check (jev2): a second, registered comparison (decision 0103), "
        "designed after Round 1 from the vendor's documentation "
        "(scripts/round1_jev2_report.py; counts only; design: docs/rounds/s27-round1-jev2.md)"
    ]
    # Both sources' records are checked before any run's cases are read (fix round 1).
    for source in args.answers:
        _refuse(runs, source)
    results: dict[str, dict[str, Paired | None]] = {}
    for source in args.answers:
        set_lines, against = _answer_set(runs, source)
        lines += set_lines
        if against is not None:
            results[source] = against
    lines += ["", outcome(results)]
    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
