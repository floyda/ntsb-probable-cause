"""Docket documents from the cache, by case key and listing index (S2.6)."""

import threading
from collections.abc import Callable

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import Listing, parse_listing
from ntsb_probable_cause.errors import DocketError


class CachedDocuments:
    """Read documents the docket client has cached; safe to share between threads.

    The client decides whether a miss may fetch: S2.6's scripts build it with a transport
    that refuses every request, so a page never costs a fetch it was not meant to.
    """

    def __init__(self, client: DocketClient) -> None:
        self._client = client
        self._listings: dict[int, Listing] = {}
        self._lock = threading.Lock()

    def listing(self, mkey: int) -> Listing:
        """The case's parsed listing, parsed once."""
        with self._lock:
            if mkey not in self._listings:
                self._listings[mkey] = parse_listing(self._client.listing_html(mkey), mkey=mkey)
            return self._listings[mkey]

    def document(self, mkey: int, index: int) -> bytes:
        """One document's bytes, by its listing index."""
        for entry in self.listing(mkey).entries:
            if entry.index == index:
                return self._client.document(mkey, index, entry.href)
        raise DocketError(f"docket {mkey}: no document at index {index}")

    def loader(self, mkey: int, index: int) -> Callable[[], bytes]:
        """A zero-argument loader for a ``PageJob``."""
        return lambda: self.document(mkey, index)
