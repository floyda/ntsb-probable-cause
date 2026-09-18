"""Page-marked extraction (spec §5.1)."""

import io

import pytest
from pypdf import PdfWriter

from ntsb_probable_cause.docket.extract import PAGE_MARKER, extract_pdf
from ntsb_probable_cause.errors import DocketError


def _blank_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_blank_pages_extract_to_zero_characters_with_markers() -> None:
    result = extract_pdf(_blank_pdf(2))
    assert result.chars_by_page == (0, 0)
    assert result.text == "[page 1 of 2]\n\n[page 2 of 2]\n"


def test_marker_format_is_stable() -> None:
    assert PAGE_MARKER.format(n=4, total=22) == "[page 4 of 22]"


def test_not_a_pdf_raises() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        extract_pdf(b"<html>not a pdf</html>")


def _malformed_encrypted_pdf() -> bytes:
    """An encrypted, empty-password PDF whose ``/Pages`` dict is missing ``/Count``.

    ``pypdf``'s encrypted-file page-count path reads ``self.root_object["/Pages"]["/Count"]``
    directly, which raises a bare ``KeyError`` when the key is absent -- not one of
    ``PyPdfError``, ``ValueError`` or ``TypeError``. A real, decades-old public docket file can
    be exactly this damaged; ``extract_pdf`` must turn it into ``DocketError`` too, not let it
    escape (fix round 1, Finding 1).
    """
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="", owner_password="", algorithm="RC4-40")
    buffer = io.BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    start = data.find(b"/Count")
    assert start != -1, "expected /Count in the encrypted test PDF"
    end = start + len(b"/Count")
    while data[end : end + 1].isdigit() or data[end : end + 1] == b" ":
        end += 1
    return data[:start] + data[end:]


def test_malformed_pdf_raises_docket_error_not_a_bare_keyerror() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        extract_pdf(_malformed_encrypted_pdf())
