"""A PDF page drawn as a viewer shows it: upright, whole, every encoding (decision 0075).

pypdfium2 bundles PDFium, the PDF engine inside Chrome, as a ready-built package installed
from the lock file, so nothing is installed on the machine itself and 0047's reproducibility
test holds. PDFium honours a page's rotation, so a page stored sideways comes out upright
with no correction here; tiled and fax, JPEG 2000 or JBIG2 pages are drawn like any other.
"""

import hashlib
import io
import threading
from collections.abc import Sequence
from typing import Literal

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image
from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.errors import DocketError

# Fix round 1, C1: PDFium is not thread-safe (confirmed by the review's `pdfium_threads.py`
# probe -- 8 concurrent workers crashed the process 5 times out of 5). `transcribe_all` calls
# this from up to `workers` threads at once, so every entry point into PDFium -- opening,
# reading a page's size or images, rendering, closing -- is serialised behind one process-wide
# lock. Rendering one page is milliseconds against a model call of seconds, so the pool still
# overlaps the calls that matter.
_PDFIUM_LOCK = threading.Lock()

Resolution = Literal[150, 200]
# Spec §5.4 and §7.5: the transcriber test chooses 150 or 200 dots per inch; 150 until then.
# Part of every transcription's cache key (Task 11).
RESOLUTION: Resolution = 150
POINTS_PER_INCH = 72
# Measured ad hoc while planning (121 dev-400 pages): a 150-dpi image-only page is about
# 1.2 MB as PNG and 385 KB as JPEG at quality 90. Every request carries its image.
JPEG_QUALITY = 90
MEDIA_TYPE = "image/jpeg"


class RenderedPage(BaseModel):
    """One drawn page: its number, size, how much of it is image, and the JPEG bytes."""

    model_config = ConfigDict(frozen=True)
    page: int
    dpi: int
    width: int
    height: int
    image_area_share: float
    data: bytes

    @property
    def sha256(self) -> str:
        """The image's hash: what identifies this drawing of the page."""
        return hashlib.sha256(self.data).hexdigest()


def _image_area_share(page: pdfium.PdfPage) -> float:
    """The share of the page its images cover, from their boxes, clipped to the page.

    Overlapping images are summed, so the share is capped at 1. A logo on a letterhead is a
    few per cent; a photograph with a caption is most of the page (decision W3).
    """
    width, height = (float(v) for v in page.get_size())
    if width <= 0 or height <= 0:
        return 0.0
    covered = 0.0
    for image in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = (float(v) for v in image.get_bounds())
        covered += max(0.0, min(right, width) - max(left, 0.0)) * max(
            0.0, min(top, height) - max(bottom, 0.0)
        )
    return min(1.0, covered / (width * height))


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def render_pages(
    data: bytes, pages: Sequence[int] | None = None, *, dpi: Resolution = RESOLUTION
) -> list[RenderedPage]:
    """Draw the asked pages (1-based, in the order asked; every page if ``None``).

    Every PDFium call this function makes runs behind ``_PDFIUM_LOCK`` (fix round 1, C1):
    PDFium itself is not thread-safe, so two calls from different threads at once can crash
    the process rather than raise a catchable error.
    """
    with _PDFIUM_LOCK:
        try:
            document = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as error:
            raise DocketError(f"not a PDF: {error}") from error
        try:
            total = len(document)
            drawn: list[RenderedPage] = []
            for number in pages if pages is not None else range(1, total + 1):
                if not 1 <= number <= total:
                    raise DocketError(f"no page {number} of {total}")
                # A real dev-400 page fails to load in PDFium (found while planning): it
                # becomes a DocketError, which a transcription records as a failed reading,
                # never a crash.
                try:
                    page = document[number - 1]
                except pdfium.PdfiumError as error:
                    raise DocketError(f"page {number} did not load: {error}") from error
                try:
                    image: Image.Image = page.render(scale=dpi / POINTS_PER_INCH).to_pil()
                    share = _image_area_share(page)
                except pdfium.PdfiumError as error:
                    raise DocketError(f"page {number} did not render: {error}") from error
                finally:
                    page.close()
                rgb = image.convert("RGB")
                drawn.append(
                    RenderedPage(
                        page=number,
                        dpi=dpi,
                        width=rgb.width,
                        height=rgb.height,
                        image_area_share=share,
                        data=_jpeg(rgb),
                    )
                )
            return drawn
        finally:
            document.close()
