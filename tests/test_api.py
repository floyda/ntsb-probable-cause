from datetime import date

import httpx
import pytest
import respx

from ntsb_probable_cause.data.api import NtsbClient, Page
from ntsb_probable_cause.errors import ApiError

URL = "https://api.ntsb.gov/public/api/Common/v2/GetCasesByDateRange/"
URL_MODIFIED = "https://api.ntsb.gov/public/api/Common/v1/GetCasesByModifiedDateRange/"


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
    with client([]) as c, pytest.raises(ApiError, match="500"):
        fetch(c)


def test_client_error_is_not_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(return_value=httpx.Response(401))
    with client([]) as c, pytest.raises(ApiError, match="401"):
        fetch(c)
    assert route.call_count == 1


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
