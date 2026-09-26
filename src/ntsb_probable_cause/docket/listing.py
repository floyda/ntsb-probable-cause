"""Parse the docket listing page into entries (spec §4.3). Structure from the saved real page."""

import html
import re

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.errors import DocketError

# From ../ntsb-spike/scripts/docket_shape_probe.py (ROW_RE, ITEMS_RE), checked against
# tests/fixtures/docket/*/listing.html. A change in the page fails the saved-page test.
_ROW = re.compile(
    r"<tr>\s*<td><b>(?P<idx>\d+)</b></td>\s*<td>(?P<title>.*?)</td>\s*"
    r"<td><b>(?P<pages>\d+)</b></td>\s*<td>(?P<photos>\d+)</td>\s*<td>(?P<dtype>.*?)</td>\s*"
    r"<td>\s*(?:<a target=\"_blank\" href=\"(?P<href>/Docket/Document/docBLOB[^\"]*)\">)?",
    re.S,
)
_ITEMS = re.compile(r"Docket Items:\s*(\d+)")
_TAGS = re.compile(r"<[^>]+>")
_INFO_BLOCK = re.compile(r"<h2><b>Docket Information</b></h2>")
_CREATION = re.compile(r"<b>Creation Date:</b>\s*([^<]*)<")
_MODIFIED = re.compile(r"<b>Last Modified:</b>\s*([^<]*)<")
_RELEASE = re.compile(r"Public Release Date &(?:amp;)? Time:\s*([^<]*)<")

# Task 3's live probe (spec §10.1; recorded in the spec's As-built section):
# the site answers a case with no public docket at all with an ordinary HTTP 200 page
# (title "NTSB Docket - Docket Management System") carrying this exact sentence in an
# ``<h5>``, never with an HTTP error or a blank page. Confirmed against ProjectID 999999999,
# a nonexistent case -- fixture tests/fixtures/docket/not-released.html. Matched after
# unescaping and whitespace-normalising the page, so a reflow of the surrounding markup does
# not break it. This was scripts/ongoing_docket_probe.py's own ``_NOT_RELEASED_SENTENCE`` and
# ``_normalised_text``; Task 8 moved both here so the probe and the recorder share one
# implementation instead of two copies drifting apart.
NOT_RELEASED_SENTENCE = "The docket for this investigation has not been released."
_WHITESPACE = re.compile(r"\s+")


def _normalised_text(page: str) -> str:
    """``page`` with HTML entities unescaped and whitespace collapsed to single spaces."""
    return _WHITESPACE.sub(" ", html.unescape(page)).strip()


def is_not_released(page: str) -> bool:
    """Whether ``page`` is the site's own "docket has not been released" page.

    Checked before :func:`parse_listing`: this page carries no "Docket Items:" count and no
    "Docket Information" block, so treating it as an ordinary listing would otherwise misread
    it as ``no-info-block`` -- indistinguishable from a genuine layout change (spec §6.2).
    """
    return NOT_RELEASED_SENTENCE in _normalised_text(page)


class DocketInfo(BaseModel):
    """The docket-level dates the page prints, as printed. Not per document (spec §6.2)."""

    model_config = ConfigDict(frozen=True)
    creation_date: str | None
    last_modified: str | None
    release_date: str | None


class ListingEntry(BaseModel):
    """One row of the listing: what the page says about a document, nothing more."""

    model_config = ConfigDict(frozen=True)
    index: int
    title: str
    pages: int
    photos: int
    doc_type: str
    extension: str
    href: str

    def is_photo_only(self) -> bool:
        """Every page is a photo: skipped, not read (spike's rule)."""
        return self.photos > 0 and self.photos >= self.pages

    def is_pdf(self) -> bool:
        """A downloadable PDF."""
        return self.extension == "pdf" and bool(self.href)


class Listing(BaseModel):
    """The docket's table of documents for one case."""

    model_config = ConfigDict(frozen=True)
    mkey: int
    declared_items: int | None
    entries: tuple[ListingEntry, ...]
    info: DocketInfo | None = None


def _extension(href: str) -> str:
    if not href:
        return ""
    ext = href.rsplit("FileExtension=", maxsplit=1)[-1].split("&", maxsplit=1)[0].strip(".").lower()
    return ext or href.rsplit(".", 1)[-1].lower()


def _info(page: str) -> DocketInfo | None:
    if not _INFO_BLOCK.search(page):
        return None

    def first(pattern: re.Pattern[str]) -> str | None:
        match = pattern.search(page)
        value = html.unescape(match.group(1)).strip() if match else ""
        return value or None

    return DocketInfo(
        creation_date=first(_CREATION), last_modified=first(_MODIFIED), release_date=first(_RELEASE)
    )


def parse_listing(page: str, *, mkey: int) -> Listing:
    """Parse the page; raise ``DocketError`` if its declared count disagrees with the rows."""
    match = _ITEMS.search(page)
    declared = int(match.group(1)) if match else None
    entries = []
    for row in _ROW.finditer(page):
        href = html.unescape(row.group("href") or "")
        entries.append(
            ListingEntry(
                index=int(row.group("idx")),
                title=html.unescape(_TAGS.sub("", row.group("title"))).strip(),
                pages=int(row.group("pages")),
                photos=int(row.group("photos")),
                doc_type=html.unescape(_TAGS.sub("", row.group("dtype"))).strip(),
                extension=_extension(href),
                href=href,
            )
        )
    if declared is not None and declared != len(entries):
        raise DocketError(
            f"docket {mkey}: page declared {declared} items, parsed {len(entries)} rows"
        )
    return Listing(mkey=mkey, declared_items=declared, entries=tuple(entries), info=_info(page))


def render_listing(listing: Listing) -> str:
    """The listing as evidence text: one line per document, from the page's own columns."""
    return "\n".join(
        f"{e.index}. {e.title} ({e.doc_type}, {e.pages} pages, {e.photos} photos)"
        for e in listing.entries
    )
