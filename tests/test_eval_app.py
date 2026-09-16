"""The ``ntsb-eval`` command: subcommand wiring and one real, fake-client end-to-end run."""

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from apps.eval.__main__ import answering_run_record, main, month_spent, resolve_latest

from ntsb_probable_cause.model.client import ModelClient, RecordingFakeClient
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, write_jsonl
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


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    finished: datetime | None,
    started: datetime | None = None,
    cost_usd: float = 0.0,
) -> None:
    """A minimal, complete-or-aborted run folder, for ``resolve_latest``/``month_spent`` tests.

    ``started`` defaults to ``finished`` for a complete run; an aborted run (``finished is
    None``) has no such default and must say when it started, since that is the only
    timestamp ``month_spent`` has to place it in a month.
    """
    when = started if started is not None else (finished or datetime(2026, 1, 1, tzinfo=UTC))
    record = RunRecord(
        **_RUN_KWARGS, run_id=run_id, started=when, finished=finished, cost_usd=cost_usd
    )
    write_jsonl(runs_dir / run_id / "run.jsonl", [record])


def _eval_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: dict[str, object]
) -> tuple[str, Path]:
    """Point ``dev-400`` and the processed file at one fixture record.

    Returns:
        The case id and the runs directory.
    """
    case_id = str(raw["ntsbNumber"])
    event_date = str(raw["eventDate"])[:10]

    ids_dir = tmp_path / "eval_ids"
    ids_dir.mkdir(exist_ok=True)
    (ids_dir / "dev_ids.csv").write_text(f"case_id,event_date\n{case_id},{event_date}\n")
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
            "ntsb_number": pa.array([case_id], type=pa.string()),
            "event_date": pa.array([date.fromisoformat(event_date)], type=pa.date32()),
            "split": pa.array(["dev"], type=pa.string()),
            "investigation_class": pa.array(["C"], type=pa.string()),
            "raw_json": pa.array([json.dumps(raw)], type=pa.string()),
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
    (run_folder,) = list(runs_dir.iterdir())
    assert (run_folder / "cases.jsonl").exists()

    capsys.readouterr()  # discard the run command's own output
    main(["report", run_folder.name], client_factory=factory)
    out = capsys.readouterr().out
    assert f"run {run_folder.name} [complete]" in out  # provenance header (fix round 1)
    assert "sample=dev-400 arm=ceiling" in out
    assert "top-1" in out
    assert "| all |" in out
    assert case_id  # the fixture case id was used to build the sample


def _write_judgeable_run(
    runs_dir: Path, run_id: str, case_id: str, *, sample: str = "dev-400"
) -> None:
    """A run folder with one scored, stepped case: the minimum ``judge`` can act on."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    kwargs = {**_RUN_KWARGS, "sample": sample}
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
