import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause import sources
from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.live.fetch import FetchError, fetch_record, prefetch_docket, prelim_present
from ntsb_probable_cause.live.queue import QueuedCase

CASE = QueuedCase(
    mkey=7,
    case_id="XXX26LA001",
    event_date=date(2026, 9, 1),
    closed_on=date(2026, 9, 25),
    closure_run=3,
)
SAVED = Path("tests/fixtures/docket/ERA17LA217/listing.html").read_text()
NOT_RELEASED = Path("tests/fixtures/docket/not-released.html").read_text()
MKEY = 95459


def _client(transport: httpx.MockTransport) -> NtsbClient:
    return NtsbClient("k", transport=transport, sleep=lambda _s: None, max_attempts=2)


def _body(data: list[dict[str, object]], marker: str | None) -> dict[str, object]:
    return {"hasMore": marker is not None, "nextMarker": marker, "data": data}


def test_fetch_record_finds_the_case_on_a_later_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "marker" in request.url.params:
            return httpx.Response(200, json=_body([{"mKey": 7, "ntsbNumber": "XXX26LA001"}], None))
        return httpx.Response(200, json=_body([{"mKey": 6}], "m2"))

    with _client(httpx.MockTransport(handler)) as client:
        record = fetch_record(client, CASE)
    assert record["ntsbNumber"] == "XXX26LA001"


def test_fetch_record_missing_record_is_a_fetch_error() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json=_body([{"mKey": 6}], None)))
    with _client(transport) as client, pytest.raises(FetchError, match="no record"):
        fetch_record(client, CASE)


def test_fetch_record_api_error_is_a_fetch_error() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(401, text="no"))
    with _client(transport) as client, pytest.raises(FetchError, match="401"):
        fetch_record(client, CASE)


def test_prelim_present() -> None:
    assert prelim_present({"narratives": [{"prelimNarrative": "The airplane..."}]})
    assert not prelim_present({"narratives": [{"prelimNarrative": "  "}]})
    assert not prelim_present({"narratives": [{}]})
    assert not prelim_present({})


def _docket_client(tmp_path: Path) -> DocketClient:
    return DocketClient(tmp_path, sleep=lambda _s: None, max_attempts=2, backoff_seconds=0.0)


def _serve_listing(respx_mock: respx.MockRouter, page: str) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(200, text=page))


def test_a_docket_with_failing_documents_reports_fetch_failed(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    _serve_listing(respx_mock, SAVED)
    respx_mock.get(url__startswith=sources.DOCKET_BASE_URL + "/Docket/Document").mock(
        return_value=httpx.Response(404)
    )
    with _docket_client(tmp_path) as client:
        docket = prefetch_docket(client, MKEY, known_documents=0)
    assert len(docket.documents) == len(parse_listing(SAVED, mkey=MKEY).entries)
    fetched = [d for d in docket.documents if d.entry.is_pdf() and not d.entry.is_photo_only()]
    assert fetched
    assert {d.status for d in fetched} == {"fetch failed"}


def test_not_released_page_is_a_docket_with_no_entries(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    _serve_listing(respx_mock, NOT_RELEASED)
    with _docket_client(tmp_path) as client:
        docket = prefetch_docket(client, MKEY, known_documents=0)
    assert docket.listing.entries == ()
    assert docket.documents == ()
    assert docket.texts == {}


def test_a_404_listing_is_a_docket_with_no_entries(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(404))
    with _docket_client(tmp_path) as client:
        assert prefetch_docket(client, MKEY, known_documents=0).documents == ()


def test_a_404_for_a_case_the_store_saw_documents_for_is_a_fetch_error(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(404))
    with _docket_client(tmp_path) as client, pytest.raises(FetchError, match="3 documents"):
        prefetch_docket(client, MKEY, known_documents=3)


def test_not_released_for_a_case_the_store_saw_documents_for_is_a_fetch_error(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    _serve_listing(respx_mock, NOT_RELEASED)
    with _docket_client(tmp_path) as client, pytest.raises(FetchError, match=str(MKEY)):
        prefetch_docket(client, MKEY, known_documents=3)


def test_a_normal_listing_ignores_known_documents(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    _serve_listing(respx_mock, SAVED)
    respx_mock.get(url__startswith=sources.DOCKET_BASE_URL + "/Docket/Document").mock(
        return_value=httpx.Response(404)
    )
    with _docket_client(tmp_path) as client:
        assert prefetch_docket(client, MKEY, known_documents=3).documents


@pytest.mark.parametrize("status", [500, 503, 429])
def test_a_site_that_keeps_failing_is_a_fetch_error(
    status: int, tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(status))
    with _docket_client(tmp_path) as client, pytest.raises(FetchError, match="after-retries"):
        prefetch_docket(client, MKEY, known_documents=0)


def test_a_transport_failure_is_a_fetch_error(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(side_effect=httpx.ConnectError("down"))
    with _docket_client(tmp_path) as client, pytest.raises(FetchError, match="fetch-failed"):
        prefetch_docket(client, MKEY, known_documents=0)


def test_a_non_retried_error_status_is_a_fetch_error(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(403))
    with _docket_client(tmp_path) as client, pytest.raises(FetchError, match="http-403"):
        prefetch_docket(client, MKEY, known_documents=0)


def test_a_page_with_no_info_block_is_not_no_docket(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    _serve_listing(respx_mock, "<html><body>The layout changed.</body></html>")
    with _docket_client(tmp_path) as client, pytest.raises(FetchError, match="no-info-block"):
        prefetch_docket(client, MKEY, known_documents=0)


def test_a_count_mismatch_is_a_fetch_error(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    _serve_listing(respx_mock, SAVED.replace("Docket Items: 5", "Docket Items: 6", 1))
    with _docket_client(tmp_path) as client, pytest.raises(FetchError, match="declared 6"):
        prefetch_docket(client, MKEY, known_documents=0)


def test_documents_are_cached_only_where_the_client_was_told(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    _serve_listing(respx_mock, SAVED)
    respx_mock.get(url__startswith=sources.DOCKET_BASE_URL + "/Docket/Document").mock(
        return_value=httpx.Response(404)
    )
    cache = tmp_path / "live-docket"
    with DocketClient(cache, sleep=lambda _s: None, max_attempts=1) as client:
        prefetch_docket(client, MKEY, known_documents=0)
    assert [p.name for p in tmp_path.iterdir()] == ["live-docket"]
    assert json.loads((cache / str(MKEY) / "fetch.json").read_text())
