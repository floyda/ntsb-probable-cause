"""The nightly pass: orchestration, summary, logging (spec S2.5 §9.1, Task 9).

:func:`run_night` ties together every earlier task in six ordered steps -- begin the run, work
out the month window, fetch the months and observe every watchable case, mark vanished cases,
store the change feed, poll every watched docket -- then finishes the run with a summary (see
:class:`~ntsb_probable_cause.store.RunSummary` for what each summary field means).

Failure isolation (spec §9.1). One case, one month or one docket poll failing never aborts the
night: an :class:`~ntsb_probable_cause.errors.ApiError` fetching a month, or a ``ValueError``
from :func:`~ntsb_probable_cause.recorder.dockets.observe_docket` for an mkey the store has no
``cases`` row for, is caught, logged and counted as one failure; the run continues. Any other
exception propagates -- the run fails loudly, and the caller (``apps/recorder``, Task 10) never
saves a store a run did not finish.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.data.ingest import Month
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import ApiError
from ntsb_probable_cause.recorder.cases import is_watchable, mark_not_returned, observe_case
from ntsb_probable_cause.recorder.dockets import observe_docket
from ntsb_probable_cause.recorder.window import first_run_window, month_window
from ntsb_probable_cause.splits import ONGOING_STATUS
from ntsb_probable_cause.store import FeedRow, RunSummary, Store

_log = logging.getLogger(__name__)
_RECORDER_LOGGER = "ntsb_probable_cause.recorder"

# The raw change-feed row's own field, capitalised, as the NTSB API returns it -- the same
# convention `recorder/cases.py`'s `_AVIATION_MODE` documents for the case-list endpoint.
_AVIATION_MODE = "Aviation"

# How far back the change feed is polled each night: two days, one request, per decision 0065
# and spec §5.3 -- wide enough to survive a missed or short run without a gap, since every row
# is upserted by (mkey, run_id) rather than by date and a re-seen row costs nothing extra.
_FEED_LOOKBACK_DAYS = 2


class NightInputs(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """Everything one nightly pass needs, injected so a test touches neither network nor clock.

    ``now`` is called repeatedly through the run (once per step boundary, for the per-step
    duration log lines) and must always return an aware datetime (see :func:`_utc`).
    """

    api: NtsbClient
    docket: DocketClient
    store: Store
    now: Callable[[], datetime]
    commit_sha: str
    dirty: bool


def _utc(moment: datetime) -> datetime:
    """``moment`` as an aware UTC datetime.

    Raises if ``moment`` is naive -- a naive clock cannot be trusted to mean UTC, and a wrong
    guess here would silently corrupt every interval and duration the night records -- then
    converts to UTC, so a clock that hands back some other real offset (never a case in
    production, since the scheduler and `launchd` both run in UTC, but cheap to allow) still
    yields a correct one. Raised, not asserted (``S101``): production code must not depend on
    assertions, which ``python -O`` strips.
    """
    if moment.tzinfo is None:
        raise AssertionError("NightInputs.now() must return an aware datetime")
    return moment.astimezone(UTC)


def _log_step(name: str, started: datetime, finished: datetime) -> None:
    """One line per step, with its duration (spec §9.1)."""
    _log.info("step=%s duration=%.1fs", name, (finished - started).total_seconds())


def _ongoing_by_month(store: Store, today: date) -> dict[str, set[int]]:
    """Watched cases whose *stored* status is ``Ongoing``, grouped by event month.

    This is the population :func:`mark_not_returned` may apply to tonight (controller
    resolution 1): a case already off ``Ongoing`` -- closed some other way, or already marked
    ``not returned`` -- is never re-marked by this function, whatever the API does or does not
    return for its month. The snapshot is taken once, before any of tonight's fetching or
    writing, so it reflects last night's state, not a case this run has already touched.
    """
    grouped: dict[str, set[int]] = {}
    for mkey in store.watched_mkeys(today=today.isoformat()):
        case = store.get_case(mkey)
        if case is not None and case.status == ONGOING_STATUS:
            grouped.setdefault(case.event_date[:7], set()).add(mkey)
    return grouped


def _observe_records(
    store: Store, records: Iterable[Mapping[str, object]], *, run_id: int, today: date
) -> tuple[set[int], int, set[int]]:
    """Filter and observe one batch of raw records (spec §9.1's per-record rule).

    ``if is_watchable(raw) or store.get_case(mkey) is not None: observe_case(...)`` -- a record
    that is neither watchable nor already known to the store is skipped entirely, never even
    split. Returns ``(seen, failures, changed)``: every mkey actually observed (whatever the
    outcome), how many of those observations failed, and which of them wrote something.
    """
    seen: set[int] = set()
    failures = 0
    changed: set[int] = set()
    for raw in records:
        mkey_value = raw.get("mKey")
        known = isinstance(mkey_value, int) and store.get_case(mkey_value) is not None
        if not (is_watchable(raw) or known):
            continue
        outcome = observe_case(store, raw, run_id=run_id, today=today)
        if isinstance(mkey_value, int):
            seen.add(mkey_value)
        if outcome.failed is not None:
            failures += 1
        elif outcome.changed:
            changed.add(outcome.mkey)
    return seen, failures, changed


def _observe_month_streaming(
    api: NtsbClient, store: Store, month: Month, *, run_id: int, today: date
) -> tuple[set[int], int, set[int], bool]:
    """Fetch one month page by page, observing as each page arrives.

    Controller resolution 1: a failed month is never evidence of absence. Observing page by
    page, rather than collecting the whole month first, means that if the API fails on page 2
    of 3, page 1's records have already been observed and committed (each :func:`observe_case`
    call is its own transaction) -- they stand. The failure itself is counted once, here, and
    the caller is told ``errored=True`` so it skips "not returned" marking for this month's
    watched cases entirely, rather than reading an incompletely-fetched month as absence.
    """
    seen: set[int] = set()
    failures = 0
    changed: set[int] = set()
    try:
        for page in api.cases_by_date_range(month.start, month.end):
            page_seen, page_failures, page_changed = _observe_records(
                store, page.records, run_id=run_id, today=today
            )
            seen |= page_seen
            failures += page_failures
            changed |= page_changed
    except ApiError as error:
        _log.warning("case month=%s failed=%s", month.label, type(error).__name__)
        return seen, failures + 1, changed, True
    return seen, failures, changed, False


def _fetch_and_keep(
    api: NtsbClient, kept: dict[str, list[dict[str, object]]], month: Month
) -> list[dict[str, object]]:
    """One month's full record list, fetched and also stashed in ``kept`` by month label.

    Used only as the ``fetch_month`` callback for :func:`~ntsb_probable_cause.recorder.window.
    first_run_window` (controller resolution 2): the walk-back needs every record anyway, to
    decide whether a month is watched, so the caller reuses what it already fetched instead of
    fetching every month a second time. Raises :class:`~ntsb_probable_cause.errors.ApiError`
    on any page failure -- ``first_run_window`` does not catch it, and neither does this
    function; the caller decides how a first-run walk failure is handled.
    """
    records: list[dict[str, object]] = []
    for page in api.cases_by_date_range(month.start, month.end):
        records.extend(page.records)
    kept[month.label] = records
    return records


def _feed_rows(raw_rows: Iterable[Mapping[str, object]]) -> tuple[list[FeedRow], int]:
    """Aviation-only :class:`~ntsb_probable_cause.store.FeedRow` rows from a raw feed response.

    Also returns a count of rows skipped for missing ``mkey`` or ``lastChangeDateTimeUtc``.
    Confirmed live shape (2026-09-22): ``mkey`` (int), ``mode`` (str), ``lastChangeDateTimeUtc``
    (str), ``stepNumber`` (int), ``stepId`` (str), ``caseClosed`` (bool). Every mode the feed
    reports is kept only if it says ``Aviation``; among those, a row missing ``mkey`` or
    ``lastChangeDateTimeUtc`` -- the two fields every downstream use depends on -- is dropped
    and counted, never guessed at.
    """
    rows: list[FeedRow] = []
    skipped = 0
    for row in raw_rows:
        if row.get("mode") != _AVIATION_MODE:
            continue
        mkey = row.get("mkey")
        last_change = row.get("lastChangeDateTimeUtc")
        if not isinstance(mkey, int) or not isinstance(last_change, str) or not last_change:
            skipped += 1
            continue
        step_number = row.get("stepNumber")
        step_id = row.get("stepId")
        rows.append(
            FeedRow(
                mkey=mkey,
                last_change_utc=last_change,
                step_number=step_number if isinstance(step_number, int) else None,
                step_id=step_id if isinstance(step_id, str) else None,
                case_closed=bool(row.get("caseClosed", False)),
            )
        )
    return rows, skipped


def run_night(  # noqa: PLR0912, PLR0915
    inputs: NightInputs, *, verbose: bool = False
) -> RunSummary:
    # PLR0915/PLR0912 (too many statements/branches): the six ordered steps below (spec §9.1)
    # are one atomic sequence with shared local state (`failures`, `changed_mkeys`, ...) --
    # splitting it into more helper functions would only move the same statements and branches
    # behind more parameter lists, not reduce them; the per-step helpers above already carry
    # the real per-step logic.
    """Run one nightly pass: begin the run, fetch and observe, poll dockets, finish, return.

    Order (spec §9.1): begin the run; compute the month window; fetch the months and observe
    every watchable or already-known case; mark cases that stopped appearing as "not returned";
    fetch and store the change feed; poll every watched docket; finish the run with a summary.

    ``verbose=True`` sets the ``ntsb_probable_cause.recorder`` logger to ``DEBUG`` -- the case
    and docket sides (``recorder/cases.py``, ``recorder/dockets.py``) already emit a ``debug``
    line per diff decision at that level; this function does not raise it back down afterwards,
    since a night is one process's one run.

    See :class:`~ntsb_probable_cause.store.RunSummary` for exactly what each summary field
    counts.
    """
    if verbose:
        logging.getLogger(_RECORDER_LOGGER).setLevel(logging.DEBUG)

    start = _utc(inputs.now())
    today = start.date()
    failures = 0
    changed_mkeys: set[int] = set()
    new_documents = 0
    suspected_renumbers = 0

    # -- 1. begin the run ----------------------------------------------------------------------
    step_start = start
    run_id = inputs.store.begin_run(
        started_at=start.isoformat(), commit_sha=inputs.commit_sha, dirty=inputs.dirty
    )
    _log_step("begin run", step_start, _utc(inputs.now()))

    # -- 2. the month window --------------------------------------------------------------------
    step_start = _utc(inputs.now())
    watched_before = _ongoing_by_month(inputs.store, today)
    computed_window = month_window(inputs.store, today=today)
    first_run = computed_window is None
    kept: dict[str, list[dict[str, object]]] = {}
    months: list[Month]
    if computed_window is None:

        def _keep(month: Month) -> list[dict[str, object]]:
            return _fetch_and_keep(inputs.api, kept, month)

        try:
            months = first_run_window(_keep, today=today, is_watched=is_watchable)
        except ApiError as error:
            # Controller resolution 2: the simplest rule for a failed first-run walk is one
            # failure, no case-side observations at all tonight, dockets still polled for
            # whatever the (possibly empty) store already holds.
            _log.warning("first run walk failed=%s", type(error).__name__)
            failures += 1
            months = []
    else:
        months = computed_window
    _log_step("window", step_start, _utc(inputs.now()))

    # -- 3. fetch the months and observe every watchable case -----------------------------------
    step_start = _utc(inputs.now())
    all_seen: set[int] = set()
    errored_months: set[str] = set()
    for month in months:
        if first_run:
            seen, month_failures, changed = _observe_records(
                inputs.store, kept[month.label], run_id=run_id, today=today
            )
        else:
            seen, month_failures, changed, errored = _observe_month_streaming(
                inputs.api, inputs.store, month, run_id=run_id, today=today
            )
            if errored:
                errored_months.add(month.label)
        failures += month_failures
        changed_mkeys |= changed
        all_seen |= seen
    _log_step("fetch months, observe", step_start, _utc(inputs.now()))

    # -- 4. mark vanished cases -------------------------------------------------------------
    step_start = _utc(inputs.now())
    fetched_months = {month.label for month in months}
    for month_label, mkeys in watched_before.items():
        if month_label not in fetched_months or month_label in errored_months:
            continue
        for mkey in mkeys - all_seen:
            mark_not_returned(inputs.store, mkey, run_id=run_id, today=today)
            changed_mkeys.add(mkey)
    _log_step("mark vanished", step_start, _utc(inputs.now()))

    # -- 5. the change feed -----------------------------------------------------------------
    step_start = _utc(inputs.now())
    try:
        raw_feed = inputs.api.cases_modified(today - timedelta(days=_FEED_LOOKBACK_DAYS), today)
    except ApiError as error:
        _log.warning("feed failed=%s", type(error).__name__)
        failures += 1
        raw_feed = ()
    feed_rows, feed_skipped = _feed_rows(raw_feed)
    if feed_skipped:
        _log.debug("feed rows skipped (missing mkey or lastChangeDateTimeUtc)=%d", feed_skipped)
    if feed_rows:
        inputs.store.add_feed_rows(feed_rows, run_id=run_id)
    _log_step("store feed", step_start, _utc(inputs.now()))

    # -- 6. poll every watched docket ---------------------------------------------------------
    step_start = _utc(inputs.now())
    watched = inputs.store.watched_mkeys(today=today.isoformat())
    for mkey in watched:
        try:
            outcome = observe_docket(inputs.store, inputs.docket, mkey, run_id=run_id)
        except ValueError as error:
            # Controller resolution 3: an mkey with no `cases` row is one failure, the loop
            # continues. `run_night` only ever calls `observe_docket` for mkeys just drawn from
            # `watched_mkeys`, so this branch cannot fire through this call site in practice --
            # kept anyway, since `observe_docket`'s own contract documents it can raise.
            _log.warning("docket mkey=%d failed=%s", mkey, type(error).__name__)
            failures += 1
            continue
        new_documents += outcome.new_documents
        suspected_renumbers += outcome.suspected_renumbers
        if outcome.failed is not None:
            failures += 1
        elif outcome.changed:
            changed_mkeys.add(mkey)
    _log_step("poll dockets", step_start, _utc(inputs.now()))

    # -- finish the run -------------------------------------------------------------------------
    finish = _utc(inputs.now())
    summary = RunSummary(
        cases_polled=len(watched),
        cases_changed=len(changed_mkeys),
        new_documents=new_documents,
        failures=failures,
        suspected_renumbers=suspected_renumbers,
        minutes=(finish - start).total_seconds() / 60,
    )
    inputs.store.finish_run(run_id, finished_at=finish.isoformat(), summary=summary)
    _log.info(
        "run done cases=%d changed=%d new_docs=%d failed=%d renumber_suspects=%d minutes=%.0f",
        summary.cases_polled,
        summary.cases_changed,
        summary.new_documents,
        summary.failures,
        summary.suspected_renumbers,
        summary.minutes,
    )
    return summary
