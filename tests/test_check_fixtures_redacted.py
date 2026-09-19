"""The docket text fixture check: every committed document text names its reviewer (0037)."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import check_fixtures_redacted
from scripts.check_fixtures_redacted import (
    Finding,
    docket_fixture_name_problems,
    docket_fixture_problems,
    main,
    title_looks_like_a_name,
)

from ntsb_probable_cause.docket.title_vocab import known_title_words, load_title_vocabulary


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


def test_title_looks_like_a_name_passes_for_a_vocabulary_only_title() -> None:
    """Every word here is in the committed vocabulary itself (not the dictionary), so this
    holds regardless of whether this machine has a system dictionary."""
    known = load_title_vocabulary()
    assert not title_looks_like_a_name("Airframe Examination Summary", known)


def test_title_looks_like_a_name_flags_an_invented_surname_outside_both_lists() -> None:
    """Invented name only (house rules): never a real person, never printed by the check that
    uses this rule. "Thackerson" is absent from both the committed vocabulary and the system
    dictionary at commit (checked when this test was written)."""
    known, _found = known_title_words()
    assert title_looks_like_a_name("Statement of Thackerson", known)
    assert not title_looks_like_a_name("Airframe Examination Summary", known)


def test_known_title_words_falls_back_to_the_vocabulary_alone_when_no_dictionary(
    tmp_path: Path,
) -> None:
    """A missing system dictionary is reported (``found`` is ``False``), and the combined set
    falls back to the committed vocabulary alone rather than silently checking against
    nothing -- an unknown word is still flagged, never waved through."""
    known, found = known_title_words(dictionary_path=tmp_path / "does-not-exist")
    assert found is False
    assert known == load_title_vocabulary()
    assert not title_looks_like_a_name("Airframe Examination Summary", known)
    assert title_looks_like_a_name("Statement of Thackerson", known)


def test_docket_fixture_name_problems_warns_to_stderr_when_dictionary_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The check still runs -- and still catches the invented surname -- on the committed
    vocabulary alone; the missing dictionary is said, not passed over in silence."""
    _write_listing_fixture(tmp_path, "X", ["Statement of Thackerson"])
    problems = docket_fixture_name_problems(
        tmp_path,
        processed=tmp_path / "no-such-dir",
        dictionary_path=tmp_path / "does-not-exist",
    )
    assert any("title 1" in p.message and "X" in p.message for p in problems)
    assert "no system dictionary" in capsys.readouterr().err


def test_html_listing_with_a_name_shaped_title_is_advisory_only(tmp_path: Path) -> None:
    """Decision 0049: a listing page is an already-public NTSB page, so a flagged title is
    reported but does not block -- it stays committed as received (0037)."""
    _write_listing_fixture(tmp_path, "X", ["Statement of Thackerson"])
    problems = docket_fixture_name_problems(tmp_path, processed=tmp_path / "no-such-dir")
    assert any("title 1" in p.message and "X" in p.message for p in problems)
    assert all(not p.blocking for p in problems)
    # The check reports where, never what (same rule as scripts/name_coverage.py).
    assert not any("Thackerson" in p.message for p in problems)


def test_html_listing_with_an_ordinary_title_is_fine(tmp_path: Path) -> None:
    _write_listing_fixture(tmp_path, "X", ["Airframe Examination Summary"])
    assert docket_fixture_name_problems(tmp_path, processed=tmp_path / "no-such-dir") == []


def test_no_raw_data_locally_skips_the_owner_operator_check_without_crashing(
    tmp_path: Path,
) -> None:
    """CI and every pre-commit hook never have ``data/processed`` (0014) -- the vocabulary
    check still runs; the raw-record search is simply skipped, not a crash or a refusal.
    """
    _write_listing_fixture(tmp_path, "X", ["Airframe Examination Summary"])
    assert docket_fixture_name_problems(tmp_path, processed=tmp_path / "does-not-exist") == []


def test_html_listing_carrying_the_records_own_owner_operator_detail_still_blocks(
    tmp_path: Path,
) -> None:
    """Where the raw record is available locally, its own recorded owner/operator strings
    (attach.py's ``owner_operator_values``) are searched for in the listing's visible text --
    invented values here, never a real name. This check is not a heuristic (0049), so it
    blocks even on a listing page."""
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
    owner_findings = [p for p in problems if "owner/operator detail" in p.message]
    assert owner_findings
    assert all(p.blocking for p in owner_findings)
    assert not any("Example Flying Club" in p.message for p in problems)


def test_csv_titles_sheet_title_check_blocks(tmp_path: Path) -> None:
    """Decision 0049 item 2/3: a `.csv` this project authors is not a public NTSB page, so
    its title check blocks like everything else this project writes."""
    root = tmp_path / "docket"
    root.mkdir()
    (root / "titles.csv").write_text(
        "case_id,title\nX,Statement of Thackerson\nY,Weather Study\n", encoding="utf-8"
    )
    problems = docket_fixture_name_problems(root, processed=tmp_path / "does-not-exist")
    row2 = [p for p in problems if "titles.csv:2" in p.message]
    assert row2
    assert all(p.blocking for p in row2)
    assert not any("titles.csv:3" in p.message for p in problems)


def test_the_committed_docket_fixtures_carry_no_blocking_name_finding() -> None:
    """The real, committed fixture tree -- proves the check runs clean on what is actually in
    the repository today, not only on synthetic inputs. A committed listing page may still
    carry an advisory finding (decision 0049): only the blocking ones must be empty."""
    assert [p for p in docket_fixture_name_problems() if p.blocking] == []


# --- main(): advisory findings are printed but never fail the run (0049) ---


def test_main_passes_with_only_advisory_findings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_fixtures_redacted, "docket_fixture_problems", lambda: [])
    monkeypatch.setattr(
        check_fixtures_redacted,
        "docket_fixture_name_problems",
        lambda: [Finding("a listing title, reported for a by-eye look", blocking=False)],
    )
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "[advisory]" in out
    assert "[blocking]" not in out


def test_main_fails_on_a_blocking_name_finding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_fixtures_redacted, "docket_fixture_problems", lambda: [])
    monkeypatch.setattr(
        check_fixtures_redacted,
        "docket_fixture_name_problems",
        lambda: [Finding("a titles.csv value this project authored", blocking=True)],
    )
    assert main([]) == 1
    assert "[blocking]" in capsys.readouterr().out


def test_main_fails_when_document_text_has_no_reviewer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """0037's reviewer requirement is unrelated to the name check and stays blocking always."""
    monkeypatch.setattr(
        check_fixtures_redacted,
        "docket_fixture_problems",
        lambda: ["X/1.txt: document text committed without reviewed_by (0037)"],
    )
    monkeypatch.setattr(check_fixtures_redacted, "docket_fixture_name_problems", lambda: [])
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "[blocking]" in out
    assert "reviewed_by" in out
