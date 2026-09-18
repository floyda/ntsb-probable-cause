"""The docket text fixture check: every committed document text names its reviewer (0037)."""

import json
from pathlib import Path

from scripts.check_fixtures_redacted import docket_fixture_problems


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
