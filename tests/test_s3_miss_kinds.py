"""scripts/exploratory/s3_miss_kinds.py: how the loop misses, counted over one case group.

S3.1 Task 15, exploratory. Synthetic run folders built from ``CaseResult`` and ``RunRecord``
objects, and a groups file as ``scripts/s3_case_groups.py`` writes it. Offline.
"""

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import miss_kinds
from scripts.exploratory import s3_miss_kinds as mk
from tests.test_occurrence_misses import _case
from tests.test_s3_case_groups import _record

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, write_jsonl

_RUN_A = "20261001T201506-fd6053f-dev-400-C"
_RUN_B = "20261001T201648-fd6053f-dev-400-C"
# Case ids no other text in the report can contain, so "no case id in the output" is testable.
_IDS = tuple(f"ZQX{n:03d}" for n in range(8))
_FATAL = frozenset(_IDS[:4])
_WRONG = _IDS[:7]
_RIGHT = _IDS[7:]


def _one(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    ntsb: tuple[str, ...],
    answer: tuple[str, ...],
    *,
    abstain: bool = False,
    failed: bool = False,
    flagged: tuple[str, ...] = (),
) -> CaseResult:
    case = _case(case_id, ntsb, answer, abstain=abstain, scored=not failed)
    return case.model_copy(
        update={"fatal": case_id in _FATAL, "verdict_findings_in_cause": flagged}
    )


def _run_a() -> list[CaseResult]:
    """Run a: every kind and every pattern at least once (cases 0-3 fatal)."""
    return [
        # same phase, different event; stall/spin against loss of control; generic consequence
        _one("ZQX000", ("552241", "552240"), ("552240", "500120")),
        # order; loss of control against stall/spin
        _one("ZQX001", ("552240",), ("500241", "552240")),
        # different phase and event; generic consequence (event 192); cause undetermined
        _one("ZQX002", ("552192",), ("500341",), flagged=("0500000000",)),
        # failed
        _one("ZQX003", ("552240",), (), failed=True),
        # different phase and event; generic consequence (event 000); cause undetermined
        _one("ZQX004", ("990000",), ("500240",)),
        # same event, different phase; no pattern
        _one("ZQX005", ("552240",), ("500240",)),
        # first code right, but abstained
        _one("ZQX006", ("552240",), ("552240",), abstain=True),
        # first code right: the "always right" case
        _one("ZQX007", ("552120",), ("552120",)),
    ]


def _run_b() -> list[CaseResult]:
    """Run b: the same cases, with case 0 now order and case 3 answered."""
    cases = _run_a()
    cases[0] = _one("ZQX000", ("552241", "552240"), ("552240", "552241"))
    cases[3] = _one("ZQX003", ("552240",), ("552241",))
    return cases


def _write(
    runs: Path,
    run_id: str,
    cases: Sequence[CaseResult],
    *,
    arm: str = "C",
    **changes: object,
) -> None:
    folder = runs / run_id
    shutil.rmtree(folder, ignore_errors=True)  # write_jsonl appends; a rewrite starts afresh
    write_jsonl(folder / "run.jsonl", [_record(run_id, arm=arm, **changes)])
    write_jsonl(folder / "cases.jsonl", cases)


def _groups(
    path: Path,
    *,
    runs: Sequence[str] = (_RUN_A, _RUN_B),
    wrong: Sequence[str] = _WRONG,
    sample: str = "dev-400",
) -> Path:
    data = {
        "sample": sample,
        "runs": [{"run_id": r, "arm": "C"} for r in runs],
        "groups": {
            "arm C": {"always right": list(_RIGHT), "always wrong": list(wrong), "flipping": []}
        },
    }
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run a and run b under the runs folder; ``dev-400`` taken to be the synthetic ids."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    _write(folder, _RUN_A, _run_a())
    _write(folder, _RUN_B, _run_b())
    return folder


@pytest.fixture
def groups(runs: Path) -> Path:
    """A groups file drawn over runs a and b, under the runs folder as the real one is."""
    path = runs / "s3-case-groups" / "20261002T065520" / "groups.json"
    path.parent.mkdir(parents=True)
    return _groups(path)


def _argv(groups: Path | None, *extra: str, group: str = "always wrong") -> list[str]:
    head = ["--runs", _RUN_A, _RUN_B, "--group", group]
    return [*head, *(["--groups", str(groups)] if groups is not None else []), *extra]


def _report(argv: Sequence[str], capsys: pytest.CaptureFixture[str]) -> str:
    assert mk.main(argv) == 0
    return capsys.readouterr().out


def _section(text: str, run: int) -> str:
    start = text.index(f"## run {run}:")
    end = text.find("## run", start + 1)
    return text[start : end if end != -1 else len(text)]


# --------------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------------


class TestReport:
    def test_the_head_names_the_group_its_source_and_the_runs(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        assert text.startswith("S3.1 miss kinds on dev-400 (scripts/exploratory/s3_miss_kinds.py")
        assert "sets no bar and tunes nothing" in text
        assert (
            "Cases: arm C, always wrong, from s3-case-groups/20261002T065520/groups.json: "
            "7 cases (4 fatal, 3 non-fatal)"
        ) in text
        assert f"run 1 = {_RUN_A}" in text
        assert f"run 2 = {_RUN_B}" in text

    def test_the_head_states_every_kind_and_pattern_with_the_labels_it_names(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        for kind, meaning in miss_kinds.KIND_MEANINGS.items():
            assert f"- {kind}: {meaning}" in text
        for pattern, meaning in miss_kinds.PATTERN_MEANINGS.items():
            assert f"- {pattern}: {meaning}" in text
        assert "240 Loss of control in flight" in text
        assert "241 Aerodynamic stall/spin" in text
        assert "0500000000 Not determined" in text

    def test_each_kind_is_counted_with_its_denominator_and_split_fatal_non_fatal(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        section = _section(_report(_argv(groups), capsys), 1)
        assert f"## run 1: {_RUN_A}" in section
        assert "Kinds, of the 7 cases (4 fatal, 3 non-fatal):" in section
        for line in (
            "- first code right: 1 of 7 (14.3%); fatal 0 of 4 (0.0%); non-fatal 1 of 3 (33.3%)",
            "- order: 1 of 7 (14.3%); fatal 1 of 4 (25.0%); non-fatal 0 of 3 (0.0%)",
            "- same phase, different event: 1 of 7 (14.3%); fatal 1 of 4 (25.0%); "
            "non-fatal 0 of 3 (0.0%)",
            "- same event, different phase: 1 of 7 (14.3%); fatal 0 of 4 (0.0%); "
            "non-fatal 1 of 3 (33.3%)",
            "- different phase and event: 2 of 7 (28.6%); fatal 1 of 4 (25.0%); "
            "non-fatal 1 of 3 (33.3%)",
            "- failed or not scored: 1 of 7 (14.3%); fatal 1 of 4 (25.0%); non-fatal 0 of 3 (0.0%)",
        ):
            assert line in section

    def test_each_pattern_is_counted_over_the_scored_cases(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        section = _section(_report(_argv(groups), capsys), 1)
        assert "Patterns, of the 6 scored cases (3 fatal, 3 non-fatal):" in section
        for line in (
            "- NTSB stall/spin first, loop loss of control first: 1 of 6 (16.7%); "
            "fatal 1 of 3 (33.3%); non-fatal 0 of 3 (0.0%)",
            "- NTSB loss of control first, loop stall/spin first: 1 of 6 (16.7%); "
            "fatal 1 of 3 (33.3%); non-fatal 0 of 3 (0.0%)",
            "- generic consequence: 3 of 6 (50.0%); fatal 2 of 3 (66.7%); non-fatal 1 of 3 (33.3%)",
            "- NTSB cause undetermined: 2 of 6 (33.3%); fatal 1 of 3 (33.3%); "
            "non-fatal 1 of 3 (33.3%)",
            "- abstained: 1 of 6 (16.7%); fatal 0 of 3 (0.0%); non-fatal 1 of 3 (33.3%)",
        ):
            assert line in section

    def test_the_ntsb_first_events_behind_the_generic_consequence_pattern(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        section = _section(_report(_argv(groups), capsys), 1)
        head = 'The NTSB\'s first events behind "generic consequence", of its 3 cases:'
        events = section[section.index(head) :].splitlines()[1:4]
        # By count, then by code: one case each, so 000, 192, 241.
        assert events == [
            "- 000 Unknown or undetermined: 1 (fatal 0, non-fatal 1)",
            "- 192 Fuel exhaustion: 1 (fatal 1, non-fatal 0)",
            "- 241 Aerodynamic stall/spin: 1 (fatal 1, non-fatal 0)",
        ]

    def test_each_run_is_counted_on_its_own(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        section = _section(_report(_argv(groups), capsys), 2)
        assert f"## run 2: {_RUN_B}" in section
        assert "- order: 2 of 7 (28.6%); fatal 2 of 4 (50.0%)" in section
        assert "- failed or not scored: 0 of 7 (0.0%)" in section
        assert "Patterns, of the 7 scored cases (4 fatal, 3 non-fatal):" in section

    def test_no_generic_case_says_none(
        self, runs: Path, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cases = [c for c in _run_a() if c.case_id not in {"ZQX000", "ZQX002", "ZQX004"}]
        plain = [_one(i, ("552120",), ("500120",)) for i in ("ZQX000", "ZQX002", "ZQX004")]
        _write(runs, _RUN_A, [*plain, *cases])
        section = _section(_report(_argv(groups), capsys), 1)
        assert 'behind "generic consequence", of its 0 cases:\n- none' in section

    def test_no_case_id_is_printed(self, groups: Path, capsys: pytest.CaptureFixture[str]) -> None:
        text = _report(_argv(groups), capsys)
        assert "ZQX" not in text

    def test_out_writes_the_same_text(
        self, groups: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "results" / "s3-miss-kinds-dev.txt"
        text = _report(_argv(groups, "--out", str(out)), capsys)
        assert out.read_text() == text

    def test_group_all_counts_every_case_and_reads_no_groups_file(
        self, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(None, group="all"), capsys)
        assert "Cases: every case of the runs: 8 cases (4 fatal, 4 non-fatal)" in text
        section = _section(text, 1)
        assert "- first code right: 2 of 8 (25.0%)" in section

    def test_another_group_of_the_file(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups, group="always right"), capsys)
        assert "Cases: arm C, always right, from " in text
        assert "- first code right: 1 of 1 (100.0%)" in _section(text, 1)

    def test_a_groups_file_outside_the_runs_folder_is_named_by_its_file_name(
        self, runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        elsewhere = _groups(tmp_path / "elsewhere.json")
        text = _report(_argv(elsewhere), capsys)
        assert "from elsewhere.json: 7 cases" in text
        assert str(tmp_path) not in text

    def test_one_run_is_enough(self, groups: Path, capsys: pytest.CaptureFixture[str]) -> None:
        argv = ["--runs", _RUN_A, "--groups", str(groups), "--group", "always wrong"]
        text = _report(argv, capsys)
        assert "## run 1:" in text
        assert "## run 2:" not in text


# --------------------------------------------------------------------------------------------
# Refusals: the runs through scripts/s3_case_groups.py's checks, the groups file through
# scripts/s3_trail_pages.py's
# --------------------------------------------------------------------------------------------


class TestRefusals:
    def test_a_held_out_run_id_is_refused(self, groups: Path) -> None:
        with pytest.raises(SystemExit, match="held-out"):
            mk.main(["--runs", "20260101T000000-abc1234-heldout-400-C", *_argv(groups)[3:]])

    @pytest.mark.parametrize(
        ("sample", "match"),
        [
            ("heldout-400", "held-out"),
            ("open-400", "not a development sample"),
            ("dev-seal-s3-400", "dev-400 only"),
        ],
    )
    def test_a_run_on_any_sample_but_dev_400_is_refused(
        self,
        runs: Path,
        groups: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample: str,
        match: str,
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
        _write(runs, _RUN_A, _run_a(), sample=sample)
        with pytest.raises(SystemExit, match=match):
            mk.main(_argv(groups))

    def test_a_sealed_sample_not_yet_opened_is_refused_as_sealed(
        self, runs: Path, groups: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
        _write(runs, _RUN_A, _run_a(), sample="dev-seal-s3-400")
        with pytest.raises(SystemExit, match="sealed"):
            mk.main(_argv(groups))

    def test_an_unfinished_run_is_refused(self, runs: Path, groups: Path) -> None:
        _write(runs, _RUN_A, _run_a(), finished=None)
        with pytest.raises(SystemExit, match="has not finished"):
            mk.main(_argv(groups))

    def test_an_arm_b_run_is_refused(self, runs: Path, groups: Path) -> None:
        _write(runs, _RUN_A, _run_a(), arm="B")
        with pytest.raises(SystemExit, match="arm B; miss kinds read arm C runs only"):
            mk.main(_argv(groups))

    def test_a_case_outside_the_development_split_is_refused(
        self, runs: Path, groups: Path
    ) -> None:
        cases = _run_a()
        cases[0] = cases[0].model_copy(update={"split": "open"})
        _write(runs, _RUN_A, cases)
        with pytest.raises(SystemExit, match="outside the dev split"):
            mk.main(_argv(groups))

    def test_a_run_on_part_of_the_sample_is_refused(self, runs: Path, groups: Path) -> None:
        _write(runs, _RUN_A, _run_a()[:7])
        with pytest.raises(SystemExit, match="not the whole of dev-400"):
            mk.main(_argv(groups))

    def test_a_run_named_twice_is_refused(self, groups: Path) -> None:
        argv = ["--runs", _RUN_A, _RUN_A, "--groups", str(groups), "--group", "always wrong"]
        with pytest.raises(SystemExit, match="named twice"):
            mk.main(argv)

    def test_a_groups_file_not_drawn_over_a_run_is_refused(
        self, runs: Path, tmp_path: Path
    ) -> None:
        other = _groups(tmp_path / "other.json", runs=(_RUN_A,))
        with pytest.raises(SystemExit, match=f"was not drawn over run {_RUN_B}"):
            mk.main(_argv(other))

    def test_a_groups_file_on_another_sample_is_refused(self, runs: Path, tmp_path: Path) -> None:
        other = _groups(tmp_path / "other.json", sample="dev-seal-400")
        with pytest.raises(SystemExit, match="is not a dev-400 groups file"):
            mk.main(_argv(other))

    def test_a_missing_groups_file_is_refused(self, runs: Path, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="no groups file"):
            mk.main(_argv(tmp_path / "absent.json"))

    def test_a_group_case_the_runs_do_not_hold_is_refused(self, runs: Path, tmp_path: Path) -> None:
        other = _groups(tmp_path / "other.json", wrong=(*_WRONG, "ZQX999"))
        with pytest.raises(SystemExit, match="does not hold 1 case"):
            mk.main(_argv(other))

    def test_a_case_with_no_ntsb_occurrence_code_is_refused(self, runs: Path, groups: Path) -> None:
        cases = _run_a()
        cases[1] = cases[1].model_copy(update={"verdict_occurrence": ()})
        _write(runs, _RUN_A, cases)
        with pytest.raises(SystemExit, match="no NTSB occurrence code"):
            mk.main(_argv(groups))

    def test_a_named_group_needs_a_groups_file(self, runs: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            mk.main(_argv(None))
        assert raised.value.code == 2

    def test_group_all_refuses_a_groups_file(self, groups: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            mk.main(_argv(groups, group="all"))
        assert raised.value.code == 2

    def test_an_unknown_group_is_a_usage_error(self, groups: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            mk.main(_argv(groups, group="always_wrong"))
        assert raised.value.code == 2
