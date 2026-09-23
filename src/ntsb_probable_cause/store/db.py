"""``Store``: the only class that touches SQLite (spec S2.5, Task 4).

Every write is one parameterised statement inside :meth:`Store.transaction`; there is no
string-formatted SQL anywhere in this module. Reads go straight through ``self._conn`` since
SQLite serialises them against any open transaction.
"""

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self

from ntsb_probable_cause.store import schema
from ntsb_probable_cause.store.models import (
    ArrivalClassification,
    ArrivalRow,
    CaseRow,
    DocketArrivalRow,
    DocumentRow,
    FeedComparisonResult,
    FeedRow,
    FieldArrivalRow,
    RegulationTransitions,
    RunSummary,
    RunSummaryRow,
    TailArrivals,
)

# The two "real closure" statuses (spec §7): a status event whose new_status is one of these,
# arriving from anything else (never a relabel between the two), is an attested closure. "not
# returned" is deliberately NOT one of these -- it is a missed record, not an attested outcome
# (spec §7's own uncertainty) -- so it is tracked separately throughout this module (Task 11
# fix round 1, IMPORTANT 3/5), but a case CAN still reach a real closure by way of it
# (Ongoing -> 'not returned' -> Completed is a real closure; fix round 3).
_REAL_CLOSURE_STATUSES = ("Completed", "N/A")
_NOT_RETURNED_STATUS = "not returned"
# The two regulation values that mean "watched": not recorded at all, or Part 91 (decision
# 0067). Anything else means the case was dropped from watching. Task 11 fix round 2.
_WATCHED_REGULATIONS = (None, "091")
# `None` and `""` both mean "not recorded" -- mirrors `recorder.cases._EMPTY_REGULATION` /
# `_normalize_regulation`. Duplicated here, not imported: `store` must never import `recorder`
# (recorder already imports store; importing the other way would be circular), and this is a
# two-line rule, not a shared abstraction worth a new module for.
_EMPTY_REGULATION = frozenset({None, ""})

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Shared by field_change_arrivals and first_sight_field_count (Task 11): the first (smallest
# ``id``) field_snapshots row per (mkey, role) -- the run that first recorded any value for
# that role at all, whether that turns out to be a true arrival or a first-sight observation.
_FIRST_FIELD_SNAPSHOT = (
    "(SELECT mkey, role, MIN(id) AS first_id FROM field_snapshots GROUP BY mkey, role)"
)

# Shared by prelim_arrivals and prelim_first_sight_count (Task 11 fix round 1, IMPORTANT 6):
# the same idea as `_FIRST_FIELD_SNAPSHOT`, one row per mkey instead of per (mkey, role).
_FIRST_PRELIM = "(SELECT mkey, MIN(id) AS first_id FROM prelim_narratives GROUP BY mkey)"


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


def _days_between_timestamps(earlier: str, later: str) -> int:
    """Days between the DATE portions of two ``runs.started_at`` timestamps."""
    return (datetime.fromisoformat(later).date() - datetime.fromisoformat(earlier).date()).days


def _normalize_regulation(value: str | None) -> str | None:
    """``None`` and ``""`` both mean "not recorded".

    Mirrors ``recorder.cases`` (see the module-level note on why this is duplicated rather
    than imported).
    """
    return None if value in _EMPTY_REGULATION else value


def _classify_run(present_run: int, closure_run: int | None) -> ArrivalClassification:
    """Where ``present_run`` falls relative to a case's real-closure run (Task 11 IMPORTANT 5).

    ``closure_run`` is ``None`` for a case with no attested closure on record (still ``Ongoing``,
    or its only departure was ``'not returned'``) -- every arrival on such a case is, by
    definition, before any closure that might one day happen.
    """
    if closure_run is None or present_run < closure_run:
        return ArrivalClassification.BEFORE_CLOSURE
    if present_run == closure_run:
        return ArrivalClassification.SAME_RUN_AS_CLOSURE
    return ArrivalClassification.AFTER_CLOSURE


def _regulation_excluded_at(
    events: Sequence[tuple[int, int, str | None, str | None]],
    current_regulation: str | None,
    present_run: int,
) -> bool:
    """Whether the case's regulation, as recorded AT ``present_run``, excluded it from watching.

    Task 11 fix round 2, IMPORTANT I5. This NEVER reads ``cases.watched``: that flag is the
    case's *current* state, and it is cleared when a closed case's 30-day tail expires --
    reproduced live by the reviewer, a case whose field, prelim and docket all arrived on night
    3 and which closed on night 5 had every one of those arrivals silently move from
    BEFORE_CLOSURE to EXCLUDED_UNWATCHED on night 6, once the tail expired, even though nothing
    about the case's regulation had ever changed. Closure and tail expiry are handled entirely
    by :func:`_classify_run`; this function answers a narrower question -- was the case's
    *regulation* itself, as recorded at the time, something other than empty or Part 91 -- from
    ``regulation_events`` history alone.

    ``events`` is one case's ``regulation_events`` rows, ``(present_run, id, old, new)``,
    sorted by ``(present_run, id)`` ascending (the caller's contract; see
    :meth:`Store._regulation_events_by_mkey`).

    - If any event's ``present_run`` is at or before this arrival's, the LATEST such event's
      ``new`` value is what was in force -- so a regulation drop recorded on the arrival's own
      run excludes that arrival too. This is conservative, and the report says so.
    - Otherwise, if events exist but all of them are later than this arrival, the EARLIEST
      event's ``old`` value is what was in force at ``present_run`` (nothing had changed it
      yet).
    - Otherwise (no events at all for the case), there is no history to consult; the case's
      *current* ``cases.regulation`` is used as a fallback -- stated as a fallback in the
      report, not silently treated as history.
    """
    at_or_before = [event for event in events if event[0] <= present_run]
    if at_or_before:
        _run, _id, _old, new = at_or_before[-1]
        return _normalize_regulation(new) not in _WATCHED_REGULATIONS
    if events:
        _run, _id, old, _new = events[0]
        return _normalize_regulation(old) not in _WATCHED_REGULATIONS
    return _normalize_regulation(current_regulation) not in _WATCHED_REGULATIONS


def _classify_arrival(
    mkey: int,
    present_run: int,
    *,
    closures: Mapping[int, int],
    regulation_events: Mapping[int, Sequence[tuple[int, int, str | None, str | None]]],
    current_regulation: Mapping[int, str | None],
) -> ArrivalClassification:
    """The one classification rule every arrival query uses (Task 11 fix round 2, IMPORTANT I5).

    Combines :func:`_regulation_excluded_at` (was the case's regulation, at the time, something
    other than empty or Part 91) with :func:`_classify_run` (before/same-run/after the case's
    real closure) -- shared, identically, by field, preliminary-narrative and docket arrivals,
    so the rule is written, and tested, once.
    """
    if _regulation_excluded_at(
        regulation_events.get(mkey, ()), current_regulation.get(mkey), present_run
    ):
        return ArrivalClassification.EXCLUDED_UNWATCHED
    return _classify_run(present_run, closures.get(mkey))


def _parse_feed_timestamp(text: str) -> datetime | None:
    """Parse a change-feed timestamp; ``None`` if it does not parse.

    Task 11 fix round 1, CRITICAL 1: the one ``*DateTimeUtc`` field ever seen in a saved
    response (``caseCreatedDateTimeUtc`` in ``tests/fixtures/api/page.json``) carries no zone
    offset at all (``"2016-08-02T13:00:00"``); the "Z"/``+00:00`` form the previous round
    assumed has never actually been confirmed live. A value with no zone is read as UTC --
    the field name says so -- rather than as a naive value that would silently compare unequal
    to every zone-aware timestamp this module also builds. A trailing ``Z`` is still tolerated
    for whichever form the live feed turns out to use.
    """
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _feed_reported_change(
    feed_rows: Iterable[tuple[int, str]],
    *,
    absent_run: int,
    present_run: int,
    window_days: int,
    run_started_at: Mapping[int, str],
) -> bool:
    """Whether one field change is "reported by the feed" (Task 11 fix round 1, CRITICAL 2).

    One rule, both conditions required:

    1. the ``change_feed`` row's own ``last_change_utc`` is strictly AFTER the absent run's
       start time -- so a row already on file about some earlier, unrelated change (the feed's
       2-day lookback can easily carry one into an unrelated night's poll) is never credited to
       *this* change;
    2. the row was polled by a run whose ``started_at`` falls within ``window_days`` days, BY
       TIME, of the present run's start -- at or after it, never before, and no more than
       ``window_days`` days later. Never by run id: a missed night shifts run ids without
       shifting time, so an id-based window is not a time window at all.

    A first-sight row (``absent_run IS NULL``) is never passed here -- :meth:`Store.
    feed_comparison` only calls this for rows with a known absent side, and needs one to form
    condition 1's boundary. A timestamp that fails to parse fails its comparison closed (never
    counts as a match).
    """
    absent_started = _parse_feed_timestamp(run_started_at.get(absent_run, ""))
    present_started = _parse_feed_timestamp(run_started_at.get(present_run, ""))
    if absent_started is None or present_started is None:
        return False
    window_end = present_started + timedelta(days=window_days)
    for run_id, last_change_utc in feed_rows:
        poll_started = _parse_feed_timestamp(run_started_at.get(run_id, ""))
        if poll_started is None or not (present_started <= poll_started <= window_end):
            continue
        changed_at = _parse_feed_timestamp(last_change_utc)
        if changed_at is not None and changed_at > absent_started:
            return True
    return False


class Store:
    """The recorder's SQLite store: one file, opened in WAL mode with foreign keys on."""

    def __init__(self, path: Path, *, readonly: bool = False) -> None:
        """Open ``path``.

        ``readonly=True`` opens a true read-only connection (Task 11 fix round 2, MINOR 4): a
        SQLite URI with ``mode=ro``, so a bug that tried to write would raise rather than
        silently succeed, and :meth:`close` skips the WAL checkpoint (itself a write)
        accordingly. Raises whatever ``sqlite3.connect`` raises if ``path`` does not exist --
        callers that want "no store yet" to be a soft case (rather than an exception) must
        check ``path.exists()`` before constructing a read-only ``Store``.

        The URI is built with :meth:`Path.as_uri`, not an f-string (Task 11 fix round 3,
        MINOR): a path containing a literal ``?`` or ``#`` is exactly what a SQLite URI's own
        query string and fragment delimiters are, so an unescaped one would truncate the path
        there, silently open (or create) the wrong file, and lose ``mode=ro`` along with it.
        ``as_uri()`` percent-encodes both characters; ``?mode=ro`` is appended after, where it
        is unambiguously the query string.
        """
        self._path = path
        self._readonly = readonly
        if readonly:
            self._conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        else:
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

        A read-only store (Task 11 fix round 2, MINOR 4) skips all of this: it never opened a
        transaction, and both ``wal_checkpoint`` and ``commit`` are writes that a ``mode=ro``
        connection cannot perform.
        """
        if self._readonly:
            self._conn.close()
            return
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

    def schema_version(self) -> int:
        """The store's current ``schema_version``, without applying any pending migration.

        For a read-only store (Task 11 fix round 2, MINOR 4): a caller that must never write
        can still tell whether the file's schema matches what the code expects, and refuse to
        read it otherwise, rather than calling :meth:`migrate` (a write) just to find out.
        """
        return self._current_version()

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

    def add_regulation_event(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        mkey: int,
        *,
        old: str | None,
        new: str | None,
        was_watched: bool,
        absent_run: int | None,
        present_run: int,
        run_id: int,
    ) -> None:
        """Record a change to a case's recorded regulation (Task 11 fix round 1, IMPORTANT 7).

        Migration 2's ``regulation_events`` fills the gap spec §4.1 assumed away: regulation is
        not an ``EvidenceRole`` and never went through ``field_snapshots``, and
        ``cases.regulation`` is overwritten on every observation, so before migration 2 there
        was no history to count changes from at all. ``recorder.cases.observe_case`` is the one
        caller: it writes a row only when the *normalised* regulation differs from the case's
        existing value (``None`` and ``""`` both read as "empty"; empty-to-empty is not a
        change), never on a case's first sight.
        """
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO regulation_events "
                "(mkey, old, new, was_watched, absent_run, present_run, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (mkey, old, new, int(was_watched), absent_run, present_run, run_id),
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
    # 2): a field, docket or prelim narrative is either a *true arrival* (there is a run that
    # observed its absence before the run that observed its presence -- ``absent_run IS NOT
    # NULL``) or a *first-sight* observation (present already at the very first run that could
    # have seen it, so only a lower bound is known). True arrivals are reported as day counts;
    # first-sight observations are reported separately, as a count, never mixed into the same
    # distribution. Every day count also carries its ``absent_days`` sibling -- the same
    # calculation applied to the run that last observed the thing's absence, giving the lower
    # bound next to the upper bound `days` already is (Task 11 fix round 1, MINOR 2).
    #
    # Fix round 1, IMPORTANT 5 (corrected in fix round 2): every true arrival is further
    # classified by :class:`~ntsb_probable_cause.store.ArrivalClassification`, relative to the
    # case's real closure (a status event whose ``new_status`` is ``'Completed'`` or ``'N/A'``
    # -- never ``'not returned'``, which is not an attested closure) and to whether the case's
    # regulation, AT THE TIME of the arrival, was recorded as anything other than empty or Part
    # 91 -- from ``regulation_events`` history (:func:`_regulation_excluded_at`), never from
    # ``cases.watched``, whose *current* value a closed case's tail expiry clears regardless of
    # what its regulation ever was. Only ``BEFORE_CLOSURE`` rows belong in the distribution
    # spec §10.2 says replaces ``scoring.samples.MASK_LIFTS_AT_DAY``.

    def _closure_runs(self) -> dict[int, int]:
        """Each case's EARLIEST real-closure event's ``present_run`` (Task 11 fix round 3).

        A real closure is a status event whose ``new_status`` is ``'Completed'`` or ``'N/A'``
        (``_REAL_CLOSURE_STATUSES``), arriving from anything that is NOT already one of those
        two statuses -- ``old_status IS NULL`` (the case's very first observation was already
        closed) or ``old_status`` outside the closure statuses. That deliberately counts a
        closure reached via ``'not returned'`` (``Ongoing`` -> ``'not returned'`` ->
        ``Completed``, spec §7's own uncertain status is not exempt from ever really closing)
        while still excluding a later re-label between two closure statuses (``Completed`` to
        ``N/A``): the second fix round required ``old_status = 'Ongoing'`` specifically, which
        wrongly excluded the ``'not returned'`` path along with the re-label it was meant to
        catch -- reproduced live by the reviewer with the real recorder functions. The broader
        predicate here fixes both at once, verified against both scenarios in
        ``tests/test_recorder_report.py``.

        Keyed by the EARLIEST such event, not the latest: once a case has genuinely closed,
        that is when it closed; a later status row for the same case can only match this
        predicate again if the case reopened to a non-closure status and closed a second time,
        which the earliest closure already answers "when did this case first close" for.
        """
        placeholders = ", ".join("?" for _ in _REAL_CLOSURE_STATUSES)
        rows = self._conn.execute(
            "SELECT mkey, MIN(present_run) FROM status_events "  # noqa: S608 -- placeholders
            f"WHERE new_status IN ({placeholders}) "
            f"AND (old_status IS NULL OR old_status NOT IN ({placeholders})) "
            "GROUP BY mkey",
            (*_REAL_CLOSURE_STATUSES, *_REAL_CLOSURE_STATUSES),
        ).fetchall()
        return {int(mkey): int(present_run) for mkey, present_run in rows}

    def _regulation_events_by_mkey(
        self,
    ) -> dict[int, list[tuple[int, int, str | None, str | None]]]:
        """Every case's ``regulation_events`` rows, sorted for :func:`_regulation_excluded_at`.

        Each row is ``(present_run, id, old, new)``, sorted by ``(present_run, id)`` ascending
        -- the precondition that function documents.
        """
        rows = self._conn.execute(
            "SELECT mkey, present_run, id, old, new FROM regulation_events "
            "ORDER BY mkey, present_run, id"
        ).fetchall()
        result: dict[int, list[tuple[int, int, str | None, str | None]]] = {}
        for mkey, present_run, event_id, old, new in rows:
            result.setdefault(int(mkey), []).append((int(present_run), int(event_id), old, new))
        return result

    def _case_regulation(self) -> dict[int, str | None]:
        """Every case's *current* ``cases.regulation`` -- the no-history fallback (IMPORTANT I5)."""
        rows = self._conn.execute("SELECT mkey, regulation FROM cases").fetchall()
        return {int(mkey): regulation for mkey, regulation in rows}

    def _arrival_context(
        self,
    ) -> tuple[
        dict[int, int],
        dict[int, list[tuple[int, int, str | None, str | None]]],
        dict[int, str | None],
    ]:
        """The three lookups every arrival classification needs, fetched once per call.

        Returns ``(closures, regulation_events_by_mkey, current_regulation)``.
        """
        return self._closure_runs(), self._regulation_events_by_mkey(), self._case_regulation()

    def field_change_arrivals(self) -> list[FieldArrivalRow]:
        """Every true evidence-field arrival: role, days, absent-side days, and classification.

        Precisely: for each ``(mkey, role)`` pair, take its *first* ``field_snapshots`` row (the
        smallest ``id`` -- ``cases.py``'s ``_apply_fields`` never writes a row for a role while
        it is still unknown, so this is the run that first recorded a value for that role at
        all). Included only when that row's ``absent_run IS NOT NULL`` -- a true arrival, with a
        run that observed the field's absence beforehand. A first-sight row (``absent_run IS
        NULL``) is excluded here; see :meth:`first_sight_field_count`.

        ``days``/``absent_days`` are :func:`_days_between` applied to the case's ``event_date``
        and, respectively, the row's ``present_run``'s and ``absent_run``'s ``runs.started_at``.
        """
        rows = self._conn.execute(
            # `_FIRST_FIELD_SNAPSHOT` is a fixed module-level constant (see its own comment),
            # not external input; there is no placeholder syntax to parameterise a sub-SELECT
            # with regardless.
            "SELECT fs.role, fs.mkey, fs.present_run, rp.started_at, ra.started_at, "  # noqa: S608
            "c.event_date "
            "FROM field_snapshots fs "
            f"JOIN {_FIRST_FIELD_SNAPSHOT} fr ON fr.first_id = fs.id "
            "JOIN runs rp ON rp.run_id = fs.present_run "
            "JOIN runs ra ON ra.run_id = fs.absent_run "
            "JOIN cases c ON c.mkey = fs.mkey "
            "WHERE fs.absent_run IS NOT NULL"
        ).fetchall()
        closures, regulation_events, current_regulation = self._arrival_context()
        result: list[FieldArrivalRow] = []
        for role, mkey, present_run, present_started, absent_started, event_date in rows:
            classification = _classify_arrival(
                mkey,
                present_run,
                closures=closures,
                regulation_events=regulation_events,
                current_regulation=current_regulation,
            )
            result.append(
                FieldArrivalRow(
                    role=str(role),
                    days=_days_between(event_date, present_started),
                    absent_days=_days_between(event_date, absent_started),
                    classification=classification,
                )
            )
        return result

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

    def prelim_arrivals(self) -> list[ArrivalRow]:
        """Every true preliminary-narrative arrival (Task 11 fix round 1, IMPORTANT 6).

        The mask (``scoring.samples.masked_exclusions``) currently withholds the preliminary
        narrative unconditionally, in the docket's "late set" -- this is the arrival data that
        finding needs to be checked against. Same rule as :meth:`field_change_arrivals`, over
        ``prelim_narratives`` instead of ``field_snapshots``: the first row per ``mkey`` with a
        known absent side.
        """
        rows = self._conn.execute(
            "SELECT pre.mkey, pre.present_run, rp.started_at, ra.started_at, c.event_date "  # noqa: S608
            "FROM prelim_narratives pre "
            f"JOIN {_FIRST_PRELIM} pf ON pf.first_id = pre.id "
            "JOIN runs rp ON rp.run_id = pre.present_run "
            "JOIN runs ra ON ra.run_id = pre.absent_run "
            "JOIN cases c ON c.mkey = pre.mkey "
            "WHERE pre.absent_run IS NOT NULL"
        ).fetchall()
        closures, regulation_events, current_regulation = self._arrival_context()
        result: list[ArrivalRow] = []
        for mkey, present_run, present_started, absent_started, event_date in rows:
            classification = _classify_arrival(
                mkey,
                present_run,
                closures=closures,
                regulation_events=regulation_events,
                current_regulation=current_regulation,
            )
            result.append(
                ArrivalRow(
                    days=_days_between(event_date, present_started),
                    absent_days=_days_between(event_date, absent_started),
                    classification=classification,
                )
            )
        return result

    def prelim_first_sight_count(self) -> int:
        """How many cases already had a preliminary narrative at their first-ever run."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM prelim_narratives pre "  # noqa: S608 -- see prelim_arrivals.
            f"JOIN {_FIRST_PRELIM} pf ON pf.first_id = pre.id "
            "JOIN cases c ON c.mkey = pre.mkey "
            "WHERE pre.absent_run IS NULL AND pre.present_run = c.first_seen_run"
        ).fetchone()
        return int(row[0])

    def _docket_poll_groups(self) -> dict[int, list[tuple[int, str, int | None, str]]]:
        """Every case's ``docket_polls`` rows, sorted oldest first.

        Each row is ``(run_id, outcome, declared_items, started_at)``. Shared by every
        docket-arrival query below (Task 11 fix round 1, IMPORTANT 4) so the "first poll
        ever" / "first read poll" / "last no-docket-or-empty poll before it" logic is written,
        and tested, once.
        """
        rows = self._conn.execute(
            "SELECT dp.mkey, dp.run_id, dp.outcome, dp.declared_items, r.started_at "
            "FROM docket_polls dp JOIN runs r ON r.run_id = dp.run_id "
            "ORDER BY dp.mkey, dp.run_id"
        ).fetchall()
        groups: dict[int, list[tuple[int, str, int | None, str]]] = {}
        for mkey, run_id, outcome, declared_items, started_at in rows:
            groups.setdefault(int(mkey), []).append(
                (int(run_id), str(outcome), declared_items, str(started_at))
            )
        return groups

    def _case_event_dates(self) -> dict[int, str]:
        rows = self._conn.execute("SELECT mkey, event_date FROM cases").fetchall()
        return {int(mkey): str(event_date) for mkey, event_date in rows}

    def docket_arrivals(self) -> list[DocketArrivalRow]:
        """Every true docket arrival: days, absent-side days, document count, classification.

        Task 11 fix round 1, IMPORTANT 4: a *true* arrival needs an earlier poll that actually
        observed absence -- ``outcome`` ``'no-docket'`` or ``'empty'`` -- before the case's
        first ``'read'`` poll (a page with at least one document, spec §6.2). The absent side is
        the LAST such poll before that first read poll (the tightest true bound on record). Two
        other populations are excluded here and counted elsewhere: the very first poll ever
        already being ``'read'`` (:meth:`docket_first_sight_count`), and a first read poll
        preceded only by ``'failed'`` polls, with no genuine absence observation at all
        (:meth:`docket_absent_side_unknown_count`). A case with no ``'read'`` poll at all
        contributes to none of the three.
        """
        groups = self._docket_poll_groups()
        event_dates = self._case_event_dates()
        closures, regulation_events, current_regulation = self._arrival_context()
        result: list[DocketArrivalRow] = []
        for mkey, rows in groups.items():
            read_rows = [r for r in rows if r[1] == "read"]
            if not read_rows:
                continue
            first_read = read_rows[0]
            if first_read[0] == rows[0][0]:
                continue  # present at first observation -- docket_first_sight_count
            earlier = [r for r in rows if r[0] < first_read[0]]
            absent_candidates = [r for r in earlier if r[1] in ("no-docket", "empty")]
            if not absent_candidates:
                continue  # absent side unknown -- docket_absent_side_unknown_count
            if mkey not in event_dates:
                continue
            event_date = event_dates[mkey]
            absent_poll = absent_candidates[-1]  # the LAST such poll before the first read poll
            present_run, _outcome, declared_items, present_started = first_read
            classification = _classify_arrival(
                mkey,
                present_run,
                closures=closures,
                regulation_events=regulation_events,
                current_regulation=current_regulation,
            )
            result.append(
                DocketArrivalRow(
                    days=_days_between(event_date, present_started),
                    absent_days=_days_between(event_date, absent_poll[3]),
                    document_count=int(declared_items or 0),
                    classification=classification,
                )
            )
        return result

    def docket_first_sight_count(self) -> int:
        """How many cases already had a documented docket at their very first poll ever."""
        groups = self._docket_poll_groups()
        return sum(1 for rows in groups.values() if rows and rows[0][1] == "read")

    def docket_absent_side_unknown_count(self) -> int:
        """Cases with a first read poll preceded only by ``'failed'`` polls (Task 11 IMPORTANT 4).

        Neither present-at-first-sight (there IS an earlier poll) nor a true arrival (that
        earlier poll never actually observed the docket's absence) -- a third population,
        counted on its own rather than folded into either.
        """
        groups = self._docket_poll_groups()
        count = 0
        for rows in groups.values():
            read_rows = [r for r in rows if r[1] == "read"]
            if not read_rows:
                continue
            first_read_run = read_rows[0][0]
            if first_read_run == rows[0][0]:
                continue
            earlier = [r for r in rows if r[0] < first_read_run]
            if not any(outcome in ("no-docket", "empty") for _run_id, outcome, _d, _s in earlier):
                count += 1
        return count

    def feed_comparison(self, window_days: int = 1) -> FeedComparisonResult:
        """The change-feed comparison (Task 11 fix round 1, CRITICAL 2).

        See :class:`~ntsb_probable_cause.store.FeedComparisonResult` and
        :func:`_feed_reported_change` for the exact rule and what each of the four numbers
        counts. ``unparsable_timestamps`` (Task 11 fix round 2, MINOR 3) is a separate,
        whole-table count of every stored ``last_change_utc`` value that does not parse at all
        -- not scoped to the mkeys involved in a comparison, so it is stable across
        ``window_days`` values and tells a reader how much of the feed's own data was unusable,
        as opposed to simply not matching.
        """
        run_started_at = dict(self._conn.execute("SELECT run_id, started_at FROM runs").fetchall())
        changes = self._conn.execute(
            "SELECT mkey, absent_run, present_run FROM field_snapshots WHERE absent_run IS NOT NULL"
        ).fetchall()
        field_changes_reported = 0
        case_nights: set[tuple[int, int]] = set()
        case_nights_reported: set[tuple[int, int]] = set()
        feed_by_mkey: dict[int, list[tuple[int, str]]] = {}
        for mkey, absent_run, present_run in changes:
            case_nights.add((mkey, present_run))
            if mkey not in feed_by_mkey:
                feed_by_mkey[mkey] = self._conn.execute(
                    "SELECT run_id, last_change_utc FROM change_feed WHERE mkey = ?", (mkey,)
                ).fetchall()
            if _feed_reported_change(
                feed_by_mkey[mkey],
                absent_run=absent_run,
                present_run=present_run,
                window_days=window_days,
                run_started_at=run_started_at,
            ):
                field_changes_reported += 1
                case_nights_reported.add((mkey, present_run))
        all_timestamps = self._conn.execute("SELECT last_change_utc FROM change_feed").fetchall()
        unparsable = sum(1 for (value,) in all_timestamps if _parse_feed_timestamp(value) is None)
        return FeedComparisonResult(
            field_changes=len(changes),
            field_changes_reported=field_changes_reported,
            case_nights=len(case_nights),
            case_nights_reported=len(case_nights_reported),
            unparsable_timestamps=unparsable,
        )

    def regulation_transitions(self) -> RegulationTransitions:
        """Regulation changes among watched cases (Task 11 fix round 1, IMPORTANT 7).

        Replaces the previous ``regulation_changes()`` lower-bound estimate now that migration
        2's ``regulation_events`` gives a real history. Every row counted here has
        ``was_watched = 1`` -- a case already dropped from watching when its regulation changed
        is not "a watched case that changed regulation" (spec §4.1). Values are compared after
        :func:`_normalize_regulation` (``None``/``""`` both read as empty).

        A store that ran under schema version 1 before migration 2 was applied would have no
        ``regulation_events`` rows for those nights -- an UNKNOWN period, not zero changes; this
        method cannot tell the two apart from the rows alone (Task 11 fix round 2, I7). It
        makes no claim about any particular store's own history; the report states the general
        rule (regulation changes are known only from the night the table was added) rather
        than asserting that gap does or does not apply to whichever store produced the report
        it is reading (fix round 3, WORDING 2).
        """
        rows = self._conn.execute(
            "SELECT re.old, re.new, re.present_run, c.first_seen_run "
            "FROM regulation_events re "
            "JOIN cases c ON c.mkey = re.mkey "
            "WHERE re.was_watched = 1"
        ).fetchall()
        run_started_at = dict(self._conn.execute("SELECT run_id, started_at FROM runs").fetchall())
        empty_to_091 = empty_to_other = changed_value = value_to_empty = 0
        fill_in_days: list[int] = []
        for old, new, present_run, first_seen_run in rows:
            old_n = _normalize_regulation(old)
            new_n = _normalize_regulation(new)
            if old_n is None and new_n is not None:
                if new_n == "091":
                    empty_to_091 += 1
                    first_started = run_started_at.get(first_seen_run)
                    present_started = run_started_at.get(present_run)
                    if first_started is not None and present_started is not None:
                        fill_in_days.append(
                            _days_between_timestamps(first_started, present_started)
                        )
                else:
                    empty_to_other += 1
            elif old_n is not None and new_n is None:
                value_to_empty += 1
            elif old_n is not None and new_n is not None:
                changed_value += 1
        return RegulationTransitions(
            empty_to_091=empty_to_091,
            empty_to_091_days=tuple(fill_in_days),
            empty_to_other=empty_to_other,
            changed_value=changed_value,
            value_to_empty=value_to_empty,
        )

    def tail_arrivals(self) -> TailArrivals:
        """Closure-tail document appearances (Task 11 fix round 1, IMPORTANT 3).

        See :class:`~ntsb_probable_cause.store.TailArrivals` for exactly what each of the four
        numbers counts. Only ``kind = 'appeared'`` document events with a known absent side
        (``absent_run IS NOT NULL``) are counted -- a first-sight document (``absent_run IS
        NULL``) was never observed to be absent, so it cannot be "an arrival" in this sense.
        ``'appeared'`` already covers a document reappearing after a prior disappearance, and
        one half of a suspected re-numbered pair (``recorder/dockets.py``'s ``diff_documents``
        writes both as ordinary ``appeared``/``disappeared`` events in addition to incrementing
        the suspected-renumber count) -- nothing here treats those differently.
        """
        real_closures = self._closure_runs()
        not_returned = self._conn.execute(
            "SELECT mkey, MAX(present_run) FROM status_events WHERE new_status = ? GROUP BY mkey",
            (_NOT_RETURNED_STATUS,),
        ).fetchall()

        same_run = after = 0
        for mkey, closure_run in real_closures.items():
            rows = self._conn.execute(
                "SELECT present_run FROM document_events WHERE mkey = ? AND kind = 'appeared' "
                "AND absent_run IS NOT NULL AND present_run >= ?",
                (mkey, closure_run),
            ).fetchall()
            for (present_run,) in rows:
                if present_run == closure_run:
                    same_run += 1
                else:
                    after += 1

        not_returned_tail = 0
        for mkey, event_run in not_returned:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM document_events WHERE mkey = ? AND kind = 'appeared' "
                "AND absent_run IS NOT NULL AND present_run >= ?",
                (mkey, event_run),
            ).fetchone()
            not_returned_tail += int(row[0])

        return TailArrivals(
            same_run=same_run,
            after=after,
            total=same_run + after,
            not_returned_tail=not_returned_tail,
        )

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
