"""scripts/round_result.py: decision 0098 item 4."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import round_result as rr
from scripts import s3_noise_floor as nf
from tests.test_occurrence_misses import _SCORES, _case

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring.coding_stats import (
    CodingStats,
    PoolCase,
    StatsName,
    build,
    load_stats,
)
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl


def _cases(top1: list[bool], recall: list[float]) -> list[CaseResult]:
    return [
        _case(f"C{i}", ("452240",), ("452240",)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=t, finding_recall_10=r)}
        )
        for i, (t, r) in enumerate(zip(top1, recall, strict=True))
    ]


def test_a_round_is_kept_above_the_noise_with_no_harm() -> None:
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 40 for i in range(n)], [0.1] * n)  # +20 points, no finding change
    noise_a = _cases([False] * n, [0.1] * n)
    noise_b = _cases([i < 2 for i in range(n)], [0.1] * n)  # 1 point of noise
    reading = rr.read(run, reference, noise_a, noise_b, finding_round=False)
    assert reading.kept
    assert abs(reading.noise - 0.01) < 1e-9


def test_a_round_inside_the_noise_is_dropped() -> None:
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 4 for i in range(n)], [0.1] * n)  # +2 points
    noise_b = _cases([i < 10 for i in range(n)], [0.1] * n)  # 5 points of noise
    reading = rr.read(run, reference, reference, noise_b, finding_round=False)
    assert not reading.kept


def test_a_gain_that_harms_the_other_score_is_dropped() -> None:
    n = 200
    reference = _cases([False] * n, [0.5] * n)
    run = _cases([i < 40 for i in range(n)], [0.0] * n)  # top-1 up, finding recall down everywhere
    reading = rr.read(run, reference, reference, reference, finding_round=False)
    assert not reading.kept
    assert "harm" in reading.reason


def test_push_line_counts_first_codes_moved_toward_a_more_common_option() -> None:
    stats = build(
        [PoolCase(2012, "Maneuvering", ("452240",))] * 30
        + [PoolCase(2013, "Maneuvering", ("452241",))] * 5,
        built_from="test",
    )
    reference = [_case("C1", ("452240",), ("452241",)), _case("C2", ("452240",), ("452240",))]
    run = [
        _case("C1", ("452240",), ("452240",)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=True)}
        ),
        _case("C2", ("452240",), ("452241",)),
    ]
    reference[1] = reference[1].model_copy(
        update={"scores": replace(_SCORES, occurrence_top1=True)}
    )
    text = rr.push_line(run, reference, {"C1": "Maneuvering", "C2": "Maneuvering"}, stats)
    assert "first codes changed: 2; toward a more common option: 1, fixes 1, breaks 0" in text


def _run_record(run_id: str, *, sample: str = "dev-400", arm: str = "B") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        sample=sample,
        arm=arm,
        evidence_version="v1",
        exclusions=(),
        includes=(),
        prompt_version="s1-v5",
        model="m",
        price_variant="batch",
        cap_usd=0.05,
        budget_usd=40.0,
        commit_sha="abc1234",
        dirty=False,
        started=datetime(2026, 9, 27, tzinfo=UTC),
        finished=datetime(2026, 9, 27, 1, tzinfo=UTC),
        cases=1,
        cost_usd=0.01,
    )


# 2026-09-27 addition beyond the brief: round_result._load mirrors the sibling scripts on this
# branch (judge_outcomes._load, round0_handread._run, round1_report._load), which check
# run.jsonl's recorded sample before cases.jsonl is read at all.
def test_supplement_line_splits_cases_by_a_code_decision_0105_added() -> None:
    hit = {"scores": replace(_SCORES, occurrence_top1=True)}
    reference = [
        _case("C1", ("553470",), ("550470",)),
        _case("C2", ("452240", "601092"), ("452240",)).model_copy(update=hit),
        _case("C3", ("452240",), ("452240",)).model_copy(update=hit),
        _case("C4", ("452240",), ("452241",)),
    ]
    run = [
        _case("C1", ("553470",), ("553470",)).model_copy(update=hit),
        _case("C2", ("452240", "601092"), ("452240",)).model_copy(update=hit),
        _case("C3", ("452240",), ("452240",)).model_copy(update=hit),
        _case("C4", ("452240",), ("452241",)),
    ]
    text = rr.supplement_line(run, reference)
    assert "NTSB sequence holds a code decision 0105 added: 2 (defining: 1)" in text
    assert "top-1 hits there: reference 1, run 2" in text
    assert "occurrence top-1 on the other cases: +0.0%" in text


def test_a_run_recorded_on_a_held_out_sample_is_refused_before_its_cases_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    folder = runs_dir / "renamed-run"
    write_jsonl(folder / "run.jsonl", [_run_record("renamed-run", sample="heldout-400")])
    with pytest.raises(SystemExit, match="held-out run"):
        rr._load("renamed-run")
    assert not (folder / "cases.jsonl").exists()


def test_a_run_recorded_on_the_sealed_sample_is_refused_until_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    write_jsonl(
        runs_dir / "sealed-run" / "run.jsonl",
        [_run_record("sealed-run", sample="dev-seal-400")],
    )
    with pytest.raises(SystemExit, match="sealed"):
        rr._load("sealed-run")


def test_a_run_that_has_not_finished_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    dead = _run_record("dead-run").model_copy(update={"finished": None})
    write_jsonl(runs_dir / "dead-run" / "run.jsonl", [dead])
    with pytest.raises(SystemExit, match="has not finished"):
        rr._load("dead-run")
    assert not (runs_dir / "dead-run" / "cases.jsonl").exists()


def test_main_refuses_a_reference_run_on_a_different_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    write_jsonl(runs_dir / "run-id" / "run.jsonl", [_run_record("run-id")])
    write_jsonl(
        runs_dir / "ref-id" / "run.jsonl",
        [_run_record("ref-id", arm="ceiling")],
    )
    with pytest.raises(SystemExit, match="arm"):
        rr.main(
            [
                "--run",
                "run-id",
                "--reference",
                "ref-id",
                "--noise",
                "run-id",
                "run-id",
            ]
        )


def test_main_prints_the_outcome_and_append_writes_it_to_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 40 for i in range(n)], [0.1] * n)
    noise_a = _cases([False] * n, [0.1] * n)
    noise_b = _cases([i < 2 for i in range(n)], [0.1] * n)
    for run_id, cases in (
        ("run-id", run),
        ("ref-id", reference),
        ("noise-a", noise_a),
        ("noise-b", noise_b),
    ):
        folder = runs_dir / run_id
        write_jsonl(folder / "run.jsonl", [_run_record(run_id)])
        write_jsonl(folder / "cases.jsonl", cases)
    monkeypatch.setattr(rr, "_groups", lambda cases: {c.case_id: None for c in cases})
    out = tmp_path / "registration.md"
    out.write_text("# a round\n")
    assert (
        rr.main(
            [
                "--run",
                "run-id",
                "--reference",
                "ref-id",
                "--noise",
                "noise-a",
                "noise-b",
                "--append",
                str(out),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "outcome: kept" in printed
    assert "run-id (prompt s1-v5)" in printed
    assert "ref-id (prompt s1-v5)" in printed
    assert out.read_text() == "# a round\n" + "\n" + printed


# S3.1 Task 13: an S3 round's run is arm C, whose tools count in S3's statistics file (decision
# 0129 item 4); its spec.json names the file, and the push line reads the same one.
@pytest.mark.parametrize(
    ("spec", "stats", "line"),
    [
        (None, "s27", False),  # an S2.7 arm B run writes no stats key: S2.7's file, as before
        ({"arm": "B"}, "s27", False),
        ({"arm": "C", "stats": "s3"}, "s3", True),
    ],
)
def test_the_push_line_reads_the_statistics_file_the_runs_spec_names(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    spec: dict[str, object] | None,
    stats: str,
    line: bool,
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    n = 10
    for run_id in ("run-id", "ref-id", "noise-a", "noise-b"):
        folder = runs_dir / run_id
        write_jsonl(folder / "run.jsonl", [_run_record(run_id, arm="C")])
        write_jsonl(folder / "cases.jsonl", _cases([False] * n, [0.1] * n))
        (folder / TRAIL_FILE).write_text("")  # an arm C run's format gate reads it (0136)
    if spec is not None:
        (runs_dir / "run-id" / "spec.json").write_text(json.dumps(spec))
    monkeypatch.setattr(rr, "_groups", lambda cases: {c.case_id: None for c in cases})
    names: list[str] = []

    def spy(name: StatsName = "s27") -> CodingStats:
        names.append(name)
        return load_stats(name)

    monkeypatch.setattr(rr, "load_stats", spy)
    argv = ["--run", "run-id", "--reference", "ref-id", "--noise", "noise-a", "noise-b"]
    assert rr.main(argv) == 0
    assert names == [stats]
    printed = capsys.readouterr().out
    assert ("statistics file for the line above: s3" in printed) is line


def test_a_spec_naming_an_unknown_statistics_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    for run_id in ("run-id", "ref-id"):
        write_jsonl(runs_dir / run_id / "run.jsonl", [_run_record(run_id, arm="C")])
        write_jsonl(runs_dir / run_id / "cases.jsonl", _cases([False], [0.1]))
    (runs_dir / "run-id" / "spec.json").write_text(json.dumps({"stats": "s9"}))
    with pytest.raises(SystemExit, match="s9"):
        rr.main(["--run", "run-id", "--reference", "ref-id", "--noise", "ref-id", "ref-id"])


# --------------------------------------------------------------------------------------------
# Decision 0136: in an S3 round (arm C), a failed case counts as wrong, and the format gate is a
# hard limit. S2.7's rounds (arm B) read exactly as before.
# --------------------------------------------------------------------------------------------

_FINDINGS = ("000000000000",)


def _scored(i: int, *, top1: bool, recall: float | None = 0.1) -> CaseResult:
    """A scored case; ``recall=None`` is a verdict with no flagged finding (nothing to score)."""
    return _case(f"C{i}", ("452240",), ("452240",)).model_copy(
        update={
            "scores": replace(
                _SCORES, occurrence_top1=top1, occurrence_top3=top1, finding_recall_10=recall
            ),
            "verdict_findings_in_cause": _FINDINGS if recall is not None else (),
        }
    )


def _failed(i: int, failure: str = "failed: coding", *, findings: bool = True) -> CaseResult:
    """A failed case, as arm C writes one: no score; its verdict's flagged findings kept."""
    return _case(f"C{i}", ("452240",), (), scored=False).model_copy(
        update={"failure": failure, "verdict_findings_in_cause": _FINDINGS if findings else ()}
    )


def _outcomes(*spans: tuple[int, bool | str], recall: float = 0.1) -> list[CaseResult]:
    """Cases ``C0``, ``C1``... from ``(count, outcome)`` spans: a hit, a miss or a failure.

    Every scored case has finding recall@10 ``recall``; at 0.0 a failure costs no recall.
    """
    cases: list[CaseResult] = []
    for count, outcome in spans:
        for _ in range(count):
            i = len(cases)
            cases.append(
                _failed(i, outcome)
                if isinstance(outcome, str)
                else _scored(i, top1=outcome, recall=recall)
            )
    return cases


class TestFailuresCountAsWrong:
    """Decision 0136 item 1: every case of the runs is paired; a failed case scores 0."""

    def test_a_failed_case_scores_zero_on_top1_top3_and_recall(self) -> None:
        cases = [
            _scored(0, top1=True, recall=0.5),
            _failed(1),
            _failed(2, "leak: x", findings=False),
            _scored(3, top1=False, recall=None),
        ]
        assert rr.top1_counting_failures(cases) == {"C0": 1.0, "C1": 0.0, "C2": 0.0, "C3": 0.0}
        assert rr.top3_counting_failures(cases) == {"C0": 1.0, "C1": 0.0, "C2": 0.0, "C3": 0.0}
        # A verdict with no flagged finding has nothing to score, failed or not.
        assert rr.recall_counting_failures(cases) == {"C0": 0.5, "C1": 0.0}

    def test_a_case_that_failed_but_holds_scores_still_counts_as_wrong(self) -> None:
        odd = _scored(0, top1=True, recall=0.5).model_copy(update={"failure": "cap"})
        no_steps = _scored(1, top1=True, recall=0.5).model_copy(update={"steps": ()})
        assert rr.top1_counting_failures([odd, no_steps]) == {"C0": 0.0, "C1": 0.0}
        assert rr.recall_counting_failures([odd, no_steps]) == {"C0": 0.0, "C1": 0.0}

    def test_a_round_that_fails_the_cases_it_used_to_get_right_is_not_kept(self) -> None:
        # The reference gets C0-C19 right. The run fails C0-C29 and gets C30-C49 right: with
        # failures left out of n (S2.7's rule) that reads +11.8 points; counted, it is no gain.
        reference = _outcomes((20, True), (180, False))
        run = _outcomes((30, "failed: coding"), (20, True), (150, False))
        s27 = rr.read(run, reference, reference, reference, finding_round=False)
        assert s27.kept
        assert s27.primary.n == 170
        s3 = rr.read(run, reference, reference, reference, finding_round=False, failures_wrong=True)
        assert not s3.kept
        assert s3.primary.n == 200
        assert s3.primary.mean == 0.0

    def test_the_noise_pair_is_read_with_failures_counted_too(self) -> None:
        noise_a = _outcomes((10, True), (190, False))
        noise_b = _outcomes((10, "failed: h1"), (190, False))
        reading = rr.read(
            noise_a, noise_a, noise_a, noise_b, finding_round=False, failures_wrong=True
        )
        assert abs(reading.noise - 0.05) < 1e-9  # 10 of 200; dropped from n it would be 0

    def test_failures_that_cost_finding_recall_are_harm(self) -> None:
        # A real top-1 gain, but 20 failures where the reference found a tenth of the
        # findings: left out of n they cost nothing; counted, recall falls on every one.
        reference = _outcomes((200, False))
        run = _outcomes((60, True), (20, "failed: coding"), (120, False))
        s27 = rr.read(run, reference, reference, reference, finding_round=False)
        assert s27.kept
        s3 = rr.read(run, reference, reference, reference, finding_round=False, failures_wrong=True)
        assert s3.secondary.high < 0
        assert s3.reason == "dropped: harm to the other score (interval wholly below zero)"


class TestTheGateIsAHardLimit:
    """Decision 0136 item 2: more than 8 format or tool failures drop a round, first.

    Recall is 0.0 on every scored case here, so a failure costs nothing but the gate.
    """

    @staticmethod
    def _run(failed: int) -> list[CaseResult]:
        # A big gain on the cases scored, and ``failed`` format failures on cases the
        # reference got wrong, so the failures cost the run nothing on top-1.
        return _outcomes((80, True), (failed, "failed: coding"), (120 - failed, False), recall=0.0)

    def test_nine_format_failures_drop_a_round_whatever_its_accuracy(self) -> None:
        reference = _outcomes((200, False), recall=0.0)
        run = self._run(9)
        gate = nf.format_gate(run)
        reading = rr.read(
            run,
            reference,
            reference,
            reference,
            finding_round=False,
            failures_wrong=True,
            gate=gate,
        )
        assert reading.primary.low > 0  # the gain alone would keep it
        assert not reading.kept
        assert reading.reason.startswith("dropped: the format gate failed")
        assert "9 of 200" in reading.reason

    def test_eight_format_failures_pass_and_the_rule_reads_on(self) -> None:
        reference = _outcomes((200, False), recall=0.0)
        run = self._run(8)
        reading = rr.read(
            run,
            reference,
            reference,
            reference,
            finding_round=False,
            failures_wrong=True,
            gate=nf.format_gate(run),
        )
        assert reading.kept

    def test_the_gate_counts_as_the_noise_floor_does(self) -> None:
        # Leaks, cap stops and the round limit are not format or tool failures (decision 0130
        # item 5); they still count as wrong on the scores.
        reference = _outcomes((200, False), recall=0.0)
        run = _outcomes(
            (80, True),
            (8, "failed: answer"),
            (1, "leak: x"),
            (1, "cap"),
            (1, "failed: rounds"),
            (109, False),
            recall=0.0,
        )
        gate = nf.format_gate(run)
        assert gate.count == 8
        reading = rr.read(
            run,
            reference,
            reference,
            reference,
            finding_round=False,
            failures_wrong=True,
            gate=gate,
        )
        assert reading.kept

    def test_a_finding_round_is_dropped_by_the_gate_too(self) -> None:
        reference = _outcomes((200, False), recall=0.0)
        run = self._run(9)
        reading = rr.read(
            run,
            reference,
            reference,
            reference,
            finding_round=True,
            failures_wrong=True,
            gate=nf.format_gate(run),
        )
        assert reading.reason.startswith("dropped: the format gate failed")


def _write_run(
    runs_dir: Path,
    run_id: str,
    cases: list[CaseResult],
    *,
    arm: str,
    trail: bool = True,
) -> None:
    folder = runs_dir / run_id
    write_jsonl(folder / "run.jsonl", [_run_record(run_id, arm=arm)])
    write_jsonl(folder / "cases.jsonl", cases)
    if arm == "C":
        (folder / "spec.json").write_text(json.dumps({"arm": "C", "stats": "s3"}))
        if trail:
            (folder / TRAIL_FILE).write_text("")


_S3_ARGV = ["--run", "run-c", "--reference", "ref-c", "--noise", "noise-c1", "noise-c2"]


@pytest.fixture
def s3_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, with phase groups read from nowhere (no processed file)."""
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    monkeypatch.setattr(rr, "_groups", lambda cases: {c.case_id: None for c in cases})
    return runs_dir


class TestAnS3RoundsResult:
    """What ``main`` prints for an arm C round (decision 0136 item 3)."""

    @staticmethod
    def _write(runs_dir: Path, run: list[CaseResult]) -> None:
        reference = _outcomes((20, True), (178, False), (2, "leak: x"), recall=0.0)
        _write_run(runs_dir, "run-c", run, arm="C")
        _write_run(runs_dir, "ref-c", reference, arm="C")
        _write_run(runs_dir, "noise-c1", _outcomes((20, True), (180, False), recall=0.0), arm="C")
        _write_run(
            runs_dir,
            "noise-c2",
            _outcomes((2, "failed: h1"), (18, True), (180, False), recall=0.0),
            arm="C",
        )

    def test_the_gate_comes_first_then_failures_and_every_denominator(
        self, s3_runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run = _outcomes((60, True), (5, "failed: coding"), (133, False), (2, "leak: x"), recall=0.0)
        self._write(s3_runs, run)
        assert rr.main(_S3_ARGV) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == (
            "## Result (scripts/round_result.py, decision 0098 item 4; failures and the format "
            "gate by decision 0136)"
        )
        assert lines[2].startswith("- format gate, run run-c: PASS -- 5 of 200 cases failed")
        assert lines[3].startswith("- round limit (failed: rounds), run run-c: 0 of 200 cases")
        assert lines[4].startswith("- run: run-c (prompt s1-v5); reference: ref-c")
        assert lines[5] == (
            "- failed cases, each counted wrong below (decision 0136 item 1): run 7 of 200, "
            "reference 2 of 200, noise pair 0 of 200 and 2 of 200"
        )
        assert lines[6] == "- the run's failures by reason: failed 5, leak (unparsed) 2"
        assert lines[7].startswith("- occurrence top-1 (a failed case counted wrong): +20.0% [")
        assert lines[7].endswith("] on n=200")
        assert lines[8] == (
            "- noise floor (occurrence top-1, the two identical runs, a failed case counted "
            "wrong): 1.0%"
        )
        assert lines[9].startswith(
            "- finding recall@10 (do no harm, a failed case counted wrong): "
        )
        assert lines[9].endswith("on n=200")
        assert lines[10].startswith(
            "- occurrence top-3 (a failed case counted wrong; beside the rule, not in it): +20.0%"
        )
        assert lines[11].startswith("- first codes changed: ")
        assert lines[12].startswith("- statistics file for the line above: s3")
        assert lines[-1] == "- outcome: kept"
        assert not any(f"C{i}" in line for line in lines for i in range(200))  # no case id

    def test_a_run_over_the_gate_says_so_first_and_is_dropped(
        self, s3_runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run = _outcomes((60, True), (9, "failed: coding"), (131, False), recall=0.0)
        self._write(s3_runs, run)
        assert rr.main(_S3_ARGV) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[2].startswith("- format gate, run run-c: FAIL -- 9 of 200 cases failed")
        assert lines[3] == (
            "- the round is dropped whatever its accuracy: its run failed the format gate "
            "(decision 0136 item 2); the figures below are printed for the record"
        )
        assert lines[-1].startswith("- outcome: dropped: the format gate failed (9 of 200 cases")

    def test_append_writes_the_same_text_under_the_registration(
        self, s3_runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._write(s3_runs, _outcomes((60, True), (140, False), recall=0.0))
        out = tmp_path / "s3-round-1.md"
        out.write_text("# S3 round 1\n")
        assert rr.main([*_S3_ARGV, "--append", str(out)]) == 0
        assert out.read_text() == "# S3 round 1\n" + "\n" + capsys.readouterr().out

    def test_the_no_reply_count_reads_the_runs_trail(
        self, s3_runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run = _outcomes((60, True), (1, "failed: coding"), (139, False), recall=0.0)
        self._write(s3_runs, run)
        silent = AgentCall(
            run_id="run-c",
            case_id="C60",
            trigger=1,
            docket_state="all",
            call_index=3,
            step="coding",
            retry=True,
            tool=None,
            arguments={},
            protocol_error="no reply",
            result_chars=0,
            argument_errors=0,
            hypothesis=None,
            prompt_tokens=0,
            cached_tokens=None,
            completion_tokens=0,
            reasoning_tokens=None,
            finish_reason=None,
            cost_usd=0.0,
            estimated_usd=0.0,
            sent_at=datetime(2026, 10, 2, tzinfo=UTC),
            returned_at=datetime(2026, 10, 2, tzinfo=UTC),
            batch_id="b1",
            commit_sha="abc1234",
            dirty=False,
        )
        write_jsonl(s3_runs / "run-c" / TRAIL_FILE, [silent])
        assert rr.main(_S3_ARGV) == 0
        assert "of which 1 had no reply on the failing call" in capsys.readouterr().out

    def test_an_arm_c_run_with_no_trail_is_refused(self, s3_runs: Path) -> None:
        self._write(s3_runs, _outcomes((60, True), (140, False), recall=0.0))
        (s3_runs / "run-c" / TRAIL_FILE).unlink()
        with pytest.raises(SystemExit, match=r"no trail\.jsonl"):
            rr.main(_S3_ARGV)

    def test_runs_on_different_cases_are_refused(self, s3_runs: Path) -> None:
        self._write(s3_runs, _outcomes((60, True), (139, False), recall=0.0))  # 199 cases, not 200
        with pytest.raises(SystemExit, match="other cases than run-c"):
            rr.main(_S3_ARGV)

    def test_the_supplement_line_is_refused_for_an_s3_round(self, s3_runs: Path) -> None:
        self._write(s3_runs, _outcomes((60, True), (140, False), recall=0.0))
        with pytest.raises(SystemExit, match="--supplement"):
            rr.main([*_S3_ARGV, "--supplement"])

    def test_a_finding_round_names_recall_first(
        self, s3_runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._write(s3_runs, _outcomes((60, True), (140, False), recall=0.0))
        assert rr.main([*_S3_ARGV, "--finding-round"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[7].startswith("- finding recall@10 (a failed case counted wrong): ")
        assert lines[9].startswith("- occurrence top-1 (do no harm, a failed case counted wrong)")


# The exact text HEAD's ``round_result.py`` (commit e694635, before decision 0136) printed for
# these synthetic arm B runs, failed cases and all: S2.7's reading must not move by one byte.
_S27_GOLDEN = """\
## Result (scripts/round_result.py, decision 0098 item 4)

- run: run-b (prompt s1-v5); reference: ref-b (prompt s1-v5); noise pair: noise-b1, noise-b2
- occurrence top-1: +18.2% [+12.4%, +24.1%] on n=170
- noise floor (occurrence top-1, the two identical runs): 0.0%
- finding recall@10 (do no harm): +0.0% [+0.0%, +0.0%] on n=170
- first codes changed: 0; toward a more common option: 0, fixes 0, breaks 0 (decision 0101 item 4)
- outcome: kept
"""


def test_an_s27_round_reads_byte_for_byte_as_before(
    s3_runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reference = _outcomes((20, True), (180, False))
    run = _outcomes((30, "failed: coding"), (31, True), (139, False))
    _write_run(s3_runs, "run-b", run, arm="B")
    _write_run(s3_runs, "ref-b", reference, arm="B")
    _write_run(s3_runs, "noise-b1", reference, arm="B")
    _write_run(s3_runs, "noise-b2", _outcomes((10, "leak: x"), (10, True), (180, False)), arm="B")
    argv = ["--run", "run-b", "--reference", "ref-b", "--noise", "noise-b1", "noise-b2"]
    assert rr.main(argv) == 0
    assert capsys.readouterr().out == _S27_GOLDEN
