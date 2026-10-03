"""Docket facts and the probe's balanced case sample (task 1)."""

import pytest
from scripts.s3_probe.cases import CaseInfo, DocketFacts, facts, has_scan, select

from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.scoring.samples import sample_ids


def _entry(index: int) -> ListingEntry:
    return ListingEntry(
        index=index,
        title=f"doc {index}",
        pages=1,
        photos=0,
        doc_type="",
        extension="pdf",
        href="/x",
    )


def _docket(rows: list[tuple[int, str, str | None, int, int]]) -> Docket:
    """Build a docket from ``(index, status, kind, pages, transcribed_pages)`` rows."""
    records = tuple(
        DocumentRecord(
            entry=_entry(index),
            category="exam_site",
            status=status,
            pages=pages,
            readable_pages=pages if status == "read" else 0,
            estimated_tokens=100,
            kind=kind,
            transcribed_pages=transcribed_pages,
        )
        for index, status, kind, pages, transcribed_pages in rows
    )
    listing = Listing(mkey=1, declared_items=len(rows), entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=records, texts={})


def test_facts_reads_every_document_in_listing_order() -> None:
    docket = _docket(
        [
            (1, "read", "born-digital", 3, 0),
            (2, "unreadable: scan", "scan", 5, 2),
        ]
    )
    result = facts(docket)
    assert result == (
        DocketFacts(
            index=1,
            kind="born-digital",
            pages=3,
            readable_pages=3,
            estimated_tokens=100,
            transcribed_pages=0,
            status="read",
        ),
        DocketFacts(
            index=2,
            kind="scan",
            pages=5,
            readable_pages=0,
            estimated_tokens=100,
            transcribed_pages=2,
            status="unreadable: scan",
        ),
    )


@pytest.mark.parametrize(
    ("kind", "transcribed_pages", "expected"),
    [
        ("born-digital", 0, False),
        ("born-digital", 3, False),
        ("scan", 0, False),
        ("scan", 1, True),
        ("scan", 4, True),
        ("partial", 0, False),
        ("partial", 1, True),
        (None, 0, False),
    ],
)
def test_has_scan_truth_table(kind: str | None, transcribed_pages: int, expected: bool) -> None:
    one = DocketFacts(
        index=1,
        kind=kind,  # type: ignore[arg-type]
        pages=1,
        readable_pages=1,
        estimated_tokens=1,
        transcribed_pages=transcribed_pages,
        status="read",
    )
    assert has_scan((one,)) is expected


def test_has_scan_true_if_any_document_qualifies() -> None:
    no_scan = DocketFacts(
        index=1,
        kind="born-digital",
        pages=1,
        readable_pages=1,
        estimated_tokens=1,
        transcribed_pages=0,
        status="read",
    )
    a_scan = DocketFacts(
        index=2,
        kind="scan",
        pages=2,
        readable_pages=0,
        estimated_tokens=1,
        transcribed_pages=2,
        status="unreadable: scan",
    )
    assert has_scan((no_scan, a_scan)) is True


def test_has_scan_false_with_no_documents() -> None:
    assert has_scan(()) is False


def _dev_ids(n: int) -> list[str]:
    return list(sample_ids("dev-400"))[:n]


def _candidates(per_cell: int) -> list[CaseInfo]:
    ids = _dev_ids(4 * per_cell)
    cells = [(False, False), (False, True), (True, False), (True, True)]
    candidates: list[CaseInfo] = []
    for cell_index, (fatal, scan) in enumerate(cells):
        cell_ids = ids[cell_index * per_cell : (cell_index + 1) * per_cell]
        candidates.extend(CaseInfo(case_id=cid, fatal=fatal, has_scan=scan) for cid in cell_ids)
    return candidates


def test_select_is_deterministic_for_a_seed() -> None:
    candidates = _candidates(per_cell=6)
    first = select(candidates, per_cell=5, seed=20260929)
    second = select(candidates, per_cell=5, seed=20260929)
    assert first == second


def test_select_returns_a_different_choice_for_a_different_seed() -> None:
    candidates = _candidates(per_cell=6)
    first = select(candidates, per_cell=5, seed=20260929)
    second = select(candidates, per_cell=5, seed=1)
    assert first != second


def test_select_draws_per_cell_from_each_cell_only() -> None:
    per_cell = 5
    candidates = _candidates(per_cell=8)
    by_id = {c.case_id: c for c in candidates}
    chosen = select(candidates, per_cell=per_cell, seed=20260929)
    assert len(chosen) == 4 * per_cell
    assert len(set(chosen)) == len(chosen)
    counts: dict[tuple[bool, bool], int] = {}
    for case_id in chosen:
        cell = (by_id[case_id].fatal, by_id[case_id].has_scan)
        counts[cell] = counts.get(cell, 0) + 1
    assert counts == {(False, False): 5, (False, True): 5, (True, False): 5, (True, True): 5}


def test_select_raises_on_a_short_cell() -> None:
    per_cell = 5
    candidates = _candidates(per_cell=per_cell)
    # Drop exactly one candidate from the fatal=True, has_scan=True cell; every other cell
    # keeps its full complement.
    dropped = next(c for c in candidates if c.fatal is True and c.has_scan is True)
    short = [c for c in candidates if c != dropped]
    with pytest.raises(ValueError, match=r"fatal=True has_scan=True"):
        select(short, per_cell=per_cell, seed=20260929)


def test_select_refuses_a_non_dev_400_id() -> None:
    candidates = _candidates(per_cell=5)
    candidates[0] = CaseInfo(case_id="NOT-A-DEV-400-ID", fatal=False, has_scan=False)
    with pytest.raises(ValueError, match="not in dev-400"):
        select(candidates, per_cell=5, seed=20260929)
