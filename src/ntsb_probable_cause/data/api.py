"""Client for the NTSB Enterprise API (spec: ../ntsb-spike/public.yaml).

Endpoints: GetCasesByDateRangeV2 (cases by event date, aviation only, paginated) and
GetCasesByModifiedDateRange (change feed, all modes, one response).
"""

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from types import TracebackType
from typing import Self

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ApiError

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_USER_AGENT = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"


@dataclass(frozen=True)
class Page:
    """One response page, kept byte-for-byte alongside its parsed records."""

    number: int
    content: bytes
    records: tuple[dict[str, object], ...]
    has_more: bool
    next_marker: str | None


class NtsbClient:
    """Marker-paginated, rate-limited, retrying client. One instance per run."""

    def __init__(  # noqa: PLR0913 -- signature is fixed by the S0 plan's Interfaces block.
        self,
        api_key: str,
        *,
        requests_per_minute: int = 30,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
    ) -> None:
        self._http = httpx.Client(
            base_url=sources.NTSB_BASE_URL,
            headers={
                sources.API_KEY_HEADER: api_key,
                "User-Agent": _USER_AGENT,
                "Cache-Control": "no-cache",
            },
            timeout=120.0,
            transport=transport,
        )
        self._gap = 60.0 / requests_per_minute
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._requested = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self._http.close()

    def cases_modified(self, start: date, end: date) -> tuple[dict[str, object], ...]:
        """Cases the NTSB changed in [start, end], all modes (decision 0065)."""
        content = self._get(
            sources.CASES_BY_MODIFIED_DATE_RANGE_V1,
            {"startDate": start.isoformat(), "endDate": end.isoformat()},
            name="GetCasesByModifiedDateRange",
        )
        try:
            payload = json.loads(content) if content.strip() else []
        except ValueError as error:
            raise ApiError("GetCasesByModifiedDateRange: not JSON") from error
        if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
            raise ApiError("GetCasesByModifiedDateRange: expected a JSON list of records")
        return tuple(payload)

    def cases_by_date_range(self, start: date, end: date) -> Iterator[Page]:
        """Yield every page of aviation cases whose event date lies in [start, end]."""
        params: dict[str, str] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "mode": sources.MODE_AVIATION,
        }
        number = 1
        while True:
            page = self._parse(
                number,
                self._get(sources.CASES_BY_DATE_RANGE_V2, params, name="GetCasesByDateRangeV2"),
            )
            yield page
            if not page.has_more:
                return
            if not page.next_marker:
                raise ApiError(f"page {number}: hasMore is true but nextMarker is missing")
            if page.next_marker == params.get("marker"):
                raise ApiError(
                    f"page {number}: nextMarker {page.next_marker!r} repeats the marker "
                    "just sent; pagination would loop forever"
                )
            params["marker"] = page.next_marker
            number += 1

    def _get(self, path: str, params: dict[str, str], *, name: str) -> bytes:
        for attempt in range(1, self._max_attempts + 1):
            if self._requested:
                self._sleep(self._gap)
            self._requested = True
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as error:
                status: object = type(error).__name__
            else:
                if response.is_success:
                    return response.content
                status = response.status_code
                if response.status_code not in _RETRY_STATUSES:
                    raise ApiError(f"{name} returned {status}: {response.text[:200]}")
            if attempt < self._max_attempts:
                self._sleep(self._backoff * 2 ** (attempt - 1))
        raise ApiError(f"{name} failed after {self._max_attempts} attempts; last status {status}")

    @staticmethod
    def _parse(number: int, content: bytes) -> Page:
        try:
            payload = json.loads(content) if content.strip() else {}
        except ValueError as error:
            raise ApiError(f"page {number}: not JSON") from error
        if not isinstance(payload, dict):
            raise ApiError(f"page {number}: expected a JSON object")
        data = payload.get("data", [])
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ApiError(f"page {number}: 'data' is not a list of records")
        marker = payload.get("nextMarker")
        return Page(
            number=number,
            content=content,
            records=tuple(data),
            has_more=payload.get("hasMore") is True,
            next_marker=marker if isinstance(marker, str) and marker else None,
        )
