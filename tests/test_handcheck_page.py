"""The local hand-check marking page: unredacted titles, marks-only export, and the merge back
into the committed (redacted) sheet (decisions 0048 item 4, 0049).

Invented case ids, titles and names throughout, per house rules.
"""

import csv
import html
import re
from pathlib import Path

import pytest
import scripts.handcheck_page as hp
import scripts.make_docket_fixture as mdf
from tests.test_docket_fixtures import _cache_case, _dev_env

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.settings import Settings

# --- sample_rows: the same sample as the committed sheet, unredacted, with real links ---


def test_sample_rows_is_unredacted_and_matches_the_stratified_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A title the committed sheet would redact appears whole, with a real document link."""
    docket_dir = _dev_env(
        tmp_path,
        monkeypatch,
        [
            ("DEV0001", 1, "2015-01-01", {"ntsbNumber": "DEV0001", "mKey": 1}),
            ("DEV0002", 2, "2016-01-01", {"ntsbNumber": "DEV0002", "mKey": 2}),
        ],
    )
    # "Ferrowick" is invented and outside both the committed vocabulary and any dictionary,
    # so the committed sheet's own redaction pass would replace it with "[proper noun]".
    _cache_case(docket_dir, 1, [(1, "Statement of Ferrowick", 1, 0, "Report", b"x")])
    _cache_case(docket_dir, 2, [(1, "Engine Examination", 1, 0, "Report", b"y")])

    rows = hp.sample_rows(Settings())

    assert {r.title for r in rows} == {"Statement of Ferrowick", "Engine Examination"}
    assert [r.row for r in sorted(rows, key=lambda r: r.row)] == list(range(1, len(rows) + 1))
    by_title = {r.title: r for r in rows}
    ferrowick = by_title["Statement of Ferrowick"]
    assert ferrowick.category == "conversation_statement"
    assert ferrowick.docket_url == sources.docket_url(1)
    assert ferrowick.document_url == sources.docket_document_url(
        "/Docket/Document/docBLOB?ProjectID=1&Index=1&FileExtension=pdf"
    )


def test_sample_rows_omits_a_document_link_when_the_listing_has_no_href(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docket_dir = _dev_env(
        tmp_path, monkeypatch, [("DEV0001", 1, "2015-01-01", {"ntsbNumber": "DEV0001", "mKey": 1})]
    )
    # `data=None` in `_cache_case` means no href -- an entry the listing carries no link for.
    _cache_case(docket_dir, 1, [(1, "Weather Study", 1, 0, "Report", None)])

    rows = hp.sample_rows(Settings())

    assert len(rows) == 1
    assert rows[0].document_url is None
    assert rows[0].docket_url == sources.docket_url(1)


# --- rows_from_listing + rendering: a small synthetic listing, never redacted ---


def _synthetic_listing() -> Listing:
    return Listing(
        mkey=555,
        declared_items=2,
        entries=(
            ListingEntry(
                index=3,
                title="Statement of Casimir Oduya",
                pages=2,
                photos=0,
                doc_type="Adobe PDF file",
                extension="pdf",
                href="/Docket/Document/docBLOB?ID=9&FileExtension=.PDF",
            ),
            ListingEntry(
                index=7,
                title="Weather Study",
                pages=1,
                photos=0,
                doc_type="Adobe PDF file",
                extension="pdf",
                href="",
            ),
        ),
    )


def test_rows_from_listing_carries_the_real_title_and_the_listing_index_as_row() -> None:
    rows = hp.rows_from_listing(_synthetic_listing())
    assert [r.row for r in rows] == [3, 7]
    assert rows[0].title == "Statement of Casimir Oduya"
    assert rows[0].category == "conversation_statement"
    assert rows[0].document_url == sources.docket_document_url(
        "/Docket/Document/docBLOB?ID=9&FileExtension=.PDF"
    )
    assert rows[1].document_url is None


def test_marking_page_shows_the_unredacted_title_links_and_controls_for_every_row() -> None:
    rows = hp.rows_from_listing(_synthetic_listing())
    page = hp.render_marking_page(rows)

    assert "Statement of Casimir Oduya" in page
    assert sources.docket_url(555) in page
    expected_link = html.escape(
        sources.docket_document_url("/Docket/Document/docBLOB?ID=9&FileExtension=.PDF"), quote=True
    )
    assert expected_link in page
    assert 'name="is_photo-3"' in page
    assert 'name="could_hold_conclusions-3"' in page
    assert 'name="author-3"' in page
    for option in hp.AUTHOR_OPTIONS:
        assert f'value="{option}"' in page
    assert 'name="notes-3"' in page
    assert "3 of 2 marked" not in page  # progress starts at 0, not a pre-filled count
    assert "0 of 2 marked" in page
    assert "localStorage" not in page.split("<script>", 1)[0]  # only the script uses storage


def test_marking_page_is_fully_inline_with_no_external_resources() -> None:
    page = hp.render_marking_page(hp.rows_from_listing(_synthetic_listing()))
    assert "<script src" not in page
    assert "<link " not in page
    assert "cdn." not in page.lower()
    urls = re.findall(r'https?://[^\s"\'<>]+', page)
    assert urls, "the docket links should be present"
    assert all(url.startswith("https://data.ntsb.gov") for url in urls)


def test_marking_page_says_nothing_is_lost_and_never_celebrates() -> None:
    page = hp.render_marking_page(hp.rows_from_listing(_synthetic_listing()))
    assert "loses nothing" in page
    for word in ("\U0001f389", "✅", "great job", "congrat"):
        assert word.lower() not in page.lower()


def test_case_page_lists_documents_with_no_marking_controls() -> None:
    rows = hp.rows_from_listing(_synthetic_listing())
    page = hp.render_case_page("DEV0099", 555, rows)

    assert "Statement of Casimir Oduya" in page
    assert "Weather Study" in page
    assert 'name="is_photo-3"' not in page
    assert "is_photo" not in page
    assert "exam_site" in page  # the allowed-categories note
    assert "specialist_factual" in page


# --- The exported CSV: marks only, never a title (task requirement, checked statically) ---


def test_exported_csv_javascript_never_references_a_row_title() -> None:
    distinctive_title = "Statement of Zzyxvale Ferrowick"
    rows = hp.rows_from_listing(
        Listing(
            mkey=1,
            declared_items=1,
            entries=(
                ListingEntry(
                    index=1,
                    title=distinctive_title,
                    pages=1,
                    photos=0,
                    doc_type="Adobe PDF file",
                    extension="pdf",
                    href="/Docket/Document/docBLOB?ID=1",
                ),
            ),
        )
    )
    page = hp.render_marking_page(rows)
    assert distinctive_title in page  # it is genuinely on the page, for display

    start = page.index("/* CSV EXPORT")
    end = page.index("/* END CSV EXPORT */") + len("/* END CSV EXPORT */")
    export_block = page[start:end]

    assert distinctive_title not in export_block
    assert "row,is_photo,could_hold_conclusions,author,notes" in export_block
    assert ".title" not in export_block


# --- case_documents: cache-only, listing order ---


def test_case_documents_reads_the_cache_only_in_listing_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docket_dir = _dev_env(
        tmp_path, monkeypatch, [("DEV0003", 3, "2017-01-01", {"ntsbNumber": "DEV0003", "mKey": 3})]
    )
    _cache_case(
        docket_dir,
        3,
        [
            (1, "Engine Examination", 1, 0, "Report", b"a"),
            (2, "Weather Study", 1, 0, "Report", b"b"),
        ],
    )

    mkey, rows = hp.case_documents(Settings(), "DEV0003")

    assert mkey == 3
    assert [r.title for r in rows] == ["Engine Examination", "Weather Study"]
    assert rows[0].docket_url == sources.docket_url(3)


def test_case_documents_refuses_an_id_outside_the_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dev_env(
        tmp_path, monkeypatch, [("DEV0004", 4, "2018-01-01", {"ntsbNumber": "DEV0004", "mKey": 4})]
    )
    with pytest.raises(FixtureError, match="DEV0999"):
        hp.case_documents(Settings(), "DEV0999")


# --- merge: fold marks into the committed sheet by row number, titles untouched ---


def _write_sheet(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["title", "doc_type", "category", *hp.MARK_COLUMNS],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_marks(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(hp.MARKS_CSV_HEADER), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _blank_row(title: str, doc_type: str, category: str) -> dict[str, str]:
    return {
        "title": title,
        "doc_type": doc_type,
        "category": category,
        "is_photo": "",
        "could_hold_conclusions": "",
        "author": "",
        "notes": "",
    }


def _mark(
    row: int, is_photo: str, could_hold_conclusions: str, author: str, notes: str = ""
) -> dict[str, object]:
    return {
        "row": row,
        "is_photo": is_photo,
        "could_hold_conclusions": could_hold_conclusions,
        "author": author,
        "notes": notes,
    }


def test_merge_maps_marks_to_the_right_rows_and_leaves_titles_untouched(tmp_path: Path) -> None:
    sheet = tmp_path / "title_handcheck.csv"
    _write_sheet(
        sheet,
        [
            _blank_row("[proper noun] SPOT Data", "Comma-delimited data file", "atc_radar_data"),
            _blank_row("Weather Study", "Adobe PDF file", "weather"),
            _blank_row("Engine Examination", "Adobe PDF file", "exam_site"),
        ],
    )
    marks = tmp_path / "marks.csv"
    _write_marks(
        marks,
        [
            _mark(1, "n", "n", "independent", "GPS track, not a photo"),
            _mark(3, "n", "y", "investigation"),
        ],
    )

    updated, total = hp.merge_marks(sheet, marks)
    assert (updated, total) == (2, 3)

    with sheet.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["title"] for r in rows] == [
        "[proper noun] SPOT Data",
        "Weather Study",
        "Engine Examination",
    ]
    assert [r["doc_type"] for r in rows] == [
        "Comma-delimited data file",
        "Adobe PDF file",
        "Adobe PDF file",
    ]
    assert [r["category"] for r in rows] == ["atc_radar_data", "weather", "exam_site"]
    assert rows[0]["author"] == "independent"
    assert rows[0]["notes"] == "GPS track, not a photo"
    # row 2 was never in the marks file: it stays exactly as it was, marks blank.
    assert rows[1]["is_photo"] == rows[1]["could_hold_conclusions"] == rows[1]["author"] == ""
    assert rows[2]["could_hold_conclusions"] == "y"


def test_merge_refuses_a_row_number_outside_the_sheet(tmp_path: Path) -> None:
    sheet = tmp_path / "title_handcheck.csv"
    _write_sheet(sheet, [_blank_row("Weather Study", "Adobe PDF file", "weather")])
    marks = tmp_path / "marks.csv"
    _write_marks(marks, [_mark(99, "n", "n", "unclear")])
    with pytest.raises(FixtureError, match="outside the sheet"):
        hp.merge_marks(sheet, marks)


def test_merge_refuses_a_non_integer_row_number(tmp_path: Path) -> None:
    sheet = tmp_path / "title_handcheck.csv"
    _write_sheet(sheet, [_blank_row("Weather Study", "Adobe PDF file", "weather")])
    marks = tmp_path / "marks.csv"
    _write_marks(
        marks,
        [{**_mark(1, "n", "n", "unclear"), "row": "one"}],
    )
    with pytest.raises(FixtureError, match="not an integer"):
        hp.merge_marks(sheet, marks)


def test_merge_refuses_a_marks_csv_missing_a_required_column(tmp_path: Path) -> None:
    sheet = tmp_path / "title_handcheck.csv"
    _write_sheet(sheet, [_blank_row("Weather Study", "Adobe PDF file", "weather")])
    marks = tmp_path / "marks.csv"
    with marks.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row", "is_photo"], lineterminator="\n")
        writer.writeheader()
        writer.writerow({"row": 1, "is_photo": "n"})
    with pytest.raises(FixtureError, match="missing column"):
        hp.merge_marks(sheet, marks)


def test_merged_sheet_carries_no_title_text_from_the_marks_file(tmp_path: Path) -> None:
    """The marks CSV the owner exports has no title column -- merge never adds one either."""
    sheet = tmp_path / "title_handcheck.csv"
    _write_sheet(sheet, [_blank_row("Engine Examination", "Adobe PDF file", "exam_site")])
    marks = tmp_path / "marks.csv"
    _write_marks(marks, [_mark(1, "n", "y", "party")])
    assert marks.read_text().splitlines()[0] == ",".join(hp.MARKS_CSV_HEADER)  # no title column
    hp.merge_marks(sheet, marks)
    assert sheet.read_text().splitlines()[0] == "title,doc_type,category," + ",".join(
        hp.MARK_COLUMNS
    )


# --- CLI ---


def test_main_dispatches_page_and_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docket_dir = _dev_env(
        tmp_path, monkeypatch, [("DEV0005", 5, "2019-01-01", {"ntsbNumber": "DEV0005", "mKey": 5})]
    )
    _cache_case(docket_dir, 5, [(1, "Engine Examination", 1, 0, "Report", b"z")])
    fixtures_root = tmp_path / "fixtures"
    fixtures_root.mkdir()
    monkeypatch.setattr(mdf, "FIXTURES", fixtures_root)
    monkeypatch.setattr(hp, "SHEET_PATH", fixtures_root / "title_handcheck.csv")
    _write_sheet(
        fixtures_root / "title_handcheck.csv",
        [_blank_row("[proper noun] Examination", "Adobe PDF file", "exam_site")],
    )

    out = tmp_path / "out" / "index.html"
    assert hp.main(["page", "--out", str(out), "--case", "DEV0005"]) == 0
    assert out.is_file()
    assert (out.with_name("dev0005.html")).is_file()

    marks = tmp_path / "marks.csv"
    _write_marks(marks, [_mark(1, "n", "y", "party")])
    assert hp.main(["merge", str(marks)]) == 0
    merged = (fixtures_root / "title_handcheck.csv").read_text()
    assert "[proper noun] Examination" in merged  # untouched
    assert "party" in merged


def test_page_help_names_the_default_output_path(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        hp.main(["page", "--help"])
    out = capsys.readouterr().out
    assert str(hp.DEFAULT_OUT) in out


def test_main_reports_a_fixture_error_and_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sheet = tmp_path / "title_handcheck.csv"
    _write_sheet(sheet, [_blank_row("Weather Study", "Adobe PDF file", "weather")])
    marks = tmp_path / "marks.csv"
    _write_marks(marks, [_mark(5, "n", "n", "unclear")])
    assert hp.main(["merge", str(marks), "--sheet", str(sheet)]) == 1
    assert "outside the sheet" in capsys.readouterr().err


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        hp.main([])
