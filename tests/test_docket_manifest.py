"""read_docket: every document gets a status; text is kept only for read documents (spec §5.3)."""

import io
import json
from pathlib import Path

import httpx
import respx
from pypdf import PdfWriter

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.docket.manifest import read_docket

FIXTURES = Path("tests/fixtures/docket")


def _first_fixture() -> tuple[Path, int]:
    folder = sorted(p for p in FIXTURES.iterdir() if p.is_dir())[0]
    return folder, int(json.loads((folder / "manifest.json").read_text())["fixture"]["mkey"])


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_every_entry_gets_a_status_and_scans_keep_no_text(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    listing = parse_listing(page, mkey=mkey)
    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    for entry in listing.entries:
        if entry.href:
            respx_mock.get(sources.docket_document_url(entry.href)).mock(
                return_value=httpx.Response(200, content=_blank_pdf())
            )
    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey)
    assert len(docket.documents) == len(listing.entries)
    for record in docket.documents:
        if record.entry.is_photo_only():
            assert record.status == "skipped: photo-only"
        elif not record.entry.is_pdf():
            assert record.status == "unreadable: not a pdf"
        else:
            assert record.status == "unreadable: scan"  # a blank page is a scan
            assert record.kind == "scan"
            assert record.readable_pages == 0
    assert docket.texts == {}


def test_fetch_failure_is_a_status_not_an_exception(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    respx_mock.get(url__startswith=sources.DOCKET_BASE_URL + "/Docket/Document").mock(
        return_value=httpx.Response(404)
    )
    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey)
    assert {
        r.status for r in docket.documents if r.entry.is_pdf() and not r.entry.is_photo_only()
    } == {"fetch failed"}


def test_denied_category_is_never_fetched(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    route = respx_mock.get(url__startswith=sources.DOCKET_BASE_URL + "/Docket/Document").mock(
        return_value=httpx.Response(200, content=_blank_pdf())
    )
    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey, denied=lambda _category: True)
    assert all(
        r.status in {"denied: write-up", "skipped: photo-only", "unreadable: not a pdf"}
        for r in docket.documents
    )
    assert route.call_count == 0
