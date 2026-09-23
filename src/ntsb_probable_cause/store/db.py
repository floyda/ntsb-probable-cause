"""``Store``: the only class that touches SQLite (spec S2.5, Task 4).

Every write is one parameterised statement inside :meth:`Store.transaction`; there is no
string-formatted SQL anywhere in this module. Reads go straight through ``self._conn`` since
SQLite serialises them against any open transaction.
"""

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
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

# Shared by field_change_arrivals and first_sight_field_count (Task 11): the first (smallest
# ``id``) field_snapshots row per (mkey, role) -- the run that first recorded any value for
# that role at all, whether that turns out to be a true arrival or a first-sight observation.
_FIRST_FIELD_SNAPSHOT = (
    "(SELECT mkey, role, MIN(id) AS first_id FROM field_snapshots GROUP BY mkey, role)"
)


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


def _days_between(event_date: str, started_at: str) -> int:
    """Days from ``event_date`` (``YYYY-MM-DD``) to the DATE portion of ``started_at``.

    ``started_at`` is one of ``runs.started_at``'s full ISO-8601 timestamps (spec §3: every
    "when" is a run id, never a bare date); only its date component is used. Task 11 controller
    note 2: this is an upper bound on how long a field took to arrive -- the run that *first*
    recorded the value may have run days after the value actually appeared, if a night was
    missed. The interval's other side (the last run that did *not* see it) is on record too,
    as ``absent_run``, but this report states only the present-side day count.
    """
    run_date = datetime.fromisoformat(started_at).date()
    return (run_date - date.fromisoformat(event_date)).days


def _parse_feed_timestamp(text: str) -> datetime | None:
    """Parse a change-feed ``last_change_utc`` value; ``None`` if it does not parse.

    Tolerates a trailing ``Z`` (``datetime.fromisoformat`` before Python 3.11 could not, and
    the feed's own timestamp format has never been confirmed by a live response, so this stays
    defensive rather than assuming one exact shape).
    """
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _feed_reported_change(
    feed_rows: Iterable[tuple[int, str]],
    *,
    absent_run: int | None,
    present_run: int,
    window_days: int,
    run_started_at: Mapping[int, str],
) -> bool:
    """Whether one field change is "reported by the feed" (Task 11 controller note 6).

    One precise rule, with two branches -- either is sufficient:

    (a) some ``change_feed`` row for the same case was recorded at ``present_run`` itself, or
        at any run up to ``window_days`` after it (the feed's own nightly poll caught the
        change the same night the month re-fetch did, or within the next ``window_days``
        nights);
    (b) some row's ``last_change_utc`` -- the NTSB's own real-world change timestamp,
        independent of our nightly polling cadence -- falls between the two runs' start times
        (``absent_run``'s and ``present_run``'s), inclusive. Only checked when the absent side
        is known and both runs' start times are on record; a first-sight row (``absent_run``
        ``None``) is never passed here at all (:meth:`Store.feed_comparison` only queries rows
        with ``absent_run IS NOT NULL``).
    """
    absent_started = (
        _parse_feed_timestamp(run_started_at[absent_run])
        if absent_run is not None and absent_run in run_started_at
        else None
    )
    present_started = (
        _parse_feed_timestamp(run_started_at[present_run])
        if present_run in run_started_at
        else None
    )
    for run_id, last_change_utc in feed_rows:
        if present_run <= run_id <= present_run + window_days:
            return True
        if absent_started is not None and present_started is not None:
            changed_at = _parse_feed_timestamp(last_change_utc)
            if changed_at is not None and absent_started <= changed_at <= present_started:
                return True
    return False


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

    # -- report queries (Task 11; spec S2.5 §10.2) -------------------------------------------
    #
    # Every method here is read-only and returns numbers, never case text -- the report script
    # (scripts/recorder_report.py) is the only caller and it is built to print counts only
    # (decision 0024). "Arrival" methods follow one rule throughout (Task 11 controller note
    # 2): a field or a docket is either a *true arrival* (there is a run that observed its
    # absence before the run that observed its presence -- ``absent_run IS NOT NULL``) or a
    # *first-sight* observation (present already at the very first run that could have seen
    # it, so only a lower bound is known). True arrivals are reported as day counts; first-
    # sight observations are reported separately, as a count, never mixed into the same
    # distribution.

    def field_change_arrivals(self) -> list[tuple[str, int]]:
        """``(role, days from event to first appearance)`` for every true evidence-field arrival.

        Precisely: for each ``(mkey, role)`` pair, take its *first* ``field_snapshots`` row (the
        smallest ``id`` -- ``cases.py``'s ``_apply_fields`` never writes a row for a role while
        it is still unknown, so this is the run that first recorded a value for that role at
        all). Included only when that row's ``absent_run IS NOT NULL`` -- a true arrival, with a
        run that observed the field's absence beforehand. A first-sight row (``absent_run IS
        NULL``) is excluded here; see :meth:`first_sight_field_count`.

        ``days`` is :func:`_days_between` applied to the case's ``event_date`` and the row's
        ``present_run``'s ``runs.started_at`` -- an upper bound (see that function's docstring).
        """
        rows = self._conn.execute(
            # `_FIRST_FIELD_SNAPSHOT` is a fixed module-level constant (see its own comment),
            # not external input; there is no placeholder syntax to parameterise a sub-SELECT
            # with regardless.
            "SELECT fs.role, r.started_at, c.event_date "  # noqa: S608
            "FROM field_snapshots fs "
            f"JOIN {_FIRST_FIELD_SNAPSHOT} fr ON fr.first_id = fs.id "
            "JOIN runs r ON r.run_id = fs.present_run "
            "JOIN cases c ON c.mkey = fs.mkey "
            "WHERE fs.absent_run IS NOT NULL"
        ).fetchall()
        return [
            (str(role), _days_between(event_date, started_at))
            for role, started_at, event_date in rows
        ]

    def first_sight_field_count(self) -> int:
        """How many ``(mkey, role)`` fields were already known at the case's first-ever run.

        These say only "present by the day we started watching" -- a lower bound, never mixed
        into :meth:`field_change_arrivals`'s day counts (Task 11 controller note 2). Precisely:
        the field's first ``field_snapshots`` row has ``absent_run IS NULL`` *and* its
        ``present_run`` equals the case's own ``first_seen_run`` -- the second check is
        belt-and-suspenders, since ``cases.py`` only ever writes ``absent_run=NULL`` on a
        case's first observation, but it keeps this query correct even if that ever changed.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM field_snapshots fs "  # noqa: S608 -- see field_change_arrivals.
            f"JOIN {_FIRST_FIELD_SNAPSHOT} fr ON fr.first_id = fs.id "
            "JOIN cases c ON c.mkey = fs.mkey "
            "WHERE fs.absent_run IS NULL AND fs.present_run = c.first_seen_run"
        ).fetchone()
        return int(row[0])

    def docket_arrivals(self) -> list[tuple[int, int]]:
        """``(days from event to first documented poll, document count at that poll)`` per case.

        Precisely: for each case, its first ``docket_polls`` row with ``outcome='read'`` (a
        page with the "Docket Information" block and at least one entry -- ``outcome='empty'``
        is a page with none, spec §6.2). Excluded when that row is also the case's very first
        poll of *any* outcome -- there is then no earlier poll that observed the docket's
        absence, so it is present-at-first-sight rather than a true arrival; see
        :meth:`docket_first_sight_count`. A case with no ``read`` poll at all contributes
        nothing to either count.
        """
        rows = self._conn.execute(
            "SELECT dp.declared_items, r.started_at, c.event_date "
            "FROM docket_polls dp "
            "JOIN runs r ON r.run_id = dp.run_id "
            "JOIN cases c ON c.mkey = dp.mkey "
            "WHERE dp.outcome = 'read' "
            "  AND dp.run_id = (SELECT MIN(run_id) FROM docket_polls "
            "                    WHERE mkey = dp.mkey AND outcome = 'read') "
            "  AND dp.run_id != (SELECT MIN(run_id) FROM docket_polls WHERE mkey = dp.mkey)"
        ).fetchall()
        return [
            (_days_between(event_date, started_at), int(declared_items or 0))
            for declared_items, started_at, event_date in rows
        ]

    def docket_first_sight_count(self) -> int:
        """How many cases already had a documented docket at their very first poll ever."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM docket_polls dp "
            "WHERE dp.outcome = 'read' "
            "  AND dp.run_id = (SELECT MIN(run_id) FROM docket_polls WHERE mkey = dp.mkey)"
        ).fetchone()
        return int(row[0])

    def feed_comparison(self, window_days: int = 1) -> tuple[int, int]:
        """``(field_changes, reported_by_feed)`` (spec §5.3, §10.2; Task 11 controller note 6).

        ``field_changes`` is every true evidence-field arrival the month re-fetch found (every
        ``field_snapshots`` row with ``absent_run IS NOT NULL`` -- not deduplicated by role,
        since the question is "how many of the changes we wrote did the feed also report", and
        each row is one change). ``reported_by_feed`` is how many of those have at least one
        matching ``change_feed`` row for the same ``mkey``, by :func:`_feed_reported_change`.
        """
        run_started_at = dict(self._conn.execute("SELECT run_id, started_at FROM runs").fetchall())
        changes = self._conn.execute(
            "SELECT mkey, absent_run, present_run FROM field_snapshots WHERE absent_run IS NOT NULL"
        ).fetchall()
        reported = 0
        for mkey, absent_run, present_run in changes:
            feed_rows = self._conn.execute(
                "SELECT run_id, last_change_utc FROM change_feed WHERE mkey = ?", (mkey,)
            ).fetchall()
            if _feed_reported_change(
                feed_rows,
                absent_run=absent_run,
                present_run=present_run,
                window_days=window_days,
                run_started_at=run_started_at,
            ):
                reported += 1
        return len(changes), reported

    def regulation_changes(self) -> int:
        """Watched cases currently excluded from watching by their regulation (spec §4.1).

        The store keeps no history of ``cases.regulation`` -- every observation overwrites the
        one column (``upsert_case``), so a case that changed regulation and later *closed*, or
        that changed away from and back to Part 91 within the store's life, leaves no trace
        this query can see. What is on record: a case whose *current* status is still
        ``'Ongoing'`` and whose ``watched`` flag is ``0`` can only have become unwatched one
        way -- ``recorder.cases.is_watchable`` returning ``False`` while the case is Ongoing,
        which happens precisely when its regulation is recorded as neither Part 91 nor empty
        (``recorder/cases.py``'s ``_apply_status``/``observe_case``: watching a case never
        stops for an Ongoing case for any other reason). So this counts *current*, still-open
        regulation drops -- a lower bound on "how many watched cases changed regulation after
        first seen", not the full historical count the spec's prose describes; a case that both
        changed regulation and closed is undercounted. Recorded as a known limitation, not a
        silent one.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'Ongoing' AND watched = 0"
        ).fetchone()
        return int(row[0])

    def tail_arrivals(self) -> int:
        """Document arrivals recorded after a case's closing status event (spec §7 rule 5).

        For each case, its closing event is the *latest* ``status_events`` row with
        ``old_status = 'Ongoing'`` (the transition ``cases.py``'s ``_apply_status`` sets the
        30-day tail on; a case that reopened and closed again is counted from its most recent
        closing, matching ``watch_until``'s own "only the latest transition matters"
        semantics). A ``document_events`` row of kind ``'appeared'`` for that case counts if its
        ``present_run`` is strictly after the closing event's ``present_run`` -- an event on the
        very same run as the closing one is not counted, since spec §7 rule 4 ("same-poll
        changes carry no order") means the store cannot say whether it arrived before or after
        the status change that same night.
        """
        closings = self._conn.execute(
            "SELECT mkey, MAX(present_run) FROM status_events WHERE old_status = 'Ongoing' "
            "GROUP BY mkey"
        ).fetchall()
        total = 0
        for mkey, present_run in closings:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM document_events "
                "WHERE mkey = ? AND kind = 'appeared' AND present_run > ?",
                (mkey, present_run),
            ).fetchone()
            total += int(row[0])
        return total

    def renumber_suspects(self) -> int:
        """Total suspected re-numbers over every finished run (unfinished runs excluded, rule 4)."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(suspected_renumbers), 0) FROM runs WHERE finished_at IS NOT NULL"
        ).fetchone()
        return int(row[0])

    def possible_false_not_returned(self) -> int:
        """How many ``'not returned'`` status events look like a false positive (Task 9 dev.).

        A ``status_events`` row with ``new_status = 'not returned'`` is counted if the same
        case later shows either sign of having reappeared: a later ``status_events`` row for
        the same ``mkey`` with ``old_status = 'not returned'`` (an explicit transition away from
        it), or the case's current ``last_case_run`` -- the last run :func:`~ntsb_probable_cause.
        recorder.cases.observe_case` actually processed a fresh record for it, which
        ``mark_not_returned`` never touches -- falling after the "not returned" event's own
        ``present_run``. Counts events, not cases: a case marked "not returned" more than once
        contributes one count per such event that was later contradicted.
        """
        rows = self._conn.execute(
            "SELECT mkey, present_run FROM status_events WHERE new_status = 'not returned'"
        ).fetchall()
        count = 0
        for mkey, present_run in rows:
            reappeared_by_status = self._conn.execute(
                "SELECT 1 FROM status_events "
                "WHERE mkey = ? AND old_status = 'not returned' AND present_run > ? LIMIT 1",
                (mkey, present_run),
            ).fetchone()
            if reappeared_by_status is not None:
                count += 1
                continue
            case_row = self._conn.execute(
                "SELECT last_case_run FROM cases WHERE mkey = ?", (mkey,)
            ).fetchone()
            if case_row is not None and case_row[0] is not None and case_row[0] > present_run:
                count += 1
        return count

    def compressed_page_sizes(self) -> list[int]:
        """The compressed byte length of every stored listing page (spec §6.4)."""
        rows = self._conn.execute("SELECT length(gz) FROM listing_pages").fetchall()
        return [int(row[0]) for row in rows]
