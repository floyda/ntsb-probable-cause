"""The listing parser against the saved real page (rule 2, decision 0037)."""

import json
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.listing import Listing, ListingEntry, parse_listing, render_listing
from ntsb_probable_cause.errors import DocketError

FIXTURES = Path("tests/fixtures/docket")


def _saved_pages() -> list[tuple[Path, int]]:
    pages = []
    for folder in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        manifest = json.loads((folder / "manifest.json").read_text())
        pages.append((folder / "listing.html", int(manifest["fixture"]["mkey"])))
    return pages


@pytest.mark.parametrize(("page", "mkey"), _saved_pages())
def test_saved_page_parses_and_the_item_count_agrees(page: Path, mkey: int) -> None:
    listing = parse_listing(page.read_text(), mkey=mkey)
    assert listing.mkey == mkey
    assert listing.declared_items == len(listing.entries)
    assert listing.entries, "a real docket has at least one document"
    assert [e.index for e in listing.entries] == list(range(1, len(listing.entries) + 1))
    for entry in listing.entries:
        assert entry.title
        assert entry.pages >= 0
        assert entry.photos >= 0


def test_doctored_page_with_a_missing_row_fails_loudly() -> None:
    # The saved page has no <tbody>, and its two earlier info tables also contain <tr>
    # elements that never match _ROW -- so the first <tr> in the whole page is not a
    # document row. Anchor on the first document row itself (index "1") instead.
    page, mkey = _saved_pages()[0]
    text = page.read_text()
    marker = text.index("<td><b>1</b></td>")
    first_row = text.rindex("<tr>", 0, marker)
    end = text.index("</tr>", first_row) + len("</tr>")
    with pytest.raises(DocketError, match="declared"):
        parse_listing(text[:first_row] + text[end:], mkey=mkey)


def test_photo_only_and_pdf_predicates() -> None:
    photos = ListingEntry(
        index=1, title="Photos", pages=3, photos=3, doc_type="Photo", extension="pdf", href="/x"
    )
    report = ListingEntry(
        index=2, title="Report", pages=5, photos=1, doc_type="Report", extension="pdf", href="/x"
    )
    sheet = ListingEntry(
        index=3, title="Data", pages=0, photos=0, doc_type="Data", extension="xlsx", href="/x"
    )
    assert photos.is_photo_only() is True
    assert photos.is_pdf() is True
    assert not report.is_photo_only()
    assert report.is_pdf()
    assert not sheet.is_pdf()


def test_render_listing_is_one_line_per_entry() -> None:
    listing = Listing(
        mkey=1,
        declared_items=1,
        entries=(
            ListingEntry(
                index=1,
                title="Weather Study",
                pages=12,
                photos=0,
                doc_type="Report",
                extension="pdf",
                href="/x",
            ),
        ),
    )
    assert render_listing(listing) == "1. Weather Study (Report, 12 pages, 0 photos)"
