"""The commit state every scored run records (decisions 0018, 0026).

Moved out of ``scoring.ledger`` (S2.5 Task 9) so :mod:`ntsb_probable_cause.recorder` can read
the commit a nightly run was produced by without importing the verdict-aware ``scoring``
package -- that import would pull scoring, and everything it depends on, into the recorder's
import graph, which the import-linter contract "Only the splitter constructs synthesis and
verdict" forbids (CLAUDE.md rule 1). ``scoring.ledger`` re-exports :func:`commit_state` under
its old name, so every existing caller -- and every test that monkeypatches
``ntsb_probable_cause.scoring.ledger.commit_state`` -- is unaffected.
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path


def commit_state(repo: Path = Path()) -> tuple[str, bool]:
    """Short SHA and whether the tree has uncommitted changes."""
    sha = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "status", "--porcelain"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sha, bool(status.strip())


def commits_since(base: str, repo: Path = Path()) -> tuple[str, ...]:
    """Full SHAs of the commits reachable from HEAD but not from ``base`` (``base..HEAD``).

    Raises ``OSError`` when git cannot be run and ``subprocess.CalledProcessError`` when git
    fails (not a repository, or ``base`` unknown); the caller decides what that means.
    """
    listing = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "rev-list", f"{base}..HEAD"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(listing.split())


def commits_between(base: str, heads: Sequence[str], repo: Path = Path()) -> tuple[str, ...]:
    """Full SHAs reachable from any of ``heads`` but not from ``base``, each once.

    S2.7 runs as a parent branch with a branch per track stacked on it (decision 0102); a
    stage's spend must count them all, so this takes several heads where
    :func:`commits_since` takes HEAD. Raises as :func:`commits_since` does.
    """
    listing = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "rev-list", *heads, f"^{base}"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(dict.fromkeys(listing.split()))


def branches_containing(commit: str, repo: Path = Path()) -> tuple[str, ...]:
    """Local branches whose history contains ``commit``, by short name (decision 0102)."""
    listing = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [  # noqa: S607 -- git on PATH
            "git",
            "-C",
            str(repo),
            "for-each-ref",
            "--contains",
            commit,
            "--format=%(refname:short)",
            "refs/heads",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(listing.split())
