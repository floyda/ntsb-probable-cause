"""Raw store: one directory of verbatim pages per event month, and a hashed manifest."""

import calendar
import hashlib
import logging
import re
import shutil
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.data.api import Page
from ntsb_probable_cause.errors import ManifestError

_log = logging.getLogger(__name__)
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_DECEMBER = 12


@dataclass(frozen=True, order=True)
class Month:
    """A calendar month; the unit of fetching (GetCasesByDateRangeV2 filters on event date)."""

    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> Month:
        """Parse ``YYYY-MM``."""
        match = _MONTH.match(text)
        if match is None:
            raise ValueError(f"expected YYYY-MM, got {text!r}")
        return cls(int(match.group(1)), int(match.group(2)))

    @property
    def label(self) -> str:
        """``YYYY-MM``."""
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def start(self) -> date:
        """First day of the month."""
        return date(self.year, self.month, 1)

    @property
    def end(self) -> date:
        """Last day of the month."""
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    def next(self) -> Month:
        """The following month."""
        if self.month == _DECEMBER:
            return Month(self.year + 1, 1)
        return Month(self.year, self.month + 1)


def months_between(first: str, last: str) -> list[Month]:
    """Every month from ``first`` to ``last`` inclusive."""
    current, final = Month.parse(first), Month.parse(last)
    months: list[Month] = []
    while current <= final:
        months.append(current)
        current = current.next()
    return months


class CasesSource(Protocol):
    """Anything that yields case pages for an event-date range."""

    def cases_by_date_range(self, start: date, end: date) -> Iterable[Page]:
        """Yield pages for [start, end]."""
        ...


class PageRecord(BaseModel):
    """One saved page file."""

    model_config = ConfigDict(frozen=True)
    file: str
    sha256: str
    records: int


class ManifestEntry(BaseModel):
    """One completed month fetch. The latest entry per month is authoritative."""

    model_config = ConfigDict(frozen=True)
    month: str
    start: str
    end: str
    endpoint: str
    fetched_at: datetime
    pages: tuple[PageRecord, ...]
    records: int


def manifest_path(raw_dir: Path) -> Path:
    """Location of the manifest."""
    return raw_dir / "v2" / "manifest.jsonl"


def month_dir(raw_dir: Path, month: str) -> Path:
    """Directory holding one month's pages."""
    return raw_dir / "v2" / month


def read_manifest(raw_dir: Path) -> list[ManifestEntry]:
    """Every manifest line, in file order."""
    path = manifest_path(raw_dir)
    if not path.exists():
        return []
    return [
        ManifestEntry.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def latest_entries(entries: Iterable[ManifestEntry]) -> dict[str, ManifestEntry]:
    """The most recent entry for each month."""
    latest: dict[str, ManifestEntry] = {}
    for entry in entries:
        if entry.month not in latest or entry.fetched_at > latest[entry.month].fetched_at:
            latest[entry.month] = entry
    return latest


def verify_entry(raw_dir: Path, entry: ManifestEntry) -> None:
    """Raise ManifestError unless every page file exists and matches its recorded hash."""
    for page in entry.pages:
        path = month_dir(raw_dir, entry.month) / page.file
        if not path.is_file():
            raise ManifestError(f"{entry.month}: missing {page.file}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != page.sha256:
            raise ManifestError(f"{entry.month}: sha256 mismatch for {page.file}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _fetch_month(
    source: CasesSource, month: Month, raw_dir: Path, now: Callable[[], datetime]
) -> ManifestEntry:
    final = month_dir(raw_dir, month.label)
    partial = final.with_name(f"{month.label}.partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    pages: list[PageRecord] = []
    for page in source.cases_by_date_range(month.start, month.end):
        name = f"page-{page.number:02d}.json"
        (partial / name).write_bytes(page.content)
        pages.append(
            PageRecord(
                file=name,
                sha256=hashlib.sha256(page.content).hexdigest(),
                records=len(page.records),
            )
        )
    shutil.rmtree(final, ignore_errors=True)
    partial.rename(final)
    entry = ManifestEntry(
        month=month.label,
        start=month.start.isoformat(),
        end=month.end.isoformat(),
        endpoint=sources.CASES_BY_DATE_RANGE_V2,
        fetched_at=now(),
        pages=tuple(pages),
        records=sum(p.records for p in pages),
    )
    with manifest_path(raw_dir).open("a") as handle:
        handle.write(entry.model_dump_json() + "\n")
    return entry


def fetch_months(
    source: CasesSource,
    months: Sequence[Month],
    raw_dir: Path,
    *,
    refresh: bool = False,
    now: Callable[[], datetime] = _utc_now,
) -> list[ManifestEntry]:
    """Fetch each month not already in the manifest (or every month if ``refresh``)."""
    done = set() if refresh else set(latest_entries(read_manifest(raw_dir)))
    written: list[ManifestEntry] = []
    for month in months:
        if month.label in done:
            continue
        entry = _fetch_month(source, month, raw_dir, now)
        _log.info(
            "fetched %s: %d records in %d pages", entry.month, entry.records, len(entry.pages)
        )
        written.append(entry)
    return written
