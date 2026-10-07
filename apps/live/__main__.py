"""``ntsb-live run`` (one live morning) and ``ntsb-live report`` (the counts-only report).

``run``: one live morning (S3.3 spec sections 4 and 9, decisions 0158, 0160, 0163).

This builds the deployed :class:`~ntsb_probable_cause.live.morning.MorningDeps` from
:class:`~ntsb_probable_cause.settings.Settings` and runs the morning. The store is pulled to a
work file and never uploaded; spend and results are read from, and written to, the runs folder.
The docket client uses ``settings.live_docket_dir``, never ``settings.docket_dir``.

No two mornings at once: a morning holds an exclusive, non-blocking lock on
``<runs_dir>/live.lock`` for its whole length. A second one exits at once with a plain message
and does nothing else (a dry run takes the lock too: it replaces the same store work file).

A refusal (a ``ConfigurationError`` or ``BudgetError``, or an AWS login that has expired) is one
line on stderr and exit code 1, never a traceback and never a value from the environment.
"""

import argparse
import fcntl
import hashlib
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import BatchCancelledError, BudgetError, ConfigurationError
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.live.local import (
    STORE_WORK_FILENAME,
    LocalFolderSink,
    LocalSpend,
    S3StoreSource,
)
from ntsb_probable_cause.live.morning import MorningDeps, MorningSummary, run_morning
from ntsb_probable_cause.model.batch import BatchClient
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.scoring.runner import BatchRunner
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store.sync import Location

LOCK_FILENAME = "live.lock"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class MorningRunningError(Exception):
    """Another morning holds the lock."""


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
    report = commands.add_parser("report", help="print the counts-only report of the live runs")
    report.add_argument("--out", default=None, metavar="PATH", help="also write it to PATH")
    return parser


def _report(args: argparse.Namespace, settings: Settings) -> int:
    """Run ``scripts.s33_live_report`` (S3.3 Task 10); it reads, calls no model, spends nothing."""
    if str(_REPO_ROOT) not in sys.path:  # `scripts` is in the checkout, not the installed package
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.s33_live_report import main as report_main  # noqa: PLC0415

    with morning_lock(settings.runs_dir):  # it replaces the same store work file
        return report_main(["--out", args.out] if args.out else [])


def _models(settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
    http = OpenRouterClient(
        settings.require_openrouter_key(), base_url=settings.openrouter_base_url
    )
    return http, BatchClient(http)


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
    billed = "not yet known" if summary.billed_usd is None else f"${summary.billed_usd:.4f}"
    lines = [
        f"run: {summary.run_id or 'none'}",
        f"coded: {summary.coded}",
        *(f"not coded, {reason}: {count}" for reason, count in sorted(summary.not_coded.items())),
        f"returned to the queue: {summary.returned}",
        f"still queued: {summary.queued}",
        f"cost: ${summary.cost_usd:.4f} (billed: {billed})",
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
            f"{command}: the AWS login has expired ({type(error).__name__}). Run "
            "`aws login --profile ntsb` and run the morning again."
        )
    text = " ".join(str(error).split())[:200]
    return f"{command}: AWS error ({type(error).__name__}): {text}"


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run one morning, or print the report. Returns the exit code."""
    args = _build_parser().parse_args(argv)
    settings = Settings()
    try:
        if args.command == "report":
            return _report(args, settings)
        with morning_lock(settings.runs_dir):
            summary = run_morning(build_deps(settings), dry_run=args.dry_run, limit=args.limit)
    except MorningRunningError:
        print(
            f"{args.command}: another morning is running (lock "
            f"{settings.runs_dir / LOCK_FILENAME}); nothing was done. Wait for it to finish.",
            file=sys.stderr,
        )
        return 1
    except BatchCancelledError as error:
        print(
            f"{args.command}: {error} (ntsb-live has no --resume option: run the same command "
            "again.)",
            file=sys.stderr,
        )
        return 1
    except (BudgetError, ConfigurationError, FileNotFoundError) as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        if not _is_aws_error(error):
            raise
        print(_aws_message(args.command, error), file=sys.stderr)
        return 1
    print(format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
