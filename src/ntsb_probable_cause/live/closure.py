"""Closure records from a finished live run's folder (S3.3 spec section 8).

Pure: a run folder, the prepared cases (the queue entry, the raw record and the prefetched
docket) and the lockfile checksum go in; ``ClosureRecord`` values come out. The morning calls it
after a run, and again to complete a run whose records were not written.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Final

from ntsb_probable_cause.agent.drive import REPLIES_FILE, ReplyRow
from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.schemas import ChooseDocuments
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.live.fetch import prelim_present
from ntsb_probable_cause.live.queue import QueuedCase, waited_days
from ntsb_probable_cause.live.records import (
    DOCKETS_FILE,
    ClosureRecord,
    DocketHashes,
    DocumentLine,
)
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


def is_finished(folder: Path) -> bool:
    """Whether the run folder's ``run.jsonl`` says it finished: the run's commit point.

    ``run.jsonl`` goes up to the bucket last (``cloud.push_order``), so a folder whose last run
    record has no ``finished`` time, or that has none, is a run still to resume, and nothing
    else in it is read as a result (final review, wave A, item A3).
    """
    path = folder / RUN_FILE
    if not path.is_file():
        return False
    records = read_jsonl(path, RunRecord)
    return bool(records) and records[-1].finished is not None


def build_records(
    folder: Path,
    prepared: Sequence[Prepared],
    lock_sha: str,
    dockets: Mapping[str, DocketHashes],
) -> list[ClosureRecord]:
    """Return one closure record per prepared case, from the run folder's files.

    ``dockets`` is the run's ``dockets.json`` by case id: the hashes the run first fetched, so a
    resume that fetched the docket again never changes them (final review, wave A, item A2).

    Raises:
        ConfigurationError: a prepared case has no entry in ``dockets``.
    """
    record = run_record(folder)
    results = {r.case_id: r for r in read_jsonl(folder / CASES_FILE, CaseResult)}
    trail = folder / TRAIL_FILE
    calls = read_jsonl(trail, AgentCall) if trail.is_file() else []
    replies_path = folder / REPLIES_FILE
    replies = read_jsonl(replies_path, ReplyRow) if replies_path.is_file() else []
    cutoff = TRAINING_CUTOFFS[record.model]
    out: list[ClosureRecord] = []
    for p in prepared:
        case_calls = [c for c in calls if c.case_id == p.case.case_id]
        result = results.get(p.case.case_id)
        scored = result is not None and bool(result.verdict_occurrence)
        scores = result.scores if scored and result is not None else None
        failure = "missing result" if result is None else result.failure
        hashes = dockets.get(p.case.case_id)
        if hashes is None:
            raise ConfigurationError(
                f"the run's {DOCKETS_FILE} holds no entry for one of its cases, so its closure "
                "record cannot name the files it was coded from"
            )
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
                event_date=p.case.event_date,
                listing_sha256=hashes.listing_sha256,
                request_sha256s=tuple(
                    r.request_sha256
                    for r in sorted(
                        (r for r in replies if r.case_id == p.case.case_id),
                        key=lambda r: r.call_index,
                    )
                ),
                replied_models=tuple(
                    sorted({c.reply_model for c in case_calls if c.reply_model is not None})
                ),
                providers=tuple(
                    sorted({c.reply_provider for c in case_calls if c.reply_provider is not None})
                ),
                documents=document_lines(p.docket, case_calls, hashes.documents),
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


def document_lines(
    docket: Docket, calls: Sequence[AgentCall], hashes: Mapping[int, str] | None = None
) -> tuple[DocumentLine, ...]:
    """Each document's status, what the agent decided (read, skipped, never on offer), its hash."""
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
            sha256=(hashes or {}).get(d.entry.index),
            pages=d.pages,
        )
        for d in docket.documents
    )
