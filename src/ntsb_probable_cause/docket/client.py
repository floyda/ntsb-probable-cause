"""Fetch a docket's listing page and documents politely, into a cache keyed by case (spec §4.2)."""

import hashlib
import json
import re
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

# The two ``DocketError`` message shapes ``_get`` raises below: a non-retried status,
# ``f"{url} returned {status}"`` (excluded from ``_RETRY_STATUSES``, most likely a 404 for a
# case with no docket); and an exhausted-retries message once every attempt is spent,
# ``f"{url} failed after {n} attempts; last status {status}"``, where ``status`` is either a
# retried HTTP status code that persisted (an int) or a transport exception's class name (the
# ``except httpx.TransportError`` branch below sets ``status = type(error).__name__``). Tried
# in that order so the non-retried form is never mistaken for the other. Originally
# scripts/ongoing_docket_probe.py's own ``outcome_for_error``; Task 8 moved it here so the
# probe and the recorder (``recorder/dockets.py``) share one implementation.
_RETURNED_STATUS = re.compile(r"returned (\d+)$")
_LAST_STATUS = re.compile(r"last status (\S+)$")


def outcome_for_error(message: str) -> str:
    """Classify a ``DocketError`` message into a short, loggable reason string.

    A non-retried status: ``"http-<status>"``. A status that persisted through every retry:
    ``"http-<status>-after-retries"`` -- kept distinct from a non-retried status, and from a
    plain network failure, since a persistent 500 or 429 is not the same finding as either. A
    transport failure that exhausted every retry: ``"fetch-failed: <ExceptionClassName>"``, the
    class name only -- never the full message, which may embed a URL. Anything unrecognised:
    ``"fetch-failed"``.
    """
    returned = _RETURNED_STATUS.search(message)
    if returned:
        return f"http-{returned.group(1)}"
    exhausted = _LAST_STATUS.search(message)
    if exhausted:
        token = exhausted.group(1)
        return f"http-{token}-after-retries" if token.isdigit() else f"fetch-failed: {token}"
    return "fetch-failed"


def _load_manifest(cache: Path, mkey: int) -> dict[str, object]:
    """The parsed ``fetch.json`` for a case, or ``{}`` if it is missing or not an object."""
    fetch_path = cache / str(mkey) / FETCH_FILE
    if not fetch_path.is_file():
        return {}
    loaded = json.loads(fetch_path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _read_verified(cache: Path, mkey: int, name: str, entry: dict[str, object]) -> bytes | None:
    """The cached file's bytes, or ``None`` if missing or its hash disagrees with the manifest.

    A hash mismatch is what a kill mid-write, or any other partial or corrupted file, looks
    like -- the write path below never leaves such a file at this name, but a reader must not
    trust a name alone (fix round 1, Finding 3).
    """
    path = cache / str(mkey) / name
    if not path.is_file():
        return None
    content = path.read_bytes()
    if entry.get("sha256") != hashlib.sha256(content).hexdigest():
        return None
    return content


def _write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so a reader never observes a partial file.

    Mirrors the judge run's ``judge.jsonl.partial`` -> ``judge.jsonl`` shape (spec §3.5): write
    to a sibling name first, then rename into place. A kill mid-write leaves either the
    previous complete file or nothing at ``path`` -- never a truncated one (fix round 1,
    Finding 3). Renaming within one cache-entry directory is a same-filesystem move.
    """
    tmp_path = path.with_name(f"{path.name}.partial")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)


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
        cache = self._cache
        if cache is not None:
            entry = _load_manifest(cache, mkey).get("listing")
            if isinstance(entry, dict):
                cached = _read_verified(cache, mkey, LISTING_FILE, entry)
                if cached is not None:
                    return cached.decode("utf-8", "replace")
        content = self._get(sources.docket_url(mkey))
        self._store(mkey, LISTING_FILE, content, {"listing": self._entry(content)})
        return content.decode("utf-8", "replace")

    def document(self, mkey: int, index: int, href: str) -> bytes:
        """One document's bytes, from the cache or one polite fetch.

        A cached entry whose recorded ``href`` disagrees with the one asked for is treated as
        a miss and re-fetched: a docket gains documents over time, the listing order can
        shift, and an index alone does not identify a document (fix round 1, Finding 2).
        """
        name = f"{index}.bin"
        cache = self._cache
        if cache is not None:
            documents = _load_manifest(cache, mkey).get("documents")
            entry = documents.get(str(index)) if isinstance(documents, dict) else None
            if isinstance(entry, dict) and entry.get("href") == href:
                cached = _read_verified(cache, mkey, name, entry)
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

    def _store(self, mkey: int, name: str, content: bytes, fetch_update: dict[str, object]) -> None:
        if self._cache is None:
            return
        folder = self._cache / str(mkey)
        folder.mkdir(parents=True, exist_ok=True)
        _write_atomic(folder / name, content)
        fetch = _load_manifest(self._cache, mkey)
        documents = fetch.get("documents")
        update = fetch_update.get("documents")
        if isinstance(documents, dict) and isinstance(update, dict):
            documents.update(update)
        else:
            fetch.update(fetch_update)
        _write_atomic(folder / FETCH_FILE, json.dumps(fetch, indent=1, sort_keys=True).encode())

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
