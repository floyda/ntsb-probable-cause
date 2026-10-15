"""The learning part: development pool cases outside every sample (decisions 0200, 0203).

A made-up parquet under tmp_path built from the redacted fixture records; offline.
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from tests.conftest import FIXTURES

from ntsb_probable_cause import fields
from ntsb_probable_cause.memory import pool


def _write(processed: Path, rows: list[tuple[str, str, str, str, dict[str, object]]]) -> None:
    processed.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "ntsb_number": [r[0] for r in rows],
                "event_date": [r[1] for r in rows],
                "split": [r[2] for r in rows],
                "investigation_class": [r[3] for r in rows],
                "raw_json": [json.dumps(r[4]) for r in rows],
            }
        ),
        processed / "cases.parquet",
    )


def _coded_record() -> dict[str, object]:
    for path in sorted((FIXTURES / "records").glob("*.json")):
        raw = json.loads(path.read_text())["record"]
        if fields.probable_cause(raw) and fields.occurrence_codes(raw):
            return raw  # type: ignore[no-any-return]
    raise AssertionError("no coded fixture record")


def test_only_development_pool_cases_of_the_years_asked_and_outside_samples(
    tmp_path: Path,
) -> None:
    raw = _coded_record()
    _write(
        tmp_path / "processed",
        [
            ("A1", "2009-05-01", "dev", "C", raw),
            ("A2", "2010-05-01", "dev", "C", raw),
            ("A3", "2009-06-01", "heldout", "C", raw),
            ("A4", "2009-07-01", "dev", "I", raw),
            ("A5", "2009-08-01", "dev", "F", raw),
        ],
    )
    got = pool.learning_part(tmp_path / "processed", years={2009}, excluded={"A5"})
    assert [c.case_id for c in got] == ["A1"]
    case = got[0]
    assert case.year == 2009
    assert case.cause == fields.probable_cause(raw)
    assert case.occurrence == fields.occurrence_codes(raw)
    assert case.findings == fields.finding_codes_in_cause(raw)


def test_a_case_without_a_cause_or_an_occurrence_code_is_left_out(tmp_path: Path) -> None:
    raw = _coded_record()
    bare = {**raw, "narratives": []}
    _write(tmp_path / "processed", [("B1", "2009-05-01", "dev", "C", bare)])
    assert pool.learning_part(tmp_path / "processed", years={2009}, excluded=set()) == []
