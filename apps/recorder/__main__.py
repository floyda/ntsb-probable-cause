"""``ntsb-record run``: the nightly recorder entrypoint (spec S2.5 §9.1, Task 10).

Six steps, in order: work out the commit this run is built from; open the store (pulling it
from S3 first, if that is where it lives); run the night (``recorder.run.run_night``, S2.5
Task 9); close the store; push it back (unless ``--dry-run``); exit.

Failure rules (controller note 2, spec §9.1's "the store is saved once, at the end"):

- A missing or unusable ``NTSB_API_KEY``, a commit identity that cannot be determined (neither
  ``NTSB_COMMIT_SHA`` nor ``git`` works), or a store whose schema is newer than this code knows
  (final review item 5b), is a clean, one-line refusal on stderr and exit 1 -- the same shape
  ``apps/eval`` uses for a :class:`~ntsb_probable_cause.errors.ConfigurationError`, never a
  traceback, and never a value from the environment.
- A pull failure (fix round 2, Minor 4) -- anything other than the missing-object case
  :func:`~ntsb_probable_cause.store.sync.pull` already reads as "first run: start empty" -- is
  logged with its traceback and exits 1 *before* :class:`~ntsb_probable_cause.store.Store` is
  ever constructed, so a failed pull never silently starts an empty local store next to a real
  one still sitting on S3.
- Any *other* exception -- in particular, one that escapes :func:`~ntsb_probable_cause.
  recorder.run.run_night` itself -- is logged (:func:`_log_run_failure`, final review item 5a:
  the exception's class name and traceback FRAMES, deliberately never its own message, which
  can carry case text), the store is closed (but never pushed), and this exits 1. For a
  **local** store the local path already *is* the store, so whatever the night wrote before it
  failed stays in place -- those are real, already-committed observations, and only the run's
  own ``runs`` row is left unfinished. For an **S3** store the local working file is a
  temporary copy: closing it checkpoints the WAL onto disk, but skipping the push means that
  copy, and everything the night wrote to it, is discarded -- tonight's rows really are lost,
  and tomorrow's run sees a wider interval, never a false date (this is the one place the two
  backends genuinely differ; the bridge runbook, ``docs/runbooks/recorder-bridge.md``, states
  it plainly).
- On success the store is closed, then pushed (skipped under ``--dry-run``), and this exits 0.
"""

import argparse
import logging
import subprocess
import sys
import time
import traceback
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


def _log_run_failure(error: BaseException) -> None:
    """Log a run failure without the exception's own MESSAGE (final review item 5a).

    ``logging.exception``/``Logger.error(..., exc_info=True)`` would append
    ``traceback.format_exception``'s output, whose final line is ``f"{type(error).__name__}:
    {error}"`` -- and a real failure inside ``run_night`` can come from deep in ``split_record``
    or an evidence extractor, where a pydantic ``ValidationError``'s own message embeds the
    offending ``input_value`` -- case text, in a log CloudWatch keeps for 30 days. This logs the
    exception's class name and the traceback's frames (file, line, function -- the part that
    actually helps diagnose a crash) via ``traceback.format_tb``, which never touches the
    exception's message at all.
    """
    frames = "".join(traceback.format_tb(error.__traceback__))
    _log.error("run failed: %s\n%s", type(error).__name__, frames)


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
    # Fix round 1, Minor 6: UTC, with a trailing "Z", matching the wrapper script's own
    # `%Y-%m-%dT%H:%M:%SZ` timestamps (scripts/recorder_bridge.sh) -- a mixed local/UTC log
    # would misorder the wrapper's "run start"/"run done" lines against this process's own,
    # which the runbook's "check it ran" step reads together. Scoped to this one Formatter
    # instance (not `logging.Formatter.converter` globally), so nothing else in the process --
    # or, in a test, anything else in the same pytest session -- is affected.
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
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
    try:
        pull(location, local)
    except Exception:
        # Fix round 1, Minor 4: a pull failure (e.g. a network error, an expired AWS
        # credential -- anything other than "the object is missing", which pull() itself
        # already reads as first-run-start-empty) must stop here, before Store(local) is ever
        # constructed. Opening the store after a failed pull would silently start a fresh,
        # empty local file next to whatever the real store held on S3, which is worse than not
        # opening a store at all: the next successful push would overwrite the real store with
        # that empty one. Logged with its traceback, the same way a run_night or push failure
        # is, for the same reason.
        _log.exception("pull failed")
        return 1

    store = Store(local)
    try:
        store.migrate()
    except ConfigurationError as error:
        # Final review item 5b: a store whose schema_version is newer than this code knows
        # (a rolled-back deploy) is refused loudly, the same clean one-line shape every other
        # ConfigurationError in this app uses -- never a traceback, never a value from the
        # environment. Pre-deploy fix round, item C: `store.close()` here too -- the open
        # sqlite3 connection otherwise leaks (a `ResourceWarning` `make check` catches), and a
        # refused store should never be left holding an open handle on the way out regardless.
        store.close()
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1
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
    except Exception as error:
        _log_run_failure(error)
        store.close()
        return 1

    store.close()
    if not args.dry_run:
        try:
            push(local, location)
        except Exception:
            # Fix round 1, Minor 3: a push failure (e.g. a network error, an expired AWS
            # credential) must not read as a silent success -- it means tonight's rows never
            # left the local working file, and for an S3 store that file is discarded when the
            # process exits (controller note 2). Logged the same way a run_night failure is,
            # for the same reason: this needs the traceback, not a clean one-liner.
            _log.exception("push failed")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
