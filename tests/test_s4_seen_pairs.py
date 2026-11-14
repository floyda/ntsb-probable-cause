"""The seen-pairs table: the script writes it, the loader reads it, the committed copy agrees."""

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import s4_seen_pairs

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings


def _raw(code: str) -> str:
    event = {"eventCode": code, "isDefiningEvent": True, "sequenceNumber": 1}
    return json.dumps({"highestInjuryLevel": "Minor", "aircrafts": [{"events": [event]}]})


def _processed(tmp_path: Path) -> Path:
    processed = tmp_path / "processed"
    processed.mkdir()
    rows = [
        ("A1", "2018-01-01", "dev", _raw("222000")),
        ("B2", "2017-01-01", "dev", _raw("111000")),
        ("C3", "2021-01-01", "heldout", _raw("333000")),
    ]
    table = pa.table(
        {
            "ntsb_number": [r[0] for r in rows],
            "event_date": pa.array([date.fromisoformat(r[1]) for r in rows], type=pa.date32()),
            "split": [r[2] for r in rows],
            "investigation_class": ["C"] * 3,
            "raw_json": [r[3] for r in rows],
        }
    )
    pq.write_table(table, processed / "cases.parquet")
    return processed


def test_script_writes_exactly_the_dev_codes_sorted(tmp_path: Path) -> None:
    out = tmp_path / "table.json"
    assert s4_seen_pairs.write_table(_processed(tmp_path), out) == 2
    assert json.loads(out.read_text()) == {
        "format": "seen-pairs/1",
        "split": "dev",
        "codes": ["111000", "222000"],
    }


def test_main_writes_from_the_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _processed(tmp_path)
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    out = tmp_path / "t.json"
    assert s4_seen_pairs.main(["--out", str(out)]) == 0
    assert json.loads(out.read_text())["codes"] == ["111000", "222000"]


def test_loader_returns_six_digit_codes() -> None:
    codes = samples.load_seen_pairs()
    assert codes
    assert all(len(c) == 6 and c.isdigit() for c in codes)


def test_loader_refuses_an_unknown_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "tables"
    bad.mkdir()
    (bad / samples.SEEN_PAIRS_FILE).write_text('{"format": "other/9", "codes": []}')
    monkeypatch.setattr(samples, "__file__", str(tmp_path / "samples.py"))
    with pytest.raises(ValueError, match="unknown format"):
        samples.load_seen_pairs()


def test_committed_table_equals_seen_pairs_when_the_data_is_present() -> None:
    processed = Settings().data_dir / "processed"
    if not (processed / "cases.parquet").is_file():
        pytest.skip("no processed file here")
    assert samples.load_seen_pairs() == samples.seen_pairs(processed)
