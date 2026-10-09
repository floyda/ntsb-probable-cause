import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.live.records import (
    BACKFILL_FORMAT,
    CLOSURE_FORMAT,
    MANIFEST_FILE,
    MANIFEST_FORMAT,
    Backfill,
    ClosureRecord,
    DocumentLine,
    portability_problems,
    verify_manifest,
    write_manifest,
)


def _record() -> ClosureRecord:
    return ClosureRecord(
        case_id="XXX26LA001",
        mkey=1,
        closed_on=date(2026, 9, 24),
        closure_run=5,
        waited_days=2,
        first_sent=datetime(2026, 9, 26, 1, 0, tzinfo=UTC),
        last_returned=None,
        commit_sha="abc123",
        dirty=False,
        prompt_version="v1",
        price_variant="batch",
        model="m",
        reasoning_effort=None,
        training_cutoff=date(2025, 1, 1),
        training_cutoff_source="page",
        uv_lock_sha256="0" * 64,
        documents=(
            DocumentLine(position=1, title="Pilot form", status="read", ellery="read"),
            DocumentLine(position=2, title="Photos", status="skipped: photo-only", ellery=None),
        ),
        prelim_present=True,
        outcome="coded",
        failure=None,
        marks=("a",),
        scored=False,
        top1=None,
        top3=None,
        abstained=None,
        cost_usd=0.5,
    )


def test_formats() -> None:
    assert CLOSURE_FORMAT == "live-closure/1"
    assert BACKFILL_FORMAT == "live-backfill/1"
    assert MANIFEST_FORMAT == "live-manifest/1"
    assert _record().format == CLOSURE_FORMAT


def test_closure_record_round_trips() -> None:
    record = _record()
    again = ClosureRecord.model_validate_json(record.model_dump_json())
    assert again == record
    assert json.loads(record.model_dump_json())["closed_on"] == "2026-09-24"


def test_backfill_format() -> None:
    backfill = Backfill(fixed_on=date(2026, 9, 25), case_ids=("a",), sha256="x")
    assert backfill.format == BACKFILL_FORMAT


def _folder(root: Path) -> Path:
    folder = root / "run"
    (folder / "sub").mkdir(parents=True)
    (folder / "closures.jsonl").write_text(_record().model_dump_json() + "\n")
    (folder / "sub" / "b.json").write_text('{"k": 1}')
    (folder / "a.txt").write_text("hello")
    return folder


def test_manifest_lists_every_file_but_itself_sorted(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    write_manifest(folder)
    write_manifest(folder)  # re-writing must not list the old manifest
    manifest = json.loads((folder / MANIFEST_FILE).read_text())
    assert manifest["format"] == MANIFEST_FORMAT
    paths = [entry["path"] for entry in manifest["files"]]
    assert paths == ["a.txt", "closures.jsonl", "sub/b.json"]
    assert manifest["files"][0]["size"] == 5
    assert len(manifest["files"][0]["sha256"]) == 64
    assert verify_manifest(folder) == []


def test_verify_reports_change_missing_and_extra(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    write_manifest(folder)
    (folder / "a.txt").write_text("hellp")
    (folder / "sub" / "b.json").unlink()
    (folder / "extra.txt").write_text("x")
    problems = verify_manifest(folder)
    assert any("a.txt" in p and "changed" in p for p in problems)
    assert any("sub/b.json" in p and "missing" in p for p in problems)
    assert any("extra.txt" in p and "extra" in p for p in problems)


def test_verify_without_manifest(tmp_path: Path) -> None:
    assert verify_manifest(_folder(tmp_path)) == [f"{MANIFEST_FILE} is missing"]


def test_copied_folder_verifies(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    write_manifest(folder)
    other = tmp_path / "elsewhere" / "run"
    shutil.copytree(folder, other)
    assert verify_manifest(other) == []
    assert portability_problems(other) == []


def test_portability_flags_paths_and_secrets(tmp_path: Path) -> None:
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "a.json").write_text(json.dumps({"x": {"y": ["/Users/me/data"]}}))
    (folder / "b.jsonl").write_text(
        json.dumps({"k": "sk-or-v1-SECRETSECRET"})
        + "\n\n"
        + json.dumps({"k": "AKIA" + "ABCDEFGHIJKLMNOP"})
        + "\n"
        + json.dumps({"aws_profile": "p", "api_key": None, "ok": "relative/path"})
        + "\n"
    )
    text = "\n".join(portability_problems(folder))
    assert "a.json" in text
    assert "absolute path" in text
    assert "b.jsonl:1" in text
    assert "b.jsonl:3" in text
    assert "aws_profile" in text
    assert "api_key" in text
    assert "SECRETSECRET" not in text
    assert "ABCDEFGHIJKLMNOP" not in text


def test_portability_reports_unreadable_json(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{")
    (tmp_path / "bad.jsonl").write_text("{\n")
    problems = portability_problems(tmp_path)
    assert len(problems) == 2
    assert all("not valid JSON" in p for p in problems)


@pytest.mark.parametrize("value", ["", "plain", "a/b", "https://x.test/y"])
def test_portability_accepts_ordinary_strings(tmp_path: Path, value: str) -> None:
    (tmp_path / "a.json").write_text(json.dumps({"v": value}))
    assert portability_problems(tmp_path) == []
