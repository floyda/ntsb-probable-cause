"""scripts/s3_case_groups.py: dev-400 sorted into always right, always wrong and flipping.

S3.1 plan Task 15. Synthetic run folders are built from ``CaseResult`` and ``RunRecord``
objects. Offline.
"""

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import s3_case_groups as cg
from tests.test_occurrence_misses import _SCORES, _case

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl

_WHEN = datetime(2026, 10, 2, 9, 30, 15, tzinfo=UTC)
# Case ids no other text in the report can contain, so "no case id in the output" is testable.
_IDS = tuple(f"ZQX{n:03d}" for n in range(8))
# Four fatal cases (the first four), four not.
_FATAL = frozenset(_IDS[:4])


def _record(run_id: str, *, arm: str, **changes: object) -> RunRecord:
    record = RunRecord(
        run_id=run_id,
        sample="dev-400",
        arm=arm,
        evidence_version="v1",
        exclusions=(),
        includes=(),
        prompt_version="p",
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.15,
        budget_usd=40.0,
        commit_sha="abc1234",
        dirty=False,
        started=_WHEN,
        finished=_WHEN,
        cases=len(_IDS),
        cost_usd=0.5,
    )
    return record.model_copy(update=changes)


def _cases(outcomes: str, ids: Sequence[str] = _IDS) -> list[CaseResult]:
    """One case per letter: ``R`` right on top-1, ``W`` wrong, ``F`` failed (no score)."""
    cases = []
    for case_id, outcome in zip(ids, outcomes, strict=True):
        if outcome == "F":
            case = _case(case_id, ("452240",), (), scored=False).model_copy(
                update={"failure": "failed: coding"}
            )
        else:
            case = _case(case_id, ("452240",), ("452240",)).model_copy(
                update={"scores": replace(_SCORES, occurrence_top1=outcome == "R")}
            )
        cases.append(case.model_copy(update={"fatal": case_id in _FATAL}))
    return cases


def _write(
    runs: Path,
    run_id: str,
    cases: Sequence[CaseResult],
    *,
    arm: str = "C",
    record: RunRecord | None = None,
) -> None:
    folder = runs / run_id
    write_jsonl(folder / "run.jsonl", [record or _record(run_id, arm=arm)])
    write_jsonl(folder / "cases.jsonl", cases)


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, and ``dev-400`` taken to be the synthetic ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _main(argv: Sequence[str]) -> int:
    return cg.main(argv, now=lambda: _WHEN)


# --------------------------------------------------------------------------------------------
# The groups
# --------------------------------------------------------------------------------------------


class TestGroup:
    def test_right_in_every_run_is_always_right(self) -> None:
        assert cg.group([1.0, 1.0, 1.0]) == "always right"

    def test_wrong_in_every_run_is_always_wrong(self) -> None:
        assert cg.group([0.0, 0.0]) == "always wrong"

    def test_right_in_some_and_wrong_in_others_is_flipping(self) -> None:
        assert cg.group([0.0, 1.0]) == "flipping"

    def test_a_failure_counts_as_wrong(self, runs: Path) -> None:
        # Right in one run and failed in the other: flipping. Failed in both: always wrong.
        _write(runs, "run-a", _cases("RFRRWWWW"))
        _write(runs, "run-b", _cases("RRFRWWWW"))
        loaded = [cg.load("run-a"), cg.load("run-b")]
        assigned = cg.assign(loaded)
        assert assigned["ZQX000"] == "always right"
        assert assigned["ZQX001"] == "flipping"
        assert assigned["ZQX002"] == "flipping"
        assert assigned["ZQX004"] == "always wrong"

    def test_a_case_failed_in_every_run_is_always_wrong(self, runs: Path) -> None:
        _write(runs, "run-a", _cases("FWWWWWWW"))
        _write(runs, "run-b", _cases("FWWWWWWW"))
        assert cg.assign([cg.load("run-a"), cg.load("run-b")])["ZQX000"] == "always wrong"


# --------------------------------------------------------------------------------------------
# The whole report, on four synthetic runs
# --------------------------------------------------------------------------------------------

_RUN_C1 = "20261001T201506-fd6053f-dev-400-C"
_RUN_C2 = "20261001T201648-fd6053f-dev-400-C"
_RUN_B1 = "20260926T082427-d19aafa-dev-400-B"
_RUN_B2 = "20260927T111202-fbab38a-dev-400-B"

# Cases 0-3 fatal, 4-7 not. Per case, across C1 C2 | B1 B2:
#   0: R R | R R  -> C always right, B always right, all always right
#   1: R R | W W  -> C always right, B always wrong, all flipping
#   2: W W | R R  -> C always wrong, B always right, all flipping
#   3: W F | W W  -> C always wrong, B always wrong, all always wrong (failed in one run)
#   4: R W | R W  -> C flipping, B flipping, all flipping
#   5: F F | W W  -> C always wrong, B always wrong, all always wrong (failed in both C runs)
#   6: W W | W W  -> always wrong everywhere
#   7: R R | R F  -> C always right, B flipping, all flipping (failed in one run)
_C1, _C2 = "RRWWRFWR", "RRWFWFWR"
_B1, _B2 = "RWRWRWWR", "RWRWWWWF"

_EXPECTED = f"""\
S3.1 case groups on dev-400 (scripts/s3_case_groups.py; plan Task 15, spec §10.3)
Counts only: no case number. Every figure is printed with its denominator.
Occurrence top-1 in each run. A case that failed in a run, or holds no score there, counts as \
wrong in that run (decision 0136 item 1).
run 1 = {_RUN_C1} (arm C)
run 2 = {_RUN_C2} (arm C)
run 3 = {_RUN_B1} (arm B)
run 4 = {_RUN_B2} (arm B)

## all 4 runs (runs 1, 2, 3, 4)

always right: 1 of 8 (12.5%)
always wrong: 3 of 8 (37.5%)
flipping: 4 of 8 (50.0%)
- fatal: always right 1 of 4 (25.0%), always wrong 1 of 4 (25.0%), flipping 2 of 4 (50.0%)
- non-fatal: always right 0 of 4 (0.0%), always wrong 2 of 4 (50.0%), flipping 2 of 4 (50.0%)
failed in at least one of these runs: 3 of 8 (37.5%); in every one: 0 of 8 (0.0%)

## arm C runs only (runs 1, 2)

always right: 3 of 8 (37.5%)
always wrong: 4 of 8 (50.0%)
flipping: 1 of 8 (12.5%)
- fatal: always right 2 of 4 (50.0%), always wrong 2 of 4 (50.0%), flipping 0 of 4 (0.0%)
- non-fatal: always right 1 of 4 (25.0%), always wrong 2 of 4 (50.0%), flipping 1 of 4 (25.0%)
failed in at least one of these runs: 2 of 8 (25.0%); in every one: 1 of 8 (12.5%)

## arm B runs only (runs 3, 4)

always right: 2 of 8 (25.0%)
always wrong: 4 of 8 (50.0%)
flipping: 2 of 8 (25.0%)
- fatal: always right 2 of 4 (50.0%), always wrong 2 of 4 (50.0%), flipping 0 of 4 (0.0%)
- non-fatal: always right 0 of 4 (0.0%), always wrong 2 of 4 (50.0%), flipping 2 of 4 (50.0%)
failed in at least one of these runs: 1 of 8 (12.5%); in every one: 0 of 8 (0.0%)

## arm C group against arm B group (cases; each row an arm C group, split by arm B group)

all cases (8):
- arm C always right: arm B always right 1, always wrong 1, flipping 1; 3 of 8 cases
- arm C always wrong: arm B always right 1, always wrong 3, flipping 0; 4 of 8 cases
- arm C flipping: arm B always right 0, always wrong 0, flipping 1; 1 of 8 cases
fatal cases (4):
- arm C always right: arm B always right 1, always wrong 1, flipping 0; 2 of 4 cases
- arm C always wrong: arm B always right 1, always wrong 1, flipping 0; 2 of 4 cases
- arm C flipping: arm B always right 0, always wrong 0, flipping 0; 0 of 4 cases
non-fatal cases (4):
- arm C always right: arm B always right 0, always wrong 0, flipping 1; 1 of 4 cases
- arm C always wrong: arm B always right 0, always wrong 2, flipping 0; 2 of 4 cases
- arm C flipping: arm B always right 0, always wrong 0, flipping 1; 1 of 4 cases

case lists (case ids; under NTSB_RUNS_DIR, never committed): \
s3-case-groups/20261002T093015/groups.json
"""


def _four(runs: Path) -> list[str]:
    _write(runs, _RUN_C1, _cases(_C1))
    _write(runs, _RUN_C2, _cases(_C2))
    _write(runs, _RUN_B1, _cases(_B1), arm="B")
    _write(runs, _RUN_B2, _cases(_B2), arm="B")
    return [_RUN_C1, _RUN_C2, _RUN_B1, _RUN_B2]


class TestTheReport:
    def test_the_whole_report(self, runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _main(_four(runs)) == 0
        assert capsys.readouterr().out == _EXPECTED

    def test_no_case_id_is_printed(self, runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _main(_four(runs)) == 0
        printed = capsys.readouterr().out
        assert "ZQX" not in printed

    def test_out_writes_the_same_text(
        self, runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "results" / "s3-case-groups-dev.txt"
        assert _main([*_four(runs), "--out", str(out)]) == 0
        assert out.read_text() == capsys.readouterr().out

    def test_the_case_lists_go_under_the_runs_folder(self, runs: Path) -> None:
        assert _main(_four(runs)) == 0
        written = json.loads((runs / "s3-case-groups/20261002T093015/groups.json").read_text())
        assert written["sample"] == "dev-400"
        assert written["runs"] == [
            {"run_id": _RUN_C1, "arm": "C"},
            {"run_id": _RUN_C2, "arm": "C"},
            {"run_id": _RUN_B1, "arm": "B"},
            {"run_id": _RUN_B2, "arm": "B"},
        ]
        assert written["groups"]["all"] == {
            "always right": ["ZQX000"],
            "always wrong": ["ZQX003", "ZQX005", "ZQX006"],
            "flipping": ["ZQX001", "ZQX002", "ZQX004", "ZQX007"],
        }
        assert written["groups"]["arm C"]["always right"] == ["ZQX000", "ZQX001", "ZQX007"]
        assert written["groups"]["arm B"]["flipping"] == ["ZQX004", "ZQX007"]
        assert written["cross"]["arm C always wrong / arm B always right"] == ["ZQX002"]
        assert written["cross"]["arm C always right / arm B always wrong"] == ["ZQX001"]
        assert len(written["cross"]) == 9
        assert written["fatal"] == ["ZQX000", "ZQX001", "ZQX002", "ZQX003"]
        assert written["failed in at least one run"] == ["ZQX003", "ZQX005", "ZQX007"]

    def test_a_second_list_in_the_same_second_is_refused(self, runs: Path) -> None:
        ids = _four(runs)
        assert _main(ids) == 0
        with pytest.raises(SystemExit, match="already exists"):
            _main(ids)

    def test_runs_of_one_arm_only_print_no_cross_count(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(runs, _RUN_C1, _cases(_C1))
        _write(runs, _RUN_C2, _cases(_C2))
        assert _main([_RUN_C1, _RUN_C2]) == 0
        printed = capsys.readouterr().out
        assert "## arm C runs only (runs 1, 2)" in printed
        assert "## arm B runs only: no arm B run given" in printed
        assert "against arm B group" not in printed
        written = json.loads((runs / "s3-case-groups/20261002T093015/groups.json").read_text())
        assert set(written["groups"]) == {"all", "arm C"}
        assert written["cross"] == {}


# --------------------------------------------------------------------------------------------
# Refusals, before any case is read where they can be
# --------------------------------------------------------------------------------------------


class TestRefusals:
    def test_a_held_out_run_id_is_refused_before_its_folder_is_read(self, runs: Path) -> None:
        with pytest.raises(SystemExit, match="held-out"):
            _main(["20260101T000000-abc1234-heldout-400-C", _RUN_C1])

    def test_a_run_recorded_on_a_held_out_sample_is_refused_before_its_cases(
        self, runs: Path
    ) -> None:
        _write(
            runs, "renamed", _cases(_C1), record=_record("renamed", arm="C", sample="heldout-400")
        )
        _write(runs, _RUN_C1, _cases(_C1))
        (runs / "renamed" / "cases.jsonl").unlink()
        with pytest.raises(SystemExit, match="held-out"):
            _main(["renamed", _RUN_C1])

    @pytest.mark.parametrize("sample", ["dev-seal-400", "dev-seal-s3-400"])
    def test_a_sealed_sample_is_refused_even_once_its_registration_is_committed(
        self, runs: Path, monkeypatch: pytest.MonkeyPatch, sample: str
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
        _write(runs, "sealed", _cases(_C1), record=_record("sealed", arm="C", sample=sample))
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match="dev-400 only"):
            _main(["sealed", _RUN_C1])

    def test_a_sealed_sample_not_yet_opened_is_refused_as_sealed(
        self, runs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
        record = _record("sealed", arm="C", sample="dev-seal-s3-400")
        _write(runs, "sealed", _cases(_C1), record=record)
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match="sealed"):
            _main(["sealed", _RUN_C1])

    def test_a_case_outside_the_development_split_is_refused(self, runs: Path) -> None:
        cases = _cases(_C1)
        cases[0] = cases[0].model_copy(update={"split": "open"})
        _write(runs, "open-case", cases)
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match="outside the dev split"):
            _main(["open-case", _RUN_C1])

    @pytest.mark.parametrize("arm", ["A", "ceiling"])
    def test_an_arm_other_than_b_or_c_is_refused(self, runs: Path, arm: str) -> None:
        _write(runs, "other", _cases(_C1), arm=arm)
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match=f"arm {arm}"):
            _main(["other", _RUN_C1])

    def test_an_unfinished_run_is_refused(self, runs: Path) -> None:
        _write(runs, "dead", _cases(_C1), record=_record("dead", arm="C", finished=None))
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match="has not finished"):
            _main(["dead", _RUN_C1])

    def test_a_run_on_part_of_the_sample_is_refused(self, runs: Path) -> None:
        _write(runs, "part", _cases(_C1[:7], _IDS[:7]))
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match="not the whole of dev-400"):
            _main(["part", _RUN_C1])

    def test_a_run_naming_a_case_twice_is_refused(self, runs: Path) -> None:
        cases = _cases(_C1)
        _write(runs, "twice", [*cases, cases[0]])
        _write(runs, _RUN_C1, cases)
        with pytest.raises(SystemExit, match="not the whole of dev-400"):
            _main(["twice", _RUN_C1])

    def test_a_folder_with_no_run_record_is_refused(self, runs: Path) -> None:
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match=r"no run\.jsonl"):
            _main(["missing", _RUN_C1])

    def test_a_copied_folder_is_refused(self, runs: Path) -> None:
        _write(runs, "copy", _cases(_C1), record=_record(_RUN_C2, arm="C"))
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match="copied or renamed"):
            _main(["copy", _RUN_C1])

    def test_a_run_named_twice_is_refused(self, runs: Path) -> None:
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit, match="named twice"):
            _main([_RUN_C1, _RUN_C1])

    def test_one_run_is_not_enough(self, runs: Path) -> None:
        _write(runs, _RUN_C1, _cases(_C1))
        with pytest.raises(SystemExit) as raised:
            _main([_RUN_C1])
        assert raised.value.code == 2  # argparse's usage error
