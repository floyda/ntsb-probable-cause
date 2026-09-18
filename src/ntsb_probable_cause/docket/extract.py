"""Text per page with page markers (spec §5.1)."""

import io

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ntsb_probable_cause.errors import DocketError

PAGE_MARKER = "[page {n} of {total}]"


class ExtractedDocument(BaseModel):
    """Characters per page, and the page-marked text."""

    model_config = ConfigDict(frozen=True)
    chars_by_page: tuple[int, ...]
    text: str


def extract_pdf(data: bytes) -> ExtractedDocument:
    """Extract every page; a page that fails counts 0 characters; a non-PDF raises."""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = list(reader.pages)
    except (PyPdfError, ValueError, TypeError) as error:
        raise DocketError(f"not a PDF: {error}") from error
    total = len(pages)
    counts: list[int] = []
    parts: list[str] = []
    for n, page in enumerate(pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # a broken page is unreadable, not fatal to the whole docket
            text = ""
        counts.append(len(text))
        parts.append(PAGE_MARKER.format(n=n, total=total) + "\n" + text)
    return ExtractedDocument(chars_by_page=tuple(counts), text="\n".join(parts))
