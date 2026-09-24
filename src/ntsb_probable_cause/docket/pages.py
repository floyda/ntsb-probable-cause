"""What a PDF page holds: text characters, images, rotation and image encodings (S2.6 §1).

Read from the page's own dictionaries with pypdf and never decoded, so a page is classified
without any image codec (0047's rule against system tools). Text is pypdf's
``extract_text``, exactly as ``extract.py`` reads it, so "under 50 characters" means here
what it means to the docket tool.
"""

import io
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, PdfObject

from ntsb_probable_cause.docket.classify import SCAN_PAGE_MAX_CHARS
from ntsb_probable_cause.errors import DocketError

PageKind = Literal["text only", "image only", "text and image", "blank"]

# A page drawn from this many image pieces or more comes out of image extraction as strips
# rather than a page (spec §5.2).
TILED_MIN_IMAGES = 5

# The encodings spec §5.2 names, by the PDF filter that declares them. Anything else is
# "other"; an image with no filter is "none".
_ENCODINGS = {
    "/CCITTFaxDecode": "fax (CCITT)",
    "/JPXDecode": "JPEG 2000",
    "/JBIG2Decode": "JBIG2",
    "/DCTDecode": "JPEG",
    "/FlateDecode": "Flate",
}


class PageFacts(BaseModel):
    """One page's counts. Never its text."""

    model_config = ConfigDict(frozen=True)
    chars: int
    images: int
    rotation: int
    encodings: tuple[str, ...]
    failed: bool = False

    @property
    def kind(self) -> PageKind:
        """Text only, image only, text and image, or blank, by the 50-character line."""
        has_text = self.chars >= SCAN_PAGE_MAX_CHARS
        if self.images:
            return "text and image" if has_text else "image only"
        return "text only" if has_text else "blank"


def _resolve(value: object) -> object:
    """An indirect reference's target; any other value unchanged."""
    return value.get_object() if isinstance(value, PdfObject) else value


def _encoding(filters: object) -> str:
    """The encoding an image is stored in: the last filter applied, by name."""
    resolved = _resolve(filters)
    if isinstance(resolved, ArrayObject):
        resolved = _resolve(resolved[-1]) if resolved else None
    if resolved is None:
        return "none"
    return _ENCODINGS.get(str(resolved), "other")


def _images(resources: object, seen: set[int]) -> Iterator[str]:
    """One encoding per image the resources draw, following forms; each object counted once.

    ``DictionaryObject.get`` and ``.values()`` return references unresolved (checked on
    pypdf 6.19), so every value is resolved here explicitly.
    """
    resolved = _resolve(resources)
    if not isinstance(resolved, DictionaryObject):
        return
    xobjects = _resolve(resolved.get("/XObject"))
    if not isinstance(xobjects, DictionaryObject):
        return
    for value in xobjects.values():
        if isinstance(value, IndirectObject):
            if value.idnum in seen:
                continue
            seen.add(value.idnum)
        target = _resolve(value)
        if not isinstance(target, DictionaryObject):
            continue
        subtype = target.get("/Subtype")
        if subtype == "/Image":
            yield _encoding(target.get("/Filter"))
        elif subtype == "/Form":
            yield from _images(target.get("/Resources"), seen)


def page_facts(page: PageObject) -> PageFacts:
    """Characters of extractable text, images drawn, rotation and the encodings present."""
    try:
        chars = len((page.extract_text() or "").strip())
        encodings = list(_images(page.get("/Resources"), set()))
        rotation = page.rotation % 360
    except Exception:  # a broken page is counted, flagged and never fatal to the document
        return PageFacts(chars=0, images=0, rotation=0, encodings=(), failed=True)
    return PageFacts(
        chars=chars,
        images=len(encodings),
        rotation=rotation,
        encodings=tuple(sorted(set(encodings))),
    )


def document_facts(data: bytes) -> tuple[PageFacts, ...]:
    """Every page's facts; a file pypdf cannot open raises ``DocketError``, as in extract."""
    try:
        pages = list(PdfReader(io.BytesIO(data)).pages)
    except Exception as error:  # the same boundary as extract.extract_pdf
        raise DocketError(f"not a PDF: {error}") from error
    return tuple(page_facts(page) for page in pages)
