"""scripts/stage_spend.py: a stage's spend against its line (0098 item 6, 0107, 0128)."""

from pathlib import Path

import pytest
from scripts import stage_spend as ss

from ntsb_probable_cause.errors import ConfigurationError

S27 = ss.STAGES["s27"]
S3 = ss.STAGES["s3"]


def test_the_stage_table_holds_s27_as_it_was_and_s3_as_decision_0128_fixes_it() -> None:
    assert set(ss.STAGES) == {"s27", "s3", "s33"}
    assert ss.STAGES["s27"] == ss.Stage(
        "S2.7", base="971ee40", first="94f5d42", line_usd=25.0, prefix="s27-"
    )
    assert (ss.STAGES["s27"].line_rule, ss.STAGES["s27"].count_rule) == (
        "decision 0098 item 6",
        "decision 0107",
    )
    assert ss.STAGES["s3"] == ss.Stage(
        "S3",
        base="4178ca1",
        first="777c2a5",
        line_usd=50.0,
        prefix="s3-",
        line_rule="decision 0128 item 2",
        count_rule="decisions 0128 item 2, 0135",
    )
    assert frozenset({"main"}) == ss.EXCLUDED_BRANCHES


def test_s27s_lines_are_byte_identical_to_before_s3() -> None:
    """S2.7's output is unchanged by the per-stage citations (its rules are 0098 and 0107)."""
    text, over = ss.report(S27, runs=10.0, spend=5.0, estimate=10.01)
    assert over
    assert text == (
        "S2.7 spend so far: $15.00 ($10.00 evaluation runs, $5.00 preparation spend rows; "
        "counted by commit from 971ee40 on S2.7's own branches, decision 0107)\n"
        "this step's estimate: $10.01; the stage line: $25.00\n"
        "refused: $25.01 would pass the line (decision 0098 item 6)"
    )
    text, over = ss.report(S27, runs=10.0, spend=5.0, estimate=9.0)
    assert not over
    assert text.splitlines()[-1] == "within the line: $1.00 left after this step"


def test_s3s_lines_cite_s3s_own_decision() -> None:
    """S3's line is decision 0128's (item 2), counted by its rule; S2.7's citations are not
    S3's, so neither appears on S3's lines."""
    text, over = ss.report(S3, runs=30.0, spend=10.0, estimate=10.01)
    assert over
    assert text == (
        "S3 spend so far: $40.00 ($30.00 evaluation runs, $10.00 preparation spend rows; "
        "counted by commit from 4178ca1 on S3's own branches, decisions 0128 item 2, 0135)\n"
        "this step's estimate: $10.01; the stage line: $50.00\n"
        "refused: $50.01 would pass the line (decision 0128 item 2)"
    )
    assert "0098" not in text
    assert "0107" not in text


def test_report_passes_under_the_line_and_refuses_over_it() -> None:
    text, over = ss.report(S27, runs=10.0, spend=5.0, estimate=9.0)
    assert not over
    assert "S2.7 spend so far: $15.00" in text
    assert "the stage line: $25.00" in text
    text, over = ss.report(S27, runs=10.0, spend=5.0, estimate=10.01)
    assert over
    assert "refused" in text


def test_report_for_s3_names_s3_and_its_own_line_and_base() -> None:
    text, over = ss.report(S3, runs=30.0, spend=10.0, estimate=9.0)
    assert not over
    assert "S3 spend so far: $40.00" in text
    assert "the stage line: $50.00" in text
    assert "from 4178ca1" in text
    assert "$1.00 left after this step" in text
    text, over = ss.report(S3, runs=30.0, spend=10.0, estimate=10.01)
    assert over
    assert "refused" in text


def test_main_exits_1_over_the_line_and_names_the_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no ``--stage`` the command is S2.7's, as the ``stage-spend`` target always was."""
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(
        ss, "stage_branches", lambda stage, repo=Path(): ("s27-coding-guidance", "s27-guidance")
    )
    monkeypatch.setattr(ss, "stage_commits", lambda stage, branches, repo=Path(): frozenset())
    monkeypatch.setattr(ss, "stage_spent", lambda runs_dir, commits: (24.0, 0.5))
    assert ss.main(["--estimate", "0.40"]) == 0
    out = capsys.readouterr().out
    assert "branches counted: s27-coding-guidance, s27-guidance" in out
    assert "S2.7 spend so far: $24.50" in out
    assert ss.main(["--estimate", "0.60"]) == 1


def test_main_takes_a_stage_and_uses_that_stages_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    asked: list[str] = []

    def _branches(stage: ss.Stage, repo: Path = Path()) -> tuple[str, ...]:
        asked.append(stage.name)
        return ("s3-agent-loop",)

    monkeypatch.setattr(ss, "stage_branches", _branches)
    monkeypatch.setattr(ss, "stage_commits", lambda stage, branches, repo=Path(): frozenset())
    monkeypatch.setattr(ss, "stage_spent", lambda runs_dir, commits: (40.0, 0.5))
    assert ss.main(["--stage", "s3", "--estimate", "9.0"]) == 0
    out = capsys.readouterr().out
    assert asked == ["S3"]
    assert "branches counted: s3-agent-loop" in out
    assert "S3 spend so far: $40.50" in out
    assert ss.main(["--stage", "s3", "--estimate", "9.60"]) == 1


def test_main_refuses_an_unknown_stage() -> None:
    with pytest.raises(SystemExit):
        ss.main(["--stage", "s4"])


def test_main_says_none_found_when_no_branch_holds_the_first_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(ss, "stage_branches", lambda stage, repo=Path(): ())
    assert ss.main(["--stage", "s3"]) == 0
    assert "branches counted: none found" in capsys.readouterr().out


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
    assert ss.stage_branches(S27) == ("s27-coding-guidance", "s27-guidance", "s27-transcriber")


def test_s3_branches_hold_its_first_commit_and_are_named_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 0128 item 3: the probe's branch has the prefix but not S3's first commit, so the
    probe's spend is outside the line; an S2.7 branch is not S3's."""
    heads = {
        "777c2a5": ("main", "s3-agent-loop", "s3-loop-tools", "s27-coding-guidance"),
        "94f5d42": ("main", "s27-coding-guidance", "s3-probe", "s3-agent-loop"),
    }
    monkeypatch.setattr(
        ss, "branches_containing", lambda commit, repo=Path(): heads.get(commit, ())
    )
    assert ss.stage_branches(S3) == ("s3-agent-loop", "s3-loop-tools")
    assert "s3-probe" not in ss.stage_branches(S3)
    assert ss.stage_branches(S27) == ("s27-coding-guidance",)


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
    assert ss.stage_commits(S27, ("s27-coding-guidance", "s27-transcriber")) == frozenset({"c1"})
    assert ss.stage_commits(S3, ("s3-agent-loop",)) == frozenset({"c1"})
    assert asked == [
        ["971ee40", "s27-coding-guidance", "s27-transcriber"],
        ["4178ca1", "s3-agent-loop"],
    ]
    assert ss.stage_commits(S3, ()) == frozenset()


def test_a_git_failure_is_a_configuration_error_not_a_zero_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_git(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        raise OSError("git not found")

    monkeypatch.setattr(ss, "branches_containing", _no_git)
    monkeypatch.setattr(ss, "commits_between", _no_git)
    with pytest.raises(ConfigurationError, match="git could not list"):
        ss.stage_branches(S3)
    with pytest.raises(ConfigurationError, match="git could not list"):
        ss.stage_commits(S3, ("s3-agent-loop",))


def test_s33_is_s3s_branches_against_the_line_left_after_s31_and_s32() -> None:
    """Decision 0163: S3.3's own $10 is S3's line less S3.1's and S3.2's $11.46."""
    assert ss.STAGES["s33"] == ss.Stage(
        "S3.3",
        base="4178ca1",
        first="777c2a5",
        line_usd=21.46,
        prefix="s3-",
        line_rule="decision 163",
        count_rule="decisions 0128 item 2, 0135",
    )
    text, over = ss.report(ss.STAGES["s33"], runs=11.46, spend=0.0, estimate=10.01)
    assert over
    assert "refused: $21.47 would pass the line (decision 163)" in text
