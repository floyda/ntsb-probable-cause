"""The ``ntsb-eval`` command: subcommand wiring and one real, fake-client end-to-end run."""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from apps.eval.__main__ import answering_run_record, main, month_spent, resolve_latest
from tests.test_attach import _docket as small_docket

from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.batch import BatchRequest, BatchResult, BatchStatus
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    RecordingFakeClient,
    Turn,
    Usage,
)
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.budget import open_reservations, reserve
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    EvidenceVersion,
    RunRecord,
    StepRecord,
    write_jsonl,
)
from ntsb_probable_cause.scoring.runner import BatchRunner, RunSpec
from ntsb_probable_cause.settings import Settings

GOOD_LABELS = json.dumps(
    {"narrative": "consistent", "cause": "same_cause", "lay": "explains_chosen_codes"}
)

GOOD = json.dumps(
    {
        "evidence_narrative": "n",
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": 0.7,
        "abstain": False,
        "evidence_used": ["phase_of_flight"],
        "occurrence": [{"phase": "552", "event": "230", "probability": 0.7}],
        "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
    }
)
REFINE = json.dumps({"items": [{"index": 0, "item8": "02063040"}]})

_RUN_KWARGS = {
    "sample": "dev-400",
    "arm": "ceiling",
    "exclusions": (),
    "includes": (),
    "prompt_version": "v",
    "model": "m",
    "price_variant": "batch",
    "cap_usd": 0.05,
    "budget_usd": 25.0,
    "commit_sha": "abc",
    "dirty": False,
}


def _write_run(  # noqa: PLR0913
    runs_dir: Path,
    run_id: str,
    *,
    finished: datetime | None,
    started: datetime | None = None,
    cost_usd: float = 0.0,
    arm: str | None = None,
) -> None:
    """A minimal, complete-or-aborted run folder, for ``resolve_latest``/``month_spent`` tests.

    ``started`` defaults to ``finished`` for a complete run; an aborted run (``finished is
    None``) has no such default and must say when it started, since that is the only
    timestamp ``month_spent`` has to place it in a month.
    """
    when = started if started is not None else (finished or datetime(2026, 1, 1, tzinfo=UTC))
    kwargs = dict(_RUN_KWARGS)
    if arm is not None:
        kwargs["arm"] = arm
    record = RunRecord(**kwargs, run_id=run_id, started=when, finished=finished, cost_usd=cost_usd)
    write_jsonl(runs_dir / run_id / "run.jsonl", [record])


def _eval_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *raws: dict[str, object]
) -> tuple[str, Path]:
    """Point ``dev-400`` and the processed file at one or more fixture records, in order.

    Returns:
        The first case id and the runs directory.
    """
    case_ids = [str(raw["ntsbNumber"]) for raw in raws]
    event_dates = [str(raw["eventDate"])[:10] for raw in raws]
    case_id = case_ids[0]

    ids_dir = tmp_path / "eval_ids"
    ids_dir.mkdir(exist_ok=True)
    rows = "".join(f"{cid},{when}\n" for cid, when in zip(case_ids, event_dates, strict=True))
    (ids_dir / "dev_ids.csv").write_text(f"case_id,event_date\n{rows}")
    monkeypatch.setattr(samples, "EVAL_DIR", ids_dir)
    monkeypatch.setitem(samples._FILES, "dev-400", "dev_ids.csv")

    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("ntsb_number", pa.string()),
            ("event_date", pa.date32()),
            ("split", pa.string()),
            ("investigation_class", pa.string()),
            ("raw_json", pa.string()),
        ]
    )
    table = pa.table(
        {
            "ntsb_number": pa.array(case_ids, type=pa.string()),
            "event_date": pa.array(
                [date.fromisoformat(when) for when in event_dates], type=pa.date32()
            ),
            "split": pa.array(["dev"] * len(raws), type=pa.string()),
            "investigation_class": pa.array(["C"] * len(raws), type=pa.string()),
            "raw_json": pa.array([json.dumps(raw) for raw in raws], type=pa.string()),
        },
        schema=schema,
    )
    pq.write_table(table, processed / "cases.parquet")

    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    return case_id, runs_dir


def test_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for word in ("baseline", "run", "report", "judge", "threshold"):
        assert word in out


def test_month_spent_includes_aborted_runs_in_the_current_month(tmp_path: Path) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    _write_run(tmp_path, "r1", finished=now, cost_usd=1.0)
    _write_run(tmp_path, "r2", finished=None, started=now, cost_usd=2.0)  # aborted; still counted
    _write_run(tmp_path, "r3", finished=datetime(2026, 8, 1, tzinfo=UTC), cost_usd=100.0)
    assert month_spent(tmp_path, now=now) == pytest.approx(3.0)


def test_month_spent_sums_every_runrecord_in_a_run_jsonl_not_only_the_first(
    tmp_path: Path,
) -> None:
    """A judged run's ``run.jsonl`` holds two records (the answering run, then the judge pass)."""
    now = datetime(2026, 9, 15, tzinfo=UTC)
    answering = RunRecord(**_RUN_KWARGS, run_id="r1", started=now, finished=now, cost_usd=1.0)
    judged = RunRecord(**_RUN_KWARGS, run_id="r1-judge", started=now, finished=now, cost_usd=0.5)
    write_jsonl(tmp_path / "r1" / "run.jsonl", [answering, judged])
    assert month_spent(tmp_path, now=now) == pytest.approx(1.5)


def test_answering_run_record_is_the_first_row_even_after_a_judge_pass(tmp_path: Path) -> None:
    """A judged run's ``run.jsonl`` holds two rows; report/judge must not choke on the second."""
    now = datetime(2026, 9, 15, tzinfo=UTC)
    answering = RunRecord(**_RUN_KWARGS, run_id="r1", started=now, finished=now, cost_usd=1.0)
    judged = RunRecord(**_RUN_KWARGS, run_id="r1-judge", started=now, finished=now, cost_usd=0.5)
    write_jsonl(tmp_path / "r1" / "run.jsonl", [answering, judged])
    assert answering_run_record(tmp_path / "r1") == answering


def test_month_spent_of_a_missing_runs_dir_is_zero(tmp_path: Path) -> None:
    assert month_spent(tmp_path / "nope", now=datetime(2026, 9, 15, tzinfo=UTC)) == 0.0


def test_resolve_latest_picks_the_newest_completed_matching_folder(tmp_path: Path) -> None:
    _write_run(tmp_path, "20260101T000000-abc-dev-400-ceiling", finished=datetime(2026, 1, 1))
    _write_run(tmp_path, "20260901T000000-abc-dev-400-ceiling", finished=datetime(2026, 9, 1))
    _write_run(tmp_path, "20260501T000000-abc-dev-400-A", finished=datetime(2026, 5, 1))
    assert resolve_latest(tmp_path, "ceiling", "dev-400") == "20260901T000000-abc-dev-400-ceiling"


def test_resolve_latest_skips_an_aborted_run_even_if_newest(tmp_path: Path) -> None:
    """Fix round 1, item 9: an aborted run must never be silently reported as complete."""
    _write_run(tmp_path, "20260101T000000-abc-dev-400-ceiling", finished=datetime(2026, 1, 1))
    _write_run(tmp_path, "20260901T000000-abc-dev-400-ceiling", finished=None)  # aborted, newest
    assert resolve_latest(tmp_path, "ceiling", "dev-400") == "20260101T000000-abc-dev-400-ceiling"


def test_resolve_latest_raises_when_nothing_matches(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no completed run found"):
        resolve_latest(tmp_path, "ceiling", "dev-400")


def test_run_rejects_an_unknown_exclude_role_as_an_argparse_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fix round 1, item 10: a bad ``--exclude`` value is a usage error, not a deep ValueError."""
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--arm", "ceiling", "--sample", "dev-400", "--exclude", "not_a_role"])
    assert excinfo.value.code == 2
    assert "invalid EvidenceRole value" in capsys.readouterr().err


def test_run_over_budget_exits_one_line_not_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fix round 1, item 10: BudgetError is a refusal Andy hits by hand, not a traceback."""
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    fake = RecordingFakeClient([GOOD, REFINE])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(
        ["run", "--arm", "ceiling", "--sample", "dev-400", "--sync", "--budget-usd", "0"],
        client_factory=factory,
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "run:" in err
    assert "Traceback" not in err


def test_run_resume_reaches_the_runner_and_refuses_an_unknown_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--resume`` is wired through to ``Runner.run``, and its refusal is one line (0032)."""
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    fake = RecordingFakeClient([GOOD, REFINE])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(
        ["run", "--arm", "ceiling", "--sample", "dev-400", "--resume", "no-such-run"],
        client_factory=factory,
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "cannot resume: no run folder" in err
    assert "Traceback" not in err
    assert fake.payloads == []


class _ScriptedBatchClient:
    """A batch client for the app-level resume tests: one scripted reply per ``wait``.

    Requests are kept by batch id for the life of the object, so a ``wait`` on an id an
    earlier, dead ``main()`` call submitted returns that batch's results exactly as the
    provider would for a batch it has already completed and billed. A ``None`` reply is a
    waiter that dies with the batch still in flight -- the failure decision 0032 exists for.
    """

    def __init__(
        self, replies: Sequence[str | None], *, on_wait: Callable[[str], None] | None = None
    ) -> None:
        self.replies = list(replies)
        self.requests: dict[str, list[object]] = {}
        self.waits: list[str] = []
        self.on_wait = on_wait

    def submit(self, requests: Sequence[object]) -> str:
        batch_id = f"b{len(self.requests) + 1}"
        self.requests[batch_id] = list(requests)
        return batch_id

    def wait(self, batch_id: str, *, on_status: object = None) -> BatchStatus:
        self.waits.append(batch_id)
        if self.on_wait is not None:
            self.on_wait(batch_id)
        content = self.replies[len(self.waits) - 1]
        if content is None:
            raise ModelError("the waiter died")
        return BatchStatus(
            batch_id=batch_id,
            status="completed",
            results=tuple(
                BatchResult(
                    custom_id=cast(BatchRequest, request).custom_id,
                    reply=ModelReply(
                        content=content,
                        usage=Usage(prompt_tokens=100, completion_tokens=50),
                        model=cast(BatchRequest, request).settings.model_id(),
                        response_id="fake",
                    ),
                    error=None,
                )
                for request in self.requests[batch_id]
            ),
            reported_cost_usd=0.01,
        )


def test_run_resume_refuses_a_different_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--limit`` end to end: resuming with a different one is refused, not quietly obeyed.

    The recorded case-id list is the only thing that can catch this -- the run id encodes
    the sample and the arm, but not how many of the sample's cases the run actually asked
    for -- so it is checked through the command line rather than argued about.
    """
    _, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0], record_fixtures[1])
    batch = _ScriptedBatchClient([GOOD, None])  # dies in the stage-2 wait, leaving a resumable run

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return RecordingFakeClient([]), cast(BatchRunner, batch)

    with pytest.raises(ModelError, match="waiter died"):
        main(["run", "--arm", "ceiling", "--sample", "dev-400"], client_factory=factory)
    (run_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    capsys.readouterr()

    exit_code = main(
        [
            "run",
            "--arm",
            "ceiling",
            "--sample",
            "dev-400",
            "--limit",
            "1",
            "--resume",
            run_folder.name,
        ],
        client_factory=factory,
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "case_ids: the run recorded 2 case ids and this one has 1" in err
    assert "Traceback" not in err
    assert len(batch.requests) == 2  # the refused resume submitted nothing


def test_resumed_run_spend_reaches_month_spent_for_the_next_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole point: work already paid for stops being invisible to the budget guard.

    ``month_spent`` sums ``RunRecord.cost_usd`` -- the per-case dollars priced from each
    reply's own token usage -- over every run started this month, and that is what the next
    run's budget check is handed. So what has to be true after a resume is that the reused
    batch's replies are priced into the finished record, and priced exactly once: the dead
    run's own ``run.jsonl`` row was set aside, or the same tokens would be counted twice.
    """
    _, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    batch = _ScriptedBatchClient([None, GOOD, REFINE])  # dies in the stage-1 wait, then resumes

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return RecordingFakeClient([]), cast(BatchRunner, batch)

    with pytest.raises(ModelError, match="waiter died"):
        main(
            ["run", "--arm", "ceiling", "--sample", "dev-400", "--model", "openai/gpt-5.6-luna"],
            client_factory=factory,
        )
    (run_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert month_spent(runs_dir, now=datetime.now(UTC)) == pytest.approx(0.0)  # nothing read yet

    exit_code = main(
        [
            "run",
            "--arm",
            "ceiling",
            "--sample",
            "dev-400",
            "--model",
            "openai/gpt-5.6-luna",
            "--resume",
            run_folder.name,
        ],
        client_factory=factory,
    )
    assert exit_code == 0
    assert batch.waits == ["b1", "b1", "b2"]  # the paid batch, waited on again, then stage 2
    assert len(batch.requests) == 2  # stage 1 was not submitted a second time

    record = answering_run_record(run_folder)
    assert record.finished is not None
    assert record.batch_ids == ("b1", "b2")
    assert record.reported_batch_cost_usd == pytest.approx(0.02)  # the reused batch's own cost
    # Two replies, the reused stage-1 one and stage 2, at the Luna batch price (sources.py).
    expected = 2 * (100 * 0.10 + 50 * 0.60) / 1e6
    assert record.cost_usd == pytest.approx(expected)
    assert month_spent(runs_dir, now=datetime.now(UTC)) == pytest.approx(expected)
    capsys.readouterr()


def test_a_resume_in_flight_keeps_the_dead_runs_spend_visible_to_month_spent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The invariant a resume must not break for the 30-100 minutes it is running.

    A run that died in its stage-2 wait has already been billed for stage 1, and its
    ``run.jsonl`` is the only record of it. The resume replaces that record -- but if it
    did so on the way in, and was then killed itself (the very failure 0032 exists for),
    the spend would be invisible to the next run's budget guard. So the check is made
    *while the resume is in flight*: the dead run's record is still countable then, and
    only stops being so in the moment the replacement is written.
    """
    _, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    seen_mid_flight: list[float] = []

    def watch(_batch_id: str) -> None:
        seen_mid_flight.append(month_spent(runs_dir, now=datetime.now(UTC)))

    batch = _ScriptedBatchClient([GOOD, None, GOOD, REFINE], on_wait=watch)

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return RecordingFakeClient([]), cast(BatchRunner, batch)

    with pytest.raises(ModelError, match="waiter died"):
        main(
            ["run", "--arm", "ceiling", "--sample", "dev-400", "--model", "openai/gpt-5.6-luna"],
            client_factory=factory,
        )
    (run_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    one_reply = (100 * 0.10 + 50 * 0.60) / 1e6  # the stage-1 reply the dead run was billed
    billed = month_spent(runs_dir, now=datetime.now(UTC))
    assert billed == pytest.approx(one_reply)

    seen_mid_flight.clear()
    assert (
        main(
            [
                "run",
                "--arm",
                "ceiling",
                "--sample",
                "dev-400",
                "--model",
                "openai/gpt-5.6-luna",
                "--resume",
                run_folder.name,
            ],
            client_factory=factory,
        )
        == 0
    )
    # Every wait the resume made: the dead run's spend was countable throughout.
    assert len(seen_mid_flight) == 2
    assert all(spend == pytest.approx(billed) for spend in seen_mid_flight)
    # And afterwards it is counted exactly once, as the resumed run's own two replies.
    assert month_spent(runs_dir, now=datetime.now(UTC)) == pytest.approx(2 * one_reply)
    capsys.readouterr()


def test_a_resume_that_aborts_leaves_the_dead_runs_spend_in_month_spent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The other half of the handover: a resume that fails must not erase what was paid.

    The dead run was billed for its stage-1 batch. Its ``run.jsonl`` is renamed aside the
    moment the resume writes its own — and the renamed file is outside ``month_spent``'s
    glob. So if the resume aborts before re-reading those replies, its own cases cost
    nothing, and without a floor under the record it writes the month would forget real
    spending. Measured the way it is spent: through ``month_spent``, before and after.
    """
    _, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    # stage 1 answered and billed, stage 2 lost its waiter; then the resume dies on the
    # reused stage-1 batch, before anything it could be billed for.
    batch = _ScriptedBatchClient([GOOD, None, None])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return RecordingFakeClient([]), cast(BatchRunner, batch)

    with pytest.raises(ModelError, match="waiter died"):
        main(["run", "--arm", "ceiling", "--sample", "dev-400"], client_factory=factory)
    (run_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    billed = month_spent(runs_dir, now=datetime.now(UTC))
    assert billed > 0.0  # or the rest of this test proves nothing

    with pytest.raises(ModelError, match="waiter died"):
        main(
            ["run", "--arm", "ceiling", "--sample", "dev-400", "--resume", run_folder.name],
            client_factory=factory,
        )
    assert month_spent(runs_dir, now=datetime.now(UTC)) == pytest.approx(billed)
    capsys.readouterr()


def test_run_flags_reach_runspec_and_month_spent_reaches_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """The highest-stakes wiring in the command: nothing else pins that flags reach RunSpec."""
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    monkeypatch.setattr("apps.eval.__main__.month_spent", lambda *_a, **_k: 7.5)
    captured: dict[str, object] = {}

    class SpyRunner:
        def __init__(self, _client: object, **kwargs: object) -> None:
            captured["month_spent_usd"] = kwargs["month_spent_usd"]

        def run(
            self, spec: RunSpec, raws: Sequence[object], *, resume: str | None = None
        ) -> RunRecord:
            captured["spec"] = spec
            captured["n_raws"] = len(raws)
            captured["resume"] = resume
            base = {
                k: v
                for k, v in _RUN_KWARGS.items()
                if k not in {"sample", "arm", "cap_usd", "budget_usd"}
            }
            return RunRecord(
                **base,
                run_id="spied",
                sample=spec.sample,
                arm=spec.arm,
                cap_usd=spec.cap_usd,
                budget_usd=spec.budget_usd,
                started=datetime.now(UTC),
                finished=datetime.now(UTC),
                cases=len(raws),
                cost_usd=0.0,
            )

    monkeypatch.setattr("apps.eval.__main__.Runner", SpyRunner)
    fake = RecordingFakeClient([GOOD, REFINE])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(
        [
            "run",
            "--arm",
            "A",
            "--sample",
            "dev-400",
            "--sync",
            "--price-variant",
            "standard",
            "--cap-usd",
            "0.02",
            "--budget-usd",
            "10",
            "--expected-cost-per-case-usd",
            "0.001",
            "--limit",
            "1",
        ],
        client_factory=factory,
    )
    assert exit_code == 0
    spec = captured["spec"]
    assert isinstance(spec, RunSpec)
    assert spec.arm == "A"
    assert spec.sample == "dev-400"
    assert spec.cap_usd == pytest.approx(0.02)
    assert spec.budget_usd == pytest.approx(10.0)
    assert spec.expected_cost_per_case_usd == pytest.approx(0.001)
    assert captured["n_raws"] == 1  # --limit 1
    assert captured["month_spent_usd"] == pytest.approx(7.5)
    assert captured["resume"] is None  # no --resume: a new run, today's behaviour


def test_run_sync_then_report_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``run --sync`` with a fake client, then ``report`` prints an occurrence top-1 row."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])

    fake = RecordingFakeClient([GOOD, REFINE])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(
        ["run", "--arm", "ceiling", "--sample", "dev-400", "--sync", "--price-variant", "standard"],
        client_factory=factory,
    )
    assert exit_code == 0
    (run_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert (run_folder / "cases.jsonl").exists()

    capsys.readouterr()  # discard the run command's own output
    main(["report", run_folder.name], client_factory=factory)
    out = capsys.readouterr().out
    assert f"run {run_folder.name} [complete]" in out  # provenance header (fix round 1)
    assert "sample=dev-400 arm=ceiling" in out
    assert "top-1" in out
    assert "| all |" in out
    assert case_id  # the fixture case id was used to build the sample


def test_run_arm_b_then_report_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fix round 1, Finding 3: the coverage gate does not measure ``apps/``, so nothing
    proved ``_cmd_run``'s real ``--arm B`` wiring (``DocketClient`` construction, the
    ``contextlib.nullcontext()``/``with`` pairing, ``CachedDocketReader(docket_client) if
    docket_client is not None else None``) ever produces a working run rather than raising
    mid-run, after the budget reservation is already taken. ``CachedDocketReader`` is
    stubbed (no socket needed) so the real ``DocketClient`` is still constructed, opened and
    closed exactly as production does; only the docket *read* is faked. Also closes the
    ``report`` command's ``if run_record.arm == "B":`` branch (the ``cap:`` line)."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})

    class StubDocketReader:
        """Stands in for ``CachedDocketReader``: same one-argument constructor, no HTTP."""

        def __init__(self, client: object) -> None:
            self.client = client

        def read(self, mkey: int) -> Docket:
            return docket

    monkeypatch.setattr("apps.eval.__main__.CachedDocketReader", StubDocketReader)
    fake = RecordingFakeClient([GOOD, REFINE])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(
        ["run", "--arm", "B", "--sample", "dev-400", "--sync", "--price-variant", "standard"],
        client_factory=factory,
    )
    assert exit_code == 0
    (run_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    record = answering_run_record(run_folder)
    assert record.arm == "B"
    assert record.finished is not None
    assert "crankshaft" in fake.payloads[0].text  # the stubbed docket really was read

    capsys.readouterr()
    main(["report", run_folder.name], client_factory=factory)
    out = capsys.readouterr().out
    assert "sample=dev-400 arm=B" in out
    assert "cap:" in out  # report._cmd_report's arm-B-only branch
    assert case_id  # the fixture case id was used to build the sample


def _write_judgeable_run(
    runs_dir: Path,
    run_id: str,
    case_id: str,
    *,
    sample: str = "dev-400",
    arm: str = "ceiling",
) -> None:
    """A run folder with one scored, stepped case: the minimum ``judge`` can act on."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    kwargs = {**_RUN_KWARGS, "sample": sample, "arm": arm}
    write_jsonl(
        runs_dir / run_id / "run.jsonl",
        [RunRecord(**kwargs, run_id=run_id, started=now, finished=now, cost_usd=1.0)],
    )
    hypothesis = parse_hypothesis(GOOD, load_tables())
    step = StepRecord(
        case_id=case_id,
        step=0,
        arm="ceiling",
        condition="full",
        day=None,
        tool="none",
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
    scores = CaseScores(
        occurrence_top1=True,
        occurrence_top3=True,
        event_match=True,
        pair_unseen=False,
        finding_precision_10=None,
        finding_recall_10=None,
        finding_precision_8=None,
        finding_recall_8=None,
        finding_precision_6=None,
        finding_recall_6=None,
        finding_precision_all_10=None,
        finding_recall_all_10=None,
        abstained=False,
        confidence=0.7,
    )
    case = CaseResult(
        case_id=case_id,
        split="heldout" if sample.startswith("heldout") else "dev",
        fatal=False,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=("552230",),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(step,),
        scores=scores,
        cost_usd=0.0,
        failure=None,
    )
    write_jsonl(runs_dir / run_id / "cases.jsonl", [case])


def test_judge_on_a_heldout_run_appends_a_ledger_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 2, item 3: spec §13 item 8 -- every held-out run, judge passes included."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    ledger_path = tmp_path / "heldout-ledger.md"
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(
        "ntsb_probable_cause.scoring.ledger.commit_state", lambda *_a, **_k: ("abc1234", False)
    )
    run_id = "20260101T000000-abc1234-heldout-40-ceiling"
    _write_judgeable_run(runs_dir, run_id, case_id, sample="heldout-40")

    fake = RecordingFakeClient([GOOD_LABELS])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(["judge", run_id, "--validated"], client_factory=factory)
    assert exit_code == 0
    ledger_text = ledger_path.read_text()
    assert "| heldout-40 |" in ledger_text
    assert "judge.jsonl" in ledger_text  # the row names the judge pass's own results file
    assert "anthropic/claude-haiku-4.5" in ledger_text  # the judge model, not the run's model


def test_judge_on_a_heldout_run_from_a_dirty_tree_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 2, item 3: a held-out judge pass is refused the same way a held-out run is."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    ledger_path = tmp_path / "heldout-ledger.md"
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(
        "ntsb_probable_cause.scoring.ledger.commit_state", lambda *_a, **_k: ("abc1234", True)
    )
    run_id = "20260101T000000-abc1234-heldout-40-ceiling"
    _write_judgeable_run(runs_dir, run_id, case_id, sample="heldout-40")

    fake = RecordingFakeClient([GOOD_LABELS])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(["judge", run_id, "--validated"], client_factory=factory)
    assert exit_code == 1
    assert fake.payloads == []  # refused before any call
    assert not ledger_path.exists()
    assert not (runs_dir / run_id / "judge.jsonl").exists()


def test_judge_command_never_deletes_a_prior_pass_labels_on_a_refused_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """The app-level judge test the reviewer noted: it would have caught the unlink ordering.

    Fix round 2, item 1: a re-judge that gets refused (or fails before its first label) must
    not delete the previous pass's already-paid ``judge.jsonl`` rows.
    """
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    run_id = "20260101T000000-abc1234-dev-400-ceiling"
    _write_judgeable_run(runs_dir, run_id, case_id, sample="dev-400")

    fake = RecordingFakeClient([GOOD_LABELS])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(["judge", run_id], client_factory=factory)
    assert exit_code == 0
    judge_path = runs_dir / run_id / "judge.jsonl"
    original_content = judge_path.read_text()
    assert case_id in original_content

    # Force the second pass to be refused before it ever reaches a call.
    monkeypatch.setattr("apps.eval.__main__.month_spent", lambda *_a, **_k: 1_000_000.0)
    exit_code = main(["judge", run_id], client_factory=factory)
    assert exit_code == 1
    assert judge_path.read_text() == original_content  # untouched by the refused retry


def test_judge_that_dies_mid_pass_leaves_the_previous_pass_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """Spec §3.5: rows go to judge.jsonl.partial; the old file is replaced only when complete."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0], record_fixtures[1])
    run_id = "20260101T000000-abc1234-dev-400-ceiling"
    _write_judgeable_run(runs_dir, run_id, case_id, sample="dev-400")
    second_id = str(record_fixtures[1]["ntsbNumber"])
    _write_judgeable_run(runs_dir, run_id, second_id, sample="dev-400")

    good = RecordingFakeClient([GOOD_LABELS, GOOD_LABELS])

    def good_factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return good, None

    assert main(["judge", run_id], client_factory=good_factory) == 0
    judge_path = runs_dir / run_id / "judge.jsonl"
    prior = judge_path.read_text()

    class DiesAfterOne:
        """One good label, then the provider falls over."""

        def __init__(self) -> None:
            self._inner = RecordingFakeClient([GOOD_LABELS])
            self.calls = 0

        def complete(
            self,
            payload: Payload,
            settings: ModelSettings,
            *,
            system: str = "",
            history: Sequence[Turn] = (),
        ) -> ModelReply:
            self.calls += 1
            if self.calls > 1:
                raise ModelError("boom")
            return self._inner.complete(payload, settings, system=system, history=history)

    dying = DiesAfterOne()

    def dying_factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return dying, None

    with pytest.raises(ModelError):
        main(["judge", run_id], client_factory=dying_factory)
    assert judge_path.read_text() == prior
    assert (runs_dir / run_id / "judge.jsonl.partial").read_text().count("\n") == 1


def _write_min_report_run(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    runs_dir: Path,
    run_id: str,
    case_id: str,
    *,
    model: str,
    commit_sha: str,
    reasoning_effort: str | None = None,
    evidence_version: EvidenceVersion = "v1",
) -> None:
    """A run folder ``report`` can act on: one failed, unscored case (fix round 1, Finding).

    Minimal on purpose: ``report``'s ``--against`` wiring is what these tests exercise, not
    scoring, so ``scores=None`` and ``failure="cap"`` are enough to drive ``failure_summary``
    and ``compare`` without needing a full ``CaseScores``/``StepRecord`` fixture.
    """
    now = datetime(2026, 1, 1, tzinfo=UTC)
    kwargs = {**_RUN_KWARGS, "model": model, "commit_sha": commit_sha}
    write_jsonl(
        runs_dir / run_id / "run.jsonl",
        [
            RunRecord(
                **kwargs,
                run_id=run_id,
                started=now,
                finished=now,
                cost_usd=1.0,
                reasoning_effort=reasoning_effort,
                evidence_version=evidence_version,
            )
        ],
    )
    case = CaseResult(
        case_id=case_id,
        split="dev",
        fatal=False,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=("552230",),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(),
        scores=None,
        cost_usd=0.0,
        failure="cap",
    )
    write_jsonl(runs_dir / run_id / "cases.jsonl", [case])


def test_report_against_labels_a_cross_model_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1: the ``report --against`` wiring is exercised end-to-end over two real
    run folders, proving both the argument order (this run first, the other run second, so
    a swap would print the wrong side first) and that a cross-model comparison is labelled
    (decision 0031 item 2) rather than printed as a plain bar."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))

    _write_min_report_run(
        runs_dir,
        "this-run",
        "CASE1",
        model="openai/gpt-6-luna",
        commit_sha="sha-this",
        reasoning_effort="medium",
    )
    _write_min_report_run(
        runs_dir, "other-run", "CASE2", model="openai/gpt-5.6-luna", commit_sha="sha-other"
    )

    exit_code = main(["report", "this-run", "--against", "other-run"])
    assert exit_code is None or exit_code == 0
    out = capsys.readouterr().out

    assert "failures by reason:" in out
    heading = (
        "model comparison (decision 0031 item 2): openai/gpt-6-luna at sha-this, "
        "reasoning medium, against openai/gpt-5.6-luna at sha-other, "
        "reasoning provider default -- run other-run:"
    )
    assert heading in out


def test_report_against_same_model_uses_the_plain_heading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1: two runs of the same model and reasoning level still get the plain,
    unlabelled ``against <run_id>:`` heading -- the existing behaviour every ``report
    --against`` test before S2.4 relied on."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))

    _write_min_report_run(runs_dir, "this-run", "CASE1", model="m", commit_sha="abc")
    _write_min_report_run(runs_dir, "other-run", "CASE2", model="m", commit_sha="abc")

    exit_code = main(["report", "this-run", "--against", "other-run"])
    assert exit_code is None or exit_code == 0
    out = capsys.readouterr().out

    assert "failures by reason:" in out
    assert "against other-run:" in out
    assert "model comparison" not in out


def test_report_against_a_different_version_is_refused_without_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision 0076: a comparison across evidence versions is refused unless labelled."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))

    _write_min_report_run(
        runs_dir, "this-run", "CASE1", model="m", commit_sha="abc", evidence_version="v2"
    )
    _write_min_report_run(
        runs_dir, "other-run", "CASE2", model="m", commit_sha="abc", evidence_version="v1"
    )

    exit_code = main(["report", "this-run", "--against", "other-run"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "decision 0076" in err

    exit_code = main(["report", "this-run", "--against", "other-run", "--versions-compared"])
    assert exit_code is None or exit_code == 0
    out = capsys.readouterr().out
    assert "evidence-version comparison (decision 0076): v2 against v1" in out


def _scored_case(case_id: str, *, marks: tuple[CaseMark, ...] = ()) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        split="dev",
        fatal=False,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=("552230",),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(),
        scores=CaseScores(
            occurrence_top1=True,
            occurrence_top3=True,
            event_match=True,
            pair_unseen=False,
            finding_precision_10=1.0,
            finding_recall_10=1.0,
            finding_precision_8=1.0,
            finding_recall_8=1.0,
            finding_precision_6=1.0,
            finding_recall_6=1.0,
            finding_precision_all_10=1.0,
            finding_recall_all_10=1.0,
            abstained=False,
            confidence=0.5,
        ),
        cost_usd=0.001,
        failure=None,
        marks=marks,
    )


def test_report_prints_unmarked_cases_and_each_marked_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S2.6 spec §4.4: a run with any marked case gets the unmarked table and marks_summary."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))

    now = datetime(2026, 1, 1, tzinfo=UTC)
    write_jsonl(
        runs_dir / "this-run" / "run.jsonl",
        [RunRecord(**_RUN_KWARGS, run_id="this-run", started=now, finished=now, cost_usd=1.0)],
    )
    clean = _scored_case("CASE1")
    marked = _scored_case("CASE2", marks=(CaseMark(kind="analysis_sentence", count=3),))
    write_jsonl(runs_dir / "this-run" / "cases.jsonl", [clean, marked])

    exit_code = main(["report", "this-run"])
    assert exit_code is None or exit_code == 0
    out = capsys.readouterr().out

    assert "unmarked cases only (S2.6 spec §4.4):" in out
    assert "marks (S2.6 spec §4.4; never in the agent's text):" in out
    assert "analysis_sentence: 1 cases (3 counted); top-1" in out


def test_release_clears_a_dead_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_dir = tmp_path / "runs"
    reserve(runs_dir, "dead-run", 5.0, now=datetime(2026, 9, 18, tzinfo=UTC))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    assert main(["release", "dead-run"]) == 0
    assert "released dead-run" in capsys.readouterr().out
    assert open_reservations(runs_dir) == {}
    assert main(["release", "dead-run"]) == 1
