"""The open-split shape script keeps nothing: read and discard (decision 0040)."""

import json
from datetime import date
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import respx
from scripts.docket_shape_open import draw, main


def _processed(tmp_path: Path) -> Path:
    processed = tmp_path / "processed"
    processed.mkdir()
    rows = [
        (
            "A",
            1,
            date(2024, 3, 1),
            "open",
            "Completed",
            json.dumps({"highestInjuryLevel": "Fatal"}),
        ),
        ("B", 2, date(2024, 4, 1), "open", "Completed", json.dumps({"highestInjuryLevel": "None"})),
        ("C", 3, date(2024, 5, 1), "open", "Ongoing", json.dumps({"highestInjuryLevel": "Fatal"})),
        (
            "D",
            4,
            date(2021, 5, 1),
            "heldout",
            "Completed",
            json.dumps({"highestInjuryLevel": "Fatal"}),
        ),
    ]
    table = pa.table(
        {
            "ntsb_number": [r[0] for r in rows],
            "mkey": [r[1] for r in rows],
            "event_date": pa.array([r[2] for r in rows], type=pa.date32()),
            "split": [r[3] for r in rows],
            "completion_status": [r[4] for r in rows],
            "raw_json": [r[5] for r in rows],
        }
    )
    pq.write_table(table, processed / "cases.parquet")
    return processed


def test_draw_takes_closed_open_split_cases_by_stratum(tmp_path: Path) -> None:
    drawn = draw(_processed(tmp_path), per_stratum=40)
    assert sorted(drawn) == [(1, True), (2, False)]


def test_script_writes_nothing_under_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    _processed(tmp_path)
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_DOCKET_DIR", str(tmp_path / "docket"))
    respx_mock.get(url__startswith="https://data.ntsb.gov/Docket").mock(
        return_value=httpx.Response(200, text="<html>Docket Items: 0</html>")
    )
    out = tmp_path / "out.txt"
    assert main(["--out", str(out), "--per-stratum", "40"]) == 0
    assert out.exists()
    assert not (tmp_path / "docket").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt", "processed"]
