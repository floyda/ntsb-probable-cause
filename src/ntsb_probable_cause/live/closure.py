"""Closure records from a finished live run's folder (S3.3 spec section 8).

Pure: a run folder, the prepared cases (the queue entry, the raw record and the prefetched
docket) and the lockfile checksum go in; ``ClosureRecord`` values come out. The morning calls it
after a run, and again to complete a run whose records were not written.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Final

from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.schemas import ChooseDocuments
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.live.fetch import prelim_present
from ntsb_probable_cause.live.queue import QueuedCase, waited_days
from ntsb_probable_cause.live.records import ClosureRecord, DocumentLine
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.sources import TRAINING_CUTOFFS

CASES_FILE: Final = "cases.jsonl"
RUN_FILE: Final = "run.jsonl"
_CHOICE_STEPS: Final = frozenset({"choice1", "choice2"})


@dataclass(frozen=True)
class Prepared:
    """One case of a run: its queue entry, its raw record and its prefetched docket."""

    case: QueuedCase
    raw: dict[str, object]
    docket: Docket


def run_record(folder: Path) -> RunRecord:
    """The run's last ``RunRecord`` (the one that says whether it finished)."""
    return read_jsonl(folder / RUN_FILE, RunRecord)[-1]


def build_records(folder: Path, prepared: Sequence[Prepared], lock_sha: str) -> list[ClosureRecord]:
    """Return one closure record per prepared case, from the run folder's files."""
    record = run_record(folder)
    results = {r.case_id: r for r in read_jsonl(folder / CASES_FILE, CaseResult)}
    trail = folder / TRAIL_FILE
    calls = read_jsonl(trail, AgentCall) if trail.is_file() else []
    cutoff = TRAINING_CUTOFFS[record.model]
    out: list[ClosureRecord] = []
    for p in prepared:
        case_calls = [c for c in calls if c.case_id == p.case.case_id]
        result = results.get(p.case.case_id)
        scored = result is not None and bool(result.verdict_occurrence)
        scores = result.scores if scored and result is not None else None
        failure = "missing result" if result is None else result.failure
        out.append(
            ClosureRecord(
                case_id=p.case.case_id,
                mkey=p.case.mkey,
                closed_on=p.case.closed_on,
                closure_run=p.case.closure_run,
                waited_days=waited_days(p.case, record.started.astimezone(UTC).date()),
                first_sent=min((c.sent_at for c in case_calls), default=None),
                last_returned=max((c.returned_at for c in case_calls), default=None),
                commit_sha=record.commit_sha,
                dirty=record.dirty,
                prompt_version=record.prompt_version,
                price_variant="batch" if record.price_variant == "batch" else "standard",
                model=record.model,
                reasoning_effort=record.reasoning_effort,
                training_cutoff=cutoff.day,
                training_cutoff_source=cutoff.source,
                uv_lock_sha256=lock_sha,
                documents=document_lines(p.docket, case_calls),
                prelim_present=prelim_present(p.raw),
                outcome="not coded" if failure else "coded",
                failure=failure,
                marks=() if result is None else tuple(m.kind for m in result.marks),
                scored=scored,
                top1=None if scores is None else scores.occurrence_top1,
                top3=None if scores is None else scores.occurrence_top3,
                abstained=None if scores is None else scores.abstained,
                cost_usd=0.0 if result is None else result.cost_usd,
            )
        )
    return out


def document_lines(docket: Docket, calls: Sequence[AgentCall]) -> tuple[DocumentLine, ...]:
    """Each document's status, and what the agent decided: read, skipped, or never on offer."""
    offered: set[int] = set()
    read: set[int] = set()
    for call in calls:
        if call.step not in _CHOICE_STEPS or call.protocol_error is not None:
            continue
        offered.update(call.offered)
        choice = ChooseDocuments.model_validate(call.arguments)
        read.update(d.document for d in choice.decisions if d.read and d.document in call.offered)
    return tuple(
        DocumentLine(
            position=d.entry.index,
            title=d.entry.title,
            status=d.status,
            ellery=("read" if d.entry.index in read else "skipped")
            if d.entry.index in offered
            else None,
        )
        for d in docket.documents
    )
