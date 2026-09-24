"""Build small PDFs from pypdf objects, for tests that must not commit a real docket page.

Each image is a one-pixel XObject whose ``/Filter`` names the encoding under test. Its data
is not a valid stream of that encoding: page facts read only the image's dictionary, and
PDFium draws such an image as blank rather than failing. Tests that need real pixels (the
renderer's, Task 3) build their images with Pillow instead.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    StreamObject,
)


@dataclass(frozen=True)
class PageSpec:
    """One test page: its text, one encoding name (or a chain of them) per image, its rotation.

    An entry of ``images`` is usually a single filter name (``"/DCTDecode"``); it may instead
    be a tuple of filter names, written as a ``/Filter`` array on that one image, for a test
    that needs a chained filter (``docket.pages._encoding`` reads the last name in the chain).
    """

    text: str = ""
    images: tuple[str | tuple[str, ...], ...] = ()
    rotation: int = 0
    in_form: bool = False


def _image(writer: PdfWriter, filter_name: str | tuple[str, ...]) -> IndirectObject:
    image = StreamObject()
    image.set_data(b"\x00")
    filt = (
        ArrayObject(NameObject(name) for name in filter_name)
        if isinstance(filter_name, tuple)
        else NameObject(filter_name)
    )
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/Filter"): filt,
        }
    )
    return writer._add_object(image)


def _form(writer: PdfWriter, draws: str, xobjects: DictionaryObject) -> IndirectObject:
    form = StreamObject()
    form.set_data(draws.encode())
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [NumberObject(0), NumberObject(0), NumberObject(612), NumberObject(792)]
            ),
            NameObject("/Resources"): DictionaryObject({NameObject("/XObject"): xobjects}),
        }
    )
    return writer._add_object(form)


def build_pdf(pages: Sequence[PageSpec]) -> bytes:
    """A letter-size PDF with one page per spec, Helvetica text, images drawn in a column."""
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for spec in pages:
        page = writer.add_blank_page(width=612, height=792)
        xobjects = DictionaryObject(
            {NameObject(f"/Im{i}"): _image(writer, name) for i, name in enumerate(spec.images)}
        )
        draws = "".join(
            f"q 100 0 0 100 0 {i * 100} cm /Im{i} Do Q\n" for i in range(len(spec.images))
        )
        if spec.in_form and spec.images:
            xobjects = DictionaryObject({NameObject("/Fm0"): _form(writer, draws, xobjects)})
            draws = "q /Fm0 Do Q\n"
        text = f"BT /F1 12 Tf 72 700 Td ({spec.text}) Tj ET\n" if spec.text else ""
        content = StreamObject()
        content.set_data((draws + text).encode())
        page[NameObject("/Contents")] = writer._add_object(content)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                NameObject("/XObject"): xobjects,
            }
        )
        if spec.rotation:
            page.rotate(spec.rotation)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
