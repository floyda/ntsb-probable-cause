"""Client for the NTSB Enterprise API's GetCasesByDateRangeV2 (spec: ../ntsb-spike/public.yaml)."""

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
_CLIENT_ERROR_THRESHOLD = 400


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

    def __init__(  # noqa: PLR0913 -- signature is fixed by the S0 spec's Interfaces block.
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

    def cases_by_date_range(self, start: date, end: date) -> Iterator[Page]:
        """Yield every page of aviation cases whose event date lies in [start, end]."""
        params: dict[str, str] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "mode": sources.MODE_AVIATION,
        }
        number = 1
        while True:
            page = self._parse(number, self._get(params))
            yield page
            if not page.has_more or not page.next_marker:
                return
            params["marker"] = page.next_marker
            number += 1

    def _get(self, params: dict[str, str]) -> bytes:
        for attempt in range(1, self._max_attempts + 1):
            if self._requested:
                self._sleep(self._gap)
            self._requested = True
            try:
                response = self._http.get(sources.CASES_BY_DATE_RANGE_V2, params=params)
            except httpx.TransportError as error:
                status: object = type(error).__name__
            else:
                if response.status_code < _CLIENT_ERROR_THRESHOLD:
                    return response.content
                status = response.status_code
                if response.status_code not in _RETRY_STATUSES:
                    raise ApiError(
                        f"GetCasesByDateRangeV2 returned {status}: {response.text[:200]}"
                    )
            if attempt < self._max_attempts:
                self._sleep(self._backoff * 2 ** (attempt - 1))
        raise ApiError(
            f"GetCasesByDateRangeV2 failed after {self._max_attempts} attempts; "
            f"last status {status}"
        )

    @staticmethod
    def _parse(number: int, content: bytes) -> Page:
        payload = json.loads(content) if content.strip() else {}
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
