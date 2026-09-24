"""scripts/analysis_handcheck.py: a private marking page, and counts-only scoring (0077)."""

import copy

import pytest
from scripts import analysis_handcheck

from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord

QUOTED = (
    "Examination of the engine revealed no mechanical anomalies"
    " that would have precluded normal operation."
)
ANALYSIS = QUOTED + " The pilot did not use the checklist before the flight."
CONCLUDED = "conclusion in the docket"


def _docket(text: str) -> Docket:
    entry = ListingEntry(
        index=1,
        title="Engine Examination Summary",
        pages=1,
        photos=0,
        doc_type="PDF",
        extension="pdf",
        href="x",
    )
    record = DocumentRecord(
        entry=entry,
        category="exam_site",
        status="read",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        kind="born-digital",
    )
    return Docket(
        mkey=7,
        listing=Listing(mkey=7, declared_items=1, entries=(entry,)),
        documents=(record,),
        texts={1: text},
    )


def _raw(record_fixtures: list[dict[str, object]]) -> dict[str, object]:
    raw = copy.deepcopy(record_fixtures[0])
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["analysisNarrative"] = ANALYSIS
    return raw


def test_a_shared_analysis_sentence_becomes_one_row_with_context(
    record_fixtures: list[dict[str, object]],
) -> None:
    text = f"[page 1 of 1]\nThe inspector noted fuel in both tanks. {QUOTED} The magneto held."
    rows = analysis_handcheck.sheet_rows(_raw(record_fixtures), _docket(text))
    assert len(rows) == 1
    (row,) = rows
    assert row.sentence.startswith("examination of the engine revealed")
    assert "fuel in both tanks" in row.before
    assert "magneto held" in row.after
    assert row.title == "Engine Examination Summary"
    assert row.category == "exam_site"


def test_a_document_without_a_shared_sentence_gives_no_row(
    record_fixtures: list[dict[str, object]],
) -> None:
    rows = analysis_handcheck.sheet_rows(_raw(record_fixtures), _docket("[page 1 of 1]\nNothing."))
    assert rows == []


def test_the_page_escapes_text_and_offers_the_two_marks() -> None:
    row = analysis_handcheck.SheetRow(
        case_id="X1",
        document=1,
        title="<b>Title</b>",
        category="other",
        sentence="a <script>sentence</script>",
        before="",
        after="",
        cause_in_case=False,
    )
    page = analysis_handcheck.render_page([row])
    assert "<script>sentence" not in page
    assert "&lt;script&gt;" in page
    assert 'value="quotes evidence"' in page
    assert f'value="{CONCLUDED}"' in page


def _sheet(n: int) -> list[dict[str, str]]:
    return [
        {"row": str(i), "category": "exam_site", "case_id": f"C{i % 17}"} for i in range(1, n + 1)
    ]


def _marks(conclusions: int) -> dict[int, str]:
    marks = dict.fromkeys(range(1, 37), "quotes evidence")
    return marks | dict.fromkeys(range(1, conclusions + 1), CONCLUDED)


def test_score_adopts_the_rule_at_five_conclusions() -> None:
    text = analysis_handcheck.score(_sheet(36), _marks(5))
    assert f"{CONCLUDED:<28} {5:3d}" in text
    assert "outcome: adopted" in text


def test_score_does_not_adopt_at_six_conclusions() -> None:
    text = analysis_handcheck.score(_sheet(36), _marks(6))
    assert "outcome: not adopted" in text


def test_score_refuses_the_rule_when_the_sheet_is_not_the_36() -> None:
    marks = dict.fromkeys(range(1, 36), "quotes evidence")
    text = analysis_handcheck.score(_sheet(35), marks)
    assert "outcome: not applied" in text


def test_score_refuses_an_unmarked_row() -> None:
    with pytest.raises(SystemExit, match="unmarked"):
        analysis_handcheck.score(_sheet(36), dict.fromkeys(range(1, 36), "quotes evidence"))
