"""scripts/page_kinds.py: counts only, development only, never a fetch (S2.6 §6.2 step 1)."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest
from scripts import page_kinds
from tests.pdf_builder import PageSpec, build_pdf

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
