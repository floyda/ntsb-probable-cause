"""scripts/exploratory/s32_heldout_diagnosis.py: decision 0153's six breakdowns, counts only.

Every run folder is made up under ``tmp_path``: S3.2's six held-out runs, with made-up case
numbers (``ZQX...``, a sentinel no other text in the report can contain), made-up codes and
made-up trails. No real held-out run is read, and whether a file is committed is faked. Offline.

The world below is built so that each breakdown has an answer worked out by hand. Twenty cases,
the first ten fatal; the NTSB's first code is 552240 in every case; ``R`` is that code, ``W``
another (552241). Arm B's answer is right on cases 0-5; its tool post-pass on 1-9 (case 0
broken, 6-9 fixed); its check on 2-10 (case 1 broken, 10 fixed). The loop is right on 0, 11
and 12 and fails case 19 (``failed: coding``); its H0 is right on 0, 1 and 11; its last
hypothesis before coding on 0, 11, 12 and 13. Documents offered: one on cases 0-4 (all read on
0-2), three on 5-9 (all read on 5 and 6), six on 10-14 (all read on 10), none on 15-18; case 19
has no trail row.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from scripts import _s3_runs as sr
from scripts.exploratory import s32_heldout_diagnosis as dg
from scripts.s32_coding_ablation import points
from tests.test_s3_noise_floor import _IDS, _call, _choose, _spec_json, _write
from tests.test_s32_claims import (
    ANSWER,
    ARM_A,
    CHECK,
    DOCKET_ROLES,
    LOOP,
    NODOCKET,
    TOOLS,
    _held_record,
    _ledger_rows,
)

from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import claims, samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import score_case
from ntsb_probable_cause.scoring.records import CaseResult, StepRecord

TRUTH = "552240"
RIGHT = TRUTH
WRONG = "552241"
# A sentinel in every model text field: the counts-only test proves none reaches the output.
TEXT = "ZQX-model-text"
LEAK = "leak: verbatim from probable_cause in docket_documents (40 chars withheld)"
TABLES = load_tables()


def _rights(ids: set[int]) -> list[str]:
    return ["R" if n in ids else "W" for n in range(20)]


ANSWER_RUN = _rights(set(range(6)))
TOOLS_RUN = _rights(set(range(1, 10)))
CHECK_RUN = _rights(set(range(2, 11)))
LOOP_RUN = [*_rights({0, 11, 12})[:19], "failed: coding"]
H0 = _rights({0, 1, 11})
BEFORE_CODING = _rights({0, 11, 12, 13})
OFFERS: dict[int, tuple[tuple[int, ...], set[int]]] = {
    **{n: ((1,), {1} if n <= 2 else set()) for n in range(5)},
    **{n: ((1, 2, 3), {1, 2, 3} if n <= 6 else {1}) for n in range(5, 10)},
    **{n: ((1, 2, 3, 4, 5, 6), {1, 2, 3, 4, 5, 6} if n == 10 else {2}) for n in range(10, 15)},
    **{n: ((), set()) for n in range(15, 19)},
}


# --------------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------------


def _hyp(first: str, *, abstain: bool = False) -> Hypothesis:
    return Hypothesis(
        evidence_narrative=f"{TEXT} narrative",
        occurrence=(OccurrenceGuess(phase=first[:3], event=first[3:], probability=0.5),),
        findings=(),
        probable_cause=f"{TEXT} working cause",
        lay_explanation=f"{TEXT} lay",
        confidence=0.5,
        abstain=abstain,
        evidence_used=(),
    )


def _code(mark: str) -> str:
    return RIGHT if mark == "R" else WRONG


def _step(case_id: str, hypothesis: Hypothesis) -> StepRecord:
    return StepRecord(
        case_id=case_id,
        step=0,
        arm="B",
        condition="full",
        day=None,
        tool="docket",
        arguments={},
        reason="",
        expected_effect="",
        returned_roles=(),
        not_available=(),
        payload_fingerprint="x",
        hypothesis=hypothesis,
        observed_effect="",
        stop_reason="answered",
        model="m",
        price_variant="batch",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        cumulative_cost_usd=0.0,
        commit_sha="abc1234",
        dirty=False,
    )


def _case(n: int, mark: str) -> CaseResult:
    """Case ``n``: ``R`` right, ``W`` wrong, anything else a failure of that text."""
    case_id = _IDS[n]
    base = CaseResult(
        case_id=case_id,
        split="heldout",
        fatal=n < 10,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=(TRUTH,),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(),
        scores=None,
        cost_usd=0.0,
        failure=None,
    )
    if mark not in {"R", "W"}:
        return base.model_copy(update={"failure": mark})
    hypothesis = _hyp(_code(mark))
    verdict = Verdict(
        probable_cause=None, occurrence_codes=(TRUTH,), finding_codes=(), finding_codes_in_cause=()
    )
    scores = score_case(hypothesis, verdict, TABLES, seen_pairs=frozenset())
    return base.model_copy(update={"steps": (_step(case_id, hypothesis),), "scores": scores})


def _cases(marks: Sequence[str]) -> list[CaseResult]:
    return [_case(n, mark) for n, mark in enumerate(marks)]


def _checkpoint(case_id: str, step: str, index: int, mark: str) -> AgentCall:
    row = _call(case_id, "record_hypothesis", index=index)
    return row.model_copy(update={"step": step, "hypothesis": _hyp(_code(mark))})


def _trail(
    h0: Sequence[str] = H0,
    before: Sequence[str] = BEFORE_CODING,
    offers: dict[int, tuple[tuple[int, ...], set[int]]] = OFFERS,
) -> list[AgentCall]:
    """The loop's trail: H0, a read choice and H1 when something is offered, coding, answer."""
    rows: list[AgentCall] = []
    for n, (offered, read) in offers.items():
        case_id = _IDS[n]
        rows.append(_checkpoint(case_id, "h0", 0, h0[n]))
        if offered:
            choice = _choose(case_id, {d: d in read for d in offered}, index=1, offered=offered)
            arguments = {
                "decisions": [
                    {"document": d, "read": d in read, "expected_effect": f"{TEXT} effect"}
                    for d in offered
                ],
                "reason": f"{TEXT} reason",
            }
            rows += [
                choice.model_copy(update={"step": "choice1", "arguments": arguments}),
                _checkpoint(case_id, "h1", 2, before[n]),
            ]
        rows += [
            _call(case_id, "describe_codes", index=3),
            # The answer checkpoint is in the trail too; it is never "before coding".
            _checkpoint(case_id, "answer", 4, "W"),
        ]
    return rows


def build(
    runs: Path,
    *,
    loop: Sequence[str] = LOOP_RUN,
    check: Sequence[str] = CHECK_RUN,
    trail: Sequence[AgentCall] | None = None,
) -> None:
    """Write the six held-out run folders of the world in the module docstring."""
    spec_c = _spec_json(list(_IDS))
    _write(runs, ARM_A, _cases(["W"] * 20), record=_held_record(ARM_A, "A", (0.3, 0.3)))
    _write(runs, ANSWER, _cases(ANSWER_RUN), record=_held_record(ANSWER, "B", (0.5, 0.6)))
    pv = f"{_held_record(ANSWER, 'B', (0, 0)).prompt_version}+tools-s3+p947fac1c86a4"
    _write(
        runs,
        TOOLS,
        _cases(TOOLS_RUN),
        [_call(_IDS[0], "describe_codes")],
        record=_held_record(TOOLS, "B", (0.4, 0.5), prompt_version=pv),
    )
    _write(
        runs,
        CHECK,
        _cases(check),
        record=_held_record(
            CHECK,
            "B",
            (0.1, 0.1),
            prompt_version=f"{pv}+check-luna-s3",
            batch_ids=(),
            reported_batch_cost_usd=None,
        ),
    )
    _write(
        runs,
        LOOP,
        _cases(loop),
        _trail() if trail is None else trail,
        spec=spec_c,
        record=_held_record(LOOP, "C", (1.0, 2.0)),
    )
    _write(
        runs,
        NODOCKET,
        _cases(["W"] * 20),
        spec=spec_c,
        record=_held_record(NODOCKET, "C", (0.5, 1.0), exclusions=DOCKET_ROLES),
    )


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, the ledger, and ``heldout-400`` taken to be the made-up ids."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    ledger = tmp_path / "ledger.md"
    ledger.write_text(_ledger_rows([ARM_A, ANSWER, TOOLS, CHECK, LOOP, NODOCKET]))
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "heldout-400" else ())
    monkeypatch.setattr(sr, "changed_files", list)  # a clean tree
    return folder


def _argv(**overrides: str) -> list[str]:
    values = {
        "loop": LOOP,
        "nodocket": NODOCKET,
        "arm-a": ARM_A,
        "armb-answer": ANSWER,
        "armb-tools": TOOLS,
        "armb-check": CHECK,
    } | overrides
    return [part for flag, value in values.items() for part in (f"--{flag}", value)]


def _always(_: Path) -> bool:
    return True


def diagnose(
    capsys: pytest.CaptureFixture[str],
    *extra: str,
    is_committed: Callable[[Path], bool] = _always,
) -> str:
    assert dg.main([*_argv(), *extra], is_committed=is_committed) == 0
    return capsys.readouterr().out


def _section(out: str, number: int) -> list[str]:
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {number}."))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def _line(lines: Sequence[str], start: str) -> str:
    return next(line for line in lines if line.startswith(start))


# --------------------------------------------------------------------------------------------
# The six breakdowns, each against the answer worked out by hand
# --------------------------------------------------------------------------------------------


def test_breakdown_1_arm_b_by_stage(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    lines = _section(diagnose(capsys), 1)
    for label, mean in (
        ("loop - arm B answer", "-15.0"),
        ("loop - arm B tools", "-30.0"),
        ("loop - arm B check", "-30.0"),
        ("arm B tools - arm B answer", "+15.0"),
        ("arm B check - arm B tools", "+0.0"),
    ):
        line = _line(lines, f"top-1, {label}: ")
        assert line.startswith(f"top-1, {label}: {mean} points ["), line
        assert line.endswith("n=20"), line
    assert not any(line.startswith("top-3") for line in lines)  # 0153 fixed top-1 only
    assert _line(lines, "arm B answer top-1: ").startswith("arm B answer top-1: 30.0% [")
    assert _line(lines, "the loop top-1: ").startswith("the loop top-1: 15.0% [")


def test_breakdown_2_the_gap_by_group(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    lines = _section(diagnose(capsys), 2)
    for label, count, mean in (
        ("fatal", 10, "-70.0"),
        ("non-fatal", 10, "+10.0"),
        ("documents offered none", 4, "+0.0"),
        ("documents offered 1", 5, "-40.0"),
        ("documents offered 2-4", 5, "-100.0"),
        ("documents offered 5 or more", 5, "+20.0"),
    ):
        line = _line(lines, f"- {label}: ")
        assert line.startswith(f"- {label}: {count} cases; {mean} points ["), line
        assert f"n={count}" in line, line
    assert _line(lines, "- documents offered none: ").endswith(
        "; of which 0 are loop failures before any read choice"
    )
    assert _line(lines, "- cases with no row").endswith(": 1")


def test_breakdown_3_reading_and_h0(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    lines = _section(diagnose(capsys), 3)
    for label, count, mean in (
        (dg.READ_ALL, 6, "-50.0"),
        (dg.READ_SOME, 9, "-33.3"),
        (dg.NOTHING, 4, "+0.0"),
        (dg.NO_TRAIL, 1, "+0.0"),
    ):
        line = _line(lines, f"- {label}: ")
        assert line.startswith(f"- {label}: {count} cases; {mean} points ["), line
    assert "- H0 right 3 of 19 (15.8%); answer right 3 of 19 (15.8%)" in lines
    # the interval is the one claims.paired would draw over the same answered cases
    assert f"- answer - H0: {_drawn(LOOP_RUN[:19], H0)}" in lines
    assert (
        f"- answer - H0: {_drawn(LOOP_RUN[:19], H0)}"
        == "- answer - H0: +0.0 points [-15.8, +15.8], n=19"
    )
    assert _line(lines, "- H0 -> answer: ").startswith(
        "- H0 -> answer: fixes 1, breaks 1 (first code changed on 2 of 19"
    )
    assert "- answered cases with no H0 in the trail (left out): 0" in lines


def _drawn(answer: Sequence[str], before: Sequence[str]) -> str:
    """``claims``' own paired draw: answer minus the hypothesis, over the answered cases."""
    after = {_IDS[n]: float(mark == "R") for n, mark in enumerate(answer)}
    prior = {_IDS[n]: float(before[n] == "R") for n in range(len(answer))}
    return points(claims._paired(after, prior))


def test_breakdown_4_coding(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    lines = _section(diagnose(capsys), 4)
    expected = _drawn(LOOP_RUN[:19], BEFORE_CODING)
    assert expected.startswith("-5.3 points [")
    assert expected.endswith("n=19")
    assert f"  top-1, answer - last hypothesis before coding: {expected}" in lines
    assert _line(lines, "- the loop, last hypothesis before coding -> answer: ").endswith(
        "19 cases; first code changed on 1 of 19 (5.3%); fixes 0, breaks 1 (net -1); score "
        "changed with the first code kept 0"
    )
    assert _line(lines, "- arm B answer -> tools: ").endswith(
        "20 cases; first code changed on 5 of 20 (25.0%); fixes 4, breaks 1 (net +3); score "
        "changed with the first code kept 0"
    )
    assert _line(lines, "- arm B tools -> check: ").endswith(
        "20 cases; first code changed on 2 of 20 (10.0%); fixes 1, breaks 1 (net +0); score "
        "changed with the first code kept 0"
    )


def test_breakdown_5_failures(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    lines = _section(diagnose(capsys), 5)
    assert _line(lines, "- the loop: ").startswith("- the loop: 1 of 20 failed: guard refusals 0")
    assert "failed: coding 1" in _line(lines, "- the loop: ")
    assert _line(lines, "- arm B ordering check: ").startswith(
        "- arm B ordering check: 0 of 20 failed"
    )
    gap = _line(lines, "top-1, loop - arm B check, the loop's 1 failed cases left out of both: ")
    assert ": -31.6 points [" in gap, gap
    assert gap.endswith("n=19")


def test_breakdown_6_wins_and_losses(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    lines = _section(diagnose(capsys), 6)
    assert (
        "- all: n=20; right in arm B only 9, in the loop only 3, in both 0, in neither 8" in lines
    )
    assert "- fatal: n=10; right in arm B only 8, in the loop only 1, in both 0, in neither 1" in (
        lines
    )
    assert (
        "- documents offered 5 or more: n=5; right in arm B only 1, in the loop only 2, in both "
        "0, in neither 2"
    ) in lines


def test_the_six_sections_and_no_others(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    out = diagnose(capsys)
    heads = [line for line in out.splitlines() if line.startswith("## ")]
    assert [h.split(".")[0] for h in heads] == [f"## {n}" for n in range(1, 7)]
    assert "decides nothing and claims nothing" in out


def test_a_guard_refusal_leaves_the_case_out_of_both_arms(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    check = list(CHECK_RUN)
    check[5] = LEAK
    build(runs, check=check)
    out = diagnose(capsys)
    line = _line(_section(out, 1), "top-1, loop - arm B check: ")
    assert line.endswith("n=19"), line
    assert "guard refusals 1" in _line(_section(out, 5), "- arm B ordering check: ")
    assert "- all: n=19;" in _line(_section(out, 6), "- all: ")


def test_an_abstained_answer_is_wrong_and_a_changed_flag_is_counted_apart() -> None:
    before = dg.Point(RIGHT, right=True)
    abstained = dg.Point(RIGHT, right=False)
    t = dg.transition([(before, abstained), (dg.Point(WRONG, False), dg.Point(RIGHT, True))])
    assert t == dg.Transition(cases=2, changed=1, fixes=1, breaks=0, score_only=1)
    case = _case(0, "R")
    assert dg.hypothesis_top1(_hyp(RIGHT), case, TABLES)
    assert not dg.hypothesis_top1(_hyp(RIGHT, abstain=True), case, TABLES)
    assert not dg.hypothesis_top1(_hyp(WRONG), case, TABLES)


def test_the_last_checkpoint_before_coding_is_the_latest_of_h0_h1_h2() -> None:
    case_id = _IDS[0]
    rows = [
        _checkpoint(case_id, "h0", 0, "W"),
        _checkpoint(case_id, "h1", 2, "W"),
        _checkpoint(case_id, "h2", 4, "R"),
        _call(case_id, "describe_codes", index=5),
        _checkpoint(case_id, "answer", 6, "W"),
    ]
    found = dg.loop_cases(rows, [_case(0, "W")])[case_id]
    assert found.h0 is not None
    assert dg.first_code(found.h0, TABLES) == WRONG
    assert found.before_coding is not None
    assert dg.first_code(found.before_coding, TABLES) == RIGHT
    assert found.band == "none"
    assert found.reading == dg.NOTHING


# --------------------------------------------------------------------------------------------
# Counts only, and the refusals
# --------------------------------------------------------------------------------------------


def test_no_case_number_appears_in_the_output(
    runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out_file = tmp_path / "diagnosis.txt"
    out = diagnose(capsys, "--out", str(out_file))
    assert "ZQX" not in out
    assert "ZQX" not in out_file.read_text()
    assert out_file.read_text() == out


def test_an_uncommitted_decision_0153_is_refused_before_any_run_is_read(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(runs)

    def no_read(*_: object) -> None:
        raise AssertionError("a held-out run was opened")

    monkeypatch.setattr(dg, "load_heldout", no_read)
    with pytest.raises(SystemExit, match="0153-a-counts-only"):
        dg.main(_argv(), is_committed=lambda path: path != dg.DECISION)


def test_an_uncommitted_registration_is_refused_before_any_run_is_read(runs: Path) -> None:
    # no folder exists: a read would fail with "no run.jsonl", not with this message
    with pytest.raises(SystemExit, match=r"s3-registration\.md"):
        dg.main(_argv(), is_committed=lambda path: path == dg.DECISION)
    assert not runs.exists()


def test_s32_claims_id_rules_apply(runs: Path) -> None:
    with pytest.raises(SystemExit, match="--armb-tools must be"):
        dg.main(_argv(**{"armb-tools": f"{ANSWER}-other"}), is_committed=_always)
    with pytest.raises(SystemExit, match="named twice"):
        dg.main(_argv(nodocket=LOOP), is_committed=_always)
    assert not runs.exists()


def test_a_dirty_tree_is_refused_for_a_result_under_docs_results(
    runs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sr, "changed_files", lambda: ["src/x.py"])
    with pytest.raises(SystemExit, match="uncommitted"):
        dg.main([*_argv(), "--out", "docs/results/s32-heldout-diagnosis.txt"], is_committed=_always)
    assert not runs.exists()


def test_a_run_is_checked_against_the_registration_as_s32_claims_checks_it(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    (runs / LOOP / "trail.jsonl").unlink()
    with pytest.raises(SystemExit, match=r"no trail\.jsonl"):
        diagnose(capsys)


# --------------------------------------------------------------------------------------------
# Review fixes: a clean tree always, one trigger, retried checkpoints, early failures
# --------------------------------------------------------------------------------------------


def test_a_dirty_tree_is_refused_without_out_before_any_run_is_read(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sr, "changed_files", lambda: ["src/x.py"])
    with pytest.raises(SystemExit, match="uncommitted"):
        dg.main(_argv(), is_committed=_always)
    assert not runs.exists()


def test_a_changed_results_file_is_not_a_dirty_tree(
    runs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    monkeypatch.setattr(sr, "changed_files", lambda: ["docs/results/s32-claims-heldout.txt"])
    assert "## 6." in diagnose(capsys)


def test_a_second_trigger_is_refused(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trail = _trail()
    trail[0] = trail[0].model_copy(update={"trigger": 2})
    build(runs, trail=trail)
    with pytest.raises(SystemExit, match="trigger other than 1"):
        diagnose(capsys)


def test_a_retried_checkpoint_takes_the_accepted_hypothesis() -> None:
    case_id = _IDS[0]
    rejected = _call(case_id, "record_hypothesis", index=0, error="bad")
    rows = [
        rejected.model_copy(update={"step": "h0"}),
        _checkpoint(case_id, "h0", 1, "R").model_copy(update={"retry": True}),
        _checkpoint(case_id, "h1", 3, "W"),
        _call(case_id, "record_hypothesis", index=4, error="bad").model_copy(
            update={"step": "h2", "retry": False}
        ),
        _call(case_id, "describe_codes", index=5),
    ]
    found = dg.loop_cases(rows, [_case(0, "W")])[case_id]
    assert found.h0 is not None
    assert dg.first_code(found.h0, TABLES) == RIGHT
    assert found.before_coding is not None  # the rejected h2 records nothing: h1 stands
    assert dg.first_code(found.before_coding, TABLES) == WRONG


def test_h0_is_the_first_accepted_h0() -> None:
    case_id = _IDS[0]
    rows = [_checkpoint(case_id, "h0", 0, "R"), _checkpoint(case_id, "h0", 1, "W")]
    found = dg.loop_cases(rows, [_case(0, "W")])[case_id]
    assert found.h0 is not None
    assert dg.first_code(found.h0, TABLES) == RIGHT


def test_loop_failures_before_any_read_choice_are_counted(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    loop = list(LOOP_RUN)
    loop[15] = "failed: h0"  # nothing on offer, no read choice
    loop[3] = "failed: choice1"  # a read choice row exists: not counted
    build(runs, loop=loop)
    out = diagnose(capsys)
    assert _line(_section(out, 2), "- documents offered none: ").endswith(
        "; of which 1 are loop failures before any read choice"
    )
    assert _line(_section(out, 3), f"- {dg.NOTHING}: ").endswith(
        "; of which 1 are loop failures before any read choice"
    )


def test_section_3_carries_its_caution(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs)
    lines = _section(diagnose(capsys), 3)
    assert lines[1].startswith("caution: cases that read every document on offer are concentrated")
    assert "confounded by docket size" in lines[1]
