"""The docket client: polite fetching, a cache keyed by case, read-and-discard (spec §4.2)."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import DocketError

MKEY = 73612
LISTING_URL = sources.docket_url(MKEY)
HREF = "/Docket/Document/docBLOB?ID=1&FileExtension=.pdf&FileName=a.pdf"
PAGE = "<html>Docket Items: 0</html>"


def _client(tmp_path: Path | None, sleeps: list[float]) -> DocketClient:
    return DocketClient(tmp_path, seconds_per_request=2.0, sleep=sleeps.append)


def test_listing_is_fetched_once_and_cached(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    sleeps: list[float] = []
    with _client(tmp_path, sleeps) as client:
        assert client.listing_html(MKEY) == PAGE
        assert client.listing_html(MKEY) == PAGE
    assert route.call_count == 1
    assert (tmp_path / str(MKEY) / "listing.html").read_text() == PAGE
    fetch = json.loads((tmp_path / str(MKEY) / "fetch.json").read_text())
    assert fetch["listing"]["sha256"] == hashlib.sha256(PAGE.encode()).hexdigest()


def test_document_is_cached_by_index(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 x")
    )
    with _client(tmp_path, []) as client:
        assert client.document(MKEY, 3, HREF) == b"%PDF-1.4 x"
        assert client.document(MKEY, 3, HREF) == b"%PDF-1.4 x"
    assert route.call_count == 1
    assert (tmp_path / str(MKEY) / "3.bin").read_bytes() == b"%PDF-1.4 x"


def test_requests_are_two_seconds_apart(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, content=b"x")
    )
    sleeps: list[float] = []
    with _client(tmp_path, sleeps) as client:
        client.listing_html(MKEY)
        client.document(MKEY, 1, HREF)
    assert sleeps == [2.0]  # no sleep before the first request, one between the two


def test_user_agent_names_the_project(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    with _client(tmp_path, []) as client:
        client.listing_html(MKEY)
    assert route.calls[0].request.headers["user-agent"] == sources.DOCKET_USER_AGENT


def test_read_and_discard_writes_nothing(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    """Decision 0040: the open-split shape script keeps no documents."""
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    with _client(None, []) as client:
        assert client.listing_html(MKEY) == PAGE
    assert list(tmp_path.iterdir()) == []


def test_server_error_is_retried_then_raised(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(503))
    sleeps: list[float] = []
    with (
        DocketClient(tmp_path, sleep=sleeps.append, max_attempts=3, backoff_seconds=1.0) as client,
        pytest.raises(DocketError, match="503"),
    ):
        client.listing_html(MKEY)
    assert sleeps == [1.0, 1.0, 2.0]


def test_not_found_is_not_retried(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(404))
    with _client(tmp_path, []) as client, pytest.raises(DocketError, match="404"):
        client.listing_html(MKEY)
    assert route.call_count == 1
