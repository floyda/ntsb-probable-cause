"""Later scores: a case coded before the NTSB's codes arrived, scored when they do (0174).

Some cases close before the NTSB has published their codes. Ellery codes them at closure, and the
closure record says ``scored=False``. Each night the record is fetched again; once it holds
occurrence codes, :func:`score_later` grades the answer the case was coded with, through the same
split and the same scoring code as a case scored at coding (``live/closure.py``,
``agent/run.py``). A score, once written, stands: verdict revisions are not followed.

Pure: nothing here does I/O beyond reading the run folders it is given.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, date
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.live.closure import CASES_FILE
from ntsb_probable_cause.live.records import CLOSURES_FILE, ClosureRecord, read_closure_records
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import score_case
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.scoring.samples import load_seen_pairs

SCORES_FORMAT: Final = "live-score/1"
AWAIT_ALERT_NIGHTS: Final = 7
# The evidence Ellery version 1 was shown (``live/morning.py``): the split runs with the same
# exclusion so a later score and a score at coding see the same record.
_EXCLUSIONS: Final = frozenset({EvidenceRole.PRELIM_NARRATIVE})


class LaterScore(BaseModel, frozen=True):
    """One case scored after the fact: the NTSB's codes, the grades and the record's hash."""

    format: Literal["live-score/1"] = SCORES_FORMAT
    case_id: str
    scored_on: date
    record_sha256: str  # sha256 of json.dumps(raw, sort_keys=True): which verdict this is
    verdict_occurrence: tuple[str, ...]
    verdict_findings: tuple[str, ...]
    verdict_findings_in_cause: tuple[str, ...]  # the findings the NTSB flagged as in the cause
    ntsb_cause: str | None
    top1: bool
    top3: bool
    abstained: bool
    finding_precision_10: float | None
    finding_recall_10: float | None


@dataclass(frozen=True)
class Awaiting:
    """A coded case still waiting for the NTSB's codes."""

    case_id: str
    mkey: int
    event_date: date
    closed_on: date
    coded_on: date
    answer: Hypothesis  # the case's final step's hypothesis


def _coded_on(record: ClosureRecord) -> date:
    """The UTC day the case's last model reply came back; the closure day if none is recorded."""
    when = record.last_returned or record.first_sent
    return when.astimezone(UTC).date() if when is not None else record.closed_on


def awaiting(runs: Sequence[Path], scored: Set[str]) -> list[Awaiting]:
    """Coded cases whose closure record is unscored and that no later score covers.

    ``runs`` are live run folders. A folder without a closures file is skipped. Version 1
    records (S3.3's runs) carry no event date, which a later score's board row needs, so they are
    skipped; so is a coded case whose result holds no step (it has no answer to grade). A case
    appearing in several folders counts once, from the earliest folder given.
    """
    found: dict[str, Awaiting] = {}
    for folder in runs:
        closures = folder / CLOSURES_FILE
        cases = folder / CASES_FILE
        if not closures.is_file() or not cases.is_file():
            continue
        results: dict[str, CaseResult] | None = None
        for record in read_closure_records(closures):
            if (
                not isinstance(record, ClosureRecord)
                or record.outcome != "coded"
                or record.scored
                or record.case_id in scored
                or record.case_id in found
            ):
                continue
            if results is None:
                results = {r.case_id: r for r in read_jsonl(cases, CaseResult)}
            result = results.get(record.case_id)
            if result is None or not result.steps:
                continue
            found[record.case_id] = Awaiting(
                case_id=record.case_id,
                mkey=record.mkey,
                event_date=record.event_date,
                closed_on=record.closed_on,
                coded_on=_coded_on(record),
                answer=result.steps[-1].hypothesis,
            )
    return list(found.values())


def record_sha256(raw: Mapping[str, object]) -> str:
    """SHA-256 (hex) of ``json.dumps(raw, sort_keys=True)``."""
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()


def score_later(raw: Mapping[str, object], case: Awaiting, today: date) -> LaterScore | None:
    """Score ``case`` against ``raw``'s verdict through ``split_record`` and ``score_case``.

    Returns None while the record has no occurrence codes. Raises ``LeakageError`` if the
    guard refuses the record, as it would at coding.
    """
    _, _, verdict = split_record(raw, exclude=_EXCLUSIONS)
    if not verdict.occurrence_codes:
        return None
    scores = score_case(case.answer, verdict, load_tables(), seen_pairs=load_seen_pairs())
    return LaterScore(
        case_id=case.case_id,
        scored_on=today,
        record_sha256=record_sha256(raw),
        verdict_occurrence=verdict.occurrence_codes,
        verdict_findings=verdict.finding_codes,
        verdict_findings_in_cause=verdict.finding_codes_in_cause,
        ntsb_cause=verdict.probable_cause,
        top1=scores.occurrence_top1,
        top3=scores.occurrence_top3,
        abstained=scores.abstained,
        finding_precision_10=scores.finding_precision_10,
        finding_recall_10=scores.finding_recall_10,
    )


def overdue(cases: Sequence[Awaiting], today: date) -> int:
    """How many have waited ``AWAIT_ALERT_NIGHTS`` nights or more since coding."""
    return sum(1 for c in cases if (today - c.coded_on).days >= AWAIT_ALERT_NIGHTS)
