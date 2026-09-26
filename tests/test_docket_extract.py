"""Page-marked extraction (spec §5.1); v2's transcribed pages (S2.6 §8)."""

import io
from datetime import UTC, datetime
from typing import Literal

import pytest
from pypdf import PdfWriter
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.extract import (
    IMAGE_WORDS_HEADING,
    PAGE_MARKER,
    TRANSCRIBED_MARKER,
    extract_pdf,
)
from ntsb_probable_cause.docket.transcribe import (
    TRANSCRIBE,
    Transcription,
    TranscriptionKey,
    key_instruction,
)
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


def _reading(
    page: int,
    text: str,
    *,
    status: Literal["transcribed", "failed"] = "transcribed",
    mixed: bool = False,
) -> Transcription:
    return Transcription(
        # Fix round 3, R4: keyed the same way a real mixed reading is (0085, amended by Task
        # 13's I3) -- a fixed "t1" here would let this test pass while `ReadingLookup` looked
        # up the wrong key for every mixed page in production.
        key=TranscriptionKey(
            document_sha256="d" * 64,
            page=page,
            model="m",
            instruction=key_instruction(TRANSCRIBE, mixed=mixed),
            dpi=150,
        ),
        status=status,
        text=text,
        page_kind="handwriting",
        mixed=mixed,
        cost_usd=0.001,
        created=datetime(2026, 10, 1, tzinfo=UTC),
    )


TYPED = "Examination of the fuel system found fuel in both wing tanks."
DOC = build_pdf(
    [
        PageSpec(text=TYPED),
        PageSpec(images=("/DCTDecode",)),
        PageSpec(text=TYPED, images=("/DCTDecode",)),
    ]
)


def test_without_readings_the_text_is_s2s() -> None:
    assert extract_pdf(DOC).text == extract_pdf(DOC, readings=None).text
    assert extract_pdf(DOC) == extract_pdf(DOC, readings={})
    assert "transcribed" not in extract_pdf(DOC).text


def test_the_markers_are_stable() -> None:
    assert TRANSCRIBED_MARKER.format(n=2, total=3) == "[page 2 of 3, transcribed from an image]"
    assert IMAGE_WORDS_HEADING == "[words in the page's images, transcribed]"


def test_an_image_page_reads_as_its_transcription_with_its_own_marker() -> None:
    result = extract_pdf(DOC, readings={2: _reading(2, "Engine sputtered at 800 ft.")})
    assert "[page 2 of 3, transcribed from an image]\nEngine sputtered at 800 ft." in result.text
    assert "[page 2 of 3]\n" not in result.text
    assert result.transcribed_pages == 1
    assert result.chars_by_page[1] == len("Engine sputtered at 800 ft.")
    assert result.preparation_cost_usd == pytest.approx(0.001)


def test_a_mixed_page_keeps_its_text_layer_and_adds_the_image_words() -> None:
    result = extract_pdf(DOC, readings={3: _reading(3, "LEFT TANK 2 GAL", mixed=True)})
    page_three = result.text.split("[page 3 of 3]")[1]
    assert TYPED.split(" in ", maxsplit=1)[0] in page_three
    assert page_three.endswith("[words in the page's images, transcribed]\nLEFT TANK 2 GAL")
    assert result.transcribed_pages == 1


def test_a_failed_page_adds_nothing_and_is_counted() -> None:
    result = extract_pdf(DOC, readings={2: _reading(2, "", status="failed")})
    assert result.transcription_failed == 1
    assert result.transcribed_pages == 0
    assert "transcribed from an image" not in result.text
    assert result.text == extract_pdf(DOC).text
    assert result.preparation_cost_usd == pytest.approx(0.001)  # a failed reading was paid


def test_a_reading_with_no_words_leaves_the_page_as_s2_read_it() -> None:
    result = extract_pdf(DOC, readings={2: _reading(2, "")})
    assert result.text == extract_pdf(DOC).text
    assert result.transcribed_pages == 0
    assert result.transcription_failed == 0
