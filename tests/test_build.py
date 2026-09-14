import copy
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pyarrow.parquet as pq
import pytest

from ntsb_probable_cause.data.api import Page
from ntsb_probable_cause.data.build import build_processed, investigation_class
from ntsb_probable_cause.data.ingest import Month, fetch_months, month_dir
from ntsb_probable_cause.errors import ManifestError
from ntsb_probable_cause.records.split import split_record


class ListSource:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    def cases_by_date_range(self, start: date, end: date) -> Iterable[Page]:
        return self._pages()

    def _pages(self) -> Iterator[Page]:
        content = json.dumps({"hasMore": False, "nextMarker": None, "data": self.records}).encode()
        yield Page(1, content, tuple(self.records), False, None)


def variant(base: dict[str, object], number: str, **changes: object) -> dict[str, object]:
    record = copy.deepcopy(base)
    record["ntsbNumber"] = number
    record.update(changes)
    return record


def write_month(
    raw: Path, month: Month, records: list[dict[str, object]], fetched: str, refresh: bool = False
) -> None:
    stamp = datetime.fromisoformat(fetched).replace(tzinfo=UTC)
    fetch_months(ListSource(records), [month], raw, refresh=refresh, now=lambda: stamp)


def test_investigation_class_reads_the_sixth_character() -> None:
    assert investigation_class("CEN09CA125") == "C"
    assert investigation_class("GAA15CA157") == "C"
    assert investigation_class("bad") is None


def test_build_filters_deduplicates_and_indexes(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    base = record_fixtures[0]
    raw, out = tmp_path / "raw", tmp_path / "processed"
    part_135 = copy.deepcopy(cast("list[dict[str, object]]", base["aircrafts"]))
    part_135[0]["ownerOperators"] = [{"regulationFlightConductedUnder": "135"}]
    write_month(
        raw,
        Month(2016, 8),
        [
            variant(base, "CEN16LA001", eventDate="2016-08-02"),
            variant(base, "CEN16LA002", eventDate="2016-08-03", completionStatus="Ongoing"),
            variant(base, "CEN16LA003", eventDate="2016-08-04", aircrafts=part_135),
            variant(base, "ERA08LA004", eventDate="2008-12-31"),
        ],
        "2026-09-13T10:00:00",
    )
    write_month(
        raw,
        Month(2021, 5),
        [variant(base, "WPR21FA005", eventDate="2021-05-06")],
        "2026-09-13T10:00:00",
    )
    write_month(
        raw,
        Month(2021, 5),
        [variant(base, "WPR21FA005", eventDate="2021-05-06", highestInjuryLevel="Serious")],
        "2026-09-14T10:00:00",
        refresh=True,
    )

    result = build_processed(raw, out)

    rows = pq.read_table(out / "cases.parquet").to_pylist()
    assert [r["ntsb_number"] for r in rows] == ["CEN16LA001", "WPR21FA005"]
    assert result.counts_by_split == {"dev": 1, "heldout": 1}
    assert result.excluded == {"not completed": 1, "not part 91": 1, "before 2009": 1}
    first, second = rows
    assert first["split"] == "dev"
    assert first["investigation_class"] == "L"
    assert first["event_date"] == date(2016, 8, 2)
    assert first["docket_url"] == f"https://data.ntsb.gov/Docket?ProjectID={base['mKey']}"
    assert json.loads(second["raw_json"])["highestInjuryLevel"] == "Serious"
    meta = json.loads((out / "cases.meta.json").read_text())
    assert meta["rows"] == 2
    assert meta["manifest_sha256"] == result.manifest_sha256


def test_build_rejects_a_changed_raw_file(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    raw, out = tmp_path / "raw", tmp_path / "processed"
    write_month(raw, Month(2016, 8), record_fixtures[:1], "2026-09-13T10:00:00")
    (month_dir(raw, "2016-08") / "page-01.json").write_bytes(b'{"data": []}')
    with pytest.raises(ManifestError, match="sha256"):
        build_processed(raw, out)


def test_build_deduplicates_across_month_partitions_by_fetched_at(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    base = record_fixtures[0]

    # Case A: two month partitions, the newer fetch (later fetched_at, later month label) is
    # Ongoing. The newer copy must win before filtering (excluded as "not completed"), and the
    # replacement must be counted exactly once.
    raw_a, out_a = tmp_path / "raw-a", tmp_path / "out-a"
    write_month(
        raw_a,
        Month(2016, 8),
        [variant(base, "CEN16LA020", eventDate="2016-08-02")],
        "2026-09-13T10:00:00",
    )
    write_month(
        raw_a,
        Month(2016, 9),
        [variant(base, "CEN16LA020", eventDate="2016-08-02", completionStatus="Ongoing")],
        "2026-09-14T10:00:00",
    )
    result_a = build_processed(raw_a, out_a)
    assert result_a.excluded == {"not completed": 1}
    assert result_a.duplicates_replaced == 1
    assert pq.read_table(out_a / "cases.parquet").to_pylist() == []

    # Case B: the newer copy is Completed, with a changed field — the newer value wins.
    raw_b, out_b = tmp_path / "raw-b", tmp_path / "out-b"
    write_month(
        raw_b,
        Month(2016, 8),
        [variant(base, "CEN16LA021", eventDate="2016-08-02")],
        "2026-09-13T10:00:00",
    )
    write_month(
        raw_b,
        Month(2016, 9),
        [variant(base, "CEN16LA021", eventDate="2016-08-02", highestInjuryLevel="Serious")],
        "2026-09-14T10:00:00",
    )
    result_b = build_processed(raw_b, out_b)
    assert result_b.duplicates_replaced == 1
    rows_b = pq.read_table(out_b / "cases.parquet").to_pylist()
    assert len(rows_b) == 1
    assert json.loads(rows_b[0]["raw_json"])["highestInjuryLevel"] == "Serious"

    # Case C: a *stale* entry is encountered after the newest is already kept — month "2016-07"
    # (alphabetically first, so iterated first) carries the newer fetched_at and the value that
    # should win; month "2016-08" (iterated second) carries an older fetched_at and a stale
    # value. This is a duplicate *seen* but never actually applied, so it must not count as a
    # replacement.
    raw_c, out_c = tmp_path / "raw-c", tmp_path / "out-c"
    write_month(
        raw_c,
        Month(2016, 7),
        [variant(base, "CEN16LA022", eventDate="2016-07-02", highestInjuryLevel="Fatal")],
        "2026-09-14T10:00:00",
    )
    write_month(
        raw_c,
        Month(2016, 8),
        [variant(base, "CEN16LA022", eventDate="2016-07-02", highestInjuryLevel="Minor")],
        "2026-09-13T10:00:00",
    )
    result_c = build_processed(raw_c, out_c)
    assert result_c.duplicates_replaced == 0
    assert result_c.duplicates_seen == 1
    rows_c = pq.read_table(out_c / "cases.parquet").to_pylist()
    assert len(rows_c) == 1
    assert json.loads(rows_c[0]["raw_json"])["highestInjuryLevel"] == "Fatal"


def test_every_processed_row_splits_cleanly(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    raw, out = tmp_path / "raw", tmp_path / "processed"
    write_month(raw, Month(2016, 8), record_fixtures, "2026-09-13T10:00:00")
    build_processed(raw, out)
    for row in pq.read_table(out / "cases.parquet").to_pylist():
        evidence, _, _ = split_record(json.loads(row["raw_json"]))
        assert evidence.case_id == row["ntsb_number"]
