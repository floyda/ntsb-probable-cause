import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx
from scripts.make_fixture import _amateur_built_name_risk, make_record_fixture

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.data.redaction import find_redacted_fields
from ntsb_probable_cause.errors import FixtureError

FIXTURES = Path("tests/fixtures")


def test_no_fixture_file_contains_a_redacted_field() -> None:
    offenders = {
        str(path): found
        for path in FIXTURES.rglob("*.json")
        if (found := find_redacted_fields(json.loads(path.read_text())))
    }
    assert offenders == {}


def test_record_fixtures_cover_the_spec_cases(record_fixtures: list[dict[str, object]]) -> None:
    assert len(record_fixtures) >= 8
    classes = Counter(str(r["ntsbNumber"])[5] for r in record_fixtures)
    assert {"C", "L", "F"} <= set(classes)
    assert any(len(cast("list[object]", r.get("aircrafts") or [])) > 1 for r in record_fixtures)


def test_api_page_fixture_parses_with_the_real_client(respx_mock: respx.MockRouter) -> None:
    content = (FIXTURES / "api/page.json").read_bytes()
    respx_mock.get().mock(return_value=httpx.Response(200, content=content))
    with NtsbClient("k", sleep=lambda _: None) as client:
        pages = list(
            client.cases_by_date_range(datetime(2016, 8, 1).date(), datetime(2016, 8, 31).date())
        )
    payload = json.loads(content)
    assert len(pages[0].records) == payload["pageSize"] == len(payload["data"])


def test_make_record_fixture_refuses_held_out_case() -> None:
    with pytest.raises(FixtureError, match="2020"):
        make_record_fixture({"ntsbNumber": "X", "eventDate": "2020-01-01"}, datetime.now(UTC))


def test_make_record_fixture_redacts_and_records_provenance() -> None:
    record = {
        "ntsbNumber": "X",
        "eventDate": "2016-08-01",
        "aircrafts": [{"ownerOperators": [{"ownerZip": "1"}]}],
    }
    fixture = make_record_fixture(record, datetime(2026, 9, 13, tzinfo=UTC))
    assert find_redacted_fields(fixture) == []
    assert (
        cast("dict[str, object]", fixture["fixture"])["fetched_at"] == "2026-09-13T00:00:00+00:00"
    )


def test_amateur_built_flag_is_a_name_risk_even_with_no_narrative_match() -> None:
    record = {"aircrafts": [{"aircraftAmateurBuilt": True, "aircraftMake": "CESSNA"}]}
    assert _amateur_built_name_risk(record) is True


def test_make_naming_the_builder_in_a_narrative_is_a_name_risk() -> None:
    record = {
        "aircrafts": [{"aircraftAmateurBuilt": False, "aircraftMake": "Example Builder"}],
        "narratives": [
            {"concatenatedFactualNarrative": "The pilot, flying an EXAMPLE BUILDER RV-7, ..."}
        ],
    }
    assert _amateur_built_name_risk(record) is True


def test_ordinary_manufacturer_with_no_narrative_match_is_not_a_name_risk() -> None:
    record = {
        "aircrafts": [{"aircraftAmateurBuilt": False, "aircraftMake": "CESSNA"}],
        "narratives": [{"concatenatedFactualNarrative": "The pilot landed short of the runway."}],
    }
    assert _amateur_built_name_risk(record) is False
