"""Page facts: characters, images, rotation and encodings, read without decoding (S2.6 §1)."""

import pytest
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.pages import TILED_MIN_IMAGES, PageFacts, document_facts
from ntsb_probable_cause.errors import DocketError

# Invented clinical text, over the 50-character line (classify.SCAN_PAGE_MAX_CHARS).
TYPED = "Examination of the left magneto found the points worn beyond limits."


def test_the_four_page_kinds() -> None:
    facts = document_facts(
        build_pdf(
            [
                PageSpec(text=TYPED),
                PageSpec(images=("/CCITTFaxDecode",)),
                PageSpec(text=TYPED, images=("/DCTDecode",)),
                PageSpec(),
            ]
        )
    )
    assert [f.kind for f in facts] == ["text only", "image only", "text and image", "blank"]


def test_a_short_caption_does_not_make_an_image_page_a_text_page() -> None:
    (facts,) = document_facts(build_pdf([PageSpec(text="Photo 3", images=("/DCTDecode",))]))
    assert facts.chars < 50
    assert facts.kind == "image only"


def test_rotation_and_encodings_are_read_from_the_page() -> None:
    (facts,) = document_facts(
        build_pdf([PageSpec(images=("/JBIG2Decode", "/JPXDecode"), rotation=90)])
    )
    assert facts.rotation == 90
    assert facts.encodings == ("JBIG2", "JPEG 2000")
    assert facts.images == 2


def test_images_inside_a_form_are_counted() -> None:
    specs = [PageSpec(images=("/DCTDecode",) * TILED_MIN_IMAGES, in_form=True)]
    (facts,) = document_facts(build_pdf(specs))
    assert facts.images == TILED_MIN_IMAGES
    assert facts.encodings == ("JPEG",)


def test_an_unknown_encoding_is_named_other() -> None:
    (facts,) = document_facts(build_pdf([PageSpec(images=("/RunLengthDecode",))]))
    assert facts.encodings == ("other",)


def test_not_a_pdf_raises() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        document_facts(b"<html>not a pdf</html>")


def test_a_failed_page_is_blank_and_flagged() -> None:
    facts = PageFacts(chars=0, images=0, rotation=0, encodings=(), failed=True)
    assert facts.kind == "blank"
