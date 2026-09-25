"""Run, case and step records, and their JSON-lines I/O (spec §6.4)."""

import hashlib
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores


class RunRecord(BaseModel):
    """One evaluation run: what was run, against what sample and arm, and its totals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    sample: str
    arm: Literal["A", "B", "ceiling"]
    exclusions: tuple[str, ...]
    includes: tuple[str, ...]
    prompt_version: str
    model: str
    # None on a run from before S2.4, which sent no level and used the provider's default.
    reasoning_effort: str | None = None
    price_variant: str
    cap_usd: float
    budget_usd: float
    # 2000 on a run from before S2.6 Task 9A: the old ModelSettings default.
    max_output_tokens: int = 2000
    commit_sha: str
    dirty: bool
    started: datetime
    finished: datetime | None = None
    batch_ids: tuple[str, ...] = ()
    cases: int = 0
    cost_usd: float = 0.0
    reported_batch_cost_usd: float | None = None


class StepRecord(BaseModel):
    """One step of a trail; a one-shot run writes exactly one (spec §6.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    step: int
    arm: str
    condition: Literal["full", "masked"]
    day: int | None
    tool: str
    arguments: dict[str, object]
    reason: str
    expected_effect: str
    returned_roles: tuple[str, ...]
    not_available: tuple[str, ...]
    documents_attached: tuple[str, ...] = ()
    documents_not_read: tuple[str, ...] = ()
    payload_fingerprint: str
    hypothesis: Hypothesis
    observed_effect: Literal["confirmed", "weakened", "unchanged", ""]
    stop_reason: Literal["answered", "abstained", "budget", "cap", "nothing_available", ""]
    model: str
    price_variant: str
    prompt_tokens: int
    completion_tokens: int
    # None when no reply for the case reported one (S2.6 Task 9A).
    reasoning_tokens: int | None = None
    # The per-reply figures behind the sums above, in call order (S2.6 Task 9A fix round 2):
    # a case makes up to four replies (stage 1 + stage 2, each with one retry), and the
    # summed fields cannot tell a single reply's own token count apart from another's, which
    # ``scripts/reply_budget.py`` needs to set a budget from real per-call figures rather
    # than a case-level total. Empty on a ``StepRecord`` written before this fix: the summed
    # fields are what such a step still has, and callers must not silently substitute them
    # for a per-reply breakdown that was never recorded.
    reply_completion_tokens: tuple[int, ...] = ()
    reply_reasoning_tokens: tuple[int | None, ...] = ()
    reply_finish_reasons: tuple[str | None, ...] = ()
    cost_usd: float
    cumulative_cost_usd: float
    commit_sha: str
    dirty: bool


class CaseResult(BaseModel):
    """One case's trail, verdict codes, scores, cost and failure reason, if any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    split: str
    fatal: bool
    investigation_class: str | None
    report_flavour: str | None
    verdict_occurrence: tuple[str, ...]
    verdict_findings: tuple[str, ...]
    verdict_findings_in_cause: tuple[str, ...]
    steps: tuple[StepRecord, ...]
    scores: CaseScores | None
    cost_usd: float
    failure: str | None
    # Set for every arm B case, including one that fails "cap" before any step is recorded
    # (``steps=()``): the docket outcome must not be invisible just because the case never
    # reached a model call (decision 0043; fix round 1, Finding 4).
    documents_not_read: tuple[str, ...] = ()
    # Every reply the case received, in call order, whether the case was scored or failed
    # (S2.6 Task 9C). A failed case has no step (``steps=()``), so ``StepRecord``'s own copy
    # of these tuples is invisible to a failed case -- and a case that failed on stage 2 after
    # an earlier reply was cut off and retried carries only its *last* reply's facts in its
    # failure text (``_reply_detail``), never the earlier one. These three tuples are filled
    # from ``ctx.replies`` for every case that made at least one call; a case that failed
    # before any call ("cap", "leak") made none and these stay empty, and so does a
    # ``CaseResult`` written before this fix.
    reply_completion_tokens: tuple[int, ...] = ()
    reply_reasoning_tokens: tuple[int | None, ...] = ()
    reply_finish_reasons: tuple[str | None, ...] = ()


def fingerprint(payload: Payload) -> str:
    """SHA-256 of the rendered payload; stored instead of the text (spec §6.4)."""
    return hashlib.sha256(payload.text.encode()).hexdigest()


def write_jsonl(path: Path, rows: Iterable[BaseModel]) -> None:
    """Append rows as JSON lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def read_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Read every row of one record type."""
    return [model.model_validate_json(line) for line in path.read_text().splitlines() if line]
