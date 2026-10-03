"""The per-case manifest: what was read, what could not be, and why (spec §5.3)."""

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
from ntsb_probable_cause.docket.transcribe import ReadingLookup, Transcription
from ntsb_probable_cause.errors import DocketError

Status = Literal[
    "read",
    "unreadable: scan",
    "unreadable: not a pdf",
    "skipped: photo-only",
    "fetch failed",
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
    # Evidence version v2 (S2.6 §8): pages read from a transcription, and pages whose
    # reading failed. Both 0 in v1.
    transcribed_pages: int = 0
    transcription_failed: int = 0


class Docket(BaseModel):
    """A case's listing, every document's record, and the text of the readable ones."""

    model_config = ConfigDict(frozen=True)
    mkey: int
    listing: Listing
    documents: tuple[DocumentRecord, ...]
    texts: dict[int, str]
    # Evidence version v2: every document's readings, by listing index then page. Empty in v1.
    readings: dict[int, dict[int, Transcription]] = {}

    @property
    def preparation_cost_usd(self) -> float:
        """What reading this docket's pages cost, paid once and apart from the cap (0081)."""
        return sum(r.cost_usd for pages in self.readings.values() for r in pages.values())

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
    transcribed_pages: int = 0,
    transcription_failed: int = 0,
) -> DocumentRecord:
    return DocumentRecord(
        entry=entry,
        category=category,
        status=status,
        pages=entry.pages if pages is None else pages,
        readable_pages=readable_pages,
        estimated_tokens=estimated_tokens,
        kind=kind,
        transcribed_pages=transcribed_pages,
        transcription_failed=transcription_failed,
    )


def read_docket(
    client: DocketClient, mkey: int, *, readings: ReadingLookup | None = None
) -> Docket:
    """Fetch the listing and every document; classify and extract; keep text for read ones.

    Decision 0056: there is no deny-list. Every entry is fetched and extracted unless its
    listing metadata alone rules it out (a photo-only entry, a non-PDF), or extraction finds
    it unreadable; the category never stops a document from being read.

    With ``readings`` (evidence version v2, S2.6 §8), each document's cached transcriptions
    are part of its text, so a scan with readings can now be read; and a photo-only entry is
    fetched and read like any other (decision W2). With ``readings=None`` (v1) this is S2's
    reader exactly: photo-only entries are skipped.
    """
    listing = parse_listing(client.listing_html(mkey), mkey=mkey)
    records: list[DocumentRecord] = []
    texts: dict[int, str] = {}
    readings_by_document: dict[int, dict[int, Transcription]] = {}
    for entry in listing.entries:
        category = document_category(entry.title)
        if entry.is_photo_only() and readings is None:
            records.append(_record(entry, category, "skipped: photo-only"))
        elif not entry.is_pdf():
            records.append(_record(entry, category, "unreadable: not a pdf"))
        else:
            try:
                content = client.document(mkey, entry.index, entry.href)
            except DocketError:
                records.append(_record(entry, category, "fetch failed"))
                continue
            document_readings = readings.for_document(content) if readings is not None else None
            if document_readings:
                readings_by_document[entry.index] = document_readings
            try:
                extracted = extract_pdf(content, readings=document_readings)
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
                        transcribed_pages=extracted.transcribed_pages,
                        transcription_failed=extracted.transcription_failed,
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
                        transcribed_pages=extracted.transcribed_pages,
                        transcription_failed=extracted.transcription_failed,
                    )
                )
                texts[entry.index] = extracted.text
    return Docket(
        mkey=mkey,
        listing=listing,
        documents=tuple(records),
        texts=texts,
        readings=readings_by_document,
    )
