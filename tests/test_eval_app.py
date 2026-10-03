"""The ``ntsb-eval`` command: subcommand wiring and one real, fake-client end-to-end run."""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from apps.eval.__main__ import (
    MAX_FAILED_SHARE,
    _ablated,
    _maybe_mark_done,
    _recorded_spec,
    answering_run_record,
    main,
    month_spent,
    resolve_latest,
)
from tests.pdf_builder import PageSpec, build_pdf
from tests.test_agent_loop import _choose, _hyp
from tests.test_attach import _docket as small_docket
from tests.test_occurrence_misses import _case
from tests.test_runner import FakeBatchClient

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent import texts as agent_texts
from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.texts import prompt_version
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.docket.render import RESOLUTION
from ntsb_probable_cause.docket.transcribe import (
    PAGE_RULE,
    TRANSCRIBE,
    TRANSCRIBER,
    PageJob,
    ReadingLookup,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
)
from ntsb_probable_cause.errors import ConfigurationError, DocketError, ModelError
from ntsb_probable_cause.model.batch import BatchRequest, BatchResult, BatchStatus
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    RecordingFakeClient,
    Turn,
    Usage,
    tool_reply,
)
from ntsb_probable_cause.model.typesafe import TypeSafeClient
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.budget import open_reservations, reserve
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, load_stats
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.preparation import PreparationStoppedError
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    EvidenceVersion,
    RunRecord,
    StepRecord,
    read_jsonl,
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


def test_recorded_spec_refuses_unreadable_json(tmp_path: Path) -> None:
    """S3.2 Task 4: an unreadable spec.json is refused, not read as `{}`.

    A run folder with unreadable JSON in spec.json raises ConfigurationError.
    A folder with no spec.json returns {}. A spec.json holding a JSON list raises.
    """
    # Unreadable JSON: raises ConfigurationError
    folder_bad_json = tmp_path / "bad-json"
    folder_bad_json.mkdir()
    (folder_bad_json / "spec.json").write_text("{not json")
    with pytest.raises(ConfigurationError, match="not readable JSON"):
        _recorded_spec(folder_bad_json)

    # No spec.json: returns {}
    folder_no_spec = tmp_path / "no-spec"
    folder_no_spec.mkdir()
    assert _recorded_spec(folder_no_spec) == {}

    # JSON list, not object: raises ConfigurationError
    folder_list = tmp_path / "list"
    folder_list.mkdir()
    (folder_list / "spec.json").write_text('["item1", "item2"]')
    with pytest.raises(ConfigurationError, match="not a JSON object"):
        _recorded_spec(folder_list)


def test_ablated_raises_on_unreadable_spec_json(tmp_path: Path) -> None:
    """S3.2 Task 4: _ablated raises ConfigurationError when spec.json is unreadable."""
    folder = tmp_path / "unreadable-spec"
    folder.mkdir()
    (folder / "spec.json").write_text("{not json")
    with pytest.raises(ConfigurationError, match="not readable JSON"):
        _ablated(folder)


def test_report_on_unreadable_spec_json_through_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S3.2 Task 4: report through main on a run with unreadable spec.json is refused.

    The ConfigurationError raised by _recorded_spec is caught and printed to
    stderr, exiting with code 1. The error message names spec.json.
    """
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))

    # Create a run with unreadable spec.json
    run_id = "20261001T000000-abc1234-dev-400-C"
    folder = runs_dir / run_id
    now = datetime(2026, 1, 1, tzinfo=UTC)
    kwargs = dict(_RUN_KWARGS) | {"arm": "C"}
    write_jsonl(
        folder / "run.jsonl",
        [
            RunRecord(
                **kwargs,
                run_id=run_id,
                started=now,
                finished=now,
                cost_usd=1.0,
            )
        ],
    )
    write_jsonl(folder / "cases.jsonl", [_scored_case("c1")])
    (folder / "spec.json").write_text("{not json")  # unreadable JSON

    exit_code = main(["report", run_id])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "spec.json" in err
    assert "not readable JSON" in err


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


def test_run_refuses_guidance_whose_registration_is_not_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
) -> None:
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    monkeypatch.setattr(
        gitinfo, "is_committed", lambda path, repo=Path(): path.name != "s27-round-2.md"
    )
    assert (
        main(
            ["run", "--arm", "ceiling", "--sample", "dev-400", "--guidance", "r2-loc-stall"],
            client_factory=lambda s: (RecordingFakeClient([]), None),
        )
        == 1
    )
    assert "registration" in capsys.readouterr().err


def test_resolve_latest_skips_a_guided_run(tmp_path: Path) -> None:
    """A guided run (S2.7) is not "the plain arm" -- --latest must not silently pick it up."""
    runs = tmp_path / "runs"
    when = datetime(2026, 9, 26, tzinfo=UTC)
    _write_run(runs, "20260926T000000-abc1234-dev-400-B", finished=when, arm="B")
    kwargs = dict(_RUN_KWARGS) | {"arm": "B"}
    guided = RunRecord(
        **kwargs,
        run_id="20260927T000000-abc1234-dev-400-B",
        started=when,
        finished=when,
        guidance=("r2-loc-stall",),
        guidance_sha256="a" * 64,
    )
    write_jsonl(runs / guided.run_id / "run.jsonl", [guided])
    assert resolve_latest(runs, "B", "dev-400") == "20260926T000000-abc1234-dev-400-B"


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
        """Stands in for ``CachedDocketReader``: same constructor, no HTTP."""

        def __init__(self, client: object, *, readings: object = None) -> None:
            self.client = client
            self.version = "v1" if readings is None else "v2"

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


def _write_judgeable_run(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    runs_dir: Path,
    run_id: str,
    case_id: str,
    *,
    sample: str = "dev-400",
    arm: str = "ceiling",
    evidence_version: EvidenceVersion = "v1",
    guidance: tuple[str, ...] = (),
    guidance_sha256: str | None = None,
) -> None:
    """A run folder with one scored, stepped case: the minimum ``judge`` can act on."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    kwargs = {**_RUN_KWARGS, "sample": sample, "arm": arm}
    write_jsonl(
        runs_dir / run_id / "run.jsonl",
        [
            RunRecord(
                **kwargs,
                run_id=run_id,
                started=now,
                finished=now,
                cost_usd=1.0,
                evidence_version=evidence_version,
                guidance=guidance,
                guidance_sha256=guidance_sha256,
            )
        ],
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


def test_judge_records_the_judged_run_s_own_evidence_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """S2.6 final review, I4: the judge pass's run record, and so its append-only held-out
    ledger row, carry the judged run's evidence version, not the default v1."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    ledger_path = tmp_path / "heldout-ledger.md"
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(
        "ntsb_probable_cause.scoring.ledger.commit_state", lambda *_a, **_k: ("abc1234", False)
    )
    run_id = "20260101T000000-abc1234-heldout-40-B"
    _write_judgeable_run(
        runs_dir, run_id, case_id, sample="heldout-40", arm="B", evidence_version="v2"
    )

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return RecordingFakeClient([GOOD_LABELS]), None

    assert main(["judge", run_id, "--validated"], client_factory=factory) == 0
    answering, judge = read_jsonl(runs_dir / run_id / "run.jsonl", RunRecord)
    assert answering.evidence_version == "v2"
    assert judge.run_id == f"{run_id}-judge"
    assert judge.evidence_version == "v2"
    assert "| heldout-40 | B | v2 |" in ledger_path.read_text()


def test_judge_records_the_judged_run_s_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 1, item 2: the judge pass's cost row must not lose which guidance ran."""
    case_id, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    monkeypatch.setattr(
        "ntsb_probable_cause.scoring.ledger.commit_state", lambda *_a, **_k: ("abc1234", False)
    )
    run_id = "20260101T000000-abc1234-dev-400-B"
    _write_judgeable_run(
        runs_dir,
        run_id,
        case_id,
        arm="B",
        guidance=("r2-loc-stall", "r3-phase"),
        guidance_sha256="a" * 64,
    )

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return RecordingFakeClient([GOOD_LABELS]), None

    assert main(["judge", run_id], client_factory=factory) == 0
    answering, judge = read_jsonl(runs_dir / run_id / "run.jsonl", RunRecord)
    assert answering.guidance == ("r2-loc-stall", "r3-phase")
    assert judge.guidance == answering.guidance
    assert judge.guidance_sha256 == answering.guidance_sha256 == "a" * 64


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


# --- Task 14: `transcribe`, and `run --evidence-version v2` ---

_SCAN = build_pdf([PageSpec(images=("/CCITTFaxDecode",)), PageSpec(images=("/DCTDecode",))])


def _entry(index: int, *, pages: int, photos: int = 0, extension: str = "pdf") -> ListingEntry:
    return ListingEntry(
        index=index,
        title=f"Document {index}",
        pages=pages,
        photos=photos,
        doc_type="",
        extension=extension,
        href=f"doc{index}",
    )


class _StubDocuments:
    """Stands in for ``CachedDocuments``: a scan, a photo-only scan, a non-PDF; no HTTP."""

    def __init__(self, _client: object) -> None:
        self.entries: tuple[ListingEntry, ...] = (
            _entry(1, pages=2),
            _entry(2, pages=2, photos=2),  # photo-only: v2 reads it too (decision W2)
            _entry(3, pages=0, extension="csv"),
            _entry(4, pages=1),  # fails to fetch
        )

    def listing(self, mkey: int) -> Listing:
        return Listing(mkey=mkey, declared_items=len(self.entries), entries=self.entries)

    def document(self, mkey: int, index: int) -> bytes:
        if index == 4:
            raise DocketError("fetch failed")
        return _SCAN

    def loader(self, mkey: int, index: int) -> Callable[[], bytes]:
        return lambda: self.document(mkey, index)


def _transcribe_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: dict[str, object]
) -> Path:
    """``dev-400`` pointed at ``raw``, the stubbed documents; returns the transcription dir."""
    _eval_env(tmp_path, monkeypatch, raw)
    monkeypatch.setattr("apps.eval.__main__.CachedDocuments", _StubDocuments)
    return tmp_path / "data" / "transcriptions"


def test_run_v2_without_a_finished_transcription_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no model client is built for a refused run")

    exit_code = main(
        ["run", "--arm", "B", "--sample", "dev-400", "--evidence-version", "v2", "--sync"],
        client_factory=factory,
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "dev-400 is not fully transcribed" in err
    assert "ntsb-eval transcribe --sample dev-400" in err


def test_run_v2_with_a_finished_transcription_reads_with_a_v2_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
) -> None:
    _, runs_dir = _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    ReadingLookup(TranscriptionCache(tmp_path / "data" / "transcriptions")).mark_done(
        "dev-400", {"pages": 0}
    )
    docket = small_docket({1: "[page 1 of 3, transcribed from an image]\nThe crankshaft.\n"})
    seen: list[object] = []

    class StubDocketReader:
        def __init__(self, client: object, *, readings: object = None) -> None:
            seen.append(readings)
            self.version = "v1" if readings is None else "v2"

        def read(self, mkey: int) -> Docket:
            return docket

    monkeypatch.setattr("apps.eval.__main__.CachedDocketReader", StubDocketReader)
    fake = RecordingFakeClient([GOOD, REFINE])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(
        [
            "run",
            "--arm",
            "B",
            "--sample",
            "dev-400",
            "--evidence-version",
            "v2",
            "--sync",
            "--price-variant",
            "standard",
        ],
        client_factory=factory,
    )
    assert exit_code == 0
    assert isinstance(seen[0], ReadingLookup)
    (run_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    record = answering_run_record(run_folder)
    assert record.evidence_version == "v2"
    # S2.7 Task 16 (spec §7.5): the defaults name the transcriber and rule in force.
    assert (record.transcriber, record.page_rule) == (TRANSCRIBER, PAGE_RULE)


def test_run_v2_under_another_page_rule_needs_that_rules_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """S2.7 Task 16: the marker checked is the one for the run's own transcriber and rule."""
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    ReadingLookup(TranscriptionCache(tmp_path / "data" / "transcriptions")).mark_done(
        "dev-400", {"pages": 0}
    )

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no model client is built for a refused run")

    exit_code = main(
        [
            "run",
            "--arm",
            "B",
            "--sample",
            "dev-400",
            "--evidence-version",
            "v2",
            "--page-rule",
            "image-only",
            "--sync",
            "--price-variant",
            "standard",
        ],
        client_factory=factory,
    )
    assert exit_code == 1
    assert "not fully transcribed with transcriber" in capsys.readouterr().err


def test_transcribe_dry_run_counts_and_prices_and_calls_no_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcriptions = _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])

    def no_preparation(**_kwargs: object) -> list[Transcription]:
        raise AssertionError("a dry run pays for nothing")

    monkeypatch.setattr("apps.eval.__main__.run_preparation", no_preparation)
    exit_code = main(
        [
            "transcribe",
            "--sample",
            "dev-400",
            "--expected-cost-per-page-usd",
            "0.01",
            "--dry-run",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    # Two scans of two image pages each (the photo-only one included, decision W2).
    assert (
        f"dev-400: 4 pages to read with {TRANSCRIBER} at 150 dpi, rule all, 4 not yet read" in out
    )
    assert "projected $0.04" in out
    # entry 4 fails to fetch (_StubDocuments): counted rather than silently dropped (M2).
    assert "1 document(s) could not be listed, fetched or parsed" in out
    assert not ReadingLookup(TranscriptionCache(transcriptions)).is_done("dev-400")


def test_transcribe_reads_the_pages_and_marks_the_sample_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """0 of 4 pages fail (well within the 2% threshold): the marker is written (M1)."""
    transcriptions = _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])
    calls: list[Sequence[PageJob]] = []

    def fake_preparation(*, jobs: Sequence[PageJob], **kwargs: object) -> list[Transcription]:
        calls.append(jobs)
        assert kwargs["kind"] == "transcription"
        assert kwargs["expected_cost_per_page_usd"] == pytest.approx(0.01)
        cache = TranscriptionCache(transcriptions)
        done = []
        for job in jobs:
            if cache.get(job.key) is not None:
                continue  # the same page twice (a shared document) is paid for once
            record = Transcription(
                key=job.key,
                status="transcribed",
                text="words",
                mixed=job.mixed,
                cost_usd=0.01,
                created=datetime(2026, 10, 1, tzinfo=UTC),
            )
            cache.put(record, instruction=TRANSCRIBE)
            done.append(record)
        return done

    monkeypatch.setattr("apps.eval.__main__.run_preparation", fake_preparation)
    argv = ["transcribe", "--sample", "dev-400", "--expected-cost-per-page-usd", "0.01"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    # The two documents are byte-identical (_StubDocuments/_SCAN), so their pages share a
    # digest and are paid for once (existing dedup behaviour, unaffected by M1/M2).
    assert "read 2 pages now ($0.02); 0 of 4 failed in all" in out
    assert "every page has a reading; v2 runs may start" in out
    lookup = ReadingLookup(TranscriptionCache(transcriptions))
    assert lookup.is_done("dev-400")
    summary = json.loads(lookup.done_file("dev-400").read_text())
    assert summary["failed"] == 0
    # entry 4 fails to fetch (_StubDocuments): counted in the marker's summary too (M2).
    assert summary["skipped_documents"] == 1
    # Every key names the chosen transcriber, the fixed resolution and the page's own mixed
    # status's instruction (fix round 3, R4).
    assert {(j.key.model, j.key.dpi, j.key.instruction) for j in calls[0]} == {
        (TRANSCRIBER, 150, "t1")
    }

    # Everything cached: a second pass needs no job at all.
    assert main(argv) == 0
    assert len(calls) == 1


def test_transcribe_retry_failed_rereads_failed_pages_even_without_a_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """1 of 4 pages fails (25%, over the threshold): no marker, exit 1, --retry-failed re-reads."""
    transcriptions = _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])
    calls: list[Sequence[PageJob]] = []

    def fake_preparation(*, jobs: Sequence[PageJob], **kwargs: object) -> list[Transcription]:
        calls.append(jobs)
        cache = TranscriptionCache(transcriptions)
        done = []
        for job in jobs:
            if cache.get(job.key) is not None:
                continue
            record = Transcription(
                key=job.key,
                status="failed" if job.key.page == 2 else "transcribed",
                text="words",
                error="model: ModelError: rate limited" if job.key.page == 2 else None,
                mixed=job.mixed,
                cost_usd=0.01,
                created=datetime(2026, 10, 1, tzinfo=UTC),
            )
            cache.put(record, instruction=TRANSCRIBE)
            done.append(record)
        return done

    monkeypatch.setattr("apps.eval.__main__.run_preparation", fake_preparation)
    argv = ["transcribe", "--sample", "dev-400", "--expected-cost-per-page-usd", "0.01"]
    assert main(argv) == 1
    out = capsys.readouterr().out
    assert "read 2 pages now ($0.02); 2 of 4 failed in all" in out
    assert "marker NOT written" in out
    assert "--retry-failed" in out
    lookup = ReadingLookup(TranscriptionCache(transcriptions))
    assert not lookup.is_done("dev-400")

    assert main([*argv, "--retry-failed"]) == 1
    assert len(calls) == 2


def _cached_job(n: int, cache: TranscriptionCache, *, failed: bool, error: str | None) -> PageJob:
    """A fabricated reading for page ``n`` of its own document, already in ``cache``."""
    key = TranscriptionKey(
        document_sha256=f"sha{n:04d}",
        page=1,
        model=TRANSCRIBER,
        instruction="t1",
        dpi=RESOLUTION,
    )
    job = PageJob(key, lambda: b"", False)
    cache.put(
        Transcription(
            key=key,
            status="failed" if failed else "transcribed",
            text="" if failed else "words",
            error=error,
            created=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        instruction=TRANSCRIBE,
    )
    return job


def test_maybe_mark_done_writes_the_marker_at_exactly_two_percent_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = TranscriptionCache(tmp_path / "transcriptions")
    jobs = [
        _cached_job(n, cache, failed=n < 2, error="model: ModelError: x" if n < 2 else None)
        for n in range(100)
    ]
    assert pytest.approx(0.02) == MAX_FAILED_SHARE
    exit_code = _maybe_mark_done(cache, "dev-400", jobs, 0)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "every page has a reading; v2 runs may start" in out
    lookup = ReadingLookup(cache)
    assert lookup.is_done("dev-400")
    summary = json.loads(lookup.done_file("dev-400").read_text())
    assert summary["failed"] == 2
    assert summary["pages"] == 100
    assert summary["skipped_documents"] == 0


def test_maybe_mark_done_refuses_the_marker_above_two_percent_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = TranscriptionCache(tmp_path / "transcriptions")
    jobs = [
        _cached_job(n, cache, failed=n < 3, error="model: ModelError: x" if n < 3 else None)
        for n in range(100)
    ]
    exit_code = _maybe_mark_done(cache, "dev-400", jobs, 0)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "3 of 100 pages failed (3.0%)" in out
    assert "marker NOT written" in out
    assert "--retry-failed" in out
    assert not ReadingLookup(cache).is_done("dev-400")


def test_maybe_mark_done_reasons_line_shows_only_error_prefixes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reasons line is the error prefix up to the second colon -- never page text."""
    cache = TranscriptionCache(tmp_path / "transcriptions")
    jobs = [
        _cached_job(
            0,
            cache,
            failed=True,
            error="model: ModelError: the pilot's medical certificate lapsed in March",
        ),
        _cached_job(
            1,
            cache,
            failed=True,
            error="schema: reply is not JSON: line 3 column 1 (char 42)",
        ),
        _cached_job(2, cache, failed=False, error=None),
    ]
    exit_code = _maybe_mark_done(cache, "dev-400", jobs, 0)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "model: ModelError" in out
    assert "schema: reply is not JSON" in out
    # Never the page-specific detail after the prefix.
    assert "medical certificate" not in out
    assert "line 3 column 1" not in out


def test_maybe_mark_done_counts_skipped_documents_in_the_marker(
    tmp_path: Path,
) -> None:
    cache = TranscriptionCache(tmp_path / "transcriptions")
    jobs = [_cached_job(0, cache, failed=False, error=None)]
    exit_code = _maybe_mark_done(cache, "dev-400", jobs, 5)
    assert exit_code == 0
    summary = json.loads(ReadingLookup(cache).done_file("dev-400").read_text())
    assert summary["skipped_documents"] == 5


def test_report_on_v2_prints_preparation_and_the_transcribed_cases_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision 0081's cost line on a v2 run; spec §9.1's comparison on the transcribed cases."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    now = datetime(2026, 1, 1, tzinfo=UTC)
    versions: tuple[tuple[str, EvidenceVersion], ...] = (("v2-run", "v2"), ("v1-run", "v1"))
    for run_id, version in versions:
        write_jsonl(
            runs_dir / run_id / "run.jsonl",
            [
                RunRecord(
                    **{**_RUN_KWARGS, "arm": "B"},
                    run_id=run_id,
                    started=now,
                    finished=now,
                    evidence_version=version,
                )
            ],
        )
    transcribed = _scored_case("CASE1").model_copy(update={"preparation_cost_usd": 0.02})
    write_jsonl(runs_dir / "v2-run" / "cases.jsonl", [transcribed, _scored_case("CASE2")])
    write_jsonl(runs_dir / "v1-run" / "cases.jsonl", [_scored_case("CASE1"), _scored_case("CASE2")])

    assert main(["report", "v2-run", "--against", "v1-run", "--versions-compared"]) == 0
    out = capsys.readouterr().out
    assert "$0.0200 per case, $0.02 in all, 1 of 2 cases with transcribed pages" in out
    assert "on the 1 cases with transcribed pages:\npaired difference (a - b) on 1 shared" in out

    assert main(["report", "v1-run"]) == 0
    assert "evidence preparation" not in capsys.readouterr().out


# --- S2.6 final review: I1 (spend bound) and I3 (held-out refused) on `transcribe` ---


@pytest.mark.parametrize("value", ["0", "-0.01", "nan", "cheap"])
def test_transcribe_refuses_an_expected_cost_of_zero_or_less(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["transcribe", "--sample", "dev-400", "--expected-cost-per-page-usd", value])
    assert exited.value.code == 2
    assert "--expected-cost-per-page-usd" in capsys.readouterr().err


def test_transcribe_refuses_a_held_out_sample_before_fetching_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))

    def no_docket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a refused sample fetches nothing")

    monkeypatch.setattr("apps.eval.__main__.DocketClient", no_docket)
    monkeypatch.setattr("apps.eval.__main__.samples.load_cases", no_docket)
    exit_code = main(
        ["transcribe", "--sample", "heldout-400", "--expected-cost-per-page-usd", "0.01"]
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "heldout-400" in err
    assert "decision 0090" in err


def test_transcribe_that_spends_its_reservation_stops_and_exits_non_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcriptions = _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])

    def stopping_preparation(*, jobs: Sequence[PageJob], **_kwargs: object) -> list[Transcription]:
        cache = TranscriptionCache(transcriptions)
        record = Transcription(
            key=jobs[0].key,
            status="transcribed",
            text="words",
            mixed=jobs[0].mixed,
            cost_usd=0.03,
            created=datetime(2026, 10, 1, tzinfo=UTC),
        )
        cache.put(record, instruction=TRANSCRIBE)
        raise PreparationStoppedError(
            "preparation job j stopped: 1 were left unread", read=[record], unread=1
        )

    monkeypatch.setattr("apps.eval.__main__.run_preparation", stopping_preparation)
    argv = ["transcribe", "--sample", "dev-400", "--expected-cost-per-page-usd", "0.01"]
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert "read 1 pages now ($0.03)" in captured.out
    assert "1 were left unread" in captured.err
    assert "marker is NOT written" in captured.err
    assert not ReadingLookup(TranscriptionCache(transcriptions)).is_done("dev-400")


# --- S2.7 track 2 Task 3: `transcribe --model --page-rule` ---

_MIXED_TEXT = "Engine sputtered at 800 ft. Switched tanks, no change."
_MIXED_SCAN = build_pdf([PageSpec(text=_MIXED_TEXT, images=("/DCTDecode",))])


class _StubDocumentsWithMixedPage(_StubDocuments):
    """``_StubDocuments`` plus one text-and-image document (pre-flight 2.5).

    ``_StubDocuments`` alone serves only image-only scans, so a rule that drops
    text-and-image pages (``image-only``) could never be told apart from ``all`` by the jobs
    it produces. This adds one such page, own to this test's stub so the shared fixture (and
    every other test's page counts) stays exactly as it was.
    """

    def __init__(self, client: object) -> None:
        super().__init__(client)
        self.entries = (*self.entries, _entry(5, pages=1))

    def document(self, mkey: int, index: int) -> bytes:
        if index == 5:
            return _MIXED_SCAN
        return super().document(mkey, index)


def test_transcribe_reads_with_another_model_and_rule_and_marks_that_pair_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcriptions = _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])
    monkeypatch.setattr("apps.eval.__main__.CachedDocuments", _StubDocumentsWithMixedPage)
    model = "google/gemini-3.1-flash-lite"  # priced, with a reasoning level (sources.py)
    calls: list[Sequence[PageJob]] = []

    def fake_preparation(*, jobs: Sequence[PageJob], **_kwargs: object) -> list[Transcription]:
        calls.append(jobs)
        cache = TranscriptionCache(transcriptions)
        for job in jobs:
            if cache.get(job.key) is None:
                cache.put(
                    Transcription(
                        key=job.key,
                        status="transcribed",
                        text="words",
                        mixed=job.mixed,
                        cost_usd=0.001,
                        created=datetime(2026, 10, 1, tzinfo=UTC),
                    ),
                    instruction=TRANSCRIBE,
                )
        return []

    monkeypatch.setattr("apps.eval.__main__.run_preparation", fake_preparation)
    argv = [
        "transcribe",
        "--sample",
        "dev-400",
        "--expected-cost-per-page-usd",
        "0.001",
        "--model",
        model,
        "--page-rule",
        "image-only",
    ]
    assert main(argv) == 0
    assert {j.key.model for j in calls[0]} == {model}
    assert {j.mixed for j in calls[0]} == {False}  # image-only sends no mixed page
    cache = TranscriptionCache(transcriptions)
    done = ReadingLookup(cache, model=model, page_rule="image-only")
    assert done.is_done("dev-400")
    assert json.loads(done.done_file("dev-400").read_text())["page_rule"] == "image-only"
    assert not ReadingLookup(cache).is_done("dev-400")  # S2.6's pair is not claimed
    assert f"with {model}" in capsys.readouterr().out


def test_transcribe_with_a_mixed_page_sends_it_under_the_all_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
) -> None:
    """Companion to the test above (review fix round 1, pre-flight 2.5's second half): the
    same stub's text-and-image page, absent under ``image-only``, is present under ``all`` --
    so that absence assertion shows the rule is actually doing something, rather than being
    true of the stub regardless of which rule is passed.
    """
    _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])
    monkeypatch.setattr("apps.eval.__main__.CachedDocuments", _StubDocumentsWithMixedPage)
    calls: list[Sequence[PageJob]] = []

    def fake_preparation(*, jobs: Sequence[PageJob], **_kwargs: object) -> list[Transcription]:
        calls.append(jobs)
        return []

    monkeypatch.setattr("apps.eval.__main__.run_preparation", fake_preparation)
    argv = [
        "transcribe",
        "--sample",
        "dev-400",
        "--expected-cost-per-page-usd",
        "0.001",
        "--page-rule",
        "all",
    ]
    assert main(argv) == 0
    assert True in {j.mixed for j in calls[0]}  # "all" sends the mixed page too


def test_transcribe_refuses_a_model_with_no_price_before_fetching_anything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])

    def no_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("nothing is fetched for a refused model")

    monkeypatch.setattr("apps.eval.__main__._page_jobs", no_fetch)
    argv = [
        "transcribe",
        "--sample",
        "dev-400",
        "--expected-cost-per-page-usd",
        "0.001",
        "--model",
        "vendor/unpriced-model",
    ]
    assert main(argv) == 1
    assert "no price on file for vendor/unpriced-model" in capsys.readouterr().err


def test_transcribe_refuses_a_page_rule_it_does_not_know(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _transcribe_env(tmp_path, monkeypatch, record_fixtures[0])
    argv = [
        "transcribe",
        "--sample",
        "dev-400",
        "--expected-cost-per-page-usd",
        "0.001",
        "--page-rule",
        "every-page",
    ]
    with pytest.raises(SystemExit):
        main(argv)
    assert "invalid choice: 'every-page'" in capsys.readouterr().err


def test_report_against_prints_each_paired_block_by_fatal_and_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S2.6 final review, I5 (spec §9.1): overall, on transcribed cases and on cases unmarked
    in both runs, each paired difference is also printed for fatal and non-fatal cases."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    runs_dir = tmp_path / "data" / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs_dir))
    now = datetime(2026, 1, 1, tzinfo=UTC)
    versions: tuple[tuple[str, EvidenceVersion], ...] = (("v2-run", "v2"), ("v1-run", "v1"))
    for run_id, version in versions:
        write_jsonl(
            runs_dir / run_id / "run.jsonl",
            [
                RunRecord(
                    **{**_RUN_KWARGS, "arm": "B"},
                    run_id=run_id,
                    started=now,
                    finished=now,
                    evidence_version=version,
                )
            ],
        )
    fatal = {"fatal": True}
    paid = {"preparation_cost_usd": 0.02}
    mark = (CaseMark(kind="analysis_sentence", count=1),)
    v2_cases = [
        _scored_case("F1").model_copy(update={**fatal, **paid}),
        _scored_case("F2").model_copy(update=fatal),
        _scored_case("N1").model_copy(update=paid),
        _scored_case("N2", marks=mark),
    ]
    v1_cases = [
        _scored_case("F1").model_copy(update=fatal),
        _scored_case("F2").model_copy(update=fatal),
        _scored_case("N1"),
        _scored_case("N2"),
    ]
    write_jsonl(runs_dir / "v2-run" / "cases.jsonl", v2_cases)
    write_jsonl(runs_dir / "v1-run" / "cases.jsonl", v1_cases)

    assert main(["report", "v2-run", "--against", "v1-run", "--versions-compared"]) == 0
    out = capsys.readouterr().out
    overall = out.split("evidence-version comparison (decision 0076)")[1]
    overall, transcribed = overall.split("on the 2 cases with transcribed pages:")
    transcribed, unmarked = transcribed.split("on cases unmarked in both runs")
    assert "\npaired difference (a - b) on 4 shared" in overall
    assert "\nfatal: paired difference (a - b) on 2 shared" in overall
    assert "\nnon-fatal: paired difference (a - b) on 2 shared" in overall
    assert "\nfatal: paired difference (a - b) on 1 shared" in transcribed
    assert "\nnon-fatal: paired difference (a - b) on 1 shared" in transcribed
    assert "\nfatal: paired difference (a - b) on 2 shared" in unmarked
    assert "\nnon-fatal: paired difference (a - b) on 1 shared" in unmarked


@pytest.mark.parametrize("sealed", ["dev-seal-400", "dev-seal-s3-400"])
def test_run_and_transcribe_refuse_the_sealed_sample_before_anything_is_read(
    sealed: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    assert main(["run", "--arm", "B", "--sample", sealed]) == 1
    assert "sealed" in capsys.readouterr().err
    assert main(["transcribe", "--sample", sealed, "--expected-cost-per-page-usd", "0.001"]) == 1
    assert "sealed" in capsys.readouterr().err


@pytest.mark.parametrize("sealed", ["dev-seal-400", "dev-seal-s3-400"])
def test_baseline_refuses_the_sealed_sample_before_anything_is_read(
    sealed: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Final review, Important 1: ``ntsb-eval baseline --sample dev-seal-400`` scored the
    sealed sample today, free and with one flag. S3's sample is refused the same way (0129)."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    assert main(["baseline", "--sample", sealed]) == 1
    assert "sealed" in capsys.readouterr().err


def test_baseline_with_no_sample_is_unaffected_by_the_sealed_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
) -> None:
    """``--sample`` is optional on ``baseline``; the sealed guard must not fire on ``None``."""
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    assert main(["baseline"]) == 0


def _write_checkable_run(
    runs: Path,
    run_id: str = "20260926T000000-abc1234-dev-400-B",
    *,
    exclusions: tuple[str, ...] = (),
    includes: tuple[str, ...] = (),
    sample: str = "dev-400",
) -> Path:
    """A dev-400 arm B run with one scored, stepped case: enough for `ntsb-eval check`."""
    folder = runs / run_id
    when = datetime(2026, 9, 26, tzinfo=UTC)
    write_jsonl(
        folder / "run.jsonl",
        [
            RunRecord(
                run_id=run_id,
                sample=sample,
                arm="B",
                exclusions=exclusions,
                includes=includes,
                prompt_version="s1-v5",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha="abc1234",
                dirty=False,
                started=when,
                finished=when,
                cases=1,
                cost_usd=1.0,
            )
        ],
    )
    write_jsonl(
        folder / "cases.jsonl",
        [_case("c1", ("552240", "552241"), ("552241",))],
    )
    return folder


def test_check_refuses_a_held_out_run_before_any_client_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-heldout-400-B"
    _write_judgeable_run(runs, run_id, "c1", sample="heldout-400", arm="B")

    def boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no client may be built for a held-out run")

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("no client may be built for a held-out run")

    assert (
        main(
            ["check", run_id, "--way", "jev"],
            client_factory=boom_client,
            jev_factory=boom_jev,
        )
        == 1
    )
    assert "development" in capsys.readouterr().err


@pytest.mark.parametrize("sealed", ["dev-seal-400", "dev-seal-s3-400"])
def test_check_refuses_the_sealed_sample_before_any_client_is_built(
    sealed: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Final review, Important 1: ``ntsb-eval check`` already calls ``refuse_sealed``
    (``__main__.py``), but no test confirmed it before this one."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    run_id = f"20260926T000000-abc1234-{sealed}-B"
    _write_judgeable_run(runs, run_id, "c1", sample=sealed, arm="B")

    def boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no client may be built for a sealed run")

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("no client may be built for a sealed run")

    assert (
        main(
            ["check", run_id, "--way", "jev"],
            client_factory=boom_client,
            jev_factory=boom_jev,
        )
        == 1
    )
    assert "sealed" in capsys.readouterr().err


def test_check_refuses_an_ablation_source_before_cases_are_read_or_any_client_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1, Important 2: reading the phase group back from the raw record would hand
    the check a field an ablation run withheld from the model. Refused before `cases.jsonl` is
    even read (no such file is written here: a read attempt would raise, not refuse cleanly)."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-dev-400-B"
    folder = runs / run_id
    when = datetime(2026, 9, 26, tzinfo=UTC)
    write_jsonl(
        folder / "run.jsonl",
        [
            RunRecord(
                run_id=run_id,
                sample="dev-400",
                arm="B",
                exclusions=("phase_of_flight",),
                includes=(),
                prompt_version="s1-v5",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha="abc1234",
                dirty=False,
                started=when,
                finished=when,
                cases=1,
                cost_usd=1.0,
            )
        ],
    )

    def boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no client may be built for an ablation source")

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("no client may be built for an ablation source")

    assert (
        main(
            ["check", run_id, "--way", "rule"],
            client_factory=boom_client,
            jev_factory=boom_jev,
        )
        == 1
    )
    assert "ablation" in capsys.readouterr().err


def test_check_way_luna_is_refused_over_budget_without_building_any_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1, Important 1: the budget guard runs, and refuses, before any client is
    built -- an over-budget `luna`/`jev` pass must never reach `client_factory`/`jev_factory`."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())

    def boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no client may be built for an over-budget check")

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("no client may be built for an over-budget check")

    exit_code = main(
        ["check", run_id, "--way", "luna", "--budget-usd", "0.00001"],
        client_factory=boom_client,
        jev_factory=boom_jev,
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "budget" in err
    assert open_reservations(runs) == {}


class _ReservationSpyClient:
    """A fake client that notices whether a budget reservation is open when it is called."""

    def __init__(self, reply_text: str, runs_dir: Path) -> None:
        self._reply_text = reply_text
        self._runs_dir = runs_dir
        self.saw_a_reservation = False

    def complete(
        self,
        _payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        self.saw_a_reservation = bool(open_reservations(self._runs_dir))
        return ModelReply(
            content=self._reply_text,
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            model=settings.model_id(),
            response_id="fake",
        )


def test_check_way_luna_settles_its_reservation_after_a_successful_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 1, Important 1: the reservation made before the client is built is visible to
    a concurrent job for the whole synchronous pass, and settled once the pass's real spend is
    on disk, so it never sits open against the month's budget."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())

    spy = _ReservationSpyClient(json.dumps({"ranking": ["552241"]}), runs)

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return spy, None

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("the luna way needs no jev client")

    exit_code = main(
        ["check", run_id, "--way", "luna"], client_factory=factory, jev_factory=boom_jev
    )
    assert exit_code == 0
    assert spy.saw_a_reservation is True  # open for the duration of the paid call, not $0
    assert open_reservations(runs) == {}
    derived = runs / f"{run_id}-check-luna"
    assert (derived / "cases.jsonl").exists()
    assert (derived / "run.jsonl").exists()


def test_check_way_rule_writes_a_derived_run_and_prints_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1, Important 3(b): a happy-path `ntsb-eval check RUN --way rule` through
    `main`, needing no client at all."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())

    def boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("the rule way needs no client")

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("the rule way needs no client")

    exit_code = main(
        ["check", run_id, "--way", "rule"], client_factory=boom_client, jev_factory=boom_jev
    )
    assert exit_code == 0
    derived_id = f"{run_id}-check-rule"
    out = capsys.readouterr().out
    assert f"check {derived_id}:" in out
    assert (runs / derived_id / "cases.jsonl").exists()
    assert (runs / derived_id / "run.jsonl").exists()


@pytest.mark.parametrize(("flags", "expected"), [([], "s27"), (["--stats", "s3"], "s3")])
def test_check_reads_the_statistics_file_its_stats_flag_names(
    flags: list[str],
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3's ordering check reads S3's file (0129 item 4); S2.7's is the default, so every
    existing ``check`` command is unchanged. The real ``load_stats`` is wrapped, not replaced,
    so the name it gets is the one the command line chose."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    asked: list[str] = []

    def spy(name: str = "s27") -> CodingStats:
        asked.append(name)
        return load_stats("s27")  # S3's file is not needed to see which one was asked for

    monkeypatch.setattr("apps.eval.__main__.load_stats", spy)
    assert main(["check", run_id, "--way", "rule", *flags]) == 0
    assert asked == [expected]


_S3_SEALED_RUN = "20260926T000000-abc1234-dev-seal-s3-400-B"


@pytest.mark.parametrize("way", ["rule", "luna"])
def test_check_refuses_s27_statistics_for_the_s3_sealed_sample_before_anything_is_done(
    way: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Decision 0129 item 5: S2.7's pool still holds ``dev-seal-s3-400``'s cases, so the
    default ``--stats s27`` would feed the sample's own verdict counts into the check once S3.2's
    registration opens it. Refused before any client, reservation or derived folder."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)  # S3.2's file
    _write_checkable_run(runs, _S3_SEALED_RUN, sample="dev-seal-s3-400")
    for flags in ([], ["--stats", "s27"]):
        assert (
            main(
                ["check", _S3_SEALED_RUN, "--way", way, *flags],
                client_factory=_boom_client,
                jev_factory=_boom_jev,
            )
            == 1
        )
        err = capsys.readouterr().err
        assert "decision 0129" in err
        assert "--stats s3" in err
    assert not (runs / f"{_S3_SEALED_RUN}-check-{way}").exists()
    assert open_reservations(runs) == {}


def test_check_reads_s3_statistics_for_the_s3_sealed_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
    _write_checkable_run(runs, _S3_SEALED_RUN, sample="dev-seal-s3-400")
    exit_code = main(
        ["check", _S3_SEALED_RUN, "--way", "rule", "--stats", "s3"],
        client_factory=_boom_client,
        jev_factory=_boom_jev,
    )
    assert exit_code == 0
    assert f"check {_S3_SEALED_RUN}-check-rule:" in capsys.readouterr().out
    assert (runs / f"{_S3_SEALED_RUN}-check-rule" / "run.jsonl").exists()


@pytest.mark.parametrize(
    ("flags", "suffix"),
    [
        ([], "+check-rule"),
        (["--stats", "s27"], "+check-rule"),
        (["--stats", "s3"], "+check-rule-s3"),
    ],
)
def test_check_on_dev_400_is_unchanged_by_the_statistics_rule(
    flags: list[str], suffix: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every S2.7 check keeps its ``+check-<way>``; a check on S3's counts says so."""
    runs = _checkable_env(tmp_path, monkeypatch)
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    exit_code = main(
        ["check", run_id, "--way", "rule", *flags],
        client_factory=_boom_client,
        jev_factory=_boom_jev,
    )
    assert exit_code == 0
    derived = answering_run_record(runs / f"{run_id}-check-rule")
    assert derived.prompt_version == f"s1-v5{suffix}"


def test_check_refuses_an_unknown_statistics_name(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["check", "some-run", "--way", "rule", "--stats", "s4"])
    assert stopped.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_check_way_luna_run_twice_is_refused_the_second_time_with_nothing_leaked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 2, Important: a repeat check of an already-finished derived run must not
    reserve anything the second time, and must not touch the first run's own output. The old
    code reserved before `checkpass.check_run` ran its own "already exists" refusal, so a
    repeated check left an open reservation behind even though `run.jsonl` was untouched."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())

    fake = RecordingFakeClient([json.dumps({"ranking": ["552241"]})])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("the luna way needs no jev client")

    first_exit = main(
        ["check", run_id, "--way", "luna"], client_factory=factory, jev_factory=boom_jev
    )
    assert first_exit == 0
    derived = runs / f"{run_id}-check-luna"
    first_run_jsonl = (derived / "run.jsonl").read_text()

    def boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("a repeated check must not reach the client factory")

    def boom_jev_again(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("a repeated check must not reach the jev factory")

    second_exit = main(
        ["check", run_id, "--way", "luna"],
        client_factory=boom_client,
        jev_factory=boom_jev_again,
    )
    assert second_exit == 1
    assert "exists" in capsys.readouterr().err
    assert open_reservations(runs) == {}
    assert (derived / "run.jsonl").read_text() == first_run_jsonl


def test_check_way_luna_releases_its_reservation_when_the_client_factory_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 2, Important: a factory that raises after the reservation was made (a missing
    API key, say) must not leave that reservation open with nothing left to settle it."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())

    def broken_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise ConfigurationError("OPENROUTER_API_KEY is not set")

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("the luna way needs no jev client")

    exit_code = main(
        ["check", run_id, "--way", "luna"], client_factory=broken_client, jev_factory=boom_jev
    )
    assert exit_code == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert open_reservations(runs) == {}


def test_check_refuses_a_check_run_as_its_own_source_leaving_no_new_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 2, Important: refusing a source that is itself a derived check run must not
    create the empty `<id>-check-<way>` folder `reserve_within_budget` would otherwise leave
    behind -- the old code reserved before `checkpass.check_run`'s own refusal of this shape
    of source ever ran."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-dev-400-B-check-luna"
    _write_checkable_run(runs, run_id)

    def boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no client may be built for a stacked-check source")

    def boom_jev(_settings: Settings) -> TypeSafeClient:
        raise AssertionError("no client may be built for a stacked-check source")

    before = {p.name for p in runs.iterdir()}
    exit_code = main(
        ["check", run_id, "--way", "luna"], client_factory=boom_client, jev_factory=boom_jev
    )
    assert exit_code == 1
    assert "stacked" in capsys.readouterr().err
    assert {p.name for p in runs.iterdir()} == before
    assert open_reservations(runs) == {}


def test_resolve_latest_skips_derived_check_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    when = datetime(2026, 9, 26, tzinfo=UTC)
    _write_run(runs, "20260926T000000-abc1234-dev-400-B", finished=when, arm="B")
    _write_run(runs, "20260926T000000-abc1234-dev-400-B-check-rule", finished=when, arm="B")
    assert resolve_latest(runs, "B", "dev-400") == "20260926T000000-abc1234-dev-400-B"


# --- `check --way jev2` (decision 0103): the same refusals and reservation as `jev` ---


def _boom_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
    raise AssertionError("the jev2 way needs no OpenRouter client")


def _boom_jev(_settings: Settings) -> TypeSafeClient:
    raise AssertionError("no TypeSafe client may be built for a refused jev2 check")


def _jev2_client(runs: Path, seen: list[dict[str, object]]) -> TypeSafeClient:
    """A TypeSafe client on a mock transport: answers every option, notes open reservations."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"body": body, "reserved": bool(open_reservations(runs))})
        labels = list(body["questions"]["defining"]["criteria"])
        probabilities = dict.fromkeys(labels, 0.0)
        probabilities[labels[-2]] = 1.0  # the last code, not none_of_these
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 1500, "output_tokens": 0},
                "answers": {
                    "defining": {
                        "type": "choice",
                        "choice": labels[-2],
                        "confidence": 0.7,
                        "probabilities": probabilities,
                    }
                },
            },
        )

    return TypeSafeClient(
        "k", base_url="https://api.typesafe.ai", transport=httpx.MockTransport(handler)
    )


def _checkable_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())
    return runs


def test_check_way_jev2_reserves_calls_the_pinned_model_and_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    seen: list[dict[str, object]] = []
    exit_code = main(
        ["check", run_id, "--way", "jev2"],
        client_factory=_boom_client,
        jev_factory=lambda _settings: _jev2_client(runs, seen),
    )
    assert exit_code == 0
    assert len(seen) == 1
    assert seen[0]["reserved"] is True  # the reservation is open for the paid call
    body = cast("dict[str, object]", seen[0]["body"])
    assert body["model"] == "jev-1.13.0"
    assert isinstance(body["state"], dict)
    assert open_reservations(runs) == {}
    derived = runs / f"{run_id}-check-jev2"
    step = read_jsonl(derived / "cases.jsonl", CaseResult)[0].steps[-1]
    assert {"choice", "confidence", "probabilities"} <= set(step.arguments)
    assert f"check {run_id}-check-jev2:" in capsys.readouterr().out


def test_check_way_jev2_run_twice_is_refused_the_second_time_before_any_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    seen: list[dict[str, object]] = []
    assert (
        main(
            ["check", run_id, "--way", "jev2"],
            client_factory=_boom_client,
            jev_factory=lambda _settings: _jev2_client(runs, seen),
        )
        == 0
    )
    derived = runs / f"{run_id}-check-jev2"
    first = (derived / "run.jsonl").read_text()
    assert (
        main(["check", run_id, "--way", "jev2"], client_factory=_boom_client, jev_factory=_boom_jev)
        == 1
    )
    assert "exists" in capsys.readouterr().err
    assert open_reservations(runs) == {}
    assert (derived / "run.jsonl").read_text() == first


def test_check_way_jev2_refuses_an_unfinished_source_before_reserving_or_any_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    run_id = "20260926T000000-abc1234-dev-400-B"
    folder = _write_checkable_run(runs, run_id)
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    (folder / "run.jsonl").unlink()
    write_jsonl(folder / "run.jsonl", [record.model_copy(update={"finished": None})])
    before = {p.name for p in runs.iterdir()}
    assert (
        main(["check", run_id, "--way", "jev2"], client_factory=_boom_client, jev_factory=_boom_jev)
        == 1
    )
    assert "finished" in capsys.readouterr().err
    assert open_reservations(runs) == {}
    assert {p.name for p in runs.iterdir()} == before


def test_check_way_jev2_refuses_an_ablation_source_and_a_held_out_run_before_any_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    ablation = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, ablation, exclusions=("phase_of_flight",))
    assert (
        main(
            ["check", ablation, "--way", "jev2"], client_factory=_boom_client, jev_factory=_boom_jev
        )
        == 1
    )
    assert "ablation" in capsys.readouterr().err
    held = "20260926T000000-abc1234-heldout-400-B"
    _write_judgeable_run(runs, held, "c1", sample="heldout-400", arm="B")
    assert (
        main(["check", held, "--way", "jev2"], client_factory=_boom_client, jev_factory=_boom_jev)
        == 1
    )
    assert "development" in capsys.readouterr().err
    assert open_reservations(runs) == {}


def test_check_way_jev2_is_refused_over_budget_without_building_any_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    exit_code = main(
        ["check", run_id, "--way", "jev2", "--budget-usd", "0.00001"],
        client_factory=_boom_client,
        jev_factory=_boom_jev,
    )
    assert exit_code == 1
    assert "budget" in capsys.readouterr().err
    assert open_reservations(runs) == {}


# --- `check` over an arm C run: the ordering check as a diagnostic (decision 0137) ---

_ARM_C_CHECKED = "20261001T201506-fd6053f-dev-400-C"


def _write_checkable_arm_c_run(
    runs: Path,
    run_id: str = _ARM_C_CHECKED,
    *,
    sample: str = "dev-400",
    without: Sequence[str] = (),
) -> Path:
    """A finished arm C run with one scored case: stall first, then LOC; the NTSB's first is LOC.

    Both codes are the loop's own, so both are on the check's candidate list whatever the counts.
    """
    folder = _write_checkable_run(runs, run_id, sample=sample)
    record = answering_run_record(folder)
    arm_c = record.model_copy(
        update={"arm": "C", "prompt_version": "s3-v1+ge17fecdc66ec+p947fac1c86a4"}
    )
    (folder / "run.jsonl").write_text(arm_c.model_dump_json() + "\n")  # replaced, not appended
    (folder / "cases.jsonl").unlink()
    write_jsonl(folder / "cases.jsonl", [_case("c1", ("552240", "552241"), ("552241", "552240"))])
    (folder / "spec.json").write_text(json.dumps({"stats": "s3", "without": list(without)}))
    return folder


def test_check_reads_an_arm_c_run_with_luna_in_s3s_statistics_and_report_prints_the_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision 0137 items 1-4: the diagnostic runs as any check does, then is read with
    ``report <derived> --against <run>``, which prints the first codes changed beside it."""
    runs = _checkable_env(tmp_path, monkeypatch)
    _write_checkable_arm_c_run(runs)
    asked: list[str] = []

    def spy(name: str = "s27") -> CodingStats:
        asked.append(name)
        return load_stats(name)  # type: ignore[arg-type]

    monkeypatch.setattr("apps.eval.__main__.load_stats", spy)
    spy_client = _ReservationSpyClient(json.dumps({"ranking": ["552240"]}), runs)
    argv = ["check", _ARM_C_CHECKED, "--way", "luna", "--stats", "s3"]
    assert main(argv, client_factory=lambda _s: (spy_client, None), jev_factory=_boom_jev) == 0
    assert asked == ["s3"]
    assert spy_client.saw_a_reservation is True
    assert open_reservations(runs) == {}
    derived_id = f"{_ARM_C_CHECKED}-check-luna"
    derived = answering_run_record(runs / derived_id)
    assert derived.prompt_version == "s3-v1+ge17fecdc66ec+p947fac1c86a4+check-luna-s3"
    assert derived.arm == "C"
    capsys.readouterr()
    assert main(["report", derived_id, "--against", _ARM_C_CHECKED]) == 0
    out = capsys.readouterr().out
    assert "- occurrence top-1: +100.0%" in out
    assert (
        "first codes changed (a against b): 1 of 1 shared, scored cases; fixes 1, breaks 0 "
        "(decision 0137)"
    ) in out


def test_report_against_prints_no_first_code_line_for_an_arm_b_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Arm B's checked runs report exactly as before decision 0137."""
    runs = _checkable_env(tmp_path, monkeypatch)
    run_id = "20260926T000000-abc1234-dev-400-B"
    _write_checkable_run(runs, run_id)
    assert main(["check", run_id, "--way", "rule"], client_factory=_boom_client) == 0
    capsys.readouterr()
    assert main(["report", f"{run_id}-check-rule", "--against", run_id]) == 0
    out = capsys.readouterr().out
    assert "paired difference (a - b) on 1 shared" in out
    assert "first codes changed" not in out


@pytest.mark.parametrize("way", ["rule", "jev", "jev2"])
def test_check_refuses_an_arm_c_run_every_way_but_luna_before_any_reservation_or_client(
    way: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    _write_checkable_arm_c_run(runs)
    before = {p.name for p in runs.iterdir()}
    argv = ["check", _ARM_C_CHECKED, "--way", way, "--stats", "s3"]
    assert main(argv, client_factory=_boom_client, jev_factory=_boom_jev) == 1
    err = capsys.readouterr().err
    assert "decision 0137 item 1" in err
    assert f"not {way}" in err
    assert {p.name for p in runs.iterdir()} == before
    assert open_reservations(runs) == {}


def test_check_refuses_an_arm_c_run_in_s27s_statistics_before_any_reservation_or_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ``--stats`` default is S2.7's, so the arm C run must name S3's, as a tool post-pass
    must (decision 0137 item 2)."""
    runs = _checkable_env(tmp_path, monkeypatch)
    _write_checkable_arm_c_run(runs)
    for flags in ([], ["--stats", "s27"]):
        argv = ["check", _ARM_C_CHECKED, "--way", "luna", *flags]
        assert main(argv, client_factory=_boom_client, jev_factory=_boom_jev) == 1
        err = capsys.readouterr().err
        assert "--stats s3, not s27" in err
        assert "decision 0137 item 2" in err
    assert not (runs / f"{_ARM_C_CHECKED}-check-luna").exists()
    assert open_reservations(runs) == {}


def test_check_refuses_an_arm_c_tool_ablation_before_any_reservation_or_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = _checkable_env(tmp_path, monkeypatch)
    _write_checkable_arm_c_run(runs, without=("coding",))
    argv = ["check", _ARM_C_CHECKED, "--way", "luna", "--stats", "s3"]
    assert main(argv, client_factory=_boom_client, jev_factory=_boom_jev) == 1
    err = capsys.readouterr().err
    assert "tool ablation (without=coding)" in err
    assert "decision 0137 item 1" in err
    assert open_reservations(runs) == {}


@pytest.mark.parametrize("sample", ["heldout-400", "dev-seal-s3-400"])
def test_check_refuses_a_held_out_or_sealed_arm_c_run_before_any_reservation_or_client(
    sample: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The sealed sample is refused even with S3.2's registration committed (decision 0137
    item 5): ``refuse_sealed`` lets it through then, and ``checkpass`` does not."""
    runs = _checkable_env(tmp_path, monkeypatch)
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
    run_id = f"20261001T201506-fd6053f-{sample}-C"
    _write_checkable_arm_c_run(runs, run_id, sample=sample)
    argv = ["check", run_id, "--way", "luna", "--stats", "s3"]
    assert main(argv, client_factory=_boom_client, jev_factory=_boom_jev) == 1
    err = capsys.readouterr().err
    assert ("development" if sample.startswith("heldout") else "decision 0137 item 5") in err
    assert not (runs / f"{run_id}-check-luna").exists()
    assert open_reservations(runs) == {}


# --------------------------------------------------------------------------------------------
# Arm C, the agent loop (S3.1 Task 10)
# --------------------------------------------------------------------------------------------

_ARM_C_USAGE = Usage(prompt_tokens=1000, completion_tokens=10, cached_tokens=600)
_S3_GUIDANCE = ("r3-loc-stall", "r6-aircraft-control")


def _arm_c_replies() -> list[str | ModelReply]:
    """One case: its one readable document skipped twice, then an answer with no findings."""
    return [
        tool_reply("record_hypothesis", _hyp(), usage=_ARM_C_USAGE),
        tool_reply("choose_documents", _choose({1: False}), usage=_ARM_C_USAGE),
        tool_reply("choose_documents", _choose({1: False}), usage=_ARM_C_USAGE),
        tool_reply("submit_answer", _hyp(findings=[]), usage=_ARM_C_USAGE),
    ]


class _StubDocketReader:
    """Stands in for ``CachedDocketReader``: the same constructor, a fixed docket, no HTTP."""

    def __init__(self, client: object, *, readings: object = None) -> None:
        self.client = client
        self.version = "v1" if readings is None else "v2"

    def read(self, mkey: int) -> Docket:
        """The fixed docket, under the key asked for, as a real reader returns a case's own."""
        docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
        listing = docket.listing.model_copy(update={"mkey": mkey})
        return docket.model_copy(update={"mkey": mkey, "listing": listing})


def _arm_c_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> tuple[str, Path]:
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
    monkeypatch.setattr("apps.eval.__main__.CachedDocketReader", _StubDocketReader)
    return _eval_env(tmp_path, monkeypatch, record_fixtures[0])


def _factory(
    client: ModelClient, batch: BatchRunner | None = None
) -> Callable[[Settings], tuple[ModelClient, BatchRunner | None]]:
    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return client, batch

    return factory


_ARM_C_SYNC = ["--sync", "--price-variant", "standard", "--expected-cost-per-case-usd", "0.01"]


def test_run_arm_c_then_report_and_report_against_arm_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Arm C writes the records arm B writes, so ``report --against`` compares them unchanged."""
    case_id, runs_dir = _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    agent = RecordingFakeClient(_arm_c_replies())
    argv = ["run", "--arm", "C", "--sample", "dev-400", *_ARM_C_SYNC]
    assert main(argv, client_factory=_factory(agent)) == 0
    (c_folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    record = answering_run_record(c_folder)
    assert (record.arm, record.finished is not None) == ("C", True)
    assert record.guidance == _S3_GUIDANCE
    assert record.cap_usd == pytest.approx(0.15)  # arm C's own default cap
    assert len(agent.payloads) == 4
    assert all("crankshaft" not in p.text for p in agent.payloads)  # never in the first message

    b_client = RecordingFakeClient([GOOD, REFINE])
    b_argv = ["run", "--arm", "B", "--sample", "dev-400", "--sync", "--price-variant", "standard"]
    assert main(b_argv, client_factory=_factory(b_client)) == 0
    (b_folder,) = [p for p in runs_dir.iterdir() if p.is_dir() and p != c_folder]

    capsys.readouterr()
    assert main(["report", c_folder.name]) == 0
    out = capsys.readouterr().out
    assert "sample=dev-400 arm=C" in out
    assert "| all |" in out
    assert "unread: 1 of 1 cases left documents unread; 1 documents not read" in out
    assert "cap: " not in out  # arm C chose not to read it; no cap was hit
    assert "cached share of prompt tokens: 2400/4000" in out
    assert "failures by reason: none" in out

    assert main(["report", c_folder.name, "--against", b_folder.name]) == 0
    compared = capsys.readouterr().out
    assert "paired difference (a - b) on 1 shared" in compared
    assert case_id not in compared


def test_run_arm_c_flags_reach_the_agent_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    captured: dict[str, object] = {}

    class SpyAgentRunner:
        def __init__(self, _client: object, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(
            self, spec: RunSpec, raws: Sequence[object], *, resume: str | None = None
        ) -> RunRecord:
            captured["spec"] = spec
            captured["resume"] = resume
            return _arm_c_record("spied", guidance=spec.guidance)

    monkeypatch.setattr("apps.eval.__main__.AgentRunner", SpyAgentRunner)
    argv = ["run", "--arm", "C", "--sample", "dev-400", "--without", "coding"]
    argv += ["--without", "suggest_codes", "--cap-usd", "0.2"]
    assert main(argv, client_factory=_factory(RecordingFakeClient([]))) == 0
    spec = captured["spec"]
    assert isinstance(spec, RunSpec)
    assert (spec.arm, spec.guidance, spec.cap_usd) == ("C", _S3_GUIDANCE, 0.2)
    assert captured["without"] == frozenset({"coding", "suggest_codes"})
    assert captured["stats"] == load_stats("s3")
    docket = captured["docket"]
    assert isinstance(docket, _StubDocketReader)
    assert docket.version == "v1"
    assert captured["ledger_path"] == Settings().heldout_ledger_path
    assert captured["pass_reasoning"] is False
    assert captured["resume"] is None
    assert captured["round_number"] is None  # no --round: the plain arm C


def test_run_arm_c_reads_the_one_pass_reasoning_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """``loop.PASS_REASONING`` is the one setting arm C and arm B's post-pass read (the shape
    probe's check 4 decides it); flipping it reaches the runner. The post-pass's half of this
    is ``tests/test_agent_armb.py``'s test of the same name."""
    _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    captured: dict[str, object] = {}

    class SpyAgentRunner:
        def __init__(self, _client: object, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(
            self, spec: RunSpec, raws: Sequence[object], *, resume: str | None = None
        ) -> RunRecord:
            return _arm_c_record("spied", guidance=spec.guidance)

    monkeypatch.setattr("apps.eval.__main__.AgentRunner", SpyAgentRunner)
    monkeypatch.setattr("ntsb_probable_cause.agent.loop.PASS_REASONING", True)
    argv = ["run", "--arm", "C", "--sample", "dev-400"]
    assert main(argv, client_factory=_factory(RecordingFakeClient([]))) == 0
    assert captured["pass_reasoning"] is True


def test_round_is_refused_before_anything_unless_its_registration_is_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
) -> None:
    """S3.1 Task 13: a tuning round is registered in docs/rounds/ before it runs (spec §10.3)."""
    _, runs_dir = _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    asked: list[Path] = []

    def committed(path: Path, repo: Path = Path()) -> bool:
        asked.append(path)
        return path.name != "s3-round-2.md"

    monkeypatch.setattr(gitinfo, "is_committed", committed)

    def boom(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no client may be built for an unregistered round")

    argv = ["run", "--arm", "C", "--sample", "dev-400", "--round", "2"]
    assert main(argv, client_factory=boom) == 1
    err = capsys.readouterr().err
    assert "docs/rounds/s3-round-2.md" in err
    assert "not committed" in err
    assert Path("docs/rounds/s3-round-2.md") in asked
    assert not runs_dir.exists()  # no folder, so no reservation either


def test_round_is_refused_on_any_arm_but_c(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
) -> None:
    _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    built: list[Settings] = []

    def factory(settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        built.append(settings)
        return RecordingFakeClient([]), None

    argv = ["run", "--arm", "B", "--sample", "dev-400", "--round", "1"]
    assert main(argv, client_factory=factory) == 1
    assert "--round" in capsys.readouterr().err
    assert built == []


@pytest.mark.parametrize("number", ["0", "-1", "one"])
def test_a_round_number_is_a_whole_number_from_one(number: str) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["run", "--arm", "C", "--sample", "dev-400", "--round", number])
    assert raised.value.code == 2  # argparse's usage error, before anything is read


def test_a_registered_round_is_recorded_in_the_spec_and_the_prompt_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    _, runs_dir = _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    agent = RecordingFakeClient(_arm_c_replies())
    argv = ["run", "--arm", "C", "--sample", "dev-400", "--round", "3", *_ARM_C_SYNC]
    assert main(argv, client_factory=_factory(agent)) == 0
    (folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    record = answering_run_record(folder)
    assert record.prompt_version == prompt_version(_S3_GUIDANCE, 3)
    assert record.prompt_version.endswith("+r3")
    recorded = json.loads((folder / "spec.json").read_text())
    assert recorded["round"] == 3
    assert recorded["agent_prompt_version"] == record.prompt_version
    assert record.guidance == _S3_GUIDANCE  # a round changes no guidance unless it names some


def test_without_is_refused_on_an_arm_with_no_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
) -> None:
    _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    built: list[Settings] = []

    def factory(settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        built.append(settings)
        return RecordingFakeClient([]), None

    argv = ["run", "--arm", "B", "--sample", "dev-400", "--without", "coding"]
    assert main(argv, client_factory=factory) == 1
    assert "--without" in capsys.readouterr().err
    assert built == []


def test_arm_c_refuses_v2_before_any_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
) -> None:
    _, runs_dir = _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    agent = RecordingFakeClient([])
    argv = ["run", "--arm", "C", "--sample", "dev-400", "--evidence-version", "v2", *_ARM_C_SYNC]
    assert main(argv, client_factory=_factory(agent)) == 1
    assert "v1 only" in capsys.readouterr().err
    assert agent.payloads == []
    assert not runs_dir.exists()


def test_arm_c_refuses_its_sealed_sample_before_anything_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)

    def boom(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        raise AssertionError("no client may be built for a sealed sample")

    assert main(["run", "--arm", "C", "--sample", "dev-seal-s3-400"], client_factory=boom) == 1
    assert "sealed" in capsys.readouterr().err


@pytest.mark.parametrize("sync", [True, False])
def test_arm_c_refuses_the_sample_s27_used_once_before_any_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
    sync: bool,
) -> None:
    """dev-seal-400 was used once (decision 0095). Its registration is committed, so
    ``refuse_sealed`` passes, and S3's pool leaves it out, so ``refuse_pool_holding`` passes:
    the runner refuses it, before any folder, reservation or model call."""
    _, runs_dir = _arm_c_env(tmp_path, monkeypatch, record_fixtures)
    monkeypatch.setitem(samples._FILES, "dev-seal-400", "dev_ids.csv")  # the one fixture case
    agent = RecordingFakeClient([])
    batch = FakeBatchClient(handlers=[])
    argv = ["run", "--arm", "C", "--sample", "dev-seal-400"]
    argv += _ARM_C_SYNC if sync else ["--expected-cost-per-case-usd", "0.01"]
    assert main(argv, client_factory=_factory(agent, batch)) == 1
    err = capsys.readouterr().err
    assert "dev-seal-400" in err
    assert "decision 0095" in err
    assert agent.payloads == []
    assert batch.submitted == []
    assert not runs_dir.exists()


def test_a_cancelled_batch_exits_one_and_says_how_to_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record_fixtures: list[dict[str, object]],
) -> None:
    _, runs_dir = _arm_c_env(tmp_path, monkeypatch, record_fixtures)

    def cancelled(batch_id: str, _requests: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(
            batch_id=batch_id, status="cancelled", results=(), reported_cost_usd=None
        )

    batch = FakeBatchClient(handlers=[cancelled])
    argv = ["run", "--arm", "C", "--sample", "dev-400", "--expected-cost-per-case-usd", "0.01"]
    assert main(argv, client_factory=_factory(RecordingFakeClient([]), batch)) == 1
    (folder,) = [p for p in runs_dir.iterdir() if p.is_dir()]
    err = capsys.readouterr().err
    assert "was cancelled" in err
    assert f"--resume {folder.name}" in err
    assert open_reservations(runs_dir) == {}


def _arm_c_record(
    run_id: str, *, guidance: tuple[str, ...], round_number: int | None = None
) -> RunRecord:
    when = datetime(2026, 10, 1, tzinfo=UTC)
    kwargs = _RUN_KWARGS | {"arm": "C", "prompt_version": prompt_version(guidance, round_number)}
    return RunRecord(**kwargs, run_id=run_id, started=when, finished=when, guidance=guidance)


def test_resolve_latest_finds_the_plain_arm_c_run_and_skips_its_variants(tmp_path: Path) -> None:
    """Arm C always reads its guidance, so "plain" means S3's guidance, no round, no ablation."""
    runs = tmp_path / "runs"
    plain = "20261001T000000-abc1234-dev-400-C"
    write_jsonl(runs / plain / "run.jsonl", [_arm_c_record(plain, guidance=_S3_GUIDANCE)])
    variants = {
        "20261001T000001-abc1234-dev-400-C": _arm_c_record(
            "x", guidance=_S3_GUIDANCE, round_number=1
        ),
        "20261001T000002-abc1234-dev-400-C": _arm_c_record("x", guidance=("r3-loc-stall",)),
        "20261001T000003-abc1234-dev-400-C": _arm_c_record("x", guidance=_S3_GUIDANCE),
    }
    for run_id, record in variants.items():
        write_jsonl(runs / run_id / "run.jsonl", [record.model_copy(update={"run_id": run_id})])
    (runs / "20261001T000003-abc1234-dev-400-C" / "spec.json").write_text(
        json.dumps({"arm": "C", "without": ["coding"]})
    )
    assert resolve_latest(runs, "C", "dev-400") == plain
    (runs / plain / "spec.json").write_text(json.dumps({"arm": "C", "without": []}))
    assert resolve_latest(runs, "C", "dev-400") == plain  # an empty ablation is no ablation


def test_resolve_latest_finds_a_plain_arm_c_run_made_on_an_earlier_agent_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Andy, 2026-10-01: plain arm C is S3's guidance and no round; ``+p`` is not compared."""
    runs = tmp_path / "runs"
    current = _arm_c_record("x", guidance=_S3_GUIDANCE).prompt_version
    original = agent_texts.source_text
    with monkeypatch.context() as patched:
        patched.setattr(agent_texts, "source_text", lambda p, n: f"{original(p, n)}# earlier\n")
        earlier = _arm_c_record("x", guidance=_S3_GUIDANCE)
        later_round = _arm_c_record("x", guidance=_S3_GUIDANCE, round_number=1)
    assert earlier.prompt_version != current
    assert current == _arm_c_record("x", guidance=_S3_GUIDANCE).prompt_version
    plain = "20261001T000000-abc1234-dev-400-C"
    write_jsonl(runs / plain / "run.jsonl", [earlier.model_copy(update={"run_id": plain})])
    newer_round = "20261001T000001-abc1234-dev-400-C"
    write_jsonl(
        runs / newer_round / "run.jsonl", [later_round.model_copy(update={"run_id": newer_round})]
    )
    assert resolve_latest(runs, "C", "dev-400") == plain


def test_resolve_latest_skips_a_tools_post_pass(tmp_path: Path) -> None:
    """Task 12's derived ``<run id>-tools`` run records arm B; it is not a new answering run."""
    runs = tmp_path / "runs"
    when = datetime(2026, 9, 26, tzinfo=UTC)
    _write_run(runs, "20260926T000000-abc1234-dev-400-B", finished=when, arm="B")
    _write_run(runs, "20260926T000000-abc1234-dev-400-B-tools", finished=when, arm="B")
    assert resolve_latest(runs, "B", "dev-400") == "20260926T000000-abc1234-dev-400-B"


def test_resolve_latest_leaves_out_a_renamed_folder_by_its_name_and_its_record(
    tmp_path: Path,
) -> None:
    """Decision 0084 split one folder into ``-confirm2000`` and ``-size16000``: both finished,
    plain dev-400 arm B runs. The glob's shape leaves out such a suffix, and a renamed folder
    whose name the glob does take is left out by its record, which names another run id."""
    runs = tmp_path / "runs"
    when = datetime(2026, 9, 25, tzinfo=UTC)
    plain = "20260925T000000-abc1234-dev-400-B"
    _write_run(runs, plain, finished=when, arm="B")
    for suffix in ("confirm2000", "size16000"):
        record = RunRecord(
            **(dict(_RUN_KWARGS) | {"arm": "B"}),
            run_id="20260925T100148-40c6ec6-dev-400-B",
            started=when,
            finished=when,
        )
        write_jsonl(runs / f"20260925T100148-40c6ec6-dev-400-B-{suffix}" / "run.jsonl", [record])
    assert resolve_latest(runs, "B", "dev-400") == plain
    copied = RunRecord(
        **(dict(_RUN_KWARGS) | {"arm": "B"}),
        run_id="20260925T100148-40c6ec6-dev-400-B",
        started=when,
        finished=when,
    )
    write_jsonl(runs / "20260926T000000-40c6ec6-dev-400-B" / "run.jsonl", [copied])
    assert resolve_latest(runs, "B", "dev-400") == plain


@pytest.mark.parametrize(
    "suffix",
    [
        "+tools-s3",
        "+check-luna",
        "+check-luna-s3",
        "+tools-s3+check-luna-s3",
        "+tools-s3+p0123456789ab",  # the post-pass label from decision 0133
        "+tools-s3+p0123456789ab+check-luna-s3",
    ],
)
def test_resolve_latest_leaves_out_a_derived_run_by_its_record(tmp_path: Path, suffix: str) -> None:
    """A derived run whose folder the glob takes (moved, say) is still not an answering run."""
    runs = tmp_path / "runs"
    when = datetime(2026, 9, 26, tzinfo=UTC)
    plain = "20260926T000000-abc1234-dev-400-B"
    _write_run(runs, plain, finished=when, arm="B")
    newer = "20260927T000000-abc1234-dev-400-B"
    kwargs = dict(_RUN_KWARGS) | {"arm": "B", "prompt_version": f"v{suffix}"}
    derived = RunRecord(**kwargs, run_id=newer, started=when, finished=when)
    write_jsonl(runs / newer / "run.jsonl", [derived])
    assert resolve_latest(runs, "B", "dev-400") == plain


def _trail_call(cached: int | None) -> AgentCall:
    when = datetime(2026, 10, 1, tzinfo=UTC)
    return AgentCall(
        run_id="r",
        case_id="c1",
        trigger=1,
        docket_state="none",
        call_index=0,
        step="h0",
        retry=False,
        tool="record_hypothesis",
        arguments={},
        protocol_error=None,
        result_chars=0,
        argument_errors=0,
        hypothesis=None,
        prompt_tokens=500,
        cached_tokens=cached,
        completion_tokens=10,
        reasoning_tokens=None,
        finish_reason="tool_calls",
        cost_usd=0.0,
        estimated_usd=0.0,
        sent_at=when,
        returned_at=when,
        batch_id=None,
        commit_sha="abc1234",
        dirty=False,
    )


def test_report_names_an_ablation_and_reads_the_cached_share_from_the_trail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20261001T000000-abc1234-dev-400-C"
    folder = runs / run_id
    write_jsonl(folder / "run.jsonl", [_arm_c_record(run_id, guidance=_S3_GUIDANCE)])
    write_jsonl(folder / "cases.jsonl", [_scored_case("c1")])
    (folder / "spec.json").write_text(json.dumps({"arm": "C", "without": ["coding"]}))
    write_jsonl(folder / TRAIL_FILE, [_trail_call(None), _trail_call(300)])
    assert main(["report", run_id]) == 0
    out = capsys.readouterr().out
    assert "without=coding" in out
    assert "cached share of prompt tokens: 300/1000" in out
