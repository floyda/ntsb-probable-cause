"""Numbered schema migrations for the recorder's SQLite store (spec S2.5, Task 4).

``MIGRATIONS[i]`` is migration ``i + 1``; ``Store.migrate`` applies each pending script with
``executescript`` in order and records the resulting version in ``schema_version``.
"""

MIGRATIONS: tuple[str, ...] = (
    # Migration 1: runs, cases and their history, the docket poll log and document ledger,
    # and the API change feed. See docs/specs/2026-09-22-s25-recorder-design.md and this
    # stage's plan, Task 4, for the shape each table follows.
    """
    CREATE TABLE schema_version (version INTEGER NOT NULL);

    CREATE TABLE runs (
        run_id INTEGER PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        commit_sha TEXT NOT NULL,
        dirty INTEGER NOT NULL,
        cases_polled INTEGER,
        cases_changed INTEGER,
        new_documents INTEGER,
        failures INTEGER,
        suspected_renumbers INTEGER,
        minutes REAL
    );

    CREATE TABLE cases (
        mkey INTEGER PRIMARY KEY,
        ntsb_number TEXT NOT NULL,
        event_date TEXT NOT NULL,
        regulation TEXT,
        status TEXT NOT NULL,
        first_seen_run INTEGER NOT NULL,
        last_seen_run INTEGER NOT NULL,
        last_case_run INTEGER,
        last_docket_run INTEGER,
        watch_until TEXT
    );

    CREATE TABLE status_events (
        id INTEGER PRIMARY KEY,
        mkey INTEGER NOT NULL,
        old_status TEXT,
        new_status TEXT NOT NULL,
        absent_run INTEGER,
        present_run INTEGER NOT NULL,
        run_id INTEGER NOT NULL
    );

    CREATE TABLE field_snapshots (
        id INTEGER PRIMARY KEY,
        mkey INTEGER NOT NULL,
        role TEXT NOT NULL,
        value_json TEXT NOT NULL,
        absent_run INTEGER,
        present_run INTEGER NOT NULL,
        run_id INTEGER NOT NULL
    );
    CREATE INDEX field_snapshots_case ON field_snapshots (mkey, role, id);

    CREATE TABLE prelim_narratives (
        id INTEGER PRIMARY KEY,
        mkey INTEGER NOT NULL,
        text TEXT NOT NULL,
        absent_run INTEGER,
        present_run INTEGER NOT NULL,
        run_id INTEGER NOT NULL
    );

    CREATE TABLE docket_polls (
        id INTEGER PRIMARY KEY,
        mkey INTEGER NOT NULL,
        run_id INTEGER NOT NULL,
        outcome TEXT NOT NULL,
        reason TEXT,
        declared_items INTEGER,
        creation_date TEXT,
        last_modified TEXT,
        release_date TEXT,
        page_sha TEXT
    );
    CREATE INDEX docket_polls_case ON docket_polls (mkey, run_id);

    CREATE TABLE listing_pages (
        page_sha TEXT PRIMARY KEY,
        mkey INTEGER NOT NULL,
        gz BLOB NOT NULL,
        first_run INTEGER NOT NULL
    );

    CREATE TABLE documents (
        mkey INTEGER NOT NULL,
        doc_id INTEGER NOT NULL,
        href TEXT NOT NULL,
        position INTEGER NOT NULL,
        title TEXT NOT NULL,
        pages INTEGER NOT NULL,
        photos INTEGER NOT NULL,
        extension TEXT NOT NULL,
        absent_run INTEGER,
        present_run INTEGER NOT NULL,
        last_present_run INTEGER NOT NULL,
        gone_absent_run INTEGER,
        gone_present_run INTEGER,
        PRIMARY KEY (mkey, doc_id)
    );

    CREATE TABLE document_events (
        id INTEGER PRIMARY KEY,
        mkey INTEGER NOT NULL,
        doc_id INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('appeared', 'revised', 'disappeared')),
        absent_run INTEGER,
        present_run INTEGER NOT NULL,
        run_id INTEGER NOT NULL,
        old_json TEXT,
        new_json TEXT
    );

    CREATE TABLE change_feed (
        id INTEGER PRIMARY KEY,
        mkey INTEGER NOT NULL,
        last_change_utc TEXT NOT NULL,
        step_number INTEGER,
        step_id TEXT,
        case_closed INTEGER NOT NULL,
        run_id INTEGER NOT NULL
    );
    """,
)
