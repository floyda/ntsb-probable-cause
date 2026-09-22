"""The nightly pass: orchestration, summary, logging (spec S2.5 §9.1, Task 9)."""

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from tests.boundary import as_ongoing

from ntsb_probable_cause import sources
from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.recorder import run as run_module
from ntsb_probable_cause.recorder.dockets import DocketOutcome
from ntsb_probable_cause.recorder.run import NightInputs, run_night
from ntsb_probable_cause.store import CaseRow, Store

MONTH_URL = "https://api.ntsb.gov/public/api/Common/v2/GetCasesByDateRange/"
FEED_URL = "https://api.ntsb.gov/public/api/Common/v1/GetCasesByModifiedDateRange/"

MKEY_1 = 95459
MKEY_2 = 95460

SAVED = Path("tests/fixtures/docket/ERA17LA217/listing.html").read_bytes().decode("utf-8")
NOT_RELEASED = Path("tests/fixtures/docket/not-released.html").read_bytes().decode("utf-8")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = Store(tmp_path / "r.sqlite")
    opened.migrate()
    yield opened
    opened.close()


def _seed_case(store: Store, mkey: int, event_date: str) -> None:
    """A watched, ``Ongoing`` case row, as if a previous night's ``observe_case`` wrote it --
    so ``month_window`` picks a single, known month instead of falling back to the walk-back.
    """
    store.upsert_case(
        CaseRow(
            mkey=mkey,
            ntsb_number=f"REC{mkey}",
            event_date=event_date,
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


def _ongoing(
    record_fixtures: list[dict[str, object]], mkey: int, event_date: str
) -> dict[str, object]:
    """A development fixture record, edited to read like a live ``Ongoing`` case with ``mkey``
    and ``event_date`` of the caller's choosing (``tests/boundary.py:as_ongoing`` does the
    synthesis/verdict stripping)."""
    raw = next(
        r for r in record_fixtures if isinstance(r.get("mKey"), int) and r.get("mode") == "Aviation"
    )
    record = as_ongoing(
        raw, prelim_text="Preliminary information indicates the flight departed on a local flight."
    )
    record["mKey"] = mkey
    record["ntsbNumber"] = f"REC{mkey}"
    record["eventDate"] = event_date
    return record


def _month_body(
    records: list[dict[str, object]], *, has_more: bool = False, marker: str | None = None
) -> dict[str, object]:
    return {"hasMore": has_more, "nextMarker": marker, "data": records}


def _inputs(store: Store, moment: datetime) -> NightInputs:
    return NightInputs(
        api=NtsbClient("k", sleep=lambda _seconds: None),
        docket=DocketClient(None, seconds_per_request=2.0, sleep=lambda _seconds: None),
        store=store,
        now=lambda: moment,
        commit_sha="abc1234",
        dirty=False,
    )


def _table_counts(store: Store) -> dict[str, int]:
    tables = (
        "runs",
        "cases",
        "status_events",
        "field_snapshots",
        "prelim_narratives",
        "docket_polls",
        "listing_pages",
        "documents",
        "document_events",
        "change_feed",
    )
    return {
        table: store.connection.execute(f"select count(*) from {table}").fetchone()[0]  # noqa: S608
        for table in tables
    }


def test_a_night_writes_summary_and_rows(
    store: Store, record_fixtures: list[dict[str, object]], respx_mock: respx.MockRouter
) -> None:
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    _seed_case(store, MKEY_2, event_date)

    # A record that is neither watchable (wrong mode) nor already known to the store: skipped
    # before it is ever split.
    unwatched = _ongoing(record_fixtures, 111111, event_date)
    unwatched["mode"] = "Railroad"
    # A record that IS watchable but carries no usable `mKey`: `observe_case` fails on it, and
    # the failure is counted -- it is never mistaken for a case actually seen this month.
    no_mkey = _ongoing(record_fixtures, 222222, event_date)
    del no_mkey["mKey"]

    records = [
        _ongoing(record_fixtures, MKEY_1, event_date),
        _ongoing(record_fixtures, MKEY_2, event_date),
        unwatched,
        no_mkey,
    ]
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(200, json=_month_body(records)))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(return_value=httpx.Response(200, text=SAVED))
    # A page with no "Docket Information" block: a failed docket poll ("no-info-block"), not a
    # raised exception -- `DocketOutcome.failed` is set and counted, the loop keeps going.
    respx_mock.get(sources.docket_url(MKEY_2)).mock(
        return_value=httpx.Response(200, text="<html>Docket Items: 0</html>")
    )

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    assert summary.cases_polled == 2
    assert summary.new_documents == 5
    assert summary.failures == 2  # the no-mKey record, and MKEY_2's malformed docket page
    assert inputs.store.last_run_id() == 1
    assert store.get_case(111111) is None


def test_same_night_twice_is_idempotent(
    store: Store, record_fixtures: list[dict[str, object]], respx_mock: respx.MockRouter
) -> None:
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    _seed_case(store, MKEY_2, event_date)
    records = [
        _ongoing(record_fixtures, MKEY_1, event_date),
        _ongoing(record_fixtures, MKEY_2, event_date),
    ]
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(200, json=_month_body(records)))
    # A non-empty feed: `change_feed` is a deliberate exception to the store's usual
    # idempotence (fix round 1, Minor 1) -- it is asserted below to GROW each night, not stay
    # put, because the 2-day lookback window overlaps between nights on purpose.
    feed_payload = [
        {
            "mkey": MKEY_1,
            "mode": "Aviation",
            "lastChangeDateTimeUtc": "2026-09-30T10:00:00Z",
            "stepNumber": 3,
            "stepId": "step-3",
            "caseClosed": False,
        }
    ]
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=feed_payload))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(return_value=httpx.Response(200, text=SAVED))
    respx_mock.get(sources.docket_url(MKEY_2)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    run_night(inputs)
    counts = _table_counts(store)
    run_night(inputs)
    again = _table_counts(store)

    assert again["runs"] == counts["runs"] + 1
    assert again["docket_polls"] == counts["docket_polls"] + 2
    assert again["change_feed"] == counts["change_feed"] + len(feed_payload)
    for table in ("field_snapshots", "document_events", "listing_pages", "status_events"):
        assert again[table] == counts[table]


def test_api_outage_still_polls_dockets(store: Store, respx_mock: respx.MockRouter) -> None:
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    _seed_case(store, MKEY_2, event_date)
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(500))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(return_value=httpx.Response(200, text=SAVED))
    respx_mock.get(sources.docket_url(MKEY_2)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    assert summary.failures == 1  # exactly the one failed month; both docket polls succeed
    assert store.connection.execute("select count(*) from docket_polls").fetchone()[0] == 2


def test_a_watched_case_in_a_failed_month_is_not_marked_not_returned(
    store: Store, respx_mock: respx.MockRouter
) -> None:
    """Controller resolution 1: a failed month is never evidence of absence -- a watched case
    whose event month's fetch returned 500 x5 must not get a "not returned" status event."""
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(500))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    run_night(inputs)

    case = store.get_case(MKEY_1)
    assert case is not None
    assert case.status == "Ongoing"
    assert store.connection.execute("select count(*) from status_events").fetchone()[0] == 0


def test_mid_month_failure_keeps_earlier_pages_and_skips_not_returned_for_the_month(
    store: Store, record_fixtures: list[dict[str, object]], respx_mock: respx.MockRouter
) -> None:
    """Fix round 1, Minor 3: page 1 (hasMore) succeeds and its record's rows stand; page 2
    fails 500 x5. The watched case that would only have appeared on page 2 gets NO
    "not returned" event, and the whole month counts as exactly one failure."""
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)  # appears on page 1
    _seed_case(store, MKEY_2, event_date)  # would appear on page 2, which never arrives
    record_1 = _ongoing(record_fixtures, MKEY_1, event_date)

    respx_mock.get(MONTH_URL).mock(
        side_effect=[
            httpx.Response(200, json=_month_body([record_1], has_more=True, marker="m1")),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
        ]
    )
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )
    respx_mock.get(sources.docket_url(MKEY_2)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    assert summary.failures == 1  # one failure for the whole month, not per page or per retry
    assert store.latest_snapshots(MKEY_1)  # page 1's record was observed and stood
    case_2 = store.get_case(MKEY_2)
    assert case_2 is not None
    assert case_2.status == "Ongoing"
    assert store.connection.execute("select count(*) from status_events").fetchone()[0] == 0


def test_two_nights_not_returned_writes_exactly_one_status_event(
    store: Store, respx_mock: respx.MockRouter
) -> None:
    """Fix round 1, Minor 3: once a case reads "not returned", a second night must not fire
    `mark_not_returned` again for it -- `_ongoing_by_month` only ever groups cases whose stored
    status still reads `Ongoing`."""
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(200, json=_month_body([])))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    run_night(_inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC)))
    run_night(_inputs(store, datetime(2026, 10, 2, 3, 0, 0, tzinfo=UTC)))

    assert store.connection.execute("select count(*) from status_events").fetchone()[0] == 1


def test_feed_rows_are_aviation_only(
    store: Store, record_fixtures: list[dict[str, object]], respx_mock: respx.MockRouter
) -> None:
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    respx_mock.get(MONTH_URL).mock(
        return_value=httpx.Response(
            200, json=_month_body([_ongoing(record_fixtures, MKEY_1, event_date)])
        )
    )
    respx_mock.get(sources.docket_url(MKEY_1)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )
    respx_mock.get(FEED_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "mkey": MKEY_1,
                    "mode": "Aviation",
                    "lastChangeDateTimeUtc": "2026-09-30T10:00:00Z",
                    "stepNumber": 3,
                    "stepId": "step-3",
                    "caseClosed": False,
                },
                {"mkey": 999, "mode": "Railroad", "lastChangeDateTimeUtc": "2026-09-30T10:00:00Z"},
                {"mkey": 777, "mode": "Aviation"},  # missing lastChangeDateTimeUtc: skipped
            ],
        )
    )

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    run_night(inputs)

    rows = store.connection.execute("select mkey, step_id, case_closed from change_feed").fetchall()
    assert rows == [(MKEY_1, "step-3", 0)]


def test_first_run_uses_the_walk_back(
    store: Store, record_fixtures: list[dict[str, object]], respx_mock: respx.MockRouter
) -> None:
    """Empty store: ``month_window`` returns ``None``, so the walk-back runs instead. A record
    in the current month plus twelve consecutive empty months means thirteen months fetched."""
    event_date = "2026-10-15"
    record = _ongoing(record_fixtures, MKEY_1, event_date)

    def _month_response(request: httpx.Request) -> httpx.Response:
        start = request.url.params["startDate"]
        records = [record] if start == "2026-10-01" else []
        return httpx.Response(200, json=_month_body(records))

    route = respx_mock.get(MONTH_URL).mock(side_effect=_month_response)
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    inputs = _inputs(store, datetime(2026, 10, 22, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    assert len(route.calls) == 13  # the watched month, plus twelve consecutive empty months
    case = store.get_case(MKEY_1)
    assert case is not None
    assert case.status == "Ongoing"
    assert summary.cases_polled == 1


def test_first_run_walk_failure_skips_case_side_but_still_polls_dockets(
    store: Store, respx_mock: respx.MockRouter
) -> None:
    """Controller resolution 2: a failed first-run walk is one failure, no case-side writes for
    the night, and the docket side still polls whatever the (here, empty) store holds."""
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(500))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))

    inputs = _inputs(store, datetime(2026, 10, 22, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    assert summary.failures == 1
    assert summary.cases_polled == 0
    assert store.connection.execute("select count(*) from cases").fetchone()[0] == 0


def test_docket_poll_for_an_mkey_with_no_case_row_is_one_failure_not_a_crash(
    store: Store,
    record_fixtures: list[dict[str, object]],
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix round 1, Important 1: the "unknown mkey" case is an explicit check on
    ``store.get_case(mkey) is None`` made before ``observe_docket`` is ever called, not a caught
    ``ValueError`` -- there is no natural way to produce a `watched_mkeys()`-sourced mkey with
    no `cases` row, so `watched_mkeys` itself is monkeypatched to return one."""
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    records = [_ongoing(record_fixtures, MKEY_1, event_date)]
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(200, json=_month_body(records)))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    real_watched_mkeys = store.watched_mkeys
    unknown_mkey = 424242

    def _with_an_unknown_mkey(*, today: str) -> list[int]:
        return [*real_watched_mkeys(today=today), unknown_mkey]

    monkeypatch.setattr(store, "watched_mkeys", _with_an_unknown_mkey)

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    assert summary.failures == 1
    assert summary.cases_polled == 2  # the unknown mkey is one attempted poll too
    assert store.connection.execute("select count(*) from docket_polls").fetchone()[0] == 1


def test_valueerror_inside_observe_docket_for_a_known_mkey_propagates(
    store: Store,
    record_fixtures: list[dict[str, object]],
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix round 1, Important 1: only the explicit "no cases row" check is ever absorbed as one
    failure -- a `ValueError` raised inside `observe_docket` for an mkey the store DOES know
    (a real bug, not the documented unknown-mkey case; a pydantic `ValidationError` or a
    `UnicodeDecodeError` both subclass `ValueError`) must fail the run loudly."""
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    records = [_ongoing(record_fixtures, MKEY_1, event_date)]
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(200, json=_month_body(records)))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))

    def _broken(store_arg: Store, client: DocketClient, mkey: int, *, run_id: int) -> DocketOutcome:
        raise ValueError("boom: a real bug, not an unknown mkey")

    monkeypatch.setattr("ntsb_probable_cause.recorder.run.observe_docket", _broken)

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="boom"):
        run_night(inputs)


def test_feed_failure_still_polls_dockets(
    store: Store, record_fixtures: list[dict[str, object]], respx_mock: respx.MockRouter
) -> None:
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    respx_mock.get(MONTH_URL).mock(
        return_value=httpx.Response(
            200, json=_month_body([_ongoing(record_fixtures, MKEY_1, event_date)])
        )
    )
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(500))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(return_value=httpx.Response(200, text=SAVED))

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    assert summary.failures == 1  # exactly the failed feed call; the case and docket succeed
    assert summary.cases_polled == 1
    assert summary.new_documents == 5
    assert store.connection.execute("select count(*) from change_feed").fetchone()[0] == 0


def test_verbose_sets_the_recorder_logger_to_debug(
    store: Store, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(500))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    logger = logging.getLogger("ntsb_probable_cause.recorder")
    monkeypatch.setattr(logger, "level", logging.WARNING)

    inputs = _inputs(store, datetime(2026, 10, 22, 3, 0, 0, tzinfo=UTC))
    run_night(inputs, verbose=True)

    assert logger.level == logging.DEBUG


def test_night_inputs_now_must_be_aware(store: Store, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(500))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    inputs = NightInputs(
        api=NtsbClient("k", sleep=lambda _seconds: None),
        docket=DocketClient(None, seconds_per_request=2.0, sleep=lambda _seconds: None),
        store=store,
        now=lambda: datetime(2026, 10, 22, 3, 0, 0),  # deliberately naive
        commit_sha="abc1234",
        dirty=False,
    )
    with pytest.raises(AssertionError):
        run_night(inputs)


def test_minutes_is_the_injected_clocks_elapsed_time(
    store: Store, respx_mock: respx.MockRouter
) -> None:
    """Independent of exactly how many times `run_night` calls `now()` (fix round 1, Minor 3):
    the clock advances by one second on every call, and the expected minutes are computed from
    the actual first and last values it returned, not from a fixed call count."""
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(500))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))

    calls: list[datetime] = []

    def _clock() -> datetime:
        moment = datetime(2026, 10, 22, 3, 0, 0, tzinfo=UTC) + timedelta(seconds=len(calls))
        calls.append(moment)
        return moment

    inputs = NightInputs(
        api=NtsbClient("k", sleep=lambda _seconds: None),
        docket=DocketClient(None, seconds_per_request=2.0, sleep=lambda _seconds: None),
        store=store,
        now=_clock,
        commit_sha="abc1234",
        dirty=False,
    )
    summary = run_night(inputs)

    assert len(calls) >= 2
    expected_minutes = (calls[-1] - calls[0]).total_seconds() / 60
    assert summary.minutes == pytest.approx(expected_minutes)
    assert summary.minutes > 0


def test_ongoing_by_month_excludes_a_watched_tail_case(store: Store) -> None:
    """A case kept in the watch set only by its 30-day tail -- its stored status is something
    other than `Ongoing` -- must never be a candidate for `mark_not_returned`: only a case
    whose stored status genuinely reads `Ongoing` right now can "stop appearing" from it."""
    store.upsert_case(
        CaseRow(
            mkey=MKEY_1,
            ntsb_number="REC1",
            event_date="2026-09-01",
            regulation="091",
            status="Completed",
            first_seen_run=1,
            last_seen_run=1,
            last_case_run=1,
            last_docket_run=None,
            watch_until="2026-10-30",
            watched=True,
        )
    )
    grouped = run_module._ongoing_by_month(store, date(2026, 10, 1))
    assert grouped == {}


def test_watched_case_that_stopped_appearing_is_marked_not_returned(
    store: Store, record_fixtures: list[dict[str, object]], respx_mock: respx.MockRouter
) -> None:
    event_date = "2026-10-15"
    _seed_case(store, MKEY_1, event_date)
    respx_mock.get(MONTH_URL).mock(return_value=httpx.Response(200, json=_month_body([])))
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(sources.docket_url(MKEY_1)).mock(
        return_value=httpx.Response(200, text=NOT_RELEASED)
    )

    inputs = _inputs(store, datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    summary = run_night(inputs)

    case = store.get_case(MKEY_1)
    assert case is not None
    assert case.status == "not returned"
    assert case.watch_until == date(2026, 10, 31).isoformat()
    assert summary.cases_changed >= 1
