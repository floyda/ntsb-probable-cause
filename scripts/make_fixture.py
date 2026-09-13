"""Create redacted development-split fixtures from this repository's raw data (decision 0015).

Usage:
    uv run python -m scripts.make_fixture records <ntsb_number> [<ntsb_number> ...]
    uv run python -m scripts.make_fixture auto
    uv run python -m scripts.make_fixture api <YYYY-MM> [--records 3]
"""

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from pathlib import Path

from ntsb_probable_cause.data.ingest import (
    ManifestEntry,
    iter_raw_records,
    latest_entries,
    month_dir,
    read_manifest,
)
from ntsb_probable_cause.data.redaction import REDACTED_FIELDS, redact_record
from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.paths import resolve_path
from ntsb_probable_cause.splits import COMPLETED_STATUS, GA_REGULATION, Split, split_of

RAW = Path("data/raw")
RECORDS = Path("tests/fixtures/records")
API = Path("tests/fixtures/api")
SOURCE = "GetCasesByDateRangeV2"
_MIN_SEVERAL = 2
_MIN_MAKE_LEN = 3

Record = Mapping[str, object]


def _event_date(record: Record) -> date:
    return date.fromisoformat(str(record.get("eventDate", ""))[:10])


def _is_dev_month(entry: ManifestEntry) -> bool:
    return split_of(date.fromisoformat(entry.start)) is Split.DEV


def _narrative_texts(record: Record) -> list[str]:
    """Every free-text field a builder's name could appear in."""
    texts = [str(record.get("probableCause") or "")]
    narratives = record.get("narratives")
    for narrative in narratives if isinstance(narratives, list) else []:
        if isinstance(narrative, dict):
            texts.append(str(narrative.get("analysisNarrative") or ""))
            texts.append(str(narrative.get("concatenatedFactualNarrative") or ""))
    return texts


def _amateur_built_name_risk(record: Record) -> bool:
    """True if a record's aircraft is amateur-built, or its make names its builder in a narrative.

    An amateur-built aircraft is often registered under its individual builder's name in
    ``aircraftMake`` (decision 0015's redacted-field list does not cover this — flagged for
    Andy). Screening on the flag alone would still miss records where the same name appears in
    a narrative even without the flag set, so both checks apply independently.
    """
    aircrafts = record.get("aircrafts")
    texts: list[str] | None = None
    for aircraft in aircrafts if isinstance(aircrafts, list) else []:
        if not isinstance(aircraft, dict):
            continue
        if aircraft.get("aircraftAmateurBuilt") is True:
            return True
        make = str(aircraft.get("aircraftMake") or "").strip().lower()
        if len(make) < _MIN_MAKE_LEN:
            continue
        if texts is None:
            texts = [t.lower() for t in _narrative_texts(record)]
        if any(make in t for t in texts):
            return True
    return False


def make_record_fixture(record: Record, fetched_at: datetime) -> dict[str, object]:
    """Return the fixture document for one record; refuse anything outside the development split."""
    event = _event_date(record)
    if split_of(event) is not Split.DEV:
        raise FixtureError(
            f"{record.get('ntsbNumber')}: event date {event} is not in the development split"
        )
    return {
        "fixture": {
            "source": SOURCE,
            "fetched_at": fetched_at.isoformat(),
            "redacted_fields": sorted(REDACTED_FIELDS),
        },
        "record": redact_record(record),
    }


def _eligible(record: Record) -> bool:
    return (
        record.get("completionStatus") == COMPLETED_STATUS
        and resolve_path(record, "aircrafts[0].ownerOperators[0].regulationFlightConductedUnder")
        == GA_REGULATION
        and split_of(_event_date(record)) is Split.DEV
        and not _amateur_built_name_risk(record)
    )


def _cls(record: Record) -> str:
    match = re.match(r"^[A-Z]{3}\d{2}([A-Z])", str(record.get("ntsbNumber", "")))
    return match.group(1) if match else ""


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _duplicated(record: Record) -> bool:
    analysis = _norm(resolve_path(record, "narratives[0].analysisNarrative"))
    return bool(analysis) and analysis in _norm(
        resolve_path(record, "narratives[0].concatenatedFactualNarrative")
    )


def _count(record: Record, path: str) -> int:
    value = resolve_path(record, path)
    return len(value) if isinstance(value, list) else 0


CRITERIA: tuple[tuple[str, Callable[[Record], bool]], ...] = (
    (
        "C-class, analysis duplicated in factual narrative",
        lambda r: _cls(r) == "C" and _duplicated(r),
    ),
    ("C-class, not duplicated", lambda r: _cls(r) == "C" and not _duplicated(r)),
    (
        "L-class, several events and findings",
        lambda r: (
            _cls(r) == "L"
            and _count(r, "aircrafts[0].events") >= _MIN_SEVERAL
            and _count(r, "aircrafts[0].findings") >= _MIN_SEVERAL
        ),
    ),
    ("L-class, any", lambda r: _cls(r) == "L"),
    ("F-class", lambda r: _cls(r) == "F"),
    ("F-class, second", lambda r: _cls(r) == "F"),
    ("multi-aircraft", lambda r: _count(r, "aircrafts") > 1),
    ("no METAR", lambda r: resolve_path(r, "weatherConditions[0].metar") is None),
    (
        "no pilot flight-time matrix",
        lambda r: _count(r, "aircrafts[0].crewAndOccupants[0].pilotsFlightTimeMatrix") == 0,
    ),
)


def select(records: Iterable[Record]) -> list[tuple[str, Record]]:
    """Pick the first eligible record, by case number, for each criterion, without repeats."""
    pool = sorted((r for r in records if _eligible(r)), key=lambda r: str(r.get("ntsbNumber")))
    chosen: list[tuple[str, Record]] = []
    used: set[object] = set()
    for name, test in CRITERIA:
        match = next((r for r in pool if r.get("ntsbNumber") not in used and test(r)), None)
        if match is None:
            print(f"no record for criterion: {name}", file=sys.stderr)
            continue
        used.add(match.get("ntsbNumber"))
        chosen.append((name, match))
    return chosen


def _write(record: Record, fetched_at: datetime) -> Path:
    RECORDS.mkdir(parents=True, exist_ok=True)
    path = RECORDS / f"{record['ntsbNumber']}.json"
    path.write_text(
        json.dumps(make_record_fixture(record, fetched_at), indent=2, sort_keys=True) + "\n"
    )
    return path


def main(argv: list[str]) -> int:
    """Run one fixture command."""
    parser = argparse.ArgumentParser(prog="make_fixture")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("records").add_argument("ids", nargs="+")
    commands.add_parser("auto")
    api = commands.add_parser("api")
    api.add_argument("month")
    api.add_argument("--records", type=int, default=3)
    args = parser.parse_args(argv)

    if args.command == "api":
        entry = latest_entries(read_manifest(RAW))[args.month]
        if split_of(date.fromisoformat(entry.start)) is not Split.DEV:
            raise FixtureError(f"{args.month} is not in the development split")
        payload = json.loads((month_dir(RAW, args.month) / entry.pages[0].file).read_bytes())
        screened = [r for r in payload["data"] if not _amateur_built_name_risk(r)]
        payload["data"] = [redact_record(r) for r in screened[: args.records]]
        payload["pageSize"] = len(payload["data"])
        API.mkdir(parents=True, exist_ok=True)
        (API / "page.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {API / 'page.json'} with {payload['pageSize']} records from {args.month}")
        return 0

    # Full corpus present (212 months, 2009-01..2026-08): iter_raw_records' include filter skips
    # held-out and open months before any page file is opened, so they are never read.
    records = {
        str(r.get("ntsbNumber")): (e, r) for e, r in iter_raw_records(RAW, include=_is_dev_month)
    }
    if args.command == "auto":
        for name, record in select(r for _, r in records.values()):
            path = _write(record, records[str(record["ntsbNumber"])][0].fetched_at)
            print(f"{name}: {path}")
        return 0
    for case_id in args.ids:
        if case_id not in records:
            raise FixtureError(f"{case_id}: not found in the development split")
        entry, record = records[case_id]
        print(_write(record, entry.fetched_at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
