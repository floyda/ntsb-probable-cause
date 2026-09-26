"""The case side of the nightly run (spec S2.5 §5.2, §7; Task 7, fix round 1)."""

import copy
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from tests.boundary import as_ongoing

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.paths import overlaps
from ntsb_probable_cause.recorder.cases import (
    REGULATION_PATH,
    _is_empty,
    is_watchable,
    mark_not_returned,
    observe_case,
)
from ntsb_probable_cause.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = Store(tmp_path / "r.sqlite")
    opened.migrate()
    yield opened
    opened.close()


@pytest.fixture
def ongoing_record(record_fixtures: list[dict[str, object]]) -> dict[str, object]:
    """A deep copy of a closed dev-split record, edited to read like a live one.

    See ``tests/boundary.py:as_ongoing`` for what is stripped and added.
    """
    raw = next(
        r for r in record_fixtures if isinstance(r.get("mKey"), int) and r.get("mode") == "Aviation"
    )
    return as_ongoing(
        raw,
        prelim_text="Preliminary information indicates the flight departed on a local flight.",
    )


def _mkey(record: dict[str, object]) -> int:
    value = record["mKey"]
    assert isinstance(value, int)
    return value


def _with_regulation(record: dict[str, object], value: str | None) -> dict[str, object]:
    """A deep copy of ``record`` with its regulation field set to ``value``."""
    edited = copy.deepcopy(record)
    aircrafts = edited["aircrafts"]
    assert isinstance(aircrafts, list)
    owner_operators = aircrafts[0]["ownerOperators"]
    assert isinstance(owner_operators, list)
    owner_operators[0]["regulationFlightConductedUnder"] = value
    return edited


def test_first_sight_writes_every_field_and_a_status_event(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    out = observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    assert out.changed
    assert out.failed is None
    snaps = store.latest_snapshots(out.mkey)
    assert "engine_type" in snaps
    assert "docket_listing" not in snaps
    events = store.connection.execute("select old_status,new_status from status_events").fetchall()
    assert events == [(None, "Ongoing")]


def test_unchanged_record_writes_nothing(store: Store, ongoing_record: dict[str, object]) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    before = store.connection.execute("select count(*) from field_snapshots").fetchone()[0]
    out = observe_case(store, ongoing_record, run_id=2, today=date(2026, 10, 2))
    after = store.connection.execute("select count(*) from field_snapshots").fetchone()[0]
    assert not out.changed
    assert before == after


def test_changed_field_writes_one_row_with_the_interval(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    changed = dict(ongoing_record)
    changed["highestInjuryLevel"] = "Fatal"
    observe_case(store, changed, run_id=3, today=date(2026, 10, 3))
    row = store.connection.execute(
        "select absent_run, present_run from field_snapshots where role='injury_level' "
        "order by id desc limit 1"
    ).fetchone()
    assert row == (1, 3)


def test_closure_sets_the_tail_and_keeps_the_prelim(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    closed = dict(ongoing_record)
    closed["completionStatus"] = "Completed"
    closed["narratives"] = [{}]  # the API deletes the prelim at closure
    observe_case(store, closed, run_id=2, today=date(2026, 10, 2))
    case = store.get_case(_mkey(closed))
    assert case is not None
    assert case.status == "Completed"
    assert case.watch_until == "2026-11-01"
    assert store.latest_prelim(case.mkey) is not None


def test_leakage_error_is_a_failed_outcome(
    store: Store, ongoing_record: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ntsb_probable_cause.recorder.cases.split_record",
        lambda *_a, **_k: (_ for _ in ()).throw(LeakageError("x", leaks=[])),
    )
    out = observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    assert out.failed == "LeakageError"


def test_value_error_from_the_split_is_a_failed_outcome(store: Store) -> None:
    """A record split raises ValueError when it has no ntsbNumber (records/split.py:24)."""
    raw = {"mKey": 999, "eventDate": "2026-01-01", "completionStatus": "Ongoing"}
    out = observe_case(store, raw, run_id=1, today=date(2026, 10, 1))
    assert out.failed == "ValueError"
    assert store.get_case(999) is None


def test_no_mkey_is_a_failed_outcome_without_writing(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Controller resolution 4: `mKey` must be an `int`, else `failed="no mKey"`."""
    raw = dict(ongoing_record)
    del raw["mKey"]
    out = observe_case(store, raw, run_id=1, today=date(2026, 10, 1))
    assert out.failed == "no mKey"
    assert not out.changed
    assert store.connection.execute("select count(*) from cases").fetchone()[0] == 0


@pytest.mark.parametrize("bad_date", [None, "", "not-a-date"])
def test_no_event_date_is_a_failed_outcome_without_writing(
    store: Store, ongoing_record: dict[str, object], bad_date: str | None
) -> None:
    """Controller resolution 3: an unparsable `eventDate` fails closed, before any write.

    An empty ``event_date`` would sort first in ``MIN(substr(event_date,1,7))`` and make every
    later night's month window raise (the reason this check exists at all).
    """
    raw = dict(ongoing_record)
    raw["eventDate"] = bad_date
    out = observe_case(store, raw, run_id=1, today=date(2026, 10, 1))
    assert out.failed == "no event date"
    assert not out.changed
    assert store.connection.execute("select count(*) from cases").fetchone()[0] == 0


def test_missing_event_date_key_is_also_a_failed_outcome(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    raw = dict(ongoing_record)
    del raw["eventDate"]
    out = observe_case(store, raw, run_id=1, today=date(2026, 10, 1))
    assert out.failed == "no event date"


@pytest.mark.parametrize("bad_status", [None, "", 42])
def test_no_status_is_a_failed_outcome_without_writing(
    store: Store, ongoing_record: dict[str, object], bad_status: object
) -> None:
    """Fix round 1, Minor: a missing/empty/non-string `completionStatus` fails closed.

    Before this fix a missing status silently became ``""`` and was written as the case's
    status, rather than being treated as unusable input like a missing `mKey` or `eventDate`.
    """
    raw = dict(ongoing_record)
    raw["completionStatus"] = bad_status
    out = observe_case(store, raw, run_id=1, today=date(2026, 10, 1))
    assert out.failed == "no status"
    assert not out.changed
    assert store.connection.execute("select count(*) from cases").fetchone()[0] == 0


def test_missing_status_key_is_also_a_failed_outcome(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    raw = dict(ongoing_record)
    del raw["completionStatus"]
    out = observe_case(store, raw, run_id=1, today=date(2026, 10, 1))
    assert out.failed == "no status"


def test_is_watchable_true_for_the_ongoing_aviation_fixture(
    ongoing_record: dict[str, object],
) -> None:
    assert is_watchable(ongoing_record)


def test_is_watchable_true_when_the_regulation_is_not_yet_recorded(
    ongoing_record: dict[str, object],
) -> None:
    assert is_watchable(_with_regulation(ongoing_record, None))


def test_is_watchable_false_for_a_non_aviation_mode(ongoing_record: dict[str, object]) -> None:
    other = dict(ongoing_record)
    other["mode"] = "Railroad"
    assert not is_watchable(other)


def test_is_watchable_false_when_not_ongoing(ongoing_record: dict[str, object]) -> None:
    other = dict(ongoing_record)
    other["completionStatus"] = "Completed"
    assert not is_watchable(other)


def test_is_watchable_false_for_a_non_part_91_regulation(ongoing_record: dict[str, object]) -> None:
    assert not is_watchable(_with_regulation(ongoing_record, "135"))


def test_regulation_path_does_not_overlap_withheld_subtrees() -> None:
    """The regulation column is read straight from the raw record, not via ``Evidence``.

    So it must not be, or read through, a withheld path. Uses the same ``paths.overlaps``
    helper ``fields.check_evidence_paths`` uses for the same purpose, rather than a one-off
    script (fix round 1, Minor).
    """
    for subtree in fields.WITHHELD_SUBTREES:
        assert not overlaps(REGULATION_PATH, subtree)


def test_a_case_dropped_by_regulation_keeps_its_row_and_history(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Rule 7: a case whose regulation is no longer 091 or empty stops being watched.

    Its row and history stay -- only the ``watched`` flag changes -- so it drops out of
    ``watched_mkeys`` (Task 4) without losing anything already recorded.
    """
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)
    assert mkey in store.watched_mkeys(today="2026-10-01")

    dropped = _with_regulation(ongoing_record, "135")
    observe_case(store, dropped, run_id=2, today=date(2026, 10, 2))

    assert mkey not in store.watched_mkeys(today="2026-10-02")
    case = store.get_case(mkey)
    assert case is not None
    assert case.regulation == "135"
    assert case.watched is False
    # The field snapshots written on the first call are untouched.
    assert "engine_type" in store.latest_snapshots(mkey)


def test_dropped_by_regulation_then_closed_does_not_readmit_the_case(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Important 4: closing a regulation-dropped case must not put it back in the watch set.

    ``_apply_status`` sets a fresh ``watch_until`` for any transition away from ``Ongoing``,
    including this one -- the tail formula must gate on whether the case was actually watched
    beforehand, or a case dropped for its regulation would reappear in ``watched_mkeys`` for
    30 days the moment it closes, contradicting rule 7 ("stops being watched").
    """
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    dropped = _with_regulation(ongoing_record, "135")
    observe_case(store, dropped, run_id=2, today=date(2026, 10, 2))
    after_drop = store.get_case(mkey)
    assert after_drop is not None
    assert after_drop.watched is False

    closed = _with_regulation(ongoing_record, "135")
    closed["completionStatus"] = "Completed"
    observe_case(store, closed, run_id=3, today=date(2026, 10, 3))

    case = store.get_case(mkey)
    assert case is not None
    assert case.status == "Completed"
    assert case.watch_until is not None  # _apply_status still records a tail date...
    assert case.watched is False  # ...but it does not count, because the case was not watched.
    assert mkey not in store.watched_mkeys(today="2026-10-03")


def test_dropped_regulation_is_logged_once_not_every_night(
    store: Store, ongoing_record: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    """Fix round 1, Minor: the drop is logged on the watched-to-unwatched transition only."""
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    dropped = _with_regulation(ongoing_record, "135")

    with caplog.at_level(logging.INFO, logger="ntsb_probable_cause.recorder.cases"):
        observe_case(store, dropped, run_id=2, today=date(2026, 10, 2))
        observe_case(store, dropped, run_id=3, today=date(2026, 10, 3))

    drop_lines = [r for r in caplog.records if "dropped: regulation" in r.getMessage()]
    assert len(drop_lines) == 1


def _regulation_events(store: Store) -> list[tuple[str | None, str | None, bool]]:
    rows = store.connection.execute(
        "SELECT old, new, was_watched FROM regulation_events ORDER BY id"
    ).fetchall()
    return [(old, new, bool(watched)) for old, new, watched in rows]


def test_regulation_event_written_on_a_real_change(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Task 11 fix round 1, IMPORTANT 7: 091 -> 135 is a real change and gets one row."""
    observe_case(store, _with_regulation(ongoing_record, "091"), run_id=1, today=date(2026, 10, 1))
    observe_case(store, _with_regulation(ongoing_record, "135"), run_id=2, today=date(2026, 10, 2))
    assert _regulation_events(store) == [("091", "135", True)]


def test_regulation_event_written_from_empty_to_recorded(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, _with_regulation(ongoing_record, None), run_id=1, today=date(2026, 10, 1))
    observe_case(store, _with_regulation(ongoing_record, "091"), run_id=2, today=date(2026, 10, 2))
    assert _regulation_events(store) == [(None, "091", True)]


def test_regulation_event_written_from_recorded_to_empty(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, _with_regulation(ongoing_record, "091"), run_id=1, today=date(2026, 10, 1))
    observe_case(store, _with_regulation(ongoing_record, None), run_id=2, today=date(2026, 10, 2))
    assert _regulation_events(store) == [("091", None, True)]


def test_no_regulation_event_for_an_unchanged_value(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, _with_regulation(ongoing_record, "091"), run_id=1, today=date(2026, 10, 1))
    observe_case(store, _with_regulation(ongoing_record, "091"), run_id=2, today=date(2026, 10, 2))
    assert _regulation_events(store) == []


def test_no_regulation_event_between_the_two_empty_spellings(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """``None`` and ``""`` both mean "not recorded"; a change between them is not a change."""
    observe_case(store, _with_regulation(ongoing_record, None), run_id=1, today=date(2026, 10, 1))
    observe_case(store, _with_regulation(ongoing_record, ""), run_id=2, today=date(2026, 10, 2))
    assert _regulation_events(store) == []


def test_no_regulation_event_on_first_sight(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, _with_regulation(ongoing_record, "091"), run_id=1, today=date(2026, 10, 1))
    assert _regulation_events(store) == []


def test_mark_not_returned_writes_no_regulation_event(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mark_not_returned(store, _mkey(ongoing_record), run_id=2, today=date(2026, 10, 2))
    assert _regulation_events(store) == []


def test_field_with_no_value_is_silent_on_first_sight_then_writes_once_set(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Important 2: spec §5.2 governs -- "one field_snapshots row per field that has a value".

    ``weather_metar`` is unset on the picked fixture. Night 1 (unset) writes no row for it, so
    Task 11's arrival query cannot read it as "present from the first watch". Night 2 (set)
    writes exactly one row, with the interval the field actually appeared in.
    """
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    assert "weather_metar" not in store.latest_snapshots(_mkey(ongoing_record))

    changed = copy.deepcopy(ongoing_record)
    weather = changed["weatherConditions"]
    assert isinstance(weather, list)
    weather[0]["metar"] = "KXYZ 011200Z 00000KT 10SM CLR 15/05 A3000"
    observe_case(store, changed, run_id=2, today=date(2026, 10, 2))

    rows = store.connection.execute(
        "select absent_run, present_run from field_snapshots where role='weather_metar'"
    ).fetchall()
    assert rows == [(1, 2)]


def test_a_value_that_becomes_none_writes_a_null_row(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Important 2: once a role has a stored row, a later None is a real change and is written.

    Nothing already recorded is deleted (spec §8), so the row itself is the record of the
    value having gone missing.
    """
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    assert "engine_type" in store.latest_snapshots(_mkey(ongoing_record))

    changed = copy.deepcopy(ongoing_record)
    aircrafts = changed["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["engines"][0]["engineType"] = None
    observe_case(store, changed, run_id=2, today=date(2026, 10, 2))

    row = store.connection.execute(
        "select absent_run, present_run, value_json from field_snapshots "
        "where role='engine_type' order by id desc limit 1"
    ).fetchone()
    assert row == (1, 2, "null")


def test_mark_not_returned_records_a_status_event_and_sets_the_tail(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Important 3: "not returned" is a departure from Ongoing like any other and gets a tail."""
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    mark_not_returned(store, mkey, run_id=2, today=date(2026, 10, 2))

    case = store.get_case(mkey)
    assert case is not None
    assert case.status == "not returned"
    assert case.watch_until == "2026-11-01"
    assert case.watched is True  # the tail is active and the case was watched beforehand
    row = store.connection.execute(
        "select old_status, new_status from status_events order by id desc limit 1"
    ).fetchone()
    assert row == ("Ongoing", "not returned")


def test_mark_not_returned_does_not_touch_last_seen_run_or_last_case_run(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)
    before = store.get_case(mkey)
    assert before is not None

    mark_not_returned(store, mkey, run_id=7, today=date(2026, 10, 5))

    after = store.get_case(mkey)
    assert after is not None
    assert after.last_seen_run == before.last_seen_run == 1
    assert after.last_case_run == before.last_case_run == 1


def test_mark_not_returned_after_the_tail_expires_is_not_watched(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    mark_not_returned(store, mkey, run_id=2, today=date(2026, 10, 2))
    after_mark = store.get_case(mkey)
    assert after_mark is not None
    assert after_mark.watched is True
    assert mkey in store.watched_mkeys(today="2026-11-01")
    assert mkey not in store.watched_mkeys(today="2026-11-02")


def test_mark_not_returned_on_an_already_closed_case_does_not_refresh_the_tail(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """A case already Completed (not Ongoing) when mark_not_returned is called.

    It keeps whatever tail it already had rather than getting a fresh one -- mirrors
    ``_apply_status``'s "not refreshed" rule for every other non-``Ongoing`` status
    (mark_not_returned's own ``if existing.status == ONGOING_STATUS`` branch, the case where
    it is False).
    """
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)
    closed = dict(ongoing_record)
    closed["completionStatus"] = "Completed"
    observe_case(store, closed, run_id=2, today=date(2026, 10, 2))
    case_after_close = store.get_case(mkey)
    assert case_after_close is not None
    original_tail = case_after_close.watch_until
    assert original_tail == "2026-11-01"

    mark_not_returned(store, mkey, run_id=3, today=date(2026, 10, 20))

    case = store.get_case(mkey)
    assert case is not None
    assert case.status == "not returned"
    assert case.watch_until == original_tail


def test_mark_not_returned_is_idempotent(store: Store, ongoing_record: dict[str, object]) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    mark_not_returned(store, mkey, run_id=2, today=date(2026, 10, 2))
    before = store.connection.execute("select count(*) from status_events").fetchone()[0]
    mark_not_returned(store, mkey, run_id=3, today=date(2026, 10, 3))
    after = store.connection.execute("select count(*) from status_events").fetchone()[0]
    assert before == after


def test_not_returned_then_completed_keeps_the_tail(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """Important 3: a "not returned" case that later reappears as Completed keeps its tail.

    ``_apply_status`` only sets a fresh tail on a transition away from ``Ongoing`` (controller
    resolution 2); "not returned" to "Completed" is a transition between two non-``Ongoing``
    statuses, so the tail ``mark_not_returned`` already set is left untouched rather than being
    cleared or overwritten -- checked directly against the value `mark_not_returned` set.
    """
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    mark_not_returned(store, mkey, run_id=2, today=date(2026, 10, 2))
    after_mark = store.get_case(mkey)
    assert after_mark is not None
    tail_after_not_returned = after_mark.watch_until
    assert tail_after_not_returned == "2026-11-01"

    completed = dict(ongoing_record)
    completed["completionStatus"] = "Completed"
    observe_case(store, completed, run_id=3, today=date(2026, 10, 6))

    case = store.get_case(mkey)
    assert case is not None
    assert case.status == "Completed"
    assert case.watch_until == tail_after_not_returned


def test_mark_not_returned_after_reappearing_as_ongoing_gets_a_fresh_tail(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """A case that reappears as Ongoing has its tail cleared there (`_apply_status`); the next

    vanishing sets a genuinely fresh tail, not the one it had before it reappeared -- the
    `mark_not_returned` docstring's own claim, checked directly.
    """
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    mark_not_returned(store, mkey, run_id=2, today=date(2026, 10, 2))
    first = store.get_case(mkey)
    assert first is not None
    assert first.watch_until == "2026-11-01"

    observe_case(store, ongoing_record, run_id=3, today=date(2026, 10, 10))
    reappeared = store.get_case(mkey)
    assert reappeared is not None
    assert reappeared.status == "Ongoing"
    assert reappeared.watch_until is None

    mark_not_returned(store, mkey, run_id=4, today=date(2026, 10, 20))
    second = store.get_case(mkey)
    assert second is not None
    assert second.watch_until == "2026-11-19"
    assert second.watch_until != first.watch_until


def test_mark_not_returned_on_an_unknown_case_does_nothing(store: Store) -> None:
    mark_not_returned(store, 999999, run_id=1, today=date(2026, 10, 1))
    assert store.get_case(999999) is None


@pytest.mark.parametrize("empty_value", [None, "", ()])
def test_is_empty_treats_none_blank_string_and_empty_tuple_as_empty(
    empty_value: str | tuple[str, ...] | None,
) -> None:
    """Fix round 2: the decision documented in `_is_empty`'s docstring, exercised directly.

    The `fields.py` extractors never actually emit "" or () themselves (they already normalise
    both to None), so only the `None` case is reachable through a real evidence value today --
    this test is what proves the other two branches do what the docstring says regardless.
    """
    assert _is_empty(empty_value)


@pytest.mark.parametrize("non_empty_value", ["REC", 14000.0, ("Private",), ("a", "b")])
def test_is_empty_is_false_for_a_real_value(
    non_empty_value: str | float | tuple[str, ...],
) -> None:
    assert not _is_empty(non_empty_value)


# --- new_case_absent_run (final review item 2; Andy's decision 2026-09-23) -----------------


def test_new_case_absent_run_becomes_the_first_sight_absent_side(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """A case never seen before, whose `new_case_absent_run` is given (an earlier run cleanly
    fetched its event month and did not find it), gets a TRUE arrival -- `absent_run` on its
    first-sight field snapshots and status event, not `None`."""
    out = observe_case(
        store, ongoing_record, run_id=5, today=date(2026, 10, 5), new_case_absent_run=2
    )
    assert out.changed
    assert out.failed is None

    snapshot_absent = store.connection.execute(
        "SELECT DISTINCT absent_run FROM field_snapshots WHERE mkey=?", (out.mkey,)
    ).fetchall()
    assert snapshot_absent == [(2,)]

    status_absent = store.connection.execute(
        "SELECT absent_run FROM status_events WHERE mkey=?", (out.mkey,)
    ).fetchone()
    assert status_absent == (2,)


def test_new_case_absent_run_none_is_a_first_sight_observation(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """The default (no earlier run ever fetched the month cleanly, or this is the store's very
    first night): `absent_run` stays `None`, exactly as before this parameter existed."""
    out = observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    snapshot_absent = store.connection.execute(
        "SELECT DISTINCT absent_run FROM field_snapshots WHERE mkey=?", (out.mkey,)
    ).fetchall()
    assert snapshot_absent == [(None,)]


def test_new_case_absent_run_is_ignored_for_an_already_known_case(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    """A case the store already has a row for uses its OWN `last_case_run`, never
    `new_case_absent_run` -- the parameter only ever applies to a genuinely new mkey."""
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    changed = dict(ongoing_record)
    changed["highestInjuryLevel"] = "Fatal"

    observe_case(store, changed, run_id=3, today=date(2026, 10, 3), new_case_absent_run=999)

    row = store.connection.execute(
        "SELECT absent_run FROM field_snapshots WHERE role='injury_level' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row == (1,)  # the case's own last_case_run (1), never the passed-in 999


# --- verbose diff logging (final review item 3) --------------------------------------------


def test_verbose_logs_the_differing_role_name_never_the_value(
    store: Store, ongoing_record: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    changed = dict(ongoing_record)
    changed["highestInjuryLevel"] = "Fatal"

    with caplog.at_level(logging.DEBUG, logger="ntsb_probable_cause.recorder.cases"):
        observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
        observe_case(store, changed, run_id=2, today=date(2026, 10, 2))

    diff_lines = [r.getMessage() for r in caplog.records if "field differed" in r.getMessage()]
    assert any("role=injury_level" in line for line in diff_lines)
    assert not any("Fatal" in line for line in diff_lines)
