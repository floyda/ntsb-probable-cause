import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from ntsb_probable_cause.data.api import NtsbClient, Page
from ntsb_probable_cause.errors import ApiError
from ntsb_probable_cause.recorder.run import _feed_rows
from ntsb_probable_cause.store import FeedRow

URL = "https://api.ntsb.gov/public/api/Common/v2/GetCasesByDateRange/"
URL_MODIFIED = "https://api.ntsb.gov/public/api/Common/v1/GetCasesByModifiedDateRange/"

# scripts/change_feed_probe.py (Task 11) writes this from a live response:
# {"shape": {key: [sorted type names]}, "last_change_utc_signatures": [masked format strings]}
# -- never a value (decision 0024). Committed by the controller after the one-shot live probe
# (`make change-feed-probe`) has run -- until then this file does not exist, and the test below
# is skipped with a clear reason rather than failing or being faked from a guess.
_CHANGE_FEED_SHAPE_FIXTURE = Path("tests/fixtures/api/change_feed_shape.json")

# One representative value per Python type name the fixture might record, for building a
# synthetic row that has the real shape without ever holding a real value.
_SYNTHETIC_VALUES: dict[str, object] = {
    "int": 1,
    "str": "x",
    "bool": True,
    "float": 1.0,
    "NoneType": None,
}

# Task 11 fix round 1, IMPORTANT 8: the six keys `recorder.run._feed_rows` actually reads
# (`recorder/run.py`'s `_feed_rows` docstring). The synthetic row overrides these with concrete,
# well-typed values instead of the generic per-type placeholder, so `_feed_rows` -- which
# filters on `mode == "Aviation"` and requires `mkey`/`lastChangeDateTimeUtc` to parse at all --
# actually keeps the row rather than silently dropping it.
_REQUIRED_FEED_KEYS = frozenset(
    {"mkey", "mode", "lastChangeDateTimeUtc", "stepNumber", "stepId", "caseClosed"}
)
_REQUIRED_OVERRIDES: dict[str, object] = {
    "mkey": 1,
    "mode": "Aviation",
    "lastChangeDateTimeUtc": "2026-01-01T00:00:00",
    "stepNumber": 1,
    "stepId": "S1",
    "caseClosed": True,
}


def body(data: list[dict[str, object]], has_more: bool, marker: str | None) -> dict[str, object]:
    return {
        "startDate": "2016-08-01",
        "endDate": "2016-08-31",
        "pageSize": len(data),
        "hasMore": has_more,
        "nextMarker": marker,
        "data": data,
    }


def client(sleeps: list[float]) -> NtsbClient:
    return NtsbClient("key-1", sleep=sleeps.append, backoff_seconds=1.0)


def fetch(c: NtsbClient) -> list[Page]:
    return list(c.cases_by_date_range(date(2016, 8, 1), date(2016, 8, 31)))


def test_pages_until_has_more_is_false(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=body([{"ntsbNumber": "A"}], True, "m1")),
            httpx.Response(200, json=body([{"ntsbNumber": "B"}], False, None)),
        ]
    )
    sleeps: list[float] = []
    with client(sleeps) as c:
        pages = list(c.cases_by_date_range(date(2016, 8, 1), date(2016, 8, 31)))
    assert [p.number for p in pages] == [1, 2]
    assert [r["ntsbNumber"] for p in pages for r in p.records] == ["A", "B"]
    first, second = (call.request for call in route.calls)
    assert first.url.params["startDate"] == "2016-08-01"
    assert first.url.params["endDate"] == "2016-08-31"
    assert first.url.params["mode"] == "aviation"
    assert "marker" not in first.url.params
    assert second.url.params["marker"] == "m1"
    assert first.headers["Ocp-Apim-Subscription-Key"] == "key-1"
    assert sleeps == [2.0]  # 60 / 30 requests per minute, between requests


def test_page_content_is_kept_byte_for_byte(respx_mock: respx.MockRouter) -> None:
    raw = b'{"hasMore": false, "nextMarker": null, "data": [{"ntsbNumber": "A"}]}'
    respx_mock.get(URL).mock(return_value=httpx.Response(200, content=raw))
    with client([]) as c:
        (page,) = fetch(c)
    assert page.content == raw


def test_no_content_yields_one_empty_page(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(204))
    with client([]) as c:
        (page,) = fetch(c)
    assert page.records == ()
    assert page.has_more is False


def test_retries_429_and_503_with_backoff(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json=body([], False, None)),
        ]
    )
    sleeps: list[float] = []
    with client(sleeps) as c:
        fetch(c)
    assert sleeps == [1.0, 2.0, 2.0, 2.0]  # backoff 1, rate gap, backoff 2, rate gap


def test_gives_up_after_max_attempts(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(500))
    with client([]) as c, pytest.raises(ApiError, match="500") as excinfo:
        fetch(c)
    assert excinfo.value.status == 500  # Task 9 fix round 1, Important 2: the last HTTP status


def test_client_error_is_not_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(return_value=httpx.Response(401))
    with client([]) as c, pytest.raises(ApiError, match="401") as excinfo:
        fetch(c)
    assert route.call_count == 1
    assert excinfo.value.status == 401


def test_api_error_after_transport_failures_carries_the_exception_class_name(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with client([]) as c, pytest.raises(ApiError) as excinfo:
        fetch(c)
    assert excinfo.value.status == "ConnectError"


def test_api_error_with_no_status_to_report_leaves_it_none(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"data": "not a list"}))
    with client([]) as c, pytest.raises(ApiError) as excinfo:
        fetch(c)
    assert excinfo.value.status is None


def test_malformed_payload_raises(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"data": "not a list"}))
    with client([]) as c, pytest.raises(ApiError, match="data"):
        fetch(c)


def test_raises_when_has_more_is_true_and_marker_is_missing(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(URL).mock(
        return_value=httpx.Response(200, json=body([{"ntsbNumber": "A"}], True, None))
    )
    with client([]) as c, pytest.raises(ApiError, match="nextMarker"):
        fetch(c)


def test_raises_when_next_marker_repeats_the_marker_just_sent(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(URL).mock(
        return_value=httpx.Response(200, json=body([{"ntsbNumber": "A"}], True, "m1"))
    )
    with client([]) as c, pytest.raises(ApiError, match="repeats"):
        fetch(c)


def test_redirect_status_is_not_treated_as_success(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(302))
    with client([]) as c, pytest.raises(ApiError, match="302"):
        fetch(c)


def test_non_json_response_raises(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(200, content=b"<html>Bad Gateway</html>"))
    with client([]) as c, pytest.raises(ApiError, match="not JSON"):
        fetch(c)


def test_retries_transport_error_then_succeeds(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=body([], False, None))]
    )
    sleeps: list[float] = []
    with client(sleeps) as c:
        fetch(c)
    assert sleeps == [1.0, 2.0]  # backoff 1 after the transport error, then the rate gap


def test_cases_modified_returns_the_list(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL_MODIFIED).mock(
        return_value=httpx.Response(
            200, json=[{"mkey": 1, "mode": "Aviation"}, {"mkey": 2, "mode": "Railroad"}]
        )
    )
    with NtsbClient("k", sleep=lambda _s: None) as client:
        rows = client.cases_modified(date(2026, 9, 19), date(2026, 9, 21))
    assert [r["mkey"] for r in rows] == [1, 2]
    sent = respx_mock.calls.last.request.url.params
    assert sent["startDate"] == "2026-09-19"
    assert sent["endDate"] == "2026-09-21"
    assert "mode" not in sent


def test_cases_modified_rejects_an_object_body(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL_MODIFIED).mock(return_value=httpx.Response(200, json={}))
    with NtsbClient("k", sleep=lambda _s: None) as client, pytest.raises(ApiError):
        client.cases_modified(date(2026, 9, 19), date(2026, 9, 21))


def test_cases_modified_accepts_204_empty_body(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL_MODIFIED).mock(return_value=httpx.Response(204))
    with NtsbClient("k", sleep=lambda _s: None) as client:
        rows = client.cases_modified(date(2026, 9, 19), date(2026, 9, 21))
    assert rows == ()


def test_cases_modified_rejects_list_with_non_object_element(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL_MODIFIED).mock(return_value=httpx.Response(200, json=[1, {"mkey": 2}]))
    with NtsbClient("k", sleep=lambda _s: None) as client, pytest.raises(ApiError):
        client.cases_modified(date(2026, 9, 19), date(2026, 9, 21))


def test_cases_modified_rejects_non_json_body(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL_MODIFIED).mock(
        return_value=httpx.Response(200, content=b"<html>Bad Gateway</html>")
    )
    with NtsbClient("k", sleep=lambda _s: None) as client, pytest.raises(ApiError):
        client.cases_modified(date(2026, 9, 19), date(2026, 9, 21))


def test_cases_modified_401_names_the_endpoint(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL_MODIFIED).mock(return_value=httpx.Response(401))
    with (
        NtsbClient("k", sleep=lambda _s: None) as client,
        pytest.raises(ApiError, match="GetCasesByModifiedDateRange returned 401"),
    ):
        client.cases_modified(date(2026, 9, 19), date(2026, 9, 21))


def test_cases_by_date_range_401_names_the_endpoint(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(401))
    with client([]) as c, pytest.raises(ApiError, match="GetCasesByDateRangeV2 returned 401"):
        fetch(c)


def test_cases_modified_parses_the_confirmed_live_shape(respx_mock: respx.MockRouter) -> None:
    """Task 11: a synthetic row built from the committed change-feed shape fixture parses.

    Skipped, with a clear reason, until ``scripts/change_feed_probe.py`` has been run once
    against the live API and its fixture committed (Task 11 controller note 1) -- this is a
    structural sanity check (the endpoint still returns a JSON list of objects with these
    keys), not a claim that every field's meaning is validated.

    Fix round 1, IMPORTANT 8: also asserts the confirmed shape actually carries the six keys
    ``recorder.run._feed_rows`` reads, and that ``_feed_rows`` turns the synthetic row into a
    real :class:`~ntsb_probable_cause.store.FeedRow` -- not just that ``cases_modified`` can
    parse a JSON list of objects, which any shape at all would satisfy.
    """
    if not _CHANGE_FEED_SHAPE_FIXTURE.exists():
        pytest.skip(
            f"{_CHANGE_FEED_SHAPE_FIXTURE} does not exist yet -- run `make change-feed-probe` "
            "once against the live API (NTSB_API_KEY set) to record it, then commit the "
            "fixture; this test then stops skipping."
        )
    fixture = json.loads(_CHANGE_FEED_SHAPE_FIXTURE.read_text())
    shape = fixture["shape"]

    missing = _REQUIRED_FEED_KEYS - shape.keys()
    assert not missing, f"confirmed change-feed shape is missing required keys: {missing}"

    # Task 11 fix round 2, I8 (partial): assert the RECORDED types directly. The synthetic row
    # below overrides these six keys with concrete, well-typed values so `_feed_rows` actually
    # keeps the row (it filters on `mode == "Aviation"`) -- but that override alone would let a
    # fixture that recorded, say, `mkey: ["str"]` pass silently. These assertions check what
    # the live probe actually saw, independent of the override.
    assert "int" in shape["mkey"]
    assert "str" in shape["mode"]
    assert "str" in shape["lastChangeDateTimeUtc"]
    assert "int" in shape["stepNumber"]
    assert "str" in shape["stepId"]
    assert "bool" in shape["caseClosed"]

    row = {
        key: _REQUIRED_OVERRIDES.get(key, _SYNTHETIC_VALUES.get(types[0], "x"))
        for key, types in shape.items()
    }
    respx_mock.get(URL_MODIFIED).mock(return_value=httpx.Response(200, json=[row]))
    with NtsbClient("k", sleep=lambda _s: None) as c:
        rows = c.cases_modified(date(2026, 9, 19), date(2026, 9, 21))
    assert rows == (row,)

    feed_rows, skipped = _feed_rows(rows)
    assert skipped == 0
    assert feed_rows == [
        FeedRow(
            mkey=1,
            last_change_utc="2026-01-01T00:00:00",
            step_number=1,
            step_id="S1",
            case_closed=True,
        )
    ]
