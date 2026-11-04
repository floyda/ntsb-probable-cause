"""Question 7's figure on the public site: the loop's beliefs against the NTSB's first code (0186).

Status
    Exploratory (decision 0059), free and offline: no model call, no new run. It decides nothing
    and claims nothing (decision 0186 item 6). It reads S3.2's held-out loop run once, through
    the held-out diagnosis's own path and refusals (decision 0153's script, reused), and prints
    only what 0186 item 4 names. Counts only (decision 0024): no case number, no case or model
    text. ``make s5-belief-path`` writes ``docs/results/s5-belief-path-heldout.txt``.

What it counts (0186 items 2 to 4, fixed before this script existed)
    The cases the loop answered (``claims.answered``), in case-id order; a case with no H0 in
    its trail is left out and counted. Three checkpoints per case, each right when its first
    occurrence code is the NTSB's first code, scored as the diagnosis scores a hypothesis:
    * before reading: H0, the first accepted ``h0``;
    * after reading: the latest accepted checkpoint of ``h0``, ``h1`` and ``h2`` (the
      diagnosis's "last hypothesis before coding"); for a case with no accepted ``h1`` or ``h2``
      it is H0, and those cases are counted;
    * the answer: the case result's recorded top-1.
    For each checkpoint, how many are right; for before -> after reading and for after reading
    -> the answer, how many stayed right, were fixed, were broken and stayed wrong.

The check against the record (0186 item 5)
    Before reading's right count and the answer's, and the after reading -> answer fixes and
    breaks (counted as the diagnosis counts them: a change of first code), must equal
    ``docs/results/s32-heldout-diagnosis.txt``'s committed figures, or nothing is written.

Refusals, in this order, before any held-out run is opened
    1. The ids, as ``s32_claims`` refuses them.
    2. ``docs/decisions/0186-...`` is not committed.
    3. ``docs/rounds/s3-registration.md`` (the S3.2 registration) is not committed.
    4. Its result, ``docs/results/s5-belief-path-heldout.txt``, is committed: 0186 allows one
       reading, made on 2026-10-14 (added after that reading; review, 2026-10-14).
    5. The tree has an uncommitted change outside ``docs/results/``.
    The cross-check reads the diagnosis as committed at ``HEAD``, never the working tree.

Usage
    uv run python -m scripts.exploratory.s5_belief_path --loop RUN --nodocket RUN --arm-a RUN \\
        --armb-answer RUN --armb-tools RUN --armb-check RUN [--out PATH]
"""

import argparse
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts._s3_runs import refuse, write_result
from scripts.exploratory import s32_heldout_diagnosis as dg
from scripts.s32_claims import load_heldout

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring import checkpass
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.records import CaseResult

PROG: Final = "s5_belief_path"
DECISION: Final = Path(
    "docs/decisions/0186-a-counts-only-reading-of-s32s-held-out-trail-for-the-path-page.md"
)
DIAGNOSIS: Final = Path("docs/results/s32-heldout-diagnosis.txt")
RESULT: Final = Path("docs/results/s5-belief-path-heldout.txt")
_AFTER_READING: Final = frozenset({"h1", "h2"})
_H0_LINE: Final = re.compile(r"^- H0 right (\d+) of (\d+) \(.*\); answer right (\d+) of (\d+) \(")
_CODING_LINE: Final = re.compile(
    r"^- the loop, last hypothesis before coding -> answer: (\d+) cases; .*fixes (\d+), breaks (\d+)"
)


@dataclass(frozen=True)
class Move:
    """How the cases moved between two checkpoints, by right and wrong alone."""

    stayed_right: int
    fixed: int
    broken: int
    stayed_wrong: int


def move(pairs: Sequence[tuple[bool, bool]]) -> Move:
    """Count (before, after) rights into the four ways a case can move."""
    return Move(
        stayed_right=sum(1 for a, b in pairs if a and b),
        fixed=sum(1 for a, b in pairs if not a and b),
        broken=sum(1 for a, b in pairs if a and not b),
        stayed_wrong=sum(1 for a, b in pairs if not a and not b),
    )


@dataclass(frozen=True)
class Path3:
    """The three checkpoints over the cases counted, and the check figures."""

    cases: int
    no_h0: int
    no_belief_after_reading: int
    right: tuple[int, int, int]  # before reading, after reading, the answer
    reading: Move
    coding: Move
    coding_transition: dg.Transition  # the diagnosis's own count, for the check only


def belief_path(
    calls: Sequence[AgentCall], cases: Sequence[CaseResult], tables: CodeTables
) -> Path3:
    """0186's counts from the loop's trail and case results."""
    per_case = dg.loop_cases(calls, cases)
    read_after = {c.case_id for c in calls if c.step in _AFTER_READING and c.hypothesis is not None}
    points: list[tuple[dg.Point, dg.Point, dg.Point]] = []
    no_h0 = no_belief = 0
    for case in sorted(cases, key=lambda c: c.case_id):
        answer = dg.answer_point(case, tables)
        if answer is None:
            continue
        loop = per_case[case.case_id]
        if loop.h0 is None or loop.before_coding is None:
            no_h0 += 1
            continue
        no_belief += case.case_id not in read_after
        before = dg.Point(dg.first_code(loop.h0, tables), dg.hypothesis_top1(loop.h0, case, tables))
        after = dg.Point(
            dg.first_code(loop.before_coding, tables),
            dg.hypothesis_top1(loop.before_coding, case, tables),
        )
        points.append((before, after, answer))
    return Path3(
        cases=len(points),
        no_h0=no_h0,
        no_belief_after_reading=no_belief,
        right=(
            sum(b.right for b, _, _ in points),
            sum(a.right for _, a, _ in points),
            sum(x.right for _, _, x in points),
        ),
        reading=move([(b.right, a.right) for b, a, _ in points]),
        coding=move([(a.right, x.right) for _, a, x in points]),
        coding_transition=dg.transition([(a, x) for _, a, x in points]),
    )


def check(found: Path3, diagnosis: str) -> None:
    """Refuse unless ``found`` agrees with the diagnosis's committed figures (0186 item 5)."""
    h0 = next((m for line in diagnosis.splitlines() if (m := _H0_LINE.match(line))), None)
    coding = next((m for line in diagnosis.splitlines() if (m := _CODING_LINE.match(line))), None)
    if h0 is None or coding is None:
        refuse(PROG, f"{DIAGNOSIS} lacks the H0 or coding line this reading is checked against")
    expected = (
        int(h0.group(1)),
        int(h0.group(2)),
        int(h0.group(3)),
        int(coding.group(1)),
        int(coding.group(2)),
        int(coding.group(3)),
    )
    t = found.coding_transition
    got = (found.right[0], found.cases, found.right[2], t.cases, t.fixes, t.breaks)
    if got != expected:
        refuse(
            PROG,
            f"the reading does not match {DIAGNOSIS} (before right, cases, answer right, "
            f"coding cases, fixes, breaks: {got} against {expected}); nothing is written",
        )


def _move_line(label: str, m: Move) -> str:
    return (
        f"{label}: stayed right {m.stayed_right}, fixed {m.fixed}, broken {m.broken}, "
        f"stayed wrong {m.stayed_wrong}"
    )


def report(found: Path3, loop_run: str) -> str:
    """The results file's text: 0186 item 4's counts and no others."""
    before, after, answer = found.right
    n = found.cases
    lines = [
        "S5 question 7: the loop's beliefs against the NTSB's first code, held-out "
        "(scripts/exploratory/s5_belief_path.py; decision 0186)",
        "Exploratory (decision 0059): it decides nothing and claims nothing. Counts only: no case "
        "number, no case or model text. Right means the belief's first occurrence code is the "
        "NTSB's first code.",
        f"the loop: {loop_run}",
        f"cases: the {n} the loop answered; left out, no belief before reading: {found.no_h0}",
        "cases with no belief after a read choice (after reading is before reading): "
        f"{found.no_belief_after_reading}",
        "",
        f"right, of {n}:",
        f"- before reading: {before}",
        f"- after reading: {after}",
        f"- the answer: {answer}",
        "",
        _move_line("before reading -> after reading", found.reading),
        _move_line("after reading -> the answer", found.coding),
        "",
        f"checked against {DIAGNOSIS}: before reading and the answer right, the cases, and after "
        "reading -> the answer's fixes and breaks (a change of first code): equal",
    ]
    return "\n".join(lines)


def committed_diagnosis() -> str:
    """The diagnosis as committed at ``HEAD``: an edit in the working tree is never read."""
    shown = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "show", f"HEAD:{DIAGNOSIS.as_posix()}"],  # noqa: S607 -- git from PATH
        capture_output=True,
        text=True,
        check=True,
    )
    return shown.stdout


def main(
    argv: Sequence[str] | None = None,
    *,
    is_committed: Callable[[Path], bool] | None = None,
    diagnosis: Callable[[], str] = committed_diagnosis,
) -> int:
    """Print, and with ``--out`` also write, 0186's counts.

    Args:
        argv: the command line.
        is_committed: whether a path is committed; ``gitinfo.is_committed`` unless a test
            passes its own.
        diagnosis: the committed diagnosis's text; a test passes its own.
    """
    parser = argparse.ArgumentParser(prog=PROG)
    for flag in ("loop", "nodocket", "arm-a", "armb-answer", "armb-tools", "armb-check"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    committed = is_committed or gitinfo.is_committed
    dg.refuse_ids(args)
    if not committed(DECISION):
        refuse(PROG, f"{DECISION} is not committed: this reading runs only once it is")
    if not committed(checkpass.S32_REGISTRATION):
        refuse(
            PROG,
            f"{checkpass.S32_REGISTRATION} is not committed: the held-out runs are read only "
            "after the registration is on record (decision 0142)",
        )
    if committed(RESULT):
        refuse(PROG, f"{RESULT} is committed: decision 0186 allows one reading, and it is made")
    dg.refuse_dirty_tree()
    held = load_heldout(args)
    try:
        found = belief_path(held.loop.calls, held.loop.cases, load_tables())
    except ValueError as error:
        refuse(PROG, str(error))
    check(found, diagnosis())
    text = report(found, held.loop.record.run_id)
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
