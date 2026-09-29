"""scripts/round1_report.py: Round 1's reading rule (decision 0096 item 5)."""

from dataclasses import replace
from pathlib import Path

import pytest
from scripts import round1_report as r1
from tests.test_occurrence_misses import _SCORES, _case, _write_run  # shared builders

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl, write_jsonl


def _p(low: float, mean: float = 0.05) -> r1.Paired:
    return r1.Paired(mean=mean, low=low, high=mean + 0.05, n=399, fixes=30, breaks=10)


def test_paired_counts_fixes_and_breaks() -> None:
    a = {"C1": True, "C2": False, "C3": True}
    b = {"C1": False, "C2": True, "C3": True, "C4": True}
    result = r1.paired(a, b)
    assert (result.n, result.fixes, result.breaks) == (3, 1, 1)


def test_the_rule_wins_when_no_model_beats_it() -> None:
    results = {
        "A": {
            "rule": (_p(0.01), None),
            "luna": (_p(0.02), _p(-0.01)),
            "jev": (_p(-0.01), _p(-0.03)),
        },
        "B": {
            "rule": (_p(0.02), None),
            "luna": (_p(0.03), _p(0.00)),
            "jev": (_p(-0.02), _p(-0.04)),
        },
    }
    assert r1.choose(results) == "rule"


def test_a_model_is_chosen_only_when_it_beats_the_rule_on_both_sets() -> None:
    results = {
        "A": {"rule": (_p(0.01), None), "luna": (_p(0.05, 0.10), _p(0.01, 0.04))},
        "B": {"rule": (_p(0.02), None), "luna": (_p(0.06, 0.11), _p(0.02, 0.05))},
    }
    assert r1.choose(results) == "luna"


def test_nothing_is_kept_when_nothing_works_on_both_sets() -> None:
    results = {"A": {"rule": (_p(0.01), None)}, "B": {"rule": (_p(-0.01), None)}}
    assert r1.choose(results) == "no check"


def test_push_counts_changes_toward_a_more_common_option() -> None:
    base = _case("C1", ("452240",), ("452241",))
    last = base.steps[-1]
    moved = last.model_copy(
        update={
            "step": 1,
            "tool": "ordering_check",
            "arguments": {"ranking": ["452240"], "toward_more_common": True},
            "hypothesis": last.hypothesis.model_copy(
                update={
                    "occurrence": (
                        last.hypothesis.occurrence[0].model_copy(update={"event": "240"}),
                    )
                }
            ),
        }
    )
    checked = base.model_copy(
        update={"steps": (last, moved), "scores": replace(_SCORES, occurrence_top1=True)}
    )
    assert r1.push([checked], {"C1": False}) == (1, 1, 1, 0)  # changed, toward, fixes, breaks


def test_a_source_recorded_on_a_held_out_sample_is_refused_before_its_cases_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One addition beyond the brief (2026-09-27): every sibling script on this branch
    (``judge_outcomes._load``, ``round0_handread._run``) refuses a non-development run by
    reading ``run.jsonl``'s ``RunRecord`` and checking ``record.sample.startswith("dev")``
    before ``cases.jsonl`` is ever read, on top of the run-id substring check. This proves
    ``round1_report`` does the same for each ``--answers`` source: no ``cases.jsonl`` is
    written for ``renamed-run``, so a check that skipped this ordering would fail with a
    missing-file error instead of a clean refusal.
    """
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    _write_run(runs_dir, "renamed-run", sample="heldout-400")  # no cases.jsonl written
    with pytest.raises(SystemExit, match="held-out run"):
        r1.main(["--answers", "renamed-run", "other-run"])


def test_a_sealed_source_is_refused_until_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    _write_run(runs_dir, "sealed-run", sample="dev-seal-400")  # no cases.jsonl written
    with pytest.raises(SystemExit, match="sealed"):
        r1.main(["--answers", "sealed-run", "other-run"])


def test_a_source_that_has_not_finished_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    folder = _write_run(runs_dir, "dead-run")
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    (folder / "run.jsonl").unlink()  # write_jsonl appends; replace, not add, the row
    write_jsonl(folder / "run.jsonl", [record.model_copy(update={"finished": None})])
    with pytest.raises(SystemExit, match="has not finished"):
        r1.main(["--answers", "dead-run", "other-run"])


def test_main_refuses_answer_sets_on_different_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    _write_run(runs_dir, "source-a", arm="B")
    _write_run(runs_dir, "source-b", arm="ceiling")
    with pytest.raises(SystemExit, match="arm"):
        r1.main(["--answers", "source-a", "source-b"])


def test_main_prints_the_outcome_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    for source in ("source-a", "source-b"):
        folder = _write_run(runs_dir, source)
        cases = [
            _case("C1", ("552240",), ("552240",)).model_copy(
                update={"scores": replace(_SCORES, occurrence_top1=True)}
            ),
            _case("C2", ("552230",), ("552241",)),
        ]
        write_jsonl(folder / "cases.jsonl", cases)
        rule_folder = runs_dir / r1.derived_id(source, "rule")
        write_jsonl(rule_folder / "cases.jsonl", cases)
    assert r1.main(["--answers", "source-a", "source-b"]) == 0
    out = capsys.readouterr().out
    assert "outcome (decision 0096 item 5):" in out
    assert "- luna: not run" in out
    assert "- jev: not run" in out
