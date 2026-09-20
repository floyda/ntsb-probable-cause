"""Arm B's document filter: admission, size order, the deny-list (decisions 0022, 0038, 0039,
0043, 0048, 0052).
"""

import pytest

from ntsb_probable_cause.docket import filter as filter_module
from ntsb_probable_cause.docket.filter import (
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


_DEFAULT_ROWS = [
    (1, "Party Submission - engine maker", "party_submission", "read", 5000),
    (2, "Weather Study", "weather", "read", 800),
    (3, "Photographs", "photos", "skipped: photo-only", 0),
    (4, "Powerplant Examination", "exam_site", "read", 1200),
    (5, "Pilot Operator Report 6120", "pilot_form_6120", "unreadable: scan", 0),
]


def _docket_with(rows: list[tuple[int, str, str, str, int]]) -> Docket:
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
    listing = Listing(mkey=1, declared_items=len(rows), entries=tuple(r.entry for r in records))
    texts = {i: chr(ord("a") + n) for n, (i, _, _, s, _) in enumerate(rows) if s == "read"}
    return Docket(mkey=1, listing=listing, documents=records, texts=texts)


def _docket() -> Docket:
    return _docket_with(_DEFAULT_ROWS)


def test_deny_list_starts_empty_and_nothing_is_denied() -> None:
    # Empty default: the measurement populating this list (Task 16) has not run yet.
    assert frozenset() == DENY_LIST
    assert not is_denied("specialist_factual")


def test_is_denied_checks_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        filter_module, "DENY_LIST", frozenset(["specialist_factual", "medical_tox"])
    )
    assert is_denied("specialist_factual")
    assert is_denied("medical_tox")
    assert not is_denied("weather")


def test_a_read_photos_document_is_attached() -> None:
    # Decision 0052: admission is the extraction outcome, not the title-derived category.
    # A document categorised "photos" that nonetheless yielded readable text must not be
    # dropped for its category -- this is the whole point of the task.
    docket = _docket_with([(1, "Photographs", "photos", "read", 400)])
    assert arm_b_documents(docket) == [1]


@pytest.mark.parametrize(
    "status",
    ["unreadable: scan", "unreadable: not a pdf", "skipped: photo-only", "denied: write-up"],
)
def test_a_document_not_marked_read_is_never_attached(status: str) -> None:
    docket = _docket_with([(1, "Some Document", "exam_site", status, 400)])
    assert arm_b_documents(docket) == []


def test_published_filter_admits_every_read_document_smallest_first() -> None:
    # Read documents are index 1 (5000 tokens), 2 (800) and 4 (1200); smallest first.
    # Index 3 (skipped: photo-only) and 5 (unreadable: scan) are never attached.
    assert arm_b_documents(_docket()) == [2, 4, 1]


def test_no_submissions_drops_party_submissions() -> None:
    assert arm_b_documents(_docket(), variant="no-submissions") == [2, 4]


def test_no_submissions_excludes_nothing_else() -> None:
    # A read, non-submission document of any other category is still attached under
    # "no-submissions" -- the variant excludes exactly one category, nothing more.
    docket = _docket_with(
        [
            (1, "Party Submission - engine maker", "party_submission", "read", 900),
            (2, "Weather Study", "weather", "read", 900),
            (3, "Powerplant Examination", "exam_site", "read", 900),
            (4, "Photographs", "photos", "read", 900),
        ]
    )
    assert arm_b_documents(docket, variant="no-submissions") == [2, 3, 4]


def test_equal_size_documents_break_the_tie_by_listing_index() -> None:
    # Three read documents of equal measured size: nothing but listing index can order them.
    docket = _docket_with(
        [
            (1, "Party Submission - engine maker", "party_submission", "read", 900),
            (2, "Weather Study", "weather", "read", 900),
            (3, "Powerplant Examination", "exam_site", "read", 900),
        ]
    )
    assert arm_b_documents(docket) == [1, 2, 3]


def test_order_is_unaffected_by_a_documents_category() -> None:
    # The property decision 0048 buys: a misclassification cannot move a document in the
    # order, because the category is no longer consulted for it. Re-labelling every document
    # to the same category leaves the size-based order unchanged.
    before = arm_b_documents(_docket())
    relabelled = _docket_with(
        [
            (1, "Party Submission - engine maker", "exam_site", "read", 5000),
            (2, "Weather Study", "exam_site", "read", 800),
            (4, "Powerplant Examination", "exam_site", "read", 1200),
        ]
    )
    assert arm_b_documents(relabelled) == before == [2, 4, 1]
