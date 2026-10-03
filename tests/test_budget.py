"""The monthly budget as a reservation under a lock (decision 0045)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import BudgetError
from ntsb_probable_cause.scoring.budget import (
    RELABEL_FILE,
    RESERVATION_FILE,
    SpendRecord,
    budget_lock,
    counts_billed,
    in_stage,
    month_spent,
    open_reservations,
    release,
    reserve,
    reserve_within_budget,
    settle,
    spent_usd,
    stage_spent,
    write_spend,
)
from ntsb_probable_cause.scoring.records import RunRecord, write_jsonl
from ntsb_probable_cause.scoring.runner import refuse_over_budget

NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_reserve_writes_a_reservation_the_next_run_can_see(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert (tmp_path / "run-1" / RESERVATION_FILE).exists()
    assert open_reservations(tmp_path) == {"run-1": 20.0}


def test_settle_removes_the_reservation(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    settle(tmp_path, "run-1")
    assert open_reservations(tmp_path) == {}
    settle(tmp_path, "run-1")  # idempotent


def test_release_reports_whether_anything_was_open(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert release(tmp_path, "run-1") is True
    assert release(tmp_path, "run-1") is False


def test_second_run_is_refused_when_the_first_reservation_fills_the_budget(tmp_path: Path) -> None:
    """The 2026-09-17 incident: four runs each projected $20 against $25 and all passed."""
    with budget_lock(tmp_path):
        refuse_over_budget(20.0, month_spent(tmp_path, now=NOW), 25.0, reserved=0.0)
        reserve(tmp_path, "run-1", 20.0, now=NOW)
    with budget_lock(tmp_path):
        reserved = sum(open_reservations(tmp_path).values())
        with pytest.raises(BudgetError, match="reserved"):
            refuse_over_budget(20.0, month_spent(tmp_path, now=NOW), 25.0, reserved=reserved)


def test_budget_lock_is_reentrant_across_processes_by_file(tmp_path: Path) -> None:
    """The lock is a file under the runs directory, created on first use."""
    with budget_lock(tmp_path):
        assert (tmp_path / ".budget.lock").exists()


def test_month_spent_ignores_reservations(tmp_path: Path) -> None:
    reserve(tmp_path, "run-1", 20.0, now=NOW)
    assert month_spent(tmp_path, now=NOW) == 0.0


def _spend(job_id: str, cost: float, started: datetime) -> SpendRecord:
    return SpendRecord(
        job_id=job_id,
        kind="transcription",
        model="google/gemini-3.1-flash-lite",
        started=started,
        calls=50,
        cost_usd=cost,
        commit_sha="abc1234",
        dirty=False,
    )


def test_month_spent_counts_preparation_spend_rows(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    write_spend(tmp_path, _spend("t1", 0.40, now))
    write_spend(tmp_path, _spend("t1", 0.35, now))
    write_spend(tmp_path, _spend("t0", 9.99, datetime(2026, 9, 30, tzinfo=UTC)))
    assert month_spent(tmp_path, now=now) == pytest.approx(0.75)


def test_reserve_within_budget_refuses_past_the_month(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    write_spend(tmp_path, _spend("t1", 30.0, now))
    with pytest.raises(BudgetError, match=r"exceeds the \$40.00 budget"):
        reserve_within_budget(tmp_path, "t2", 11.0, 40.0, now=now)
    reserve_within_budget(tmp_path, "t2", 9.0, 40.0, now=now)
    assert open_reservations(tmp_path) == {"t2": 9.0}


_STAGE = frozenset({"abcdef1234567890", "1234567abcdef000"})


def _run(runs_dir: Path, run_id: str, sha: str, cost: float) -> None:
    write_jsonl(
        runs_dir / run_id / "run.jsonl",
        [
            RunRecord(
                run_id=run_id,
                sample="dev-400",
                arm="B",
                exclusions=(),
                includes=(),
                prompt_version="s1-v5",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha=sha,
                dirty=False,
                started=datetime(2026, 9, 27, tzinfo=UTC),
                cost_usd=cost,
            )
        ],
    )


def test_in_stage_matches_a_short_sha_by_prefix_and_refuses_a_too_short_one() -> None:
    assert in_stage("abcdef1", _STAGE)
    assert not in_stage("abc", _STAGE)
    assert not in_stage("fffffff", _STAGE)


def test_stage_spent_counts_runs_and_spend_rows_of_the_stage_only(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run(runs, "in-stage", "abcdef1", 1.25)
    _run(runs, "other-stage", "9999999", 7.0)
    write_spend(
        runs,
        SpendRecord(
            job_id="job",
            kind="transcription",
            model="m",
            started=datetime(2026, 9, 27, tzinfo=UTC),
            calls=3,
            cost_usd=0.5,
            commit_sha="1234567",
            dirty=False,
        ),
    )
    assert stage_spent(runs, _STAGE) == (1.25, 0.5)


def test_a_probe_spend_row_validates_and_month_spent_counts_it(tmp_path: Path) -> None:
    """Decision 0131: ``probe`` is paid work that tests a shape or a flow."""
    now = datetime(2026, 10, 3, tzinfo=UTC)
    row = _spend("s3-probe-job", 0.25, now).model_copy(update={"kind": "probe"})
    assert SpendRecord.model_validate_json(row.model_dump_json()).kind == "probe"
    write_spend(tmp_path, row)
    assert month_spent(tmp_path, now=now) == pytest.approx(0.25)


def test_a_relabel_copy_beside_spend_jsonl_is_never_counted(tmp_path: Path) -> None:
    """Decision 0131 item 3: the kept original rows are not read by the budget code."""
    now = datetime(2026, 10, 3, tzinfo=UTC)
    probe = _spend("job", 0.25, now).model_copy(update={"kind": "probe"})
    write_spend(tmp_path, probe)
    write_jsonl(tmp_path / "job" / RELABEL_FILE, [probe.model_copy(update={"kind": "inventory"})])
    assert RELABEL_FILE == "spend-before-relabel.jsonl"
    assert month_spent(tmp_path, now=now) == pytest.approx(0.25)
    assert stage_spent(tmp_path, frozenset({"abc1234" + "0" * 33})) == (0.0, 0.25)


# --------------------------------------------------------------------------------------------
# What a run counts as spent (decision 0135): the billed total for S3's batch runs only
# --------------------------------------------------------------------------------------------

# The S3.1 batch smoke run's two figures (its run.jsonl): the computed price, which prices every
# prompt token at the full batch input rate, and the 12 batches' own reported total.
COMPUTED = 0.1458389
BILLED = 0.048429965
# Arm C's prompt version, and arm B's tool post-pass's: the source's with ``+tools-s3``.
ARM_C_VERSION = "s3-v1+ge17fecdc66ec+p10738adc39f3"
TOOLS_VERSION = "s1-v6+g0123456789ab+tools-s3+p10738adc39f3"


def _record(**changes: object) -> RunRecord:
    """An arm C batch run whose every round reported its cost, as the smoke run was."""
    record = RunRecord(
        run_id="20261001T140150-5a63002-dev-400-C",
        sample="dev-400",
        arm="C",
        exclusions=(),
        includes=(),
        prompt_version=ARM_C_VERSION,
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.15,
        budget_usd=50.0,
        commit_sha="5a63002",
        dirty=False,
        started=datetime(2026, 10, 1, 14, 1, 50, tzinfo=UTC),
        batch_ids=tuple(f"b{n}" for n in range(1, 13)),
        cases=20,
        cost_usd=COMPUTED,
        reported_batch_cost_usd=BILLED,
    )
    return record.model_copy(update=changes)


def test_an_arm_c_batch_run_counts_what_the_provider_billed() -> None:
    record = _record()
    assert counts_billed(record)
    assert spent_usd(record) == BILLED
    assert record.cost_usd == COMPUTED  # both figures stay in the record


def test_arm_bs_tool_post_pass_counts_what_the_provider_billed() -> None:
    """The post-pass is a derived arm B run; its prompt version holds ``+tools-``."""
    record = _record(arm="B", prompt_version=TOOLS_VERSION, run_id="r-tools")
    assert counts_billed(record)
    assert spent_usd(record) == BILLED


@pytest.mark.parametrize("arm", ["C", "B"])
def test_a_round_that_reported_no_cost_leaves_the_computed_price_counted(arm: str) -> None:
    version = ARM_C_VERSION if arm == "C" else TOOLS_VERSION
    record = _record(arm=arm, prompt_version=version, reported_batch_cost_usd=None)
    assert not counts_billed(record)
    assert spent_usd(record) == COMPUTED


def test_a_sync_arm_c_run_counts_the_computed_price() -> None:
    """A sync run has no rounds, so no reported total: the smoke run at the standard price."""
    record = _record(price_variant="standard", batch_ids=(), reported_batch_cost_usd=None)
    assert spent_usd(record) == COMPUTED


@pytest.mark.parametrize(
    ("arm", "version"),
    [
        ("A", "s1-v6"),
        ("B", "s1-v6+g0123456789ab"),
        ("ceiling", "s1-v6"),
        ("B", "s1-v5"),
    ],
)
def test_every_earlier_kind_of_run_counts_the_computed_price_even_with_a_reported_total(
    arm: str, version: str
) -> None:
    """No run from before S3 changes its counted spend: arms A, B and the ceiling all report a
    batch total, and they keep counting ``cost_usd`` (decision 0135 is scoped to S3's kinds)."""
    record = _record(arm=arm, prompt_version=version, reported_batch_cost_usd=0.01)
    assert not counts_billed(record)
    assert spent_usd(record) == COMPUTED


def test_a_judge_pass_on_an_arm_c_run_counts_its_own_cost() -> None:
    """The judge's record copies the judged run's arm and prompt version and reports no batch
    total (``apps/eval``'s ``_record_judge_cost``), so it counts its ``cost_usd``, as before."""
    judge = _record(
        run_id="20261001T140150-5a63002-dev-400-C-judge",
        model="judge-model",
        price_variant="standard",
        batch_ids=(),
        cost_usd=0.02,
        reported_batch_cost_usd=None,
    )
    assert spent_usd(judge) == 0.02


def test_an_ordering_check_on_a_tool_post_pass_counts_its_own_cost() -> None:
    """A check pass is synchronous and records no batch total (``scoring/checkpass.py``), so a
    check on a post-pass, whose version still holds ``+tools-``, counts its ``cost_usd``."""
    check = _record(
        run_id="r-tools-check-luna",
        arm="B",
        prompt_version=f"{TOOLS_VERSION}+check-luna-s3",
        batch_ids=(),
        cost_usd=0.003,
        reported_batch_cost_usd=None,
    )
    assert spent_usd(check) == 0.003


def _write_run(runs_dir: Path, record: RunRecord, *more: RunRecord) -> None:
    write_jsonl(runs_dir / record.run_id / "run.jsonl", [record, *more])


def test_month_spent_counts_the_billed_total_for_s3s_runs_and_the_computed_price_otherwise(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    # An arm C batch run with its judge pass in the same run.jsonl: each record counts.
    judge = _record(
        run_id="c-judge",
        price_variant="standard",
        cost_usd=0.02,
        reported_batch_cost_usd=None,
        started=now,
    )
    _write_run(tmp_path, _record(run_id="c", started=now), judge)
    _write_run(
        tmp_path,
        _record(run_id="b-tools", arm="B", prompt_version=TOOLS_VERSION, started=now),
    )
    _write_run(
        tmp_path,
        _record(run_id="b", arm="B", prompt_version="s1-v6", cost_usd=1.25, started=now),
    )
    _write_run(tmp_path, _record(run_id="c-sync", reported_batch_cost_usd=None, started=now))
    _write_run(tmp_path, _record(run_id="c-september", started=datetime(2026, 9, 30, tzinfo=UTC)))
    expected = BILLED + 0.02 + BILLED + 1.25 + COMPUTED
    assert month_spent(tmp_path, now=now) == pytest.approx(expected)


def test_stage_spent_counts_the_billed_total_for_s3s_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, _record(run_id="c", commit_sha="abcdef1"))
    _write_run(runs, _record(run_id="b", arm="B", prompt_version="s1-v6", commit_sha="abcdef1"))
    _write_run(runs, _record(run_id="elsewhere", commit_sha="9999999"))
    counted, spend = stage_spent(runs, _STAGE)
    assert counted == pytest.approx(BILLED + COMPUTED)
    assert spend == 0.0
