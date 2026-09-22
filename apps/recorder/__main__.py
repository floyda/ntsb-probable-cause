"""``ntsb-record run``: the nightly recorder entrypoint (spec S2.5 §9.1, Task 10).

Six steps, in order: work out the commit this run is built from; open the store (pulling it
from S3 first, if that is where it lives); run the night (``recorder.run.run_night``, S2.5
Task 9); close the store; push it back (unless ``--dry-run``); exit.

Failure rules (controller note 2, spec §9.1's "the store is saved once, at the end"):

- A missing or unusable ``NTSB_API_KEY``, or a commit identity that cannot be determined
  (neither ``NTSB_COMMIT_SHA`` nor ``git`` works), is a clean, one-line refusal on stderr and
  exit 1 -- the same shape ``apps/eval`` uses for a :class:`~ntsb_probable_cause.errors.
  ConfigurationError`, never a traceback, and never a value from the environment.
- Any *other* exception -- in particular, one that escapes :func:`~ntsb_probable_cause.
  recorder.run.run_night` itself -- is logged with its full traceback, the store is closed
  (but never pushed), and this exits 1. For a **local** store the local path already *is* the
  store, so whatever the night wrote before it failed stays in place -- those are real,
  already-committed observations, and only the run's own ``runs`` row is left unfinished. For
  an **S3** store the local working file is a temporary copy: closing it checkpoints the WAL
  onto disk, but skipping the push means that copy, and everything the night wrote to it, is
  discarded -- tonight's rows really are lost, and tomorrow's run sees a wider interval, never
  a false date (this is the one place the two backends genuinely differ; the bridge runbook,
  ``docs/runbooks/recorder-bridge.md``, states it plainly).
- On success the store is closed, then pushed (skipped under ``--dry-run``), and this exits 0.
"""

import argparse
import logging
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.recorder.run import NightInputs, run_night
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import Store
from ntsb_probable_cause.store.sync import Location, pull, push

_log = logging.getLogger(__name__)

# Under an `s3://` store, the working file the store actually opens -- always resolved under
# `settings.data_dir`, never a path relative to the process's current working directory. A
# relative path here once resolved inside a git worktree during development and nearly
# discarded 19 GB of already-fetched docket documents when the worktree was later removed (see
# `settings.py`'s own note on `docket_dir`, which the same incident also fixed).
_S3_WORK_FILENAME = "recorder-work.sqlite"


def _commit_identity(settings: Settings) -> tuple[str, bool]:
    """The commit this run is built from, and whether the tree was dirty (controller note 1).

    ``NTSB_COMMIT_SHA`` is set only inside the container image (Task 12), which is built from a
    known, clean commit and has no ``.git`` to ask -- that value is trusted as-is and reported
    not dirty. Everywhere else (a developer checkout, the Mac bridge) ``git`` supplies both.
    Never fabricates a SHA: if ``git`` itself fails -- no ``.git``, no ``git`` binary, or any
    other failure -- this raises rather than guessing one.
    """
    if settings.commit_sha is not None:
        return settings.commit_sha, False
    try:
        return commit_state()
    except (subprocess.CalledProcessError, OSError) as error:
        raise ConfigurationError(
            "cannot determine the commit: NTSB_COMMIT_SHA is not set and `git` failed "
            f"({error.__class__.__name__}); set NTSB_COMMIT_SHA explicitly -- for example, "
            "inside a container image that has no .git."
        ) from error


def _local_path(settings: Settings, location: Location) -> Path:
    """Where the store opens on disk.

    The location itself, for a local store -- it already *is* the store. A work file under
    ``NTSB_DATA_DIR`` for an `s3://` store (never a path relative to the process's cwd; see the
    module docstring).
    """
    if location.is_s3:
        return settings.data_dir / _S3_WORK_FILENAME
    return Path(location.raw)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ntsb-record")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one nightly pass")
    run.add_argument("--verbose", action="store_true", help="log every diff decision")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="pull and run as usual, but never push the store back to its location",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run one nightly pass. Returns the process exit code."""
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    settings = Settings()

    try:
        commit_sha, dirty = _commit_identity(settings)
        api_key = settings.require_api_key()
    except ConfigurationError as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1

    location = Location(settings.store)
    local = _local_path(settings, location)
    local.parent.mkdir(parents=True, exist_ok=True)
    # Never log NTSB_STORE itself -- only which kind of location it is (module docstring, and
    # the plan's "logs never contain case text" rule extends to settings values generally).
    _log.info("store location=%s", "s3" if location.is_s3 else "local")
    pull(location, local)

    store = Store(local)
    store.migrate()
    try:
        with (
            NtsbClient(api_key, requests_per_minute=settings.requests_per_minute) as api,
            DocketClient(None, seconds_per_request=settings.docket_seconds_per_request) as docket,
        ):
            inputs = NightInputs(
                api=api,
                docket=docket,
                store=store,
                now=lambda: datetime.now(UTC),
                commit_sha=commit_sha,
                dirty=dirty,
            )
            run_night(inputs, verbose=args.verbose)
    except Exception:
        _log.exception("run failed")
        store.close()
        return 1

    store.close()
    if not args.dry_run:
        push(local, location)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
