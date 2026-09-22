"""The docket side of the nightly run: outcomes, the document diff, stored pages.

Nightly, for each watched case, this module fetches the docket's listing page once (the
docket client's cache off, per decision 0061: no document is ever downloaded), classifies the
poll's outcome, diffs the listed documents against what the store last saw, and writes
documents, document events, the poll row and a compressed copy of the page when its hash is
new (spec S2.5 §6.2, §6.4). Every "when" is an interval between two run ids: ``absent_run`` is
the last run that did not see a thing, ``present_run`` the first run that did (spec §3).
"""

import gzip
import hashlib
import logging
import re

from pydantic import BaseModel

from ntsb_probable_cause.docket.client import DocketClient, outcome_for_error
from ntsb_probable_cause.docket.listing import (
    DocketInfo,
    Listing,
    ListingEntry,
    is_not_released,
    parse_listing,
)
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.store import DocumentRow, Store

_log = logging.getLogger(__name__)

# The document's own numeric id, from its href, e.g.
# "/Docket/Document/docBLOB?ID=40469808&FileExtension=.PDF&FileName=...". The listing parser
# (docket/listing.py) already unescapes the href's HTML entities, so this never has to handle
# "&amp;ID=".
_DOC_ID = re.compile(r"[?&]ID=(\d+)")


class DocketOutcome(BaseModel, frozen=True):
    """What one call to :func:`observe_docket` did."""

    mkey: int
    outcome: str
    changed: bool
    new_documents: int
    suspected_renumbers: int
    failed: str | None


class DiffResult(BaseModel, frozen=True):
    """The document diff between a case's stored rows and one freshly parsed listing.

    Pure: :func:`diff_documents` never touches the store. ``appeared`` covers both a document
    never seen before and one that had previously disappeared and is present again.
    ``unchanged`` still carries a refreshed ``position`` (rows can be reordered on the page
    without any document itself changing) and a refreshed ``last_present_run``, so the caller
    still has to write it, even though it produces no ``document_events`` row.
    """

    appeared: tuple[DocumentRow, ...]
    revised: tuple[tuple[DocumentRow, DocumentRow], ...]
    disappeared: tuple[DocumentRow, ...]
    unchanged: tuple[DocumentRow, ...]
    suspected_renumbers: int


def doc_id_of(href: str) -> int | None:
    """The integer after ``ID=`` in a document's href, or ``None`` if it is not there.

    An entry with no parseable id is never silently skipped by the caller (:func:`observe_docket`
    fails the whole poll instead, spec §6.2 controller change 3) -- but ``diff_documents`` itself
    stays pure and simply cannot place such an entry in its ``current`` map.
    """
    match = _DOC_ID.search(href)
    return int(match.group(1)) if match else None


def diff_documents(
    previous: dict[int, DocumentRow],
    listing: Listing,
    *,
    mkey: int,
    run_id: int,
    absent_run: int | None,
) -> DiffResult:
    """Diff ``listing``'s entries against ``previous``. Pure: no store access.

    ``absent_run`` is the case's ``last_docket_run`` as of *before* this poll -- the interval
    start for any document appearing for the first time ever (``None`` on a case's first
    docket poll). A document returning after having disappeared instead uses its own stored
    ``gone_present_run`` (the run that first noticed it missing) as the interval start, since
    that is the last point this store can vouch the document was actually absent.

    Revision compares ``title``, ``pages`` and ``photos``. A "suspected re-number" is a
    disappeared row and an appeared row that agree on ``(title, pages)`` -- counted, never
    merged into one event, so the true appearance and disappearance both stay on the record.
    """
    current: dict[int, ListingEntry] = {}
    for entry in listing.entries:
        doc_id = doc_id_of(entry.href)
        if doc_id is not None:
            current[doc_id] = entry

    appeared: list[DocumentRow] = []
    revised: list[tuple[DocumentRow, DocumentRow]] = []
    unchanged: list[DocumentRow] = []
    for doc_id, entry in current.items():
        prior = previous.get(doc_id)
        is_returning = prior is not None and prior.gone_present_run is not None
        if prior is None or is_returning:
            row_absent_run = prior.gone_present_run if is_returning and prior else absent_run
            row_present_run = run_id
        else:
            row_absent_run = prior.absent_run
            row_present_run = prior.present_run
        row = DocumentRow(
            mkey=mkey,
            doc_id=doc_id,
            href=entry.href,
            position=entry.index,
            title=entry.title,
            pages=entry.pages,
            photos=entry.photos,
            extension=entry.extension,
            absent_run=row_absent_run,
            present_run=row_present_run,
            last_present_run=run_id,
            gone_absent_run=None,
            gone_present_run=None,
        )
        if prior is None or is_returning:
            appeared.append(row)
        elif (prior.title, prior.pages, prior.photos) != (entry.title, entry.pages, entry.photos):
            revised.append((prior, row))
        else:
            unchanged.append(row)

    disappeared: list[DocumentRow] = []
    for doc_id, prior in previous.items():
        if prior.gone_present_run is not None or doc_id in current:
            continue
        disappeared.append(
            prior.model_copy(
                update={"gone_absent_run": prior.last_present_run, "gone_present_run": run_id}
            )
        )

    disappeared_keys = {(row.title, row.pages) for row in disappeared}
    suspected_renumbers = sum(1 for row in appeared if (row.title, row.pages) in disappeared_keys)

    return DiffResult(
        appeared=tuple(appeared),
        revised=tuple(revised),
        disappeared=tuple(disappeared),
        unchanged=tuple(unchanged),
        suspected_renumbers=suspected_renumbers,
    )


def _page_sha(page: str) -> str:
    return hashlib.sha256(page.encode()).hexdigest()


def _store_page(store: Store, mkey: int, page: str, run_id: int) -> str:
    """Gzip and store ``page`` keyed by its hash, unless that hash is already stored (0063)."""
    sha = _page_sha(page)
    if not store.has_page(sha):
        store.add_page(page_sha=sha, mkey=mkey, gz=gzip.compress(page.encode()), run_id=run_id)
    return sha


def _record_poll(  # noqa: PLR0913 -- one parameter per docket_polls column; a dataclass would
    # only move the same fields, and every caller below needs a different subset filled in.
    store: Store,
    mkey: int,
    *,
    run_id: int,
    outcome: str,
    reason: str | None,
    page: str | None,
    declared_items: int | None = None,
    info: DocketInfo | None = None,
) -> None:
    """Store the page (if any) and write the ``docket_polls`` row, inside the caller's transaction.

    Must be called from within a ``with store.transaction():`` block.
    """
    page_sha = _store_page(store, mkey, page, run_id) if page is not None else None
    store.add_docket_poll(
        mkey,
        run_id=run_id,
        outcome=outcome,
        reason=reason,
        declared_items=declared_items,
        creation_date=info.creation_date if info is not None else None,
        last_modified=info.last_modified if info is not None else None,
        release_date=info.release_date if info is not None else None,
        page_sha=page_sha,
    )


def _apply_diff(store: Store, mkey: int, diff: DiffResult, *, run_id: int) -> None:
    for row in (
        *diff.appeared,
        *(new for _old, new in diff.revised),
        *diff.unchanged,
        *diff.disappeared,
    ):
        store.upsert_document(row)
    for row in diff.appeared:
        store.add_document_event(
            mkey,
            doc_id=row.doc_id,
            kind="appeared",
            absent_run=row.absent_run,
            present_run=run_id,
            run_id=run_id,
            old=None,
            new=row.model_dump(mode="json"),
        )
    for old, new in diff.revised:
        store.add_document_event(
            mkey,
            doc_id=new.doc_id,
            kind="revised",
            absent_run=old.last_present_run,
            present_run=run_id,
            run_id=run_id,
            old=old.model_dump(mode="json"),
            new=new.model_dump(mode="json"),
        )
    for row in diff.disappeared:
        store.add_document_event(
            mkey,
            doc_id=row.doc_id,
            kind="disappeared",
            absent_run=row.gone_absent_run,
            present_run=run_id,
            run_id=run_id,
            old=row.model_dump(mode="json"),
            new=None,
        )


def _log_outcome(  # noqa: PLR0913 -- one parameter per the spec §9.1 log line's own fields.
    mkey: int, outcome: str, *, items: int = 0, new: int = 0, revised: int = 0, gone: int = 0
) -> None:
    _log.info(
        "docket mkey=%d outcome=%s items=%d new=%d revised=%d gone=%d",
        mkey,
        outcome,
        items,
        new,
        revised,
        gone,
    )


def _failed(  # noqa: PLR0913 -- one parameter per optional docket_polls column a failure may carry.
    store: Store,
    mkey: int,
    *,
    run_id: int,
    reason: str,
    page: str | None,
    declared_items: int | None = None,
    info: DocketInfo | None = None,
) -> DocketOutcome:
    with store.transaction():
        _record_poll(
            store,
            mkey,
            run_id=run_id,
            outcome="failed",
            reason=reason,
            page=page,
            declared_items=declared_items,
            info=info,
        )
    _log_outcome(mkey, "failed")
    return DocketOutcome(
        mkey=mkey,
        outcome="failed",
        changed=False,
        new_documents=0,
        suspected_renumbers=0,
        failed=reason,
    )


def observe_docket(store: Store, client: DocketClient, mkey: int, *, run_id: int) -> DocketOutcome:
    """One nightly poll of a case's docket listing: outcome, page storage, the document diff.

    Outcome rules (spec §6.2, controller changes over the plan's original design):

    - a fetch error (``DocketClient.listing_html`` raises ``DocketError``) -> ``"failed"``;
    - the site's own "has not been released" page (:func:`~docket.listing.is_not_released`,
      an ordinary HTTP 200 -- Task 3's live probe found the site never answers "no docket"
      with an HTTP status) -> ``"no-docket"``;
    - the page's declared item count disagrees with its parsed rows
      (``parse_listing`` raises ``DocketError``) -> ``"failed"`` (``count-mismatch``);
    - no "Docket Information" block -> ``"failed"`` (``no-info-block``): a page with no count
      *and* no sentence stays in this bucket too, so a genuine layout change stays visible
      instead of being silently read as "no docket";
    - a listed entry with no parseable document id -> ``"failed"`` (``entry-without-id``):
      nothing is diffed, since skipping just that entry would make an existing document whose
      link format changed look like it disappeared;
    - otherwise ``"read"`` (or ``"empty"`` if the listing has no entries).

    Only ``"read"``/``"empty"`` run the document diff. A ``"no-docket"`` poll is itself an
    observation of absence (spec §3): it does not touch a document, but it does update the
    case's ``last_docket_run``, so the next document that appears still gets a correct
    interval. A ``"failed"`` poll updates nothing, so its interval simply widens the next
    successful poll's.

    The page is stored (gzipped, hashed, deduplicated by hash) for every outcome where a page
    was actually received -- ``read``, ``empty``, ``no-docket``, and the ``failed`` outcomes
    ``count-mismatch``, ``no-info-block`` and ``entry-without-id`` -- because the page is
    exactly what a later re-parse needs (spec §6.4). It is never stored for a fetch error,
    since no page was received.

    Raises:
        ValueError: no ``cases`` row exists for ``mkey``. The nightly run (Task 9) only calls
            this for mkeys drawn from ``store.watched_mkeys``, so a missing row means the
            caller has a bug -- there is nothing sensible to diff or record against.
    """
    case = store.get_case(mkey)
    if case is None:
        raise ValueError(f"docket poll for unknown case mkey={mkey}")

    try:
        page = client.listing_html(mkey)
    except DocketError as error:
        return _failed(store, mkey, run_id=run_id, reason=outcome_for_error(str(error)), page=None)

    if is_not_released(page):
        with store.transaction():
            _record_poll(store, mkey, run_id=run_id, outcome="no-docket", reason=None, page=page)
            store.upsert_case(case.model_copy(update={"last_docket_run": run_id}))
        _log_outcome(mkey, "no-docket")
        return DocketOutcome(
            mkey=mkey,
            outcome="no-docket",
            changed=False,
            new_documents=0,
            suspected_renumbers=0,
            failed=None,
        )

    try:
        listing = parse_listing(page, mkey=mkey)
    except DocketError:
        return _failed(store, mkey, run_id=run_id, reason="count-mismatch", page=page)

    if listing.info is None:
        return _failed(
            store,
            mkey,
            run_id=run_id,
            reason="no-info-block",
            page=page,
            declared_items=listing.declared_items,
        )

    if any(doc_id_of(entry.href) is None for entry in listing.entries):
        return _failed(
            store,
            mkey,
            run_id=run_id,
            reason="entry-without-id",
            page=page,
            declared_items=listing.declared_items,
            info=listing.info,
        )

    outcome = "read" if listing.entries else "empty"
    previous = store.documents_for(mkey)
    diff = diff_documents(
        previous, listing, mkey=mkey, run_id=run_id, absent_run=case.last_docket_run
    )

    with store.transaction():
        _record_poll(
            store,
            mkey,
            run_id=run_id,
            outcome=outcome,
            reason=None,
            page=page,
            declared_items=listing.declared_items,
            info=listing.info,
        )
        _apply_diff(store, mkey, diff, run_id=run_id)
        store.upsert_case(case.model_copy(update={"last_docket_run": run_id}))

    changed = bool(diff.appeared or diff.revised or diff.disappeared)
    _log_outcome(
        mkey,
        outcome,
        items=len(listing.entries),
        new=len(diff.appeared),
        revised=len(diff.revised),
        gone=len(diff.disappeared),
    )
    return DocketOutcome(
        mkey=mkey,
        outcome=outcome,
        changed=changed,
        new_documents=len(diff.appeared),
        suspected_renumbers=diff.suspected_renumbers,
        failed=None,
    )
