"""The renderer: upright, whole, every encoding; a fixed resolution (S2.6 §5, 0075)."""

import io

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter, Transformation
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.render import RESOLUTION, render_pages
from ntsb_probable_cause.errors import DocketError

DARK = 128


def _image_pdf(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PDF", resolution=72)
    return out.getvalue()


def _marked_portrait(mode: str = "L") -> Image.Image:
    """200 x 300 points, white, with a black square in the top-left corner."""
    image = Image.new("L", (200, 300), 255)
    ImageDraw.Draw(image).rectangle((0, 0, 60, 60), fill=0)
    return image.convert(mode)


def _pixel_dark(data: bytes, x_frac: float, y_frac: float) -> bool:
    image = Image.open(io.BytesIO(data)).convert("L")
    x = min(image.width - 1, int(x_frac * image.width))
    y = min(image.height - 1, int(y_frac * image.height))
    return int(image.getpixel((x, y))) < DARK  # type: ignore[arg-type]


def test_an_upright_page_keeps_its_corner() -> None:
    (page,) = render_pages(_image_pdf(_marked_portrait()))
    assert page.height > page.width
    assert _pixel_dark(page.data, 0.02, 0.02)


def test_a_rotated_page_is_drawn_upright() -> None:
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(_image_pdf(_marked_portrait()))))
    writer.pages[0].rotate(90)
    out = io.BytesIO()
    writer.write(out)
    (page,) = render_pages(out.getvalue())
    assert page.width > page.height
    assert _pixel_dark(page.data, 0.98, 0.02)  # the corner a viewer shows at the top right
    assert not _pixel_dark(page.data, 0.02, 0.02)


def test_a_fax_encoded_page_renders() -> None:
    data = _image_pdf(_marked_portrait(mode="1"))
    xobjects = PdfReader(io.BytesIO(data)).pages[0]["/Resources"]["/XObject"]  # type: ignore[index]
    filters = [str(x.get_object()["/Filter"]) for x in xobjects.values()]
    assert any("CCITTFaxDecode" in f for f in filters)
    (page,) = render_pages(data)
    assert _pixel_dark(page.data, 0.02, 0.02)


def test_a_page_built_from_five_strips_renders_whole() -> None:
    writer = PdfWriter()
    base = writer.add_blank_page(width=200, height=300)
    for i in range(5):
        strip = Image.new("L", (200, 60), 0 if i % 2 == 0 else 255)
        base.merge_transformed_page(
            PdfReader(io.BytesIO(_image_pdf(strip))).pages[0],
            Transformation().translate(0, i * 60),
        )
    out = io.BytesIO()
    writer.write(out)
    (page,) = render_pages(out.getvalue())
    assert _pixel_dark(page.data, 0.5, 0.99)  # strip 0, at the bottom
    assert not _pixel_dark(page.data, 0.5, 0.7)  # strip 1
    assert _pixel_dark(page.data, 0.5, 0.02)  # strip 4, at the top
    assert page.image_area_share == pytest.approx(1.0)


def test_image_area_share_tells_a_logo_from_a_photograph() -> None:
    data = build_pdf(
        [PageSpec(text="A typed report with a logo.", images=("/DCTDecode",)), PageSpec(text="x")]
    )
    logo, typed = render_pages(data)
    assert logo.image_area_share == pytest.approx(100 * 100 / (612 * 792))
    assert typed.image_area_share == 0.0


def test_resolution_sets_the_size_and_the_default_is_150() -> None:
    data = _image_pdf(_marked_portrait())
    (low,) = render_pages(data)
    (high,) = render_pages(data, dpi=200)
    assert RESOLUTION == 150
    assert (low.width, low.height) == (417, 625)
    assert high.width > low.width
    assert low.dpi == 150


def test_rendering_is_repeatable() -> None:
    data = _image_pdf(_marked_portrait())
    assert render_pages(data)[0].sha256 == render_pages(data)[0].sha256


def test_only_the_asked_pages_are_drawn() -> None:
    data = build_pdf([PageSpec(text="one"), PageSpec(text="two"), PageSpec(text="three")])
    assert [p.page for p in render_pages(data, [3, 1])] == [3, 1]


def test_not_a_pdf_and_a_missing_page_raise() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        render_pages(b"<html>not a pdf</html>")
    with pytest.raises(DocketError, match="no page 2"):
        render_pages(build_pdf([PageSpec(text="one")]), [2])
