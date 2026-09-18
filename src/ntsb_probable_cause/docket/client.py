"""Fetch a docket's listing page and documents politely, into a cache keyed by case (spec §4.2)."""

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import DocketError

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
LISTING_FILE = "listing.html"
FETCH_FILE = "fetch.json"


class DocketClient:
    """One request every ``seconds_per_request``; every fetch cached unless ``cache_dir`` is None.

    ``cache_dir=None`` is read-and-discard (decision 0040): nothing is written anywhere.
    """

    def __init__(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        cache_dir: Path | None,
        *,
        seconds_per_request: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._cache = cache_dir
        self._gap = seconds_per_request
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._now = now
        self._requested = False
        self._last_backoff_slept = 0.0
        self._http = httpx.Client(
            headers={"User-Agent": sources.DOCKET_USER_AGENT},
            timeout=120.0,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    def listing_html(self, mkey: int) -> str:
        """The listing page for a case, from the cache or one polite fetch."""
        cached = self._cached(mkey, LISTING_FILE)
        if cached is not None:
            return cached.decode("utf-8", "replace")
        content = self._get(sources.docket_url(mkey))
        self._store(mkey, LISTING_FILE, content, {"listing": self._entry(content)})
        return content.decode("utf-8", "replace")

    def document(self, mkey: int, index: int, href: str) -> bytes:
        """One document's bytes, from the cache or one polite fetch."""
        name = f"{index}.bin"
        cached = self._cached(mkey, name)
        if cached is not None:
            return cached
        content = self._get(sources.docket_document_url(href))
        self._store(
            mkey,
            name,
            content,
            {"documents": {str(index): {**self._entry(content), "href": href}}},
        )
        return content

    def _entry(self, content: bytes) -> dict[str, str]:
        return {"time": self._now().isoformat(), "sha256": hashlib.sha256(content).hexdigest()}

    def _cached(self, mkey: int, name: str) -> bytes | None:
        if self._cache is None:
            return None
        path = self._cache / str(mkey) / name
        return path.read_bytes() if path.is_file() else None

    def _store(self, mkey: int, name: str, content: bytes, fetch_update: dict[str, object]) -> None:
        if self._cache is None:
            return
        folder = self._cache / str(mkey)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        fetch_path = folder / FETCH_FILE
        fetch: dict[str, object] = (
            json.loads(fetch_path.read_text()) if fetch_path.is_file() else {}
        )
        documents = fetch.get("documents")
        update = fetch_update.get("documents")
        if isinstance(documents, dict) and isinstance(update, dict):
            documents.update(update)
        else:
            fetch.update(fetch_update)
        fetch_path.write_text(json.dumps(fetch, indent=1, sort_keys=True))

    def _get(self, url: str) -> bytes:
        """One GET with the polite gap, retried with backoff on transport errors and 5xx.

        The gap is net of any backoff already slept -- the rule ``openrouter.py``'s
        ``request_json`` uses. A backoff of ``b`` seconds has already spaced the requests
        by ``b``, so the next gap sleep is ``gap - b`` when that is positive and is skipped
        otherwise. Without a preceding backoff the full gap applies.
        """
        status: object = None
        for attempt in range(1, self._max_attempts + 1):
            if self._requested:
                remaining_gap = self._gap - self._last_backoff_slept
                if remaining_gap > 0:
                    self._sleep(remaining_gap)
            self._requested = True
            self._last_backoff_slept = 0.0
            try:
                response = self._http.get(url)
            except httpx.TransportError as error:
                status = type(error).__name__
            else:
                if response.is_success:
                    return response.content
                status = response.status_code
                if response.status_code not in _RETRY_STATUSES:
                    raise DocketError(f"{url} returned {status}")
            if attempt < self._max_attempts:
                backoff = self._backoff * 2 ** (attempt - 1)
                self._sleep(backoff)
                self._last_backoff_slept = backoff
        raise DocketError(f"{url} failed after {self._max_attempts} attempts; last status {status}")
