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
    population_skips,
    report,
    stratify,
)

from ntsb_probable_cause import sources
from ntsb_probable_cause.data.api import Page
from ntsb_probable_cause.data.ingest import Month, fetch_months
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import DocketError

SAVED = Path("tests/fixtures/docket/ERA17LA217/listing.html").read_bytes().decode("utf-8")
MKEY = 95459

# tests/fixtures/docket/not-released.html: the site's real answer for ProjectID 999999999, a
# nonexistent case (fetched 2026-09-22 by the controller during Task 3's live run) -- not
# open-split data, since no such case exists (decision 0024 governs real cases, not this).
# HTTP 200, title "NTSB Docket - Docket Management System", no item count, no info block, and
# one line reading "The docket for this investigation has not been released."
NOT_RELEASED = Path("tests/fixtures/docket/not-released.html").read_bytes().decode("utf-8")


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


def test_page_without_a_count_or_a_block_is_distinguished() -> None:
    """Fix round 1, IMPORTANT 2: a docket shell (a count, no info block) is not the same
    outcome as an unrelated 200 page (a maintenance page, say) with no docket text at all."""
    assert classify_page("<html>nothing to see here</html>", 1) == "no-info-block-no-count"


def test_the_sites_not_released_page_classifies_as_not_released() -> None:
    """Fix round 2 (Andy's decision, after the live run): the site's real answer for a case
    with no public docket at all is an HTTP 200 page carrying this sentence, not an error."""
    assert classify_page(NOT_RELEASED, 999999999) == "not-released"


def test_the_same_page_without_the_sentence_is_no_info_block_no_count() -> None:
    """Without the sentence, the page has no count and no info block either, so it still
    falls into no-info-block-no-count -- a layout change away from the known sentence stays
    visible rather than silently landing back in "not-released"."""
    stripped = NOT_RELEASED.replace(
        "The docket for this investigation has not been released.", "Some other message."
    )
    assert classify_page(stripped, 999999999) == "no-info-block-no-count"


def test_not_released_survives_a_reflow() -> None:
    """Matched after whitespace-normalising, so a reflow of the surrounding markup -- extra
    line breaks or runs of spaces inside the sentence itself -- does not defeat the match."""
    reflowed = (
        "<html>\n  <h5>\n    The docket   for this investigation\n    has not been "
        "released.\n  </h5>\n</html>"
    )
    assert classify_page(reflowed, 1) == "not-released"


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


def test_outcome_for_error_parses_a_non_retried_status() -> None:
    message = "https://data.ntsb.gov/Docket?ProjectID=1 returned 404"
    assert outcome_for_error(message) == "http-404"


def test_outcome_for_error_parses_an_exhausted_numeric_status() -> None:
    message = "https://data.ntsb.gov/Docket?ProjectID=1 failed after 5 attempts; last status 500"
    assert outcome_for_error(message) == "http-500-after-retries"


def test_outcome_for_error_parses_an_exhausted_transport_error() -> None:
    message = (
        "https://data.ntsb.gov/Docket?ProjectID=1 failed after 5 attempts; last status ConnectError"
    )
    assert outcome_for_error(message) == "fetch-failed: ConnectError"


def test_outcome_for_error_falls_back_on_an_unrecognised_message() -> None:
    assert outcome_for_error("nothing recognisable here") == "fetch-failed"


def test_outcome_for_error_matches_a_real_non_retried_status(
    respx_mock: respx.MockRouter,
) -> None:
    """Driven through the real client, not a hand-typed string: breaks if its wording changes."""
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(404))
    sleeps: list[float] = []
    with (
        DocketClient(None, seconds_per_request=2.0, sleep=sleeps.append) as client,
        pytest.raises(DocketError) as excinfo,
    ):
        client.listing_html(MKEY)
    assert outcome_for_error(str(excinfo.value)) == "http-404"
    assert sleeps == []  # a non-retried status never sleeps at all


def test_outcome_for_error_matches_a_real_exhausted_numeric_status(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(500))
    sleeps: list[float] = []
    with (
        DocketClient(None, seconds_per_request=2.0, sleep=sleeps.append) as client,
        pytest.raises(DocketError) as excinfo,
    ):
        client.listing_html(MKEY)
    assert outcome_for_error(str(excinfo.value)) == "http-500-after-retries"
    assert sleeps  # every retry asked to sleep; injected, so none of it was real


def test_outcome_for_error_matches_a_real_exhausted_transport_error(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(sources.docket_url(MKEY)).mock(side_effect=httpx.ConnectError("boom"))
    sleeps: list[float] = []
    with (
        DocketClient(None, seconds_per_request=2.0, sleep=sleeps.append) as client,
        pytest.raises(DocketError) as excinfo,
    ):
        client.listing_html(MKEY)
    assert outcome_for_error(str(excinfo.value)) == "fetch-failed: ConnectError"


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


def test_report_states_the_no_event_date_skip_count() -> None:
    text = report(outcomes={"read": 1}, doc_counts=[1], by_stratum={}, attempted=1)
    assert "skipped: no event date: 0" in text
    text = report(
        outcomes={"read": 1},
        doc_counts=[1],
        by_stratum={},
        attempted=1,
        skipped_no_event_date=3,
    )
    assert "skipped: no event date: 3" in text


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


def test_population_skips_counts_missing_and_unparsable_event_dates(tmp_path: Path) -> None:
    """Fix round 1, item d: a bad eventDate is a stated denominator, not a silent drop."""
    raw = tmp_path / "raw"
    today = date(2026, 9, 22)
    _write_month(
        raw,
        Month(2026, 8),
        [
            _record(ntsbNumber="CEN26LA030", mKey=4001, eventDate="2026-09-01"),  # kept
            _record(ntsbNumber="CEN26LA031", mKey=4002, eventDate="not-a-date"),  # unparsable
            _record(ntsbNumber="CEN26LA032", mKey=4003, eventDate=None),  # missing
        ],
        "2026-09-20T00:00:00",
    )
    assert population_skips(raw, today) == 2
    drawn = draw(raw, 100, seed=1, today=today)
    assert drawn == [(4001, 21)]


def test_draw_takes_every_member_of_a_stratum_smaller_than_its_share(tmp_path: Path) -> None:
    """A stratum with fewer candidates than its even share takes all of it, not a sample --
    what draw()'s min(shares[name], len(members)) already does; this pins the behaviour and
    what population_sizes reports for main()'s "drew N of M" line to describe it accurately.
    """
    raw = tmp_path / "raw"
    today = date(2026, 9, 22)
    _write_month(
        raw, Month(2026, 8), [_record(ntsbNumber="CEN26LA040", mKey=5001)], "2026-09-20T00:00:00"
    )
    drawn = draw(raw, 100, seed=1, today=today)  # share for "0-30" is 25; only 1 candidate exists
    assert drawn == [(5001, 21)]
    assert population_sizes(raw, today)["0-30"] == 1


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
    # Fix round 1, item c: NEVER override the polite rate to near-zero -- that is the one
    # thing the project rule forbids (docket_seconds_per_request is `gt=0` for a real reason:
    # data.ntsb.gov is a real government site). main() builds its own DocketClient without a
    # way to inject a fake `sleep`, so this test follows tests/test_docket_shape_open.py:70-71
    # instead: keep the real 2-second rate and keep the drawn set to exactly the two cases
    # above, so there is only ever one real gap to wait out, not zero or none. NTSB_DOCKET_DIR
    # is pinned to a tmp path too, as that precedent does, even though DocketClient(None, ...)
    # never writes to it.
    monkeypatch.setenv("NTSB_DOCKET_DIR", str(tmp_path / "docket"))
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
    assert "skipped: no event date: 0" in text
    assert "no-info-block: 1" in text
    assert "http-404: 1" in text
    assert "docketOpenDate set:" in text
    assert "docketOpenDate not set:" in text
    assert "drew 1 of 1 0-30-day ongoing cases in the population" in text
    assert "drew 1 of 1 181+-day ongoing cases in the population" in text
    assert f"raw store fetched as of {date(2026, 9, 20).isoformat()}" in text
    assert "1001" not in text
    assert "1002" not in text
    assert "CEN26LA001" not in text
    assert not (tmp_path / "docket").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt", "raw"]
