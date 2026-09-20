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


def _text_pdf(page_texts: list[bytes]) -> bytes:
    """A synthetic, hand-assembled PDF whose pages draw real, exactly-known-length text.

    Built by hand (not `PdfWriter`, which has no simple way to draw text) so the character
    count per page is exact and controlled by the test, not by a font's rendering: each
    argument is drawn verbatim with one `Tj` operator on its own page. Invented text only.
    """
    n_pages = len(page_texts)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode(),
    }
    number = 3
    for text in page_texts:
        content = b"BT /F1 24 Tf 10 700 Td (" + text + b") Tj ET"
        objects[number] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica >> >> >> /Contents " + str(number + 1).encode() + b" 0 R >>"
        )
        objects[number + 1] = (
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
        )
        number += 2
    parts = [b"%PDF-1.4\n"]
    offsets: dict[int, int] = {}
    position = len(parts[0])
    for key in sorted(objects):
        piece = f"{key} 0 obj\n".encode() + objects[key] + b"\nendobj\n"
        offsets[key] = position
        parts.append(piece)
        position += len(piece)
    xref_offset = position
    size = max(offsets) + 1
    xref = [b"xref\n", f"0 {size}\n".encode(), b"0000000000 65535 f \n"]
    xref.extend(f"{offsets[i]:010d} 00000 n \n".encode() for i in range(1, size))
    parts.extend(xref)
    parts.append(
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return b"".join(parts)


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


def test_read_documents_carry_text_and_scans_do_not(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    """`status == "read"` is the only path that populates `texts` (fix round 1, Finding 2)."""
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    listing = parse_listing(page, mkey=mkey)
    non_photo = [e for e in listing.entries if e.is_pdf() and not e.is_photo_only()]
    born_digital, scanned, *rest = non_photo

    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    page_texts = [b"A" * 400, b"B" * 350]  # invented text, exact known lengths
    for entry in listing.entries:
        if not entry.href:
            continue
        content = _text_pdf(page_texts) if entry.index == born_digital.index else _blank_pdf()
        respx_mock.get(sources.docket_document_url(entry.href)).mock(
            return_value=httpx.Response(200, content=content)
        )

    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey)

    read_record = docket.record(born_digital.index)
    assert read_record.status == "read"
    assert read_record.kind == "born-digital"
    assert read_record.pages == 2
    assert read_record.readable_pages == 2  # both pages are over the scan threshold
    assert read_record.estimated_tokens == (400 + 350) // 4
    text = docket.texts[born_digital.index]
    assert "[page 1 of 2]" in text
    assert "[page 2 of 2]" in text
    assert "A" * 400 in text
    assert "B" * 350 in text

    assert docket.record(scanned.index).status == "unreadable: scan"
    for entry in rest:
        assert docket.record(entry.index).status != "read"  # every other entry got a blank pdf

    # The property that matters: only the read document's text is kept.
    assert set(docket.texts) == {born_digital.index}


def test_downloaded_non_pdf_content_is_unreadable_not_fetch_failed(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    """A downloaded non-PDF is `unreadable: not a pdf` (Finding 3), not `fetch failed`."""
    folder, mkey = _first_fixture()
    page = (folder / "listing.html").read_text()
    listing = parse_listing(page, mkey=mkey)
    target = next(e for e in listing.entries if e.is_pdf() and not e.is_photo_only())

    respx_mock.get(sources.docket_url(mkey)).mock(return_value=httpx.Response(200, text=page))
    for entry in listing.entries:
        if not entry.href:
            continue
        content = b"downloaded fine, but not a PDF" if entry.index == target.index else _blank_pdf()
        respx_mock.get(sources.docket_document_url(entry.href)).mock(
            return_value=httpx.Response(200, content=content)
        )

    with DocketClient(tmp_path, sleep=lambda _s: None) as client:
        docket = read_docket(client, mkey)

    assert docket.record(target.index).status == "unreadable: not a pdf"
    assert target.index not in docket.texts
