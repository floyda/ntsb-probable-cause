"""The docket side of the nightly run: outcomes, the document diff, stored pages (Task 8)."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.recorder.dockets import (
    DiffResult,
    DocketOutcome,
    diff_documents,
    doc_id_of,
    observe_docket,
)
from ntsb_probable_cause.store import CaseRow, DocumentRow, Store

MKEY = 95459
SAVED = Path("tests/fixtures/docket/ERA17LA217/listing.html").read_bytes().decode("utf-8")

# The site's real answer for ProjectID 999999999, a nonexistent case (fetched 2026-09-22 by the
# controller during Task 3's live run) -- not open-split data under decision 0024, since no
# such case exists to be split. HTTP 200, no item count, no info block, and one line reading
# "The docket for this investigation has not been released." Used here only for its page text
# (never mixed with a real project id or case number): the outcome this test proves is a
# content classification, not a lookup keyed by which case the page happens to describe.
NOT_RELEASED = Path("tests/fixtures/docket/not-released.html").read_bytes().decode("utf-8")


# --- page-editing helpers: string edits of SAVED, each keeping "Docket Items: N" consistent ---

_FULL_ROW = re.compile(r"<tr>\s*<td><b>\d+</b></td>.*?</tr>", re.S)
_ROW_IDX = re.compile(r"(<tr>\s*<td><b>)(\d+)(</b></td>)", re.S)
_ITEMS_TEXT = re.compile(r"(Docket Items:\s*)(\d+)")
_ID = re.compile(r"ID=\d+")


def _rows(page: str) -> list[str]:
    """Every data row's full ``<tr>...</tr>`` text, in the order it appears on the page."""
    return _FULL_ROW.findall(page)


def _row_idx(row: str) -> int:
    match = _ROW_IDX.search(row)
    assert match is not None
    return int(match.group(2))


def _with_idx(row: str, idx: int) -> str:
    return _ROW_IDX.sub(rf"\g<1>{idx}\g<3>", row, count=1)


def _set_declared_items(page: str, n: int) -> str:
    return _ITEMS_TEXT.sub(rf"\g<1>{n}", page, count=1)


def _with_extra_row(page: str, *, doc_id: int) -> str:
    """Row 1 duplicated as one new row appended after the last, with a new document id."""
    rows = _rows(page)
    new_row = _with_idx(rows[0], len(rows) + 1)
    new_row = _ID.sub(f"ID={doc_id}", new_row, count=1)
    page = page.replace(rows[-1], rows[-1] + "\n" + new_row, 1)
    return _set_declared_items(page, len(rows) + 1)


def _without_row(page: str, *, index: int) -> str:
    """The row whose own ``#`` cell reads ``index`` removed entirely."""
    rows = _rows(page)
    row = next(r for r in rows if _row_idx(r) == index)
    page = page.replace(row, "", 1)
    return _set_declared_items(page, len(rows) - 1)


def _swap_rows(page: str, i: int, j: int) -> str:
    """Rows ``i`` and ``j``'s content traded; each row's own ``#`` cell stays put.

    This is what the real listing page looks like when the site lists two documents in a new
    order: each physical row still counts up from 1, but the document that used to be at
    position ``i`` (its title, page count, href) is now printed at position ``j`` and vice
    versa.
    """
    rows = _rows(page)
    row_i = next(r for r in rows if _row_idx(r) == i)
    row_j = next(r for r in rows if _row_idx(r) == j)
    page = page.replace(row_i, _with_idx(row_j, i), 1)
    page = page.replace(row_j, _with_idx(row_i, j), 1)
    return page


def _with_doc_id(page: str, *, index: int, doc_id: int) -> str:
    """The row at ``index``'s document id replaced; its title and page count are untouched."""
    rows = _rows(page)
    row = next(r for r in rows if _row_idx(r) == index)
    return page.replace(row, _ID.sub(f"ID={doc_id}", row, count=1), 1)


def test_with_extra_row_yields_six_entries() -> None:
    listing = parse_listing(_with_extra_row(SAVED, doc_id=40469999), mkey=MKEY)
    assert len(listing.entries) == 6
    assert listing.declared_items == 6


def test_without_row_yields_four_entries() -> None:
    listing = parse_listing(_without_row(SAVED, index=5), mkey=MKEY)
    assert len(listing.entries) == 4
    assert listing.declared_items == 4


def test_swap_rows_yields_five_entries() -> None:
    listing = parse_listing(_swap_rows(SAVED, 1, 2), mkey=MKEY)
    assert len(listing.entries) == 5
    assert listing.declared_items == 5


def test_with_doc_id_yields_five_entries() -> None:
    listing = parse_listing(_with_doc_id(SAVED, index=5, doc_id=40470000), mkey=MKEY)
    assert len(listing.entries) == 5
    assert listing.declared_items == 5


# The saved page's first row (index 1) has href ID=40469808; ADDED is that row duplicated as
# index 6 with ID=40469999 and the declared count raised from 5 to 6. REPAGED changes row 1's
# unique page count (10, the only row with that value) to 14. REMOVED drops row 5 (the Photo
# row). SWAPPED trades rows 1 and 2. RENUMBERED gives row 5 a new document id, same title and
# page count -- a suspected re-number, not a genuine disappearance-and-appearance.
ADDED = _with_extra_row(SAVED, doc_id=40469999)
REPAGED = SAVED.replace("<td><b>10</b></td>", "<td><b>14</b></td>", 1)
REMOVED = _without_row(SAVED, index=5)
SWAPPED = _swap_rows(SAVED, 1, 2)
RENUMBERED = _with_doc_id(SAVED, index=5, doc_id=40470000)
TWO_DOCS = _without_row(_without_row(_without_row(SAVED, index=5), index=4), index=3)
EMPTY = _without_row(
    _without_row(
        _without_row(_without_row(_without_row(SAVED, index=5), index=4), index=3), index=2
    ),
    index=1,
)
# Row 5's href with "ID=" swapped for a format the parser cannot find a document id in --
# everything else about the page (the info block, the declared count) is unchanged and valid.
NO_ID = SAVED.replace("ID=40469811", "REF=40469811", 1)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = Store(tmp_path / "r.sqlite")
    opened.migrate()
    # A case row, as Task 7's observe_case would already have written before the docket side
    # ever polls it (Task 9 only calls observe_docket for mkeys drawn from watched_mkeys).
    opened.upsert_case(
        CaseRow(
            mkey=MKEY,
            ntsb_number="ERA17LA217",
            event_date="2017-06-26",
            regulation="091",
            status="Ongoing",
            first_seen_run=0,
            last_seen_run=0,
            last_case_run=0,
            last_docket_run=None,
            watch_until=None,
            watched=True,
        )
    )
    yield opened
    opened.close()


@pytest.fixture
def client() -> Iterator[DocketClient]:
    # cache_dir=None: read-and-discard (decision 0061/0066). sleep is a no-op, never a zero
    # rate -- seconds_per_request stays at the real 2.0-second floor.
    opened = DocketClient(None, seconds_per_request=2.0, sleep=lambda _seconds: None)
    yield opened
    opened.close()


def _poll(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter, page: str, run_id: int
) -> DocketOutcome:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(200, text=page))
    return observe_docket(store, client, MKEY, run_id=run_id)


def _events(store: Store) -> list[tuple[str, int | None, int]]:
    rows = store.connection.execute(
        "select kind, absent_run, present_run from document_events order by id"
    ).fetchall()
    return [(str(kind), absent, int(present)) for kind, absent, present in rows]


# --- outcomes -------------------------------------------------------------------------------


def test_first_poll_records_every_document_as_appeared(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    out = _poll(store, client, respx_mock, SAVED, 1)
    assert out.outcome == "read"
    assert out.new_documents == 5
    assert out.changed
    kinds = [r[0] for r in store.connection.execute("select kind from document_events")]
    assert kinds == ["appeared"] * 5
    assert store.connection.execute("select count(*) from listing_pages").fetchone()[0] == 1
    case = store.get_case(MKEY)
    assert case is not None
    assert case.last_docket_run == 1


def test_same_page_again_writes_no_rows(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    out = _poll(store, client, respx_mock, SAVED, 2)
    assert out.outcome == "read"
    assert not out.changed
    assert len(_events(store)) == 5
    assert store.connection.execute("select count(*) from listing_pages").fetchone()[0] == 1


def test_added_row_is_one_appeared_with_interval(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    out = _poll(store, client, respx_mock, ADDED, 2)
    assert out.new_documents == 1
    assert _events(store)[-1] == ("appeared", 1, 2)


def test_page_count_change_is_revised(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    _poll(store, client, respx_mock, REPAGED, 2)
    kind, old, new = store.connection.execute(
        "select kind, old_json, new_json from document_events order by id desc limit 1"
    ).fetchone()
    assert kind == "revised"
    assert json.loads(old)["pages"] == 10
    assert json.loads(new)["pages"] == 14


def test_removed_row_is_disappeared_and_kept(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    _poll(store, client, respx_mock, REMOVED, 2)
    assert _events(store)[-1] == ("disappeared", 1, 2)
    assert len(store.documents_for(MKEY)) == 5  # the row is kept
    gone = [r for r in store.documents_for(MKEY).values() if r.gone_present_run == 2]
    assert len(gone) == 1


def test_swapped_rows_are_no_event(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    out = _poll(store, client, respx_mock, SWAPPED, 2)
    assert not out.changed
    assert len(_events(store)) == 5
    assert store.documents_for(MKEY)[40469808].position == 2


def test_renumbered_pair_is_counted(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    out = _poll(store, client, respx_mock, RENUMBERED, 2)
    assert out.suspected_renumbers == 1
    last_two = {e[0] for e in _events(store)[-2:]}
    assert last_two == {"disappeared", "appeared"}


def test_no_info_block_is_failed_not_read(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    out = _poll(store, client, respx_mock, "<html>Docket Items: 0</html>", 2)
    assert out.outcome == "failed"
    assert not out.changed
    assert len(_events(store)) == 5  # nothing recorded as disappeared
    reason = store.connection.execute("select reason from docket_polls where run_id=2").fetchone()[
        0
    ]
    assert reason == "no-info-block"


def test_count_mismatch_is_failed(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    bad = SAVED.replace("Docket Items: 5", "Docket Items: 6", 1)
    out = _poll(store, client, respx_mock, bad, 1)
    assert out.outcome == "failed"
    assert out.failed == "count-mismatch"
    reason = store.connection.execute("select reason from docket_polls where run_id=1").fetchone()[
        0
    ]
    assert reason == "count-mismatch"
    # the page is still stored -- it is exactly what a later re-parse needs (spec §6.4).
    assert store.connection.execute("select count(*) from listing_pages").fetchone()[0] == 1


def test_empty_outcome_when_info_block_present_but_no_rows(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    out = _poll(store, client, respx_mock, EMPTY, 1)
    assert out.outcome == "empty"
    assert not out.changed
    assert store.documents_for(MKEY) == {}


def test_entry_without_id_fails_the_whole_poll(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    out = _poll(store, client, respx_mock, NO_ID, 1)
    assert out.outcome == "failed"
    assert out.failed == "entry-without-id"
    assert len(_events(store)) == 0
    assert store.documents_for(MKEY) == {}
    reason = store.connection.execute("select reason from docket_polls where run_id=1").fetchone()[
        0
    ]
    assert reason == "entry-without-id"
    # a valid docket page with one broken link is still stored whole (spec §6.4).
    assert store.connection.execute("select count(*) from listing_pages").fetchone()[0] == 1


def test_not_released_page_maps_to_no_docket(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    out = _poll(store, client, respx_mock, NOT_RELEASED, 1)
    assert out.outcome == "no-docket"
    assert out.failed is None
    case = store.get_case(MKEY)
    assert case is not None
    assert case.last_docket_run == 1
    outcome = store.connection.execute(
        "select outcome from docket_polls where run_id=1"
    ).fetchone()[0]
    assert outcome == "no-docket"


def test_no_docket_poll_updates_last_docket_run_but_never_diffs(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    """Controller change 2 (a): three no-docket nights, then a read gives new documents a real
    interval spanning them -- absent since the last no-docket run, not ``None``."""
    for run_id in (1, 2, 3):
        _poll(store, client, respx_mock, NOT_RELEASED, run_id)
    out = _poll(store, client, respx_mock, TWO_DOCS, 4)
    assert out.outcome == "read"
    assert out.new_documents == 2
    events = _events(store)
    assert len(events) == 2
    assert all(
        kind == "appeared" and absent == 3 and present == 4 for kind, absent, present in events
    )


def test_no_docket_poll_does_not_diff_or_disappear_documents(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    """Controller change 2 (b): a no-docket night between two identical reads causes nothing --
    no events, and no document is ever marked disappeared."""
    _poll(store, client, respx_mock, SAVED, 1)
    no_docket = _poll(store, client, respx_mock, NOT_RELEASED, 2)
    assert no_docket.outcome == "no-docket"
    out = _poll(store, client, respx_mock, SAVED, 3)
    assert out.outcome == "read"
    assert not out.changed
    assert len(_events(store)) == 5
    assert all(row.gone_present_run is None for row in store.documents_for(MKEY).values())


def test_failed_night_leaves_absent_run_alone(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    _poll(store, client, respx_mock, SAVED, 1)
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(500))
    out = observe_docket(store, client, MKEY, run_id=2)  # five attempts, all 500
    assert out.outcome == "failed"
    reason = store.connection.execute("select reason from docket_polls where run_id=2").fetchone()[
        0
    ]
    assert reason == "http-500-after-retries"
    _poll(store, client, respx_mock, ADDED, 3)
    assert _events(store)[-1] == ("appeared", 1, 3)  # the interval spans the failed night
    # a fetch failure never received a page, so nothing is stored for it.
    assert store.connection.execute("select count(*) from listing_pages").fetchone()[0] == 2


def test_a_non_retried_status_is_failed_with_its_own_reason(
    store: Store, client: DocketClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(404))
    out = observe_docket(store, client, MKEY, run_id=1)
    assert out.outcome == "failed"
    assert out.failed == "http-404"
    assert store.connection.execute("select count(*) from listing_pages").fetchone()[0] == 0


def test_unknown_mkey_raises(tmp_path: Path, client: DocketClient) -> None:
    bare = Store(tmp_path / "bare.sqlite")
    bare.migrate()
    with pytest.raises(ValueError, match=str(MKEY)):
        observe_docket(bare, client, MKEY, run_id=1)
    bare.close()


# --- doc_id_of and diff_documents, as pure functions -----------------------------------------


def test_doc_id_of_parses_the_href_id() -> None:
    assert doc_id_of("/Docket/Document/docBLOB?ID=40469808&FileExtension=.PDF") == 40469808


def test_doc_id_of_returns_none_without_an_id() -> None:
    assert doc_id_of("/Docket/Document/docBLOB?REF=40469808") is None


def test_diff_documents_is_pure_and_reports_the_same_shape_observe_docket_does() -> None:
    listing = parse_listing(SAVED, mkey=MKEY)
    diff = diff_documents({}, listing, mkey=MKEY, run_id=1, absent_run=None)
    assert isinstance(diff, DiffResult)
    assert len(diff.appeared) == 5
    assert diff.revised == ()
    assert diff.disappeared == ()
    assert diff.unchanged == ()
    assert diff.suspected_renumbers == 0
    assert all(row.absent_run is None and row.present_run == 1 for row in diff.appeared)


def test_diff_documents_against_a_prior_snapshot_finds_the_change() -> None:
    first = parse_listing(SAVED, mkey=MKEY)
    baseline: dict[int, DocumentRow] = {}
    for e in first.entries:
        doc_id = doc_id_of(e.href)
        assert doc_id is not None
        baseline[doc_id] = DocumentRow(
            mkey=MKEY,
            doc_id=doc_id,
            href=e.href,
            position=e.index,
            title=e.title,
            pages=e.pages,
            photos=e.photos,
            extension=e.extension,
            absent_run=None,
            present_run=1,
            last_present_run=1,
            gone_absent_run=None,
            gone_present_run=None,
        )
    second = parse_listing(REPAGED, mkey=MKEY)
    diff = diff_documents(baseline, second, mkey=MKEY, run_id=2, absent_run=1)
    assert diff.appeared == ()
    assert diff.disappeared == ()
    assert len(diff.revised) == 1
    old, new = diff.revised[0]
    assert old.pages == 10
    assert new.pages == 14
