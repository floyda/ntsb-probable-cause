"""S2.6 Task 9A: read one run folder's ``cases.jsonl`` and report the reply-budget verdict.

Status
    One-shot. Prints and, with ``--out``, writes counts only (decision 0024: no case number,
    no title, no prose) -- cases; failures by reason (``report.failure_summary``, unchanged);
    the reply-format (``"schema:"``) failures broken down by ``finish_reason``, parsed from
    each failure text's trailing ``(finish_reason=..., completion_tokens=...,
    reasoning_tokens=...)`` bracket (S2.6 Task 9A, ``scoring/runner.py``'s ``_reply_detail``)
    -- a failure text from before that task carries no such bracket, and is counted under
    ``"unrecorded"`` rather than raising; their reasoning tokens (min/median/max); the
    successful cases' *per-reply* token spread (median/p90/p99/max, one figure per reply that
    finished ``"stop"``); truncated-then-recovered replies -- a reply that finished
    ``"length"`` inside an otherwise successful case, because a schema retry after it
    succeeded -- counted separately, on both sides of the rule (their reasoning tokens raise
    the floor `new_budget` sets, and they count as failures in the confirmation verdict,
    alongside the cases that failed outright); the rule's verdict (confirmed / not confirmed,
    with the counts behind it, both fixed in the Task 9A brief before any run); and, if
    confirmed, the new budget by ``new_budget``'s fixed rule.

    Fix round 2 (2026-09-25, code review): the first version fed `new_budget` a *case's*
    summed ``StepRecord.completion_tokens`` -- stage 1 plus stage 2, plus any retries -- and
    called it "the stage-1 reply's own figure", which it is not: `max_output_tokens` bounds
    one reply, not a case's total across up to four calls. On S2's dev-400 arm B run the gap
    was concrete: summed completion tokens gave p99=3,555 (-> proposed budget 8,000); the
    correct per-reply p99 gives 4,000. `StepRecord` now also records
    ``reply_completion_tokens``/``reply_reasoning_tokens``/``reply_finish_reasons`` -- the
    individual figures behind those sums, in call order -- and this script reads those, not
    the sums, wherever it can. A run whose ``steps.jsonl`` predates that fix carries none of
    the three tuples; this script says so explicitly (`per-reply data unavailable`) rather
    than silently falling back to the old, wrong, summed-total reading.

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
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, read_jsonl
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


@dataclass(frozen=True)
class _Reply:
    """One reply's own figures, read from a ``StepRecord``'s per-reply tuples."""

    completion_tokens: int
    reasoning_tokens: int | None
    finish_reason: str | None


def _step_replies(step: StepRecord) -> list[_Reply] | None:
    """The individual replies behind one successful case's step, or ``None`` if unrecorded.

    Fix round 2: a ``StepRecord`` written before this fix carries an empty
    ``reply_completion_tokens`` -- there is nothing here to read a per-reply figure from, and
    the caller must say so rather than substituting the case-level sum.
    """
    if not step.reply_completion_tokens:
        return None
    count = len(step.reply_completion_tokens)
    reasoning = step.reply_reasoning_tokens or (None,) * count
    finishes = step.reply_finish_reasons or (None,) * count
    return [
        _Reply(completion_tokens=c, reasoning_tokens=r, finish_reason=f)
        for c, r, f in zip(step.reply_completion_tokens, reasoning, finishes, strict=True)
    ]


@dataclass(frozen=True)
class _Classified:
    """The per-reply figures, split into the two sides the rule reads (fix round 2)."""

    successful: list[int]
    successful_reasoning: list[int]
    recovered_tuples: list[tuple[str, int]]  # for the verdict: counted as failures too
    recovered_reasoning: list[int]  # for new_budget's failed side
    recovered_count: int


def _classify_replies(available: Sequence[Sequence[_Reply]]) -> _Classified:
    """Split every reply of every successful case into "stop" (successful) or not (recovered).

    A reply that did not finish ``"stop"`` inside an otherwise successful case (``scores`` is
    not ``None``) means a schema retry after it must have gone on to succeed, or the case
    would have failed outright -- that reply is a truncated-then-recovered failure, not a
    successful one, whatever the case's own outcome was.
    """
    successful: list[int] = []
    successful_reasoning: list[int] = []
    recovered_tuples: list[tuple[str, int]] = []
    recovered_reasoning: list[int] = []
    recovered_count = 0
    for replies in available:
        for reply in replies:
            if reply.finish_reason == "stop":
                successful.append(reply.completion_tokens)
                if reply.reasoning_tokens is not None:
                    successful_reasoning.append(reply.reasoning_tokens)
            else:
                recovered_count += 1
                recovered_tuples.append(
                    (reply.finish_reason or "unrecorded", reply.reasoning_tokens or 0)
                )
                if reply.reasoning_tokens is not None:
                    recovered_reasoning.append(reply.reasoning_tokens)
    return _Classified(
        successful, successful_reasoning, recovered_tuples, recovered_reasoning, recovered_count
    )


def _percentile(values: Sequence[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def _stats_line(label: str, values: Sequence[int]) -> str:
    if not values:
        return f"  {label}: no data"
    return (
        f"  {label}: n={len(values)} min={min(values)} median={_percentile(values, 0.5)} "
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
        ``finish_reason`` with their reasoning-token spread, the successful cases'
        per-reply token spread, truncated-then-recovered replies, the rule's verdict, and
        (if confirmed) the new budget.
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

    # Per-reply figures: one entry per reply, not per case (a case makes up to four calls).
    successful_steps = [
        c.steps[0] for c in cases if c.failure is None and c.scores is not None and c.steps
    ]
    per_case_replies = [_step_replies(s) for s in successful_steps]
    available = [replies for replies in per_case_replies if replies is not None]
    unavailable_cases = len(per_case_replies) - len(available)
    classified = _classify_replies(available)
    successful = classified.successful
    successful_reasoning = classified.successful_reasoning
    recovered_tuples = classified.recovered_tuples
    recovered_reasoning = classified.recovered_reasoning
    recovered_count = classified.recovered_count

    per_reply_data_available = bool(available) or not per_case_replies
    lines.append(
        "successful cases' per-reply tokens (replies that finished 'stop' only; a "
        "truncated-then-recovered reply is reported separately below, not here):"
    )
    if not per_reply_data_available:
        lines.append(
            "  unavailable: this run's steps.jsonl predates the per-reply fields "
            "(S2.6 Task 9A fix round 2) -- no per-reply breakdown is recorded"
        )
    else:
        if unavailable_cases:
            lines.append(
                f"  note: {unavailable_cases} successful case(s) predate the per-reply "
                "fields and are excluded from the figures below"
            )
        lines.append(_stats_line("  total (completion_tokens)", successful))
        lines.append(_stats_line("  reasoning tokens alone", successful_reasoning))

    lines.append(
        f"truncated-then-recovered replies (finished other than 'stop' inside an "
        f"otherwise successful case): {recovered_count}"
    )
    lines.append(_stats_line("  their reasoning tokens", recovered_reasoning))

    length_failures = [(d.finish_reason, d.reasoning_tokens or 0) for d in format_failures]
    length_failures += recovered_tuples
    confirmed = cause_confirmed(length_failures, budget=budget)
    hits = sum(1 for r, t in length_failures if r == "length" and t >= budget / 2)
    lines.append(
        f"cause {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} against budget={budget} "
        f"({hits} of {len(length_failures)} format failures (failed cases + "
        f"truncated-then-recovered replies) are length with reasoning >= {budget / 2:.0f})"
    )
    if confirmed:
        if not per_reply_data_available:
            lines.append(
                "new max_output_tokens: cannot compute -- successful cases' per-reply "
                "tokens are unavailable in this run"
            )
        else:
            combined_failed_reasoning = failed_reasoning + recovered_reasoning
            proposed = new_budget(successful, combined_failed_reasoning)
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
