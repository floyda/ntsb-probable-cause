"""Build the processed file: index columns plus the raw record (decision 0014)."""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ntsb_probable_cause.data.ingest import iter_raw_records, manifest_path
from ntsb_probable_cause.paths import resolve_path
from ntsb_probable_cause.sources import docket_url
from ntsb_probable_cause.splits import COMPLETED_STATUS, GA_REGULATION, MIN_EVENT_YEAR, split_of

SCHEMA = pa.schema(
    [
        ("ntsb_number", pa.string()),
        ("mkey", pa.int64()),
        ("event_date", pa.date32()),
        ("split", pa.string()),
        ("completion_status", pa.string()),
        ("investigation_class", pa.string()),
        ("report_flavour", pa.string()),
        ("aircraft_count", pa.int32()),
        ("docket_url", pa.string()),
        ("raw_json", pa.string()),
    ]
)

# ../ntsb-spike/docs/build-brief.md §6, from the spike's volume.py over its filtered closed GA set.
SPIKE_SPLIT_COUNTS: Mapping[str, int] = {"dev": 13560, "heldout": 4241}

_CLASS = re.compile(r"^[A-Z]{3}\d{2}([A-Z])")


@dataclass(frozen=True)
class BuildResult:
    """What one build wrote and why rows were left out."""

    rows: int
    duplicates_replaced: int
    duplicates_seen: int
    excluded: Mapping[str, int]
    counts_by_split: Mapping[str, int]
    counts_by_class: Mapping[str, int]
    manifest_sha256: str


def investigation_class(ntsb_number: str) -> str | None:
    """The investigation-class letter: the sixth character of the case number."""
    match = _CLASS.match(ntsb_number)
    return match.group(1) if match else None


def _exclusion(record: Mapping[str, object]) -> str | None:
    try:
        event = date.fromisoformat(str(record.get("eventDate"))[:10])
    except ValueError:
        return "no event date"
    if record.get("completionStatus") != COMPLETED_STATUS:
        return "not completed"
    if (
        resolve_path(record, "aircrafts[0].ownerOperators[0].regulationFlightConductedUnder")
        != GA_REGULATION
    ):
        return "not part 91"
    if event.year < MIN_EVENT_YEAR:
        return "before 2009"
    return None


def _row(record: Mapping[str, object]) -> dict[str, object]:
    number = str(record["ntsbNumber"])
    event = date.fromisoformat(str(record["eventDate"])[:10])
    mkey = record.get("mKey")
    aircrafts = record.get("aircrafts")
    flavour = record.get("factualFinalReportFlavor")
    return {
        "ntsb_number": number,
        "mkey": mkey if isinstance(mkey, int) else None,
        "event_date": event,
        "split": split_of(event).value,
        "completion_status": str(record.get("completionStatus")),
        "investigation_class": investigation_class(number),
        "report_flavour": flavour if isinstance(flavour, str) else None,
        "aircraft_count": len(aircrafts) if isinstance(aircrafts, list) else 0,
        "docket_url": docket_url(mkey) if isinstance(mkey, int) else None,
        "raw_json": json.dumps(record, ensure_ascii=False, sort_keys=True),
    }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_processed(
    raw_dir: Path, processed_dir: Path, *, now: Callable[[], datetime] = _utc_now
) -> BuildResult:
    """Verify the raw store, keep the newest copy of each case, filter, and write the file."""
    newest: dict[str, tuple[datetime, dict[str, object]]] = {}
    seen = 0
    replaced = 0
    for entry, record in iter_raw_records(raw_dir):
        number = record.get("ntsbNumber")
        if not isinstance(number, str):
            continue
        if number in newest:
            seen += 1
            if entry.fetched_at <= newest[number][0]:
                continue
            replaced += 1
        newest[number] = (entry.fetched_at, record)

    excluded: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    for number in sorted(newest):
        record = newest[number][1]
        reason = _exclusion(record)
        if reason:
            excluded[reason] += 1
        else:
            rows.append(_row(record))

    processed_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=SCHEMA),
        processed_dir / "cases.parquet",
        compression="zstd",
    )
    result = BuildResult(
        rows=len(rows),
        duplicates_replaced=replaced,
        duplicates_seen=seen,
        excluded=dict(excluded),
        counts_by_split=dict(sorted(Counter(str(r["split"]) for r in rows).items())),
        counts_by_class=dict(sorted(Counter(str(r["investigation_class"]) for r in rows).items())),
        manifest_sha256=hashlib.sha256(manifest_path(raw_dir).read_bytes()).hexdigest(),
    )
    meta = {
        **asdict(result),
        "built_at": now().isoformat(),
        "filters": {
            "completion_status": COMPLETED_STATUS,
            "regulation": GA_REGULATION,
            "min_event_year": MIN_EVENT_YEAR,
        },
    }
    (processed_dir / "cases.meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n"
    )
    return result
