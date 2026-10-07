"""A stage's spend, counted by commit on the stage's own branches, against the stage's line.

Status
    Live check for S2.7 (decision 0098 item 6), S3 (decision 0128 item 2) and S3.3 (decision 163),
    chosen with ``--stage`` (default ``s27``). Every paid ``make`` target of a stage runs it first
    with the step's estimate; it exits 1 when the stage's spend plus the estimate would pass the
    line.
    Free: reads run folders only.

Why
    The line is the stage's stop rule's second half. Spend is counted by commit because S2.6
    found a date filter caught another stage's runs. A stage may be a parent branch with a
    branch per track stacked on it (decision 0102); until the tracks merge back, neither sees
    the other's commits, so the count takes every local branch whose history holds the stage's
    first commit and whose name starts with the stage's prefix -- the parent and its tracks, not
    a later stage cut from one (decision 0107) -- and prints them. S3's learning probe branch
    (``s3-probe``) has the prefix but not S3's first commit, so its spend is outside S3's line
    (decision 0128 item 3).

Usage
    uv run python -m scripts.stage_spend [--stage {s27,s3,s33}] [--estimate USD]
"""

import argparse
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.gitinfo import branches_containing, commits_between
from ntsb_probable_cause.scoring.budget import stage_spent
from ntsb_probable_cause.settings import Settings


@dataclass(frozen=True)
class Stage:
    """One stage's spend line and the rule that finds its commits."""

    name: str  # printed: "S2.7", "S3"
    base: str  # the merge the stage branched from
    first: str  # the stage's first commit; a branch counts only if it holds it
    line_usd: float
    prefix: str  # branch-name prefix a counted branch must have (decision 0107)
    # The decisions the printed lines cite: the one that sets the stage's line (the refused
    # line) and the one that says how its spend is counted. S2.7's are the defaults.
    line_rule: str = "decision 0098 item 6"
    count_rule: str = "decision 0107"


# S2.7's first commit is the specification's first draft, on the parent s27-coding-guidance;
# every branch whose history holds it grew from the parent (decision 0102). S3's first commit
# is the draft specification, on s3-agent-loop (decision 0128 item 2); s3-probe, the learning
# probe's branch, was cut before it. S3's line, and how it is counted, are 0128 item 2's.
STAGES: Mapping[str, Stage] = {
    "s27": Stage("S2.7", base="971ee40", first="94f5d42", line_usd=25.0, prefix="s27-"),
    "s3": Stage(
        "S3",
        base="4178ca1",
        first="777c2a5",
        line_usd=50.0,
        prefix="s3-",
        line_rule="decision 0128 item 2",
        count_rule="decisions 0128 item 2, 0135",
    ),
    # S3.3's own $10 is S3's line less S3.1's and S3.2's $11.46 (decision 163): it counts the same
    # commits as "s3" (S3.1, S3.2 and S3.3 grew from the same first commit) against $21.46.
    "s33": Stage(
        "S3.3",
        base="4178ca1",
        first="777c2a5",
        line_usd=21.46,
        prefix="s3-",
        line_rule="decision 163",
        count_rule="decisions 0128 item 2, 0135",
    ),
}
# main holds every stage once merged, and later stages' commits too; it is never counted.
EXCLUDED_BRANCHES = frozenset({"main"})


def _git_error(error: Exception) -> ConfigurationError:
    return ConfigurationError(f"stage_spend: git could not list the stage's commits: {error}")


def stage_branches(stage: Stage, repo: Path = Path()) -> tuple[str, ...]:
    """The stage's branches: those holding its first commit and named for it (0102, 0107)."""
    try:
        found = branches_containing(stage.first, repo)
    except (OSError, subprocess.CalledProcessError) as error:
        raise _git_error(error) from error
    return tuple(
        name for name in found if name not in EXCLUDED_BRANCHES and name.startswith(stage.prefix)
    )


def stage_commits(stage: Stage, branches: Sequence[str], repo: Path = Path()) -> frozenset[str]:
    """Every commit reachable from a stage branch and not from the stage's base.

    HEAD is not counted (decision 0107): run from another stage's branch, it would count that
    stage's commits. Every commit of a stage is on one of the stage's branches.
    """
    if not branches:
        return frozenset()
    try:
        return frozenset(commits_between(stage.base, list(branches), repo))
    except (OSError, subprocess.CalledProcessError) as error:
        raise _git_error(error) from error


def report(stage: Stage, *, runs: float, spend: float, estimate: float) -> tuple[str, bool]:
    """The printed lines, and whether the step is refused."""
    spent = runs + spend
    over = spent + estimate > stage.line_usd
    lines = [
        f"{stage.name} spend so far: ${spent:.2f} (${runs:.2f} evaluation runs, ${spend:.2f} "
        f"preparation spend rows; counted by commit from {stage.base} on {stage.name}'s own "
        f"branches, {stage.count_rule})",
        f"this step's estimate: ${estimate:.2f}; the stage line: ${stage.line_usd:.2f}",
        (
            f"refused: ${spent + estimate:.2f} would pass the line ({stage.line_rule})"
            if over
            else f"within the line: ${stage.line_usd - spent - estimate:.2f} left after this step"
        ),
    ]
    return "\n".join(lines), over


def main(argv: Sequence[str] | None = None) -> int:
    """Print the stage's spend; exit 1 if the estimate would pass the line."""
    parser = argparse.ArgumentParser(prog="stage_spend")
    parser.add_argument("--stage", choices=sorted(STAGES), default="s27")
    parser.add_argument("--estimate", type=float, default=0.0, metavar="USD")
    args = parser.parse_args(argv)
    stage = STAGES[args.stage]
    branches = stage_branches(stage)
    runs, spend = stage_spent(Settings().runs_dir, stage_commits(stage, branches))
    text, over = report(stage, runs=runs, spend=spend, estimate=args.estimate)
    print(f"branches counted: {', '.join(branches) or 'none found'}")
    print(text)
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
