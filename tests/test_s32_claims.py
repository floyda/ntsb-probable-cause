"""scripts/s32_claims.py: the held-out verdict, the four results, the predictions (Task 11).

Every run folder is made up under ``tmp_path``: the six held-out runs, the coding ablation and
the two noise-floor runs, with made-up case numbers and made-up costs. No real held-out or
sealed data is read, and the repository's state (the registration, a dirty tree) is faked.
Offline.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from scripts import _s3_runs as sr
from scripts import s32_claims as sc
from scripts import s32_coding_ablation as ab
from tests.test_s3_noise_floor import (
    _IDS,
    _call,
    _choose,
    _failed,
    _record,
    _scored,
    _spec_json,
    _write,
)

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent.run import GUIDANCE
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring import calibration, samples
from ntsb_probable_cause.scoring.calibration import Curve
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl

FROZEN = "s3-v1+ge17fecdc66ec+p947fac1c86a4"
ARM_A = "20261010T000000-abc1234-heldout-400-A"
ANSWER = "20261010T010000-abc1234-heldout-400-B"
TOOLS = f"{ANSWER}-tools"
CHECK = f"{TOOLS}-check-luna"
LOOP = "20261010T030000-abc1234-heldout-400-C"
NODOCKET = "20261010T050000-abc1234-heldout-400-C"
ABLATION = "20261005T010000-abc1234-dev-400-C"
NOISE = ab.NOISE_RUNS
ANSWER_PV = "s1-v6+gabcdef123456"
DOCKET_ROLES = ("docket_documents", "docket_listing")
ALL = (True,) * 20
NONE = (False,) * 20


@dataclass
class World:
    """What a made-up set of runs holds; the defaults make the loop and arm B level."""

    loop_hits: Sequence[bool] = (True,) * 10 + (False,) * 10
    armb_hits: Sequence[bool] = (True,) * 10 + (False,) * 10
    arma_hits: Sequence[bool] = (True,) * 4 + (False,) * 16
    nodocket_hits: Sequence[bool] = (True,) * 10 + (False,) * 10
    ablation_hits: Sequence[bool] = NONE
    noise_hits: Sequence[bool] = (True,) * 10 + (False,) * 10
    loop_cost: tuple[float, float] = (1.0, 2.0)  # billed, computed
    armb_parts: tuple[tuple[float, float], ...] = ((0.5, 0.6), (0.4, 0.5), (0.1, 0.1))
    loop_calls: list[AgentCall] = field(default_factory=list)
    loop_failures: dict[int, str] = field(default_factory=dict)
    armb_failures: dict[int, str] = field(default_factory=dict)
    loop_confidence: Sequence[float] = (0.5,) * 20
    unbilled_check: bool = False


def _cases(
    hits: Sequence[bool],
    failures: dict[int, str] | None = None,
    confidence: Sequence[float] = (0.5,) * 20,
    split: str = "heldout",
) -> list[CaseResult]:
    cases: list[CaseResult] = []
    for n, case_id in enumerate(_IDS):
        if failures and n in failures:
            case = _failed(case_id, failures[n])
        else:
            case = _scored(case_id, top1=hits[n], confidence=confidence[n], fatal=n < 5)
        cases.append(case.model_copy(update={"split": split}))
    return cases


def _held_record(run_id: str, arm: str, cost: tuple[float, float], **changes: object) -> RunRecord:
    base = {
        "sample": "heldout-400",
        "arm": arm,
        "cap_usd": 0.30,
        "reasoning_effort": "medium",
        "max_output_tokens": 8000,
        "cost_usd": cost[1],
        "reported_batch_cost_usd": cost[0],
        "batch_ids": ("batch1",),
        "guidance": () if arm == "A" else GUIDANCE,
        "prompt_version": FROZEN if arm == "C" else ANSWER_PV,
    }
    return _record(run_id, 20).model_copy(update=base | changes)


def _ledger_rows(run_ids: Sequence[str]) -> str:
    head = "# Held-out ledger\n\n| date | sample | arm | results |\n|---|---|---|---|\n"
    rows = "".join(f"| 2026-10-10 | heldout-400 | X | {r}/cases.jsonl |\n" for r in run_ids)
    return head + rows


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, the ledger, the registration (committed) and the sample ids."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    ledger = tmp_path / "ledger.md"
    ledger.write_text(_ledger_rows([ARM_A, ANSWER, TOOLS, CHECK, LOOP, NODOCKET]))
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger))
    monkeypatch.setattr(
        samples, "sample_ids", lambda name: _IDS if name in {"dev-400", "heldout-400"} else ()
    )
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): True)
    return folder


def build(runs: Path, world: World | None = None) -> World:
    """Write the nine run folders of a made-up world."""
    w = world or World()
    ids = list(_IDS)
    spec_c = _spec_json(ids)
    _write(
        runs,
        ARM_A,
        _cases(w.arma_hits),
        record=_held_record(ARM_A, "A", (0.3, 0.3)),
    )
    _write(
        runs,
        ANSWER,
        _cases(w.armb_hits),
        record=_held_record(ANSWER, "B", w.armb_parts[0]),
    )
    tools_calls = [_call(_IDS[0], "describe_codes", prompt_tokens=700, cached=500)]
    _write(
        runs,
        TOOLS,
        _cases(w.armb_hits),
        tools_calls,
        record=_held_record(
            TOOLS, "B", w.armb_parts[1], prompt_version=f"{ANSWER_PV}+tools-s3+p947fac1c86a4"
        ),
    )
    check_cost = w.armb_parts[2]
    _write(
        runs,
        CHECK,
        _cases(w.armb_hits, w.armb_failures),
        record=_held_record(
            CHECK,
            "B",
            check_cost,
            prompt_version=f"{ANSWER_PV}+tools-s3+p947fac1c86a4+check-luna-s3",
            batch_ids=(),
            reported_batch_cost_usd=None,
        ),
    )
    _write(
        runs,
        LOOP,
        _cases(w.loop_hits, w.loop_failures, w.loop_confidence),
        w.loop_calls,
        spec=spec_c,
        record=_held_record(LOOP, "C", w.loop_cost),
    )
    _write(
        runs,
        NODOCKET,
        _cases(w.nodocket_hits),
        spec=spec_c,
        record=_held_record(NODOCKET, "C", (0.5, 1.0), exclusions=DOCKET_ROLES),
    )
    dev_ids = [c.case_id for c in _cases(w.ablation_hits, split="dev")]
    _write(
        runs,
        ABLATION,
        _cases(w.ablation_hits, split="dev"),
        spec=_spec_json(dev_ids, without=["coding"]),
    )
    for noise_id in NOISE:
        _write(runs, noise_id, _cases(w.noise_hits, split="dev"))
    return w


def _argv(**overrides: str) -> list[str]:
    values = {
        "loop": LOOP,
        "nodocket": NODOCKET,
        "arm-a": ARM_A,
        "armb-answer": ANSWER,
        "armb-tools": TOOLS,
        "armb-check": CHECK,
        "ablation": ABLATION,
    } | overrides
    argv: list[str] = []
    for flag, value in values.items():
        argv += [f"--{flag}", value]
    return [*argv, "--noise", *NOISE]


def run_claims(capsys: pytest.CaptureFixture[str], *extra: str, **overrides: str) -> str:
    """Run the script on the nine folders and return what it printed."""
    assert sc.main([*_argv(**overrides), *extra]) == 0
    return capsys.readouterr().out


def _line(out: str, start: str) -> str:
    return next(line for line in out.splitlines() if line.startswith(start))


def _read_everything_calls(read: bool) -> list[AgentCall]:
    calls: list[AgentCall] = []
    for case_id in _IDS:
        row = _choose(case_id, {1: read, 2: read}, offered=(1, 2))
        calls.append(row.model_copy(update={"step": "choice1"}))
    return calls


def _fixed_order_calls() -> list[AgentCall]:
    order = ("describe_codes", "occurrence_usage", "past_findings", "suggest_codes")
    return [_call(c, tool, index=10 + i) for c in _IDS for i, tool in enumerate(order)]


# --------------------------------------------------------------------------------------------
# The verdict: one test per path, each checking the headline
# --------------------------------------------------------------------------------------------


def test_warranted_by_beats_at_equal_cost(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs, World(loop_hits=ALL, armb_hits=NONE, loop_cost=(1.0, 2.0)))
    out = run_claims(capsys)
    assert "On held-out cases, the loop beat the fixed pipeline at equal or lower cost." in out
    assert "outcome: beats" in out
    assert "cost band: equal" in out
    assert "warranted: yes" in out


def test_warranted_by_matches_at_lower_cost(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs, World(loop_cost=(0.5, 2.0)))
    out = run_claims(capsys)
    assert "On held-out cases, the loop matched the fixed pipeline at lower cost." in out
    assert "outcome: matches" in out
    assert "cost band: lower" in out
    assert "warranted: yes" in out


def test_not_warranted_by_matches_at_equal_cost(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    assert (
        "On held-out cases, the loop was not shown to improve on the fixed pipeline: "
        "it matched it at equal or greater cost."
    ) in out
    assert "warranted: no" in out


def test_not_warranted_by_beats_at_greater_cost(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_hits=ALL, armb_hits=NONE, loop_cost=(2.0, 3.0)))
    out = run_claims(capsys)
    assert "it beat it only at greater cost." in out
    assert "cost band: greater" in out


def test_not_warranted_by_worse(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs, World(loop_hits=NONE, armb_hits=ALL, loop_cost=(0.5, 2.0)))
    out = run_claims(capsys)
    assert (
        "On held-out cases, the loop was not shown to improve on the fixed pipeline: it was worse."
        in out
    )
    assert "outcome: worse" in out


def test_not_warranted_by_undecided(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    loop = (True,) * 3 + (False,) * 5 + (True,) * 6 + (False,) * 6
    armb = (False,) * 3 + (True,) * 5 + (True,) * 6 + (False,) * 6
    build(runs, World(loop_hits=loop, armb_hits=armb))
    out = run_claims(capsys)
    assert "it was undecided." in out
    assert "outcome: undecided" in out


def test_the_verdict_prints_the_interval_n_and_the_bottom_on_its_own_line(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_hits=ALL, armb_hits=NONE))
    out = run_claims(capsys)
    assert "top-1, loop - arm B: +100.0 points [+100.0, +100.0], n=20" in out
    assert "bottom of the interval: +100.0 points" in out
    assert "a stricter margin can be applied to this figure" in out
    assert "both answered +100.0 points" in out


def test_a_guard_refusal_in_arm_b_removes_the_case_from_the_loops_comparison(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(armb_failures={0: f"leak: {_IDS[0]}: verbatim from probable_cause"}))
    out = run_claims(capsys)
    assert "top-1, loop - arm B: +0.0 points" in out
    assert "n=19" in out
    assert "n=20" not in _line(out, "top-1, loop - arm B")


def test_a_failure_in_the_loop_counts_as_wrong(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_failures={0: "failed: coding"}))
    out = run_claims(capsys)
    assert "top-1, loop - arm B: -5.0 points" in out
    assert "n=20" in _line(out, "top-1, loop - arm B")


# --------------------------------------------------------------------------------------------
# Cost, tokens, saving
# --------------------------------------------------------------------------------------------


def test_the_cost_section_sums_arm_b_and_prints_computed_beside(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    assert "arm B billed 1.0000 USD (answer 0.5000 + tools 0.4000 + check 0.1000)" in out
    assert "arm B computed 1.2000 USD" in out
    assert "loop billed 1.0000 USD, computed 2.0000 USD" in out


def test_a_check_run_with_no_batch_is_billed_at_its_cost(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    assert "every figure used is a billed figure" in out


def test_a_batch_run_with_no_reported_bill_is_noted(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    folder = runs / LOOP
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["reported_batch_cost_usd"] = None
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    out = run_claims(capsys)
    assert "NOTE: no billed figure was reported for the loop" in out


def test_tokens_are_summed_from_the_trails(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    calls = [
        _call(_IDS[0], "describe_codes", prompt_tokens=1000, cached=600),
        _call(_IDS[1], "describe_codes", prompt_tokens=500, cached=None),
    ]
    build(runs, World(loop_calls=calls))
    out = run_claims(capsys)
    assert "loop: 1500 prompt tokens, 600 cached" in out
    assert "arm B tool post-pass: 700 prompt tokens, 500 cached" in out
    assert "answer and check runs keep no trail" in out


def test_the_saving_split_is_always_figures_and_explained_when_lower(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_cost=(0.5, 2.0)))
    out = run_claims(capsys)
    assert "work (loop computed - arm B computed): +0.8000 USD" in out
    assert "loop discount (computed - billed): 1.5000 USD" in out
    assert "arm B discount (computed - billed): 0.2000 USD" in out
    assert "the loop's saving comes from" in out


def test_the_saving_split_is_figures_only_when_not_lower(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    assert "work (loop computed - arm B computed)" in out
    assert "the loop's saving comes from" not in out


# --------------------------------------------------------------------------------------------
# The predictions, each branch
# --------------------------------------------------------------------------------------------


def _prediction(out: str, number: int) -> str:
    return _line(out, f"P{number}: ")


@pytest.mark.parametrize(
    ("world", "met"),
    [(World(), True), (World(loop_hits=ALL, armb_hits=NONE), False)],
)
def test_prediction_1(
    runs: Path, capsys: pytest.CaptureFixture[str], world: World, met: bool
) -> None:
    build(runs, world)
    assert _prediction(run_claims(capsys), 1).startswith("P1: " + ("met" if met else "not met"))


@pytest.mark.parametrize(("cost", "met"), [((0.5, 2.0), True), ((1.0, 2.0), False)])
def test_prediction_2(
    runs: Path, capsys: pytest.CaptureFixture[str], cost: tuple[float, float], met: bool
) -> None:
    build(runs, World(loop_cost=cost))
    assert _prediction(run_claims(capsys), 2).startswith("P2: " + ("met" if met else "not met"))


@pytest.mark.parametrize(
    ("world", "met"),
    [(World(loop_hits=NONE, armb_hits=ALL), True), (World(), False)],
)
def test_prediction_3(
    runs: Path, capsys: pytest.CaptureFixture[str], world: World, met: bool
) -> None:
    build(runs, world)
    assert _prediction(run_claims(capsys), 3).startswith("P3: " + ("met" if met else "not met"))


@pytest.mark.parametrize(
    ("world", "met"),
    [(World(), True), (World(loop_hits=ALL, armb_hits=NONE), False)],
)
def test_prediction_4(
    runs: Path, capsys: pytest.CaptureFixture[str], world: World, met: bool
) -> None:
    build(runs, world)
    assert _prediction(run_claims(capsys), 4).startswith("P4: " + ("met" if met else "not met"))


@pytest.mark.parametrize(
    ("nodocket", "met"),
    [(NONE, True), ((True,) * 10 + (False,) * 10, False)],
)
def test_prediction_5(
    runs: Path, capsys: pytest.CaptureFixture[str], nodocket: Sequence[bool], met: bool
) -> None:
    build(runs, World(nodocket_hits=nodocket))
    assert _prediction(run_claims(capsys), 5).startswith("P5: " + ("met" if met else "not met"))


def test_prediction_5_reads_exactly_ten_points_as_met(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 18 hits against the loop's 20: a mean of -0.10 exactly
    build(runs, World(loop_hits=ALL, nodocket_hits=(True,) * 18 + (False,) * 2))
    assert _prediction(run_claims(capsys), 5).startswith("P5: met")


@pytest.mark.parametrize(("ablation", "met"), [(NONE, True), ((True,) * 10 + (False,) * 10, False)])
def test_prediction_6(
    runs: Path, capsys: pytest.CaptureFixture[str], ablation: Sequence[bool], met: bool
) -> None:
    build(runs, World(ablation_hits=ablation))
    assert _prediction(run_claims(capsys), 6).startswith("P6: " + ("met" if met else "not met"))


def test_prediction_7_met_and_not_met(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(runs, World(loop_calls=_read_everything_calls(True)))
    assert _prediction(run_claims(capsys), 7).startswith("P7: met")


def test_prediction_7_not_met_when_the_loop_skips_documents(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_calls=_read_everything_calls(False)))
    assert _prediction(run_claims(capsys), 7).startswith("P7: not met")


def test_prediction_7_not_met_when_the_fixed_order_is_common(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = [*_read_everything_calls(True), *_fixed_order_calls()]
    build(runs, World(loop_calls=calls))
    assert _prediction(run_claims(capsys), 7).startswith("P7: not met")


def test_prediction_8_met_when_calibrated_and_the_cut_off_seldom_fires(
    runs: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "load_curve", lambda path=None: Curve(0.0, 0.0))
    alternate = (True, False) * 10  # half right everywhere, a curve of one half everywhere
    build(runs, World(loop_hits=alternate, armb_hits=alternate))
    out = run_claims(capsys)
    assert _prediction(out, 8).startswith("P8: met")
    assert "result 3: does not hold" in out


def test_prediction_8_not_met_when_not_calibrated(
    runs: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "load_curve", lambda path=None: Curve(0.0, 0.0))
    build(runs, World(loop_hits=NONE, armb_hits=NONE))
    out = run_claims(capsys)
    assert _prediction(out, 8).startswith("P8: not met")
    assert "result 3: holds" in out
    assert "the board shows its confidence with a plain warning" in out


def test_prediction_8_not_met_when_the_cut_off_fires_often(
    runs: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "load_curve", lambda path=None: Curve(-3.0, 0.0))
    build(runs, World(loop_hits=NONE, armb_hits=NONE))
    out = run_claims(capsys)
    assert _prediction(out, 8).startswith("P8: not met")
    assert "fired on 20 of 20 scored loop cases" in out


@pytest.mark.parametrize(("failed", "met"), [(8, True), (9, False)])
def test_prediction_9(
    runs: Path, capsys: pytest.CaptureFixture[str], failed: int, met: bool
) -> None:
    failures = dict.fromkeys(range(failed), "failed: coding")
    build(runs, World(loop_failures=failures))
    assert _prediction(run_claims(capsys), 9).startswith("P9: " + ("met" if met else "not met"))


# --------------------------------------------------------------------------------------------
# The results, the abstain reading, the ablations, the reading
# --------------------------------------------------------------------------------------------


def test_result_1_is_read_from_the_loop_trail(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_calls=_read_everything_calls(True)))
    out = run_claims(capsys)
    assert "result 1: holds" in out
    assert "read every document on offer: 20 of 20" in out


def test_result_2_holds_when_the_loop_does_not_beat_arm_b_and_costs_no_less(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    assert "result 2: holds" in run_claims(capsys)


def test_result_2_does_not_hold_when_the_loop_is_cheaper(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_cost=(0.5, 2.0)))
    assert "result 2: does not hold" in run_claims(capsys)


def _result_lines(out: str, number: int) -> list[str]:
    """The ``result N:`` line in section 5 and the one in section 9, in that order."""
    return [line for line in out.splitlines() if line.startswith(f"result {number}:")]


def test_result_3_line_states_the_finding_when_the_curve_is_calibrated(
    runs: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "load_curve", lambda path=None: Curve(0.0, 0.0))
    alternate = (True, False) * 10
    build(runs, World(loop_hits=alternate, armb_hits=alternate))
    lines = _result_lines(run_claims(capsys), 3)
    assert lines == [
        "result 3: does not hold (the fitted confidence is calibrated on held-out; "
        "spec §9.3, §8.3)",
        "result 3: does not hold (the fitted confidence is calibrated on held-out)",
    ]


def test_result_3_line_states_the_finding_when_the_curve_is_not_calibrated(
    runs: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "load_curve", lambda path=None: Curve(0.0, 0.0))
    build(runs, World(loop_hits=NONE, armb_hits=NONE))
    lines = _result_lines(run_claims(capsys), 3)
    assert lines == [
        "result 3: holds (the fitted confidence is not calibrated on held-out; spec §9.3, §8.3)",
        "result 3: holds (the fitted confidence is not calibrated on held-out)",
    ]


def test_result_1_and_2_lines_state_the_finding_when_they_hold(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_calls=_read_everything_calls(True)))
    out = run_claims(capsys)
    assert _result_lines(out, 1)[0] == (
        "result 1: holds (more than half on at least one reading; spec §9.1)"
    )
    assert _result_lines(out, 2)[0].startswith(
        "result 2: holds (the loop does not beat arm B on top-1 and its bill is not lower; "
    )


def test_result_1_and_2_lines_state_the_finding_when_they_do_not_hold(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_cost=(0.5, 2.0)))
    out = run_claims(capsys)
    assert _result_lines(out, 1)[0] == (
        "result 1: does not hold (not more than half on either reading; spec §9.1)"
    )
    assert _result_lines(out, 2)[0].startswith(
        "result 2: does not hold (the loop beats arm B on top-1 or its bill is lower; "
    )


def test_result_3_prints_each_group_and_the_sorting_figure(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_confidence=tuple(0.2 + 0.03 * n for n in range(20))))
    out = run_claims(capsys)
    for group in ("low", "middle", "high"):
        assert f"group {group}:" in out
    assert "sorting (share right in the high group minus the low group)" in out
    assert "calibrated:" in out


def test_result_4_is_not_shown_and_counts_the_routes(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    label = next(name for name in load_tables().events.values() if len(name) >= 6)
    arguments = {
        "decisions": [
            {"document": 1, "read": True, "expected_effect": f"this may show {label}"},
            {"document": 2, "read": True, "expected_effect": "what it shows"},
        ],
        "reason": "r",
    }
    row = _choose(_IDS[0], {1: True, 2: True}, offered=(1, 2))
    row = row.model_copy(update={"arguments": arguments, "step": "choice1"})
    build(runs, World(loop_calls=[row]))
    out = run_claims(capsys)
    assert "result 4: not shown" in out
    assert "stated effects on documents read: 2" in out
    assert "event label (strict) 1" in out
    assert "upper bound" in out


def test_the_curve_floor_and_whether_the_cut_off_can_fire_are_printed(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    floor = calibration.load_curve().p(0.0)
    assert f"curve floor p(0) = {floor:.3f}" in out
    can = floor < calibration.ABSTAIN_BELOW
    assert ("can fire" if can else "cannot fire") in out


def test_the_abstain_reading_gives_the_share_right_in_each_part(
    runs: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "load_curve", lambda path=None: Curve(-3.0, 6.0))
    # fitted below 0.164 only for a stated confidence under about 0.3
    confidence = (0.1,) * 5 + (0.8,) * 15
    hits = (False,) * 5 + (True,) * 15
    build(runs, World(loop_hits=hits, armb_hits=hits, loop_confidence=confidence))
    out = run_claims(capsys)
    assert "fired on 5 of 20 scored loop cases" in out
    assert "right among abstained: 0 of 5" in out
    assert "right among answered: 15 of 15" in out


def test_the_no_docket_ablation_and_arm_a_are_printed(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(nodocket_hits=NONE))
    out = run_claims(capsys)
    assert "no-docket - loop, top-1: -50.0 points" in out
    assert "no-docket - loop, top-3:" in out
    assert "no-docket - loop, recall@10:" in out
    assert "arm A top-1: 20.0% [" in out


def test_the_reading_states_the_board_consequences(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    assert 'the board labels a stated effect "the agent\'s note", never a prediction' in out
    assert "question 1:" in out
    for number in (1, 2, 3, 4):
        assert f"result {number}:" in out.split("## 9. The reading")[1]


def test_the_sections_come_in_the_briefs_order(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    headings = [
        "## 1. Provenance",
        "## 2. The verdict",
        "## 3. Secondary readings",
        "## 4. Where the saving comes from",
        "## 5. The four results",
        "## 6. Abstain",
        "## 7. The no-docket ablation and arm A",
        "## 8. The predictions",
        "## 9. The reading",
    ]
    positions = [out.index(h) for h in headings]
    assert positions == sorted(positions)


def test_provenance_lists_every_run_and_its_ledger_row(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    for run_id in (ARM_A, ANSWER, TOOLS, CHECK, LOOP, NODOCKET, ABLATION, *NOISE):
        assert f"run {run_id} [complete]" in out
    assert f"ledger: | 2026-10-10 | heldout-400 | X | {LOOP}/cases.jsonl |" in out


def test_the_output_holds_no_case_id(
    runs: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    build(
        runs,
        World(
            armb_failures={0: f"leak: {_IDS[0]}: verbatim from probable_cause"},
            loop_failures={1: "failed: coding"},
            loop_calls=_read_everything_calls(True),
        ),
    )
    target = tmp_path / "out" / "claims.txt"
    out = run_claims(capsys, "--out", str(target))
    assert "ZQX" not in out
    assert "ZQX" not in target.read_text()


# --------------------------------------------------------------------------------------------
# Refusals, before anything is read
# --------------------------------------------------------------------------------------------


def test_a_wrong_armb_tools_id_is_refused_before_anything_is_read(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # no folder exists: a read would fail with "no run.jsonl", not with this message
    with pytest.raises(SystemExit, match="--armb-tools must be"):
        sc.main(_argv(**{"armb-tools": f"{ANSWER}-other"}))
    assert not runs.exists()


def test_a_wrong_armb_check_id_is_refused_before_anything_is_read(runs: Path) -> None:
    with pytest.raises(SystemExit, match="--armb-check must be"):
        sc.main(_argv(**{"armb-check": f"{TOOLS}-check-jev"}))
    assert not runs.exists()


def test_other_noise_runs_are_refused_before_anything_is_read(runs: Path) -> None:
    argv = _argv()
    argv[-2:] = [NOISE[0], LOOP]
    with pytest.raises(SystemExit, match="noise-floor"):
        sc.main(argv)
    assert not runs.exists()


def test_a_run_named_twice_is_refused(runs: Path) -> None:
    with pytest.raises(SystemExit, match="named twice"):
        sc.main(_argv(nodocket=LOOP))
    assert not runs.exists()


def test_an_uncommitted_registration_is_refused_before_anything_is_read(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): False)
    with pytest.raises(SystemExit, match=r"s3-registration\.md"):
        sc.main(_argv())
    assert not runs.exists()


def test_a_dirty_tree_is_refused_for_a_result_under_docs_results(
    runs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sr, "changed_files", lambda: ["src/x.py"])
    with pytest.raises(SystemExit, match="uncommitted"):
        sc.main([*_argv(), "--out", "docs/results/s32-claims-heldout.txt"])
    assert not runs.exists()


def test_a_run_on_the_wrong_sample_is_refused(runs: Path) -> None:
    build(runs)
    folder = runs / LOOP
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["sample"] = "dev-400"
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="heldout-400"):
        sc.main(_argv())


def test_the_loop_must_carry_the_frozen_prompt_version(runs: Path) -> None:
    build(runs)
    spec = json.loads((runs / LOOP / "spec.json").read_text())
    spec["agent_prompt_version"] = "s3-v1+gother"
    (runs / LOOP / "spec.json").write_text(json.dumps(spec))
    with pytest.raises(SystemExit, match="agent_prompt_version"):
        sc.main(_argv())


def test_the_no_docket_run_must_exclude_exactly_the_two_docket_roles(runs: Path) -> None:
    build(runs)
    folder = runs / NODOCKET
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["exclusions"] = ["docket_listing"]
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="exclusions"):
        sc.main(_argv())


def test_the_loop_must_not_exclude_anything(runs: Path) -> None:
    build(runs)
    folder = runs / LOOP
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["exclusions"] = list(DOCKET_ROLES)
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="exclusions"):
        sc.main(_argv())


def test_the_check_run_must_carry_the_check_suffix(runs: Path) -> None:
    build(runs)
    folder = runs / CHECK
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["prompt_version"] = f"{ANSWER_PV}+tools-s3+p947fac1c86a4+check-luna"
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match=r"\+check-luna-s3"):
        sc.main(_argv())


def test_the_cap_must_be_thirty_cents(runs: Path) -> None:
    build(runs)
    folder = runs / ARM_A
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["cap_usd"] = 0.05
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="cap_usd"):
        sc.main(_argv())


def test_an_unfinished_run_is_refused(runs: Path) -> None:
    build(runs)
    folder = runs / ANSWER
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["finished"] = None
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="finished"):
        sc.main(_argv())


def test_a_run_from_a_dirty_tree_is_refused(runs: Path) -> None:
    build(runs)
    folder = runs / NODOCKET
    row = json.loads((folder / "run.jsonl").read_text().splitlines()[0])
    row["dirty"] = True
    (folder / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="uncommitted"):
        sc.main(_argv())


def test_a_run_with_a_development_case_is_refused(runs: Path) -> None:
    build(runs)
    _write_cases = _cases(NONE, split="dev")
    write_jsonl(runs / ARM_A / "cases.jsonl", _write_cases)
    with pytest.raises(SystemExit, match="held-out split"):
        sc.main(_argv())


def test_a_run_over_other_cases_than_the_sample_is_refused(runs: Path) -> None:
    build(runs)
    cases = _cases(NONE)
    cases[0] = cases[0].model_copy(update={"case_id": "ZQX999"})
    write_jsonl(runs / ARM_A / "cases.jsonl", cases)
    with pytest.raises(SystemExit, match="whole of heldout-400"):
        sc.main(_argv())


def test_a_missing_ledger_row_is_refused(runs: Path, tmp_path: Path) -> None:
    build(runs)
    (tmp_path / "ledger.md").write_text(_ledger_rows([ARM_A, ANSWER, TOOLS, CHECK, LOOP]))
    with pytest.raises(SystemExit, match="ledger"):
        sc.main(_argv())


def test_a_run_without_a_trail_is_refused(runs: Path) -> None:
    build(runs)
    (runs / LOOP / "trail.jsonl").unlink()
    with pytest.raises(SystemExit, match=r"trail\.jsonl"):
        sc.main(_argv())


# --------------------------------------------------------------------------------------------
# The dev-only loaders still refuse a held-out run
# --------------------------------------------------------------------------------------------


def test_the_dev_only_loader_still_refuses_a_held_out_run(runs: Path) -> None:
    build(runs)
    with pytest.raises(SystemExit, match="held-out"):
        sr.load_runs("prog", [LOOP])
    with pytest.raises(SystemExit, match="held-out"):
        sr.load_runs("prog", [NODOCKET])


def test_the_dev_only_loader_refuses_a_renamed_held_out_run(runs: Path) -> None:
    build(runs)
    renamed = "20261010T090000-abc1234-dev-400-C"
    (runs / LOOP).rename(runs / renamed)  # the id says dev; the record says held-out
    row = json.loads((runs / renamed / "run.jsonl").read_text().splitlines()[0])
    row["run_id"] = renamed
    (runs / renamed / "run.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="heldout-400"):
        sr.load_runs("prog", [renamed])


def test_the_claims_script_does_not_widen_what_the_loader_accepts(runs: Path) -> None:
    build(runs)
    sc.main(_argv())  # a full read of held-out through the claims script's own path...
    with pytest.raises(SystemExit, match="held-out"):
        sr.load_runs("prog", [LOOP])  # ...and the shared loader still refuses it


def test_prediction_7_needs_fewer_than_five_percent_for_the_fixed_order(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    one_case = [c for c in _fixed_order_calls() if c.case_id == _IDS[0]]
    build(runs, World(loop_calls=[*_read_everything_calls(True), *one_case]))
    # 1 of 20 is exactly 5%: not "fewer than 5%"
    assert _prediction(run_claims(capsys), 7).startswith("P7: not met")


def test_a_held_out_result_is_written_to_the_output_file(
    runs: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    build(runs)
    target = tmp_path / "out" / "claims.txt"
    printed = run_claims(capsys, "--out", str(target))
    assert target.read_text() == printed


def test_result_1_is_also_printed_by_fatal_and_by_documents_offered(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_calls=_read_everything_calls(True)))
    out = run_claims(capsys)
    assert "- fatal: 5 counted; read every document on offer 5 of 5 (100.0%)" in out
    assert "- non-fatal: 15 counted; read every document on offer 15 of 15 (100.0%)" in out
    assert "- 2-4: 20 counted; read every document on offer 20 of 20 (100.0%)" in out
    assert "- none: 0 counted" in out
    assert "by documents offered (docket size)" in out


def test_the_saving_is_split_by_an_identity_with_figures(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs, World(loop_cost=(0.5, 2.0)))
    out = run_claims(capsys)
    # billed saving 1.0 - 0.5 = +0.5 = (-0.8 work) + (1.5 - 0.2 discounts)
    assert (
        "billed saving (arm B billed - loop billed) +0.5000 USD = reading less (-work) "
        "-0.8000 USD + cache discounts (loop discount - arm B discount) +1.3000 USD"
    ) in out


def test_the_identity_is_printed_when_the_band_is_not_lower(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    assert "billed saving (arm B billed - loop billed) +0.0000 USD" in run_claims(capsys)


@pytest.mark.parametrize("role", [LOOP, NODOCKET])
def test_the_loop_runs_must_have_counted_in_s3_statistics(runs: Path, role: str) -> None:
    build(runs)
    spec = json.loads((runs / role / "spec.json").read_text())
    spec["stats"] = "s27"
    (runs / role / "spec.json").write_text(json.dumps(spec))
    with pytest.raises(SystemExit, match="stats"):
        sc.main(_argv())


def test_a_development_refusal_comes_before_any_held_out_case_is_read(runs: Path) -> None:
    build(runs)
    spec = json.loads((runs / ABLATION / "spec.json").read_text())
    spec["without"] = []
    (runs / ABLATION / "spec.json").write_text(json.dumps(spec))
    (runs / ARM_A / "cases.jsonl").write_text("not json\n")  # a read would fail differently
    with pytest.raises(SystemExit, match="coding ablation"):
        sc.main(_argv())


def test_the_format_gate_line_names_the_runs_own_sample(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(runs)
    out = run_claims(capsys)
    assert "format gate, run loop: PASS -- 0 of 20 cases failed" in out
    assert "at most 8 of 20 pass" in out
    assert "dev-400's 401" not in out.split("## 8.")[1]
