"""scripts/page_kinds.py: counts only, development only, never a fetch (S2.6 §6.2 step 1)."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest
from scripts import page_kinds
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.pages import PageFacts, document_facts


def _facts(chars: int, images: int = 0, rotation: int = 0, *encodings: str) -> PageFacts:
    return PageFacts(chars=chars, images=images, rotation=rotation, encodings=encodings)


def test_tally_counts_kinds_by_stratum_and_image_only_details() -> None:
    tally = page_kinds.Tally()
    tally.add_document(
        "fatal",
        (
            _facts(400),
            _facts(0, 1, 90, "fax (CCITT)"),
            _facts(0, 6, 0, "JPEG"),
            _facts(400, 1, 0, "JPEG"),
        ),
    )
    tally.add_document("non-fatal", (_facts(0), _facts(400)))
    assert tally.pages[("fatal", "image only")] == 2
    assert tally.pages[("non-fatal", "blank")] == 1
    assert tally.rotated["fatal"] == 1
    assert tally.tiled["fatal"] == 1
    assert tally.encodings["fax (CCITT)"] == 1
    assert tally.mixed_documents == 1  # the fatal document mixes three non-blank kinds
    assert tally.pdfs == 2


def test_report_holds_counts_and_no_case_number() -> None:
    tally = page_kinds.Tally()
    tally.cases.update({"fatal": 1})
    tally.add_document("fatal", (_facts(0, 1, 0, "JPEG"),))
    text = page_kinds.report(tally, "dev-400")
    assert "image only" in text
    assert "## limits" in text
    assert not re.search(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}[A-Z]?\b", text)  # no case number


def test_held_out_samples_are_refused() -> None:
    with pytest.raises(SystemExit, match="development"):
        page_kinds.main(["--sample", "heldout-400"])


def test_frame_rows_carry_the_page_and_its_kind(tmp_path: Path) -> None:
    rows = page_kinds.frame_rows(
        case_id="X1", mkey=7, fatal=True, document=2, facts=(_facts(0, 1, 0, "JPEG"),)
    )
    assert rows == [
        {
            "case_id": "X1",
            "mkey": 7,
            "fatal": True,
            "document": 2,
            "page": 1,
            "pages": 1,
            "kind": "image only",
            "chars": 0,
            "images": 1,
            "rotation": 0,
            "encodings": ["JPEG"],
            "photo_only": False,
        }
    ]
    out = tmp_path / "frame.jsonl"
    page_kinds.write_frame(out, rows)
    assert json.loads(out.read_text().splitlines()[0])["kind"] == "image only"


def test_document_facts_of_a_built_pdf_feed_the_tally() -> None:
    tally = page_kinds.Tally()
    tally.add_document("fatal", document_facts(build_pdf([PageSpec(images=("/JPXDecode",))])))
    assert tally.encodings["JPEG 2000"] == 1


def _listing_row(idx: int, *, pages: int, photos: int, href: str, dtype: str = "Text/Pdf") -> str:
    return (
        f"<tr><td><b>{idx}</b></td><td>Document {idx}</td><td><b>{pages}</b></td>"
        f"<td>{photos}</td><td>{dtype}</td>"
        f'<td><a target="_blank" href="{href}"></a></td></tr>'
    )


def _seed_cache(
    cache_dir: Path, mkey: int, listing_html: str, documents: dict[int, tuple[bytes, str]]
) -> None:
    """Write a docket cache directly in ``DocketClient``'s own layout (never through a fetch).

    Mirrors ``docket/client.py``'s ``<mkey>/listing.html``, ``<mkey>/<index>.bin`` and
    ``<mkey>/fetch.json`` (each entry's ``sha256``, and a document's ``href``), copying the
    shape ``tests/fixtures/docket/ERA17LA217/`` uses for a real docket. An index with no
    entry here is left uncached, so a client reading it hits the offline transport.
    """
    folder = cache_dir / str(mkey)
    folder.mkdir(parents=True)
    listing_bytes = listing_html.encode()
    (folder / "listing.html").write_bytes(listing_bytes)
    fetch: dict[str, object] = {
        "listing": {"sha256": hashlib.sha256(listing_bytes).hexdigest()},
        "documents": {},
    }
    for index, (data, href) in documents.items():
        (folder / f"{index}.bin").write_bytes(data)
        fetch["documents"][str(index)] = {  # type: ignore[index]
            "sha256": hashlib.sha256(data).hexdigest(),
            "href": href,
        }
    (folder / "fetch.json").write_text(json.dumps(fetch))


_HREF = {
    i: f"/Docket/Document/docBLOB?ID={i}&FileExtension=.pdf&FileName=d{i}.pdf" for i in range(1, 5)
}


def _seed_sweep_case(tmp_path: Path) -> tuple[int, int]:
    """A cached docket with a plain document (1), a photo-only one (2, entry only), a document
    whose cached bytes are not a PDF (3), and one never cached at all (4); plus a second,
    entirely uncached case (its listing itself is missing).
    """
    mkey = 111111
    uncached_mkey = 222222
    listing_html = (
        "<html>Docket Items: 4<table>"
        + "".join(
            [
                _listing_row(1, pages=1, photos=0, href=_HREF[1]),
                _listing_row(2, pages=1, photos=1, href=_HREF[2]),  # photo-only
                _listing_row(3, pages=1, photos=0, href=_HREF[3]),
                _listing_row(4, pages=1, photos=0, href=_HREF[4]),  # never cached
            ]
        )
        + "</table></html>"
    )
    plain_pdf = build_pdf([PageSpec(text="Examination found nothing remarkable in the wreckage.")])
    photo_pdf = build_pdf([PageSpec(images=("/DCTDecode",))])
    _seed_cache(
        tmp_path,
        mkey,
        listing_html,
        {
            1: (plain_pdf, _HREF[1]),
            2: (photo_pdf, _HREF[2]),
            3: (b"not a pdf at all", _HREF[3]),
            # 4 deliberately left uncached
        },
    )
    return mkey, uncached_mkey


def test_sweep_reads_the_cache_and_classifies_every_outcome(tmp_path: Path) -> None:
    mkey, uncached_mkey = _seed_sweep_case(tmp_path)
    records = [
        {"mKey": mkey, "highestInjuryLevel": "Fatal", "ntsbNumber": "TST01"},
        {"mKey": uncached_mkey, "highestInjuryLevel": "Non-Fatal", "ntsbNumber": "TST02"},
    ]
    client = DocketClient(tmp_path, transport=page_kinds._offline(), sleep=lambda _s: None)

    tally, rows = page_kinds.sweep(records, client, fetch_photo_only=None)

    assert tally.not_cached == 1  # the second case's listing is not in the cache
    assert tally.fetch_failed == 1  # entry 4: never cached, offline transport refuses it
    assert tally.not_pdf == 1  # entry 3: cached bytes are not a PDF
    assert tally.pdfs == 1  # only entry 1 is counted as a read document
    assert tally.photo_only_entries["fatal"] == 1  # entry 2, skipped rather than read
    assert tally.photo_only_pages["fatal"] == 1
    assert tally.photo_pdfs == 0  # never fetched: fetch_photo_only was None
    assert [r["document"] for r in rows] == [1]
    assert rows[0]["case_id"] == "TST01"


def test_sweep_fetches_photo_only_documents_apart_when_asked(tmp_path: Path) -> None:
    mkey, uncached_mkey = _seed_sweep_case(tmp_path)
    records = [
        {"mKey": mkey, "highestInjuryLevel": "Fatal", "ntsbNumber": "TST01"},
        {"mKey": uncached_mkey, "highestInjuryLevel": "Non-Fatal", "ntsbNumber": "TST02"},
    ]
    client = DocketClient(tmp_path, transport=page_kinds._offline(), sleep=lambda _s: None)
    # Reads the same cache the photo-only document was seeded into; the offline transport is
    # never actually reached because entry 2 is already cached (routing test, not a network test).
    photo_client = DocketClient(tmp_path, transport=page_kinds._offline(), sleep=lambda _s: None)

    tally, rows = page_kinds.sweep(records, client, fetch_photo_only=photo_client)

    assert tally.pdfs == 1  # entry 1 only; the photo-only document is counted apart
    assert tally.photo_pdfs == 1
    assert tally.photo_pages[("fatal", "image only")] == 1
    assert tally.fetch_failed == 1  # entry 4 is still uncached regardless of the photo routing
    assert tally.not_pdf == 1
    assert {r["document"] for r in rows} == {1, 2}
    (photo_row,) = [r for r in rows if r["document"] == 2]
    assert photo_row["photo_only"] is True


def test_photo_only_documents_are_counted_apart_and_framed_as_such() -> None:
    """Decision W2: fetched photo-only documents never change S2's page-kind counts."""
    tally = page_kinds.Tally()
    tally.add_photo_document("fatal", (_facts(0, 1, 0, "JPEG"), _facts(0, 1, 0, "JPEG")))
    assert tally.photo_pages[("fatal", "image only")] == 2
    assert tally.pages == Counter()
    assert tally.photo_pdfs == 1
    (row,) = page_kinds.frame_rows(
        case_id="X1", mkey=7, fatal=True, document=5, facts=(_facts(0, 1),), photo_only=True
    )
    assert row["photo_only"] is True
