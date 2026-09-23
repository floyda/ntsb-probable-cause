"""The nightly pass: orchestration, summary, logging (spec S2.5 §9.1, Task 9).

:func:`run_night` ties together every earlier task in six ordered steps -- begin the run, work
out the month window, fetch the months and observe every watchable case, mark vanished cases,
store the change feed, poll every watched docket -- then finishes the run with a summary (see
:class:`~ntsb_probable_cause.store.RunSummary` for what each summary field means).

Failure isolation (spec §9.1). One case, one month or one docket poll failing never aborts the
night: an :class:`~ntsb_probable_cause.errors.ApiError` fetching a month or the change feed, or
a watched mkey the store has no ``cases`` row for at all, is logged and counted as one failure;
the run continues. Any other exception -- including one raised *inside*
:func:`~ntsb_probable_cause.recorder.dockets.observe_docket` for an mkey the store does know
about -- propagates (the run fails loudly, and the caller, ``apps/recorder`` Task 10, never
saves a store a run did not finish). Fix round 1, Important 1: the docket side used to catch
every ``ValueError`` from ``observe_docket``, which would have silently absorbed a
``pydantic.ValidationError`` or a ``UnicodeDecodeError`` (both subclass ``ValueError``) as if it
were the documented "unknown mkey" case -- the check is now made explicitly, before the call, so
only that one condition is ever swallowed.

Outage budget (final review, item 1). Spec §9.1 promises "if the API is down, dockets are still
polled; if the docket site is down, fields are still snapshotted" -- but neither promise bounds
how long a down site is allowed to eat into the night before the scheduler's own 90-minute
Fargate timeout kills the task outright, which on an S3 store discards the whole night (nothing
gets pushed). Two mechanisms, both driven by ``inputs.now()`` (never wall-clock time measured
some other way, so a test can drive them deterministically): a RUN DEADLINE
(:data:`RUN_DEADLINE_MINUTES` after the run's own start; no new month fetch or docket poll
starts after it, and each skipped item is one failure) and a per-side CIRCUIT BREAKER
(:data:`CONSECUTIVE_FAILURES_TO_TRIP` consecutive fetch failures on the case side or the docket
side stops that side for the rest of the night; a single success resets the count). A month or
docket poll skipped by either mechanism is never treated as fetched cleanly: the case side's
``run_months`` bookkeeping (below) and "mark vanished" step both already only ever act on a
month that finished cleanly, so a skip simply leaves that month, and every watched case in it,
untouched -- exactly like an ``ApiError`` does. The deadline and breaker are NOT applied inside
:func:`~ntsb_probable_cause.recorder.window.first_run_window`'s own walk-back loop (see
:func:`_case_side`'s docstring for why).

Pre-deploy fix round (2026-09-23), four corrections found before the original numbers could
survive a real hung API: (A1) the CHANGE FEED was completely ungated -- it hit the same API
host the case side does, so a hung API could exhaust the deadline on the case side and then the
feed call would add its own full retry worst case on top, past the scheduler's limit; it is now
skipped, and counted, whenever the deadline has already passed or the case side's own breaker
has already tripped. (A2) :data:`RUN_DEADLINE_MINUTES` was 75 against a wrong "~2.5 minutes"
estimate of one request's own worst case; the real figure -- 5 retried attempts, each up to the
client's own 120-second timeout, plus backoff, plus rate-limit gaps -- is about 10.7 minutes for
the API and 10.5 for the docket client, so the constant is now 65 (see its own comment for the
full arithmetic). (A3) the deadline used to be checked only once per MONTH, so a single hung,
multi-page month could still run every remaining page of itself past the deadline before the
next check; :func:`_observe_month_streaming` now checks it before every PAGE too. (A4) the
docket circuit breaker used to count every kind of ``DocketOutcome.failed`` poll, including
fast PARSE failures (``no-info-block``, ``count-mismatch``, and the like) that mean the site
answered and only its page content was unusual -- a real layout change could then trip the
breaker after ten pages and stop storing the raw pages spec §6.4 needs precisely to diagnose
that change. It now counts only reasons that mean the site itself did not answer
(:func:`_is_docket_outage_reason`).

New cases' absent side (final review, item 2; Andy's decision 2026-09-23: "Add it"). Every month
:func:`_case_side` fetches cleanly AND fully (pre-deploy fix round, item B: every record it
returned was also successfully observed) is recorded, via :meth:`~ntsb_probable_cause.store.
Store.add_run_month`, in a new ``run_months`` table. A case observed for the first time ever can
then be told whether an EARLIER run already fetched its event month that way and did not find
it -- :meth:`~ntsb_probable_cause.store.Store.last_clean_fetch` answers that -- and if so, that
earlier run becomes the case's first-sight ``absent_run``, a TRUE arrival, rather than the case
simply reading as "present when watching began" (the only possibility before this run of fixes,
since a brand-new case's ``absent_run`` was always ``None``). In plain terms: a case first seen
after the recorder's first night has an absent side if the latest earlier night whose fetch of
its event month was clean and fully observed found it absent.

Seen-but-unstored records (pre-deploy fix round, item B). The rule above has a gap on its own:
the recorder also sees records it does NOT store -- returned by the API but not watchable and
unknown (a Completed or non-Part-91 case never watched), or a watchable record whose
``observe_case`` call itself failed. If such an mkey later becomes storable (the case reopens,
or the failure stops happening), it looks exactly like a genuinely new case, and would get
``new_case_absent_run`` as if it were -- a false arrival date, possibly years after the real
event. A new ``seen_unstored`` table (migration 3, edited in place rather than added as
migration 4, since it had not yet been applied to any real store when this round landed) records
every such mkey the first time it happens; :meth:`~ntsb_probable_cause.store.Store.
is_seen_unstored` overrides ``new_case_absent_run`` to ``None`` (first-sight) for any mkey found
there, regardless of what ``last_clean_fetch`` would otherwise have said.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
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
# and spec §5.3 -- wide enough to survive a missed or short run without a gap. Unlike every
# other table this module writes to, `change_feed` rows are a plain INSERT every night, not an
# upsert keyed by (mkey, run_id) -- see the module-level note by `_feed_rows` for why that is
# deliberate (fix round 1, Minor 1).
_FEED_LOOKBACK_DAYS = 2

# Final review item 1, corrected by the pre-deploy fix round (A2): the run deadline. The
# scheduler's own hard stop is 90 minutes (docs/runbooks/recorder-deploy.md's Fargate task
# timeout, docs/runbooks/recorder-bridge.md for the Mac bridge's own launchd timeout); this
# trips well before that so the run still finishes CLEANLY -- writes its summary, closes the
# store -- rather than being killed mid-write, which on an S3 store discards the whole night
# (nothing gets pushed).
#
# ONE request's own worst case, fully retried (`data/api.py`'s `NtsbClient`, `docket/
# client.py`'s `DocketClient`; both default to 5 attempts, a 120s httpx timeout per attempt,
# and exponential backoff starting at 2s): 5 attempts x up to 120s each = 600s, plus backoff
# between the first four (2 + 4 + 8 + 16 = 30s), plus the polite rate-limit gap before each of
# the 5 attempts once the client has made any earlier request (about 2s x 5 = 10s) -- 600 + 30
# + 10 = 640s = 10.7 minutes for the API; the docket client's own gap/backoff arithmetic is
# very slightly smaller (its gap sleep is net of any backoff already slept), about 10.5
# minutes. The corrected constant below (65, not the original 75) still leaves this fully
# inside the scheduler's limit: 65 minutes of run budget, plus one more request's worst case
# already in flight when the deadline is checked (about 10.7 minutes, the larger of the two),
# plus the store push and task startup/shutdown overhead the runbook budgets at roughly 10
# minutes, is 65 + 10.7 + 10 = 85.7 minutes -- under the scheduler's 90-minute hard stop, with
# a few minutes to spare, whichever single step happens to be in flight when the deadline
# trips.
RUN_DEADLINE_MINUTES = 65

# Final review item 1, corrected by the pre-deploy fix round (A2, A4): the per-side circuit
# breaker. After this many CONSECUTIVE genuine fetch-outage failures on one side (case-side
# months, or docket polls -- never a fast, non-retried status or a parse failure; see
# `_is_docket_outage_reason`), that side stops calling the network for the rest of the night.
#
# This mechanism and the run deadline above catch two DIFFERENT failure shapes, not the same
# one at different speeds. A site that HANGS (every attempt eats the full ~10.7/10.5-minute
# worst case above) trips the DEADLINE first: only about six such failures (6 x 10.7 =~ 64
# minutes) are needed to reach it, well under this constant's 10. A site that answers FAST but
# WRONG -- a persistent 5xx that fails every retry quickly, or a transport error with no real
# timeout involved -- costs only backoff-and-gap time per attempt (tens of seconds, not
# minutes), and could otherwise run through the ENTIRE remaining budget one fast failure at a
# time without ever tripping the deadline; this breaker is what actually stops that case. A
# single success on a side resets its count to zero -- the breaker answers "is this side
# rejecting requests right now", not "has this side ever had a bad night".
CONSECUTIVE_FAILURES_TO_TRIP = 10

_SKIPPED_DEADLINE = "skipped: deadline"
_SKIPPED_OUTAGE = "skipped: outage"


class NightInputs(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """Everything one nightly pass needs, injected so a test touches neither network nor clock.

    ``now`` is called repeatedly through the run (once per step boundary for the per-step
    duration log lines, and once per month/docket-poll attempt for the outage budget) and must
    always return an aware datetime (see :func:`_utc`).
    """

    api: NtsbClient
    docket: DocketClient
    store: Store
    now: Callable[[], datetime]
    commit_sha: str
    dirty: bool


@dataclass
class _Tally:
    """The counts every step of the night adds to, shared by reference (fix round 1, Minor 2).

    Each `_*_side` helper below only ever adds to these fields; `run_night` reads them once, at
    the very end, to build the `RunSummary`. `cases_polled` is not here: it is simply
    `len(watched)`, the list `_docket_side` itself returns.
    """

    failures: int = 0
    changed_mkeys: set[int] = field(default_factory=set)
    new_documents: int = 0
    suspected_renumbers: int = 0


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

    Caveat (fix round 1, Minor 5): this groups by the case's *currently stored* event month. If
    an investigator later corrects a case's event date to a month before tonight's window, the
    case's own row still shows the old, still-watched month here -- but the API now reports it
    under the new month instead, so it is absent from what this month's fetch returns and gets
    a "not returned" status event even though nothing about the case actually vanished. A
    status event is the only trace this leaves (`mark_not_returned` never deletes the case's
    field history), and the 8-week comparison report (`scripts/recorder_report.py`, Task 11)
    can count such cases as a false "not returned" if it does not cross-check the event date. An
    event date corrected to a month still *inside* the window is not affected: `all_seen` is a
    single set across every month fetched this run, so the case is still found there regardless
    of which of this run's months it turned up under.
    """
    grouped: dict[str, set[int]] = {}
    for mkey in store.watched_mkeys(today=today.isoformat()):
        case = store.get_case(mkey)
        if case is not None and case.status == ONGOING_STATUS:
            grouped.setdefault(case.event_date[:7], set()).add(mkey)
    return grouped


def _observe_records(
    store: Store,
    records: Iterable[Mapping[str, object]],
    *,
    run_id: int,
    today: date,
    new_case_absent_run: int | None,
) -> tuple[set[int], int, set[int]]:
    """Filter and observe one batch of raw records (spec §9.1's per-record rule).

    ``if is_watchable(raw) or store.get_case(mkey) is not None: observe_case(...)`` -- a record
    that is neither watchable nor already known to the store is skipped entirely, never even
    split. Returns ``(seen, failures, changed)``: every mkey actually observed (whatever the
    outcome), how many of those observations failed, and which of them wrote something.

    ``new_case_absent_run`` (final review item 2) is passed straight through to every
    :func:`~ntsb_probable_cause.recorder.cases.observe_case` call: every record in one batch
    shares the same event month (a page of ``cases_by_date_range(month.start, month.end)``, or
    one first-run-walk month's kept records), so the caller computes it once, via
    ``store.last_clean_fetch``, rather than this function computing it per record.
    ``observe_case`` itself decides whether that value actually applies, per mkey (see its own
    docstring's ``is_seen_unstored`` paragraph).

    Pre-deploy fix round, item B: a record the API returned but this function does NOT store --
    neither watchable nor already known (skipped before ever being split), or a watchable
    record whose ``observe_case`` call itself failed -- is recorded in
    :meth:`~ntsb_probable_cause.store.Store.add_seen_unstored`, so a later night that DOES
    store it (the case reopens, or the failure stops happening) never mistakes it for a
    genuinely new case and gives it a false absent side.
    """
    seen: set[int] = set()
    failures = 0
    changed: set[int] = set()
    for raw in records:
        mkey_value = raw.get("mKey")
        known = isinstance(mkey_value, int) and store.get_case(mkey_value) is not None
        if not (is_watchable(raw) or known):
            if isinstance(mkey_value, int):
                store.add_seen_unstored(mkey_value, first_run=run_id)
            continue
        outcome = observe_case(
            store,
            raw,
            run_id=run_id,
            today=today,
            new_case_absent_run=new_case_absent_run,
        )
        if isinstance(mkey_value, int):
            seen.add(mkey_value)
        if outcome.failed is not None:
            failures += 1
            if isinstance(mkey_value, int):
                store.add_seen_unstored(mkey_value, first_run=run_id)
        elif outcome.changed:
            changed.add(outcome.mkey)
    return seen, failures, changed


def _observe_month_streaming(  # noqa: PLR0913 -- one parameter per fetch/observe input, plus
    # `new_case_absent_run` (final review item 2) and the outage-budget clock/deadline (item
    # A3), which every page of this one month shares.
    api: NtsbClient,
    store: Store,
    month: Month,
    *,
    run_id: int,
    today: date,
    new_case_absent_run: int | None,
    now: Callable[[], datetime],
    deadline: datetime,
) -> tuple[set[int], int, set[int], bool]:
    """Fetch one month page by page, observing as each page arrives.

    Controller resolution 1: a failed month is never evidence of absence. Observing page by
    page, rather than collecting the whole month first, means that if the API fails on page 2
    of 3, page 1's records have already been observed and committed (each :func:`observe_case`
    call is its own transaction) -- they stand. The failure itself is counted once, here, and
    the caller is told ``errored=True`` so it skips "not returned" marking for this month's
    watched cases entirely, rather than reading an incompletely-fetched month as absence.

    Pre-deploy fix round, item A3: the run deadline is also checked HERE, before each PAGE
    (not only once per month, in ``_case_side``, before the whole month starts) -- a hung,
    multi-page month must stop requesting the next page as soon as the deadline is reached,
    not run every remaining page of that one month first. ``api.cases_by_date_range`` is a
    generator; the loop below drives it with an explicit ``next()`` so the deadline can be
    checked before each page is requested, not only after one arrives. A month cut short this
    way is treated exactly like an ``ApiError`` mid-month: whatever pages already arrived stand
    (each already committed), the month itself counts as ``errored=True`` -- no ``run_months``
    row, no "not returned" marking for the rest of it.
    """
    seen: set[int] = set()
    failures = 0
    changed: set[int] = set()
    pages = api.cases_by_date_range(month.start, month.end)
    try:
        while True:
            if _utc(now()) >= deadline:
                _log.warning(
                    "case side: run deadline reached mid-month, month=%s stopped", month.label
                )
                return seen, failures + 1, changed, True
            try:
                page = next(pages)
            except StopIteration:
                break
            page_seen, page_failures, page_changed = _observe_records(
                store,
                page.records,
                run_id=run_id,
                today=today,
                new_case_absent_run=new_case_absent_run,
            )
            seen |= page_seen
            failures += page_failures
            changed |= page_changed
    except ApiError as error:
        _log.warning("case month=%s failed=ApiError status=%s", month.label, error.status)
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
    and counted, never guessed at. ``caseClosed`` is compared with ``is True`` rather than
    coerced with ``bool(...)``, so anything other than the literal JSON ``true`` -- a missing
    field, ``null``, or some other truthy-but-wrong value a future API change might send -- reads
    as ``False`` explicitly rather than by accident of Python truthiness (fix round 1, Minor 6).

    ``change_feed`` rows are stored per run, not deduplicated across nights, because the 2-day
    lookback window overlaps between consecutive nights on purpose (a missed or short run still
    leaves no gap) and the 8-week comparison report (Task 11) reads them per run to compare
    against what the case/docket sides actually observed that same night -- deduplicating here
    would throw away exactly the rows that comparison needs. This is a deliberate exception to
    CLAUDE.md rule 7's general idempotence expectation, not an oversight (fix round 1, Minor 1).
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
                case_closed=row.get("caseClosed") is True,
            )
        )
    return rows, skipped


def _case_side(
    inputs: NightInputs,
    *,
    run_id: int,
    today: date,
    tally: _Tally,
    deadline: datetime,
) -> tuple[list[Month], set[int], set[str], bool]:
    """Steps 2-3: the month window, then fetch each month and observe every watchable record.

    Returns ``(months fetched this run, every mkey observed, the months an ApiError -- or the
    outage budget -- cut short, whether the case-side circuit breaker tripped)``.
    :func:`_mark_vanished` needs the first three; ``run_night`` needs the fourth to gate the
    change feed (pre-deploy fix round, item A1 -- see :func:`_feed_side`). ``computed_window is
    None`` (rather than a separately tracked flag) is the one and only test for "this is a
    first run" -- fix round 1, Minor 2 dropped the redundant ``first_run`` boolean the two used
    to track in parallel.

    The run deadline and circuit breaker (final review item 1) apply only to the STEADY-STATE
    branch below (``computed_window`` already known), one check per month, before that month's
    own fetch begins. They are deliberately NOT applied inside
    :func:`~ntsb_probable_cause.recorder.window.first_run_window`'s own walk-back loop: that
    function has no clock parameter, walks every month back to the earliest watched case (or
    twelve empty months) as one atomic operation, and -- being a first run -- there is no
    ``cases`` history yet for a mid-walk cut to protect; a first-run walk that runs long is
    covered by the run deadline the OUTER call already sits inside (:func:`run_night` checks
    ``inputs.now()`` again immediately after this function returns, via its own step-duration
    log line, so a first run that overruns is visible in the log even though it is not cut off
    mid-walk). Every month the walk DOES return is, by construction, cleanly fetched (the walk
    itself raises and aborts on the first ``ApiError``, never returning a partial month) -- see
    the loop below.

    Each cleanly fetched month's ``run_months`` row (final review item 2) is written here, via
    :meth:`~ntsb_probable_cause.store.Store.add_run_month`, immediately after that month is
    confirmed clean -- a month skipped by the deadline or breaker, or cut short by an
    ``ApiError``, gets no row.
    """
    computed_window = month_window(inputs.store, today=today)
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
            _log.warning("first run walk failed=ApiError status=%s", error.status)
            tally.failures += 1
            months = []
    else:
        months = computed_window

    all_seen: set[int] = set()
    errored_months: set[str] = set()
    consecutive_failures = 0
    breaker_tripped = False
    for month in months:
        if computed_window is None:
            new_case_absent_run = inputs.store.last_clean_fetch(month.label, before_run=run_id)
            seen, month_failures, changed = _observe_records(
                inputs.store,
                kept[month.label],
                run_id=run_id,
                today=today,
                new_case_absent_run=new_case_absent_run,
            )
            errored = False
        else:
            if _utc(inputs.now()) >= deadline:
                _log.warning("case side: run deadline reached, month=%s skipped", month.label)
                tally.failures += 1
                errored_months.add(month.label)
                continue
            if breaker_tripped:
                tally.failures += 1
                errored_months.add(month.label)
                continue
            new_case_absent_run = inputs.store.last_clean_fetch(month.label, before_run=run_id)
            seen, month_failures, changed, errored = _observe_month_streaming(
                inputs.api,
                inputs.store,
                month,
                run_id=run_id,
                today=today,
                new_case_absent_run=new_case_absent_run,
                now=inputs.now,
                deadline=deadline,
            )
            if errored:
                errored_months.add(month.label)
                consecutive_failures += 1
                if consecutive_failures >= CONSECUTIVE_FAILURES_TO_TRIP and not breaker_tripped:
                    breaker_tripped = True
                    _log.warning(
                        "case side: circuit breaker tripped after %d consecutive month failures",
                        consecutive_failures,
                    )
            else:
                consecutive_failures = 0
        tally.failures += month_failures
        tally.changed_mkeys |= changed
        all_seen |= seen
        # Pre-deploy fix round, item B: a month is "clean" only if it also fetched WITHOUT
        # ANY observation failure -- `month_failures > 0` means at least one record the API
        # returned was not actually stored (see `_observe_records`'s `add_seen_unstored`
        # calls), so this month was not fully observed even though every page arrived.
        if not errored and month_failures == 0:
            inputs.store.add_run_month(run_id, month.label)
    return months, all_seen, errored_months, breaker_tripped


def _mark_vanished(  # noqa: PLR0913 -- one parameter per input `_case_side` produced, plus the
    # tally every `_*_side` helper shares (fix round 1, Minor 2).
    store: Store,
    *,
    run_id: int,
    today: date,
    months: list[Month],
    all_seen: set[int],
    errored_months: set[str],
    watched_before: dict[str, set[int]],
    tally: _Tally,
) -> None:
    """Step 4: mark vanished cases as "not returned".

    Every previously-``Ongoing`` watched case not seen in a completely, cleanly fetched month
    is marked. A month never fetched at all tonight, cut short by an ``ApiError``, or skipped by
    the outage budget (all three land in ``errored_months`` -- final review item 1), contributes
    no such marks.
    """
    fetched_months = {month.label for month in months}
    for month_label, mkeys in watched_before.items():
        if month_label not in fetched_months or month_label in errored_months:
            continue
        for mkey in mkeys - all_seen:
            mark_not_returned(store, mkey, run_id=run_id, today=today)
            tally.changed_mkeys.add(mkey)


def _feed_side(  # noqa: PLR0913 -- the outage budget (pre-deploy fix round, item A1) needs
    # the clock, the deadline and the case-side breaker's own result alongside every parameter
    # the feed step already took.
    api: NtsbClient,
    store: Store,
    *,
    run_id: int,
    today: date,
    tally: _Tally,
    now: Callable[[], datetime],
    deadline: datetime,
    case_side_breaker_tripped: bool,
) -> None:
    """Step 5: fetch the change feed for the last two days and store its aviation-only rows.

    Pre-deploy fix round, item A1: gated by the SAME outage budget the case and docket sides
    already are, and for the same reason -- ``cases_modified`` (``data/api.py``) hits the same
    API host ``cases_by_date_range`` does, with the same retry/backoff worst case
    (``RUN_DEADLINE_MINUTES``'s own comment), and calling it UNGATED after the case side has
    already burned most of the run deadline (or given up on that host entirely, via its own
    circuit breaker) is exactly what could push a night past the scheduler's own limit. Skipped
    -- one failure, one log line, ``cases_modified`` never called -- if the deadline has
    already passed, OR if the case-side breaker already tripped (the same host is down; no
    point trying it a sixth way tonight). The DOCKET side's own breaker does not gate this step:
    a docket outage says nothing about whether the API host answers.
    """
    if case_side_breaker_tripped:
        _log.warning("feed skipped: case-side circuit breaker already tripped (same API host)")
        tally.failures += 1
        return
    if _utc(now()) >= deadline:
        _log.warning("feed skipped: run deadline reached")
        tally.failures += 1
        return
    try:
        raw_feed = api.cases_modified(today - timedelta(days=_FEED_LOOKBACK_DAYS), today)
    except ApiError as error:
        _log.warning("feed failed=ApiError status=%s", error.status)
        tally.failures += 1
        raw_feed = ()
    feed_rows, feed_skipped = _feed_rows(raw_feed)
    if feed_skipped:
        _log.debug("feed rows skipped (missing mkey or lastChangeDateTimeUtc)=%d", feed_skipped)
    if feed_rows:
        store.add_feed_rows(feed_rows, run_id=run_id)


def _is_docket_outage_reason(reason: str) -> bool:
    """Final review item A4: only a reason meaning the site itself is unreachable counts.

    That is exactly ``docket.client.outcome_for_error``'s two "exhausted every retry" shapes: a
    persistent HTTP status that survived every attempt (its ``"...-after-retries"`` suffix) or
    a transport failure that did too (``"fetch-failed: ..."``). Everything else leaves the
    counter untouched, exactly as a real success would (never trips the breaker, and resets any
    in-progress streak): a PARSE failure (``no-info-block``, ``count-mismatch``,
    ``entry-without-id``, ``duplicate-id``) means a page arrived and was read -- on a night the
    site changes its own page layout, every poll can fail this way, fast, and every one of
    those raw pages must still be stored (spec §6.4), which tripping the breaker would stop
    after only ten; and a FAST, non-retried status (``outcome_for_error``'s plain
    ``"http-<status>"``, e.g. a 404 for one case that genuinely has no docket) means the site
    answered too, just with a status this client does not retry -- also not evidence the site
    itself is down.
    """
    return reason.endswith("-after-retries") or reason.startswith("fetch-failed:")


def _skip_docket_poll(store: Store, mkey: int, *, run_id: int, reason: str) -> None:
    """Write a ``failed`` ``docket_polls`` row for a poll the outage budget never attempted.

    Final review item 1: "so the log and the store agree" -- a poll the deadline or breaker
    skipped gets exactly the row a poll that failed over the network would have gotten (outcome
    ``failed``, no page, no declared item count), just with a ``reason`` naming which budget
    mechanism skipped it, rather than leaving a gap in ``docket_polls`` for that mkey tonight.
    """
    store.add_docket_poll(
        mkey,
        run_id=run_id,
        outcome="failed",
        reason=reason,
        declared_items=None,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )


def _docket_side(  # noqa: PLR0913 -- the outage budget (final review item 1) needs the clock
    # and the deadline alongside every parameter the docket side already took.
    store: Store,
    docket: DocketClient,
    *,
    run_id: int,
    today: date,
    tally: _Tally,
    now: Callable[[], datetime],
    deadline: datetime,
) -> list[int]:
    """Step 6: poll every watched case's docket.

    Returns the watched mkey list (``cases_polled`` is simply its length).

    Fix round 1, Important 1: a watched mkey the store has no ``cases`` row for -- which
    ``observe_docket`` itself would raise ``ValueError`` for -- is checked *before* the call and
    counted as one failure, rather than by catching the exception. `run_night` only ever calls
    this for mkeys freshly drawn from ``watched_mkeys``, which reads the same ``cases`` table
    ``get_case`` does, so this branch should be unreachable through this call site in real use;
    it is kept because ``observe_docket``'s own contract documents the case. Any OTHER
    exception -- including a ``ValueError`` raised for a genuinely known mkey, which a caught-
    and-swallowed ``except ValueError`` would previously have absorbed as if it were this same
    "unknown mkey" case -- now propagates instead of being silently counted as one quiet
    failure a night.

    Final review item 1: the deadline is checked once per mkey, before that mkey's own poll
    (never mid-poll -- a poll already in flight always finishes). Once tripped it stays tripped
    for the rest of this call: every remaining mkey gets a skipped ``docket_polls`` row
    (:func:`_skip_docket_poll`, reason ``"skipped: deadline"``) instead of a real fetch. The
    circuit breaker counts consecutive ``DocketOutcome.failed`` polls whose reason means a real
    fetch outage (:func:`_is_docket_outage_reason`, pre-deploy fix round A4 -- never a parse
    failure, a fast non-retried status, or the unknown-mkey check above, which is a store bug,
    not a fetch failure at all) and, once tripped, likewise skips every remaining mkey (reason
    ``"skipped: outage"``) -- a single non-outage poll (a real success, or any of those
    non-outage failure shapes) resets the count to zero.
    """
    watched = store.watched_mkeys(today=today.isoformat())
    consecutive_failures = 0
    breaker_tripped = False
    deadline_tripped = False
    for mkey in watched:
        if not deadline_tripped and _utc(now()) >= deadline:
            deadline_tripped = True
            _log.warning("docket side: run deadline reached, remaining polls skipped")
        if deadline_tripped:
            _skip_docket_poll(store, mkey, run_id=run_id, reason=_SKIPPED_DEADLINE)
            tally.failures += 1
            continue
        if breaker_tripped:
            _skip_docket_poll(store, mkey, run_id=run_id, reason=_SKIPPED_OUTAGE)
            tally.failures += 1
            continue
        if store.get_case(mkey) is None:
            _log.warning("docket mkey=%d failed=unknown-mkey", mkey)
            tally.failures += 1
            continue
        outcome = observe_docket(store, docket, mkey, run_id=run_id)
        tally.new_documents += outcome.new_documents
        tally.suspected_renumbers += outcome.suspected_renumbers
        if outcome.failed is not None:
            tally.failures += 1
            if _is_docket_outage_reason(outcome.failed):
                consecutive_failures += 1
                if consecutive_failures >= CONSECUTIVE_FAILURES_TO_TRIP and not breaker_tripped:
                    breaker_tripped = True
                    _log.warning(
                        "docket side: circuit breaker tripped after %d consecutive failures",
                        consecutive_failures,
                    )
            else:
                consecutive_failures = 0
        else:
            consecutive_failures = 0
            if outcome.changed:
                tally.changed_mkeys.add(mkey)
    return watched


def run_night(inputs: NightInputs, *, verbose: bool = False) -> RunSummary:
    """Run one nightly pass: begin the run, fetch and observe, poll dockets, finish, return.

    Order (spec §9.1): begin the run; compute the month window; fetch the months and observe
    every watchable or already-known case; mark cases that stopped appearing as "not returned";
    fetch and store the change feed; poll every watched docket; finish the run with a summary.
    Each step's real work lives in one of the ``_*_side``/``_mark_vanished`` helpers above,
    which share progress through one mutable :class:`_Tally` rather than each returning a
    growing tuple of counters (fix round 1, Minor 2).

    ``verbose=True`` sets the ``ntsb_probable_cause.recorder`` logger to ``DEBUG``. The case and
    docket sides (``recorder/cases.py``, ``recorder/dockets.py``) then also emit a ``debug``
    line per diff decision -- which evidence ROLE names differed (never a value) on the case
    side, and which document IDs appeared, were revised, or disappeared (never a title) on the
    docket side (final review item 3; spec §9.1: "which fields differed, which document numbers
    were compared"). This function does not raise the level back down afterwards, since a
    night is one process's one run.

    The run deadline and per-side circuit breaker (final review item 1; see the module
    docstring) bound how long a down API or docket site can eat into the night before the
    scheduler's own timeout would otherwise kill the task outright.

    See :class:`~ntsb_probable_cause.store.RunSummary` for exactly what each summary field
    counts.
    """
    if verbose:
        logging.getLogger(_RECORDER_LOGGER).setLevel(logging.DEBUG)

    start = _utc(inputs.now())
    today = start.date()
    deadline = start + timedelta(minutes=RUN_DEADLINE_MINUTES)
    tally = _Tally()

    # -- 1. begin the run ----------------------------------------------------------------------
    step_start = start
    run_id = inputs.store.begin_run(
        started_at=start.isoformat(), commit_sha=inputs.commit_sha, dirty=inputs.dirty
    )
    _log_step("begin run", step_start, _utc(inputs.now()))

    # -- 2-3. the month window, then fetch and observe ---------------------------------------
    step_start = _utc(inputs.now())
    watched_before = _ongoing_by_month(inputs.store, today)
    months, all_seen, errored_months, case_side_breaker_tripped = _case_side(
        inputs, run_id=run_id, today=today, tally=tally, deadline=deadline
    )
    _log_step("window, fetch months, observe", step_start, _utc(inputs.now()))

    # -- 4. mark vanished cases -------------------------------------------------------------
    step_start = _utc(inputs.now())
    _mark_vanished(
        inputs.store,
        run_id=run_id,
        today=today,
        months=months,
        all_seen=all_seen,
        errored_months=errored_months,
        watched_before=watched_before,
        tally=tally,
    )
    _log_step("mark vanished", step_start, _utc(inputs.now()))

    # -- 5. the change feed -----------------------------------------------------------------
    step_start = _utc(inputs.now())
    _feed_side(
        inputs.api,
        inputs.store,
        run_id=run_id,
        today=today,
        tally=tally,
        now=inputs.now,
        deadline=deadline,
        case_side_breaker_tripped=case_side_breaker_tripped,
    )
    _log_step("store feed", step_start, _utc(inputs.now()))

    # -- 6. poll every watched docket ---------------------------------------------------------
    step_start = _utc(inputs.now())
    watched = _docket_side(
        inputs.store,
        inputs.docket,
        run_id=run_id,
        today=today,
        tally=tally,
        now=inputs.now,
        deadline=deadline,
    )
    _log_step("poll dockets", step_start, _utc(inputs.now()))

    # -- finish the run -------------------------------------------------------------------------
    finish = _utc(inputs.now())
    summary = RunSummary(
        cases_polled=len(watched),
        cases_changed=len(tally.changed_mkeys),
        new_documents=tally.new_documents,
        failures=tally.failures,
        suspected_renumbers=tally.suspected_renumbers,
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
