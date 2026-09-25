"""S2.6 Task 9A: confirm the reply-budget cause on one run, size it on another.

Status
    One-shot. Prints and, with ``--out``, writes counts only (decision 0024: no case number,
    no title, no prose).

    Task 9C fix round 1 (2026-09-25, final review of Task 9C): two more findings, before either
    development run is submitted. Important 1 -- the sizing guard Task 9C added only flagged
    ``None``/``"unrecorded"`` as ambiguous, so a reply that ended anything else *other than*
    ``"stop"`` or ``"length"`` (a genuine provider reason such as ``"content_filter"``,
    ``"error"`` or ``"tool_calls"``) was not guarded at all, and -- read from a failed case's
    earlier reply, invisible to that case's failure text -- was not seen at all. Such a reply
    ended before finishing, so its reasoning count is a lower bound, the same censoring the
    ``None`` case carries: a scored case with a ``content_filter`` reply of 15,900 reasoning
    tokens at a 16,000 budget gave "new max_output_tokens 16000"; the same reply as an earlier
    ``"error"`` reply in a failed case was invisible and gave 4000. ``_scan_sizing_replies``
    (renamed from ``_cut_off_and_unknown_reason``) now treats *any* finish reason other than
    ``"stop"`` or ``"length"`` as ambiguous, and the outcome line names the reason it found:
    "no step fits -- a reply in the sizing run did not finish normally (<reason>); returned to
    Andy". Separately (review Minor 4; see the plan's dated Deviations entry for the reasoning),
    every case's ``"stop"`` replies, scored or failed alike, now feed the successful-percentile
    pool (``_failed_case_stop_replies``) -- this can only raise a proposed budget, never lower
    one, and it never touches the failed side's own figures or ``cause_confirmed``'s ratio.
    Neither change touches ``new_budget``'s or ``cause_confirmed``'s own arithmetic.

    Task 9C (2026-09-25, Task 9A's final review) closes two gaps. First: a failed case has no
    step (``steps=()``), and its failure text names only the *last* reply it made
    (``_reply_detail``'s bracket) -- so a case whose stage-1 reply was cut off (``length``),
    retried successfully, and which then failed for an unrelated reason on stage 2 had that
    earlier cut-off reply invisible to the sizing run's cut-off guard. ``CaseResult`` now
    carries every reply a case received, scored or failed, in its own
    ``reply_completion_tokens``/``reply_reasoning_tokens``/``reply_finish_reasons`` tuples,
    filled from the same source as ``StepRecord``'s copy of them, but present even where the
    case has no step. This script's own scored-case reading (``_successful_case_replies``,
    which feeds the percentile and was unaffected by the first gap) now reads them from there
    instead of from the step; the cut-off/ambiguous-reason guard (``_scan_sizing_replies``)
    scans every case's own tuples directly, and only falls back to a failed case's failure-text
    bracket where a case predates Task 9C and carries none. Second: a reply whose
    ``finish_reason`` was never recorded (``None``, or ``"unrecorded"`` from a bracket-less
    pre-Task-9A failure) is neither a proven cut-off nor a proven "stop", so on its own it could
    let a wrong number out of the sizing run -- the sizing run's outcome now treats any such
    reply the same way as a cut-off one (widened by fix round 1, above, to every non-"stop",
    non-"length" reason). Neither guard changes ``new_budget``'s or ``cause_confirmed``'s own
    arithmetic; both only decide whether the outcome may call them at all.

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
    completion_tokens: int | None
    reasoning_tokens: int | None


def _int_or_none(text: str) -> int | None:
    return None if text == "None" else int(text)


def _parse_detail(failure: str) -> _Detail:
    """The failure text's trailing ``_reply_detail`` bracket, or the pre-Task-9A placeholder.

    A failure text recorded before S2.6 Task 9A carries no such bracket -- that is not a
    parse bug to raise on, it is what an older run's failures look like, so it is reported
    under ``finish_reason="unrecorded"`` with no completion- or reasoning-token figure,
    rather than crashing.
    """
    match = _DETAIL_RE.search(failure)
    if match is None:
        return _Detail(finish_reason="unrecorded", completion_tokens=None, reasoning_tokens=None)
    return _Detail(
        finish_reason=match["finish_reason"],
        completion_tokens=_int_or_none(match["completion_tokens"]),
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
    """One reply's own figures, read from a ``CaseResult``'s per-reply tuples (S2.6 Task 9C)."""

    completion_tokens: int
    reasoning_tokens: int | None
    finish_reason: str | None


def _case_replies(case: CaseResult) -> list[_Reply] | None:
    """The individual replies ``CaseResult`` itself recorded for one case (S2.6 Task 9C).

    ``None`` where nothing is recorded there -- either because the case made no call at all
    (a "cap" or "leak" failure has no replies to carry), or because the case was recorded
    before Task 9C added these tuples. This function does not tell the two apart -- it is
    simply the reading of whatever is there, and a caller that needs to distinguish them
    (``_fallback_failed_reply``, for a failed case) reads ``case.failure`` itself, not
    ``cost_usd``.
    """
    if not case.reply_completion_tokens:
        return None
    count = len(case.reply_completion_tokens)
    reasoning = case.reply_reasoning_tokens or (None,) * count
    finishes = case.reply_finish_reasons or (None,) * count
    return [
        _Reply(completion_tokens=c, reasoning_tokens=r, finish_reason=f)
        for c, r, f in zip(case.reply_completion_tokens, reasoning, finishes, strict=True)
    ]


def _fallback_failed_reply(case: CaseResult) -> _Reply | None:
    """The pre-Task-9C fallback: a failed case's *last* reply, from its failure-text bracket.

    Used only when ``CaseResult`` carries no per-reply tuples of its own (recorded before
    Task 9C) -- the failure text's trailing bracket (``_reply_detail``, S2.6 Task 9A) is all
    that survives of that case's replies, and it names only the one that ended the case, not
    every reply it made. ``None`` for anything but a ``"schema:"`` failure: a "model:" or
    "aborted:" failure carries no such bracket to recover. A pre-Task-9A failure text has no
    bracket at all, so ``completion_tokens`` is ``None`` there too -- reported as ``0``, since
    its ``finish_reason`` is then ``"unrecorded"`` and never ``"stop"``, so nothing reads this
    figure as a real token count (fix round 1, controller ruling on Minor 4).
    """
    if case.failure is None or not case.failure.startswith("schema:"):
        return None
    detail = _parse_detail(case.failure)
    return _Reply(
        completion_tokens=detail.completion_tokens or 0,
        reasoning_tokens=detail.reasoning_tokens,
        finish_reason=detail.finish_reason,
    )


@dataclass(frozen=True)
class _PerCaseReplies:
    """The per-reply data recoverable from a run's successful cases."""

    available: list[list[_Reply]]  # one list per successful case that recorded per-reply data
    unavailable_cases: int  # successful cases that recorded no recoverable reply data


def _successful_case_replies(cases: Sequence[CaseResult]) -> _PerCaseReplies:
    """The per-reply data behind every successful (unfailed, scored) case in ``cases``.

    S2.6 Task 9C: reads ``CaseResult``'s own tuples directly -- filled identically to
    ``StepRecord``'s for a scored case -- rather than the step's copy of them. A scored case
    never carries a failure-text bracket, so there is no fallback to try here; a case that
    made a call but recorded no tuples simply predates Task 9C. Whether the run has *no*
    scored cases at all is no longer read from here (fix round 1): completeness is decided by
    ``_cases_with_unrecoverable_replies``, across every case, not only scored ones.
    """
    successful = [c for c in cases if c.failure is None and c.scores is not None]
    per_case = [_case_replies(c) for c in successful]
    available = [replies for replies in per_case if replies is not None]
    return _PerCaseReplies(available, len(per_case) - len(available))


def _case_replies_with_fallback(case: CaseResult) -> list[_Reply]:
    """One case's replies -- ``CaseResult``'s own tuples, or the pre-Task-9C bracket fallback."""
    replies = _case_replies(case)
    if replies is not None:
        return replies
    fallback = _fallback_failed_reply(case)
    return [fallback] if fallback is not None else []


def _failed_case_stop_replies(cases: Sequence[CaseResult]) -> list[_Reply]:
    """Every reply that finished normally (``"stop"``) inside a *failed* case (fix round 1).

    Controller ruling on the review's Minor 4: a "successful reply" for the percentile means a
    reply that finished, whatever happened to its case afterwards -- a completed reply's own
    token count is a true measure of need, whether the schema went on to reject its content or
    a later reply in the same case failed instead. Only a case's ``"stop"`` replies are pulled
    in here; a failed case's other replies stay exactly where they already were (the
    failure-text bracket, read by ``_format_failures``, and Task 9C's cut-off/ambiguous scan),
    so this can only ever add to the successful-percentile pool -- never touch the failed
    side's own figures or ``cause_confirmed``'s ratio.
    """
    return [
        reply
        for case in cases
        if case.failure is not None
        for reply in _case_replies_with_fallback(case)
        if reply.finish_reason == "stop"
    ]


def _cases_with_unrecoverable_replies(cases: Sequence[CaseResult]) -> int:
    """Cases that made a call but recorded no recoverable reply at all (fix round 1).

    Neither ``CaseResult``'s own tuples (Task 9C) nor, for a failed case, its failure-text
    bracket fallback. A "cap" or "leak" case made no call and is not counted -- there is
    nothing to recover because nothing was ever sent. A run containing even one case that
    *did* call the model but left nothing recoverable cannot honestly claim its percentile
    pool is complete, whether or not another case's ``"stop"`` reply (Minor 4) happens to
    fill it with data.
    """
    return sum(1 for case in cases if case.cost_usd > 0.0 and not _case_replies_with_fallback(case))


@dataclass(frozen=True)
class _SizingScan:
    """What the sizing run's cut-off/ambiguous-reason scan found (S2.6 Task 9C, fix round 1)."""

    cut_off: int  # replies that ended "length" -- scored and failed cases alike
    ambiguous: int  # replies that finished neither "stop" nor "length"
    ambiguous_reason: str | None  # the first such reason found, for the outcome line


def _scan_sizing_replies(cases: Sequence[CaseResult]) -> _SizingScan:
    """Scan every reply of every case, scored or failed alike, for the sizing run's two guards.

    Reads ``CaseResult``'s own per-reply tuples, falling back to a failed case's failure-text
    bracket only where its own tuples are empty (pre-Task-9C). This is separate from -- and
    never feeds -- ``_classify_replies``'s successful/recovered split or ``new_budget``'s and
    ``cause_confirmed``'s arithmetic: its only job is to decide whether the sizing run's
    ``outcome:`` line may call them at all.

    Fix round 1 (review Important 1): a reply that ended anything other than ``"stop"`` or
    ``"length"`` -- ``None``, the pre-Task-9A placeholder ``"unrecorded"``, or a genuine
    provider reason such as ``"content_filter"``, ``"error"`` or ``"tool_calls"`` -- ended
    before finishing normally, so its own reasoning count is a lower bound on what it needed,
    the same censoring a cut-off ("length") reply carries. A content_filter reply of 15,900
    reasoning tokens at a 16,000 budget must not silently pass as a genuine, uncut need just
    because it is not literally ``"length"`` -- and, read from a failed case's *earlier* reply,
    it was invisible to Task 9A's own reading (only that case's failure text, naming its last
    reply) altogether. Every such reason -- across every case, scored or failed -- makes the
    whole run's outcome ambiguous, not just the one data point.
    """
    cut_off = 0
    ambiguous = 0
    first_reason: str | None = None
    for case in cases:
        for reply in _case_replies_with_fallback(case):
            if reply.finish_reason == "length":
                cut_off += 1
            elif reply.finish_reason != "stop":
                ambiguous += 1
                if first_reason is None:
                    first_reason = "None" if reply.finish_reason is None else reply.finish_reason
    return _SizingScan(cut_off, ambiguous, first_reason)


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


def _merge_failed_stop_replies(
    cases: Sequence[CaseResult], classified: _Classified
) -> tuple[list[int], list[int]]:
    """The successful-percentile pool, widened by every failed case's own "stop" replies.

    Fix round 1, controller ruling on the review's Minor 4. Can only ever add to
    ``classified.successful``/``successful_reasoning``, never remove from them or change what
    is already there -- the scored-case reading (``_successful_case_replies``) and
    ``_classify_replies``'s own split stay exactly as they were.
    """
    failed_stop = _failed_case_stop_replies(cases)
    successful = [*classified.successful, *(r.completion_tokens for r in failed_stop)]
    successful_reasoning = [
        *classified.successful_reasoning,
        *(r.reasoning_tokens for r in failed_stop if r.reasoning_tokens is not None),
    ]
    return successful, successful_reasoning


def summarise(cases: Sequence[CaseResult], *, budget: int = _DEFAULT_BUDGET) -> str:
    """One run's own numbers against the fixed rule -- kept for a rule check in isolation.

    At a real, censoring budget (2,000, the pre-fix-round-3 default) this over-states what
    budget is needed, for the reason fix round 3 exists: a successful reply is itself
    censored at ``budget``, so its own token count is not the true figure the rule wants.
    ``confirm_and_size`` is what a real reply-budget decision reads; this stays for tests and
    for reading one run's numbers on their own. Unlike ``confirm_and_size``, this applies
    neither the cut-off nor the ambiguous-finish-reason guard (fix round 1) -- its own "new
    max_output_tokens" line, when printed, is a raw application of the rule, not a vetted
    decision the way ``confirm_and_size``'s ``outcome:`` line is.

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
    # Fix round 1: "complete" no longer means "every scored case has tuples" alone -- a run
    # with no scored cases at all can still be complete if its failed cases' own "stop"
    # replies (Minor 4) are themselves fully recoverable. It is incomplete only where some
    # case that made a call left nothing recoverable at all.
    per_reply_data_available = _cases_with_unrecoverable_replies(cases) == 0
    successful, successful_reasoning = _merge_failed_stop_replies(cases, classified)

    lines.append(
        "successful replies' per-reply tokens (every reply that finished 'stop', scored or "
        "failed case alike; a truncated-then-recovered reply is reported separately below, "
        "not here -- fix round 1, controller ruling on Minor 4):"
    )
    if not per_reply_data_available:
        lines.append(
            "  unavailable: this run's scored cases carry no per-reply tuples on CaseResult "
            "(S2.6 Task 9C) -- a run recorded before Task 9C may still have them on its own "
            "steps.jsonl (Task 9A fix round 2), but this script no longer reads that"
        )
    else:
        if per_case.unavailable_cases:
            lines.append(
                f"  note: {per_case.unavailable_cases} successful case(s) predate the "
                "per-reply fields and are excluded from the figures below"
            )
        lines.append(_stats_line("  total (completion_tokens)", successful))
        lines.append(_stats_line("  reasoning tokens alone", successful_reasoning))

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
            proposed = new_budget(successful, combined_failed_reasoning)
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
    cut_off: int  # replies that ended "length", scored and failed cases alike (S2.6 Task 9C)
    ambiguous: int  # replies that finished neither "stop" nor "length" (fix round 1)
    ambiguous_reason: str | None  # the first such reason found, for the outcome line


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
    successful, successful_reasoning = _merge_failed_stop_replies(cases, classified)
    lines.append(
        f"truncated-then-recovered replies (finished other than 'stop' inside an "
        f"otherwise successful case): {classified.recovered_count}"
    )
    lines.append(_stats_line("  their reasoning tokens", classified.recovered_reasoning))
    # Fix round 1: "complete" no longer means "every scored case has tuples" alone -- see
    # ``_cases_with_unrecoverable_replies`` (the same reasoning as in ``summarise``).
    per_reply_available = _cases_with_unrecoverable_replies(cases) == 0
    lines.append(
        "successful replies' uncut per-reply tokens (every reply that finished 'stop', "
        "scored or failed case alike -- fix round 1, controller ruling on Minor 4):"
    )
    if not per_reply_available:
        lines.append(
            "  unavailable: this run's scored cases carry no per-reply tuples on CaseResult "
            "(S2.6 Task 9C) -- a run recorded before Task 9C may still have them on its own "
            "steps.jsonl (Task 9A fix round 2), but this script no longer reads that"
        )
    else:
        if per_case.unavailable_cases:
            lines.append(
                f"  note: {per_case.unavailable_cases} successful case(s) predate the "
                "per-reply fields and are excluded from the figures below"
            )
        lines.append(_stats_line("  total (completion_tokens)", successful))
        lines.append(_stats_line("  reasoning tokens alone", successful_reasoning))
    _length_failures, floor_reasoning = _length_failures_and_floor(failures, classified)
    # S2.6 Task 9C, fix round 1: scanned across every reply of every case (scored or failed),
    # not just the failed side's failure-text bracket -- the source ``new_budget``'s own
    # inputs above still read unchanged. See ``_scan_sizing_replies``.
    scan = _scan_sizing_replies(cases)
    lines.append(f"replies cut off at this run's own budget (finish_reason=length): {scan.cut_off}")
    lines.append(
        f"replies that did not finish normally (neither 'stop' nor 'length'): {scan.ambiguous}"
    )
    return _Sizing(
        lines=lines,
        successful=successful,
        failed_reasoning=floor_reasoning,
        per_reply_complete=per_reply_available,
        cut_off=scan.cut_off,
        ambiguous=scan.ambiguous,
        ambiguous_reason=scan.ambiguous_reason,
    )


def _outcome(confirmed: bool, sizing: _Sizing, size_budget: int) -> str:
    """The one ``outcome:`` line -- fail-closed wherever the sizing run cannot prove a number.

    Fix round 4 (controller ruling): a reply cut off at the sizing run's own budget means that
    budget itself censored it, so its reasoning tokens are a lower bound, not a need, and no
    budget can be proven from the run; likewise when the per-reply figures are missing (a
    pre-fix-round-2 step, or not one successful ``"stop"`` reply). Each goes back to Andy
    rather than letting ``new_budget`` answer from nothing.

    Task 9C added one more guard, checked right after the cut-off one and before the
    per-reply-data-unavailable one; fix round 1 widened it. A reply that finished anything
    other than ``"stop"`` or ``"length"`` -- unrecorded, or a genuine provider reason such as
    ``"content_filter"`` -- ended before finishing normally, so it is neither a proven cut-off
    nor a proven "stop": it cannot honestly answer either way, and it goes back to Andy too,
    rather than silently passing as a genuine, uncut need.
    """
    if not confirmed:
        return "outcome: not confirmed -- returned to Andy"
    if sizing.cut_off:
        return f"outcome: no step fits -- a reply was cut off at {size_budget}; returned to Andy"
    if sizing.ambiguous:
        return (
            "outcome: no step fits -- a reply in the sizing run did not finish normally "
            f"({sizing.ambiguous_reason}); returned to Andy"
        )
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
