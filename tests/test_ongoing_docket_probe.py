"""The ongoing-docket probe: outcome classification, the draw, and a counts-only report."""

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from scripts.ongoing_docket_probe import (
    classify_page,
    draw,
    has_open_date_set,
    main,
    outcome_for_error,
    population_sizes,
    report,
    stratify,
)

from ntsb_probable_cause import sources
from ntsb_probable_cause.data.api import Page
from ntsb_probable_cause.data.ingest import Month, fetch_months

SAVED = Path("tests/fixtures/docket/ERA17LA217/listing.html").read_bytes().decode("utf-8")
MKEY = 95459


class _ListSource:
    """A fixed page of records, wrapped as ``fetch_months``' ``CasesSource`` protocol wants."""

    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    def cases_by_date_range(self, start: date, end: date) -> Iterable[Page]:
        return self._pages()

    def _pages(self) -> Iterator[Page]:
        content = json.dumps({"hasMore": False, "nextMarker": None, "data": self.records}).encode()
        yield Page(1, content, tuple(self.records), False, None)


def _write_month(
    raw: Path,
    month: Month,
    records: list[dict[str, object]],
    fetched: str,
    *,
    refresh: bool = False,
) -> None:
    stamp = datetime.fromisoformat(fetched).replace(tzinfo=UTC)
    fetch_months(_ListSource(records), [month], raw, refresh=refresh, now=lambda: stamp)


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "ntsbNumber": "CEN26LA001",
        "mKey": 1001,
        "mode": "Aviation",
        "completionStatus": "Ongoing",
        "eventDate": "2026-09-01",
        "aircrafts": [{"ownerOperators": [{"regulationFlightConductedUnder": "091"}]}],
    }
    base.update(overrides)
    return base


# --- classify_page -----------------------------------------------------------------------


def test_saved_page_classifies_as_read() -> None:
    assert classify_page(SAVED, MKEY) == "read"


def test_page_without_block_is_not_read() -> None:
    assert classify_page("<html>Docket Items: 0</html>", 1) == "no-info-block"


def test_mismatch_is_reported_not_raised() -> None:
    bad = SAVED.replace("Docket Items: 5", "Docket Items: 7")
    assert classify_page(bad, MKEY) == "count-mismatch"


def test_page_with_info_block_and_no_rows_is_empty() -> None:
    page = "<html><h2><b>Docket Information</b></h2>Docket Items: 0</html>"
    assert classify_page(page, 1) == "empty"


# --- stratify ------------------------------------------------------------------------------


def test_stratify_buckets_by_days() -> None:
    assert stratify(0) == "0-30"
    assert stratify(10) == "0-30"
    assert stratify(30) == "0-30"
    assert stratify(31) == "31-90"
    assert stratify(45) == "31-90"
    assert stratify(91) == "91-180"
    assert stratify(180) == "91-180"
    assert stratify(181) == "181+"
    assert stratify(400) == "181+"


# --- outcome_for_error -----------------------------------------------------------------------


def test_outcome_for_error_parses_the_returned_status() -> None:
    assert outcome_for_error("https://data.ntsb.gov/Docket?ProjectID=1 returned 404") == "http-404"
    assert outcome_for_error("https://data.ntsb.gov/Docket?ProjectID=1 returned 500") == "http-500"


def test_outcome_for_error_falls_back_when_no_clean_status() -> None:
    message = "https://x failed after 5 attempts; last status ConnectError"
    assert outcome_for_error(message) == "fetch-failed"


# --- report ----------------------------------------------------------------------------------


def test_report_prints_counts_only() -> None:
    text = report(
        outcomes={"read": 3, "http-404": 1},
        doc_counts=[0, 2, 9],
        by_stratum={"0-30": {"read": 1, "http-404": 1}},
        attempted=4,
    )
    assert "cases attempted: 4" in text
    assert "http-404: 1" in text
    assert "95459" not in text


def test_report_carries_the_seed_and_percentiles_when_given() -> None:
    text = report(
        outcomes={"read": 4},
        doc_counts=[1, 2, 3, 4],
        by_stratum={},
        attempted=4,
        creation_date_present=2,
        seed=2026,
    )
    assert "seed: 2026" in text
    assert "p50=" in text
    assert "read pages with a creation date: 2" in text


def test_report_never_names_a_case_id() -> None:
    """No output form of the report may carry a case number, however it is built."""
    text = report(
        outcomes={"read": 1},
        doc_counts=[3],
        by_stratum={"181+": {"read": 1}},
        attempted=1,
        creation_date_present=1,
        seed=1,
    )
    assert "CEN" not in text
    assert str(MKEY) not in text


def test_report_cross_tabs_by_open_date_presence_when_given() -> None:
    text = report(
        outcomes={"read": 1, "http-404": 1},
        doc_counts=[2],
        by_stratum={},
        attempted=2,
        by_open_date={True: {"read": 1}, False: {"http-404": 1}},
    )
    assert "docketOpenDate set:" in text
    assert "docketOpenDate not set:" in text
    assert "    read: 1" in text
    assert "    http-404: 1" in text


def test_report_omits_open_date_section_when_not_given() -> None:
    text = report(outcomes={"read": 1}, doc_counts=[1], by_stratum={}, attempted=1)
    assert "docketOpenDate" not in text


# --- has_open_date_set -----------------------------------------------------------------------


def test_has_open_date_set_reads_the_records_own_field(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_month(
        raw,
        Month(2026, 8),
        [
            _record(ntsbNumber="CEN26LA020", mKey=3001, docketOpenDate="2026-09-10"),
            _record(ntsbNumber="CEN26LA021", mKey=3002, docketOpenDate=""),
            _record(ntsbNumber="CEN26LA022", mKey=3003),
        ],
        "2026-09-20T00:00:00",
    )
    flags = has_open_date_set(raw)
    assert flags == {3001: True, 3002: False, 3003: False}


# --- draw / population_sizes ------------------------------------------------------------------


def test_draw_keeps_only_ongoing_aviation_ga_cases(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    today = date(2026, 9, 22)
    _write_month(
        raw,
        Month(2026, 8),
        [
            _record(ntsbNumber="CEN26LA001", mKey=1001, eventDate="2026-09-01"),  # ok, 0-30
            _record(
                ntsbNumber="CEN26LA002", mKey=1002, eventDate="2026-08-01", mode="Highway"
            ),  # wrong mode
            _record(
                ntsbNumber="CEN26LA003",
                mKey=1003,
                eventDate="2026-08-01",
                completionStatus="Completed",
            ),  # closed
            _record(
                ntsbNumber="CEN26LA004",
                mKey=1004,
                eventDate="2026-08-01",
                aircrafts=[{"ownerOperators": [{"regulationFlightConductedUnder": "135"}]}],
            ),  # not GA
            _record(
                ntsbNumber="CEN26LA005",
                mKey=1005,
                eventDate="2026-03-01",
                aircrafts=[{"ownerOperators": [{}]}],
            ),  # regulation not yet recorded -- still in population, 91-180 stratum
        ],
        "2026-09-20T00:00:00",
    )
    drawn = draw(raw, 100, seed=1, today=today)
    assert sorted(drawn) == [(1001, 21), (1005, 205)]
    assert stratify(21) == "0-30"
    assert stratify(205) == "181+"


def test_draw_is_deterministic_for_a_fixed_seed(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    today = date(2026, 9, 22)
    records = [
        _record(ntsbNumber=f"CEN26LA{i:03d}", mKey=2000 + i, eventDate="2026-09-01")
        for i in range(3)
    ]
    _write_month(raw, Month(2026, 8), records, "2026-09-20T00:00:00")
    first = draw(raw, 1, seed=7, today=today)
    second = draw(raw, 1, seed=7, today=today)
    assert first == second
    assert len(first) == 1
    assert first[0][0] in {2000, 2001, 2002}
    assert first[0][1] == 21


def test_draw_splits_evenly_across_populated_strata(tmp_path: Path) -> None:
    """Two strata, two candidates each: an even (1, 1) share, not all from one stratum."""
    raw = tmp_path / "raw"
    today = date(2026, 9, 22)
    records = [
        _record(ntsbNumber="CEN26LA010", mKey=2010, eventDate="2026-09-01"),  # 0-30
        _record(ntsbNumber="CEN26LA011", mKey=2011, eventDate="2026-09-02"),  # 0-30
        _record(ntsbNumber="CEN26LA012", mKey=2012, eventDate="2026-08-01"),  # 31-90
        _record(ntsbNumber="CEN26LA013", mKey=2013, eventDate="2026-07-31"),  # 31-90
    ]
    _write_month(raw, Month(2026, 8), records, "2026-09-20T00:00:00")
    drawn = draw(raw, 2, seed=3, today=today)
    assert len(drawn) == 2
    strata = sorted(stratify(days) for _, days in drawn)
    assert strata == ["0-30", "31-90"]


def test_draw_prefers_the_newest_fetch_of_a_case(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    today = date(2026, 9, 22)
    _write_month(
        raw, Month(2026, 8), [_record(completionStatus="Completed")], "2026-09-19T00:00:00"
    )
    _write_month(raw, Month(2026, 8), [_record()], "2026-09-20T00:00:00", refresh=True)
    drawn = draw(raw, 100, seed=1, today=today)
    assert drawn == [(1001, 21)]


def test_population_sizes_matches_what_draw_samples_from(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    today = date(2026, 9, 22)
    _write_month(raw, Month(2026, 8), [_record()], "2026-09-20T00:00:00")
    sizes = population_sizes(raw, today)
    assert sizes["0-30"] == 1
    assert sum(sizes.values()) == 1
    assert sorted(draw(raw, 100, seed=1, today=today)) == [(1001, 21)]


# --- main --------------------------------------------------------------------------------------


def test_main_writes_a_counts_only_report_and_no_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    # main() computes "today" from the real clock (datetime.now(UTC).date()), so the fixture
    # event dates are relative to that same clock, not a hardcoded date, so the test does not
    # depend on which day it happens to run.
    real_today = datetime.now(UTC).date()
    recent = (real_today - timedelta(days=10)).isoformat()  # 0-30 stratum
    old = (real_today - timedelta(days=250)).isoformat()  # 181+ stratum
    raw = tmp_path / "raw"
    _write_month(
        raw,
        Month(2026, 8),
        [
            _record(
                ntsbNumber="CEN26LA001", mKey=1001, eventDate=recent, docketOpenDate="2026-09-15"
            ),
            _record(ntsbNumber="CEN26LA002", mKey=1002, eventDate=old),
        ],
        "2026-09-20T00:00:00",
    )
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_DOCKET_SECONDS_PER_REQUEST", "0.001")
    respx_mock.get(sources.docket_url(1001)).mock(
        return_value=httpx.Response(200, text="<html>Docket Items: 0</html>")
    )
    respx_mock.get(sources.docket_url(1002)).mock(
        return_value=httpx.Response(404, text="not found")
    )
    out = tmp_path / "out.txt"
    assert main(["--n", "4", "--seed", "1", "--out", str(out)]) == 0
    text = out.read_text()
    assert "cases attempted: 2" in text
    assert "no-info-block: 1" in text
    assert "http-404: 1" in text
    assert "docketOpenDate set:" in text
    assert "docketOpenDate not set:" in text
    assert "1001" not in text
    assert "1002" not in text
    assert "CEN26LA001" not in text
    assert not (tmp_path / "docket").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt", "raw"]
