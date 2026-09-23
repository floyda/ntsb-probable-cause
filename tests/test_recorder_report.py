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
from scripts.recorder_report import _open_store, main, report

from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import (
    ArrivalClassification,
    CaseRow,
    DocumentRow,
    FeedRow,
    RunSummary,
    Store,
)
from ntsb_probable_cause.store import schema as store_schema
from ntsb_probable_cause.store.sync import Location

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

    # mkey 3: regulation is currently "135" (not Part 91) and there is no regulation_events
    # history at all -- the no-history fallback reads the case's current regulation.
    store.upsert_case(_case(3, event_date="2025-12-01", regulation="135"))
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


def test_i5_tail_expiry_never_moves_arrivals_to_excluded(store: Store) -> None:
    """Task 11 fix round 2, IMPORTANT I5: the reviewer's own reproduction.

    A case whose field, preliminary narrative and docket all arrive on night 3, and which
    closes on night 5, must have all three stay BEFORE_CLOSURE forever after -- including once
    the case's ``watched`` flag clears when its 30-day tail expires (simulated here directly,
    since only ``recorder/cases.py`` runs the tail logic; ``Store`` itself never computes it).
    The case's regulation is never dropped and no ``regulation_events`` row is ever written.
    """
    _begin_runs(
        store,
        (1, "2026-01-01T03:00:00+00:00"),
        (2, "2026-01-02T03:00:00+00:00"),
        (3, "2026-01-03T03:00:00+00:00"),
        (4, "2026-01-04T03:00:00+00:00"),
        (5, "2026-01-05T03:00:00+00:00"),
        (6, "2026-01-06T03:00:00+00:00"),
    )
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=2, present_run=3, run_id=3
    )
    store.add_prelim(1, text="arrived", absent_run=2, present_run=3, run_id=3)
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
        declared_items=2,
        creation_date=None,
        last_modified=None,
        release_date=None,
        page_sha=None,
    )
    store.add_status_event(1, old="Ongoing", new="Completed", absent_run=4, present_run=5, run_id=5)
    # Night 6: the tail expires; `watched` clears. Regulation was never touched.
    store.upsert_case(
        _case(1, event_date="2025-12-01", status="Completed", watched=False, first_seen_run=1)
    )

    (field,) = store.field_change_arrivals()
    assert field.classification == ArrivalClassification.BEFORE_CLOSURE
    (prelim,) = store.prelim_arrivals()
    assert prelim.classification == ArrivalClassification.BEFORE_CLOSURE
    (docket,) = store.docket_arrivals()
    assert docket.classification == ArrivalClassification.BEFORE_CLOSURE


def test_i5_regulation_drop_boundary_excludes_at_and_after_the_drop_run(store: Store) -> None:
    """091 -> 135 recorded at run 3: an arrival at run 2 is counted; one at run 3 itself (the
    drop's own run, a conservative choice) and one at run 4 are excluded."""
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3), (4, RUN4))
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_regulation_event(
        1, old="091", new="135", was_watched=True, absent_run=2, present_run=3, run_id=3
    )
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )
    store.add_field_snapshot(
        1, role="registration", value_json='"N1"', absent_run=2, present_run=3, run_id=3
    )
    store.add_field_snapshot(
        1, role="pilot_total_hours", value_json="1", absent_run=3, present_run=4, run_id=4
    )

    by_role = {row.role: row.classification for row in store.field_change_arrivals()}
    assert by_role["weather_condition"] == ArrivalClassification.BEFORE_CLOSURE
    assert by_role["registration"] == ArrivalClassification.EXCLUDED_UNWATCHED
    assert by_role["pilot_total_hours"] == ArrivalClassification.EXCLUDED_UNWATCHED


def test_i5_regulation_readmission_counts_arrivals_after_it(store: Store) -> None:
    """135 -> 091: an arrival recorded after the re-admission is counted normally."""
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3))
    store.upsert_case(_case(1, event_date="2025-12-01", regulation="135"))
    store.add_regulation_event(
        1, old="135", new="091", was_watched=False, absent_run=1, present_run=2, run_id=2
    )
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=2, present_run=3, run_id=3
    )
    (field,) = store.field_change_arrivals()
    assert field.classification == ArrivalClassification.BEFORE_CLOSURE


def test_i5_no_regulation_history_falls_back_to_current_regulation(store: Store) -> None:
    """No ``regulation_events`` rows at all: the case's current ``cases.regulation`` decides."""
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-01", regulation="135"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )
    (field,) = store.field_change_arrivals()
    assert field.classification == ArrivalClassification.EXCLUDED_UNWATCHED


def test_first_sight_field_count(store: Store) -> None:
    _begin_runs(store, (1, RUN1))
    store.upsert_case(_case(1, event_date="2025-12-20"))
    store.add_field_snapshot(
        1, role="engine_type", value_json='"REC"', absent_run=None, present_run=1, run_id=1
    )
    assert store.first_sight_field_count() == 1
    assert store.field_change_arrivals() == []


def test_a_new_cases_first_snapshot_with_a_known_absent_run_is_a_true_arrival(
    store: Store,
) -> None:
    """Final review item 2 (Andy's decision 2026-09-23): a case observed for the very first
    time whose event month an EARLIER run had already fetched cleanly gets a real absent side
    on its first-sight row (`recorder.cases.observe_case`'s `new_case_absent_run`) -- the
    report's arrival query must count that as a TRUE arrival, not fold it into the
    "present when watching began" first-sight count, exactly as any other true arrival."""
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-20", first_seen_run=2))
    # The case's very first-ever field_snapshots row, written with a real `absent_run` -- what
    # `observe_case(..., new_case_absent_run=1)` produces for a brand-new mkey.
    store.add_field_snapshot(
        1, role="engine_type", value_json='"REC"', absent_run=1, present_run=2, run_id=2
    )

    assert store.first_sight_field_count() == 0  # not "present when watching began"
    (arrival,) = store.field_change_arrivals()
    assert arrival.role == "engine_type"
    assert arrival.classification == ArrivalClassification.BEFORE_CLOSURE
    assert arrival.days == 13  # 2026-01-02 - 2025-12-20
    assert arrival.absent_days == 12  # 2026-01-01 - 2025-12-20


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


def test_feed_timestamp_with_no_timezone_and_4_5_or_6_fractional_digits_is_read_as_utc(
    store: Store,
) -> None:
    """Task 11 close-out: the live probe (2026-09-23, `make change-feed-probe`) confirmed
    ``lastChangeDateTimeUtc`` carries no time zone at all and 4, 5 or 6 fractional-second
    digits (``dddd-dd-ddTdd:dd:dd.dddd``/``.ddddd``/``.dddddd``) -- never a "Z" or an offset.
    All three widths must parse as UTC, exactly like the plain-seconds form fix round 1 fixed.
    """
    _begin_runs(store, (1, RUN1), (2, RUN2))
    for mkey, fractional in ((1, "1234"), (2, "12345"), (3, "123456")):
        store.upsert_case(_case(mkey, event_date="2025-12-01"))
        store.add_field_snapshot(
            mkey,
            role="weather_condition",
            value_json='"VMC"',
            absent_run=1,
            present_run=2,
            run_id=2,
        )
        store.add_feed_rows(
            [
                FeedRow(
                    mkey=mkey,
                    last_change_utc=f"2026-01-02T01:00:00.{fractional}",
                    step_number=None,
                    step_id=None,
                    case_closed=False,
                )
            ],
            run_id=2,
        )
    result = store.feed_comparison(window_days=1)
    assert result.field_changes == 3
    assert result.field_changes_reported == 3
    assert result.unparsable_timestamps == 0


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


def test_feed_comparison_counts_unparsable_timestamps(store: Store) -> None:
    """Task 11 fix round 2, MINOR 3."""
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=1, present_run=2, run_id=2
    )
    store.add_feed_rows(
        [
            FeedRow(
                mkey=1,
                last_change_utc="not-a-timestamp-at-all",
                step_number=None,
                step_id=None,
                case_closed=False,
            ),
            FeedRow(
                mkey=1,
                last_change_utc="2026-01-02T01:00:00+00:00",
                step_number=None,
                step_id=None,
                case_closed=False,
            ),
        ],
        run_id=2,
    )
    result = store.feed_comparison(window_days=1)
    assert result.unparsable_timestamps == 1
    assert result.field_changes_reported == 1  # the good row still matches


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


def test_closure_run_ignores_a_relabel_between_two_non_ongoing_statuses(store: Store) -> None:
    """Task 11 fix round 2, I3: a Completed -> N/A relabel must not move the closure run --
    the case actually left Ongoing at the earlier, real closure."""
    _begin_runs(store, (1, RUN1), (2, RUN2), (3, RUN3), (4, RUN4))
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_status_event(1, old="Ongoing", new="Completed", absent_run=2, present_run=3, run_id=3)
    store.add_status_event(1, old="Completed", new="N/A", absent_run=3, present_run=4, run_id=4)
    # An arrival on the relabel's own run (4) must read AFTER_CLOSURE, not SAME_RUN_AS_CLOSURE
    # -- the real closure was run 3.
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=3, present_run=4, run_id=4
    )
    (field,) = store.field_change_arrivals()
    assert field.classification == ArrivalClassification.AFTER_CLOSURE


def test_closure_reached_via_not_returned_is_a_real_closure(store: Store) -> None:
    """Task 11 fix round 3: the reviewer's own reproduction, with the real recorder shape.

    status_events are ``(None, 'Ongoing', 1)``, ``('Ongoing', 'not returned', 3)``,
    ``('not returned', 'Completed', 4)``. Round 2's ``old_status = 'Ongoing'`` requirement
    made ``_closure_runs()`` return ``{}`` for this case -- a real closure was missed entirely
    because it was reached via 'not returned' rather than directly from 'Ongoing'. A field
    arriving on night 5, after the case closed on night 4, must be AFTER_CLOSURE, and the case
    must appear in both the real-closure tail and the 'not returned' tail.
    """
    _begin_runs(
        store,
        (1, "2026-01-01T03:00:00+00:00"),
        (2, "2026-01-02T03:00:00+00:00"),
        (3, "2026-01-03T03:00:00+00:00"),
        (4, "2026-01-04T03:00:00+00:00"),
        (5, "2026-01-05T03:00:00+00:00"),
    )
    store.upsert_case(_case(1, event_date="2025-12-01"))
    store.add_status_event(1, old=None, new="Ongoing", absent_run=None, present_run=1, run_id=1)
    store.add_status_event(
        1, old="Ongoing", new="not returned", absent_run=1, present_run=3, run_id=3
    )
    store.add_status_event(
        1, old="not returned", new="Completed", absent_run=3, present_run=4, run_id=4
    )
    store.add_field_snapshot(
        1, role="weather_condition", value_json='"VMC"', absent_run=4, present_run=5, run_id=5
    )

    (field,) = store.field_change_arrivals()
    assert field.classification == ArrivalClassification.AFTER_CLOSURE

    # The case appears in both tails: the real closure (run 4) and the 'not returned' event
    # (also run 4) each have a document arriving strictly after them (run 5).
    document = DocumentRow(
        mkey=1,
        doc_id=1,
        href="docBLOB?ID=1",
        position=1,
        title="DISTINCTIVE-TITLE",
        pages=1,
        photos=0,
        extension=".PDF",
        absent_run=4,
        present_run=5,
        last_present_run=5,
        gone_absent_run=None,
        gone_present_run=None,
    )
    store.upsert_document(document)
    store.add_document_event(
        1, doc_id=1, kind="appeared", absent_run=4, present_run=5, run_id=5, old=None, new={}
    )
    tail = store.tail_arrivals()
    assert tail.total == 1
    assert tail.not_returned_tail == 1


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

    assert "nights recorded (every run, finished or not): 2" in text
    assert "finished runs: 1" in text
    assert "distinct finished nights: 1 " in text
    assert "unfinished (crashed) runs: 1" in text
    assert "Percentiles: nearest-rank method" in text
    assert "How arrivals are classified" in text
    assert "before-closure arrivals are the mask distribution" in text


def test_report_never_prints_reviewer_labels_or_raw_column_names(store: Store) -> None:
    """Fix round 1 MINOR 1, extended in fix round 3 WORDING 5: the citable report is plain
    English -- no review shorthand, no SQL column names. Populated with at least one finished
    and one unfinished run, so the run table and totals line are actually rendered (an empty
    store never reaches that code path at all)."""
    _begin_runs(store, (1, RUN1), (2, RUN2))
    store.finish_run(
        1,
        finished_at=RUN1,
        summary=RunSummary(
            cases_polled=1,
            cases_changed=1,
            new_documents=1,
            failures=0,
            suspected_renumbers=0,
            minutes=1.0,
        ),
    )
    text = _full_report_from(store)
    for forbidden in (
        "CRITICAL",
        "IMPORTANT",
        "MINOR",
        "change_feed row",
        "last_change_utc",
        "cases.watched",
        "cases.regulation",
        "run_id",
        "started_at",
        "finished_at",
        "cases_polled",
        "cases_changed",
        "new_documents",
        "suspected_renumbers",
        "SAME NIGHT AS",
    ):
        assert forbidden not in text
    assert "started (UTC)" in text
    assert "finished (UTC)" in text
    assert "SAME RUN AS" in text
    assert "cases polled=" in text
    assert "cases changed=" in text
    assert "new documents=" in text


def test_report_states_the_whole_i5_rule_and_the_feed_direction(store: Store) -> None:
    """Task 11 fix round 3, WORDING 1 and WORDING 4."""
    text = _full_report_from(store)
    assert "the latest regulation change recorded at or before the arrival's run decides" in text
    assert "the regulation recorded before the first of those changes decides" in text
    assert "its regulation as currently recorded decides" in text
    assert "excluded only when that decided regulation is neither not-yet-recorded nor" in text
    assert "whichever night that was" not in text
    assert "at the same time as, or within" in text
    assert "day(s) after, the run that found the change" in text


def test_report_states_the_evidence_field_name_note(store: Store) -> None:
    """Task 11 fix round 3, WORDING 5."""
    text = _full_report_from(store)
    assert "this project's own evidence field names, not raw database column names" in text


def test_report_states_the_new_case_absent_side_rule(store: Store) -> None:
    """Final review item 2, corrected wording by the pre-deploy fix round item B: the report
    states, in plain English, when a case first seen after the recorder's first night gets a
    true absent side instead of reading as first-sight -- "the latest earlier night whose
    fetch ... was clean and fully observed", never simply "the night before"."""
    text = _full_report_from(store)
    rule = (
        "a case first seen after the recorder's first night has an absent side if the "
        "latest earlier night whose fetch of its event month was clean and fully observed "
        "found it absent"
    )
    assert rule in text
    assert "was fetched cleanly the night before" not in text  # the old, corrected wording
    assert text.count("A record the API returned but never stored") == 1
    assert (
        text.count(
            "which nights count as 'clean and fully observed' is known only from the "
            "night this store gained the table that records it"
        )
        == 1
    )


def test_report_regulation_coverage_makes_no_deployment_claim(store: Store) -> None:
    """Task 11 fix round 3, WORDING 2: no claim about a particular store's own history."""
    text = _full_report_from(store)
    assert (
        "Regulation changes are known only from the night the regulation-history table was "
        "added to this store" in text
    )
    assert "for any nights before that, changes are unknown, not zero" in text
    assert "has always been built with the regulation-history table present" not in text
    assert "no gap for this deployment" not in text


def test_report_counts_distinct_finished_nights_not_runs(store: Store) -> None:
    """MINOR 2: two finished runs on the same UTC calendar date count as one finished night."""
    same_night_a = "2026-01-01T03:00:00+00:00"
    same_night_b = "2026-01-01T14:00:00+00:00"  # same UTC date, a re-run later that day
    different_night = "2026-01-02T03:00:00+00:00"
    _begin_runs(store, (1, same_night_a), (2, same_night_b), (3, different_night))
    for run_id, started_at in ((1, same_night_a), (2, same_night_b), (3, different_night)):
        store.finish_run(
            run_id,
            finished_at=started_at,
            summary=RunSummary(
                cases_polled=0,
                cases_changed=0,
                new_documents=0,
                failures=0,
                suspected_renumbers=0,
                minutes=1.0,
            ),
        )
    text = _full_report_from(store)
    assert "nights recorded (every run, finished or not): 3" in text
    assert "finished runs: 3" in text
    assert "distinct finished nights: 2 " in text


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
    assert "nights recorded (every run, finished or not): 0" in text
    assert "run summaries: no data" in text
    assert "no data" in text


# --- _open_store / main(): the store is opened strictly read-only (Task 11 fix round 2, MINOR 4)


def test_open_store_with_no_file_returns_none_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "does-not-exist.sqlite"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_STORE", str(store_path))

    result_store, error = _open_store(Settings())

    assert result_store is None
    assert error is None
    assert not store_path.exists()


def test_open_store_refuses_a_mismatched_schema_version_without_migrating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store stuck at schema version 1 is refused, not silently migrated to 2."""
    path = tmp_path / "r.sqlite"
    v1_store = Store(path)
    v1_store.connection.executescript(
        f"BEGIN;\n{store_schema.MIGRATIONS[0]}\n"
        "INSERT INTO schema_version (version) VALUES (1);\nCOMMIT;"
    )
    v1_store.close()
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_STORE", str(path))

    result_store, error = _open_store(Settings())

    assert result_store is None
    assert error is not None
    assert "schema version" in error

    # Confirm _open_store never called migrate(): the file is still at version 1.
    check = Store(path)
    try:
        assert check.schema_version() == 1
    finally:
        check.close()


def test_open_store_pulls_an_s3_location_to_a_local_work_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review item 5f: `NTSB_STORE=s3://...` is pulled to a temporary file under
    `NTSB_DATA_DIR` and opened read-only from there -- the S3 object itself is never opened or
    written to. No test exercised this branch before this fix."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_STORE", "s3://a-bucket/recorder.sqlite")

    pulled: list[tuple[Location, Path]] = []

    def _fake_pull(location: Location, local: Path, **_: object) -> None:
        pulled.append((location, local))
        setup = Store(local)
        setup.migrate()
        setup.close()

    monkeypatch.setattr("scripts.recorder_report.pull", _fake_pull)

    result_store, error = _open_store(Settings())

    assert error is None
    assert result_store is not None
    assert pulled == [
        (Location("s3://a-bucket/recorder.sqlite"), tmp_path / "recorder-report-work.sqlite")
    ]
    result_store.close()


def test_main_prints_an_empty_report_and_creates_no_file_when_no_store_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "does-not-exist.sqlite"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_STORE", str(store_path))

    exit_code = main([])

    assert exit_code == 0
    assert "nights recorded (every run, finished or not): 0" in capsys.readouterr().out
    assert not store_path.exists()


def test_main_refuses_a_mismatched_store_with_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "r.sqlite"
    v1_store = Store(path)
    v1_store.connection.executescript(
        f"BEGIN;\n{store_schema.MIGRATIONS[0]}\n"
        "INSERT INTO schema_version (version) VALUES (1);\nCOMMIT;"
    )
    v1_store.close()
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_STORE", str(path))

    exit_code = main([])

    assert exit_code == 1
    assert "schema version" in capsys.readouterr().err


def test_main_reads_a_real_store_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "r.sqlite"
    setup = Store(path)
    setup.migrate()
    setup.begin_run(started_at=RUN1, commit_sha="a" * 7, dirty=False)
    setup.close()
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_STORE", str(path))

    exit_code = main([])

    assert exit_code == 0
    assert "nights recorded (every run, finished or not): 1" in capsys.readouterr().out


def test_main_reads_a_store_whose_path_has_special_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task 11 fix round 3, MINOR: '?'/'#' in NTSB_STORE must not break the read-only open."""
    path = tmp_path / "r?eport#1.sqlite"
    setup = Store(path)
    setup.migrate()
    setup.begin_run(started_at=RUN1, commit_sha="a" * 7, dirty=False)
    setup.close()
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_STORE", str(path))

    exit_code = main([])

    assert exit_code == 0
    assert "nights recorded (every run, finished or not): 1" in capsys.readouterr().out
    # No stray file (e.g. a file literally named "r", from a URI truncated at the first
    # unescaped '?') -- only the intended path and its ordinary WAL-mode side files.
    expected = {path.name, path.name + "-wal", path.name + "-shm", path.name + "-journal"}
    after = {p.name for p in tmp_path.iterdir()}
    assert after <= expected
