"""Tests for the recorder report's store queries and its pure ``report()`` text (Task 11).

Fix round 1 (2026-09-23): rewritten for the corrected feed rule (CRITICAL 2), the
before/same-run/after-closure classification (IMPORTANT 5), the docket absent-side rule
(IMPORTANT 4), the split closure tail (IMPORTANT 3), the preliminary narrative (IMPORTANT 6)
and migration 2's regulation history (IMPORTANT 7). See ``docs/plans/2026-09-22-s25-recorder.md``
Deviations for what changed and why.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts.recorder_report import report

from ntsb_probable_cause.store import (
    ArrivalClassification,
    CaseRow,
    DocumentRow,
    FeedRow,
    RunSummary,
    Store,
)

RUN1 = "2026-01-01T03:00:00+00:00"  # day 0
RUN2 = "2026-01-02T03:00:00+00:00"  # day 1
RUN3 = "2026-01-03T03:00:00+00:00"  # day 2 -- left unfinished in every test that uses it
RUN4 = "2026-01-06T03:00:00+00:00"  # day 5
RUN5 = "2026-01-16T03:00:00+00:00"  # day 15 -- far outside any 1-day feed window


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store(tmp_path / "r.sqlite") as opened:
        opened.migrate()
        yield opened


def _case(  # noqa: PLR0913 -- one keyword per CaseRow field a test needs to vary.
    mkey: int,
    *,
    event_date: str,
    status: str = "Ongoing",
    watched: bool = True,
    first_seen_run: int = 1,
    regulation: str | None = "091",
) -> CaseRow:
    return CaseRow(
        mkey=mkey,
        ntsb_number=f"DISTINCTIVE{mkey:04d}",
        event_date=event_date,
        regulation=regulation,
        status=status,
        first_seen_run=first_seen_run,
        last_seen_run=first_seen_run,
        last_case_run=first_seen_run,
        last_docket_run=None,
        watch_until=None,
        watched=watched,
    )


def _begin_runs(store: Store, *run_ids_and_starts: tuple[int, str]) -> None:
    """Begin one run per ``(expected_id, started_at)`` pair, asserting the id sequence."""
    for expected_id, started_at in run_ids_and_starts:
        run_id = store.begin_run(started_at=started_at, commit_sha="a" * 7, dirty=False)
        assert run_id == expected_id


# --- field arrival classification (IMPORTANT 5) ---------------------------------------------


def test_field_arrivals_are_classified_before_same_run_after_and_excluded(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3), (4, RUN4))

    # mkey 1: never closes -- its arrival is BEFORE_CLOSURE.
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )

    # mkey 2: closes (real closure) at run 3; one arrival lands on the closing run itself, one
    # after it.
    store.upsert_case(_case(2, event_date="2025-12-25"))
    store.add_status_event(2, old="Ongoing", new="Completed", absent_run=2, present_run=3, run_id=3)
    store.add_field_snapshot(
        2, role="registration", value_json='"N1"', absent_run=2, present_run=3, run_id=3
    )
    store.add_field_snapshot(
        2, role="pilot_total_hours", value_json="10", absent_run=3, present_run=4, run_id=4
    )

    # mkey 3: currently unwatched (dropped for its regulation) -- excluded regardless of status.
    store.upsert_case(_case(3, event_date="2025-12-01", watched=False))
    store.add_field_snapshot(
        3, role="injury_level", value_json='"None"', absent_run=1, present_run=2, run_id=2
    )

    arrivals = {(row.role, row.classification) for row in store.field_change_arrivals()}
    assert arrivals == {
        ("weather_condition", ArrivalClassification.BEFORE_CLOSURE),
        ("registration", ArrivalClassification.SAME_RUN_AS_CLOSURE),
        ("pilot_total_hours", ArrivalClassification.AFTER_CLOSURE),
        ("injury_level", ArrivalClassification.EXCLUDED_UNWATCHED),
    }

    weather = next(r for r in store.field_change_arrivals() if r.role == "weather_condition")
    assert weather.days == 13  # 2026-01-02 - 2025-12-20
    assert weather.absent_days == 12  # 2026-01-01 - 2025-12-20


def test_first_sight_field_count(store: Store) -> None:
    _begin_runs(store, (1, RUN1))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_field_snapshot(
        1, role="engine_type", value_json='"REC"', absent_run=None, present_run=1, run_id=1
    )
    assert store.first_sight_field_count() == 1
    assert store.field_change_arrivals() == []


# --- preliminary narrative arrival (IMPORTANT 6) -------------------------------------------


def test_prelim_arrival_and_first_sight(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.upsert_case(_case(2, event_date="2025-12-22"))

    store.add_prelim(1, text="first sight", absent_run=None, present_run=1, run_id=1)
    store.add_prelim(2, text="arrived later", absent_run=1, present_run=2, run_id=2)

    assert store.prelim_first_sight_count() == 1
    (arrival,) = store.prelim_arrivals()
    assert arrival.classification == ArrivalClassification.BEFORE_CLOSURE
    assert arrival.days == 11  # 2026-01-02 - 2025-12-22
    assert arrival.absent_days == 10  # 2026-01-01 - 2025-12-22


# --- docket arrival, first sight, and absent-side-unknown (IMPORTANT 4) --------------------


def test_docket_arrival_uses_the_last_absence_observation_before_the_first_read(
    store: Store,
) -> None:
    """The absent side is the LAST no-docket/empty poll before the first read poll, not the
    first."""
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_docket_poll(
        1,
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
        1,
        run_id=2,
        outcome="empty",
        reason=None,
        declared_items=0,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    store.add_docket_poll(
        1,
        run_id=3,
        outcome="read",
        reason=None,
        declared_items=4,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )

    (arrival,) = store.docket_arrivals()
    assert arrival.document_count == 4
    assert arrival.days == 14  # 2026-01-03 - 2025-12-20
    assert arrival.absent_days == 13  # run 2 (empty), the LAST absence poll -- not run 1
    assert store.docket_first_sight_count() == 0
    assert store.docket_absent_side_unknown_count() == 0


def test_docket_first_sight(store: Store) -> None:
    _begin_runs(store, (1, RUN1))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_docket_poll(
        1,
        run_id=1,
        outcome="read",
        reason=None,
        declared_items=7,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    assert store.docket_first_sight_count() == 1
    assert store.docket_arrivals() == []
    assert store.docket_absent_side_unknown_count() == 0


def test_docket_absent_side_unknown_when_only_failed_polls_precede(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_docket_poll(
        1,
        run_id=1,
        outcome="failed",
        reason="500",
        declared_items=None,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    store.add_docket_poll(
        1,
        run_id=2,
        outcome="read",
        reason=None,
        declared_items=2,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    assert store.docket_absent_side_unknown_count() == 1
    assert store.docket_arrivals() == []
    assert store.docket_first_sight_count() == 0


def test_docket_with_no_read_poll_ever_contributes_to_no_docket_count(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_docket_poll(
        1,
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
        1,
        run_id=2,
        outcome="empty",
        reason=None,
        declared_items=0,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    assert store.docket_arrivals() == []
    assert store.docket_first_sight_count() == 0
    assert store.docket_absent_side_unknown_count() == 0


# --- feed comparison (CRITICAL 1 and 2) ------------------------------------------------------


def test_feed_comparison_matches_and_rejects_the_reviewers_counter_examples(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3), (4, RUN4), (5, RUN5))
    for mkey in (8, 9, 10):
        store.upsert_case(_case(mkey, event_date="2025-12-01"))
        store.add_field_snapshot(
            mkey,
            role="weather_condition",
            value_json='"VMC"',
            absent_run=1,
            present_run=2,
            run_id=2,
        )

    # mkey 8: a genuine match -- polled within the window, timestamp after the absent run.
    store.add_feed_rows(
        [
            FeedRow(
                mkey=8,
                last_change_utc="2026-01-02T01:00:00",
                step_number=None,
                step_id=None,
                case_closed=False,
            )
        ],
        run_id=2,
    )
    # mkey 9 (counter-example 1): a stamp BEFORE the absent run's start -- must NOT count, even
    # though it was polled inside the window.
    store.add_feed_rows(
        [
            FeedRow(
                mkey=9,
                last_change_utc="2025-12-31T00:00:00+00:00",
                step_number=None,
                step_id=None,
                case_closed=False,
            )
        ],
        run_id=2,
    )
    # mkey 10 (counter-example 2): a poll 10+ days later -- must NOT count, even though its own
    # timestamp is validly after the absent run.
    store.add_feed_rows(
        [
            FeedRow(
                mkey=10,
                last_change_utc="2026-01-02T12:00:00+00:00",
                step_number=None,
                step_id=None,
                case_closed=False,
            )
        ],
        run_id=5,
    )

    result = store.feed_comparison(window_days=1)
    assert result.field_changes == 3
    assert result.field_changes_reported == 1
    assert result.case_nights == 3  # (8,2), (9,2), (10,2) are all distinct case-nights
    assert result.case_nights_reported == 1


def test_feed_timestamp_with_no_timezone_is_read_as_utc(store: Store) -> None:
    """CRITICAL 1: the only real saved ``*DateTimeUtc`` value has no zone offset at all."""
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )
    # No "Z", no "+00:00" -- exactly the shape tests/fixtures/api/page.json's
    # caseCreatedDateTimeUtc carries.
    store.add_feed_rows(
        [
            FeedRow(
                mkey=1,
                last_change_utc="2026-01-02T01:00:00",
                step_number=None,
                step_id=None,
                case_closed=False,
            )
        ],
        run_id=2,
    )
    result = store.feed_comparison(window_days=1)
    assert result.field_changes_reported == 1


def test_feed_comparison_caches_change_feed_rows_per_mkey(store: Store) -> None:
    """Two field changes on the same case in one run: one case-night, two field-row changes,
    and the change_feed rows for that mkey are fetched once, not once per field row."""
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )
    store.add_field_snapshot(
        1, role="registration", value_json='"N1"', absent_run=1, present_run=2, run_id=2
    )
    store.add_feed_rows(
        [
            FeedRow(
                mkey=1,
                last_change_utc="2026-01-02T01:00:00+00:00",
                step_number=None,
                step_id=None,
                case_closed=False,
            )
        ],
        run_id=2,
    )
    result = store.feed_comparison(window_days=1)
    assert result.field_changes == 2
    assert result.field_changes_reported == 2
    assert result.case_nights == 1
    assert result.case_nights_reported == 1


# --- regulation transitions (IMPORTANT 7 / migration 2) ------------------------------------


def test_regulation_transitions_four_categories_and_fill_in_days(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3))
    for mkey in (11, 12, 13, 14, 15):
        store.upsert_case(_case(mkey, event_date="2025-12-01", first_seen_run=1))

    store.add_regulation_event(
        11, old=None, new="091", was_watched=True, absent_run=1, present_run=3, run_id=3
    )
    store.add_regulation_event(
        12, old=None, new="135", was_watched=True, absent_run=1, present_run=2, run_id=2
    )
    store.add_regulation_event(
        13, old="091", new="135", was_watched=True, absent_run=1, present_run=2, run_id=2
    )
    store.add_regulation_event(
        14, old="091", new=None, was_watched=True, absent_run=1, present_run=2, run_id=2
    )
    # was_watched=False: excluded from every count.
    store.add_regulation_event(
        15, old="091", new="135", was_watched=False, absent_run=1, present_run=2, run_id=2
    )

    result = store.regulation_transitions()
    assert result.empty_to_091 == 1
    assert result.empty_to_091_days == (2,)  # 2026-01-03 - 2026-01-01
    assert result.empty_to_other == 1
    assert result.changed_value == 1
    assert result.value_to_empty == 1


# --- closure tail (IMPORTANT 3) --------------------------------------------------------------


def test_tail_arrivals_real_closures_only_split_same_run_after_and_excludes_first_sight(
    store: Store,
) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3))
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_status_event(1, old="Ongoing", new="Completed", absent_run=1, present_run=2, run_id=2)

    def _doc(doc_id: int, *, absent_run: int | None, present_run: int) -> DocumentRow:
        return DocumentRow(
            mkey=1,
            doc_id=doc_id,
            href=f"docBLOB?ID={doc_id}",
            position=1,
            title="DISTINCTIVE-TITLE",
            pages=1,
            photos=0,
            extension=".PDF",
            absent_run=absent_run,
            present_run=present_run,
            last_present_run=present_run,
            gone_absent_run=None,
            gone_present_run=None,
        )

    # Same run as closure (order unknown).
    store.upsert_document(_doc(1, absent_run=1, present_run=2))
    store.add_document_event(
        1, doc_id=1, kind="appeared", absent_run=1, present_run=2, run_id=2, old=None, new={}
    )
    # After closure.
    store.upsert_document(_doc(2, absent_run=2, present_run=3))
    store.add_document_event(
        1, doc_id=2, kind="appeared", absent_run=2, present_run=3, run_id=3, old=None, new={}
    )
    # First-sight (absent_run IS NULL) -- excluded even though present_run is after closure.
    store.upsert_document(_doc(3, absent_run=None, present_run=3))
    store.add_document_event(
        1, doc_id=3, kind="appeared", absent_run=None, present_run=3, run_id=3, old=None, new={}
    )

    result = store.tail_arrivals()
    assert result.same_run == 1
    assert result.after == 1
    assert result.total == 2
    assert result.not_returned_tail == 0


def test_not_returned_tail_is_separate_and_uses_at_or_after(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3))
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_status_event(
        1, old="Ongoing", new="not returned", absent_run=1, present_run=2, run_id=2
    )

    def _doc(doc_id: int, *, absent_run: int | None, present_run: int) -> DocumentRow:
        return DocumentRow(
            mkey=1,
            doc_id=doc_id,
            href=f"docBLOB?ID={doc_id}",
            position=1,
            title="DISTINCTIVE-TITLE",
            pages=1,
            photos=0,
            extension=".PDF",
            absent_run=absent_run,
            present_run=present_run,
            last_present_run=present_run,
            gone_absent_run=None,
            gone_present_run=None,
        )

    # present_run == event_run: "at or after" counts it.
    store.upsert_document(_doc(1, absent_run=1, present_run=2))
    store.add_document_event(
        1, doc_id=1, kind="appeared", absent_run=1, present_run=2, run_id=2, old=None, new={}
    )
    # present_run > event_run: also counts.
    store.upsert_document(_doc(2, absent_run=2, present_run=3))
    store.add_document_event(
        1, doc_id=2, kind="appeared", absent_run=2, present_run=3, run_id=3, old=None, new={}
    )

    result = store.tail_arrivals()
    assert result.not_returned_tail == 2
    assert result.total == 0  # no REAL closure for this case


# --- suspects, false not-returned, page sizes (unaffected by this fix round) ---------------


def test_renumber_suspects_sums_finished_runs_only(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.finish_run(
        1,
        finished_at=RUN1,
        summary=RunSummary(
            cases_polled=1,
            cases_changed=0,
            new_documents=0,
            failures=0,
            suspected_renumbers=1,
            minutes=1.0,
        ),
    )
    # run 2 left unfinished -- contributes nothing.
    assert store.renumber_suspects() == 1


def test_possible_false_not_returned(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3))
    store.upsert_case(_case(4, event_date="2025-12-01"))
    store.upsert_case(_case(5, event_date="2025-12-01"))
    store.upsert_case(_case(6, event_date="2025-12-01"))
    store.add_status_event(
        4, old="Ongoing", new="not returned", absent_run=1, present_run=1, run_id=1
    )
    store.add_status_event(
        4, old="not returned", new="Ongoing", absent_run=1, present_run=2, run_id=2
    )
    store.add_status_event(
        5, old="Ongoing", new="not returned", absent_run=1, present_run=1, run_id=1
    )
    # mkey 6: no later status event away from "not returned", but the case's own row shows a
    # later last_case_run -- observe_case ran again for it (mark_not_returned never touches
    # last_case_run), so it reappeared in the API without an explicit status event.
    store.add_status_event(
        6, old="Ongoing", new="not returned", absent_run=1, present_run=1, run_id=1
    )
    store.upsert_case(
        _case(6, event_date="2025-12-01", status="not returned").model_copy(
            update={"last_case_run": 3}
        )
    )
    assert store.possible_false_not_returned() == 2


def test_compressed_page_sizes(store: Store) -> None:
    store.add_page(page_sha="a" * 64, mkey=1, gz=b"x" * 100, run_id=1)
    store.add_page(page_sha="b" * 64, mkey=2, gz=b"y" * 300, run_id=1)
    assert sorted(store.compressed_page_sizes()) == [100, 300]


# --- report() text: percentile method, classification rule, safety, no-data ---------------


def _full_report_from(store: Store) -> str:
    return report(
        run_rows=store.run_summaries(),
        field_arrivals=store.field_change_arrivals(),
        first_sight_fields=store.first_sight_field_count(),
        prelim_arrivals=store.prelim_arrivals(),
        prelim_first_sight=store.prelim_first_sight_count(),
        docket_arrivals=store.docket_arrivals(),
        docket_first_sight=store.docket_first_sight_count(),
        docket_absent_side_unknown=store.docket_absent_side_unknown_count(),
        feed_comparison=store.feed_comparison(),
        feed_window_days=1,
        regulation_transitions=store.regulation_transitions(),
        tail_arrivals=store.tail_arrivals(),
        renumber_suspects=store.renumber_suspects(),
        possible_false_not_returned=store.possible_false_not_returned(),
        page_sizes=store.compressed_page_sizes(),
    )


def test_report_states_nights_finished_nights_and_the_rules(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.finish_run(
        1,
        finished_at=RUN1,
        summary=RunSummary(
            cases_polled=0,
            cases_changed=0,
            new_documents=0,
            failures=0,
            suspected_renumbers=0,
            minutes=1.0,
        ),
    )
    # run 2 left unfinished.
    text = _full_report_from(store)

    assert "nights: 2" in text
    assert "finished nights: 1 " in text
    assert "unfinished (crashed) runs: 1" in text
    assert "Percentiles: nearest-rank method" in text
    assert "BEFORE_CLOSURE" in text
    assert "CRITICAL 2" in text or "reported iff" in text


def test_report_suppresses_percentiles_below_three_observations(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )
    text = _full_report_from(store)
    assert "n<3" in text


def test_report_prints_no_case_data(store: Store) -> None:
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )
    store.add_status_event(1, old="Ongoing", new="Completed", absent_run=2, present_run=3, run_id=3)
    store.add_prelim(1, text="DISTINCTIVE PRELIM TEXT", absent_run=None, present_run=1, run_id=1)

    document = DocumentRow(
        mkey=1,
        doc_id=1,
        href="docBLOB?ID=1",
        position=1,
        title="DISTINCTIVE DOC TITLE",
        pages=1,
        photos=0,
        extension=".PDF",
        absent_run=None,
        present_run=1,
        last_present_run=1,
        gone_absent_run=None,
        gone_present_run=None,
    )
    store.upsert_document(document)

    text = _full_report_from(store)
    for distinctive in ("DISTINCTIVE1234", "DISTINCTIVE PRELIM TEXT", "DISTINCTIVE DOC TITLE"):
        assert distinctive not in text
    assert "ntsb_number" not in text


def test_report_empty_store_prints_no_data(store: Store) -> None:
    text = _full_report_from(store)
    assert "nights: 0" in text
    assert "run summaries: no data" in text
    assert "no data" in text
