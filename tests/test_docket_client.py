"""The docket client: polite fetching, a cache keyed by case, read-and-discard (spec §4.2)."""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.client import DocketClient, cached_hashes
from ntsb_probable_cause.errors import ConfigurationError, DocketError

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


def test_read_and_discard_writes_nothing(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 0040: the open-split shape script keeps no documents.

    ``cache_dir=None`` alone made the original version of this test pass vacuously: nothing
    the client could write would ever land under ``tmp_path``, so the assertion held even if
    the client wrote somewhere else entirely. Chdir into ``tmp_path`` so a real leak -- to a
    relative path, say -- would be caught (fix round 1, Finding 6).
    """
    monkeypatch.chdir(tmp_path)
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, content=b"x")
    )
    with _client(None, []) as client:
        assert client.listing_html(MKEY) == PAGE
        assert client.document(MKEY, 1, HREF) == b"x"
    assert list(tmp_path.rglob("*")) == []


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


def test_a_changed_href_at_the_same_index_is_not_served_from_the_stale_cache(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    """Fix round 1, Finding 2: an index alone does not identify a document.

    A docket gains documents over time and the listing order can shift, so index 3 today
    may not be index 3's document from an earlier fetch. A cache hit must also match the
    href.
    """
    old_href = HREF
    new_href = "/Docket/Document/docBLOB?ID=9&FileExtension=.pdf&FileName=b.pdf"
    old_route = respx_mock.get(sources.docket_document_url(old_href)).mock(
        return_value=httpx.Response(200, content=b"old bytes")
    )
    new_route = respx_mock.get(sources.docket_document_url(new_href)).mock(
        return_value=httpx.Response(200, content=b"new bytes")
    )
    with _client(tmp_path, []) as client:
        assert client.document(MKEY, 3, old_href) == b"old bytes"
        assert client.document(MKEY, 3, new_href) == b"new bytes"
    assert old_route.call_count == 1
    assert new_route.call_count == 1
    assert (tmp_path / str(MKEY) / "3.bin").read_bytes() == b"new bytes"
    fetch = json.loads((tmp_path / str(MKEY) / "fetch.json").read_text())
    assert fetch["documents"]["3"]["href"] == new_href


def test_a_truncated_file_is_not_served_as_complete(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    """Fix round 1, Finding 3: a kill mid-write must not be read back as a good file.

    The write path never leaves a truncated file at the final name, but this pins the read
    side against one anyway -- by hand, mimicking disk corruption or an out-of-band edit
    rather than the client's own crash.
    """
    full_content = b"%PDF-1.4 0123456789"
    route = respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, content=full_content)
    )
    with _client(tmp_path, []) as client:
        assert client.document(MKEY, 5, HREF) == full_content
        # fetch.json still records the full file's hash; truncate the bytes on disk to
        # simulate a partial write that a reader must not trust.
        (tmp_path / str(MKEY) / "5.bin").write_bytes(full_content[:10])
        assert client.document(MKEY, 5, HREF) == full_content
    assert route.call_count == 2
    assert (tmp_path / str(MKEY) / "5.bin").read_bytes() == full_content


def test_two_documents_are_both_kept_in_the_manifest(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    """Fix round 1, Finding 5: the merge path every multi-document docket takes from doc 2 on."""
    href_a = HREF
    href_b = "/Docket/Document/docBLOB?ID=2&FileExtension=.pdf&FileName=b.pdf"
    respx_mock.get(sources.docket_document_url(href_a)).mock(
        return_value=httpx.Response(200, content=b"document a")
    )
    respx_mock.get(sources.docket_document_url(href_b)).mock(
        return_value=httpx.Response(200, content=b"document b")
    )
    with _client(tmp_path, []) as client:
        assert client.document(MKEY, 1, href_a) == b"document a"
        assert client.document(MKEY, 2, href_b) == b"document b"
    fetch = json.loads((tmp_path / str(MKEY) / "fetch.json").read_text())
    assert fetch["documents"]["1"]["href"] == href_a
    assert fetch["documents"]["1"]["sha256"] == hashlib.sha256(b"document a").hexdigest()
    assert fetch["documents"]["2"]["href"] == href_b
    assert fetch["documents"]["2"]["sha256"] == hashlib.sha256(b"document b").hexdigest()


def test_cached_hashes_read_back_what_was_recorded(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(LISTING_URL).mock(return_value=httpx.Response(200, text=PAGE))
    respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 x")
    )
    assert cached_hashes(tmp_path, MKEY) == (None, {})
    with _client(tmp_path, []) as client:
        client.listing_html(MKEY)
        client.document(MKEY, 2, HREF)
    assert cached_hashes(tmp_path, MKEY) == (
        hashlib.sha256(PAGE.encode()).hexdigest(),
        {2: hashlib.sha256(b"%PDF-1.4 x").hexdigest()},
    )


class _Pieces(httpx.SyncByteStream):
    """A response body that arrives in pieces, and may fail after the first (decision 0217)."""

    def __init__(self, pieces: list[bytes], *, fail_after_first: bool = False) -> None:
        self._pieces = pieces
        self._fail = fail_after_first

    def __iter__(self) -> Iterator[bytes]:
        for n, piece in enumerate(self._pieces):
            if self._fail and n == 1:
                raise httpx.ReadError("connection dropped")
            yield piece


def test_document_file_streams_into_the_cache(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    """Decision 0217: a document goes to disk in pieces, never whole into memory."""
    pieces = [b"%PDF-1.4 ", b"a" * 70_000, b" tail"]
    route = respx_mock.get(sources.docket_document_url(HREF)).mock(
        return_value=httpx.Response(200, stream=_Pieces(pieces))
    )
    with _client(tmp_path, []) as client:
        path = client.document_file(MKEY, 4, HREF)
        assert path == tmp_path / str(MKEY) / "4.bin"
        assert path.read_bytes() == b"".join(pieces)
        assert client.document(MKEY, 4, HREF) == b"".join(pieces)  # a cache hit, same bytes
    assert route.call_count == 1
    assert not list((tmp_path / str(MKEY)).glob("*.partial"))
    fetch = json.loads((tmp_path / str(MKEY) / "fetch.json").read_text())
    assert fetch["documents"]["4"] == {
        "href": HREF,
        "sha256": hashlib.sha256(b"".join(pieces)).hexdigest(),
        "time": fetch["documents"]["4"]["time"],
    }


def test_a_dropped_stream_is_retried_and_leaves_no_file(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(sources.docket_document_url(HREF)).mock(
        side_effect=[
            httpx.Response(200, stream=_Pieces([b"%PDF", b"-1.4"], fail_after_first=True)),
            httpx.Response(200, stream=_Pieces([b"%PDF", b"-1.4"])),
        ]
    )
    with _client(tmp_path, []) as client:
        assert client.document_file(MKEY, 1, HREF).read_bytes() == b"%PDF-1.4"


def test_a_stream_that_never_completes_leaves_nothing_behind(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(sources.docket_document_url(HREF)).mock(
        side_effect=lambda _request: httpx.Response(
            200, stream=_Pieces([b"%PDF", b"-1.4"], fail_after_first=True)
        )
    )
    with _client(tmp_path, []) as client, pytest.raises(DocketError, match="last status ReadError"):
        client.document_file(MKEY, 1, HREF)
    folder = tmp_path / str(MKEY)
    assert not folder.exists() or not [p for p in folder.iterdir() if p.name != "fetch.json"]


def test_document_file_needs_a_cache() -> None:
    """A read-and-discard client (decision 0040) writes nothing, so it has no file to give."""
    with _client(None, []) as client, pytest.raises(ConfigurationError, match="cache"):
        client.document_file(MKEY, 1, HREF)
