"""live/ledger.py and scripts/ledger_append.py: the manifest-hash ledger (decision 0178)."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import ledger_append

from ntsb_probable_cause.live import records
from ntsb_probable_cause.live.ledger import (
    LEDGER_FORMAT,
    LedgerLine,
    new_lines,
    read_ledger,
    render_line,
    verify,
)

NOW = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
RUN_KEY = "runs/20261011T030000-abc1234-live-C/manifest.json"
NIGHT_KEY = "nights/2026-10-11/manifest.json"
RUN_KEY_R1 = "runs/r1/manifest.json"
RUN_BODY = b'{"format": "live-manifest/1", "files": []}\n'
NIGHT_BODY = json.dumps(
    {"format": "live-night-manifest/1", "counts": {"coded": 3, "x": 1}}
).encode()


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def test_new_lines_on_an_empty_ledger_gives_one_line_per_manifest_sorted() -> None:
    lines = new_lines([], {NIGHT_KEY: NIGHT_BODY, RUN_KEY: RUN_BODY}, NOW)
    assert [line.key for line in lines] == [NIGHT_KEY, RUN_KEY]
    assert lines[1].sha256 == _sha(RUN_BODY)
    assert lines[1].size == len(RUN_BODY)
    assert lines[1].counts is None
    assert lines[0].counts == {"coded": 3, "x": 1}
    assert all(line.format == LEDGER_FORMAT and line.appended_at == NOW for line in lines)


def test_the_same_manifests_again_give_no_line() -> None:
    first = new_lines([], {RUN_KEY: RUN_BODY}, NOW)
    assert new_lines(first, {RUN_KEY: RUN_BODY}, NOW + timedelta(days=1)) == []


def test_a_rewritten_manifest_is_appended_and_a_return_to_the_old_one_too() -> None:
    first = new_lines([], {RUN_KEY: RUN_BODY}, NOW)
    second = new_lines(first, {RUN_KEY: RUN_BODY + b" "}, NOW + timedelta(days=1))
    assert len(second) == 1
    assert second[0].sha256 == _sha(RUN_BODY + b" ")
    third = new_lines([*first, *second], {RUN_KEY: RUN_BODY}, NOW + timedelta(days=2))
    assert [line.sha256 for line in third] == [_sha(RUN_BODY)]


def test_an_unreadable_night_manifest_has_no_counts() -> None:
    bodies = {NIGHT_KEY: b"not json", "nights/2026-10-12/manifest.json": b"[1]"}
    assert [line.counts for line in new_lines([], bodies, NOW)] == [None, None]


def test_ledger_lines_round_trip_through_the_file(tmp_path: Path) -> None:
    lines = new_lines([], {NIGHT_KEY: NIGHT_BODY, RUN_KEY: RUN_BODY}, NOW)
    path = tmp_path / "ledger.jsonl"
    assert read_ledger(path) == []
    path.write_text("".join(render_line(line) for line in lines))
    assert read_ledger(path) == lines


def _run_folder(mirror: Path) -> Path:
    folder = mirror / "runs" / "r1"
    folder.mkdir(parents=True)
    (folder / "spec.json").write_text("{}")
    (folder / "run.jsonl").write_text("row\n")
    records.write_manifest(folder)
    return folder


def _ledger_for(mirror: Path) -> list[LedgerLine]:
    bodies = {
        p.relative_to(mirror).as_posix(): p.read_bytes() for p in mirror.glob("*/*/manifest.json")
    }
    return new_lines([], bodies, NOW)


def test_verify_is_empty_for_a_sound_mirror(tmp_path: Path) -> None:
    _run_folder(tmp_path)
    assert verify(_ledger_for(tmp_path), tmp_path) == []


def test_verify_reports_a_changed_manifest_by_key_only(tmp_path: Path) -> None:
    folder = _run_folder(tmp_path)
    ledger = _ledger_for(tmp_path)
    (folder / "spec.json").write_text('{"secret": "x"}')
    records.write_manifest(folder)  # a rewrite: the manifest hash changes
    problems = verify(ledger, tmp_path)
    assert "runs/r1/manifest.json: manifest differs from the ledger" in problems
    assert not any("secret" in problem for problem in problems)


def test_verify_reports_a_folder_file_that_changed_under_an_unchanged_manifest(
    tmp_path: Path,
) -> None:
    folder = _run_folder(tmp_path)
    ledger = _ledger_for(tmp_path)
    (folder / "run.jsonl").write_text("other\n")
    assert verify(ledger, tmp_path) == ["runs/r1: run.jsonl: changed"]


def test_verify_reports_a_missing_manifest(tmp_path: Path) -> None:
    folder = _run_folder(tmp_path)
    ledger = _ledger_for(tmp_path)
    (folder / "manifest.json").unlink()
    assert verify(ledger, tmp_path) == ["runs/r1/manifest.json: manifest is missing"]


def test_verify_uses_the_latest_line_for_a_key(tmp_path: Path) -> None:
    folder = _run_folder(tmp_path)
    first = _ledger_for(tmp_path)
    (folder / "spec.json").write_text('{"a": 1}')
    records.write_manifest(folder)
    both = [*first, *new_lines(first, {RUN_KEY_R1: (folder / "manifest.json").read_bytes()}, NOW)]
    assert verify(both, tmp_path) == []


def _night_folder(mirror: Path, *, with_record: bool = True) -> Path:
    folder = mirror / "nights" / "2026-10-11"
    folder.mkdir(parents=True)
    (folder / "started").write_bytes(b"")
    files: list[dict[str, Any]] = [
        {"path": "started", "size": 0, "sha256": _sha(b"")},
    ]
    record = b'{"coded": 1}\n'
    if with_record:
        (folder / "night.json").write_bytes(record)
    files.append({"path": "night.json", "size": len(record), "sha256": _sha(record)})
    manifest = {"format": "live-night-manifest/1", "files": files, "night_files": [], "counts": {}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def test_verify_checks_a_night_folder(tmp_path: Path) -> None:
    _night_folder(tmp_path)
    assert verify(_ledger_for(tmp_path), tmp_path) == []


def test_a_night_without_night_json_is_reported_missing(tmp_path: Path) -> None:
    _night_folder(tmp_path, with_record=False)
    assert verify(_ledger_for(tmp_path), tmp_path) == ["nights/2026-10-11: night.json: missing"]


def test_a_malformed_night_files_keeps_the_problems_already_found(tmp_path: Path) -> None:
    folder = _night_folder(tmp_path)
    (folder / "night.json").write_bytes(b"changed\n")
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["night_files"] = [{"path": "scores/ok.jsonl"}, "not a mapping"]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert verify(_ledger_for(tmp_path), tmp_path) == [
        "nights/2026-10-11: night.json: changed",
        "nights/2026-10-11: scores/ok.jsonl: missing",
        "nights/2026-10-11: night_files unreadable",
    ]


def test_an_unreadable_manifest_is_one_problem(tmp_path: Path) -> None:
    folder = _run_folder(tmp_path)
    (folder / "manifest.json").write_text("not json")
    assert verify(_ledger_for(tmp_path), tmp_path) == ["runs/r1: manifest unreadable"]


def test_verify_checks_the_files_a_night_manifest_lists_by_bucket_path(tmp_path: Path) -> None:
    folder = _night_folder(tmp_path)
    scores = tmp_path / "scores" / "s.jsonl"
    scores.parent.mkdir()
    scores.write_text("a\n")
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["night_files"] = [
        {"path": "scores/s.jsonl", "size": 2, "sha256": _sha(b"a\n")},
        {"path": "scores/gone.jsonl", "size": 2, "sha256": _sha(b"a\n")},
    ]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    ledger = _ledger_for(tmp_path)
    scores.write_text("b\n")
    assert verify(ledger, tmp_path) == [
        "nights/2026-10-11: scores/s.jsonl: changed",
        "nights/2026-10-11: scores/gone.jsonl: missing",
    ]


# -- scripts/ledger_append.py --------------------------------------------------------------


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _Paginator:
    def __init__(self, pages: list[dict[str, Any]], seen: list[tuple[str, str]]) -> None:
        self._pages = pages
        self._seen = seen

    def paginate(self, *, Bucket: str, Prefix: str) -> list[dict[str, Any]]:  # noqa: N803
        self._seen.append((Bucket, Prefix))
        return [p for p in self._pages if p["Prefix"] == Prefix]


class FakeS3:
    """A paginated fake: two pages under ``runs/``, one under ``nights/``."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.listed: list[tuple[str, str]] = []
        self.got: list[str] = []

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        runs = sorted(k for k in self.objects if k.startswith("runs/"))
        nights = sorted(k for k in self.objects if k.startswith("nights/"))
        pages: list[dict[str, Any]] = [
            {"Prefix": "runs/", "Contents": [{"Key": k} for k in runs[:2]]},
            {"Prefix": "runs/", "Contents": [{"Key": k} for k in runs[2:]]},
            {"Prefix": "nights/", "Contents": [{"Key": k} for k in nights]},
            {"Prefix": "nights/"},  # a page with no Contents key
        ]
        return _Paginator(pages, self.listed)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.got.append(Key)
        return {"Body": _Body(self.objects[Key])}


def _bucket() -> FakeS3:
    objects = {f"runs/r{i}/{name}": b"x" for i in range(3) for name in ("spec.json", "run.jsonl")}
    objects.update({f"runs/r{i}/manifest.json": f"m{i}".encode() for i in range(3)})
    objects.update(
        {"nights/2026-10-11/manifest.json": NIGHT_BODY, "nights/2026-10-11/night.json": b"n"}
    )
    objects["nights/2026-10-11/started"] = b""
    return FakeS3(objects)


def test_manifests_from_reads_every_page_and_only_manifest_keys() -> None:
    s3 = _bucket()
    found, skipped = ledger_append.manifests_from(s3, "b")
    assert skipped == 0
    assert sorted(found) == [
        "nights/2026-10-11/manifest.json",
        "runs/r0/manifest.json",
        "runs/r1/manifest.json",
        "runs/r2/manifest.json",
    ]
    assert sorted(s3.got) == sorted(found)
    assert s3.listed == [("b", "runs/"), ("b", "nights/")]


def test_ledger_append_prints_only_the_count_and_appends_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    s3 = _bucket()
    assert ledger_append.append(s3, "a-bucket", ledger, NOW) == 4
    assert ledger_append.append(s3, "a-bucket", ledger, NOW) == 0
    assert len(read_ledger(ledger)) == 4
    text = ledger.read_text()
    assert "a-bucket" not in text
    assert "m0" not in text
    assert capsys.readouterr().out == ""


def test_main_prints_appended_and_nothing_else(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = _bucket()
    monkeypatch.setattr(ledger_append, "_client", lambda: s3)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    assert ledger_append.main(["--bucket", "b", "--ledger", str(ledger)]) == 0
    assert capsys.readouterr().out == "appended: 4\n"


def test_a_deeper_manifest_key_is_skipped_and_counted() -> None:
    s3 = _bucket()
    s3.objects["runs/r0/sub/manifest.json"] = b"deep"
    s3.objects["nights/2026-10-11/x/y/manifest.json"] = b"deep"
    found, skipped = ledger_append.manifests_from(s3, "b")
    assert skipped == 2
    assert "runs/r0/sub/manifest.json" not in found
    assert "runs/r0/sub/manifest.json" not in s3.got


def test_main_refuses_a_missing_ledger_and_one_without_a_final_newline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = _bucket()
    monkeypatch.setattr(ledger_append, "_client", lambda: s3)
    ledger = tmp_path / "ledger.jsonl"
    assert ledger_append.main(["--bucket", "b", "--ledger", str(ledger)]) == 1
    assert not ledger.exists()
    ledger.write_text('{"a": 1}')
    assert ledger_append.main(["--bucket", "b", "--ledger", str(ledger)]) == 1
    assert ledger.read_text() == '{"a": 1}'
    assert s3.got == []
    assert capsys.readouterr().out == ""


def test_main_accepts_an_empty_ledger_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_append, "_client", _bucket)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    assert ledger_append.main(["--bucket", "b", "--ledger", str(ledger)]) == 0
    assert capsys.readouterr().out == "appended: 4\n"
