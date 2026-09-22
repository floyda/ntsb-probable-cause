"""The case side of the nightly run (spec S2.5 §5.2, §7; Task 7)."""

import copy
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.recorder.cases import (
    REGULATION_PATH,
    TAIL_DAYS,
    is_watchable,
    mark_not_returned,
    observe_case,
)
from ntsb_probable_cause.store import Store

# fields.WITHHELD_SUBTREES's narrative keys, less the docket roles, which do not exist on a raw
# API record at all (fields.py:244-249) and so need no stripping.
_WITHHELD_NARRATIVE_KEYS = ("concatenatedFactualNarrative", "analysisNarrative", "probableCause")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = Store(tmp_path / "r.sqlite")
    opened.migrate()
    yield opened
    opened.close()


@pytest.fixture
def ongoing_record(record_fixtures: list[dict[str, object]]) -> dict[str, object]:
    """A deep copy of a closed dev-split record, edited to read like a live one.

    ``completionStatus`` becomes ``Ongoing`` and every ``fields.WITHHELD_SUBTREES`` path is
    stripped, so the record carries no synthesis or verdict content -- the shape a case
    actually has while it is open. A preliminary narrative is added: none of the fixtures'
    closed records still carry one (the API clears it at closure, rule 6), but an open case
    needs one for the prelim-history tests.
    """
    raw = next(
        r for r in record_fixtures if isinstance(r.get("mKey"), int) and r.get("mode") == "Aviation"
    )
    record = copy.deepcopy(raw)
    record["completionStatus"] = "Ongoing"

    narratives = record.get("narratives")
    assert isinstance(narratives, list)
    assert narratives
    narrative = narratives[0]
    assert isinstance(narrative, dict)
    for key in _WITHHELD_NARRATIVE_KEYS:
        narrative.pop(key, None)
    narrative["prelimNarrative"] = (
        "Preliminary information indicates the flight departed on a local flight."
    )

    aircrafts = record.get("aircrafts")
    assert isinstance(aircrafts, list)
    assert aircrafts
    for aircraft in aircrafts:
        assert isinstance(aircraft, dict)
        aircraft.pop("events", None)
        aircraft.pop("findings", None)

    record.pop("richNarratives", None)
    return record


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


def test_regulation_path_matches_the_module_constant() -> None:
    assert REGULATION_PATH == "aircrafts[0].ownerOperators[0].regulationFlightConductedUnder"


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


def test_mark_not_returned_records_a_status_event_and_stops_watching(
    store: Store, ongoing_record: dict[str, object]
) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    mark_not_returned(store, mkey, run_id=2)

    case = store.get_case(mkey)
    assert case is not None
    assert case.status == "not returned"
    assert case.watched is False
    row = store.connection.execute(
        "select old_status, new_status from status_events order by id desc limit 1"
    ).fetchone()
    assert row == ("Ongoing", "not returned")


def test_mark_not_returned_is_idempotent(store: Store, ongoing_record: dict[str, object]) -> None:
    observe_case(store, ongoing_record, run_id=1, today=date(2026, 10, 1))
    mkey = _mkey(ongoing_record)

    mark_not_returned(store, mkey, run_id=2)
    before = store.connection.execute("select count(*) from status_events").fetchone()[0]
    mark_not_returned(store, mkey, run_id=3)
    after = store.connection.execute("select count(*) from status_events").fetchone()[0]
    assert before == after


def test_mark_not_returned_on_an_unknown_case_does_nothing(store: Store) -> None:
    mark_not_returned(store, 999999, run_id=1)
    assert store.get_case(999999) is None


def test_tail_days_is_thirty() -> None:
    assert TAIL_DAYS == 30
