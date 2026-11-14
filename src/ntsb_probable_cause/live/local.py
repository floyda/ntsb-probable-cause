"""The seams' local versions: a store pulled to a work file, and live runs in a runs folder.

A run folder is a *live* run when its ``run.jsonl``'s first record has ``sample == "live"``;
a folder with no ``run.jsonl`` yet (a run killed before it finished) is one when its
``spec.json`` says so. The folder name is never the test.
S4's bucket mirror (``live/cloud.py``) uploads run folders; this module never uploads the store.
"""

import json
import shutil
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final

from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    Backfill,
    ClosureRecord,
    write_manifest,
)
from ntsb_probable_cause.live.seams import MonthSpend
from ntsb_probable_cause.live.state import NightState
from ntsb_probable_cause.scoring.budget import spent_usd
from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl
from ntsb_probable_cause.store import Store
from ntsb_probable_cause.store.sync import Location, S3Like, pull

LIVE_SAMPLE: Final = "live"
STORE_WORK_FILENAME: Final = "live-store.sqlite"
STATE_FILE: Final = "live-state.json"
LOCAL_LIMIT_USD: Final = 10.0  # the live key's monthly limit (decision 0170), as the Mac sees it

_RUN_FILE: Final = "run.jsonl"
_SPEC_FILE: Final = "spec.json"
_CASES_FILE: Final = "cases.jsonl"
_SIDE_SUFFIXES: Final = ("-wal", "-shm")


class S3StoreSource:
    """The recorder's store, pulled to a work file and opened read-only."""

    def __init__(self, location: Location, work_file: Path, *, s3: S3Like | None = None) -> None:
        self._location = location
        self._work_file = work_file
        self._s3 = s3
        self._store: Store | None = None

    def open(self) -> Store:
        """Pull the store to the work file and open it read-only.

        Raises:
            FileNotFoundError: there is no store at the location to open.
        """
        self.discard()
        self._work_file.parent.mkdir(parents=True, exist_ok=True)
        if self._location.is_s3:
            pull(self._location, self._work_file, s3=self._s3)
        elif Path(self._location.raw).is_file():
            shutil.copyfile(self._location.raw, self._work_file)
        if not self._work_file.is_file():
            raise FileNotFoundError(f"no store at {self._location.raw}")
        self._store = Store(self._work_file, readonly=True)
        return self._store

    def discard(self) -> None:
        """Close the store if open and delete the work file and its WAL side files."""
        if self._store is not None:
            self._store.close()
            self._store = None
        self._work_file.unlink(missing_ok=True)
        for suffix in _SIDE_SUFFIXES:
            self._work_file.with_name(self._work_file.name + suffix).unlink(missing_ok=True)


def _first_run_record(folder: Path) -> RunRecord | None:
    path = folder / _RUN_FILE
    if not path.is_file():
        return None
    records = read_jsonl(path, RunRecord)
    return records[0] if records else None


def _is_live(folder: Path) -> bool:
    """Whether ``folder`` is a live run's folder.

    Raises:
        ValueError: a folder with no ``run.jsonl`` has an unreadable ``spec.json``.
    """
    first = _first_run_record(folder)
    if first is not None:
        return first.sample == LIVE_SAMPLE
    spec = folder / _SPEC_FILE
    if not spec.is_file():
        return False
    try:
        loaded = json.loads(spec.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"{spec}: unreadable spec of a possible live run: {error}") from error
    return isinstance(loaded, dict) and loaded.get("sample") == LIVE_SAMPLE


def _live_runs(runs_dir: Path) -> Iterator[Path]:
    if not runs_dir.is_dir():
        return
    for folder in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if _is_live(folder):
            yield folder


def live_run_folders(runs_dir: Path) -> list[Path]:
    """The live run folders under ``runs_dir``, sorted by name (the sink's own recognition)."""
    return list(_live_runs(runs_dir))


class LocalSpend:
    """Live spend, from the run records in a runs folder."""

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def month(self, now: datetime) -> MonthSpend:
        """Spend (decision 0135) of live run records started in the calendar month of ``now``."""
        total = 0.0
        for folder in _live_runs(self._runs_dir):
            path = folder / _RUN_FILE
            if not path.is_file():
                continue
            for record in read_jsonl(path, RunRecord):
                started = record.started
                if record.sample == LIVE_SAMPLE and (started.year, started.month) == (
                    now.year,
                    now.month,
                ):
                    total += spent_usd(record)
        return MonthSpend(used_usd=total, limit_usd=LOCAL_LIMIT_USD)


class LocalFolderSink:
    """Live results, read from and written to run folders under a runs folder."""

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def done_case_ids(self) -> frozenset[str]:
        """Case ids in the ``cases.jsonl`` of every live run."""
        done: set[str] = set()
        for folder in _live_runs(self._runs_dir):
            done.update(_case_ids(folder))
        return frozenset(done)

    def unfinished_run(self) -> str | None:
        """The first live run whose last record is unfinished, or which has no record yet."""
        for folder in _live_runs(self._runs_dir):
            path = folder / _RUN_FILE
            records = read_jsonl(path, RunRecord) if path.is_file() else []
            if not records or records[-1].finished is None:
                return folder.name
        return None

    def backfill(self) -> Backfill | None:
        """The backfill of the first live run that holds one."""
        for folder in _live_runs(self._runs_dir):
            path = folder / BACKFILL_FILE
            if path.is_file():
                return Backfill.model_validate_json(path.read_text())
        return None

    def write(
        self, run_id: str, records: Sequence[ClosureRecord], backfill: Backfill | None
    ) -> None:
        """Write ``closures.jsonl``, ``backfill.json`` when given, then the manifest."""
        folder = self._runs_dir / run_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / CLOSURES_FILE).write_text("".join(r.model_dump_json() + "\n" for r in records))
        if backfill is not None:
            (folder / BACKFILL_FILE).write_text(backfill.model_dump_json() + "\n")
        write_manifest(folder)

    def night_state(self) -> NightState:
        """The state in ``live-state.json``; an empty one when the file is not there."""
        path = self._runs_dir / STATE_FILE
        if not path.is_file():
            return NightState()
        return NightState.model_validate_json(path.read_text())

    def write_night_state(self, state: NightState) -> None:
        """Replace ``live-state.json``."""
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        (self._runs_dir / STATE_FILE).write_text(state.model_dump_json() + "\n")


def _case_ids(folder: Path) -> list[str]:
    path = folder / _CASES_FILE
    if not path.is_file():
        return []
    ids: list[str] = []
    for line in path.read_text().splitlines():
        if line:
            case_id = json.loads(line).get("case_id")
            if isinstance(case_id, str):
                ids.append(case_id)
    return ids
