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
        watch_until TEXT,
        watched INTEGER NOT NULL DEFAULT 1
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

    -- Pages are deduplicated by hash, not by case: two cases can (and, for a shared
    -- "not released" page, routinely do) receive byte-identical listing pages. `mkey` and
    -- `first_run` name whichever case and run first stored this exact page, not every case
    -- that has ever received it -- that per-poll association lives in `docket_polls.page_sha`,
    -- one row per case per run, not here (Task 8 fix round 1, Minor 2).
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
    # Migration 2 (Task 11 fix round 1, IMPORTANT 7): a regulation history and an index the
    # feed comparison needs. Never edit migration 1 above -- a live store may already exist at
    # version 1, and `Store.migrate` only ever applies scripts *after* the current version.
    #
    # `regulation_events` fills a gap spec S2.5 §4.1 assumed away: "the recorder snapshots the
    # field, and the 8-week report counts the changes". Regulation is not an `EvidenceRole`, so
    # it never went through `field_snapshots`, and `cases.regulation` is overwritten on every
    # observation -- before this migration there was no history to count changes from at all.
    # A store that ran only under migration 1 has no regulation history for those nights; the
    # report states this rather than silently treating the gap as "no changes occurred".
    """
    CREATE TABLE regulation_events (
        id INTEGER PRIMARY KEY,
        mkey INTEGER NOT NULL,
        old TEXT,
        new TEXT,
        was_watched INTEGER NOT NULL,
        absent_run INTEGER,
        present_run INTEGER NOT NULL,
        run_id INTEGER NOT NULL
    );
    CREATE INDEX change_feed_mkey ON change_feed (mkey);
    """,
    # Migration 3 (final-review fix, item 2; Andy's decision 2026-09-23: "Add it"). Records
    # which event months a run fetched CLEANLY -- to completion, with no ApiError, and not cut
    # short by the outage budget's deadline or circuit breaker (item 1). One row per
    # (run_id, month) actually fetched cleanly; a month skipped or failed gets no row at all.
    #
    # This exists so a case seen for the very first time can still get a TRUE absent side
    # (`field_snapshots.absent_run IS NOT NULL`) instead of always reading as a first-sight
    # observation: `Store.last_clean_fetch` finds the latest EARLIER run that cleanly fetched
    # the new case's event month, and `recorder.cases.observe_case`'s `new_case_absent_run`
    # parameter uses that as the first-sight snapshots' `absent_run` when the case genuinely
    # was not there before. Never edit migrations 1 or 2 above -- a live store may already
    # exist at either version, and `Store.migrate` only ever applies scripts after the current
    # version.
    """
    CREATE TABLE run_months (
        run_id INTEGER NOT NULL,
        month TEXT NOT NULL,
        PRIMARY KEY (run_id, month)
    );
    """,
)
