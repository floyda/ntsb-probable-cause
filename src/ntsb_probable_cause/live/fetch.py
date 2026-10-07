"""Fetching one closed case's record and docket before its first model call (spec section 6).

A failure here costs nothing: the case simply stays in the queue for the next morning.
"""

from collections.abc import Mapping
from typing import Final

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient, outcome_for_error
from ntsb_probable_cause.docket.listing import Listing, is_not_released, parse_listing
from ntsb_probable_cause.docket.manifest import Docket, read_docket
from ntsb_probable_cause.errors import ApiError, DocketError
from ntsb_probable_cause.fields import EVIDENCE_FIELDS, EvidenceRole
from ntsb_probable_cause.live.queue import QueuedCase

# docket.client.outcome_for_error's label for a status the site answered without retrying: the
# recorder reads it as "the site answered" (recorder.run._is_docket_outage_reason), and for a
# docket the one such answer that means "nothing there" is a 404.
_NO_DOCKET_STATUS: Final = "http-404"


class FetchError(Exception):
    """A case could not be fetched before its first model call: it returns to the queue."""


def fetch_record(client: NtsbClient, case: QueuedCase) -> dict[str, object]:
    """Fetch the case record whose ``mKey`` is the case's, from its event date's pages.

    Args:
        client: the NTSB API client.
        case: the queued case.

    Returns:
        The raw record.

    Raises:
        FetchError: the API failed, or no record on that date has the case's ``mKey``.
    """
    try:
        for page in client.cases_by_date_range(case.event_date, case.event_date):
            for record in page.records:
                if str(record.get("mKey")) == str(case.mkey):
                    return record
    except ApiError as error:
        raise FetchError(
            f"case record for {case.case_id}: API error (status {error.status})"
        ) from error
    raise FetchError(f"case record for {case.case_id}: no record with mKey {case.mkey}")


def prefetch_docket(client: DocketClient, mkey: int) -> Docket:
    """Read the case's docket, telling "no docket" from "the site did not answer".

    The site answers "no released docket" with an ordinary page (``docket.listing.
    is_not_released``), which becomes a docket with no entries; the case is then coded from
    its record alone. A 404 reads the same way. A listing request the site did not answer (a
    status or a transport failure that survived every retry), or a page that arrived but did
    not parse (a count mismatch, or no "Docket Information" block: a layout change, which
    must not read as "no docket"), raises ``FetchError``. The recorder keeps these apart in
    the same way (``recorder.dockets.observe_docket``). One document failing is not an
    error: it comes back with a ``"fetch failed"`` status.

    The caller builds ``client`` on ``Settings.live_docket_dir``: nothing here caches
    elsewhere.

    Args:
        client: the docket client.
        mkey: the case's key.

    Returns:
        The docket, with no entries when the site says there is none.

    Raises:
        FetchError: the listing could not be read.
    """
    try:
        page = client.listing_html(mkey)
    except DocketError as error:
        reason = outcome_for_error(str(error))
        if reason == _NO_DOCKET_STATUS:
            return _empty_docket(mkey)
        raise FetchError(f"docket {mkey}: listing not read ({reason})") from error
    if is_not_released(page):
        return _empty_docket(mkey)
    try:
        listing = parse_listing(page, mkey=mkey)
        if listing.info is None:
            raise FetchError(f"docket {mkey}: listing not read (no-info-block)")
        return read_docket(client, mkey)
    except DocketError as error:
        raise FetchError(f"docket {mkey}: listing not read ({error})") from error


def _empty_docket(mkey: int) -> Docket:
    return Docket(
        mkey=mkey,
        listing=Listing(mkey=mkey, declared_items=None, entries=()),
        documents=(),
        texts={},
    )


def prelim_present(raw: Mapping[str, object]) -> bool:
    """Whether the record holds preliminary-narrative text (the field the fields table names)."""
    for field in EVIDENCE_FIELDS:
        if field.role is EvidenceRole.PRELIM_NARRATIVE:
            return field.extract(raw) is not None
    return False
