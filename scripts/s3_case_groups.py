"""dev-400 sorted into always right, always wrong and flipping, across finished runs.

Status
    Live tool for S3.1's tuning rounds (plan Task 15, spec §10.3), free: reads finished run
    folders and makes no model call. Exploratory, for the design of a round, but scripted: it
    names the group a round's designer reads trails from, so cases are chosen by a stated group,
    never by hand and never from arm B's misses. Its printed output is counts only (decision
    0024); ``make s3-case-groups RUNS="<ids>"`` also writes it to
    ``docs/results/s3-case-groups-dev.txt``. The case lists themselves go to a JSON file under
    ``NTSB_RUNS_DIR`` (``s3-case-groups/<UTC time>/groups.json``), which is never committed.

Why
    A round is designed from trails, and which trails are read decides what the designer sees.
    Picking cases by hand, or from arm B's misses, would tune the loop toward a set chosen by
    its look. A group fixed by a rule over the noise-floor runs and the existing arm B runs is a
    reason that can be stated and checked.

The groups
    Per case of ``dev-400``, on occurrence top-1, across the runs given:

    - **always right**: right in every run;
    - **always wrong**: wrong in every run;
    - **flipping**: right in at least one run and wrong in at least one.

    A case that failed in a run (any ``failure``: a format or tool failure, a guard refusal,
    the per-case cap, the round limit), or that holds no score there, counts as wrong in that
    run, as decision 0136 item 1 reads an S3 round (``round_result.top1_counting_failures``).
    So a case right in one run and failed in another is flipping, and a case that failed in
    every run is always wrong. Beside each split, the cases that failed in at least one of its
    runs, and in every one, are counted.

What it prints
    The runs and their arms; the three groups over all runs given; the same over the arm C runs
    only and over the arm B runs only; a cross-count of each case's arm C group against its arm
    B group (when both arms are given). Each split is printed again for fatal and non-fatal
    cases. Every figure has its denominator. No case number and no text from a case.

The case lists
    ``groups.json`` holds the runs and their arms; for ``all``, ``arm C`` and ``arm B`` (each
    when given), the case ids of each group, sorted; ``cross``, the case ids of each pair of an
    arm C group and an arm B group; the fatal cases; and the cases that failed in at least one
    run. A second list in the same second is refused rather than written over.

Refusals, before any case is read
    A run id naming a held-out run; a folder with no ``run.jsonl``, or whose record names
    another run (a copied or renamed folder); a run on any sample but ``dev-400`` (held-out,
    sealed and every other sample: a sealed sample not yet opened is refused as sealed first); a
    run of any arm but B or C; a run that has not finished; a run named twice; fewer than two
    runs. Then, once the cases are read: a case outside the development split, and a run whose
    cases are not exactly ``dev-400``'s (a ``--limit`` run, or a case named twice).

Usage
    uv run python -m scripts.s3_case_groups RUN RUN [RUN ...] [--out PATH]
"""

import argparse
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, NoReturn

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts.round_result import counted_failed, top1_counting_failures

type Group = Literal["always right", "always wrong", "flipping"]

SAMPLE: Final = "dev-400"
GROUPS: Final[tuple[Group, ...]] = ("always right", "always wrong", "flipping")
ARMS: Final = ("C", "B")
FOLDER: Final = "s3-case-groups"
_STAMP: Final = "%Y%m%dT%H%M%S"


@dataclass(frozen=True)
class Run:
    """One run, read: its id, arm and cases."""

    run_id: str
    arm: str
    cases: list[CaseResult]

    @property
    def hits(self) -> dict[str, float]:
        """Occurrence top-1 per case; a failed case scores 0 (decision 0136 item 1)."""
        return top1_counting_failures(self.cases)

    @property
    def failed(self) -> frozenset[str]:
        """The cases that failed, or hold no score, in this run (decision 0136 item 1)."""
        return frozenset(c.case_id for c in self.cases if counted_failed(c))


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_case_groups: {message}")


# --- the groups ---


def group(values: Sequence[float]) -> Group:
    """Always right, always wrong or flipping, from a case's top-1 in each run."""
    if all(values):
        return "always right"
    if not any(values):
        return "always wrong"
    return "flipping"


def assign(runs: Sequence[Run]) -> dict[str, Group]:
    """Each case's group across ``runs``, which hold the same cases."""
    hits = [run.hits for run in runs]
    return {case_id: group([h[case_id] for h in hits]) for case_id in sorted(hits[0])}


def _split(runs: Sequence[Run]) -> list[tuple[str, list[int]]]:
    """All runs, then arm C's, then arm B's: each split's run numbers (from 1), maybe none."""
    numbered = list(enumerate(runs, 1))
    return [
        ("all", [n for n, _ in numbered]),
        *((f"arm {arm}", [n for n, run in numbered if run.arm == arm]) for arm in ARMS),
    ]


def _assigned(runs: Sequence[Run]) -> dict[str, dict[str, Group]]:
    """Each split that has runs: each case's group across that split's runs."""
    return {
        name: assign([runs[n - 1] for n in numbers]) for name, numbers in _split(runs) if numbers
    }


# --- the lines ---


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.1%})" if whole else f"{part} of {whole}"


def group_lines(
    assigned: Mapping[str, Group], fatal: Mapping[str, bool], chosen: Sequence[Run]
) -> list[str]:
    """One split's groups, then by fatal and non-fatal, then its failures."""
    counts = Counter(assigned.values())
    lines = [f"{name}: {_share(counts[name], len(assigned))}" for name in GROUPS]
    for label, wanted in (("fatal", True), ("non-fatal", False)):
        part = Counter(g for case_id, g in assigned.items() if fatal[case_id] is wanted)
        whole = sum(part.values())
        lines.append(
            f"- {label}: " + ", ".join(f"{name} {_share(part[name], whole)}" for name in GROUPS)
        )
    failed = [run.failed for run in chosen]
    some = frozenset[str]().union(*failed)
    every = frozenset[str](assigned).intersection(*failed)
    lines.append(
        f"failed in at least one of these runs: {_share(len(some), len(assigned))}; in every "
        f"one: {_share(len(every), len(assigned))}"
    )
    return lines


def cross_lines(
    by_c: Mapping[str, Group], by_b: Mapping[str, Group], fatal: Mapping[str, bool]
) -> list[str]:
    """Each arm C group split by arm B group: all cases, then fatal, then non-fatal."""
    lines: list[str] = []
    for label, wanted in (("all cases", None), ("fatal cases", True), ("non-fatal cases", False)):
        ids = [i for i in by_c if wanted is None or fatal[i] is wanted]
        lines.append(f"{label} ({len(ids)}):")
        for name in GROUPS:
            row = Counter(by_b[i] for i in ids if by_c[i] == name)
            lines.append(
                f"- arm C {name}: arm B "
                + ", ".join(f"{other} {row[other]}" for other in GROUPS)
                + f"; {sum(row.values())} of {len(ids)} cases"
            )
    return lines


def _title(name: str, numbers: Sequence[int]) -> str:
    if not numbers:
        return f"## {name} runs only: no {name} run given"
    which = f"(runs {', '.join(str(n) for n in numbers)})"
    return (
        f"## all {len(numbers)} runs {which}" if name == "all" else f"## {name} runs only {which}"
    )


def report(runs: Sequence[Run], listed: str) -> str:
    """The whole report: the runs, each split's groups, the cross-count, the lists' path."""
    fatal = {c.case_id: c.fatal for c in runs[0].cases}
    head = [
        "S3.1 case groups on dev-400 (scripts/s3_case_groups.py; plan Task 15, spec §10.3)",
        "Counts only: no case number. Every figure is printed with its denominator.",
        "Occurrence top-1 in each run. A case that failed in a run, or holds no score there, "
        "counts as wrong in that run (decision 0136 item 1).",
        *(f"run {n} = {run.run_id} (arm {run.arm})" for n, run in enumerate(runs, 1)),
    ]
    blocks = ["\n".join(head)]
    assigned = _assigned(runs)
    for name, numbers in _split(runs):
        lines = [_title(name, numbers)]
        if numbers:
            chosen = [runs[n - 1] for n in numbers]
            lines += ["", *group_lines(assigned[name], fatal, chosen)]
        blocks.append("\n".join(lines))
    if "arm C" in assigned and "arm B" in assigned:
        blocks.append(
            "\n".join(
                [
                    "## arm C group against arm B group (cases; each row an arm C group, split "
                    "by arm B group)",
                    "",
                    *cross_lines(assigned["arm C"], assigned["arm B"], fatal),
                ]
            )
        )
    blocks.append(f"case lists (case ids; under NTSB_RUNS_DIR, never committed): {listed}")
    return "\n\n".join(blocks)


# --- the case lists ---


def case_lists(runs: Sequence[Run]) -> dict[str, object]:
    """What ``groups.json`` holds: case ids by group, by pair of groups, fatal and failed."""
    assigned = _assigned(runs)
    cross: dict[str, list[str]] = {}
    if "arm C" in assigned and "arm B" in assigned:
        by_c, by_b = assigned["arm C"], assigned["arm B"]
        for c_group in GROUPS:
            for b_group in GROUPS:
                cross[f"arm C {c_group} / arm B {b_group}"] = [
                    i for i in by_c if by_c[i] == c_group and by_b[i] == b_group
                ]
    return {
        "sample": SAMPLE,
        "measure": (
            "occurrence top-1; a case that failed in a run, or holds no score there, is wrong "
            "in that run (decision 0136 item 1)"
        ),
        "runs": [{"run_id": run.run_id, "arm": run.arm} for run in runs],
        "groups": {
            name: {g: [i for i, got in groups.items() if got == g] for g in GROUPS}
            for name, groups in assigned.items()
        },
        "cross": cross,
        "fatal": sorted(c.case_id for c in runs[0].cases if c.fatal),
        "failed in at least one run": sorted(frozenset[str]().union(*(r.failed for r in runs))),
    }


def write_lists(runs: Sequence[Run], when: datetime) -> str:
    """Write ``groups.json`` under the runs folder; return its path relative to that folder."""
    relative = Path(FOLDER) / when.astimezone(UTC).strftime(_STAMP) / "groups.json"
    path = Settings().runs_dir / relative
    try:
        path.parent.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        _refuse(f"{path.parent} already exists; run again in a second, rather than write over it")
    path.write_text(json.dumps(case_lists(runs), indent=1) + "\n")
    return relative.as_posix()


# --- reading the runs ---


def _head(run_id: str) -> RunRecord:
    """A run's record, after every refusal that needs no case."""
    try:
        samples.refuse_unless_development(run_id, None)
    except ConfigurationError as error:
        _refuse(str(error))
    folder = Settings().runs_dir / run_id
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
        _refuse(f"{run_id} is on {record.sample}; case groups are on {SAMPLE} only")
    if record.arm not in ARMS:
        _refuse(f"{run_id} is arm {record.arm}, not B or C")
    if record.finished is None:
        _refuse(f"{run_id} has not finished: it did not complete a pass")
    return record


def _read(run_id: str, record: RunRecord) -> Run:
    """A run's cases, after the refusals that need them."""
    cases = read_jsonl(Settings().runs_dir / run_id / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        _refuse(f"{run_id} holds a case outside the dev split")
    ids = [c.case_id for c in cases]
    if len(ids) != len(set(ids)) or set(ids) != set(samples.sample_ids(SAMPLE)):
        _refuse(f"{run_id} is not the whole of {SAMPLE}, each case once (a --limit run?)")
    return Run(run_id, record.arm, cases)


def load(run_id: str) -> Run:
    """One run, after every refusal."""
    return _read(run_id, _head(run_id))


def _now() -> datetime:
    return datetime.now(UTC)


def main(argv: Sequence[str] | None = None, *, now: Callable[[], datetime] = _now) -> int:
    """Print, and with ``--out`` also write, the groups; write the case lists."""
    parser = argparse.ArgumentParser(prog="s3_case_groups")
    parser.add_argument("runs", nargs="+", metavar="RUN_ID", help="finished dev-400 runs, B or C")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if len(args.runs) < 2:  # noqa: PLR2004 -- a group is across runs
        parser.error("give at least two run ids")
    if len(set(args.runs)) != len(args.runs):
        _refuse("a run is named twice; the groups are across distinct runs")
    heads = [_head(run_id) for run_id in args.runs]
    runs = [_read(run_id, record) for run_id, record in zip(args.runs, heads, strict=True)]
    text = report(runs, write_lists(runs, now()))
    print(text)
    if args.out is not None:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
