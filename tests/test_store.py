import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from ntsb_probable_cause.store import (
    CaseRow,
    DocumentRow,
    FeedRow,
    RunSummary,
    Store,
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store(tmp_path / "r.sqlite") as opened:
        opened.migrate()
        yield opened


def test_migrate_creates_tables_once(tmp_path: Path) -> None:
    store = Store(tmp_path / "r.sqlite")
    assert store.migrate() == 1
    assert store.migrate() == 1
    names = {
        r[0] for r in store.connection.execute("select name from sqlite_master where type='table'")
    }
    assert {
        "runs",
        "cases",
        "documents",
        "document_events",
        "change_feed",
        "listing_pages",
    } <= names
    store.close()


def test_pragmas_are_set(store: Store) -> None:
    journal_mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
    foreign_keys = store.connection.execute("PRAGMA foreign_keys").fetchone()[0]
    assert journal_mode == "wal"
    assert foreign_keys == 1


def test_run_lifecycle(store: Store) -> None:
    run_id = store.begin_run(
        started_at="2026-10-01T03:00:00+00:00", commit_sha="abc1234", dirty=False
    )
    store.finish_run(
        run_id,
        finished_at="2026-10-01T03:38:00+00:00",
        summary=RunSummary(
            cases_polled=3,
            cases_changed=1,
            new_documents=2,
            failures=0,
            suspected_renumbers=0,
            minutes=38.0,
        ),
    )
    assert store.last_run_id() == run_id
    assert store.run_summaries()[0].new_documents == 2


def test_last_run_id_is_none_when_no_runs(store: Store) -> None:
    assert store.last_run_id() is None
    assert store.run_summaries() == []


def test_run_summaries_orders_most_recent_first(store: Store) -> None:
    first = store.begin_run(started_at="2026-10-01T03:00:00+00:00", commit_sha="a", dirty=False)
    second = store.begin_run(started_at="2026-10-02T03:00:00+00:00", commit_sha="b", dirty=True)
    summaries = store.run_summaries()
    assert [row.run_id for row in summaries] == [second, first]
    assert summaries[0].dirty is True
    assert summaries[1].dirty is False
    assert summaries[0].finished_at is None
    assert summaries[0].new_documents is None


def test_watched_mkeys_includes_tail_until_date(store: Store) -> None:
    store.upsert_case(
        CaseRow(
            mkey=1,
            ntsb_number="X",
            event_date="2026-01-01",
            regulation="091",
            status="Ongoing",
            first_seen_run=1,
            last_seen_run=1,
            last_case_run=1,
            last_docket_run=None,
            watch_until=None,
        )
    )
    store.upsert_case(
        CaseRow(
            mkey=2,
            ntsb_number="Y",
            event_date="2025-06-01",
            regulation="091",
            status="Completed",
            first_seen_run=1,
            last_seen_run=1,
            last_case_run=1,
            last_docket_run=None,
            watch_until="2026-10-30",
        )
    )
    assert store.watched_mkeys(today="2026-10-15") == [1, 2]
    assert store.watched_mkeys(today="2026-11-01") == [1]
    assert store.earliest_watched_event_month(today="2026-10-15") == "2025-06"


def test_earliest_watched_event_month_is_none_when_nothing_watched(store: Store) -> None:
    store.upsert_case(
        CaseRow(
            mkey=1,
            ntsb_number="X",
            event_date="2026-01-01",
            regulation="091",
            status="Completed",
            first_seen_run=1,
            last_seen_run=1,
            last_case_run=1,
            last_docket_run=None,
            watch_until=None,
        )
    )
    assert store.watched_mkeys(today="2026-10-15") == []
    assert store.earliest_watched_event_month(today="2026-10-15") is None


def test_get_case_round_trips_and_is_none_when_unseen(store: Store) -> None:
    assert store.get_case(1) is None
    row = CaseRow(
        mkey=1,
        ntsb_number="X",
        event_date="2026-01-01",
        regulation="091",
        status="Ongoing",
        first_seen_run=1,
        last_seen_run=1,
        last_case_run=1,
        last_docket_run=None,
        watch_until=None,
    )
    store.upsert_case(row)
    assert store.get_case(1) == row


def test_upsert_case_replaces_existing_row(store: Store) -> None:
    store.upsert_case(
        CaseRow(
            mkey=1,
            ntsb_number="X",
            event_date="2026-01-01",
            regulation="091",
            status="Ongoing",
            first_seen_run=1,
            last_seen_run=1,
            last_case_run=1,
            last_docket_run=None,
            watch_until=None,
        )
    )
    store.upsert_case(
        CaseRow(
            mkey=1,
            ntsb_number="X",
            event_date="2026-01-01",
            regulation="091",
            status="Completed",
            first_seen_run=1,
            last_seen_run=2,
            last_case_run=2,
            last_docket_run=2,
            watch_until="2026-11-30",
        )
    )
    row = store.get_case(1)
    assert row is not None
    assert row.status == "Completed"
    assert row.last_seen_run == 2
    assert row.watch_until == "2026-11-30"


def test_add_status_event_round_trips(store: Store) -> None:
    store.add_status_event(1, old="Ongoing", new="Completed", absent_run=3, present_run=4, run_id=4)
    row = store.connection.execute(
        "SELECT mkey, old_status, new_status, absent_run, present_run, run_id FROM status_events"
    ).fetchone()
    assert tuple(row) == (1, "Ongoing", "Completed", 3, 4, 4)


def test_latest_snapshot_is_the_newest_row(store: Store) -> None:
    store.add_field_snapshot(
        1, role="engine_type", value_json='"REC"', absent_run=None, present_run=1, run_id=1
    )
    store.add_field_snapshot(
        1, role="engine_type", value_json='"TURBO"', absent_run=1, present_run=2, run_id=2
    )
    assert store.latest_snapshots(1) == {"engine_type": '"TURBO"'}


def test_latest_snapshots_is_empty_for_an_unseen_case(store: Store) -> None:
    assert store.latest_snapshots(999) == {}


def test_prelim_round_trips_and_latest_wins(store: Store) -> None:
    assert store.latest_prelim(1) is None
    store.add_prelim(
        1, text="The pilot lost control on landing.", absent_run=None, present_run=1, run_id=1
    )
    store.add_prelim(
        1, text="The pilot lost control on landing rollout.", absent_run=1, present_run=2, run_id=2
    )
    assert store.latest_prelim(1) == "The pilot lost control on landing rollout."


def test_add_docket_poll_round_trips(store: Store) -> None:
    store.add_docket_poll(
        1,
        run_id=1,
        outcome="read",
        reason=None,
        declared_items=4,
        creation_date="2026-09-01",
        last_modified="2026-09-10",
        release_date="2026-09-10",
        page_sha="a" * 64,
    )
    row = store.connection.execute(
        "SELECT mkey, run_id, outcome, reason, declared_items, creation_date, last_modified, "
        "release_date, page_sha FROM docket_polls"
    ).fetchone()
    assert tuple(row) == (1, 1, "read", None, 4, "2026-09-01", "2026-09-10", "2026-09-10", "a" * 64)


def test_page_is_stored_once(store: Store) -> None:
    store.add_page(page_sha="a" * 64, mkey=1, gz=b"x", run_id=1)
    assert store.has_page("a" * 64)
    assert not store.has_page("b" * 64)


def test_upsert_document_and_documents_for_round_trip(store: Store) -> None:
    assert store.documents_for(1) == {}
    row = DocumentRow(
        mkey=1,
        doc_id=10,
        href="/Docket/Document/docBLOB?ID=10",
        position=1,
        title="Weather",
        pages=2,
        photos=0,
        extension=".pdf",
        absent_run=None,
        present_run=1,
        last_present_run=1,
        gone_absent_run=None,
        gone_present_run=None,
    )
    store.upsert_document(row)
    assert store.documents_for(1) == {10: row}

    revised = row.model_copy(update={"title": "Weather (revised)", "last_present_run": 2})
    store.upsert_document(revised)
    assert store.documents_for(1) == {10: revised}


def test_add_document_event_serializes_old_and_new_json(store: Store) -> None:
    store.add_document_event(
        1,
        doc_id=10,
        kind="appeared",
        absent_run=None,
        present_run=1,
        run_id=1,
        old=None,
        new={"title": "Weather"},
    )
    store.add_document_event(
        1,
        doc_id=10,
        kind="revised",
        absent_run=1,
        present_run=2,
        run_id=2,
        old={"pages": 2},
        new={"pages": 3},
    )
    rows = store.connection.execute(
        "SELECT kind, old_json, new_json FROM document_events ORDER BY id"
    ).fetchall()
    assert rows[0][0] == "appeared"
    assert rows[0][1] is None
    assert json.loads(rows[0][2]) == {"title": "Weather"}
    assert rows[1][0] == "revised"
    assert json.loads(rows[1][1]) == {"pages": 2}
    assert json.loads(rows[1][2]) == {"pages": 3}


def test_add_document_event_rejects_an_unknown_kind_and_rolls_back(store: Store) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        store.add_document_event(
            1,
            doc_id=10,
            kind="bogus",
            absent_run=None,
            present_run=1,
            run_id=1,
            old=None,
            new=None,
        )
    count = store.connection.execute("SELECT COUNT(*) FROM document_events").fetchone()[0]
    assert count == 0


def test_add_feed_rows_round_trips(store: Store) -> None:
    rows = [
        FeedRow(
            mkey=1,
            last_change_utc="2026-09-20T00:00:00+00:00",
            step_number=1,
            step_id="prelim",
            case_closed=False,
        ),
        FeedRow(
            mkey=2,
            last_change_utc="2026-09-21T00:00:00+00:00",
            step_number=None,
            step_id=None,
            case_closed=True,
        ),
    ]
    store.add_feed_rows(rows, run_id=1)
    stored = store.connection.execute(
        "SELECT mkey, last_change_utc, step_number, step_id, case_closed, run_id "
        "FROM change_feed ORDER BY mkey"
    ).fetchall()
    assert tuple(stored[0]) == (1, "2026-09-20T00:00:00+00:00", 1, "prelim", 0, 1)
    assert tuple(stored[1]) == (2, "2026-09-21T00:00:00+00:00", None, None, 1, 1)


def test_close_checkpoints_wal_so_a_fresh_store_sees_the_rows(tmp_path: Path) -> None:
    path = tmp_path / "r.sqlite"
    store = Store(path)
    store.migrate()
    store.upsert_case(
        CaseRow(
            mkey=1,
            ntsb_number="X",
            event_date="2026-01-01",
            regulation="091",
            status="Ongoing",
            first_seen_run=1,
            last_seen_run=1,
            last_case_run=1,
            last_docket_run=None,
            watch_until=None,
        )
    )
    store.close()

    wal_path = path.with_name(path.name + "-wal")
    assert not wal_path.exists() or wal_path.stat().st_size == 0

    reopened = Store(path)
    assert reopened.get_case(1) is not None
    reopened.close()
