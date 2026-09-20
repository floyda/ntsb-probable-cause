"""The per-case manifest: what was read, what could not be, and why (spec §5.3)."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.docket.classify import (
    Kind,
    classify_pages,
    document_category,
    estimated_tokens,
    readable_pages,
)
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.extract import extract_pdf
from ntsb_probable_cause.docket.listing import Listing, ListingEntry, parse_listing
from ntsb_probable_cause.errors import DocketError

Status = Literal[
    "read",
    "unreadable: scan",
    "unreadable: not a pdf",
    "skipped: photo-only",
    "fetch failed",
    "denied: write-up",
]


class DocumentRecord(BaseModel):
    """One document's outcome: never its text."""

    model_config = ConfigDict(frozen=True)
    entry: ListingEntry
    category: str
    status: Status
    pages: int
    readable_pages: int
    estimated_tokens: int
    kind: Kind | None


class Docket(BaseModel):
    """A case's listing, every document's record, and the text of the readable ones."""

    model_config = ConfigDict(frozen=True)
    mkey: int
    listing: Listing
    documents: tuple[DocumentRecord, ...]
    texts: dict[int, str]

    def record(self, index: int) -> DocumentRecord:
        """The record for a listing index.

        Raises ``DocketError`` rather than a bare ``StopIteration`` (fix round 1, finding 3):
        from S3 the caller choosing ``index`` is a model, and a hallucinated index must come
        back as a clean tool error the loop can report, not an opaque internal exception.
        """
        for candidate in self.documents:
            if candidate.entry.index == index:
                return candidate
        raise DocketError(f"docket {self.mkey}: no document at index {index}")


def _record(  # noqa: PLR0913 -- one outcome field per status; see the Interfaces block.
    entry: ListingEntry,
    category: str,
    status: Status,
    *,
    pages: int | None = None,
    readable_pages: int = 0,
    estimated_tokens: int = 0,
    kind: Kind | None = None,
) -> DocumentRecord:
    return DocumentRecord(
        entry=entry,
        category=category,
        status=status,
        pages=entry.pages if pages is None else pages,
        readable_pages=readable_pages,
        estimated_tokens=estimated_tokens,
        kind=kind,
    )


def read_docket(
    client: DocketClient, mkey: int, *, denied: Callable[[str], bool] = lambda _c: False
) -> Docket:
    """Fetch the listing and every document; classify and extract; keep text for read ones."""
    listing = parse_listing(client.listing_html(mkey), mkey=mkey)
    records: list[DocumentRecord] = []
    texts: dict[int, str] = {}
    for entry in listing.entries:
        category = document_category(entry.title)
        if denied(category):
            records.append(_record(entry, category, "denied: write-up"))
        elif entry.is_photo_only():
            records.append(_record(entry, category, "skipped: photo-only"))
        elif not entry.is_pdf():
            records.append(_record(entry, category, "unreadable: not a pdf"))
        else:
            try:
                content = client.document(mkey, entry.index, entry.href)
            except DocketError:
                records.append(_record(entry, category, "fetch failed"))
                continue
            try:
                extracted = extract_pdf(content)
            except DocketError:
                records.append(_record(entry, category, "unreadable: not a pdf"))
                continue
            kind = classify_pages(extracted.chars_by_page)
            readable = readable_pages(extracted.chars_by_page)
            tokens = estimated_tokens(sum(extracted.chars_by_page))
            if kind == "scan":
                records.append(
                    _record(
                        entry,
                        category,
                        "unreadable: scan",
                        pages=len(extracted.chars_by_page),
                        kind=kind,
                    )
                )
            else:
                records.append(
                    _record(
                        entry,
                        category,
                        "read",
                        pages=len(extracted.chars_by_page),
                        readable_pages=readable,
                        estimated_tokens=tokens,
                        kind=kind,
                    )
                )
                texts[entry.index] = extracted.text
    return Docket(mkey=mkey, listing=listing, documents=tuple(records), texts=texts)
