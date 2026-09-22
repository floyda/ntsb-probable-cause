"""The case side of the nightly run: snapshots, status events and the preliminary narrative.

Every record passes through :func:`~ntsb_probable_cause.records.split.split_record`, the
project's one split (CLAUDE.md rule 1; decisions 0013, 0016), before anything is compared or
written. Only :class:`~ntsb_probable_cause.records.evidence.Evidence` values ever reach the
store; the synthesis and verdict roles a raw record carries are dropped the moment the record
is split (spec S2.5 §5.2, §7).
"""

import json
import logging
from collections.abc import Mapping
from datetime import date, timedelta

from pydantic import BaseModel

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.paths import resolve_path
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.splits import GA_REGULATION, ONGOING_STATUS
from ntsb_probable_cause.store import CaseRow, Store

_log = logging.getLogger(__name__)

TAIL_DAYS = 30
REGULATION_PATH = "aircrafts[0].ownerOperators[0].regulationFlightConductedUnder"
NOT_RETURNED_STATUS = "not returned"

# The raw record's own field, capitalised, as the NTSB API returns it -- not
# ``sources.MODE_AVIATION``, which is the lowercase query parameter a request sends.
_AVIATION_MODE = "Aviation"

# Handled outside the per-field snapshot loop: the docket roles are Task 8's tables, and the
# preliminary narrative has its own history table (rule 6) so its deletion at closure is never
# read as a change.
_SKIPPED_ROLES = frozenset(
    {EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS, EvidenceRole.PRELIM_NARRATIVE}
)

# "Empty" (spec §4.1): the regulation has not been recorded yet. `resolve_path` returns `None`
# for a missing field; an empty string is treated the same way, belt and suspenders.
_EMPTY_REGULATION = frozenset({None, ""})


class CaseOutcome(BaseModel, frozen=True):
    """What one call to :func:`observe_case` did."""

    mkey: int
    changed: bool
    failed: str | None


def is_watchable(raw: Mapping[str, object]) -> bool:
    """A case the recorder watches: aviation, ``Ongoing``, regulation 091 or empty (spec §4.1)."""
    if raw.get("mode") != _AVIATION_MODE:
        return False
    if raw.get("completionStatus") != ONGOING_STATUS:
        return False
    regulation = resolve_path(raw, REGULATION_PATH)
    return regulation in _EMPTY_REGULATION or regulation == GA_REGULATION


def _parse_event_date(raw: Mapping[str, object]) -> date | None:
    """``eventDate``, read the way ``data/build.py``'s ``_exclusion`` does. ``None`` if unusable."""
    try:
        return date.fromisoformat(str(raw.get("eventDate"))[:10])
    except ValueError:
        return None


def _regulation_of(raw: Mapping[str, object]) -> str | None:
    regulation = resolve_path(raw, REGULATION_PATH)
    return regulation if isinstance(regulation, str) else None


def _apply_status(  # noqa: PLR0913 -- one parameter per rule 4's inputs and outputs.
    store: Store,
    mkey: int,
    *,
    old_status: str | None,
    new_status: str,
    watch_until: str | None,
    absent: int | None,
    run_id: int,
    today: date,
) -> tuple[str | None, bool]:
    """Write a status_events row if the status changed; return ``(watch_until, wrote)``.

    Controller resolution 2: the tail is set only on the transition away from ``Ongoing``,
    never refreshed on a later night, and cleared on a return to ``Ongoing``.
    """
    if old_status == new_status:
        return watch_until, False
    store.add_status_event(
        mkey, old=old_status, new=new_status, absent_run=absent, present_run=run_id, run_id=run_id
    )
    if new_status == ONGOING_STATUS:
        watch_until = None
    elif old_status == ONGOING_STATUS:
        watch_until = (today + timedelta(days=TAIL_DAYS)).isoformat()
    return watch_until, True


def _apply_fields(
    store: Store, mkey: int, evidence: Evidence, *, absent: int | None, run_id: int
) -> int:
    """Write one ``field_snapshots`` row per changed, non-skipped role; return how many."""
    previous = store.latest_snapshots(mkey)
    count = 0
    for role, value in evidence.role_values().items():
        if role in _SKIPPED_ROLES:
            continue
        value_json = json.dumps(value, sort_keys=True)
        if previous.get(role.value) == value_json:
            continue
        store.add_field_snapshot(
            mkey,
            role=role.value,
            value_json=value_json,
            absent_run=absent,
            present_run=run_id,
            run_id=run_id,
        )
        count += 1
    return count


def _apply_prelim(
    store: Store, mkey: int, prelim: str | None, *, absent: int | None, run_id: int
) -> bool:
    """Write a ``prelim_narratives`` row if new or changed; return whether it was written.

    Rule 6: a deletion (the API clears the preliminary narrative at closure) is never written
    -- the status event already says the case closed.
    """
    if not prelim or prelim == store.latest_prelim(mkey):
        return False
    store.add_prelim(mkey, text=prelim, absent_run=absent, present_run=run_id, run_id=run_id)
    return True


def observe_case(
    store: Store, raw: Mapping[str, object], *, run_id: int, today: date
) -> CaseOutcome:
    """Split one record, diff it against the case's last snapshot, and write what changed.

    Every write this call makes lands in one transaction: a case is recorded whole or not at
    all. Nothing is written if ``raw`` has no usable ``mKey`` or ``eventDate``, or if
    :func:`~ntsb_probable_cause.records.split.split_record` raises.
    """
    mkey = raw.get("mKey")
    if not isinstance(mkey, int):
        _log.warning("case mkey=%d failed=%s", 0, "no mKey")
        return CaseOutcome(mkey=0, changed=False, failed="no mKey")

    event_date = _parse_event_date(raw)
    if event_date is None:
        _log.warning("case mkey=%d failed=%s", mkey, "no event date")
        return CaseOutcome(mkey=mkey, changed=False, failed="no event date")

    try:
        evidence, _synthesis, _verdict = split_record(raw)
    except (LeakageError, ValueError) as error:
        # The exception CLASS NAME only, never the message: a LeakageError's message quotes
        # the leaked sentence, and this line -- and the CaseOutcome it returns -- must not.
        failed = type(error).__name__
        _log.warning("case mkey=%d failed=%s", mkey, failed)
        return CaseOutcome(mkey=mkey, changed=False, failed=failed)

    status_value = raw.get("completionStatus")
    new_status = status_value if isinstance(status_value, str) else ""

    existing = store.get_case(mkey)
    absent = existing.last_case_run if existing else None
    old_status = existing.status if existing else None
    watch_until = existing.watch_until if existing else None

    wrote: list[str] = []

    with store.transaction():
        watch_until, status_written = _apply_status(
            store,
            mkey,
            old_status=old_status,
            new_status=new_status,
            watch_until=watch_until,
            absent=absent,
            run_id=run_id,
            today=today,
        )
        if status_written:
            wrote.append("1 status event")

        field_count = _apply_fields(store, mkey, evidence, absent=absent, run_id=run_id)
        if field_count:
            noun = "field snapshot" if field_count == 1 else "field snapshots"
            wrote.append(f"{field_count} {noun}")

        if _apply_prelim(store, mkey, evidence.prelim_narrative, absent=absent, run_id=run_id):
            wrote.append("1 prelim narrative")

        regulation = _regulation_of(raw)
        watched = is_watchable(raw) or (
            watch_until is not None and watch_until >= today.isoformat()
        )
        if regulation and regulation != GA_REGULATION:
            _log.info("case mkey=%d dropped: regulation=%s", mkey, regulation)

        store.upsert_case(
            CaseRow(
                mkey=mkey,
                ntsb_number=str(raw.get("ntsbNumber", "")),
                event_date=event_date.isoformat(),
                regulation=regulation,
                status=new_status,
                first_seen_run=existing.first_seen_run if existing else run_id,
                last_seen_run=run_id,
                last_case_run=run_id,
                last_docket_run=existing.last_docket_run if existing else None,
                watch_until=watch_until,
                watched=watched,
            )
        )

    changed = bool(wrote)
    _log.info("case mkey=%d changed=%s wrote=%s", mkey, changed, ", ".join(wrote) or "nothing")
    return CaseOutcome(mkey=mkey, changed=changed, failed=None)


def mark_not_returned(store: Store, mkey: int, *, run_id: int) -> None:
    """Record that a previously watched case's API record no longer appears in its event month.

    Spec §5.2/§7: a case the API stops returning is recorded the same way as any other status
    change, and nothing already written is touched or deleted. Idempotent: a case already
    marked ``not returned`` writes nothing on a later night.
    """
    existing = store.get_case(mkey)
    if existing is None or existing.status == NOT_RETURNED_STATUS:
        return

    with store.transaction():
        store.add_status_event(
            mkey,
            old=existing.status,
            new=NOT_RETURNED_STATUS,
            absent_run=existing.last_case_run,
            present_run=run_id,
            run_id=run_id,
        )
        store.upsert_case(
            existing.model_copy(
                update={"status": NOT_RETURNED_STATUS, "last_seen_run": run_id, "watched": False}
            )
        )

    _log.info("case mkey=%d changed=%s wrote=%s", mkey, True, "1 status event")
