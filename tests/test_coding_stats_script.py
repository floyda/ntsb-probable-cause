"""scripts/coding_stats.py: the pool, and the contamination guard (decision 0094)."""

import dataclasses
import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import coding_stats as cs

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.coding_stats import CodingStats

_SCHEMA = pa.schema(
    [
        ("ntsb_number", pa.string()),
        ("event_date", pa.date32()),
        ("split", pa.string()),
        ("investigation_class", pa.string()),
        ("raw_json", pa.string()),
    ]
)

Row = tuple[str, str, str, str, dict[str, object]]


def _row(  # noqa: PLR0913, PLR0917 -- one row of the fixture table, one argument per column
    case: str,
    date: str,
    split: str,
    klass: str,
    codes: tuple[str, ...],
    group: str,
    findings: tuple[tuple[str, bool], ...] = (),
) -> Row:
    events: list[dict[str, object]] = [
        {
            "eventCode": code,
            "isDefiningEvent": i == 0,
            "sequenceNumber": i + 1,
            "cicttPhaseSOEGroup": group,
        }
        for i, code in enumerate(codes)
    ]
    rows: list[dict[str, object]] = [
        {"findingCode": code, "findingNumber": i + 1, "inProbableCause": cause}
        for i, (code, cause) in enumerate(findings)
    ]
    return case, date, split, klass, {"aircrafts": [{"events": events, "findings": rows}]}


ROWS = [
    _row("POOL1", "2011-05-01", "dev", "C", ("552300",), "Landing"),
    _row(
        "POOL2",
        "2016-05-01",
        "dev",
        "F",
        ("452240", "452241"),
        "Maneuvering",
        (("0206304044", True), ("0303404591", False)),
    ),
    _row("DEV400", "2012-01-01", "dev", "C", ("552300",), "Landing"),
    _row("OTHERCLASS", "2012-01-01", "dev", "I", ("552300",), "Landing"),
    _row("HELD", "2021-01-01", "heldout", "C", ("552300",), "Landing"),
    _row("OPEN", "2025-01-01", "open", "C", ("552300",), "Landing"),
]


def test_processed_rows_parses_raw_json_for_development_rows_only(tmp_path: Path) -> None:
    """Final review, Minor 5: ``pool_cases`` skips a held-out/open row before touching ``raw``
    at all, so ``processed_rows`` must not have parsed its ``raw_json`` either."""
    table = pa.table(
        {
            "ntsb_number": pa.array(["DEV1", "HELD1", "OPEN1"], type=pa.string()),
            "event_date": pa.array(
                [date(2012, 1, 1), date(2021, 1, 1), date(2025, 1, 1)], type=pa.date32()
            ),
            "split": pa.array(["dev", "heldout", "open"], type=pa.string()),
            "investigation_class": pa.array(["C", "C", "C"], type=pa.string()),
            "raw_json": pa.array(
                [json.dumps({"k": "dev"}), json.dumps({"k": "held"}), json.dumps({"k": "open"})],
                type=pa.string(),
            ),
        },
        schema=_SCHEMA,
    )
    processed = tmp_path / "processed"
    processed.mkdir()
    pq.write_table(table, processed / "cases.parquet")
    rows = {case: raw for case, _date, _split, _klass, raw in cs.processed_rows(processed)}
    assert rows["DEV1"] == {"k": "dev"}
    assert rows["HELD1"] == {}
    assert rows["OPEN1"] == {}


def test_pool_keeps_dev_classes_c_f_l_outside_the_samples() -> None:
    cases, ids = cs.pool_cases(ROWS, excluded=frozenset({"DEV400"}))
    assert ids == ["POOL1", "POOL2"]
    assert [c.sequence for c in cases] == [("552300",), ("452240", "452241")]
    assert cases[1].group == "Maneuvering"
    assert cases[1].findings == ("0206304044",)  # flagged in the probable cause only


def test_check_pool_refuses_a_sample_case_or_a_non_development_case() -> None:
    cs.check_pool(["POOL1"], excluded=frozenset({"DEV400"}), splits={"POOL1": "dev"})
    with pytest.raises(LeakageError, match="DEV400"):
        cs.check_pool(["DEV400"], excluded=frozenset({"DEV400"}), splits={"DEV400": "dev"})
    with pytest.raises(LeakageError, match="HELD"):
        cs.check_pool(["HELD"], excluded=frozenset(), splits={"HELD": "heldout"})


def test_report_prints_counts_and_both_halves_without_case_numbers() -> None:
    cases, _ids = cs.pool_cases(ROWS, excluded=frozenset({"DEV400"}))
    stats = cs.build(cases, built_from="test")
    text = cs.report(stats)
    assert "2009-2014: 1 cases; 2015-2019: 1 cases" in text
    assert "POOL" not in text
    assert "## flagged findings by defining event" in text
    assert "- 240 Loss of control in flight: 1 cases" in text
    assert "0206304044" in text


_S27_SAMPLES = ("dev-400", "dev-seal-400")
_S3_SAMPLES = ("dev-400", "dev-seal-400", "dev-seal-s3-400")


def test_the_two_stages_name_their_samples_their_file_and_their_provenance() -> None:
    """Decision 0129 item 4: S3's pool also leaves out ``dev-seal-s3-400``; S2.7's is as before."""
    s27, s3 = cs.STAGES["s27"], cs.STAGES["s3"]
    assert s27.excluded == _S27_SAMPLES
    assert s27.json_out == Path("src/ntsb_probable_cause/scoring/tables/coding_stats.json")
    assert s27.built_from == (
        "development split, classes C/F/L, excluding dev-400 and dev-seal-400 "
        "(scripts/coding_stats.py, decision 0094)"
    )
    assert s3.excluded == _S3_SAMPLES
    assert s3.json_out == Path("src/ntsb_probable_cause/scoring/tables/coding_stats_s3.json")
    assert s3.built_from == (
        "development split, classes C/F/L, excluding dev-400, dev-seal-400 and dev-seal-s3-400 "
        "(scripts/coding_stats.py, decisions 0094, 129)"
    )
    assert s27.json_out != s3.json_out


def test_the_s3_pool_leaves_out_the_new_sample_and_the_guard_refuses_one_that_is_present() -> None:
    rows = [*ROWS, _row("S3SEAL", "2017-06-01", "dev", "L", ("552300",), "Landing")]
    excluded = frozenset({"DEV400", "SEAL27", "S3SEAL"})
    _cases, ids = cs.pool_cases(rows, excluded=excluded)
    assert ids == ["POOL1", "POOL2"]
    _cases, leaky = cs.pool_cases(rows, excluded=frozenset({"DEV400"}))
    assert "S3SEAL" in leaky
    with pytest.raises(LeakageError, match="S3SEAL"):
        cs.check_pool(leaky, excluded=excluded, splits=dict.fromkeys(leaky, "dev"))


def _stage_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A processed file and the three sample lists in ``tmp_path``; throwaway output paths.

    Returns the two JSON paths the stages are pointed at (S2.7's, then S3's), so a test can see
    which one a stage wrote. Pool cases: POOL1 (2011), POOL2 (2016) and S3SEAL (2017); only S3's
    stage leaves S3SEAL out.
    """
    rows = [
        *ROWS,
        _row("SEAL27", "2013-01-01", "dev", "C", ("552300",), "Landing"),
        _row("S3SEAL", "2017-06-01", "dev", "L", ("552300",), "Landing"),
    ]
    processed = tmp_path / "processed"
    processed.mkdir()
    table = pa.table(
        {
            "ntsb_number": pa.array([r[0] for r in rows], type=pa.string()),
            "event_date": pa.array([date.fromisoformat(r[1]) for r in rows], type=pa.date32()),
            "split": pa.array([r[2] for r in rows], type=pa.string()),
            "investigation_class": pa.array([r[3] for r in rows], type=pa.string()),
            "raw_json": pa.array([json.dumps(r[4]) for r in rows], type=pa.string()),
        },
        schema=_SCHEMA,
    )
    pq.write_table(table, processed / "cases.parquet")
    lists = tmp_path / "lists"
    lists.mkdir()
    for name, case in (
        ("dev_400_ids.csv", "DEV400"),
        ("dev_seal_400_ids.csv", "SEAL27"),
        ("dev_seal_s3_400_ids.csv", "S3SEAL"),
    ):
        (lists / name).write_text(f"case_id,event_date\n{case},2015-01-01\n")
    monkeypatch.setattr(samples, "EVAL_DIR", lists)
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    paths = {"s27": tmp_path / "s27.json", "s3": tmp_path / "s3.json"}
    for stage_name in ("s27", "s3"):
        stage = dataclasses.replace(cs.STAGES[stage_name], json_out=paths[stage_name])
        monkeypatch.setitem(cs.STAGES, stage_name, stage)
    return paths["s27"], paths["s3"]


def test_the_s3_stage_writes_only_the_s3_file_from_a_pool_without_the_new_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s27_json, s3_json = _stage_env(tmp_path, monkeypatch)
    out = tmp_path / "s3.txt"
    assert cs.main(["--stage", "s3", "--out", str(out)]) == 0
    assert not s27_json.exists()
    stats = CodingStats.model_validate_json(s3_json.read_text())
    assert stats.cases == {"2009-2014": 1, "2015-2019": 1}
    assert stats.built_from == cs.STAGES["s3"].built_from
    assert "dev-seal-s3-400" in out.read_text()
    assert "S3SEAL" not in out.read_text()
    assert "built from: " in capsys.readouterr().out


def test_the_default_stage_is_s27_and_writes_only_the_s27_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s27_json, s3_json = _stage_env(tmp_path, monkeypatch)
    assert cs.main([]) == 0
    assert not s3_json.exists()
    stats = CodingStats.model_validate_json(s27_json.read_text())
    assert stats.cases == {"2009-2014": 1, "2015-2019": 2}  # S2.7's pool still holds S3SEAL
    assert stats.built_from == cs.STAGES["s27"].built_from


def test_the_s3_stage_writes_nothing_when_the_new_sample_list_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3's pool cannot be built before ``dev-seal-s3-400`` is drawn: it would hold its verdicts."""
    s27_json, s3_json = _stage_env(tmp_path, monkeypatch)
    (tmp_path / "lists" / "dev_seal_s3_400_ids.csv").unlink()
    with pytest.raises(FileNotFoundError):
        cs.main(["--stage", "s3"])
    assert not s27_json.exists()
    assert not s3_json.exists()
