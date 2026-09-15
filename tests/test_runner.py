"""The runner: sync and batch answering passes, the cap, the budget (spec §6)."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import BudgetError, ConfigurationError, LeakageError, ModelError
from ntsb_probable_cause.model.batch import BatchRequest, BatchResult, BatchStatus
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    RecordingFakeClient,
    Turn,
    Usage,
)
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, read_jsonl
from ntsb_probable_cause.scoring.runner import (
    Runner,
    RunSpec,
    case_payload,
    project_cost,
    refuse_over_budget,
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
ABSTAIN = json.dumps(
    {
        "evidence_narrative": "n",
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": 0.1,
        "abstain": True,
        "evidence_used": [],
        "occurrence": [{"phase": "552", "event": "230", "probability": 0.1}],
        "findings": [],
    }
)


def runner(
    tmp_path: Path,
    client: ModelClient,
    spent: float = 0.0,
    batch: FakeBatchClient | None = None,
) -> Runner:
    return Runner(
        client,
        batch=batch,
        tables=load_tables(),
        seen_pairs=frozenset({"552230"}),
        runs_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.md",
        month_spent_usd=spent,
        commit=("abc1234", False),
        now=lambda: datetime(2026, 9, 15, tzinfo=UTC),
    )


def test_over_cap_case_is_failed_without_a_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        cap_usd=0.0000001,
        expected_cost_per_case_usd=0.0,
    )
    run = runner(tmp_path, client).run(spec, record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure == "cap"
    assert client.payloads == []


def test_sync_run_writes_three_files_and_one_step_per_case(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE] * len(record_fixtures))
    spec = RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001)
    run = runner(tmp_path, client).run(spec, record_fixtures)
    folder = tmp_path / "runs" / run.run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    steps = read_jsonl(folder / "steps.jsonl", StepRecord)
    assert len(cases) == len(record_fixtures)
    assert len(steps) == len(record_fixtures)
    assert all(c.scores is not None and c.failure is None for c in cases)
    assert steps[0].tool == "none"
    assert steps[0].stop_reason == "answered"
    assert read_jsonl(folder / "run.jsonl", RunRecord)[0].prompt_version == "s1-v1"
    assert len(client.payloads) == 2 * len(record_fixtures)  # two turns per case


def test_schema_failure_is_retried_once_then_recorded(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient(["not json", "still not json"] + [GOOD, REFINE] * 10)
    run = runner(tmp_path, client).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema")
    assert case.scores is None


def test_arm_a_excludes_everything_but_start_facts(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE] * 2)
    runner(tmp_path, client).run(
        RunSpec(sample="dev-400", arm="A", sync=True, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    sent = client.payloads[0].fields()
    assert "pilot_total_hours" not in sent
    assert "weather_metar" not in sent


def test_case_number_probe_refused_off_dev(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    with pytest.raises(LeakageError, match="case number"):
        runner(tmp_path, client).run(
            RunSpec(
                sample="heldout-40",
                arm="ceiling",
                sync=True,
                include_case_number=True,
                expected_cost_per_case_usd=0.001,
            ),
            record_fixtures[:1],
        )


def test_budget_refusal_before_any_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD])
    with pytest.raises(BudgetError):
        runner(tmp_path, client, spent=24.99).run(
            RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.01),
            record_fixtures,
        )
    assert client.payloads == []


def test_project_cost_and_refusal() -> None:
    assert project_cost(RunSpec(sample="dev-400", arm="A", cap_usd=0.05), 400) == pytest.approx(
        20.0
    )
    assert project_cost(
        RunSpec(sample="dev-400", arm="A", expected_cost_per_case_usd=0.001), 400
    ) == pytest.approx(0.4)
    refuse_over_budget(1.0, 20.0, 25.0)
    with pytest.raises(BudgetError):
        refuse_over_budget(6.0, 20.0, 25.0)


def test_heldout_run_appends_ledger_row(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE] * 2)
    r = runner(tmp_path, client)
    r.run(
        RunSpec(sample="heldout-40", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert (tmp_path / "ledger.md").read_text().count("| heldout-40 |") == 1


def test_case_number_probe_included_on_a_development_sample_and_case(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = record_fixtures[0]
    case_id = str(raw["ntsbNumber"])
    spec = RunSpec(sample="dev-400", arm="ceiling", include_case_number=True)
    _, system, _, _ = case_payload(raw, spec, load_tables())
    assert case_id in system


def test_sync_case_that_abstains_skips_stage_two(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([ABSTAIN])
    run = runner(tmp_path, client).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(client.payloads) == 1  # no stage-2 turn
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is None
    assert case.scores is not None
    assert case.scores.abstained


def test_sync_stage_two_schema_failure_is_retried_once_then_recorded(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, "not json", "still not json"])
    run = runner(tmp_path, client).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema")
    assert case.scores is None
    assert case.cost_usd >= 0.0  # replies made before the failure are still priced


class _RaisingClient:
    """A ModelClient stand-in that always raises ModelError, as a client does after retries."""

    def complete(
        self,
        payload: object,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        raise ModelError("upstream exhausted its retries")


def test_sync_model_error_is_recorded_without_a_retry(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    run = runner(tmp_path, _RaisingClient()).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=True, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("model:")
    assert case.scores is None


def test_batch_run_without_a_batch_client_is_refused(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    with pytest.raises(ConfigurationError, match="batch client"):
        runner(tmp_path, RecordingFakeClient([]), batch=None).run(
            RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
            record_fixtures[:1],
        )


# --- the batch path (controller resolution 2: tested here, not deferred to Task 13) ---


def _batch_result(
    request: BatchRequest, content: str | None, *, error: str | None = None
) -> BatchResult:
    if error is not None:
        return BatchResult(custom_id=request.custom_id, reply=None, error=error)
    return BatchResult(
        custom_id=request.custom_id,
        reply=ModelReply(
            content=content,
            usage=Usage(prompt_tokens=100, completion_tokens=50),
            model=request.settings.model_id(),
            response_id="fake",
        ),
        error=None,
    )


def _status(
    batch_id: str,
    requests: Sequence[BatchRequest],
    content: str | None,
    *,
    reported_cost: float | None = None,
    status: str = "completed",
) -> BatchStatus:
    return BatchStatus(
        batch_id=batch_id,
        status=status,
        results=tuple(_batch_result(r, content) for r in requests),
        reported_cost_usd=reported_cost,
    )


@dataclass
class FakeBatchClient:
    """A scripted BatchClient stand-in: one handler per submit/wait pair, called in order."""

    handlers: list[Callable[[str, Sequence[BatchRequest]], BatchStatus]]
    submitted: list[list[BatchRequest]] = field(default_factory=list)
    waited: list[str] = field(default_factory=list)
    _pending: dict[str, list[BatchRequest]] = field(default_factory=dict)

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        batch_id = f"b{len(self.submitted) + 1}"
        self.submitted.append(list(requests))
        self._pending[batch_id] = list(requests)
        return batch_id

    def wait(
        self, batch_id: str, *, on_status: Callable[[str], None] = lambda _s: None
    ) -> BatchStatus:
        self.waited.append(batch_id)
        on_status("completed")
        handler = self.handlers[len(self.waited) - 1]
        return handler(batch_id, self._pending[batch_id])


def test_batch_run_submits_two_batches_with_every_case_custom_id(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ]
    )
    cases = record_fixtures[:2]
    ids = {str(raw["ntsbNumber"]) for raw in cases}
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        cases,
    )
    assert [{r.custom_id for r in batch} for batch in fake.submitted] == [ids, ids]
    assert run.batch_ids == ("b1", "b2")
    assert run.reported_batch_cost_usd == pytest.approx(0.03)
    folder = tmp_path / "runs" / run.run_id
    result_cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert len(result_cases) == 2
    assert all(c.scores is not None and c.failure is None for c in result_cases)


def test_batch_case_that_abstains_skips_stage_two(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(handlers=[lambda bid, reqs: _status(bid, reqs, ABSTAIN)])
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(fake.submitted) == 1
    assert run.batch_ids == ("b1",)
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is None
    assert case.scores is not None
    assert case.scores.abstained


def test_batch_case_with_no_findings_skips_stage_two(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    no_findings = json.dumps(
        {
            "evidence_narrative": "n",
            "probable_cause": "p",
            "lay_explanation": "l",
            "confidence": 0.4,
            "abstain": False,
            "evidence_used": [],
            "occurrence": [{"phase": "552", "event": "230", "probability": 0.4}],
            "findings": [],
        }
    )
    fake = FakeBatchClient(handlers=[lambda bid, reqs: _status(bid, reqs, no_findings)])
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(fake.submitted) == 1
    assert run.batch_ids == ("b1",)


def test_batch_per_case_cost_priced_at_the_batch_price(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(handlers=[lambda bid, reqs: _status(bid, reqs, ABSTAIN)])
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    expected = 100 * 0.10 / 1e6 + 50 * 0.60 / 1e6  # Luna batch price, sources.py
    assert case.cost_usd == pytest.approx(expected)


def test_batch_reply_with_no_content_is_retried_once_then_recorded_as_model_failure(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: BatchStatus(
                batch_id=bid,
                status="completed",
                results=tuple(
                    BatchResult(custom_id=r.custom_id, reply=None, error="upstream timeout")
                    for r in reqs
                ),
                reported_cost_usd=None,
            ),
            lambda bid, reqs: BatchStatus(
                batch_id=bid,
                status="completed",
                results=tuple(
                    BatchResult(custom_id=r.custom_id, reply=None, error="upstream timeout")
                    for r in reqs
                ),
                reported_cost_usd=None,
            ),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(fake.submitted) == 2
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("model:")
    assert case.scores is None


def test_batch_reply_that_fails_schema_is_retried_once_then_recorded(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, "not json"),
            lambda bid, reqs: _status(bid, reqs, "still not json"),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(fake.submitted) == 2
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema")
    assert case.scores is None


def test_batch_ending_failed_raises_model_error_naming_the_batch_id(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: BatchStatus(
                batch_id=bid, status="failed", results=(), reported_cost_usd=None
            )
        ]
    )
    with pytest.raises(ModelError, match="b1"):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
            RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
            record_fixtures[:1],
        )


def test_batch_records_batch_ids_before_waiting(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    folder = tmp_path / "runs" / run.run_id
    lines = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [row["stage"] for row in lines] == ["stage1", "stage2"]
    assert [row["batch_id"] for row in lines] == ["b1", "b2"]


def test_batch_writes_the_same_three_files_as_sync(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    folder = tmp_path / "runs" / run.run_id
    assert (folder / "cases.jsonl").exists()
    assert (folder / "steps.jsonl").exists()
    assert (folder / "run.jsonl").exists()


def test_batch_all_cases_over_cap_makes_no_batch_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(handlers=[])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=False,
        cap_usd=0.0000001,
        expected_cost_per_case_usd=0.0,
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(spec, record_fixtures[:1])
    assert fake.submitted == []
    assert run.batch_ids == ()
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure == "cap"


def test_batch_stage1_retry_recovers_and_the_case_still_completes(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, "not json"),
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert run.batch_ids == ("b1", "b2", "b3")
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is None
    assert case.scores is not None


def test_batch_stage_two_schema_failure_is_retried_once_then_recorded(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, "not json"),
            lambda bid, reqs: _status(bid, reqs, "still not json"),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert run.batch_ids == ("b1", "b2", "b3")
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema")
    assert case.scores is None


def test_batch_stage_two_no_reply_is_retried_once_then_recorded_as_model_failure(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    def _no_reply(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(
            batch_id=bid,
            status="completed",
            results=tuple(
                BatchResult(custom_id=r.custom_id, reply=None, error="upstream timeout")
                for r in reqs
            ),
            reported_cost_usd=None,
        )

    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            _no_reply,
            _no_reply,
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert run.batch_ids == ("b1", "b2", "b3")
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("model:")
    assert case.scores is None
