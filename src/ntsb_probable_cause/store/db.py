"""``Store``: the only class that touches SQLite (spec S2.5, Task 4).

Every write is one parameterised statement inside :meth:`Store.transaction`; there is no
string-formatted SQL anywhere in this module. Reads go straight through ``self._conn`` since
SQLite serialises them against any open transaction.
"""

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Self

from ntsb_probable_cause.store import schema
from ntsb_probable_cause.store.models import (
    CaseRow,
    DocumentRow,
    FeedRow,
    RunSummary,
    RunSummaryRow,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require_plain_date(today: str) -> None:
    """Raise ``ValueError`` unless ``today`` is exactly ``YYYY-MM-DD``.

    ``watched_mkeys`` and ``earliest_watched_event_month`` compare ``today`` against
    ``watch_until`` and ``event_date`` as plain strings. A timestamp such as
    ``"2026-10-30T03:00:00+00:00"`` sorts *before* the plain date ``"2026-10-30"`` (``"T"`` <
    nothing), so passing one in would silently drop a case on its last watched day instead of
    raising -- this check makes that a loud error at the call site instead.
    """
    if not _DATE_RE.match(today):
        raise ValueError(f"today must be exactly 'YYYY-MM-DD', got {today!r}")
    try:
        date.fromisoformat(today)
    except ValueError as error:
        raise ValueError(f"today must be exactly 'YYYY-MM-DD', got {today!r}") from error


class Store:
    """The recorder's SQLite store: one file, opened in WAL mode with foreign keys on."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._txn_depth = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """The underlying connection, read-only use: tests and the report script."""
        return self._conn

    def close(self) -> None:
        """Roll back any open transaction, checkpoint the write-ahead log, then close.

        Without the checkpoint, recent writes can sit in a separate ``-wal`` file: reading the
        ``.sqlite`` path alone (the store boundary test, and Task 10's upload to S3) would then
        miss them. A transaction left open by a caller who did not go through
        :meth:`transaction` (or by a bug) makes the checkpoint fail with "database table is
        locked", which would otherwise mask whatever the real problem was -- so it is rolled
        back first, and the connection is closed in a ``finally`` so a failed checkpoint never
        leaves the file handle open.
        """
        try:
            if self._conn.in_transaction:
                self._conn.rollback()
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.commit()
        finally:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on a clean exit, roll back on any exception, re-entrantly.

        Catches ``BaseException``, not just ``Exception``, so a ``KeyboardInterrupt`` mid-write
        still rolls back. Re-entrant: a call nested inside an outer ``with
        self.transaction():`` (for example one write method calling another, or a caller
        grouping several writes so "a half-written night cannot exist") shares the same
        underlying SQLite transaction. Only the outermost level commits or rolls back; an
        inner level's exit does neither.
        """
        self._txn_depth += 1
        try:
            yield self._conn
        except BaseException:
            self._txn_depth -= 1
            if self._txn_depth == 0:
                self._conn.rollback()
            raise
        else:
            self._txn_depth -= 1
            if self._txn_depth == 0:
                self._conn.commit()

    def _current_version(self) -> int:
        has_table = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if has_table is None:
            return 0
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        return int(row[0]) if row is not None else 0

    def migrate(self) -> int:
        """Apply every migration after the current version, in order. Idempotent.

        Each migration's DDL and its version-row write run as one atomic unit.
        ``executescript`` always commits any already-open transaction before it runs, and then
        runs the statements in the script text itself in autocommit mode unless that text
        opens its own transaction -- so the DDL and the version write are wrapped in a
        literal ``BEGIN``/``COMMIT`` inside the same script, and a failure partway through is
        rolled back explicitly. Without this, a failure after (say) ``CREATE TABLE
        schema_version`` but before its row is written leaves a store that a later `migrate()`
        cannot repair: it would see version 0 (no row) and try to create ``schema_version``
        again, failing with "table schema_version already exists".

        ``i`` is this loop's own 1-based migration index, an internal `int`, not external
        input, so building the version-write statement with an f-string carries no injection
        risk; ``executescript`` has no placeholder syntax to parameterise it with regardless.
        """
        version = self._current_version()
        for i, migration_script in enumerate(schema.MIGRATIONS[version:], start=version + 1):
            version_write = (
                f"INSERT INTO schema_version (version) VALUES ({i});"  # noqa: S608
                if version == 0
                else f"UPDATE schema_version SET version = {i};"  # noqa: S608
            )
            try:
                self._conn.executescript(f"BEGIN;\n{migration_script}\n{version_write}\nCOMMIT;")
            except Exception:
                self._conn.rollback()
                raise
            version = i
        return version

    # -- runs --------------------------------------------------------------------------------

    def begin_run(self, *, started_at: str, commit_sha: str, dirty: bool) -> int:
        """Insert a new run row and return its ``run_id``."""
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO runs (started_at, commit_sha, dirty) VALUES (?, ?, ?)",
                (started_at, commit_sha, int(dirty)),
            )
            run_id = cursor.lastrowid
        if run_id is None:  # pragma: no cover -- sqlite always assigns one on INSERT.
            raise RuntimeError("insert into runs did not assign a rowid")
        return run_id

    def finish_run(self, run_id: int, *, finished_at: str, summary: RunSummary) -> None:
        """Record a run's finish time and summary counts."""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, cases_polled=?, cases_changed=?, "
                "new_documents=?, failures=?, suspected_renumbers=?, minutes=? WHERE run_id=?",
                (
                    finished_at,
                    summary.cases_polled,
                    summary.cases_changed,
                    summary.new_documents,
                    summary.failures,
                    summary.suspected_renumbers,
                    summary.minutes,
                    run_id,
                ),
            )

    def last_run_id(self) -> int | None:
        """The highest ``run_id``, or ``None`` if no run has ever started."""
        row = self._conn.execute("SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
        return int(row[0]) if row is not None else None

    def run_summaries(self) -> list[RunSummaryRow]:
        """Every run, most recent first (Task 11 adds more report queries)."""
        rows = self._conn.execute(
            "SELECT run_id, started_at, finished_at, commit_sha, dirty, cases_polled, "
            "cases_changed, new_documents, failures, suspected_renumbers, minutes "
            "FROM runs ORDER BY run_id DESC"
        ).fetchall()
        return [
            RunSummaryRow(
                run_id=row[0],
                started_at=row[1],
                finished_at=row[2],
                commit_sha=row[3],
                dirty=bool(row[4]),
                cases_polled=row[5],
                cases_changed=row[6],
                new_documents=row[7],
                failures=row[8],
                suspected_renumbers=row[9],
                minutes=row[10],
            )
            for row in rows
        ]

    # -- cases ---------------------------------------------------------------------------------

    def get_case(self, mkey: int) -> CaseRow | None:
        """The case's latest known state, or ``None`` if it has never been seen."""
        row = self._conn.execute(
            "SELECT mkey, ntsb_number, event_date, regulation, status, first_seen_run, "
            "last_seen_run, last_case_run, last_docket_run, watch_until, watched "
            "FROM cases WHERE mkey=?",
            (mkey,),
        ).fetchone()
        if row is None:
            return None
        return CaseRow(
            mkey=row[0],
            ntsb_number=row[1],
            event_date=row[2],
            regulation=row[3],
            status=row[4],
            first_seen_run=row[5],
            last_seen_run=row[6],
            last_case_run=row[7],
            last_docket_run=row[8],
            watch_until=row[9],
            watched=bool(row[10]),
        )

    def upsert_case(self, row: CaseRow) -> None:
        """Insert a case, or replace its row entirely if ``row.mkey`` is already known."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO cases (mkey, ntsb_number, event_date, regulation, status, "
                "first_seen_run, last_seen_run, last_case_run, last_docket_run, watch_until, "
                "watched) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(mkey) DO UPDATE SET "
                "ntsb_number=excluded.ntsb_number, event_date=excluded.event_date, "
                "regulation=excluded.regulation, status=excluded.status, "
                "first_seen_run=excluded.first_seen_run, last_seen_run=excluded.last_seen_run, "
                "last_case_run=excluded.last_case_run, "
                "last_docket_run=excluded.last_docket_run, watch_until=excluded.watch_until, "
                "watched=excluded.watched",
                (
                    row.mkey,
                    row.ntsb_number,
                    row.event_date,
                    row.regulation,
                    row.status,
                    row.first_seen_run,
                    row.last_seen_run,
                    row.last_case_run,
                    row.last_docket_run,
                    row.watch_until,
                    int(row.watched),
                ),
            )

    def set_last_docket_run(self, mkey: int, run_id: int) -> None:
        """Update only a case's ``last_docket_run`` column (Task 8 fix round 1, Minor 1).

        Unlike :meth:`upsert_case`, which replaces the whole row, this never risks writing back
        a stale copy of the other columns: the docket side (``recorder/dockets.py``) reads a
        case row before its network fetch, and a full ``upsert_case`` of that stale copy could
        silently clobber a case-side field the case side (``recorder/cases.py``) wrote to the
        same row in the meantime.
        """
        with self.transaction() as conn:
            conn.execute("UPDATE cases SET last_docket_run=? WHERE mkey=?", (run_id, mkey))

    def watched_mkeys(self, *, today: str) -> list[int]:
        """Every case still watched: status ``Ongoing``, or within its ``watch_until`` tail.

        A case whose ``watched`` column is 0 -- its regulation is no longer Part 91 or empty
        (decision 0064) -- is excluded even if its status or tail would otherwise qualify.

        Raises:
            ValueError: ``today`` is not exactly ``YYYY-MM-DD``.
        """
        _require_plain_date(today)
        rows = self._conn.execute(
            "SELECT mkey FROM cases "
            "WHERE (status='Ongoing' OR (watch_until IS NOT NULL AND watch_until >= ?)) "
            "AND watched = 1 "
            "ORDER BY mkey",
            (today,),
        ).fetchall()
        return [int(row[0]) for row in rows]

    def earliest_watched_event_month(self, *, today: str) -> str | None:
        """The earliest ``YYYY-MM`` event month among watched cases, or ``None`` if none.

        See :meth:`watched_mkeys` for the ``watched`` column's role in the predicate.

        Raises:
            ValueError: ``today`` is not exactly ``YYYY-MM-DD``.
        """
        _require_plain_date(today)
        row = self._conn.execute(
            "SELECT MIN(substr(event_date, 1, 7)) FROM cases "
            "WHERE (status='Ongoing' OR (watch_until IS NOT NULL AND watch_until >= ?)) "
            "AND watched = 1",
            (today,),
        ).fetchone()
        return row[0] if row is not None else None

    def add_status_event(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        mkey: int,
        *,
        old: str | None,
        new: str,
        absent_run: int | None,
        present_run: int,
        run_id: int,
    ) -> None:
        """Record a case's status change, between the run it was last absent from and this one."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO status_events "
                "(mkey, old_status, new_status, absent_run, present_run, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mkey, old, new, absent_run, present_run, run_id),
            )

    # -- evidence field snapshots and the preliminary narrative ---------------------------------

    def latest_snapshots(self, mkey: int) -> dict[str, str]:
        """The newest value per role, as JSON text, for a case."""
        rows = self._conn.execute(
            "SELECT role, value_json FROM field_snapshots WHERE mkey=? ORDER BY id", (mkey,)
        ).fetchall()
        return dict(rows)

    def add_field_snapshot(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        mkey: int,
        *,
        role: str,
        value_json: str,
        absent_run: int | None,
        present_run: int,
        run_id: int,
    ) -> None:
        """Record one evidence field's value as it appeared as of a run."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO field_snapshots "
                "(mkey, role, value_json, absent_run, present_run, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mkey, role, value_json, absent_run, present_run, run_id),
            )

    def latest_prelim(self, mkey: int) -> str | None:
        """The most recently recorded preliminary narrative text, or ``None``."""
        row = self._conn.execute(
            "SELECT text FROM prelim_narratives WHERE mkey=? ORDER BY id DESC LIMIT 1", (mkey,)
        ).fetchone()
        return row[0] if row is not None else None

    def add_prelim(
        self,
        mkey: int,
        *,
        text: str,
        absent_run: int | None,
        present_run: int,
        run_id: int,
    ) -> None:
        """Record the preliminary narrative's text as it read as of a run."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO prelim_narratives (mkey, text, absent_run, present_run, run_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (mkey, text, absent_run, present_run, run_id),
            )

    # -- dockets ---------------------------------------------------------------------------------

    def add_docket_poll(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        mkey: int,
        *,
        run_id: int,
        outcome: str,
        reason: str | None,
        declared_items: int | None,
        creation_date: str | None,
        last_modified: str | None,
        release_date: str | None,
        page_sha: str | None,
    ) -> None:
        """Record one poll of a case's docket listing page."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO docket_polls "
                "(mkey, run_id, outcome, reason, declared_items, creation_date, "
                "last_modified, release_date, page_sha) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mkey,
                    run_id,
                    outcome,
                    reason,
                    declared_items,
                    creation_date,
                    last_modified,
                    release_date,
                    page_sha,
                ),
            )

    def has_page(self, page_sha: str) -> bool:
        """Whether a listing page with this hash has already been stored."""
        row = self._conn.execute(
            "SELECT 1 FROM listing_pages WHERE page_sha=?", (page_sha,)
        ).fetchone()
        return row is not None

    def add_page(self, *, page_sha: str, mkey: int, gz: bytes, run_id: int) -> None:
        """Store a listing page's compressed bytes, keyed by its hash (0063).

        Raises:
            sqlite3.IntegrityError: ``page_sha`` is already stored (it is the primary key).
                Callers must check :meth:`has_page` first.
        """
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO listing_pages (page_sha, mkey, gz, first_run) VALUES (?, ?, ?, ?)",
                (page_sha, mkey, gz, run_id),
            )

    def documents_for(self, mkey: int) -> dict[int, DocumentRow]:
        """Every document ever seen for a case, present or gone, keyed by ``doc_id``."""
        rows = self._conn.execute(
            "SELECT mkey, doc_id, href, position, title, pages, photos, extension, "
            "absent_run, present_run, last_present_run, gone_absent_run, gone_present_run "
            "FROM documents WHERE mkey=?",
            (mkey,),
        ).fetchall()
        return {
            row[1]: DocumentRow(
                mkey=row[0],
                doc_id=row[1],
                href=row[2],
                position=row[3],
                title=row[4],
                pages=row[5],
                photos=row[6],
                extension=row[7],
                absent_run=row[8],
                present_run=row[9],
                last_present_run=row[10],
                gone_absent_run=row[11],
                gone_present_run=row[12],
            )
            for row in rows
        }

    def upsert_document(self, row: DocumentRow) -> None:
        """Insert a document, or replace its row entirely if ``(mkey, doc_id)`` is known."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO documents "
                "(mkey, doc_id, href, position, title, pages, photos, extension, "
                "absent_run, present_run, last_present_run, gone_absent_run, gone_present_run) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(mkey, doc_id) DO UPDATE SET "
                "href=excluded.href, position=excluded.position, title=excluded.title, "
                "pages=excluded.pages, photos=excluded.photos, extension=excluded.extension, "
                "absent_run=excluded.absent_run, present_run=excluded.present_run, "
                "last_present_run=excluded.last_present_run, "
                "gone_absent_run=excluded.gone_absent_run, "
                "gone_present_run=excluded.gone_present_run",
                (
                    row.mkey,
                    row.doc_id,
                    row.href,
                    row.position,
                    row.title,
                    row.pages,
                    row.photos,
                    row.extension,
                    row.absent_run,
                    row.present_run,
                    row.last_present_run,
                    row.gone_absent_run,
                    row.gone_present_run,
                ),
            )

    def add_document_event(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        mkey: int,
        *,
        doc_id: int,
        kind: str,
        absent_run: int | None,
        present_run: int,
        run_id: int,
        old: dict[str, object] | None,
        new: dict[str, object] | None,
    ) -> None:
        """Record a document appearing, being revised, or disappearing.

        ``kind`` must be one of ``'appeared'``, ``'revised'`` or ``'disappeared'``; the
        ``document_events`` table's ``CHECK`` constraint rejects anything else.
        """
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO document_events "
                "(mkey, doc_id, kind, absent_run, present_run, run_id, old_json, new_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mkey,
                    doc_id,
                    kind,
                    absent_run,
                    present_run,
                    run_id,
                    json.dumps(old) if old is not None else None,
                    json.dumps(new) if new is not None else None,
                ),
            )

    # -- the API change feed ----------------------------------------------------------------

    def add_feed_rows(self, rows: Iterable[FeedRow], *, run_id: int) -> None:
        """Record a batch of change-feed entries against this run."""
        with self.transaction() as conn:
            conn.executemany(
                "INSERT INTO change_feed "
                "(mkey, last_change_utc, step_number, step_id, case_closed, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        row.mkey,
                        row.last_change_utc,
                        row.step_number,
                        row.step_id,
                        int(row.case_closed),
                        run_id,
                    )
                    for row in rows
                ],
            )
