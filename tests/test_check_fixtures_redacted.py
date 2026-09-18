"""The docket text fixture check: every committed document text names its reviewer (0037)."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from scripts.check_fixtures_redacted import (
    docket_fixture_name_problems,
    docket_fixture_problems,
    title_looks_like_a_name,
)


def test_docket_text_fixture_without_reviewed_by_is_a_problem(tmp_path: Path) -> None:
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "1.txt").write_text("text")
    (folder / "manifest.json").write_text(
        json.dumps(
            {"fixture": {}, "documents": [{"index": 1, "text_file": "1.txt", "reviewed_by": ""}]}
        )
    )
    problems = docket_fixture_problems(tmp_path)
    assert any("reviewed_by" in p for p in problems)


def test_orphan_document_file_is_a_problem(tmp_path: Path) -> None:
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "2.pdf").write_bytes(b"%PDF")
    (folder / "manifest.json").write_text(json.dumps({"fixture": {}, "documents": []}))
    assert any("2.pdf" in p for p in docket_fixture_problems(tmp_path))


def test_reviewed_document_is_fine(tmp_path: Path) -> None:
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "1.txt").write_text("text")
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "fixture": {},
                "documents": [
                    {"index": 1, "text_file": "1.txt", "reviewed_by": "Andy, 2026-09-20"}
                ],
            }
        )
    )
    assert docket_fixture_problems(tmp_path) == []


def test_no_fixtures_directory_is_not_a_problem(tmp_path: Path) -> None:
    assert docket_fixture_problems(tmp_path / "does-not-exist") == []


def test_a_file_directly_under_the_fixtures_root_is_a_problem(tmp_path: Path) -> None:
    """Fix round 1, finding 3: a document committed at ``root`` itself, above any case
    folder's manifest, previously went unchecked -- the old loop only ever looked inside a
    subdirectory of ``root``.
    """
    (tmp_path / "1.txt").write_text("text")
    problems = docket_fixture_problems(tmp_path)
    assert any("1.txt" in p and "manifest" in p for p in problems)


def test_a_file_in_a_nested_subfolder_not_listed_is_a_problem(tmp_path: Path) -> None:
    """Fix round 1, finding 3: the old loop only checked a case folder's immediate children,
    so a document nested one level deeper inside the case folder went unchecked.
    """
    folder = tmp_path / "X"
    folder.mkdir()
    nested = folder / "sub"
    nested.mkdir()
    (nested / "2.pdf").write_bytes(b"%PDF")
    (folder / "manifest.json").write_text(json.dumps({"fixture": {}, "documents": []}))
    problems = docket_fixture_problems(tmp_path)
    assert any("2.pdf" in p for p in problems)


def test_a_case_folder_without_a_manifest_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    """Fix round 1, finding 3: a case folder with no ``manifest.json`` at all used to raise
    ``FileNotFoundError``; it must report a problem instead, since this check exists to catch
    exactly this kind of hole.
    """
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "1.txt").write_text("text")
    problems = docket_fixture_problems(tmp_path)
    assert any("1.txt" in p and "manifest" in p for p in problems)


# --- fix finding 6: names in committed docket listings and titles sheets ---

_ROW_TEMPLATE = (
    "<tr><td><b>{index}</b></td><td>{title}</td><td><b>3</b></td><td>0</td>"
    "<td>Report</td><td></td></tr>"
)


def _listing_html(titles: list[str]) -> str:
    rows = "".join(_ROW_TEMPLATE.format(index=i, title=t) for i, t in enumerate(titles, start=1))
    return f"<html><body>Docket Items: {len(titles)}<table>{rows}</table></body></html>"


def _write_listing_fixture(root: Path, case_id: str, titles: list[str]) -> None:
    folder = root / case_id
    folder.mkdir(parents=True)
    (folder / "listing.html").write_text(_listing_html(titles), encoding="utf-8")
    (folder / "manifest.json").write_text(
        json.dumps({"fixture": {"case_id": case_id}, "documents": []})
    )


def test_title_looks_like_a_name_matches_common_ntsb_patterns() -> None:
    """Invented names only (house rules): never a real person, never printed by the check
    that uses this rule."""
    assert title_looks_like_a_name("Statement of Jordan Vale")
    assert title_looks_like_a_name("Interview of Morgan Reyes")
    assert not title_looks_like_a_name("Powerplant Examination Report")
    assert not title_looks_like_a_name("Weather Study")


def test_html_listing_with_a_name_shaped_title_is_a_problem(tmp_path: Path) -> None:
    _write_listing_fixture(tmp_path, "X", ["Statement of Jordan Vale"])
    problems = docket_fixture_name_problems(tmp_path, processed=tmp_path / "no-such-dir")
    assert any("title 1" in p and "X" in p for p in problems)
    # The check reports where, never what (same rule as scripts/name_coverage.py).
    assert not any("Jordan Vale" in p for p in problems)


def test_html_listing_with_an_ordinary_title_is_fine(tmp_path: Path) -> None:
    _write_listing_fixture(tmp_path, "X", ["Powerplant Examination Report"])
    assert docket_fixture_name_problems(tmp_path, processed=tmp_path / "no-such-dir") == []


def test_no_raw_data_locally_skips_the_owner_operator_check_without_crashing(
    tmp_path: Path,
) -> None:
    """CI and every pre-commit hook never have ``data/processed`` (0014) -- the name-shape
    heuristic still runs; the raw-record search is simply skipped, not a crash or a refusal.
    """
    _write_listing_fixture(tmp_path, "X", ["Powerplant Examination Report"])
    assert docket_fixture_name_problems(tmp_path, processed=tmp_path / "does-not-exist") == []


def test_html_listing_carrying_the_records_own_owner_operator_detail_is_a_problem(
    tmp_path: Path,
) -> None:
    """Where the raw record is available locally, its own recorded owner/operator strings
    (attach.py's ``owner_operator_values``) are searched for in the listing's visible text --
    invented values here, never a real name."""
    processed = tmp_path / "processed"
    processed.mkdir()
    raw = {
        "ntsbNumber": "X",
        "aircrafts": [{"ownerOperators": [{"registeredOwner": "Example Flying Club"}]}],
    }
    table = pa.table({"ntsb_number": ["X"], "raw_json": [json.dumps(raw)]})
    pq.write_table(table, processed / "cases.parquet")
    root = tmp_path / "docket"
    folder = root / "X"
    folder.mkdir(parents=True)
    (folder / "listing.html").write_text(
        "<html><body>Docket Items: 1<table>"
        "<tr><td><b>1</b></td><td>Correspondence, Example Flying Club</td>"
        "<td><b>3</b></td><td>0</td><td>Report</td><td></td></tr>"
        "</table></body></html>",
        encoding="utf-8",
    )
    (folder / "manifest.json").write_text(
        json.dumps({"fixture": {"case_id": "X"}, "documents": []})
    )
    problems = docket_fixture_name_problems(root, processed=processed)
    assert any("owner/operator detail" in p for p in problems)
    assert not any("Example Flying Club" in p for p in problems)


def test_csv_titles_sheet_is_checked_too(tmp_path: Path) -> None:
    root = tmp_path / "docket"
    root.mkdir()
    (root / "titles.csv").write_text(
        "case_id,title\nX,Statement of Jordan Vale\nY,Weather Study\n", encoding="utf-8"
    )
    problems = docket_fixture_name_problems(root, processed=tmp_path / "does-not-exist")
    assert any("titles.csv:2" in p for p in problems)
    assert not any("titles.csv:3" in p for p in problems)


def test_the_committed_docket_fixtures_carry_no_name() -> None:
    """The real, committed fixture tree -- proves the check runs clean on what is actually
    in the repository today, not only on synthetic inputs."""
    assert docket_fixture_name_problems() == []
