"""The listing parser against the saved real page (rule 2, decision 0037)."""

import json
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.listing import (
    Listing,
    ListingEntry,
    parse_listing,
    render_listing,
)
from ntsb_probable_cause.errors import DocketError

FIXTURES = Path("tests/fixtures/docket")


def _saved_pages() -> list[tuple[Path, int]]:
    pages = []
    for folder in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        manifest = json.loads((folder / "manifest.json").read_text())
        pages.append((folder / "listing.html", int(manifest["fixture"]["mkey"])))
    return pages


def _read_page(page: Path) -> str:
    """The fixture's own bytes, decoded explicitly -- never ``Path.read_text()``.

    ``read_text()`` opens in text mode with universal newlines, which silently turns the
    fixture's CRLF into LF before a single assertion runs. ``DocketClient.listing_html``
    (``docket/client.py``) never does that: it decodes the raw response bytes as-is, so a
    real fetch always hands the parser CRLF. Decoding bytes here keeps the test on the page
    the parser will actually meet.
    """
    return page.read_bytes().decode("utf-8")


@pytest.mark.parametrize(("page", "mkey"), _saved_pages())
def test_saved_page_parses_and_the_item_count_agrees(page: Path, mkey: int) -> None:
    text = _read_page(page)
    assert "\r\n" in text, "fixture is expected to be CRLF; a clean checkout would prove it"
    listing = parse_listing(text, mkey=mkey)
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
    text = _read_page(page)
    marker = text.index("<td><b>1</b></td>")
    first_row = text.rindex("<tr>", 0, marker)
    end = text.index("</tr>", first_row) + len("</tr>")
    with pytest.raises(DocketError, match="declared"):
        parse_listing(text[:first_row] + text[end:], mkey=mkey)


def test_render_listing_of_the_real_page_leaks_nothing() -> None:
    """render_listing goes to the model: it must hold titles and counts, nothing else."""
    page, mkey = _saved_pages()[0]
    manifest = json.loads((page.parent / "manifest.json").read_text())
    case_id = str(manifest["fixture"]["case_id"])
    listing = parse_listing(_read_page(page), mkey=mkey)
    rendered = render_listing(listing)
    assert "docBLOB" not in rendered
    assert "href" not in rendered
    assert "http" not in rendered
    assert str(mkey) not in rendered
    assert case_id not in rendered


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


def test_saved_page_carries_docket_info() -> None:
    page = FIXTURES / "ERA17LA217" / "listing.html"
    listing = parse_listing(_read_page(page), mkey=95459)
    assert listing.info is not None
    assert listing.info.creation_date == "01/28/2019"
    assert listing.info.last_modified == "01/28/2019 7:37 AM"
    assert listing.info.release_date == "01/28/2019 7:37 AM"


def test_page_without_info_block_has_none() -> None:
    listing = parse_listing("<html>Docket Items: 0</html>", mkey=1)
    assert listing.info is None
    assert listing.entries == ()


def test_info_block_with_empty_date_labels_returns_none_fields() -> None:
    page = (
        "<h2><b>Docket Information</b></h2>"
        "<table><tr><td><h3><b>Creation Date:</b> </h3></td></tr></table>"
        "<html>Docket Items: 0</html>"
    )
    listing = parse_listing(page, mkey=1)
    assert listing.info is not None
    assert listing.info.creation_date is None
    assert listing.info.last_modified is None
    assert listing.info.release_date is None


def test_release_date_with_amp_entity_unescapes() -> None:
    # Verify the regex handles &amp; entity (raw & also works from real pages)
    page = (
        "<h2><b>Docket Information</b></h2>"
        "<table><tr><td><h3>"
        "Public Release Date &amp; Time: 01/28/2019 7:37 AM<"
        "</h3></td></tr></table>"
        "<html>Docket Items: 0</html>"
    )
    listing = parse_listing(page, mkey=1)
    assert listing.info is not None
    assert listing.info.release_date == "01/28/2019 7:37 AM"


@pytest.mark.parametrize(("page", "mkey"), _saved_pages())
def test_all_saved_listing_fixtures_carry_docket_info(page: Path, mkey: int) -> None:
    text = _read_page(page)
    listing = parse_listing(text, mkey=mkey)
    assert listing.info is not None, f"fixture {page.parent.name} has no docket info block"
    assert listing.info.creation_date is not None
    assert listing.info.last_modified is not None
    assert listing.info.release_date is not None
