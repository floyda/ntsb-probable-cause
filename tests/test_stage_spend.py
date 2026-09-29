"""scripts/stage_spend.py: S2.7's spend against its $25 line (decision 0098 item 6)."""

from pathlib import Path

import pytest
from scripts import stage_spend as ss


def test_report_passes_under_the_line_and_refuses_over_it() -> None:
    text, over = ss.report(runs=10.0, spend=5.0, estimate=9.0)
    assert not over
    assert "S2.7 spend so far: $15.00" in text
    text, over = ss.report(runs=10.0, spend=5.0, estimate=10.01)
    assert over
    assert "refused" in text


def test_main_exits_1_over_the_line_and_names_the_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(
        ss, "stage_branches", lambda repo=Path(): ("s27-coding-guidance", "s27-guidance")
    )
    monkeypatch.setattr(ss, "stage_commits", lambda branches, repo=Path(): frozenset())
    monkeypatch.setattr(ss, "stage_spent", lambda runs_dir, commits: (24.0, 0.5))
    assert ss.main(["--estimate", "0.40"]) == 0
    assert "branches counted: s27-coding-guidance, s27-guidance" in capsys.readouterr().out
    assert ss.main(["--estimate", "0.60"]) == 1


def test_stage_branches_are_s27_branches_grown_from_the_first_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 0107: a later stage cut from an S2.7 branch also holds the first commit, and
    main holds it once merged; neither is S2.7's spend."""
    monkeypatch.setattr(
        ss,
        "branches_containing",
        lambda commit, repo=Path(): (
            (
                "main",
                "s27-coding-guidance",
                "s27-guidance",
                "s27-transcriber",
                "s28-coding-lookup",
                "s3-probe",
            )
            if commit == "94f5d42"
            else ()
        ),
    )
    assert ss.stage_branches() == ("s27-coding-guidance", "s27-guidance", "s27-transcriber")


def test_stage_commits_counts_the_stage_branches_only_not_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 0107: HEAD is not counted, so running this from another stage's branch cannot
    count that stage's commits."""
    asked: list[list[str]] = []

    def _fake_commits_between(base: str, heads: list[str], repo: Path = Path()) -> tuple[str, ...]:
        asked.append([base, *heads])
        return ("c1",)

    monkeypatch.setattr(ss, "commits_between", _fake_commits_between)
    assert ss.stage_commits(("s27-coding-guidance", "s27-transcriber")) == frozenset({"c1"})
    assert asked == [["971ee40", "s27-coding-guidance", "s27-transcriber"]]
    assert ss.stage_commits(()) == frozenset()
