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
