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
    # Vestigial (decision 0054): the ``no-submissions`` run variant this recorded is retired
    # and nothing sets a value other than the default any more. Kept, not removed, so a
    # pre-0054 run folder's ``run.jsonl`` -- which does carry this key -- still deserialises;
    # the model is frozen with ``extra="forbid"``, so dropping the field would refuse to read
    # every run recorded before this change.
    docket_filter: str = "published"
    prompt_version: str
    model: str
    price_variant: str
    cap_usd: float
    budget_usd: float
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
    # Vestigial (decision 0054): used to hold the readable documents the ``no-submissions``
    # variant excluded on purpose, distinct from a cap drop. That variant is retired and
    # admission no longer excludes anything, so nothing sets this to a non-empty value any
    # more. Kept, not removed, so a pre-0054 ``steps.jsonl`` row -- which does carry this key
    # -- still deserialises; the model is frozen with ``extra="forbid"``, so dropping the
    # field would refuse to read every step recorded before this change.
    documents_filtered: tuple[str, ...] = ()
    payload_fingerprint: str
    hypothesis: Hypothesis
    observed_effect: Literal["confirmed", "weakened", "unchanged", ""]
    stop_reason: Literal["answered", "abstained", "budget", "cap", "nothing_available", ""]
    model: str
    price_variant: str
    prompt_tokens: int
    completion_tokens: int
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
    # Vestigial (decision 0054): see ``StepRecord.documents_filtered``. Kept only so a
    # pre-0054 ``cases.jsonl`` row still deserialises.
    documents_filtered: tuple[str, ...] = ()


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
