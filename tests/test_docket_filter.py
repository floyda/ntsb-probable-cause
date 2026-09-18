"""Arm B's document filter: types, rank order, the deny-list (decisions 0022, 0038, 0039, 0043)."""

import pytest

from ntsb_probable_cause.docket import filter as filter_module
from ntsb_probable_cause.docket.filter import (
    ARM_B_RANK,
    ARM_B_TYPES,
    DENY_LIST,
    arm_b_documents,
    is_denied,
)
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord


def _entry(index: int, title: str) -> ListingEntry:
    return ListingEntry(
        index=index, title=title, pages=2, photos=0, doc_type="", extension="pdf", href="/x"
    )


def _docket() -> Docket:
    rows = [
        (1, "Party Submission - engine maker", "party_submission", "read", 5000),
        (2, "Weather Study", "weather", "read", 800),
        (3, "Photographs", "photos", "skipped: photo-only", 0),
        (4, "Powerplant Examination", "exam_site", "read", 1200),
        (5, "Pilot Operator Report 6120", "pilot_form_6120", "unreadable: scan", 0),
    ]
    records = tuple(
        DocumentRecord(
            entry=_entry(i, t),
            category=c,
            status=s,
            pages=2,
            readable_pages=2 if s == "read" else 0,
            estimated_tokens=tok,
            kind="born-digital" if s == "read" else None,
        )
        for i, t, c, s, tok in rows
    )
    listing = Listing(mkey=1, declared_items=5, entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=records, texts={1: "a", 2: "b", 4: "c"})


def test_deny_list_starts_empty_and_nothing_is_denied() -> None:
    assert frozenset() == DENY_LIST
    assert not is_denied("specialist_factual")


def test_published_filter_admits_read_documents_of_admitted_types_in_index_order_when_unranked() -> (  # noqa: E501
    None
):
    assert "photos" not in ARM_B_TYPES
    assert ARM_B_RANK == ()
    assert arm_b_documents(_docket()) == [1, 2, 4]


def test_unfiltered_admits_every_read_document() -> None:
    assert arm_b_documents(_docket(), variant="unfiltered") == [1, 2, 4]


def test_no_submissions_drops_party_submissions() -> None:
    assert arm_b_documents(_docket(), variant="no-submissions") == [2, 4]


def test_rank_order_sorts_by_type_then_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(filter_module, "ARM_B_RANK", ("weather", "exam_site", "party_submission"))
    assert arm_b_documents(_docket()) == [2, 4, 1]
