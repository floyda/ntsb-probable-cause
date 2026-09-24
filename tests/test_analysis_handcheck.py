"""scripts/analysis_handcheck.py: a private marking page, and counts-only scoring (0077)."""

import copy
import csv
from pathlib import Path

import pytest
from scripts import analysis_handcheck

from ntsb_probable_cause.docket.attach import prepare_attachment
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.records.guard import find_leaks

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


def _two_document_docket(text1: str, text2: str) -> Docket:
    entry1 = ListingEntry(
        index=1, title="Doc A", pages=1, photos=0, doc_type="PDF", extension="pdf", href="x"
    )
    entry2 = ListingEntry(
        index=2, title="Doc B", pages=1, photos=0, doc_type="PDF", extension="pdf", href="y"
    )
    record1 = DocumentRecord(
        entry=entry1,
        category="exam_site",
        status="read",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        kind="born-digital",
    )
    record2 = DocumentRecord(
        entry=entry2,
        category="party_submission",
        status="read",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        kind="born-digital",
    )
    return Docket(
        mkey=7,
        listing=Listing(mkey=7, declared_items=2, entries=(entry1, entry2)),
        documents=(record1, record2),
        texts={1: text1, 2: text2},
    )


def test_sheet_rows_counts_the_same_sentences_as_the_docket_leak_scan_method(
    record_fixtures: list[dict[str, object]],
) -> None:
    """``sheet_rows`` claims to mirror ``docket_leak_scan.sweep``'s counting method (module

    docstring); this checks the claim rather than trusting it: the same distinct sentence
    leaks, found the scan's way -- one ``DOCUMENTS`` haystack, the documents joined the way
    ``records/guard.py:_as_text`` joins a tuple evidence value (``" | ".join``) -- as
    ``sheet_rows`` returns rows for, including a sentence (``QUOTED``) that appears in both
    documents and must count once, not twice.
    """
    checklist = "The pilot did not use the checklist before the flight."
    analysis = f"{QUOTED} {checklist}"
    raw = copy.deepcopy(record_fixtures[0])
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["analysisNarrative"] = analysis
    text1 = f"[page 1 of 1]\nAlpha detail. {QUOTED} Bravo detail."
    text2 = f"[page 1 of 1]\nCharlie detail. {QUOTED} Delta detail. {checklist}"
    docket = _two_document_docket(text1, text2)

    rows = analysis_handcheck.sheet_rows(raw, docket)

    attachment = prepare_attachment(raw, docket)
    readable = [r.entry.index for r in docket.documents if r.status == "read"]
    joined = " | ".join(attachment.document_texts[i] for i in readable)
    leaks = find_leaks(
        {analysis_handcheck.DOCUMENTS: joined},
        {analysis_handcheck.ANALYSIS: analysis},
        (),
        exemptions=frozenset(),
    )
    distinct_sentences = {leak.fragment for leak in leaks if leak.kind == "sentence"}

    assert len(rows) == len(distinct_sentences)
    assert {row.sentence for row in rows} == distinct_sentences


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


def test_main_sheet_refuses_a_non_development_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    with pytest.raises(SystemExit, match="development cases only"):
        analysis_handcheck.main(["sheet", "--sample", "heldout-400"])


def test_main_sheet_skips_a_case_with_no_mkey_and_still_writes_the_sheet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The per-case loop's ``DocketError``/``LeakageError`` skip path, ``write_sheet`` and the

    printed summary -- driven without a real ``cases.parquet`` or docket cache by monkeypatching
    ``sample_ids`` and ``load_cases`` (both plain module-level names ``main`` calls directly), so
    no network access or real dev-400 fixture data is needed. ``mKey`` missing makes
    ``_read_docket`` raise ``DocketError`` before any reader is touched, so ``CachedDocketReader``
    is exercised (constructed, never asked to read) rather than mocked away.
    """
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(analysis_handcheck, "sample_ids", lambda _name: ("X1",))
    monkeypatch.setattr(
        analysis_handcheck, "load_cases", lambda _processed, _ids: [{"ntsbNumber": "X1"}]
    )

    assert analysis_handcheck.main(["sheet", "--sample", "dev-400"]) == 0

    out = capsys.readouterr().out
    assert "0 sentences in 0 cases; 1 cases skipped; page at" in out
    folder = tmp_path / "handcheck" / "s26-analysis"
    assert (folder / "index.html").is_file()
    assert (folder / "sheet.csv").read_text().strip().splitlines() == [
        "row,case_id,document,title,category,sentence,before,after,cause_in_case"
    ]


def test_main_sheet_writes_a_matched_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
) -> None:
    """The per-case loop's success path: ``sheet_rows`` finding a row, through ``main``."""
    raw = _raw(record_fixtures)
    text = f"[page 1 of 1]\nThe inspector noted fuel in both tanks. {QUOTED} The magneto held."
    docket = _docket(text)

    class _FakeReader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def read(self, _mkey: int) -> Docket:
            return docket

    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(analysis_handcheck, "sample_ids", lambda _name: (raw["ntsbNumber"],))
    monkeypatch.setattr(analysis_handcheck, "load_cases", lambda _processed, _ids: [raw])
    monkeypatch.setattr(analysis_handcheck, "CachedDocketReader", _FakeReader)

    assert analysis_handcheck.main(["sheet", "--sample", "dev-400"]) == 0

    out = capsys.readouterr().out
    assert "1 sentences in 1 cases; 0 cases skipped; page at" in out
    sheet_path = tmp_path / "handcheck" / "s26-analysis" / "sheet.csv"
    (row,) = list(csv.DictReader(sheet_path.open(newline="")))
    assert row["case_id"] == raw["ntsbNumber"]


def test_main_score_reads_the_sheet_and_marks_and_writes_the_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ``score`` branch's file I/O: the committed ``sheet.csv``, ``read_marks`` on a

    downloaded marks CSV, and ``--out``.
    """
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    folder = tmp_path / "handcheck" / "s26-analysis"
    folder.mkdir(parents=True)
    with (folder / "sheet.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row", "case_id", "category"])
        writer.writeheader()
        for i in range(1, 37):
            writer.writerow({"row": i, "case_id": f"C{i % 17}", "category": "exam_site"})
    marks_path = tmp_path / "marks.csv"
    with marks_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row", "mark", "notes"])
        writer.writeheader()
        for i in range(1, 37):
            writer.writerow({"row": i, "mark": analysis_handcheck.QUOTES, "notes": ""})
    out_path = tmp_path / "out.txt"

    assert analysis_handcheck.main(["score", str(marks_path), "--out", str(out_path)]) == 0

    assert "outcome: adopted" in out_path.read_text()
