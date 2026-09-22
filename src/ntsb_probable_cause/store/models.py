"""Frozen row and summary models for the store package (spec S2.5, Task 4)."""

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
    """The counts a finished run reports about itself, written by ``finish_run``."""

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
