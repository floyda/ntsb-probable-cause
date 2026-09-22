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
