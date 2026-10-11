"""``ntsb-live run`` (one live morning) and ``ntsb-live report`` (the counts-only report).

``report --mirror DIR --export DIR [--night-export DIR] --ledger PATH [--attest PATH]
[--out PATH]``: the counts-only S4 report (``scripts/s4_live_report.py``) from local files; it
prints no case number and takes no lock.

``export --from DIR --out DIR``: the public board's JSON export (``board/1``) from a local copy of
the bucket (``runs/``, ``scores/``, ``nights/``), with no store, so the open-case counts are zero.
It reads files, calls no model and prints counts only, never a case number.

``verify-ledger --ledger PATH [--mirror DIR]``: a local copy of the bucket (default
``<data_dir>/live-mirror``) against the ledger (decision 0178); keys and problem kinds only.

``run``: one cloud night (S4 spec section 5, decisions 0171, 0172, 0177), in the live image
only. Paid nights run only where ``NTSB_COMMIT_SHA`` and ``NTSB_LIVE_BUCKET`` are both set (the
live image sets them); anywhere else ``run`` without ``--dry-run`` refuses with one line and
does nothing (decision 0171). In the image it builds
:class:`~ntsb_probable_cause.live.night.NightDeps`: a mirror of the bucket under
``<data_dir>/live-mirror`` (boto3 S3, its listing paginated), the morning's sink a
``MirrorSink`` over it and its runs folder the mirror's ``runs/``, the live key's spend from
OpenRouter's key endpoint (httpx), alerts to SNS, the metric to CloudWatch, and an export built
from the mirror into ``<data_dir>/live-export`` with its own store copy. The same-day marker
in the bucket replaces the Mac's ``live.lock``. boto3 is imported only on that path.

``run --dry-run``: with ``NTSB_LIVE_BUCKET`` set, the bucket is pulled into a temporary folder
under ``data_dir`` through a bucket that refuses every write, and the morning's dry run reads
it, the live key's spend and the store; alerts are printed. Without it, the S3.3 local dry run
(S3.3 spec sections 4 and 9): the store pulled to a work file, spend and results read from the
runs folder, under an exclusive, non-blocking lock on ``<runs_dir>/live.lock``. The docket client
uses ``settings.live_docket_dir``, never ``settings.docket_dir``.

A refusal (a ``ConfigurationError`` or ``BudgetError``, or an AWS login that has expired) is one
line on stderr and exit code 1, never a traceback and never a value from the environment.

No error line names a live case (decision 0160, the open-split fence): a ``FetchError`` or
``DocketError`` is reported by its class alone, with its runbook row (decision 0175), and every
line printed for an error passes through :func:`scrubbed`, which replaces NTSB case numbers and
docket and case keys.
"""

import argparse
import fcntl
import hashlib
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import httpx

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import (
    BatchCancelledError,
    BudgetError,
    ConfigurationError,
    DocketError,
)
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.live.board import build_export, write_export
from ntsb_probable_cause.live.cloud import (
    BucketLike,
    BucketMirror,
    MetricLike,
    MirrorSink,
    OpenRouterKeySpend,
    PrintAlerts,
    SnsAlerts,
    SnsLike,
)
from ntsb_probable_cause.live.fetch import FetchError
from ntsb_probable_cause.live.ledger import read_ledger, verify
from ntsb_probable_cause.live.local import (
    STORE_WORK_FILENAME,
    LocalFolderSink,
    LocalSpend,
    S3StoreSource,
)
from ntsb_probable_cause.live.morning import MorningDeps, MorningSummary, run_morning
from ntsb_probable_cause.live.night import NightDeps, NightReport, run_night
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.scoring.runner import BatchRunner
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store.sync import Location

LOCK_FILENAME = "live.lock"
MIRROR_DIRNAME: Final = "live-mirror"
EXPORT_DIRNAME: Final = "live-export"
EXPORT_STORE_FILENAME: Final = "live-export-store.sqlite"
IMAGE_ONLY: Final = (
    "ntsb-live run: paid nights run only in the live image (decision 0171); use --dry-run here."
)
_HTTP_TIMEOUT_SECONDS: Final = 30.0
_PRECONDITION_FAILED: Final = 412
_CONFLICT: Final = 409
# A 409 answer to a conditional write is retried (fix round 1 of Task 10, item 4): twice more,
# after these pauses in seconds.
_CONFLICT_PAUSES: Final = (0.5, 1.0)
_CASE_NUMBER = re.compile(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}\b")
# "docket 1234567", "mKey 1234567", and the pairing guard's "not its own 1234567".
_KEY = re.compile(r"\b(docket|mkey|own)([\s:=]+)\d+", re.IGNORECASE)
_REPO_ROOT = Path(__file__).resolve().parents[2]


class MorningRunningError(Exception):
    """Another morning holds the lock."""


def scrubbed(text: str) -> str:
    """``text`` with any NTSB case number and docket or case key replaced.

    Rare paths (a resume, a completion, the pairing guard) raise errors that name the live case
    they were reading; nothing of the kind may reach a terminal that is copied or shared.
    """
    return _KEY.sub(lambda m: f"{m.group(1)}{m.group(2)}<key>", _CASE_NUMBER.sub("<case>", text))


def _fail(line: str) -> int:
    print(scrubbed(line), file=sys.stderr)
    return 1


def uv_lock_sha256() -> str:
    """SHA-256 of the repository's ``uv.lock`` (it pins the code a morning ran with)."""
    return hashlib.sha256((_REPO_ROOT / "uv.lock").read_bytes()).hexdigest()


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ntsb-live")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one live morning")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="open the store, build the queue, fetch one case and its docket; call no model",
    )
    run.add_argument(
        "--limit", type=_positive, default=None, metavar="N", help="take at most N cases"
    )
    report = commands.add_parser("report", help="print the counts-only report of the live nights")
    report.add_argument(
        "--mirror", required=True, metavar="DIR", help="the local copy of the bucket"
    )
    report.add_argument(
        "--export", dest="export_dir", required=True, metavar="DIR", help="the export"
    )
    report.add_argument(
        "--night-export",
        default=None,
        metavar="DIR",
        help="the night's own export, copied from the bucket (built with the store)",
    )
    report.add_argument("--ledger", required=True, metavar="PATH", help="ledger.jsonl")
    report.add_argument(
        "--attest", default=None, metavar="PATH", help="Andy's dated attestations (JSON)"
    )
    report.add_argument("--out", default=None, metavar="PATH", help="also write it to PATH")
    export = commands.add_parser(
        "export", help="build the board/1 export from a local copy of the bucket"
    )
    export.add_argument("--from", dest="source", required=True, metavar="DIR", help="the mirror")
    export.add_argument("--out", required=True, metavar="DIR", help="where to write the export")
    verify_ledger = commands.add_parser(
        "verify-ledger", help="check a local copy of the bucket against the ledger"
    )
    verify_ledger.add_argument("--ledger", required=True, metavar="PATH", help="ledger.jsonl")
    verify_ledger.add_argument(
        "--mirror", default=None, metavar="DIR", help="the local copy (default: the live mirror)"
    )
    return parser


def _check_export_target(out: Path) -> None:
    """Refuse an export target inside the checkout that git does not ignore.

    The export is published and holds case numbers and the NTSB's causes: it must not sit where
    a ``git add`` could take it (decision 0024). Inside the repository the target must be ignored
    (``git check-ignore``); a git failure refuses too.
    """
    target = out.resolve()
    if not target.is_relative_to(_REPO_ROOT):
        return
    ignored = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(_REPO_ROOT), "check-ignore", "-q", "--", str(target)],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if ignored.returncode != 0:
        raise ConfigurationError(
            "export: --out is inside the git checkout and git does not ignore it; "
            "choose a folder outside the checkout or an ignored one (such as under data/)"
        )


def _export(args: argparse.Namespace) -> int:
    """Build the export from a mirror folder and print its counts; no store, no model call."""
    mirror = Path(args.source)
    if not mirror.is_dir():
        return _fail(f"export: {mirror} is not a folder")
    _check_export_target(Path(args.out))
    now = datetime.now(UTC)
    sha, dirty = commit_state(_REPO_ROOT)
    report = write_export(
        mirror,
        Path(args.out),
        store=None,
        today=now.date(),
        commit=f"{sha}+dirty" if dirty else sha,
        now=now,
    )
    lines = [
        f"cases: {report.cases}",
        *(f"grade, {name}: {count}" for name, count in report.grades.items()),
        f"unreachable: {report.unreachable}",
    ]
    print("\n".join(lines))
    return 0


def _verify_ledger(args: argparse.Namespace, settings: Settings) -> int:
    """Check a mirror against the ledger; problems are keys and kinds, never contents."""
    mirror = Path(args.mirror) if args.mirror else settings.data_dir / MIRROR_DIRNAME
    ledger = Path(args.ledger)
    if not ledger.is_file():
        return _fail(f"verify-ledger: {ledger} is not a file")
    if not mirror.is_dir():
        return _fail(f"verify-ledger: {mirror} is not a folder")
    try:
        lines = read_ledger(ledger)
    except ValueError:
        return _fail(f"verify-ledger: {ledger} is not a valid ledger")
    problems = verify(lines, mirror)
    for problem in problems:
        print(problem)
    print(f"ledger lines: {len(lines)}; problems: {len(problems)}")
    return 1 if problems else 0


def _report(args: argparse.Namespace, settings: Settings) -> int:
    """Run ``scripts.s4_live_report`` (S4 Task 14); it reads local files, calls no model.

    It reads a local copy of the bucket, the export built from it and the ledger, never the
    bucket itself, so it needs no lock and no AWS key.
    """
    if str(_REPO_ROOT) not in sys.path:  # `scripts` is in the checkout, not the installed package
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.s4_live_report import main as report_main  # noqa: PLC0415

    argv = ["--mirror", args.mirror, "--export", args.export_dir, "--ledger", args.ledger]
    if args.night_export:
        argv += ["--night-export", args.night_export]
    if args.attest:
        argv += ["--attest", args.attest]
    if args.out:
        argv += ["--out", args.out]
    return report_main(argv)


class S3Bucket:
    """``cloud.BucketLike`` over a boto3 S3 client."""

    def __init__(self, client: Any, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._client = client
        self._sleep = sleep  # injected, so a test of the conflict retry does not wait

    def list_keys(self, bucket: str, prefix: str) -> list[tuple[str, int]]:
        """Every ``(key, size)`` under ``prefix``, from every page of the listing.

        ``list_objects_v2`` answers at most 1,000 keys a page; a page left unread would hide
        old runs, and their cases would be coded again (carried ruling 6, Task 9).
        """
        found: list[tuple[str, int]] = []
        for page in self._client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix
        ):
            found.extend((str(item["Key"]), int(item["Size"])) for item in page.get("Contents", []))
        return found

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        """Download one object."""
        self._client.download_file(bucket, key, filename)

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        """Upload one file, replacing any object there."""
        self._client.upload_file(filename, bucket, key)

    def put_if_absent(self, bucket: str, key: str, body: bytes) -> bool:
        """``put_object`` with ``IfNoneMatch="*"``: one atomic check and write.

        Returns True when the write succeeded and False when the key exists (S3 answers
        ``PreconditionFailed``, HTTP 412). S3 answers HTTP 409 ``ConditionalRequestConflict``
        when another conditional write to the key is in flight, and its guide says to retry:
        https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html
        A 409 is retried twice more after a short pause; a third 409 returns False, so the day
        is taken as claimed and the night stops (fail closed). Any other error is raised
        (carried ruling 9, Task 9).
        """
        for pause in (0.0, *_CONFLICT_PAUSES):
            if pause:
                self._sleep(pause)
            try:
                self._client.put_object(Bucket=bucket, Key=key, Body=body, IfNoneMatch="*")
            except Exception as error:
                if _answered(error, "PreconditionFailed", _PRECONDITION_FAILED):
                    return False
                if not _answered(error, "ConditionalRequestConflict", _CONFLICT):
                    raise
                continue  # another conditional write is in flight: try again
            return True
        return False  # still in conflict: never claim a day another task may hold


def _answered(error: Exception, code: str, status: int) -> bool:
    """Whether a botocore error carries S3's error ``code`` or HTTP ``status``."""
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    found: object = response.get("Error", {}).get("Code")
    http: object = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return bool(found == code or http == status)


class ReadOnlyBucket:
    """A bucket that reads through and refuses every write (a dry run writes nothing)."""

    def __init__(self, inner: BucketLike) -> None:
        self._inner = inner

    def list_keys(self, bucket: str, prefix: str) -> list[tuple[str, int]]:
        """The inner bucket's listing."""
        return self._inner.list_keys(bucket, prefix)

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        """The inner bucket's download."""
        self._inner.download_file(bucket, key, filename)

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        """Refused."""
        raise ConfigurationError("a dry run writes nothing to the bucket")

    def put_if_absent(self, bucket: str, key: str, body: bytes) -> bool:
        """Refused."""
        raise ConfigurationError("a dry run writes nothing to the bucket")


def http_get(url: str, *, headers: Mapping[str, str]) -> tuple[int, object]:
    """``cloud.HttpGet`` over ``httpx.get``: the status and the decoded body (None if not JSON)."""
    response = httpx.get(url, headers=dict(headers), timeout=_HTTP_TIMEOUT_SECONDS)
    try:
        body: object = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _aws_clients() -> tuple[Any, SnsLike, MetricLike]:
    """boto3's S3, SNS and CloudWatch clients, imported only for a cloud night or dry run."""
    try:
        import boto3  # noqa: PLC0415 -- the optional `aws` extra, as store/sync.py imports it
    except ImportError as error:
        raise ConfigurationError(
            "boto3 is not installed; install the 'aws' extra (uv sync --extra aws)."
        ) from error
    return boto3.client("s3"), boto3.client("sns"), boto3.client("cloudwatch")


def _key_spend(settings: Settings) -> OpenRouterKeySpend:
    return OpenRouterKeySpend(
        settings.require_openrouter_key(), settings.openrouter_base_url, http_get
    )


def _exporter(settings: Settings) -> Callable[[Path, date, datetime], Path]:
    """The night's export: ``build_export`` with its own store copy and the commit bound.

    The night passes its own day and clock reading, so a night that runs past midnight UTC
    dates its export as it dates its records (fix round 1 of Task 10, item 7). The store is
    pulled again to a work file of its own (the morning has discarded its copy) and discarded
    after. The export goes to ``<data_dir>/live-export``, outside the mirror.
    """
    commit = settings.commit_sha or ""

    def export(mirror: Path, today: date, now: datetime) -> Path:
        source = S3StoreSource(Location(settings.store), settings.data_dir / EXPORT_STORE_FILENAME)
        store = source.open()
        try:
            return build_export(
                mirror,
                settings.data_dir / EXPORT_DIRNAME,
                store=store,
                today=today,
                commit=commit,
                now=now,
            )
        finally:
            source.discard()

    return export


def build_night_deps(settings: Settings) -> NightDeps:
    """The deployed dependencies of a cloud night, built from ``settings`` (in the image only).

    Raises:
        ConfigurationError: the commit, the bucket or the alert topic is not set, or boto3 is
            not installed.
    """
    sha, bucket, topic = settings.commit_sha, settings.live_bucket, settings.live_alert_topic_arn
    if sha is None or bucket is None:
        raise ConfigurationError(IMAGE_ONLY)
    if topic is None:
        raise ConfigurationError(
            "NTSB_LIVE_ALERT_TOPIC_ARN is not set: a cloud night must be able to send its alerts"
        )
    s3, sns, cloudwatch = _aws_clients()
    local = settings.data_dir / MIRROR_DIRNAME
    mirror = BucketMirror(bucket, local, S3Bucket(s3))
    night_settings = settings.model_copy(update={"runs_dir": local / "runs"})
    morning = replace(
        build_deps(night_settings),
        spend=_key_spend(settings),
        sink=MirrorSink(mirror, local),
        commit=lambda: (sha, False),  # the image is built from a clean commit (decision 0171)
    )
    return NightDeps(
        morning=morning,
        mirror=mirror,
        alerts=SnsAlerts(topic, sns),
        metric=cloudwatch,
        ntsb=morning.ntsb,
        export=_exporter(settings),
    )


def _night(args: argparse.Namespace, settings: Settings) -> int:
    """Run one cloud night; exit 1 when something stopped it, 0 otherwise."""
    report: NightReport = run_night(build_night_deps(settings), limit=args.limit)
    if not report.started:
        return 0
    if report.outcome is not None:
        print(format_summary(report.outcome.summary))
    else:
        print(f"night stopped: {report.alerts[0]}")
    print(f"later scores: {report.later_scored}")
    for kind in report.alerts:
        print(f"alert: {kind}")
    return 0 if report.outcome is not None else 1


def _cloud_dry_run(args: argparse.Namespace, settings: Settings) -> int:
    """The morning's dry run on a temporary mirror of the bucket; nothing is written to it.

    It holds ``<runs_dir>/live.lock``, as the local ``run`` and ``report`` do: all three replace
    the same store work file under ``data_dir`` (fix round 1 of Task 10, item 8).
    """
    bucket = settings.live_bucket
    if bucket is None:  # the caller checked; kept for the type checker
        raise ConfigurationError("NTSB_LIVE_BUCKET is not set")
    with morning_lock(settings.runs_dir):
        return _cloud_dry_run_locked(args, settings, bucket)


def _cloud_dry_run_locked(args: argparse.Namespace, settings: Settings, bucket: str) -> int:
    s3, _sns, _metric = _aws_clients()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="live-dry-run-", dir=settings.data_dir) as work:
        local = Path(work) / "mirror"
        mirror = BucketMirror(bucket, local, ReadOnlyBucket(S3Bucket(s3)))
        mirror.pull()
        dry = settings.model_copy(update={"runs_dir": local / "runs"})
        deps = replace(build_deps(dry), spend=_key_spend(settings), sink=MirrorSink(mirror, local))
        # The Mac's commit is not the image's, so the resume-across-commits check is skipped here
        # and said so (a paid night keeps it).
        outcome = run_morning(deps, dry_run=True, limit=args.limit, check_resume=False)
    print(format_summary(outcome.summary))
    print(
        "information: this dry run does not check whether an unfinished run began at another "
        "commit (only the image's own night can say); see the runbook, 'resume-refused'."
    )
    alerts = PrintAlerts()
    for kind in outcome.alerts:
        alerts.send([kind], {})
    return 0


def _models(settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
    http = OpenRouterClient(
        settings.require_openrouter_key(), base_url=settings.openrouter_base_url
    )
    return http, None  # decision 0165: live runs are sync, so no batch client is built


def build_deps(settings: Settings) -> MorningDeps:
    """The deployed dependencies of a morning, built from ``settings``."""
    return MorningDeps(
        settings=settings,
        now=lambda: datetime.now(UTC),
        store=S3StoreSource(Location(settings.store), settings.data_dir / STORE_WORK_FILENAME),
        spend=LocalSpend(settings.runs_dir),
        sink=LocalFolderSink(settings.runs_dir),
        ntsb=lambda: NtsbClient(
            settings.require_api_key(), requests_per_minute=settings.requests_per_minute
        ),
        docket=lambda: DocketClient(
            settings.live_docket_dir, seconds_per_request=settings.docket_seconds_per_request
        ),
        models=lambda: _models(settings),
        commit=commit_state,
        uv_lock_sha256=uv_lock_sha256,
    )


@contextmanager
def morning_lock(runs_dir: Path) -> Iterator[None]:
    """Hold the morning lock, or raise :class:`MorningRunningError` at once."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    with (runs_dir / LOCK_FILENAME).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MorningRunningError from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def format_summary(summary: MorningSummary) -> str:
    """The morning's counts as plain lines; no case is named."""
    billed = "" if summary.billed_usd is None else f" (billed: ${summary.billed_usd:.4f})"
    lines = [
        f"run: {summary.run_id or 'none'}",
        f"coded: {summary.coded}",
        *(f"not coded, {reason}: {count}" for reason, count in sorted(summary.not_coded.items())),
        f"returned to the queue: {summary.returned}",
        f"still queued: {summary.queued}",
        f"held back by money: {summary.held_back}",
        f"cost: ${summary.cost_usd:.4f}{billed}",
        f"minutes: {summary.minutes:.1f}",
        f"bytes freed: {summary.freed_bytes}",
        *(f"warning: {warning}" for warning in summary.warnings),
    ]
    return "\n".join(lines)


# An expired login, by class name or error code (matched by name so that botocore need not be
# installed where this is read).
_EXPIRED_CLASSES = frozenset(
    {
        "TokenRetrievalError",
        "UnauthorizedSSOTokenError",
        "SSOTokenLoadError",
        "LoginRefreshRequired",
        "LoginTokenLoadError",
    }
)
_EXPIRED_CODES = frozenset(
    {"ExpiredToken", "ExpiredTokenException", "RequestExpired", "InvalidClientTokenId"}
)


def _is_aws_error(error: Exception) -> bool:
    return type(error).__module__.startswith(("botocore", "boto3"))


def _login_expired(error: Exception) -> bool:
    if type(error).__name__ in _EXPIRED_CLASSES:
        return True
    response = getattr(error, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    return code in _EXPIRED_CODES


def _aws_message(command: str, error: Exception) -> str:
    if _login_expired(error):
        return (
            f"{command}: the AWS login has expired ({type(error).__name__}). With the ntsb-live "
            "profile, check that pass is unlocked and that the key is still valid (see the "
            "runbook, 'The live shadow's AWS key'). With an `aws login` profile, run "
            "`aws login`. Then run the morning again."
        )
    text = " ".join(str(error).split())[:200]
    return f"{command}: AWS error ({type(error).__name__}): {text}"


def _error_line(command: str, settings: Settings, error: Exception) -> str | None:
    """The one line an error is reported as, or None when it is a bug that should propagate."""
    if isinstance(error, MorningRunningError):
        return (
            f"{command}: another morning is running (lock {settings.runs_dir / LOCK_FILENAME}); "
            "nothing was done. Wait for it to finish."
        )
    if isinstance(error, BatchCancelledError):
        return f"{command}: {error} (ntsb-live has no --resume option: run the same command again.)"
    if isinstance(error, FetchError | DocketError):
        # Its text names the case's docket key, so only its class is said.
        return (
            f"{command}: {type(error).__name__}: a case's record or docket could not be read; "
            "no case is named here. See the runbook, 'fetch-failed'."
        )
    if isinstance(error, BudgetError | ConfigurationError | FileNotFoundError):
        return f"{command}: {error}"
    return _aws_message(command, error) if _is_aws_error(error) else None


def _local_dry_run(args: argparse.Namespace, settings: Settings) -> int:
    """S3.3's dry run on the local runs folder, under the morning lock."""
    with morning_lock(settings.runs_dir):
        outcome = run_morning(build_deps(settings), dry_run=True, limit=args.limit)
    print(format_summary(outcome.summary))
    for kind in outcome.alerts:
        print(f"alert: {kind}")
    return 0


def _dispatch(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "export":
        return _export(args)
    if args.command == "report":
        return _report(args, settings)
    if args.command == "verify-ledger":
        return _verify_ledger(args, settings)
    if not args.dry_run:
        return _night(args, settings)
    if settings.live_bucket is not None:
        return _cloud_dry_run(args, settings)
    return _local_dry_run(args, settings)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run one night or dry run, or a report or export; the exit code."""
    args = _build_parser().parse_args(argv)
    settings = Settings()
    if (
        args.command == "run"
        and not args.dry_run
        and (settings.commit_sha is None or settings.live_bucket is None)
    ):
        return _fail(IMAGE_ONLY)  # before anything else: paid calls only from the image (0171)
    try:
        return _dispatch(args, settings)
    except Exception as error:
        line = _error_line(args.command, settings, error)
        if line is None:
            raise
        return _fail(line)


if __name__ == "__main__":
    raise SystemExit(main())
