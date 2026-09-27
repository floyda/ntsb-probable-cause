"""gitinfo: commits reachable from several heads, branches, and committed files (S2.7)."""

import subprocess
from pathlib import Path

from ntsb_probable_cause import gitinfo


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [  # noqa: S607 -- git on PATH
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def test_commits_between_counts_every_head_once_and_never_the_base(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    one = _commit(repo, "one.txt")
    _git(repo, "checkout", "-q", "-b", "other")
    two = _commit(repo, "two.txt")
    _git(repo, "checkout", "-q", "main")
    three = _commit(repo, "three.txt")
    found = gitinfo.commits_between(base, ["HEAD", "other"], repo)
    assert set(found) == {one, two, three}
    assert base not in found
    assert len(found) == len(set(found))


def test_branches_containing_finds_every_branch_grown_from_a_commit(tmp_path: Path) -> None:
    repo, _base = _repo(tmp_path)
    first = _commit(repo, "spec.txt")  # the stage's first commit, on the parent
    _git(repo, "checkout", "-q", "-b", "s27-guidance")
    _commit(repo, "track1.txt")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "unrelated", _base)  # cut before the stage began
    assert set(gitinfo.branches_containing(first, repo)) == {"main", "s27-guidance"}
