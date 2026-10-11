"""One cloud night: the morning on the bucket's mirror, and the steps around it (S4 spec 5, 7).

``run_night`` is library code; every outside effect comes in through :class:`NightDeps`, so a
test replaces each with a fake. In order:

1. Claim the day with the conditional marker ``nights/<date>/started``. A second task on the
   same day stops here, before the bucket is read or the store is opened (decision 0171).
2. Pull the bucket's ``runs/``, ``scores/`` and ``nights/`` into the local mirror.
3. Run the morning (``morning.run_morning``) on the mirror. The sync driver tells an observer
   before the run's first request and after every reply; the observer copies the open run
   folder to the bucket, so a night killed at any point (the task's 3-hour limit) leaves what
   the next night's resume needs: the inputs before the first request, then every reply
   (Review Focus 1). A refusal (``LiveRefusal``) or a fetch error that escapes the morning
   stops it; its kind is the alert, and the steps below that need no store still run.
4. Later scores: each coded case still waiting for the NTSB's codes is fetched again and, when
   the codes are there, scored into ``scores/<date>.jsonl`` (decision 0174). One bad record is
   counted by kind and the others go on.
5. Build the export from the mirror and push it to ``export/board-1/``; a damaged mirror
   (``ConfigurationError``) is the alert ``export-failed`` and pushes nothing.
6. Write and push ``nights/<date>/night.json`` and the night's manifest (counts only).
7. Publish the one metric, unless something stopped the night (decision 0177 item 2).
8. Send one alert per kind, each with its own counts (decision 0177 item 1).

Any other exception sends ``night-crashed`` with no counts and is raised again; the missing-night
alarm fires too, because no metric was published. Nothing that leaves the night (the records,
the manifest, the alerts, the printed line) names a case (decision 0024).
"""

import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, date
from pathlib import Path
from typing import Final

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.errors import ConfigurationError, DocketError, LeakageError
from ntsb_probable_cause.live.cloud import Alerts, BucketMirror, MetricLike, publish_finished
from ntsb_probable_cause.live.fetch import FetchError, fetch_record
from ntsb_probable_cause.live.later import (
    Awaiting,
    LaterScore,
    awaiting,
    overdue,
    score_later,
)
from ntsb_probable_cause.live.local import live_run_folders
from ntsb_probable_cause.live.morning import (
    ALERT_KINDS,
    LiveRefusal,
    MorningDeps,
    NightOutcome,
    run_morning,
)
from ntsb_probable_cause.live.queue import QueuedCase
from ntsb_probable_cause.scoring.budget import RESERVATION_FILE
from ntsb_probable_cause.scoring.records import read_jsonl

NIGHT_FORMAT: Final = "live-night/1"
NIGHT_MANIFEST_FORMAT: Final = "live-night-manifest/1"
NIGHT_FILE: Final = "night.json"
NIGHT_MANIFEST_FILE: Final = "manifest.json"
STATE_KEY: Final = Path("nights") / "state.json"
FETCH_FAILED: Final = "fetch-failed"
AWAITING_CODES: Final = "awaiting-codes-7"
EXPORT_FAILED: Final = "export-failed"
NIGHT_CRASHED: Final = "night-crashed"
NIGHT_KINDS: Final = (FETCH_FAILED, AWAITING_CODES, EXPORT_FAILED, NIGHT_CRASHED)


@dataclass(frozen=True)
class NightDeps:
    """Everything a night touches outside itself; a test gives a fake for each.

    ``morning.settings.runs_dir`` must be ``<mirror.local>/runs`` (so the bucket sees the run's
    replies and trail); the morning's sink is a ``MirrorSink`` over ``mirror`` and its spend an
    ``OpenRouterKeySpend``. ``export`` builds the export from the mirror folder it is given and
    returns the folder it wrote (``board.build_export``, with its other arguments bound).
    """

    morning: MorningDeps
    mirror: BucketMirror
    alerts: Alerts
    metric: MetricLike | None  # None outside the image
    ntsb: Callable[[], NtsbClient]  # for later scores
    export: Callable[[Path], Path]


@dataclass(frozen=True)
class NightReport:
    """What a night did; no case is named."""

    started: bool  # False when today's marker already existed
    outcome: NightOutcome | None  # None when the morning was stopped
    alerts: tuple[str, ...]
    later_scored: int


@dataclass(frozen=True)
class _Later:
    scored: int
    overdue: int
    errors: dict[str, int]  # error kind -> cases; never a case id
    path: Path | None  # tonight's scores file, if one was written


def run_night(deps: NightDeps, *, limit: int | None = None) -> NightReport:
    """Run one cloud night.

    Args:
        deps: the outside world, as fakes or the deployed versions.
        limit: take at most this many new cases (never more than the money allows).

    Returns:
        What the night did, in counts and kinds.

    Raises:
        ConfigurationError: the morning's runs folder is not the mirror's ``runs/``; raised
            (after the ``night-crashed`` alert) before the day is claimed, so a corrected task
            can still run today.
        Exception: anything the night did not expect, after the ``night-crashed`` alert.
    """
    try:
        _check_runs_folder(deps)
        today = deps.morning.now().astimezone(UTC).date()
        if not deps.mirror.mark_started(today):
            _say("a night already started today: this task stops here and does nothing else")
            return NightReport(started=False, outcome=None, alerts=(), later_scored=0)
        return _Night(deps, today, limit).run()
    except Exception:
        with suppress(Exception):  # a crash is reported if it can be; the alarm covers the rest
            deps.alerts.send([NIGHT_CRASHED], {})
        raise


def _check_runs_folder(deps: NightDeps) -> None:
    """Refuse a morning whose runs folder is not the mirror's ``runs/`` (carried ruling 7)."""
    if deps.morning.settings.runs_dir.resolve() != (deps.mirror.local / "runs").resolve():
        raise ConfigurationError(
            "the live night's runs folder must be the bucket mirror's runs/ folder, so that "
            "every reply reaches the bucket"
        )


class _Night:
    def __init__(self, deps: NightDeps, today: date, limit: int | None) -> None:
        self.deps = deps
        self.today = today
        self.limit = limit
        self.local = deps.mirror.local

    def run(self) -> NightReport:
        self.deps.mirror.pull()
        outcome, stop = self._morning()
        kinds = list(outcome.alerts) if outcome is not None else [stop or NIGHT_CRASHED]
        later = self._later_scores()
        if later.overdue:
            kinds.append(AWAITING_CODES)
        if later.path is not None:
            self.deps.mirror.push(later.path.relative_to(self.local))
        if not self._export():
            kinds.append(EXPORT_FAILED)
        kinds = list(dict.fromkeys(kinds))
        _check_kinds(kinds)
        self._write_record(outcome, kinds, later, finished=stop is None)
        self.deps.mirror.push(Path("nights") / self.today.isoformat())
        if stop is None and self.deps.metric is not None:
            publish_finished(self.deps.metric)
        for kind in kinds:  # one email per condition (decision 0177 item 1)
            self.deps.alerts.send([kind], _alert_counts(kind, outcome, later))
        return NightReport(
            started=True, outcome=outcome, alerts=tuple(kinds), later_scored=later.scored
        )

    # --- the morning, with a copy to the bucket after every reply ---

    def _morning(self) -> tuple[NightOutcome | None, str | None]:
        morning_deps = replace(self.deps.morning, on_reply_factory=self._pusher)
        try:
            return run_morning(morning_deps, limit=self.limit), None
        except LiveRefusal as refusal:
            return None, refusal.kind
        except FetchError, DocketError:  # a resume's or a completion's fetch: never a case's
            return None, FETCH_FAILED

    def _pusher(self, folder: Path) -> Callable[[], None]:
        """The observer for one run folder: push every file in it but a budget reservation.

        A reservation is the runner's local lock on the month's budget, settled when the run
        ends. The task role cannot delete, so one copied up would stay in the bucket and be
        counted against every later night's budget; it is never copied.
        """
        mirror = self.deps.mirror

        def push() -> None:
            for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                if path.name != RESERVATION_FILE:
                    mirror.push(path.relative_to(self.local))

        return push

    # --- later scores (decision 0174) ---

    def _later_scores(self) -> _Later:
        runs = live_run_folders(self.local / "runs")
        cases = awaiting(runs, _scored_ids(self.local / "scores"))
        if not cases:
            return _Later(scored=0, overdue=0, errors={}, path=None)
        written: list[LaterScore] = []
        errors: Counter[str] = Counter()
        with self.deps.ntsb() as client:
            for case in cases:
                try:
                    score = score_later(fetch_record(client, _queued(case)), case, self.today)
                except Exception as error:  # one bad record must not stop the rest (ruling 5)
                    errors[_error_kind(error)] += 1
                    continue
                if score is not None:
                    written.append(score)
        path: Path | None = None
        if written:
            path = self.local / "scores" / f"{self.today.isoformat()}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as handle:
                handle.write("".join(s.model_dump_json() + "\n" for s in written))
        done = {s.case_id for s in written}
        left = [c for c in cases if c.case_id not in done]
        return _Later(
            scored=len(written),
            overdue=overdue(left, self.today),
            errors=dict(sorted(errors.items())),
            path=path,
        )

    # --- the export ---

    def _export(self) -> bool:
        """Build the export and push its folder; False when the mirror is damaged."""
        try:
            out = self.deps.export(self.local)
        except ConfigurationError:
            return False
        self.deps.mirror.push_export(out)
        return True

    # --- the night record and its manifest ---

    def _write_record(
        self, outcome: NightOutcome | None, kinds: Sequence[str], later: _Later, *, finished: bool
    ) -> None:
        summary = outcome.summary if outcome is not None else None
        counts = {
            "coded": summary.coded if summary else 0,
            "not_coded": sum(summary.not_coded.values()) if summary else 0,
            "held_back": summary.held_back if summary else 0,
            "later_scored": later.scored,
            "failures_counted": summary.failures_counted if summary else 0,
        }
        record = {
            "format": NIGHT_FORMAT,
            "date": self.today.isoformat(),
            "coded": counts["coded"],
            "not_coded": dict(sorted(summary.not_coded.items())) if summary else {},
            "held_back": counts["held_back"],
            "later_scored": later.scored,
            "alerts": list(kinds),
            "failures_counted": counts["failures_counted"],
            "later_errors": later.errors,
        }
        folder = self.local / "nights" / self.today.isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / NIGHT_FILE).write_text(json.dumps(record, indent=2) + "\n")
        night_files = self._night_files(summary.run_id if summary else None, later.path)
        manifest = {
            "format": NIGHT_MANIFEST_FORMAT,
            "date": self.today.isoformat(),
            "finished": finished,
            # This folder's own files, as ``records.write_manifest`` lists a folder's.
            "files": [_entry(p, folder) for p in _files(folder) if p.name != NIGHT_MANIFEST_FILE],
            # Everything else the night wrote, by its path in the bucket.
            "night_files": [_entry(p, self.local) for p in night_files],
            "counts": counts,
        }
        (folder / NIGHT_MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n")

    def _night_files(self, run_id: str | None, scores: Path | None) -> list[Path]:
        paths: list[Path] = []
        if run_id is not None:
            paths += [p for p in _files(self.local / "runs" / run_id) if p.name != RESERVATION_FILE]
        if scores is not None:
            paths.append(scores)
        state = self.local / STATE_KEY
        if state.is_file():
            paths.append(state)
        return paths


def _check_kinds(kinds: Sequence[str]) -> None:
    unknown = [k for k in kinds if k not in ALERT_KINDS]
    if unknown:
        raise ConfigurationError(f"{len(unknown)} alert kinds are not in ALERT_KINDS")


def _alert_counts(kind: str, outcome: NightOutcome | None, later: _Later) -> dict[str, int]:
    """The counts one alert carries: those of its own condition, never a case id."""
    summary = outcome.summary if outcome is not None else None
    if summary is not None and kind == "money-held-back":
        return {"held-back": summary.held_back, "coded": summary.coded}
    if summary is not None and kind == "outage":
        return {"returned": summary.returned}
    if summary is not None and kind in {"unreachable-3", "unreachable-final"}:
        return {"failures-counted": summary.failures_counted}
    if kind == AWAITING_CODES:
        return {"overdue": later.overdue}
    return {}


def _scored_ids(folder: Path) -> set[str]:
    ids: set[str] = set()
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        ids.update(score.case_id for score in read_jsonl(path, LaterScore))
    return ids


def _queued(case: Awaiting) -> QueuedCase:
    """The fetch's view of an awaiting case (its closure run plays no part in a fetch)."""
    return QueuedCase(
        mkey=case.mkey,
        case_id=case.case_id,
        event_date=case.event_date,
        closed_on=case.closed_on,
        closure_run=0,
    )


def _error_kind(error: Exception) -> str:
    if isinstance(error, LeakageError):
        return "leakage"
    if isinstance(error, FetchError):
        return FETCH_FAILED
    return "error"


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []


def _entry(path: Path, root: Path) -> Mapping[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")
