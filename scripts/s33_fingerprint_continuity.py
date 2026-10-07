"""Prove the rendered-text fingerprint gives the same value on the frozen commit and on HEAD.

Status
    Run once in S3.3 (spec §7.2); writes ``docs/results/s33-fingerprint-continuity.txt``.
    Free: it adds a throwaway git worktree of the frozen commit, runs one import in it and one
    in this tree, and removes the worktree.

Why
    Version 1's label, :data:`SOURCE_LABEL_V1`, was made on the frozen commit by hashing source
    (``+p``). Decision 0143 replaced that with a hash of the rendered requests (``+t``), computed
    by ``agent/rendered.py``, which imports only what existed at the frozen commit. If that file,
    copied unchanged into a checkout of the frozen commit, gives the same hash as on this
    branch, then ``+t`` describes the very texts version 1 sent.

Usage
    uv run python -m scripts.s33_fingerprint_continuity [--out PATH]

Exit status: 0 on a match, 1 on a mismatch, 2 if the run on the frozen commit itself fails.
"""

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path

from ntsb_probable_cause.agent.version import SOURCE_LABEL_V1
from ntsb_probable_cause.scoring.prompt import FINGERPRINT_CHARS

FROZEN_COMMIT = "fd6053f"
REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERED = Path("src/ntsb_probable_cause/agent/rendered.py")
_CODE = "from ntsb_probable_cause.agent.rendered import rendered_sha256; print(rendered_sha256())"


class RunFailedError(Exception):
    """The fingerprint run in one tree failed; the message is its standard error."""


def _git(*args: str) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@contextlib.contextmanager
def frozen_checkout() -> Iterator[Path]:
    """Yield a throwaway worktree of the frozen commit holding this tree's ``rendered.py``.

    Always removed on exit, with a prune, even after a failure.
    """
    tmp = Path(tempfile.mkdtemp(prefix="s33-continuity-")) / "tree"
    try:
        _git("worktree", "add", "--detach", str(tmp), FROZEN_COMMIT)
        shutil.copyfile(REPO_ROOT / RENDERED, tmp / RENDERED)
        yield tmp
    finally:
        with contextlib.suppress(subprocess.CalledProcessError):
            _git("worktree", "remove", "--force", str(tmp))
        shutil.rmtree(tmp.parent, ignore_errors=True)
        with contextlib.suppress(subprocess.CalledProcessError):
            _git("worktree", "prune")


def run_in_tree(tree: Path) -> str:
    """Return the full SHA-256 the tree's own ``rendered_sha256`` prints.

    Args:
        tree: A checkout; its ``src`` goes first on ``PYTHONPATH``.

    Returns:
        The full hex digest.

    Raises:
        RunFailedError: The run exited non-zero; the message is its standard error.
    """
    env = {**os.environ, "PYTHONPATH": str(tree / "src")}
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _CODE],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RunFailedError(done.stderr)
    return done.stdout.strip()


def _head() -> str:
    return _git("rev-parse", "--short", "HEAD")


def main(
    argv: Sequence[str] | None = None,
    *,
    checkout: Callable[[], AbstractContextManager[Path]] = frozen_checkout,
    runner: Callable[[Path], str] = run_in_tree,
    head: Callable[[], str] = _head,
) -> int:
    """Run the fingerprint on the frozen commit and on this tree, and compare.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv``.
        checkout: Makes the frozen tree (a context manager yielding its path); injectable.
        runner: Returns the full hex fingerprint of a tree; injectable.
        head: Returns HEAD's short commit; injectable.

    Returns:
        0 on a match, 1 on a mismatch, 2 if the run on the frozen commit fails.
    """
    parser = argparse.ArgumentParser(description="Fingerprint continuity on the frozen commit.")
    parser.add_argument("--out", type=Path, help="write the results file here")
    args = parser.parse_args(argv)

    try:
        with checkout() as frozen:
            frozen_hex = runner(frozen)
    except RunFailedError as exc:
        print(f"the run on {FROZEN_COMMIT} failed:\n{exc}", file=sys.stderr)
        return 2
    head_hex = runner(REPO_ROOT)
    match = frozen_hex == head_hex
    n = FINGERPRINT_CHARS
    lines = [
        f"frozen commit: {FROZEN_COMMIT}",
        f"version 1 label: {SOURCE_LABEL_V1}",
        f"+t on {FROZEN_COMMIT}: {frozen_hex[:n]}",
        f"+t on HEAD ({head()}): {head_hex[:n]}",
        f"sha256 on {FROZEN_COMMIT}: {frozen_hex}",
        f"sha256 on HEAD: {head_hex}",
        f"match: {'yes' if match else 'no'}",
    ]
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    return 0 if match else 1


if __name__ == "__main__":
    sys.exit(main())
