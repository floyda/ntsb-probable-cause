"""The cap check: did the $0.15 cap cut any noise-floor case's coding short? (S3.2 Task 9).

Status
    Live measurement for S3.2 (spec §5, decision 144), free: reads finished ``dev-400`` arm C run
    folders and makes no model call. Counts only (decision 0024): no case number, no prose.
    Its output is ``docs/results/s32-cap-check-dev.txt`` (``make s32-cap-check RUNS="<a> <b>"``).
    It decides one thing: whether the single cap of $0.30 may stand, or the choice goes back to
    Andy before any S3.2 run.

Why
    The loop's cap is $0.15 a case in the noise-floor runs. S3.2 raises it to $0.30 for every
    arm. That would change what a case does only if the $0.15 cap had already changed what a
    case did. The one place the cap changes the loop's course is its room check
    (``loop.CaseLoop._prepare``): when the call and the room kept back for the answer and its
    refinement no longer fit, the loop forces the answer, early. A case forced that way never
    finished its coding.

How a forced answer shows in the trail
    A call with ``step == "answer"`` is reached by three routes only, which were read in
    ``agent/loop.py`` and ``agent/steps.py``:

    1. ``loop._code`` sets the step to ``answer`` after ``max_coding_calls`` (6) accepted coding
       calls (``agent.run.MAX_CODING_CALLS``);
    2. ``steps.to_coding`` goes straight to ``answer`` when the run has no coding step
       (``without={"coding"}``), which the noise-floor runs do not;
    3. ``_prepare`` forces ``answer`` when the room check fails: the cap's route.

    So an ``answer`` call made after **fewer than 6** accepted coding calls is the cap's route.
    A coding call counts when its step is ``coding``, it called a coding tool and it was
    accepted (``protocol_error`` is None): a rejected call does not move ``_coding_calls``. A
    ``submit_answer`` made during coding is a step ``coding`` call, not an ``answer`` step, so
    it is not counted. A case is counted once, however many times its answer was retried.

What it prints
    For each run: the cases counted (the cases with a trail), and the cases forced to answer by
    the cap. Then the decision line::

        cap check: <N> cases had coding cut short at $0.15 -> <decision>

    where N sums the runs. ``the $0.30 cap stands (decision 144)`` when N is 0, else
    ``STOP: the cap goes back to Andy before any S3.2 run (spec §5)``.

Usage
    uv run python -m scripts.s32_cap_check RUN_A [RUN_B ...] [--out PATH]
"""

import argparse
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from ntsb_probable_cause.agent.run import MAX_CODING_CALLS
from ntsb_probable_cause.agent.schemas import CODING_TOOLS
from ntsb_probable_cause.agent.trail import AgentCall
from scripts._s3_runs import load_runs, write_result

PROG: Final = "s32_cap_check"
_STANDS: Final = "the $0.30 cap stands (decision 144)"
_STOP: Final = "STOP: the cap goes back to Andy before any S3.2 run (spec §5)"


def cut_short(calls: Sequence[AgentCall]) -> tuple[int, int]:
    """The cases in a trail, and the cases forced to answer before the coding limit.

    Args:
        calls: one run's ``trail.jsonl`` rows.

    Returns:
        ``(cases counted, cases forced to answer by the cap)``.
    """
    by_case: dict[str, list[AgentCall]] = defaultdict(list)
    for call in calls:
        by_case[call.case_id].append(call)
    forced = 0
    for rows in by_case.values():
        coding = 0
        for call in sorted(rows, key=lambda c: (c.trigger, c.call_index)):
            if call.step == "answer":
                forced += coding < MAX_CODING_CALLS
                break
            if call.step == "coding" and call.tool in CODING_TOOLS and call.protocol_error is None:
                coding += 1
    return len(by_case), forced


def decision_line(forced: int) -> str:
    """The decision line for ``forced`` cases cut short."""
    return (
        f"cap check: {forced} cases had coding cut short at $0.15 -> "
        f"{_STANDS if forced == 0 else _STOP}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the cap check of the given runs."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("runs", nargs="+", metavar="RUN_ID", help="finished dev-400 arm C run ids")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    runs = load_runs(PROG, args.runs)
    lines = [
        "S3.2 cap check (scripts/s32_cap_check.py; spec §5, decision 144)",
        "Counts only: no case number.",
        *(f"run {run.label} = {run.record.run_id}" for run in runs),
    ]
    total = 0
    for run in runs:
        counted, forced = cut_short(run.calls)
        total += forced
        lines.append(
            f"run {run.label}: {counted} cases counted, {forced} forced to answer by the cap "
            f"(an answer call after fewer than {MAX_CODING_CALLS} coding calls)"
        )
    lines.append(decision_line(total))
    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
