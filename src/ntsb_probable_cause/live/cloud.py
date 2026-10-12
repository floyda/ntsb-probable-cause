"""The cloud seams a live night talks to the outside through (decisions 0170, 0172, 0177).

The bucket, OpenRouter's key endpoint, SNS and CloudWatch are reached only through the narrow
protocols below. The real boto3 and httpx clients are built in ``apps/live``; this module imports
neither (an import-linter contract keeps it so), and its tests use in-memory fakes.
"""

import hashlib
import json
import math
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Final, Protocol

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.live.local import LocalFolderSink
from ntsb_probable_cause.live.morning import LiveRefusal
from ntsb_probable_cause.live.records import Backfill, ClosureRecord
from ntsb_probable_cause.live.seams import MonthSpend
from ntsb_probable_cause.live.state import NightState
from ntsb_probable_cause.scoring.budget import RESERVATION_FILE

PULLED_PREFIXES: Final = ("runs", "scores", "nights")
EXPORT_PREFIX: Final = "export/board-1"
FINISHED_MARK: Final = "_finished.json"  # export/board-1/_finished.json, uploaded last (A11)
FINISHED_FORMAT: Final = "board-finished/1"
_INDEX_FILE: Final = "index.json"
NIGHT_STATE_FILE: Final = "state.json"
METRIC_NAMESPACE: Final = "Ntsb/Live"
METRIC_NAME: Final = "NightFinished"
_OK: Final = 200
_NAME: Final = re.compile(r"^[a-z][a-z0-9-]*$")
_SUBJECT_MAX: Final = 99  # SNS subjects must be under 100 characters
_SUBJECT_PREFIX: Final = "Ellery live night: "
_PLAIN_WORD: Final = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ABSENT: Final = object()  # the key's answer has no limit_reset field
_NOT_READ: Final = object()  # no good answer read yet
# The push order's two named files (fix round 1 of Task 10). ``run.jsonl`` is the commit point:
# a run folder whose ``run.jsonl`` says finished is never resumed, so it goes up last, after every
# file a finished run needs. ``spec.json`` is what makes a folder a live run at all (a folder
# without ``run.jsonl`` is one when its spec says so), so it goes up after every other file, and
# a half-copied folder is never taken for a live run. A reservation is the runner's local lock on
# the month's budget, settled when the run ends; the task role cannot delete, so one copied up
# would stay in the bucket and count against every later night's guard: it is never copied.
_RUN_FILE: Final = "run.jsonl"
_SPEC_FILE: Final = "spec.json"
_MANIFEST_FILE: Final = "manifest.json"
_NEVER_PUSHED: Final = frozenset({RESERVATION_FILE})


class BucketLike(Protocol):
    """The four bucket calls the mirror needs."""

    def list_keys(self, bucket: str, prefix: str) -> list[tuple[str, int]]:
        """Every ``(key, size)`` under ``prefix``."""
        ...

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        """Download one object to ``filename``."""
        ...

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        """Upload ``filename`` as ``key``, replacing any object there."""
        ...

    def put_if_absent(self, bucket: str, key: str, body: bytes) -> bool:
        """Write ``body`` only when ``key`` does not exist; ``False`` when it does.

        The real S3 call (Task 10) uses ``IfNoneMatch="*"``, so the check and the write are one
        atomic step.
        """
        ...


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def push_order(paths: Sequence[Path]) -> list[Path]:
    """``paths`` in the order a push uploads them: the rest by name, then specs, then run records.

    A night folder's ``manifest.json`` is last of all (it lists ``night.json``).

    The order is explicit, not alphabetical (``run.jsonl`` sorts before ``spec.json`` and
    ``trail.jsonl``). A task killed between two uploads leaves a folder that is either not yet a
    live run (no ``spec.json``) or a live run that is resumed (no ``run.jsonl``), never a run that
    reads as finished with files missing.
    """

    def rank(path: Path) -> tuple[int, str]:
        # A night manifest lists night.json, so it goes up after it: a kill between the two
        # uploads must never leave a manifest whose folder can not be verified.
        if path.name == _MANIFEST_FILE and path.parent.parent.name == "nights":
            return 3, path.as_posix()
        return {_SPEC_FILE: 1, _RUN_FILE: 2}.get(path.name, 0), path.as_posix()

    return sorted(paths, key=rank)


class BucketMirror:
    """The bucket's ``runs/``, ``scores/`` and ``nights/`` held in a local folder."""

    def __init__(self, bucket: str, local: Path, s3: BucketLike) -> None:
        self._bucket = bucket
        self._local = local
        self._s3 = s3
        self._seen: dict[str, str] = {}  # key -> SHA-256 at the last pull or push

    @property
    def local(self) -> Path:
        """The local folder the bucket's ``runs/``, ``scores/`` and ``nights/`` are held in."""
        return self._local

    def pull(self) -> int:
        """Download every object under ``runs/``, ``scores/`` and ``nights/``, never ``export/``.

        A key that would resolve outside the local folder (``..`` parts) is skipped, never
        written. Returns how many keys were skipped.
        """
        root = self._local.resolve()
        skipped = 0
        for prefix in PULLED_PREFIXES:
            for key, _size in self._s3.list_keys(self._bucket, f"{prefix}/"):
                if key.endswith("/"):
                    continue
                target = self._local / key
                if not target.resolve().is_relative_to(root / prefix):
                    skipped += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                self._s3.download_file(self._bucket, key, str(target))
                self._seen[key] = _sha256(target)
        return skipped

    def push(self, relative: Path) -> int:
        """Upload the files changed since the last pull or push; return how many.

        ``relative`` is a file or a folder under the local folder; a folder means every file
        under it, in :func:`push_order` (``run.jsonl`` last, ``spec.json`` just before it). A
        file is changed when its SHA-256 differs from the one recorded; a missing path uploads
        nothing, and a budget reservation (``reservation.json``) is never uploaded.

        Raises:
            ValueError: ``relative`` resolves outside ``runs/``, ``scores/`` and ``nights/``.
        """
        base = self._local / relative
        root = self._local.resolve()
        if not any(base.resolve().is_relative_to(root / prefix) for prefix in PULLED_PREFIXES):
            raise ValueError(f"{relative}: outside runs/, scores/ and nights/")
        files = [p for p in base.rglob("*") if p.is_file()] if base.is_dir() else [base]
        uploaded = 0
        for path in push_order(files):
            if not path.is_file() or path.name in _NEVER_PUSHED:
                continue
            key = path.relative_to(self._local).as_posix()
            digest = _sha256(path)
            if self._seen.get(key) == digest:
                continue
            self._s3.upload_file(str(path), self._bucket, key)
            self._seen[key] = digest
            uploaded += 1
        return uploaded

    def mark_started(self, day: date) -> bool:
        """Claim the day: ``True`` the first time, ``False`` when a night already started.

        On ``True`` the empty marker is also written to the local folder and recorded as seen,
        so the night's manifest lists it and a later push of the folder does not upload it again
        (an unconditional upload would replace the conditional one's object).
        """
        key = f"nights/{day.isoformat()}/started"
        if not self._s3.put_if_absent(self._bucket, key, b""):
            return False
        target = self._local / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
        self._seen[key] = _sha256(target)
        return True

    def push_export(self, folder: Path) -> None:
        """Upload the export under ``folder`` to ``export/board-1/``, then its finished mark.

        The case files go first, then ``index.json``, and last, once every upload succeeded,
        ``export/board-1/_finished.json``: ``{"format": "board-finished/1", "built_at",
        "commit"}``, from the index's stamp, overwritten each night (final review, wave A, item
        A11). A failed upload raises before the mark, so the old mark stays and names the last
        export that went up whole.

        Raises:
            ConfigurationError: ``index.json`` is missing or holds no readable stamp; nothing
                is uploaded.
        """
        index = folder / _INDEX_FILE
        mark = _finished_mark(index)
        files = sorted(p for p in folder.rglob("*") if p.is_file() and p != index)
        for path in [*files, index]:
            key = f"{EXPORT_PREFIX}/{path.relative_to(folder).as_posix()}"
            self._s3.upload_file(str(path), self._bucket, key)
        with tempfile.TemporaryDirectory() as work:
            written = Path(work) / FINISHED_MARK
            written.write_text(json.dumps(mark, indent=2) + "\n")
            self._s3.upload_file(str(written), self._bucket, f"{EXPORT_PREFIX}/{FINISHED_MARK}")


def _finished_mark(index: Path) -> dict[str, str]:
    """The finished mark's body, from ``index.json``'s stamp.

    Raises:
        ConfigurationError: the index is missing, not JSON, or its stamp lacks a text
            ``built_at`` or ``commit``.
    """
    try:
        stamp = json.loads(index.read_text()).get("stamp")
    except (OSError, ValueError, AttributeError) as error:
        raise ConfigurationError(f"the export's {_INDEX_FILE} is missing or unreadable") from error
    built_at = stamp.get("built_at") if isinstance(stamp, dict) else None
    commit = stamp.get("commit") if isinstance(stamp, dict) else None
    if not isinstance(built_at, str) or not isinstance(commit, str):
        raise ConfigurationError(f"the export's {_INDEX_FILE} holds no build stamp")
    return {"format": FINISHED_FORMAT, "built_at": built_at, "commit": commit}


class MirrorSink(LocalFolderSink):
    """``ResultSink`` over the mirror.

    Reads use ``LocalFolderSink`` on ``<local>/runs``; the night state lives at
    ``<local>/nights/state.json`` (one object, overwritten each night; bucket versioning keeps
    the earlier ones). ``write`` and ``write_night_state`` push what they wrote.
    """

    def __init__(self, mirror: BucketMirror, local: Path) -> None:
        super().__init__(local / "runs")
        self._mirror = mirror
        self._local = local

    def write(
        self, run_id: str, records: Sequence[ClosureRecord], backfill: Backfill | None
    ) -> None:
        """Write the run folder as the local sink does, then push it (``run.jsonl`` last)."""
        super().write(run_id, records, backfill)
        self._mirror.push(Path("runs") / run_id)

    def night_state(self) -> NightState:
        """The state in ``nights/state.json``; an empty one when it is not there."""
        path = self._local / "nights" / NIGHT_STATE_FILE
        if not path.is_file():
            return NightState()
        return NightState.model_validate_json(path.read_text())

    def write_night_state(self, state: NightState) -> None:
        """Replace ``nights/state.json`` and push it."""
        path = self._local / "nights" / NIGHT_STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.model_dump_json() + "\n")
        self._mirror.push(Path("nights") / NIGHT_STATE_FILE)


class HttpGet(Protocol):
    """One authenticated GET: ``(status, decoded JSON body)``."""

    def __call__(self, url: str, *, headers: Mapping[str, str]) -> tuple[int, object]:
        """Fetch ``url``."""
        ...


def _number(value: object) -> float | None:
    """``value`` as a finite float, or ``None`` for a bool, a non-number, NaN or infinity."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


class OpenRouterKeySpend:
    """The live key's ``usage_monthly`` and ``limit`` from ``GET /api/v1/key`` (decision 0170)."""

    def __init__(self, key: str, base_url: str, get: HttpGet) -> None:
        self._key = key
        self._url = f"{base_url.rstrip('/')}/api/v1/key"
        self._get = get
        self._limit_reset: object = _NOT_READ

    def limit_reset_line(self) -> str:
        """One line naming the key's ``limit_reset`` as the last good answer gave it (item A5).

        ``limit_reset: <value>`` for a plain word (``monthly``, say), ``limit_reset: null``,
        ``limit_reset: absent`` when the field is not in the answer, ``limit_reset: not a plain
        word`` for anything else, and ``limit_reset: not read`` before an answer was read. It
        never holds the key. Nothing refuses on it: no saved answer shows the field (CLAUDE.md
        rule 2), so the runbook has Andy confirm on OpenRouter that the reset is monthly.
        """
        value = self._limit_reset
        if value is _NOT_READ:
            return "limit_reset: not read"
        if value is _ABSENT:
            return "limit_reset: absent"
        if value is None:
            return "limit_reset: null"
        if isinstance(value, str) and _PLAIN_WORD.fullmatch(value):
            return f"limit_reset: {value}"
        return "limit_reset: not a plain word"

    def month(self, now: datetime) -> MonthSpend:
        """The key's spend this month and its limit.

        Raises:
            LiveRefusal: kind ``"key-unreachable"`` when the call fails, answers other than 200,
                or holds a spend or limit that is not a finite, non-negative number. The message
                never holds the key.
        """
        failure: str | None = None
        status, body = 0, None
        try:
            status, body = self._get(self._url, headers={"Authorization": f"Bearer {self._key}"})
        except Exception as error:
            failure = type(error).__name__
        if failure is not None:  # raised outside the handler: no __context__ carries the error
            raise LiveRefusal(
                "key-unreachable", f"the key endpoint could not be reached ({failure})"
            )
        if status != _OK:
            raise LiveRefusal("key-unreachable", f"the key endpoint answered {status}")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise LiveRefusal("key-unreachable", "the key endpoint's answer has no data object")
        used = _number(data.get("usage_monthly"))
        limit = _number(data.get("limit"))
        if used is None or used < 0:
            raise LiveRefusal("key-unreachable", "the key's monthly usage is not a valid number")
        if limit is None or limit < 0:
            raise LiveRefusal("key-unreachable", "the key's limit is not a valid number")
        self._limit_reset = data.get("limit_reset", _ABSENT)
        return MonthSpend(used_usd=used, limit_usd=limit)


def _checked(kinds: Sequence[str], counts: Mapping[str, int]) -> None:
    """Refuse anything but alert kinds and integer counts (a case id never passes).

    Raises:
        ValueError: a kind or count name is not lower-case words and hyphens, or a count is not
            an ``int`` (a ``bool`` is not).
    """
    for name in (*kinds, *counts):
        if not _NAME.fullmatch(name):
            raise ValueError("alert kinds and count names must be lower-case words and hyphens")
    for value in counts.values():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("alert counts must be integers")  # noqa: TRY004 -- one error type


class Alerts(Protocol):
    """Where a night's alert kinds go (decision 0177); never a case number."""

    def send(self, kinds: Sequence[str], counts: Mapping[str, int]) -> None:
        """Send one alert naming ``kinds`` with integer ``counts``."""
        ...


class PrintAlerts:
    """Prints one line; for local and dry runs."""

    def send(self, kinds: Sequence[str], counts: Mapping[str, int]) -> None:
        """Print the kinds and counts."""
        _checked(kinds, counts)
        pairs = ", ".join(f"{k}: {v}" for k, v in counts.items())
        sys.stdout.write(f"alert: {', '.join(kinds)}" + (f" ({pairs})" if pairs else "") + "\n")


class SnsLike(Protocol):
    """The one SNS call used."""

    def publish(self, *, TopicArn: str, Subject: str, Message: str) -> object:  # noqa: N803
        """Publish a message to a topic."""
        ...


class SnsAlerts:
    """Alerts to an SNS topic. Only kinds and integer counts are formatted (decision 0024)."""

    def __init__(self, topic_arn: str, sns: SnsLike) -> None:
        self._topic_arn = topic_arn
        self._sns = sns

    def send(self, kinds: Sequence[str], counts: Mapping[str, int]) -> None:
        """Publish ``Ellery live night: <kinds>`` with a ``kind: count`` line per count."""
        _checked(kinds, counts)
        subject = (_SUBJECT_PREFIX + ", ".join(kinds))[:_SUBJECT_MAX]
        lines = [f"kinds: {', '.join(kinds)}", *(f"{k}: {v}" for k, v in counts.items())]
        message = "\n".join(lines)
        self._sns.publish(TopicArn=self._topic_arn, Subject=subject, Message=message)


class MetricLike(Protocol):
    """The one CloudWatch call used."""

    def put_metric_data(
        self,
        *,
        Namespace: str,  # noqa: N803
        MetricData: list[dict[str, object]],  # noqa: N803
    ) -> object:
        """Put metric data points."""
        ...


def publish_finished(metric: MetricLike) -> None:
    """Record one ``NightFinished`` data point of value 1 (the missing-night alarm reads it)."""
    metric.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{"MetricName": METRIC_NAME, "Value": 1, "Unit": "Count"}],
    )
