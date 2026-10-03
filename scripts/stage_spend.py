"""S2.7's spend, counted by commit on S2.7's own branches, against its $25 line.

Status
    Live check for S2.7 (decision 0098 item 6). Every paid ``make`` target of both tracks runs
    it first with the step's estimate; it exits 1 when the stage's spend plus the estimate
    would pass the line. Free: reads run folders only.

Why
    The line is the stage's stop rule's second half. Spend is counted by commit because S2.6
    found a date filter caught another stage's runs. S2.7 is a parent branch with a branch per
    track stacked on it (decision 0102); until the tracks merge back, neither sees the other's
    commits, so the count takes every local branch whose history holds S2.7's first commit and
    whose name starts ``s27-`` -- the parent and its tracks, not a later stage cut from one
    (decision 0107) -- and prints them.

Usage
    uv run python -m scripts.stage_spend [--estimate USD]
"""

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.gitinfo import branches_containing, commits_between
from ntsb_probable_cause.scoring.budget import stage_spent
from ntsb_probable_cause.settings import Settings

STAGE_BASE = "971ee40"
# S2.7's first commit (the specification's first draft, on the parent s27-coding-guidance).
# Every branch whose history holds it grew from the parent (decision 0102).
STAGE_FIRST = "94f5d42"
STAGE_LINE_USD = 25.0
# main holds every stage once merged, and later stages' commits too; it is never counted.
EXCLUDED_BRANCHES = frozenset({"main"})
# Decision 0107: a later stage cut from an S2.7 branch (s28-coding-lookup, s3-probe) also
# holds the first commit; only branches named for S2.7 are its own.
STAGE_BRANCH_PREFIX = "s27-"


def _git_error(error: Exception) -> ConfigurationError:
    return ConfigurationError(f"stage_spend: git could not list the stage's commits: {error}")


def stage_branches(repo: Path = Path()) -> tuple[str, ...]:
    """S2.7's branches: those holding its first commit and named for it (decisions 0102, 0107)."""
    try:
        found = branches_containing(STAGE_FIRST, repo)
    except (OSError, subprocess.CalledProcessError) as error:
        raise _git_error(error) from error
    return tuple(
        name
        for name in found
        if name not in EXCLUDED_BRANCHES and name.startswith(STAGE_BRANCH_PREFIX)
    )


def stage_commits(branches: Sequence[str], repo: Path = Path()) -> frozenset[str]:
    """Every commit reachable from a stage branch and not from the base.

    HEAD is not counted (decision 0107): run from another stage's branch, it would count that
    stage's commits. Every S2.7 commit is on an S2.7 branch.
    """
    if not branches:
        return frozenset()
    try:
        return frozenset(commits_between(STAGE_BASE, list(branches), repo))
    except (OSError, subprocess.CalledProcessError) as error:
        raise _git_error(error) from error


def report(*, runs: float, spend: float, estimate: float) -> tuple[str, bool]:
    """The printed lines, and whether the step is refused."""
    spent = runs + spend
    over = spent + estimate > STAGE_LINE_USD
    lines = [
        f"S2.7 spend so far: ${spent:.2f} (${runs:.2f} evaluation runs, ${spend:.2f} "
        f"preparation spend rows; counted by commit from {STAGE_BASE} on S2.7's own branches, "
        "decision 0107)",
        f"this step's estimate: ${estimate:.2f}; the stage line: ${STAGE_LINE_USD:.2f}",
        (
            f"refused: ${spent + estimate:.2f} would pass the line (decision 0098 item 6)"
            if over
            else f"within the line: ${STAGE_LINE_USD - spent - estimate:.2f} left after this step"
        ),
    ]
    return "\n".join(lines), over


def main(argv: Sequence[str] | None = None) -> int:
    """Print the stage's spend; exit 1 if the estimate would pass the line."""
    parser = argparse.ArgumentParser(prog="stage_spend")
    parser.add_argument("--estimate", type=float, default=0.0, metavar="USD")
    args = parser.parse_args(argv)
    branches = stage_branches()
    runs, spend = stage_spent(Settings().runs_dir, stage_commits(branches))
    text, over = report(runs=runs, spend=spend, estimate=args.estimate)
    print(f"branches counted: {', '.join(branches) or 'none found'}")
    print(text)
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
