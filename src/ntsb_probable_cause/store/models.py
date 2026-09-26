"""Frozen row and summary models for the store package (spec S2.5, Task 4)."""

from enum import StrEnum

from pydantic import BaseModel


class CaseRow(BaseModel, frozen=True):
    """One row of the ``cases`` table: a watched case's latest known state."""

    mkey: int
    ntsb_number: str
    event_date: str
    regulation: str | None
    status: str
    first_seen_run: int
    last_seen_run: int
    last_case_run: int | None
    last_docket_run: int | None
    watch_until: str | None
    watched: bool = True


class DocumentRow(BaseModel, frozen=True):
    """One row of the ``documents`` table: a docket document, present or gone."""

    mkey: int
    doc_id: int
    href: str
    position: int
    title: str
    pages: int
    photos: int
    extension: str
    absent_run: int | None
    present_run: int
    last_present_run: int
    gone_absent_run: int | None
    gone_present_run: int | None


class FeedRow(BaseModel, frozen=True):
    """One row of the ``change_feed`` table: one entry from the API's change feed."""

    mkey: int
    last_change_utc: str
    step_number: int | None
    step_id: str | None
    case_closed: bool


class RunSummary(BaseModel, frozen=True):
    """The counts a finished run reports about itself, written by ``finish_run``.

    Definitions (spec S2.5 §9.1, Task 9 controller note 4; :func:`~ntsb_probable_cause.
    recorder.run.run_night` is what computes these):

    - ``cases_polled`` -- the number of docket polls attempted, i.e. the number of watched
      cases this night (``len(store.watched_mkeys(...))`` at the moment the docket step ran).
    - ``cases_changed`` -- the number of *distinct* mkeys for which either side (the case side
      or the docket side, including a "not returned" status event) wrote anything at all.
    - ``new_documents`` -- the sum of every docket poll's ``new_documents`` (documents that
      appeared, whether for the first time or on their return, this run).
    - ``suspected_renumbers`` -- the sum of every docket poll's ``suspected_renumbers``.
    - ``failures`` -- failed case observations, plus failed docket polls, plus failed months
      (an ``ApiError`` fetching one month's cases), plus a failed change-feed call, plus every
      unknown-mkey ``ValueError`` the docket side raised. Each is counted once, however many
      documents or fields that one failure would otherwise have touched.
    - ``minutes`` -- ``(finished_at - started_at)`` in minutes, from the run's own injected
      clock, not wall-clock time measured some other way.
    """

    cases_polled: int
    cases_changed: int
    new_documents: int
    failures: int
    suspected_renumbers: int
    minutes: float


class RunSummaryRow(BaseModel, frozen=True):
    """One row of the ``runs`` table, as read back by ``run_summaries`` (Task 11 adds more)."""

    run_id: int
    started_at: str
    finished_at: str | None
    commit_sha: str
    dirty: bool
    cases_polled: int | None
    cases_changed: int | None
    new_documents: int | None
    failures: int | None
    suspected_renumbers: int | None
    minutes: float | None


class ArrivalClassification(StrEnum):
    """Where one arrival falls relative to its case's closure (Task 11, IMPORTANT I5).

    Only ``BEFORE_CLOSURE`` arrivals form the distribution spec §10.2 says replaces
    ``scoring.samples.MASK_LIFTS_AT_DAY``: an arrival recorded on the same run as, or after,
    the status event that closed the case is not something a live agent watching an *open*
    case would ever see arrive, so it cannot inform what the mask should assume about an open
    case's evidence.

    ``EXCLUDED_UNWATCHED`` is decided from ``regulation_events`` history alone, never from the
    case's *current* ``cases.watched`` flag (that flag is cleared when a closed case's 30-day
    tail expires, which used to silently move every already-closed case's genuine
    before-closure arrivals into this bucket a month later -- fix round 2 replaced that rule).
    Precisely, at the arrival's own run:

    - the LATEST regulation change recorded at or before that run decides;
    - if the case has regulation changes but all of them are later, the regulation recorded
      BEFORE the first of those changes decides (nothing had changed it yet);
    - if the case has no recorded regulation changes at all, its *current* ``cases.regulation``
      decides, as a stated fallback;
    - the case is excluded only when that decided regulation is neither "not yet recorded" nor
      Part 91 (``091``, decision 0067).

    Closing, and the end of the 30-day watch after closing, never exclude a case on their own
    -- those are exactly what ``SAME_RUN_AS_CLOSURE``/``AFTER_CLOSURE`` already state.
    """

    BEFORE_CLOSURE = "before_closure"
    SAME_RUN_AS_CLOSURE = "same_run_as_closure"
    AFTER_CLOSURE = "after_closure"
    EXCLUDED_UNWATCHED = "excluded_unwatched"


class ArrivalRow(BaseModel, frozen=True):
    """One true arrival (a preliminary narrative, Task 11 IMPORTANT 6): days plus classification."""

    days: int
    absent_days: int
    classification: ArrivalClassification


class FieldArrivalRow(BaseModel, frozen=True):
    """One true evidence-field arrival: its role, days, and classification."""

    role: str
    days: int
    absent_days: int
    classification: ArrivalClassification


class DocketArrivalRow(BaseModel, frozen=True):
    """One true docket arrival: days, document count at that poll, and classification."""

    days: int
    absent_days: int
    document_count: int
    classification: ArrivalClassification


class TailArrivals(BaseModel, frozen=True):
    """Closure-tail document appearances (spec §7 rule 5; Task 11 fix round 1, IMPORTANT 3).

    ``same_run``/``after``/``total`` cover only *real* closures (a status event whose
    ``new_status`` is ``'Completed'`` or ``'N/A'``). ``not_returned_tail`` is the same measure
    for cases whose last departure from ``Ongoing`` was ``'not returned'`` instead -- reported
    separately because "not returned" is not an attested closure (the case may simply be a
    missed record, spec §7's own uncertainty), so mixing it into the real-closure counts would
    overstate how many genuine post-closure arrivals occur.
    """

    same_run: int
    after: int
    total: int
    not_returned_tail: int


class FeedComparisonResult(BaseModel, frozen=True):
    """The change-feed comparison (spec §5.3, §10.2; Task 11 fix round 1, CRITICAL 2).

    Reported at two granularities: per field-change row (``field_changes``/
    ``field_changes_reported``) and per case-night -- one ``(mkey, present_run)`` pair, which
    can hold several field changes at once (``case_nights``/``case_nights_reported``).
    ``unparsable_timestamps`` (fix round 2, MINOR 3) is a whole-table count of stored
    ``last_change_utc`` values that failed to parse at all, independent of ``window_days``.
    """

    field_changes: int
    field_changes_reported: int
    case_nights: int
    case_nights_reported: int
    unparsable_timestamps: int


class RegulationTransitions(BaseModel, frozen=True):
    """Regulation changes among watched cases (spec §4.1; Task 11 fix round 1, IMPORTANT 7).

    Every count is over ``regulation_events`` rows with ``was_watched = 1`` only -- a case
    already dropped from watching when its regulation changed is not part of "watched cases
    changed regulation". ``empty_to_091_days`` is, per such event, the days from the case's
    first-ever run (``cases.first_seen_run``) to the run that recorded the fill-in -- an
    upper bound on how long a case's regulation stayed unrecorded, not from the event date.
    """

    empty_to_091: int
    empty_to_091_days: tuple[int, ...]
    empty_to_other: int
    changed_value: int
    value_to_empty: int
