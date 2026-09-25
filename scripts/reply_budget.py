"""S2.6 Task 9A: read one run folder's ``cases.jsonl`` and report the reply-budget verdict.

Status
    One-shot. Prints and, with ``--out``, writes counts only (decision 0024: no case number,
    no title, no prose) -- cases; failures by reason (``report.failure_summary``, unchanged);
    the reply-format (``"schema:"``) failures broken down by ``finish_reason``, parsed from
    each failure text's trailing ``(finish_reason=..., completion_tokens=...,
    reasoning_tokens=...)`` bracket (S2.6 Task 9A, ``scoring/runner.py``'s ``_reply_detail``)
    -- a failure text from before that task carries no such bracket, and is counted under
    ``"unrecorded"`` rather than raising; their reasoning tokens (min/median/max); the
    successful cases' per-reply token totals (median/p90/p99/max, from
    ``StepRecord.completion_tokens`` and ``.reasoning_tokens``); the rule's verdict
    (confirmed / not confirmed, with the counts behind it, both fixed in the Task 9A brief
    before any run); and, if confirmed, the new budget by ``new_budget``'s fixed rule.

    ``completion_tokens`` already includes reasoning tokens as a subset, not in addition to
    them (``tests/fixtures/openrouter/structured.json``: ``completion_tokens=188``,
    ``reasoning_tokens=161``) -- so it is the figure that counts against
    ``max_output_tokens``, and what ``new_budget``'s ``successful`` argument is built from.
    ``StepRecord`` aggregates every reply that went into a case (up to four, with retries),
    not one reply alone; per the brief, this script uses that total as the stage-1 reply's
    own figure for a successful case, since the two are not recorded separately, and says so
    in its own output rather than presenting it as an exact per-reply count.

    There is no committed result yet: the confirmation run this script is written to read
    (plan Step 6, ``make s26-reply-budget``) has not been submitted as of this commit, so
    ``docs/results/s26-reply-budget-dev.txt`` does not exist. Step 7 makes it, from a real
    run id, once Step 6 has run.

Usage:
    uv run python -m scripts.reply_budget --run RUN_ID \
        [--out docs/results/s26-reply-budget-dev.txt] [--budget 2000]
"""

import argparse
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.scoring import report
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings

BUDGET_STEPS = (4_000, 8_000, 16_000)

# scoring/runner.py's _reply_detail: "(finish_reason=..., completion_tokens=...,
# reasoning_tokens=...)"
_DETAIL_RE = re.compile(
    r"\(finish_reason=(?P<finish_reason>[^,]+), completion_tokens=(?P<completion_tokens>[^,]+), "
    r"reasoning_tokens=(?P<reasoning_tokens>[^)]+)\)$"
)

# The run's own reply budget at the confirmation run this script was written to read
# (Step 6: `make s26-reply-budget` pins `--max-output-tokens 2000`, the pre-Task-9A
# default) -- overridable with `--budget` for a run made at a different one.
_DEFAULT_BUDGET = 2_000


def new_budget(successful: Sequence[int], failed_reasoning: Sequence[int]) -> int | None:
    """The smallest step at least twice the p99 of successful replies and above every failure."""
    ordered = sorted(successful)
    p99 = ordered[min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1)] if ordered else 0
    floor = max([2 * p99, *failed_reasoning], default=0)
    return next(
        (
            step
            for step in BUDGET_STEPS
            if step >= floor and step > max(failed_reasoning, default=0)
        ),
        None,
    )


def cause_confirmed(failures: Sequence[tuple[str, int]], *, budget: int) -> bool:
    """At least half the format failures are `length` with reasoning of at least half the budget."""
    hits = sum(
        1 for reason, reasoning in failures if reason == "length" and reasoning >= budget / 2
    )
    return bool(failures) and hits * 2 >= len(failures)


@dataclass(frozen=True)
class _Detail:
    """One reply-format failure's trailing bracket, parsed -- or "unrecorded" without one."""

    finish_reason: str
    reasoning_tokens: int | None


def _int_or_none(text: str) -> int | None:
    return None if text == "None" else int(text)


def _parse_detail(failure: str) -> _Detail:
    """The failure text's trailing ``_reply_detail`` bracket, or the pre-Task-9A placeholder.

    A failure text recorded before S2.6 Task 9A carries no such bracket -- that is not a
    parse bug to raise on, it is what an older run's failures look like, so it is reported
    under ``finish_reason="unrecorded"`` with no reasoning-token figure, rather than
    crashing.
    """
    match = _DETAIL_RE.search(failure)
    if match is None:
        return _Detail(finish_reason="unrecorded", reasoning_tokens=None)
    return _Detail(
        finish_reason=match["finish_reason"],
        reasoning_tokens=_int_or_none(match["reasoning_tokens"]),
    )


def _percentile(values: Sequence[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def _stats_line(label: str, values: Sequence[int]) -> str:
    if not values:
        return f"  {label}: no data"
    return (
        f"  {label}: n={len(values)} median={_percentile(values, 0.5)} "
        f"p90={_percentile(values, 0.9)} p99={_percentile(values, 0.99)} max={max(values)}"
    )


def summarise(cases: Sequence[CaseResult], *, budget: int = _DEFAULT_BUDGET) -> str:
    """Counts only (decision 0024): no case number, no title, no prose.

    Args:
        cases: one run's ``cases.jsonl`` rows, in any order.
        budget: the run's own ``max_output_tokens`` -- the confirmation run's is 2,000
            (``_DEFAULT_BUDGET``, the pre-Task-9A default), so this can be omitted for it.

    Returns:
        The report text: cases, failures by reason, the reply-format failures by
        ``finish_reason`` with their reasoning-token spread, the successful cases' per-reply
        token spread, the rule's verdict, and (if confirmed) the new budget.
    """
    lines = [f"cases: {len(cases)}", report.failure_summary(cases)]

    format_failures = [
        _parse_detail(c.failure) for c in cases if c.failure and c.failure.startswith("schema:")
    ]
    by_reason: dict[str, int] = {}
    for detail in format_failures:
        by_reason[detail.finish_reason] = by_reason.get(detail.finish_reason, 0) + 1
    reason_text = ", ".join(f"{k} {v}" for k, v in sorted(by_reason.items())) or "none"
    lines.append(f"reply-format failures by finish_reason: {reason_text}")

    failed_reasoning = [
        d.reasoning_tokens for d in format_failures if d.reasoning_tokens is not None
    ]
    lines.append(_stats_line("reply-format failures' reasoning tokens", failed_reasoning))

    successful_steps = [
        c.steps[0] for c in cases if c.failure is None and c.scores is not None and c.steps
    ]
    successful = [s.completion_tokens for s in successful_steps]
    successful_reasoning = [
        s.reasoning_tokens for s in successful_steps if s.reasoning_tokens is not None
    ]
    lines.append(
        "successful cases' per-reply tokens (a case's step total, taken as the stage-1 "
        "reply's own figure when the step aggregates more than one reply; reasoning tokens "
        "are a subset of the total, not additional to it):"
    )
    lines.append(_stats_line("  total (completion_tokens)", successful))
    lines.append(_stats_line("  reasoning tokens alone", successful_reasoning))

    length_failures = [(d.finish_reason, d.reasoning_tokens or 0) for d in format_failures]
    confirmed = cause_confirmed(length_failures, budget=budget)
    hits = sum(1 for r, t in length_failures if r == "length" and t >= budget / 2)
    lines.append(
        f"cause {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} against budget={budget} "
        f"({hits} of {len(length_failures)} reply-format failures are length with "
        f"reasoning >= {budget / 2:.0f})"
    )
    if confirmed:
        proposed = new_budget(successful, failed_reasoning)
        lines.append(
            f"new max_output_tokens: {proposed}"
            if proposed is not None
            else "new max_output_tokens: none of the budget steps "
            f"({', '.join(str(s) for s in BUDGET_STEPS)}) fit"
        )
    return "\n".join(lines)


def main(argv: Sequence[str]) -> int:
    """Read one run folder's ``cases.jsonl`` and ``run.jsonl``; print and optionally write."""
    parser = argparse.ArgumentParser(prog="reply_budget")
    parser.add_argument("--run", required=True, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="override the run's own max_output_tokens (default: read from run.jsonl)",
    )
    args = parser.parse_args(argv)

    folder = Settings().runs_dir / args.run
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    run_record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    budget = args.budget if args.budget is not None else run_record.max_output_tokens
    text = summarise(cases, budget=budget)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
