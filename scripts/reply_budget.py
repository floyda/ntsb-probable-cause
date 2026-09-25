"""S2.6 Task 9A: confirm the reply-budget cause on one run, size it on another.

Status
    One-shot. Prints and, with ``--out``, writes counts only (decision 0024: no case number,
    no title, no prose).

    Fix round 4 (2026-09-25, re-review and controller ruling; the rule's numbers are
    unchanged): the outcome is fail-closed. A sizing run with any reply that ended
    ``length`` -- in a failed case or a recovered one -- was cut off by the sizing budget
    itself, so no budget can be proven from it: "no step fits -- a reply was cut off at
    <budget>; returned to Andy". A sizing run without per-reply figures, or without one
    successful ``"stop"`` reply, gives "per-reply data unavailable -- returned to Andy"
    rather than letting ``new_budget`` answer from an empty list. And the pair is refused
    unless the confirmation run's budget is the lower one, so swapped arguments cannot size
    from censored replies. Fix round 3's paragraph below said a failure's reasoning tokens
    are "never censored"; that was wrong. Reasoning tokens count against
    ``max_output_tokens``, so a cut-off reply reports at most the budget
    (``tests/fixtures/openrouter/batch.json``, ``probe-1``: ``length`` at ``max_tokens`` 300,
    completion 300, reasoning 300). The confirmation test (reasoning of at least 1,000 at a
    2,000 budget) stays valid, because any count up to the budget is still observable; the
    same bound is why the sizing run needs the "cut off" guard above.

    Fix round 3 (2026-09-25, Andy's decision, verbatim "Let's go with b and work this out
    properly"): at a 2,000-token budget every successful reply is itself censored at 2,000,
    so ``new_budget``'s "twice the p99 of successful replies" can only ever answer 4,000 --
    it can confirm the cause but cannot size the budget honestly. So there are **two**
    development runs, identical except ``max_output_tokens``: a **confirmation** run at the
    old budget (2,000), whose failures prove the cause via the reasoning tokens inside
    them (corrected in fix round 4: those counts are bounded by the budget, but a count of
    1,000 or more is still observable at 2,000); and a
    **sizing** run at a roomy budget (16,000), whose successful replies' own token counts are
    the real, uncut figures the fixed rule needs. ``confirm_and_size`` reads both, refuses
    them unless they are the same run in every respect but the budget
    (``refuse_mismatched_runs``), and applies the unchanged rule (``new_budget``,
    ``cause_confirmed``) to the confirmation run's failures and the sizing run's successful
    replies respectively. ``summarise`` (one run) stays as it was for anything that only
    needs one run's own numbers, or a rule check in isolation (tests).

    Fix round 2 (2026-09-25, code review): the first version fed ``new_budget`` a *case's*
    summed ``StepRecord.completion_tokens`` -- stage 1 plus stage 2, plus any retries -- and
    called it "the stage-1 reply's own figure", which it is not: ``max_output_tokens`` bounds
    one reply, not a case's total across up to four calls. ``StepRecord`` now also records
    ``reply_completion_tokens``/``reply_reasoning_tokens``/``reply_finish_reasons`` -- the
    individual figures behind those sums, in call order -- and this script reads those, not
    the sums, wherever it can. A run whose ``steps.jsonl`` predates that fix carries none of
    the three tuples; this script says so explicitly (`per-reply data unavailable`) rather
    than silently falling back to the old, wrong, summed-total reading.

    There is no committed result yet: the two development runs this script is written to read
    (plan Steps 6-7, ``make s26-reply-budget`` and ``make s26-reply-budget-roomy``) have not
    been submitted as of this commit, so ``docs/results/s26-reply-budget-dev.txt`` does not
    exist. Step 7 makes it, from the two real run ids, once Step 6 has run both.

Usage:
    uv run python -m scripts.reply_budget --confirm RUN_ID --size RUN_ID \
        [--out docs/results/s26-reply-budget-dev.txt]

    uv run python -m scripts.reply_budget --run RUN_ID [--out PATH] [--budget 2000]
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
# default) -- overridable with `--budget` for a run made at a different one. Used only by
# the single-run `summarise`; the two-run `confirm_and_size` always reads each run's own
# recorded `max_output_tokens`.
_DEFAULT_BUDGET = 2_000

# The fields two runs must agree on to be "the same run at two reply budgets" (fix round 3,
# Andy's decision B). `evidence_version` is read separately, by `getattr` with a default, so
# this list -- and this script -- works before Task 8 gives `RunRecord` that field.
_MATCH_FIELDS = (
    "sample",
    "arm",
    "model",
    "reasoning_effort",
    "price_variant",
    "commit_sha",
    "dirty",
)


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


def refuse_mismatched_runs(confirm: RunRecord, size: RunRecord) -> None:
    """Refuse two runs that are not the same run at two reply budgets (Andy's decision B).

    ``confirm_and_size`` reads the confirmation run's failures and the sizing run's
    successful replies as if they were two windows onto one experiment -- which is only
    sound if nothing else differed between them. Every mismatch names the field and both
    values, so a wrong pair of run ids is refused rather than silently combined.

    Args:
        confirm: the confirmation run's ``RunRecord``.
        size: the sizing run's ``RunRecord``.

    Raises:
        SystemExit: the two runs differ in a field they must match, or the confirmation
            run's ``max_output_tokens`` is not lower than the sizing run's (the one field
            the whole comparison depends on, and the direction it must go).
    """
    for field in _MATCH_FIELDS:
        confirm_value, size_value = getattr(confirm, field), getattr(size, field)
        if confirm_value != size_value:
            raise SystemExit(
                f"--confirm and --size runs differ in {field}: {confirm_value!r} vs "
                f"{size_value!r} -- they must be the same run at two reply budgets, not two "
                "different runs"
            )
    # `evidence_version` does not exist on `RunRecord` before Task 8; `getattr` with a
    # default means this check (and this script) works either side of that task.
    confirm_version = getattr(confirm, "evidence_version", "v1")
    size_version = getattr(size, "evidence_version", "v1")
    if confirm_version != size_version:
        raise SystemExit(
            f"--confirm and --size runs differ in evidence_version: {confirm_version!r} vs "
            f"{size_version!r} -- they must be the same run at two reply budgets, not two "
            "different runs"
        )
    # Fix round 4: lower, not merely different. With the arguments swapped the "sizing" run
    # would be the one at the old budget, whose successful replies are censored at it --
    # exactly the reading the pair exists to avoid.
    if confirm.max_output_tokens >= size.max_output_tokens:
        raise SystemExit(
            "--confirm run's max_output_tokens must be lower than the --size run's (they "
            f"were {confirm.max_output_tokens} and {size.max_output_tokens}) -- the pair is "
            "one run at the old budget and one roomy enough to measure uncut need; "
            "were the arguments swapped?"
        )


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


def _format_failures(cases: Sequence[CaseResult]) -> list[_Detail]:
    """Every ``"schema:"`` (reply-format) failure in ``cases``, parsed."""
    return [
        _parse_detail(c.failure) for c in cases if c.failure and c.failure.startswith("schema:")
    ]


def _reason_breakdown(details: Sequence[_Detail]) -> str:
    """``"length 2, unrecorded 1"``, or ``"none"``."""
    by_reason: dict[str, int] = {}
    for detail in details:
        by_reason[detail.finish_reason] = by_reason.get(detail.finish_reason, 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(by_reason.items())) or "none"


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
class _PerCaseReplies:
    """The per-reply data recoverable from a run's successful cases."""

    available: list[list[_Reply]]  # one list per successful case that recorded per-reply data
    unavailable_cases: int  # successful cases whose step predates the per-reply fields
    had_successful_cases: bool  # whether the run had any successful cases at all


def _successful_case_replies(cases: Sequence[CaseResult]) -> _PerCaseReplies:
    """The per-reply data behind every successful (unfailed, scored) case in ``cases``."""
    successful_steps = [
        c.steps[0] for c in cases if c.failure is None and c.scores is not None and c.steps
    ]
    per_case = [_step_replies(s) for s in successful_steps]
    available = [replies for replies in per_case if replies is not None]
    return _PerCaseReplies(available, len(per_case) - len(available), bool(per_case))


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


def _cap_hits(cases: Sequence[CaseResult]) -> tuple[int, int]:
    """(cases with at least one document dropped by the per-case cap, total cases)."""
    return sum(1 for c in cases if c.documents_not_read), len(cases)


def _length_failures_and_floor(
    format_failures: Sequence[_Detail], classified: _Classified
) -> tuple[list[tuple[str, int]], list[int]]:
    """The tuples ``cause_confirmed`` reads, and the reasoning tokens ``new_budget`` reads.

    From one run's schema failures plus its truncated-then-recovered replies.
    """
    length_failures = [(d.finish_reason, d.reasoning_tokens or 0) for d in format_failures]
    length_failures += classified.recovered_tuples
    failed_reasoning = [
        d.reasoning_tokens for d in format_failures if d.reasoning_tokens is not None
    ]
    failed_reasoning += classified.recovered_reasoning
    return length_failures, failed_reasoning


def summarise(cases: Sequence[CaseResult], *, budget: int = _DEFAULT_BUDGET) -> str:
    """One run's own numbers against the fixed rule -- kept for a rule check in isolation.

    At a real, censoring budget (2,000, the pre-fix-round-3 default) this over-states what
    budget is needed, for the reason fix round 3 exists: a successful reply is itself
    censored at ``budget``, so its own token count is not the true figure the rule wants.
    ``confirm_and_size`` is what a real reply-budget decision reads; this stays for tests and
    for reading one run's numbers on their own.

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

    format_failures = _format_failures(cases)
    lines.append(f"reply-format failures by finish_reason: {_reason_breakdown(format_failures)}")
    failed_reasoning = [
        d.reasoning_tokens for d in format_failures if d.reasoning_tokens is not None
    ]
    lines.append(_stats_line("reply-format failures' reasoning tokens", failed_reasoning))

    per_case = _successful_case_replies(cases)
    classified = _classify_replies(per_case.available)
    per_reply_data_available = bool(per_case.available) or not per_case.had_successful_cases

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
        if per_case.unavailable_cases:
            lines.append(
                f"  note: {per_case.unavailable_cases} successful case(s) predate the "
                "per-reply fields and are excluded from the figures below"
            )
        lines.append(_stats_line("  total (completion_tokens)", classified.successful))
        lines.append(_stats_line("  reasoning tokens alone", classified.successful_reasoning))

    lines.append(
        f"truncated-then-recovered replies (finished other than 'stop' inside an "
        f"otherwise successful case): {classified.recovered_count}"
    )
    lines.append(_stats_line("  their reasoning tokens", classified.recovered_reasoning))

    length_failures, combined_failed_reasoning = _length_failures_and_floor(
        format_failures, classified
    )
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
            proposed = new_budget(classified.successful, combined_failed_reasoning)
            lines.append(
                f"new max_output_tokens: {proposed}"
                if proposed is not None
                else "new max_output_tokens: none of the budget steps "
                f"({', '.join(str(s) for s in BUDGET_STEPS)}) fit"
            )
    return "\n".join(lines)


def _confirmation_section(cases: Sequence[CaseResult], record: RunRecord) -> tuple[list[str], bool]:
    """Section 1: the confirmation run's failure lines and verdict.

    Returns:
        The section's lines, and whether the cause is confirmed at this run's own budget.
    """
    budget = record.max_output_tokens
    lines = [
        f"confirmation run: {record.run_id} (max_output_tokens={budget})",
        f"cases: {len(cases)}",
    ]
    failures = _format_failures(cases)
    lines.append(f"reply-format failures by finish_reason: {_reason_breakdown(failures)}")
    failed_reasoning = [d.reasoning_tokens for d in failures if d.reasoning_tokens is not None]
    lines.append(_stats_line("reply-format failures' reasoning tokens", failed_reasoning))
    classified = _classify_replies(_successful_case_replies(cases).available)
    lines.append(
        f"truncated-then-recovered replies (finished other than 'stop' inside an "
        f"otherwise successful case): {classified.recovered_count}"
    )
    lines.append(_stats_line("  their reasoning tokens", classified.recovered_reasoning))
    length_failures, _floor = _length_failures_and_floor(failures, classified)
    confirmed = cause_confirmed(length_failures, budget=budget)
    hits = sum(1 for r, t in length_failures if r == "length" and t >= budget / 2)
    lines.append(
        f"cause {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} against budget={budget} "
        f"({hits} of {len(length_failures)} format failures (failed cases + "
        f"truncated-then-recovered replies) are length with reasoning >= {budget / 2:.0f})"
    )
    return lines, confirmed


@dataclass(frozen=True)
class _Sizing:
    """Section 2's lines, and what the outcome reads from the sizing run (fix round 4)."""

    lines: list[str]
    successful: list[int]  # the "stop" replies' completion tokens -- new_budget's first input
    failed_reasoning: list[int]  # the failed side's reasoning tokens -- new_budget's second
    per_reply_complete: bool  # every successful case recorded its per-reply figures
    cut_off: int  # replies that ended "length" -- failed cases and recovered replies alike


def _sizing_section(cases: Sequence[CaseResult], record: RunRecord) -> _Sizing:
    """Section 2: the sizing run's failure and per-reply lines, and what the outcome reads."""
    budget = record.max_output_tokens
    lines = [
        f"sizing run: {record.run_id} (max_output_tokens={budget})",
        f"cases: {len(cases)}",
    ]
    failures = _format_failures(cases)
    lines.append(
        "reply-format failures by finish_reason (a roomy budget should remove almost all "
        f"of these): {_reason_breakdown(failures)}"
    )
    failed_reasoning_shown = [
        d.reasoning_tokens for d in failures if d.reasoning_tokens is not None
    ]
    lines.append(_stats_line("reply-format failures' reasoning tokens", failed_reasoning_shown))
    per_case = _successful_case_replies(cases)
    classified = _classify_replies(per_case.available)
    lines.append(
        f"truncated-then-recovered replies (finished other than 'stop' inside an "
        f"otherwise successful case): {classified.recovered_count}"
    )
    lines.append(_stats_line("  their reasoning tokens", classified.recovered_reasoning))
    per_reply_available = bool(per_case.available) or not per_case.had_successful_cases
    lines.append("successful replies' uncut per-reply tokens:")
    if not per_reply_available:
        lines.append(
            "  unavailable: this run's steps.jsonl predates the per-reply fields "
            "(S2.6 Task 9A fix round 2) -- no per-reply breakdown is recorded"
        )
    else:
        if per_case.unavailable_cases:
            lines.append(
                f"  note: {per_case.unavailable_cases} successful case(s) predate the "
                "per-reply fields and are excluded from the figures below"
            )
        lines.append(_stats_line("  total (completion_tokens)", classified.successful))
        lines.append(_stats_line("  reasoning tokens alone", classified.successful_reasoning))
    length_failures, floor_reasoning = _length_failures_and_floor(failures, classified)
    cut_off = sum(1 for reason, _reasoning in length_failures if reason == "length")
    lines.append(f"replies cut off at this run's own budget (finish_reason=length): {cut_off}")
    return _Sizing(
        lines=lines,
        successful=classified.successful,
        failed_reasoning=floor_reasoning,
        per_reply_complete=bool(per_case.available) and not per_case.unavailable_cases,
        cut_off=cut_off,
    )


def _outcome(confirmed: bool, sizing: _Sizing, size_budget: int) -> str:
    """The one ``outcome:`` line -- fail-closed wherever the sizing run cannot prove a number.

    Fix round 4 (controller ruling): a reply cut off at the sizing run's own budget means that
    budget itself censored it, so its reasoning tokens are a lower bound, not a need, and no
    budget can be proven from the run; likewise when the per-reply figures are missing (a
    pre-fix-round-2 step, or not one successful ``"stop"`` reply). Each goes back to Andy
    rather than letting ``new_budget`` answer from nothing.
    """
    if not confirmed:
        return "outcome: not confirmed -- returned to Andy"
    if sizing.cut_off:
        return f"outcome: no step fits -- a reply was cut off at {size_budget}; returned to Andy"
    if not sizing.per_reply_complete or not sizing.successful:
        return "outcome: per-reply data unavailable -- returned to Andy"
    proposed = new_budget(sizing.successful, sizing.failed_reasoning)
    if proposed is None:
        return "outcome: no step fits -- returned to Andy"
    return f"outcome: new max_output_tokens {proposed}"


def confirm_and_size(
    confirm_cases: Sequence[CaseResult],
    confirm_record: RunRecord,
    size_cases: Sequence[CaseResult],
    size_record: RunRecord,
) -> str:
    """Confirm the cause at the old budget; size the budget at a roomy one (Andy's decision B).

    Fix round 3: the confirmation run's failures prove the cause; the sizing run's
    successful replies give the rule the per-reply figures it needs, uncut unless a reply
    reached 16,000 tokens.

    Fix round 4: a failure's reasoning tokens *are* bounded by the budget -- they count
    against ``max_output_tokens``, so a cut-off reply reports at most the budget
    (``tests/fixtures/openrouter/batch.json``, ``probe-1``: ``length`` at ``max_tokens``
    300, completion 300, reasoning 300). The confirmation test still holds, because it asks
    only whether reasoning reached 1,000 of 2,000, and any count up to the budget is still
    observable. The same bound is why the sizing run needs its own guard: a reply cut off at
    16,000 shows only that its need was at least that much, so any ``length`` reply there
    sends the outcome back to Andy instead of sizing from it (``_outcome``). So does missing
    per-reply data: the outcome is never computed from nothing.

    Args:
        confirm_cases: the confirmation run's ``cases.jsonl`` rows.
        confirm_record: the confirmation run's own ``RunRecord``.
        size_cases: the sizing run's ``cases.jsonl`` rows.
        size_record: the sizing run's own ``RunRecord``.

    Returns:
        The two-section report text, ending with one ``outcome:`` line.

    Raises:
        SystemExit: the two runs are not the same run at two reply budgets, the
            confirmation run's lower (``refuse_mismatched_runs``).
    """
    refuse_mismatched_runs(confirm_record, size_record)
    confirm_lines, confirmed = _confirmation_section(confirm_cases, confirm_record)
    sizing = _sizing_section(size_cases, size_record)

    confirm_cap_hit, confirm_total = _cap_hits(confirm_cases)
    size_cap_hit, size_total = _cap_hits(size_cases)
    cap_lines = [
        "cases the per-case cap cut short (a larger reply-budget reserve leaves slightly "
        "less room for documents under the cap):",
        f"  confirmation run: {confirm_cap_hit} of {confirm_total}",
        f"  sizing run: {size_cap_hit} of {size_total}",
    ]

    outcome = _outcome(confirmed, sizing, size_record.max_output_tokens)
    return "\n".join([*confirm_lines, "", *sizing.lines, *cap_lines, "", outcome])


def main(argv: Sequence[str]) -> int:
    """Read one run (``--run``) or a confirm/size pair (``--confirm``/``--size``).

    Prints, and with ``--out`` also writes, the report text.
    """
    parser = argparse.ArgumentParser(prog="reply_budget")
    parser.add_argument("--run", default=None, metavar="RUN_ID")
    parser.add_argument("--confirm", default=None, metavar="RUN_ID")
    parser.add_argument("--size", default=None, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="override the --run run's own max_output_tokens (default: read from run.jsonl)",
    )
    args = parser.parse_args(argv)

    runs_dir = Settings().runs_dir
    if args.confirm or args.size:
        if not (args.confirm and args.size):
            raise SystemExit("--confirm and --size must be given together")
        if args.run:
            raise SystemExit("--run cannot be combined with --confirm/--size")
        confirm_folder = runs_dir / args.confirm
        size_folder = runs_dir / args.size
        confirm_cases = read_jsonl(confirm_folder / "cases.jsonl", CaseResult)
        confirm_record = read_jsonl(confirm_folder / "run.jsonl", RunRecord)[0]
        size_cases = read_jsonl(size_folder / "cases.jsonl", CaseResult)
        size_record = read_jsonl(size_folder / "run.jsonl", RunRecord)[0]
        text = confirm_and_size(confirm_cases, confirm_record, size_cases, size_record)
    elif args.run:
        folder = runs_dir / args.run
        cases = read_jsonl(folder / "cases.jsonl", CaseResult)
        run_record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
        budget = args.budget if args.budget is not None else run_record.max_output_tokens
        text = summarise(cases, budget=budget)
    else:
        raise SystemExit("either --run, or --confirm together with --size, is required")

    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
