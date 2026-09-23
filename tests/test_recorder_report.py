"""Tests for the recorder report's store queries and its pure ``report()`` text (Task 11)."""

from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts.recorder_report import report

from ntsb_probable_cause.store import CaseRow, DocumentRow, FeedRow, RunSummary, Store

# Three fake nights, one day apart except the last (a gap, to prove day counts are computed
# from real dates, not run-id arithmetic). Run 2 is left unfinished throughout -- a "crashed"
# night (spec §9.1) whose rows are still real observations (rule 4) but which is excluded from
# the finished-run sums.
RUN1_STARTED = "2026-01-01T03:00:00+00:00"
RUN2_STARTED = "2026-01-02T03:00:00+00:00"
RUN3_STARTED = "2026-01-05T03:00:00+00:00"

MKEY1 = 1  # closes at run 2; a tail arrival lands at run 3.
MKEY2 = 2  # docket documents present at its very first poll ever (first-sight).
MKEY3 = 999888777  # dropped for its regulation while still Ongoing -- a distinctive mkey.
MKEY4 = 4  # "not returned" at run 1, reappears via a later status event.
MKEY5 = 5  # "not returned" at run 1, never reappears.
MKEY6 = 6  # "not returned" at run 1, reappears only via a bumped last_case_run.


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store(tmp_path / "r.sqlite") as opened:
        opened.migrate()
        yield opened


def _case(mkey: int, *, event_date: str, status: str, watched: bool = True) -> CaseRow:
    return CaseRow(
        mkey=mkey,
        ntsb_number=f"DCA26FDISTINCTIVE{mkey:03d}",
        event_date=event_date,
        regulation="091",
        status=status,
        first_seen_run=1,
        last_seen_run=1,
        last_case_run=1,
        last_docket_run=None,
        watch_until=None,
        watched=watched,
    )


def _populate(store: Store) -> None:
    """Build the three-night store every test in this file reads from."""
    run1 = store.begin_run(started_at=RUN1_STARTED, commit_sha="a" * 7, dirty=False)
    run2 = store.begin_run(started_at=RUN2_STARTED, commit_sha="b" * 7, dirty=False)
    run3 = store.begin_run(started_at=RUN3_STARTED, commit_sha="c" * 7, dirty=False)
    assert (run1, run2, run3) == (1, 2, 3)

    # -- cases --------------------------------------------------------------------------------
    store.upsert_case(_case(MKEY1, event_date="2025-12-20", status="Ongoing"))
    store.upsert_case(_case(MKEY2, event_date="2025-12-25", status="Ongoing"))
    store.upsert_case(_case(MKEY3, event_date="2025-12-01", status="Ongoing", watched=False))
    store.upsert_case(_case(MKEY4, event_date="2025-12-01", status="Ongoing"))
    store.upsert_case(_case(MKEY5, event_date="2025-12-01", status="Ongoing"))
    store.upsert_case(_case(MKEY6, event_date="2025-12-01", status="Ongoing"))

    # -- field_snapshots: first-sight rows at run 1 --------------------------------------------
    store.add_field_snapshot(
        MKEY1, role="engine_type", value_json='"REC"', absent_run=None, present_run=1, run_id=1
    )
    store.add_field_snapshot(
        MKEY1, role="injury_level", value_json='"None"', absent_run=None, present_run=1, run_id=1
    )
    store.add_field_snapshot(
        MKEY2,
        role="phase_of_flight",
        value_json='"Cruise"',
        absent_run=None,
        present_run=1,
        run_id=1,
    )

    # -- field_snapshots: true arrivals ---------------------------------------------------------
    # weather_condition (mkey1): absent at run 1, present at run 2 -- 13 days from 2025-12-20.
    store.add_field_snapshot(
        MKEY1,
        role="weather_condition",
        value_json='"VMC"',
        absent_run=1,
        present_run=2,
        run_id=2,
    )
    # pilot_total_hours (mkey2): absent at run 1, present at run 3 -- 11 days from 2025-12-25.
    store.add_field_snapshot(
        MKEY2,
        role="pilot_total_hours",
        value_json="120",
        absent_run=1,
        present_run=3,
        run_id=3,
    )
    # registration (mkey1): absent at run 2, present at run 3 -- 16 days from 2025-12-20.
    store.add_field_snapshot(
        MKEY1, role="registration", value_json='"N123AB"', absent_run=2, present_run=3, run_id=3
    )

    # -- status events --------------------------------------------------------------------------
    store.add_status_event(MKEY1, old=None, new="Ongoing", absent_run=None, present_run=1, run_id=1)
    store.add_status_event(
        MKEY1, old="Ongoing", new="Completed", absent_run=1, present_run=2, run_id=2
    )
    # "not returned" cases.
    store.add_status_event(
        MKEY4, old="Ongoing", new="not returned", absent_run=1, present_run=1, run_id=1
    )
    store.add_status_event(
        MKEY4, old="not returned", new="Ongoing", absent_run=1, present_run=2, run_id=2
    )
    store.add_status_event(
        MKEY5, old="Ongoing", new="not returned", absent_run=1, present_run=1, run_id=1
    )
    store.add_status_event(
        MKEY6, old="Ongoing", new="not returned", absent_run=1, present_run=1, run_id=1
    )
    # mkey6 reappears only via a bumped last_case_run, no further status event.
    store.upsert_case(
        _case(MKEY6, event_date="2025-12-01", status="not returned").model_copy(
            update={"last_case_run": 3}
        )
    )

    # -- document_events: one tail arrival for mkey1 (after its run-2 closing) ------------------
    same_night = DocumentRow(
        mkey=MKEY1,
        doc_id=100,
        href="docBLOB?ID=100",
        position=1,
        title="DISTINCTIVE-SAME-NIGHT-TITLE",
        pages=1,
        photos=0,
        extension=".PDF",
        absent_run=1,
        present_run=2,
        last_present_run=2,
        gone_absent_run=None,
        gone_present_run=None,
    )
    store.upsert_document(same_night)
    store.add_document_event(
        MKEY1,
        doc_id=100,
        kind="appeared",
        absent_run=1,
        present_run=2,
        run_id=2,
        old=None,
        new={"title": same_night.title},
    )
    tail_doc = DocumentRow(
        mkey=MKEY1,
        doc_id=101,
        href="docBLOB?ID=101",
        position=2,
        title="DISTINCTIVE-TAIL-ARRIVAL-TITLE",
        pages=2,
        photos=0,
        extension=".PDF",
        absent_run=2,
        present_run=3,
        last_present_run=3,
        gone_absent_run=None,
        gone_present_run=None,
    )
    store.upsert_document(tail_doc)
    store.add_document_event(
        MKEY1,
        doc_id=101,
        kind="appeared",
        absent_run=2,
        present_run=3,
        run_id=3,
        old=None,
        new={"title": tail_doc.title},
    )

    # -- docket_polls -----------------------------------------------------------------------
    # mkey1: no-docket at run 1, read (3 docs) at run 2 (a true arrival), read (3 docs) at run 3
    # (unchanged -- must not be double-counted).
    store.add_docket_poll(
        MKEY1,
        run_id=1,
        outcome="no-docket",
        reason=None,
        declared_items=None,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    store.add_docket_poll(
        MKEY1,
        run_id=2,
        outcome="read",
        reason=None,
        declared_items=3,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    store.add_docket_poll(
        MKEY1,
        run_id=3,
        outcome="read",
        reason=None,
        declared_items=3,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    # mkey2: read (5 docs) at its very first poll ever -- present at first sight.
    store.add_docket_poll(
        MKEY2,
        run_id=1,
        outcome="read",
        reason=None,
        declared_items=5,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )

    # -- listing_pages ----------------------------------------------------------------------
    store.add_page(page_sha="a" * 64, mkey=MKEY1, gz=b"x" * 100, run_id=1)
    store.add_page(page_sha="b" * 64, mkey=MKEY2, gz=b"y" * 300, run_id=1)

    # -- change_feed --------------------------------------------------------------------------
    # Matches mkey1's weather_condition arrival (absent=1, present=2) via the run-window rule:
    # this row's own run_id (2) equals present_run.
    store.add_feed_rows(
        [
            FeedRow(
                mkey=MKEY1,
                last_change_utc="2026-01-02T01:00:00+00:00",
                step_number=3,
                step_id="S3",
                case_closed=False,
            )
        ],
        run_id=2,
    )
    # Matches mkey2's pilot_total_hours arrival (absent=1, present=3) via the timestamp rule:
    # its run_id (1) is outside [3, 4], but last_change_utc falls between run 1's and run 3's
    # start times.
    store.add_feed_rows(
        [
            FeedRow(
                mkey=MKEY2,
                last_change_utc="2026-01-03T12:00:00+00:00",
                step_number=None,
                step_id=None,
                case_closed=False,
            )
        ],
        run_id=1,
    )

    # -- prelim narrative (distinctive text, for the output-safety test) ----------------------
    store.add_prelim(
        MKEY1,
        text="DISTINCTIVE PRELIM NARRATIVE TEXT",
        absent_run=None,
        present_run=1,
        run_id=1,
    )

    # -- finish runs 1 and 3; run 2 stays unfinished -------------------------------------------
    store.finish_run(
        1,
        finished_at="2026-01-01T03:40:00+00:00",
        summary=RunSummary(
            cases_polled=4,
            cases_changed=4,
            new_documents=1,
            failures=0,
            suspected_renumbers=1,
            minutes=40.0,
        ),
    )
    store.finish_run(
        3,
        finished_at="2026-01-05T03:35:00+00:00",
        summary=RunSummary(
            cases_polled=4,
            cases_changed=2,
            new_documents=1,
            failures=0,
            suspected_renumbers=2,
            minutes=35.0,
        ),
    )


def test_field_change_arrivals_and_first_sight(store: Store) -> None:
    _populate(store)
    arrivals = sorted(store.field_change_arrivals())
    assert arrivals == sorted(
        [("weather_condition", 13), ("pilot_total_hours", 11), ("registration", 16)]
    )
    assert store.first_sight_field_count() == 3


def test_docket_arrivals_and_first_sight(store: Store) -> None:
    _populate(store)
    assert store.docket_arrivals() == [(13, 3)]
    assert store.docket_first_sight_count() == 1


def test_feed_comparison_matches_both_rule_branches(store: Store) -> None:
    _populate(store)
    # 3 true field arrivals total (weather_condition, pilot_total_hours, registration); 2 are
    # matched by a change_feed row (one via the run-window rule, one via the timestamp rule),
    # registration is not.
    assert store.feed_comparison(window_days=1) == (3, 2)


def test_regulation_changes_counts_current_ongoing_drops(store: Store) -> None:
    _populate(store)
    assert store.regulation_changes() == 1


def test_tail_arrivals_excludes_the_same_night_as_closure(store: Store) -> None:
    _populate(store)
    assert store.tail_arrivals() == 1


def test_renumber_suspects_sums_finished_runs_only(store: Store) -> None:
    _populate(store)
    # Run 1 contributes 1, run 3 contributes 2; run 2 (unfinished) contributes nothing.
    assert store.renumber_suspects() == 3


def test_possible_false_not_returned(store: Store) -> None:
    _populate(store)
    # mkey4 (a later status event back from "not returned") and mkey6 (a later last_case_run)
    # count; mkey5 (never reappears) does not.
    assert store.possible_false_not_returned() == 2


def test_compressed_page_sizes(store: Store) -> None:
    _populate(store)
    assert sorted(store.compressed_page_sizes()) == [100, 300]


def test_report_prints_nights_and_no_case_data(store: Store) -> None:
    _populate(store)
    run_rows = store.run_summaries()
    field_arrivals: dict[str, list[int]] = defaultdict(list)
    for role, days in store.field_change_arrivals():
        field_arrivals[role].append(days)

    text = report(
        run_rows=run_rows,
        field_arrivals=field_arrivals,
        first_sight_fields=store.first_sight_field_count(),
        docket_arrivals=store.docket_arrivals(),
        docket_first_sight=store.docket_first_sight_count(),
        feed_comparison=store.feed_comparison(),
        regulation_changes=store.regulation_changes(),
        tail_arrivals=store.tail_arrivals(),
        renumber_suspects=store.renumber_suspects(),
        possible_false_not_returned=store.possible_false_not_returned(),
        page_sizes=store.compressed_page_sizes(),
    )

    assert "nights: 3" in text
    assert "unfinished (crashed) runs: 1" in text

    # Output-safety (Task 11 controller note 9): distinctive case numbers, an mkey, a document
    # title and prelim narrative text built into the store above must never appear.
    for distinctive in (
        "DCA26FDISTINCTIVE",
        str(MKEY3),
        "DISTINCTIVE-SAME-NIGHT-TITLE",
        "DISTINCTIVE-TAIL-ARRIVAL-TITLE",
        "DISTINCTIVE PRELIM NARRATIVE TEXT",
        "ntsb_number",
    ):
        assert distinctive not in text


def test_empty_store_prints_no_data(store: Store) -> None:
    text = report(
        run_rows=store.run_summaries(),
        field_arrivals={},
        first_sight_fields=store.first_sight_field_count(),
        docket_arrivals=store.docket_arrivals(),
        docket_first_sight=store.docket_first_sight_count(),
        feed_comparison=store.feed_comparison(),
        regulation_changes=store.regulation_changes(),
        tail_arrivals=store.tail_arrivals(),
        renumber_suspects=store.renumber_suspects(),
        possible_false_not_returned=store.possible_false_not_returned(),
        page_sizes=store.compressed_page_sizes(),
    )
    assert "nights: 0" in text
    assert "run summaries: no data" in text
    assert "no data" in text
