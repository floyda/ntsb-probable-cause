import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from tests.test_live_records import _record
from tests.test_store_sync import _FakeS3

from ntsb_probable_cause.live.local import (
    LIVE_SAMPLE,
    STORE_WORK_FILENAME,
    LocalFolderSink,
    LocalSpend,
    S3StoreSource,
)
from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    MANIFEST_FILE,
    Backfill,
    verify_manifest,
)
from ntsb_probable_cause.scoring.records import RunRecord, write_jsonl
from ntsb_probable_cause.store import Store
from ntsb_probable_cause.store.sync import Location


def test_constants() -> None:
    assert LIVE_SAMPLE == "live"
    assert STORE_WORK_FILENAME == "live-store.sqlite"


def _make_store(path: Path) -> None:
    store = Store(path)
    store.migrate()
    store.close()


def _source(tmp_path: Path) -> tuple[S3StoreSource, _FakeS3, Path]:
    bucket = tmp_path / "bucket"
    (bucket / "b").mkdir(parents=True)
    _make_store(bucket / "b" / "k")
    fake = _FakeS3(bucket)
    work = tmp_path / "work" / STORE_WORK_FILENAME
    return S3StoreSource(Location("s3://b/k"), work, s3=fake), fake, work


def test_store_source_opens_a_read_only_copy_and_never_uploads(tmp_path: Path) -> None:
    source, fake, work = _source(tmp_path)
    store = source.open()
    assert work.is_file()
    assert fake.downloads == [("b", "k", str(work))]
    with pytest.raises(sqlite3.OperationalError):
        store.connection.execute("create table x (a)")
    assert fake.uploads == []
    source.discard()


def test_discard_removes_the_work_file_and_wal_files(tmp_path: Path) -> None:
    source, _fake, work = _source(tmp_path)
    source.open()
    work.with_name(work.name + "-wal").write_bytes(b"w")
    work.with_name(work.name + "-shm").write_bytes(b"s")
    source.discard()
    assert list(work.parent.iterdir()) == []
    source.discard()  # twice is fine


def test_open_twice_replaces_the_copy(tmp_path: Path) -> None:
    source, fake, _work = _source(tmp_path)
    source.open()
    source.open()
    assert len(fake.downloads) == 2
    source.discard()


def test_a_missing_s3_object_is_file_not_found(tmp_path: Path) -> None:
    fake = _FakeS3(tmp_path, missing=True)
    source = S3StoreSource(Location("s3://b/k"), tmp_path / "w.sqlite", s3=fake)
    with pytest.raises(FileNotFoundError):
        source.open()


def test_a_local_location_is_copied_so_discard_keeps_the_original(tmp_path: Path) -> None:
    original = tmp_path / "recorder.sqlite"
    _make_store(original)
    work = tmp_path / "w" / "copy.sqlite"
    source = S3StoreSource(Location(str(original)), work)
    source.open()
    assert work.is_file()
    source.discard()
    assert original.is_file()
    assert not work.exists()


def test_a_missing_local_store_is_file_not_found(tmp_path: Path) -> None:
    source = S3StoreSource(Location(str(tmp_path / "none.sqlite")), tmp_path / "w.sqlite")
    with pytest.raises(FileNotFoundError):
        source.open()


NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


def _run_record(  # noqa: PLR0913 -- a test builder with one keyword per varied field
    run_id: str,
    sample: str = "live",
    *,
    started: datetime = datetime(2026, 10, 7, 1, tzinfo=UTC),
    finished: datetime | None = datetime(2026, 10, 7, 2, tzinfo=UTC),
    cost: float = 1.0,
    reported: float | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        sample=sample,
        arm="C",
        exclusions=(),
        includes=(),
        prompt_version="v",
        model="m",
        price_variant="batch",
        cap_usd=0.05,
        budget_usd=40.0,
        commit_sha="abc",
        dirty=False,
        started=started,
        finished=finished,
        cost_usd=cost,
        reported_batch_cost_usd=reported,
    )


def _live(runs: Path, run_id: str, *records: RunRecord, cases: tuple[str, ...] = ()) -> Path:
    folder = runs / run_id
    folder.mkdir(parents=True, exist_ok=True)
    write_jsonl(folder / "run.jsonl", records or [_run_record(run_id)])
    if cases:
        (folder / "cases.jsonl").write_text(
            "".join(json.dumps({"case_id": c}) + "\n" for c in cases)
        )
    return folder


def test_spend_counts_live_records_of_the_month_only(tmp_path: Path) -> None:
    _live(tmp_path, "20261007-a", _run_record("a", cost=2.0))
    _live(tmp_path, "20261006-b", _run_record("b", cost=3.0))
    _live(tmp_path, "20260930-c", _run_record("c", started=datetime(2026, 9, 30, tzinfo=UTC)))
    _live(tmp_path, "20251007-d", _run_record("d", started=datetime(2025, 10, 7, tzinfo=UTC)))
    _live(tmp_path, "20261007-e", _run_record("e", "dev-400", cost=50.0))
    assert LocalSpend(tmp_path).live_month_usd(NOW) == 5.0
    assert LocalSpend(tmp_path / "missing").live_month_usd(NOW) == 0.0


def test_spend_uses_the_billed_total_when_the_record_counts_it(tmp_path: Path) -> None:
    from ntsb_probable_cause.scoring.budget import spent_usd  # noqa: PLC0415

    record = _run_record("a", cost=3.0, reported=1.0)
    _live(tmp_path, "20261007-a", record)
    assert LocalSpend(tmp_path).live_month_usd(NOW) == spent_usd(record)


def test_spend_ignores_a_record_of_another_sample_in_a_live_folder(tmp_path: Path) -> None:
    _live(tmp_path, "20261007-a", _run_record("a", cost=2.0), _run_record("a-j", "judge", cost=9.0))
    assert LocalSpend(tmp_path).live_month_usd(NOW) == 2.0


def test_spend_of_a_folder_with_only_a_spec_is_zero(tmp_path: Path) -> None:
    folder = tmp_path / "20261007-x"
    folder.mkdir()
    (folder / "spec.json").write_text(json.dumps({"sample": "live"}))
    assert LocalSpend(tmp_path).live_month_usd(NOW) == 0.0


def test_a_live_run_is_recognised_by_its_record_not_its_name(tmp_path: Path) -> None:
    _live(tmp_path, "weird-name", cases=("A1",))
    _live(tmp_path, "20261007-dev", _run_record("d", "dev-400"), cases=("B1",))
    assert LocalFolderSink(tmp_path).done_case_ids() == {"A1"}


def test_done_case_ids_spans_runs_and_ignores_non_case_rows(tmp_path: Path) -> None:
    _live(tmp_path, "20261006-a", cases=("A1", "A2"))
    folder = _live(tmp_path, "20261007-b", cases=("B1",))
    with (folder / "cases.jsonl").open("a") as handle:
        handle.write("\n" + json.dumps({"other": 1}) + "\n")
    _live(tmp_path, "20261007-c")  # no cases.jsonl
    (tmp_path / "stray.txt").write_text("x")
    assert LocalFolderSink(tmp_path).done_case_ids() == {"A1", "A2", "B1"}
    assert LocalFolderSink(tmp_path / "missing").done_case_ids() == frozenset()


def test_coded_on_counts_cases_of_runs_starting_that_day(tmp_path: Path) -> None:
    _live(tmp_path, "20261007-a", cases=("A1", "A2"))
    _live(tmp_path, "20261007-b", cases=("B1",))
    _live(tmp_path, "20261006-c", cases=("C1",))
    sink = LocalFolderSink(tmp_path)
    assert sink.coded_on(date(2026, 10, 7)) == 3
    assert sink.coded_on(date(2026, 10, 6)) == 1
    assert sink.coded_on(date(2026, 10, 5)) == 0


def test_unfinished_run(tmp_path: Path) -> None:
    sink = LocalFolderSink(tmp_path)
    assert sink.unfinished_run() is None
    _live(tmp_path, "20261006-a")
    assert sink.unfinished_run() is None
    _live(tmp_path, "20261007-b", _run_record("b", finished=None))
    assert sink.unfinished_run() == "20261007-b"


def test_last_record_decides_whether_a_run_is_unfinished(tmp_path: Path) -> None:
    _live(tmp_path, "20261007-a", _run_record("a", finished=None), _run_record("a", finished=NOW))
    assert LocalFolderSink(tmp_path).unfinished_run() is None


def test_a_folder_with_only_a_live_spec_is_unfinished(tmp_path: Path) -> None:
    folder = tmp_path / "20261007-killed"
    folder.mkdir()
    (folder / "spec.json").write_text(json.dumps({"sample": "live"}))
    other = tmp_path / "20261007-dev"
    other.mkdir()
    (other / "spec.json").write_text(json.dumps({"sample": "dev-400"}))
    (tmp_path / "20261007-empty").mkdir()
    assert LocalFolderSink(tmp_path).unfinished_run() == "20261007-killed"


def test_an_empty_run_jsonl_falls_back_to_the_spec(tmp_path: Path) -> None:
    folder = tmp_path / "20261007-z"
    folder.mkdir()
    (folder / "run.jsonl").write_text("")
    (folder / "spec.json").write_text(json.dumps({"sample": "live"}))
    assert LocalFolderSink(tmp_path).unfinished_run() == "20261007-z"


def test_an_unreadable_spec_is_an_error(tmp_path: Path) -> None:
    folder = tmp_path / "20261007-bad"
    folder.mkdir()
    (folder / "spec.json").write_text("{not json")
    with pytest.raises(ValueError, match="unreadable spec"):
        LocalFolderSink(tmp_path).unfinished_run()


def test_a_spec_that_is_not_an_object_is_not_live(tmp_path: Path) -> None:
    folder = tmp_path / "20261007-list"
    folder.mkdir()
    (folder / "spec.json").write_text("[1]")
    assert LocalFolderSink(tmp_path).unfinished_run() is None


def test_backfill_comes_from_the_first_live_run_holding_one(tmp_path: Path) -> None:
    sink = LocalFolderSink(tmp_path)
    assert sink.backfill() is None
    _live(tmp_path, "20261005-a")
    backfill = Backfill(fixed_on=date(2026, 10, 5), case_ids=("A",), sha256="x")
    _live(tmp_path, "20261006-b")
    (tmp_path / "20261006-b" / BACKFILL_FILE).write_text(backfill.model_dump_json())
    _live(tmp_path, "20261004-dev", _run_record("d", "dev-400"))
    (tmp_path / "20261004-dev" / BACKFILL_FILE).write_text("garbage")
    assert sink.backfill() == backfill


def test_write_puts_closures_backfill_and_manifest_in_the_run_folder(tmp_path: Path) -> None:
    sink = LocalFolderSink(tmp_path)
    backfill = Backfill(fixed_on=date(2026, 10, 7), case_ids=("A",), sha256="x")
    sink.write("20261007-r", [_record()], backfill)
    folder = tmp_path / "20261007-r"
    assert sorted(p.name for p in folder.iterdir()) == [BACKFILL_FILE, CLOSURES_FILE, MANIFEST_FILE]
    assert len((folder / CLOSURES_FILE).read_text().splitlines()) == 1
    assert verify_manifest(folder) == []


def test_write_without_backfill_writes_none(tmp_path: Path) -> None:
    LocalFolderSink(tmp_path).write("20261007-r", [], None)
    assert not (tmp_path / "20261007-r" / BACKFILL_FILE).exists()
