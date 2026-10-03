"""Text per page with page markers (spec §5.1); in v2, with transcribed pages (S2.6 §8)."""

import io
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader

from ntsb_probable_cause.docket.transcribe import Transcription
from ntsb_probable_cause.errors import DocketError

PAGE_MARKER = "[page {n} of {total}]"
# Decision 0079: a transcribed page says where its text came from, never what it means.
TRANSCRIBED_MARKER = "[page {n} of {total}, transcribed from an image]"
IMAGE_WORDS_HEADING = "[words in the page's images, transcribed]"


class ExtractedDocument(BaseModel):
    """Characters per page, and the page-marked text; in v2, what transcription added."""

    model_config = ConfigDict(frozen=True)
    chars_by_page: tuple[int, ...]
    text: str
    transcribed_pages: int = 0
    transcription_failed: int = 0
    # Decision 0081: what this document's readings cost, paid once, apart from the case cap.
    preparation_cost_usd: float = 0.0


def extract_pdf(
    data: bytes, *, readings: Mapping[int, Transcription] | None = None
) -> ExtractedDocument:
    """Extract every page; a page that fails counts 0 characters; a non-PDF raises.

    With ``readings`` (evidence version v2, by 1-based page number): an image-only page reads
    as its transcription under ``TRANSCRIBED_MARKER``; a mixed page keeps its text layer and
    adds the words in its images under ``IMAGE_WORDS_HEADING``; a failed or empty reading
    leaves the page as S2 read it. With ``readings=None`` the output is S2's, byte for byte.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = list(reader.pages)
    except Exception as error:  # a readable PDF or not: no exception escapes this boundary
        raise DocketError(f"not a PDF: {error}") from error
    total = len(pages)
    counts: list[int] = []
    parts: list[str] = []
    transcribed = failed = 0
    cost = 0.0
    for n, page in enumerate(pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # a broken page is unreadable, not fatal to the whole docket
            text = ""
        reading = readings.get(n) if readings is not None else None
        marker = PAGE_MARKER.format(n=n, total=total)
        if reading is not None:
            cost += reading.cost_usd
            failed += reading.status == "failed"
        if reading is not None and reading.status == "transcribed" and reading.text:
            if reading.mixed:
                text = f"{text}\n{IMAGE_WORDS_HEADING}\n{reading.text}"
            else:
                marker = TRANSCRIBED_MARKER.format(n=n, total=total)
                text = reading.text
            transcribed += 1
        counts.append(len(text))
        parts.append(marker + "\n" + text)
    return ExtractedDocument(
        chars_by_page=tuple(counts),
        text="\n".join(parts),
        transcribed_pages=transcribed,
        transcription_failed=failed,
        preparation_cost_usd=cost,
    )
