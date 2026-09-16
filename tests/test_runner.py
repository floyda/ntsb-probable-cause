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
    BatchRunner,
    Runner,
    RunSpec,
    _BatchRun,
    case_payload,
    project_cost,
    refuse_over_budget,
    spec_json,
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
    batch: BatchRunner | None = None,
    *,
    dirty: bool = False,
) -> Runner:
    return Runner(
        client,
        batch=batch,
        tables=load_tables(),
        seen_pairs=frozenset({"552230"}),
        runs_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.md",
        month_spent_usd=spent,
        commit=("abc1234", dirty),
        now=lambda: datetime(2026, 9, 15, tzinfo=UTC),
    )


def _run_id(sample: str = "dev-400", arm: str = "ceiling") -> str:
    """The deterministic run id every test's fixed ``now``/commit produce, given sample/arm."""
    started = datetime(2026, 9, 15, tzinfo=UTC)
    return f"{started:%Y%m%dT%H%M%S}-abc1234-{sample}-{arm}"


def test_over_cap_case_is_failed_without_a_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
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
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    run = runner(tmp_path, client).run(spec, record_fixtures)
    folder = tmp_path / "runs" / run.run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    steps = read_jsonl(folder / "steps.jsonl", StepRecord)
    assert len(cases) == len(record_fixtures)
    assert len(steps) == len(record_fixtures)
    assert all(c.scores is not None and c.failure is None for c in cases)
    assert steps[0].tool == "none"
    assert steps[0].stop_reason == "answered"
    assert read_jsonl(folder / "run.jsonl", RunRecord)[0].prompt_version == "s1-v5"
    assert len(client.payloads) == 2 * len(record_fixtures)  # two turns per case


def test_schema_failure_is_retried_once_then_recorded(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient(["not json", "still not json"] + [GOOD, REFINE] * 10)
    run = runner(tmp_path, client).run(
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        ),
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
        RunSpec(
            sample="dev-400",
            arm="A",
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        ),
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
                price_variant="standard",
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
            RunSpec(
                sample="dev-400",
                arm="ceiling",
                sync=True,
                price_variant="standard",
                expected_cost_per_case_usd=0.01,
            ),
            record_fixtures,
        )
    assert client.payloads == []


def test_sync_with_batch_price_variant_is_refused_before_any_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A sync run against the batch model id 404s on the chat-completions endpoint; caught
    before any call, the same way as the budget and dirty-tree refusals."""
    client = RecordingFakeClient([GOOD])
    with pytest.raises(ConfigurationError, match="price-variant standard"):
        runner(tmp_path, client).run(
            RunSpec(
                sample="dev-400",
                arm="ceiling",
                sync=True,
                price_variant="batch",
                expected_cost_per_case_usd=0.001,
            ),
            record_fixtures[:1],
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
        RunSpec(
            sample="heldout-40",
            arm="ceiling",
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        ),
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
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        ),
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
    """Real cost accounting (fix round 1, Important 3): ``RecordingFakeClient`` now carries
    non-zero usage per call, so this asserts the hand-computed dollar amount of all three
    calls (stage 1, plus both rejected stage-2 attempts) rather than a ``>= 0.0`` bound that
    a $0 accounting bug would also satisfy."""
    usage = [
        Usage(prompt_tokens=300, completion_tokens=40),  # stage 1 (accepted)
        Usage(prompt_tokens=150, completion_tokens=10),  # stage 2, first attempt (rejected)
        Usage(prompt_tokens=160, completion_tokens=12),  # stage 2, retry (also rejected)
    ]
    client = RecordingFakeClient([GOOD, "not json", "still not json"], usage=usage)
    run = runner(tmp_path, client).run(
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        ),
        record_fixtures[:1],
    )
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema")
    assert case.scores is None
    # Luna standard price (sources.py): $0.20 / M input tokens, $1.20 / M output tokens.
    # A sync run cannot use the batch price variant (it 404s on chat-completions), so this
    # test, run sync, prices at the standard rate rather than the batch rate.
    expected = sum((u.prompt_tokens * 0.20 + u.completion_tokens * 1.20) / 1e6 for u in usage)
    assert case.cost_usd == pytest.approx(expected)


def test_sync_cost_reflects_both_replies_when_the_retry_succeeds(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A stage-1 schema failure followed by a successful retry must price BOTH calls, by
    hand-computed dollars (fix round 1, Important 3), and the totals must roll up correctly:
    RunRecord.cost_usd is the sum over its (one) case, and the one StepRecord's
    cumulative_cost_usd matches too."""
    usage = [
        Usage(prompt_tokens=200, completion_tokens=20),  # stage 1, rejected
        Usage(prompt_tokens=210, completion_tokens=5),  # stage 1, retry — accepted, abstains
    ]
    client = RecordingFakeClient(["not json", ABSTAIN], usage=usage)
    run = runner(tmp_path, client).run(
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        ),
        record_fixtures[:1],
    )
    # Luna standard price (sources.py): $0.20 / M input tokens, $1.20 / M output tokens.
    # A sync run cannot use the batch price variant (it 404s on chat-completions), so this
    # test, run sync, prices at the standard rate rather than the batch rate.
    expected = sum((u.prompt_tokens * 0.20 + u.completion_tokens * 1.20) / 1e6 for u in usage)
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    (step,) = read_jsonl(folder / "steps.jsonl", StepRecord)
    assert case.failure is None
    assert case.cost_usd == pytest.approx(expected)
    assert step.cumulative_cost_usd == pytest.approx(expected)
    assert run.cost_usd == pytest.approx(expected)  # RunRecord sums over its one case


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
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        ),
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
    """A scripted BatchClient stand-in: one handler per submit/wait pair, called in order.

    ``preloaded`` stands for batches the provider already holds from an earlier, dead run:
    a resume waits on such an id without ever submitting it, so the fake needs the requests
    from somewhere other than its own ``submit``. ``prefix`` keeps a resumed run's freshly
    minted ids from colliding with the dead run's.
    """

    handlers: list[Callable[[str, Sequence[BatchRequest]], BatchStatus]]
    submitted: list[list[BatchRequest]] = field(default_factory=list)
    waited: list[str] = field(default_factory=list)
    prefix: str = "b"
    preloaded: dict[str, list[BatchRequest]] = field(default_factory=dict)
    _pending: dict[str, list[BatchRequest]] = field(default_factory=dict)

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        batch_id = f"{self.prefix}{len(self.submitted) + 1}"
        self.submitted.append(list(requests))
        self._pending[batch_id] = list(requests)
        return batch_id

    def wait(
        self, batch_id: str, *, on_status: Callable[[str], None] = lambda _s: None
    ) -> BatchStatus:
        self.waited.append(batch_id)
        on_status("completed")
        handler = self.handlers[len(self.waited) - 1]
        known = {**self.preloaded, **self._pending}
        return handler(batch_id, known[batch_id])  # KeyError on an id from nowhere


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
    # Both attempts carry the fixture's 100/50-token usage (fix round 1, Important 3): a
    # failed case's priced cost, not just its non-negativity.
    expected = 2 * (100 * 0.10 + 50 * 0.60) / 1e6
    assert case.cost_usd == pytest.approx(expected)


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
    """Fix round 1, Minor 6: the fake's own ``wait`` asserts the id is already on disk when
    it is called, so this actually tests the ordering (record-before-wait), not just the
    end state — which would pass even if the write happened after every batch finished."""
    folder = tmp_path / "runs" / _run_id()

    def stage1(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        assert f'"batch_id": "{bid}"' in (folder / "batches.jsonl").read_text()
        return _status(bid, reqs, GOOD, reported_cost=0.01)

    def stage2(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        assert f'"batch_id": "{bid}"' in (folder / "batches.jsonl").read_text()
        return _status(bid, reqs, REFINE, reported_cost=0.02)

    fake = FakeBatchClient(handlers=[stage1, stage2])
    runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    lines = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [row["stage"] for row in lines] == ["stage1", "stage2"]
    assert [row["batch_id"] for row in lines] == ["b1", "b2"]


def test_batch_status_goes_to_stderr_not_stdout(
    tmp_path: Path, record_fixtures: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1, Minor 7: ``on_status`` writes to stderr only (controller resolution 7)."""
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ]
    )
    runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "stage1" in captured.err
    assert "stage2" in captured.err


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
    # Three calls (rejected stage-1 attempt, accepted retry, stage-2), each the fixture's
    # 100/50-token usage (fix round 1, Important 3).
    expected = 3 * (100 * 0.10 + 50 * 0.60) / 1e6
    assert case.cost_usd == pytest.approx(expected)
    # The first batch reported no cost at all, so the total is honestly unknown, not a
    # partial sum presented as the whole (fix round 1, Minor 4).
    assert run.reported_batch_cost_usd is None


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


def test_batch_stage2_retry_replays_the_stage1_content_not_the_rejected_reply(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 1, Important 1: on a stage-2 retry batch, the assistant history must carry
    the accepted stage-1 reply (GOOD), never the rejected first stage-2 attempt's text."""
    captured_history: list[tuple[Turn, ...]] = []

    def stage2_first(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        captured_history.append(reqs[0].history)
        return _status(bid, reqs, "not json")  # rejected: forces a stage-2 retry batch

    def stage2_retry(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        captured_history.append(reqs[0].history)
        return _status(bid, reqs, REFINE, reported_cost=0.02)

    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            stage2_first,
            stage2_retry,
        ]
    )
    runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(captured_history) == 2
    for history in captured_history:
        assert history[0].content == GOOD


def test_batch_stage1_retry_records_its_own_error_not_pass_ones(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 1, Minor 5: a case that fails schema on the first stage-1 attempt but then
    fails with a model error on retry must be filed as ``model: ...``, not ``schema: ...``
    from the first attempt."""

    def retry_no_reply(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(
            batch_id=bid,
            status="completed",
            results=tuple(
                BatchResult(custom_id=r.custom_id, reply=None, error="retry-specific failure")
                for r in reqs
            ),
            reported_cost_usd=None,
        )

    fake = FakeBatchClient(
        handlers=[lambda bid, reqs: _status(bid, reqs, "not json"), retry_no_reply]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    folder = tmp_path / "runs" / run.run_id
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("model:")
    assert "retry-specific failure" in case.failure
    assert "schema" not in case.failure


def test_batch_abort_on_stage_two_failure_still_records_stage_one_spend(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 1, Important 2: a stage-2 batch that ends ``expired`` after the stage-1
    batch was billed must not make that stage-1 spend invisible — cases.jsonl/run.jsonl are
    still written, with the accrued cost, before the ModelError is re-raised."""
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: BatchStatus(
                batch_id=bid, status="expired", results=(), reported_cost_usd=None
            ),
        ]
    )
    with pytest.raises(ModelError, match="expired"):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
            RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
            record_fixtures[:1],
        )
    folder = tmp_path / "runs" / _run_id()
    (record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    assert record.finished is None
    expected_stage1_cost = 100 * 0.10 / 1e6 + 50 * 0.60 / 1e6  # the billed stage-1 reply
    assert record.cost_usd == pytest.approx(expected_stage1_cost)
    # Batch 2 never completed, so its cost is honestly unknown, not a one-batch sum
    # (0.01) presented as the two-batch total (fix round 2, Minor 2).
    assert record.reported_batch_cost_usd is None
    # The failing batch's id is still on record, even though it never completed.
    assert record.batch_ids == ("b1", "b2")
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("aborted:")
    assert case.cost_usd == pytest.approx(expected_stage1_cost)


def test_batch_keyboard_interrupt_during_wait_still_records_stage_one_spend(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 2, Minor 1: a Ctrl-C during a real batch's ``wait`` (which polls for a long
    time on a real run) is the most likely real mid-run abort. ``except Exception`` would
    not catch ``KeyboardInterrupt``, leaving the billed stage-1 spend invisible to the next
    run's budget guard; ``run()`` and ``_answer_batch`` now catch ``BaseException``."""

    def stage2_interrupt(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise KeyboardInterrupt

    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            stage2_interrupt,
        ]
    )
    with pytest.raises(KeyboardInterrupt):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
            RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
            record_fixtures[:1],
        )
    folder = tmp_path / "runs" / _run_id()
    (record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    assert record.finished is None
    expected_stage1_cost = 100 * 0.10 / 1e6 + 50 * 0.60 / 1e6  # the billed stage-1 reply
    assert record.cost_usd == pytest.approx(expected_stage1_cost)
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("aborted:")
    assert case.cost_usd == pytest.approx(expected_stage1_cost)


# --- resume: a run continues from the batches it already paid for (0032) ---


BATCH_SPEC = RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001)


class _ExplodingBatchClient:
    """A batch client that dies on its first submit: nothing is called, nothing is paid for."""

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        raise RuntimeError("the provider was unreachable")

    def wait(
        self, batch_id: str, *, on_status: Callable[[str], None] = lambda _s: None
    ) -> BatchStatus:
        raise AssertionError("never reached")


def _died_waiting_on_stage1(tmp_path: Path, raws: Sequence[dict[str, object]]) -> FakeBatchClient:
    """A batch run whose stage-1 batch was submitted and recorded, then lost its waiter.

    The real incident decision 0032 was written for: the process was killed while sitting in
    ``wait``, so the provider went on to complete (and bill) a batch nobody read.
    """

    def die(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise ModelError("the waiter died")

    fake = FakeBatchClient(handlers=[die])
    with pytest.raises(ModelError, match="waiter died"):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(BATCH_SPEC, raws)
    return fake


def _resume_after_stage1_death(
    tmp_path: Path, raws: Sequence[dict[str, object]]
) -> tuple[RunRecord, FakeBatchClient]:
    """Kill a run in its stage-1 wait, then resume it; the stage-1 batch is there to reuse."""
    dead = _died_waiting_on_stage1(tmp_path, raws)
    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),  # the reused batch
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),  # a fresh stage 2
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, raws, resume=_run_id()
    )
    return record, resumed


def test_resume_waits_on_the_recorded_batch_instead_of_submitting_it_again(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """0032 point 3: the stage with a recorded id skips the submit; stage 2 still submits."""
    record, resumed = _resume_after_stage1_death(tmp_path, record_fixtures[:1])
    assert resumed.waited == ["b1", "c1"]  # the paid batch first, then the fresh one
    assert len(resumed.submitted) == 1  # stage 1 was never submitted a second time
    assert resumed.submitted[0][0].settings.schema_name == "refinement"  # it was stage 2
    assert record.batch_ids == ("b1", "c1")
    assert record.finished is not None
    assert record.cases == 1


def test_resume_scores_the_reused_batch_replies(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The point of the exercise: the replies the dead run paid for produce the answers."""
    record, _ = _resume_after_stage1_death(tmp_path, record_fixtures[:1])
    cases = read_jsonl(tmp_path / "runs" / _run_id() / "cases.jsonl", CaseResult)
    finished = [case for case in cases if case.failure is None]
    assert len(finished) == 1
    assert finished[0].scores is not None
    # Two replies at the fixture's 100/50-token usage: the reused stage-1 one and stage 2.
    assert finished[0].cost_usd == pytest.approx(2 * (100 * 0.10 + 50 * 0.60) / 1e6)
    assert record.cost_usd == pytest.approx(finished[0].cost_usd)


def test_resume_sets_the_dead_runs_result_files_aside_and_writes_clean_ones(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The resumed run is the same run, so its folder holds one set of results, not two.

    ``write_jsonl`` appends; without this the aborted rows would sit in front of the
    resumed run's, double-counting the spend and leaving ``run.jsonl``'s first row —
    the one ``report`` reads — saying the run never finished.
    """
    folder = tmp_path / "runs" / _run_id()
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    assert read_jsonl(folder / "cases.jsonl", CaseResult)[0].failure is not None
    # An earlier recovery attempt already parked one set aside: the next is numbered 2.
    (folder / "cases.aborted-1.jsonl").write_text("")
    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is None
    (record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    assert record.finished is not None
    # Nothing was destroyed: the dead run's own rows are still there to read.
    assert read_jsonl(folder / "cases.aborted-2.jsonl", CaseResult)[0].failure is not None
    assert read_jsonl(folder / "run.aborted-1.jsonl", RunRecord)[0].finished is None
    assert (folder / "steps.aborted-1.jsonl").exists()


def test_resume_counts_the_reused_batchs_reported_cost(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Money already spent stays visible: the reused batch reports its cost like a fresh one."""
    record, _ = _resume_after_stage1_death(tmp_path, record_fixtures[:1])
    assert record.reported_batch_cost_usd == pytest.approx(0.03)  # 0.01 reused + 0.02 fresh


def test_resume_appends_no_second_row_for_the_reused_batch(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A reused id is already in ``batches.jsonl``; recording it again would double-count it."""
    _resume_after_stage1_death(tmp_path, record_fixtures[:1])
    path = tmp_path / "runs" / _run_id() / "batches.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(row["stage"], row["batch_id"]) for row in rows] == [("stage1", "b1"), ("stage2", "c1")]


def test_spec_json_is_written_before_the_first_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """0032 point 1: a folder that dies before its first batch still describes itself."""
    with pytest.raises(RuntimeError, match="unreachable"):
        runner(tmp_path, RecordingFakeClient([]), batch=_ExplodingBatchClient()).run(
            BATCH_SPEC, record_fixtures[:1]
        )
    recorded = json.loads((tmp_path / "runs" / _run_id() / "spec.json").read_text())
    assert recorded["sample"] == "dev-400"
    assert recorded["arm"] == "ceiling"
    assert recorded["model"] == BATCH_SPEC.model
    assert recorded["prompt_version"] == "s1-v5"
    assert recorded["commit_sha"] == "abc1234"
    assert recorded["dirty"] is False  # a dirty tree means the code is not the sha
    assert recorded["case_ids"] == [str(record_fixtures[0]["ntsbNumber"])]


def test_resume_consumes_recorded_batches_by_stage_and_in_order(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The queue discipline itself: four stages, four recorded ids, each taken once.

    Every other resume test records a single batch, where "the first row matching this
    stage" and "the only row" are indistinguishable. Here the dead run recorded three rows
    across three different stages, so a reuse that matched the last row, ignored the stage,
    or forgot to consume the row it used would score the wrong replies against the case --
    the most expensive thing this feature could get silently wrong. The fourth stage has no
    recorded row, so it also pins where the queue runs dry and a fresh submit takes over.
    """

    def die(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise ModelError("the waiter died")

    dead = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, "not json"),  # stage1     -> b1, rejected
            lambda bid, reqs: _status(bid, reqs, GOOD),  # stage1-retry     -> b2, accepted
            die,  # stage2                                                  -> b3, never read
        ]
    )
    with pytest.raises(ModelError, match="waiter died"):
        runner(tmp_path, RecordingFakeClient([]), batch=dead).run(BATCH_SPEC, record_fixtures[:1])
    folder = tmp_path / "runs" / _run_id()
    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [(row["stage"], row["batch_id"]) for row in rows] == [
        ("stage1", "b1"),
        ("stage1-retry", "b2"),
        ("stage2", "b3"),
    ]

    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, "not json"),  # b1 replayed: same rejection
            lambda bid, reqs: _status(bid, reqs, GOOD),  # b2 replayed: the accepted stage 1
            lambda bid, reqs: _status(bid, reqs, "not json"),  # b3, read at last: rejected
            lambda bid, reqs: _status(bid, reqs, REFINE),  # stage2-retry: nothing recorded
        ],
        prefix="c",
        preloaded={f"b{n + 1}": batch for n, batch in enumerate(dead.submitted)},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    # Each recorded id waited on once, in the order the stages run; only the stage with no
    # recorded row was paid for again.
    assert resumed.waited == ["b1", "b2", "b3", "c1"]
    assert len(resumed.submitted) == 1
    assert resumed.submitted[0][0].settings.schema_name == "refinement"
    assert record.batch_ids == ("b1", "b2", "b3", "c1")
    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [(row["stage"], row["batch_id"]) for row in rows] == [
        ("stage1", "b1"),
        ("stage1-retry", "b2"),
        ("stage2", "b3"),
        ("stage2-retry", "c1"),  # the only new row: the three reused ids were already there
    ]
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is None
    assert case.scores is not None


def test_resume_refuses_a_reused_batch_that_answers_different_cases(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The replay assumption, checked against what the provider actually holds.

    If the recorded batch's replies do not cover the cases this pass replayed, the requests
    were not reproduced, and carrying on would score replies against the wrong records and
    pay for a retry batch covering the difference.
    """
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])

    def answers_someone_else(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        other = BatchRequest(
            custom_id="NOT-THIS-CASE",
            payload=reqs[0].payload,
            settings=reqs[0].settings,
            system=reqs[0].system,
        )
        return _status(bid, [other], GOOD, reported_cost=0.01)

    resumed = FakeBatchClient(
        handlers=[answers_someone_else], prefix="c", preloaded={"b1": dead.submitted[0]}
    )
    with pytest.raises(ConfigurationError, match="recorded batch b1 answers"):
        runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert resumed.submitted == []  # refused rather than quietly retried at full price


def test_resume_refuses_a_run_that_already_finished(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A mis-pasted completed run id passes every other check and would undo the result."""
    complete = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ]
    )
    runner(tmp_path, RecordingFakeClient([]), batch=complete).run(BATCH_SPEC, record_fixtures[:1])
    folder = tmp_path / "runs" / _run_id()
    other = FakeBatchClient(handlers=[])
    with pytest.raises(ConfigurationError, match="already finished at"):
        runner(tmp_path, RecordingFakeClient([]), batch=other).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert other.submitted == []
    # The finished run is untouched: nothing was set aside, nothing was rewritten.
    assert not (folder / "cases.aborted-1.jsonl").exists()
    assert read_jsonl(folder / "run.jsonl", RunRecord)[0].finished is not None


def test_resume_refuses_a_half_written_batches_line(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A killed process is what leaves a truncated line, and this is the file resume reads."""
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    path = tmp_path / "runs" / _run_id() / "batches.jsonl"
    path.write_text(path.read_text() + '{"batch_id": "b2", "stage": "stage')
    with pytest.raises(ConfigurationError, match="line 2 is not readable JSON"):
        runner(tmp_path, RecordingFakeClient([]), batch=FakeBatchClient(handlers=[])).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )


def test_resume_refuses_a_batches_line_that_records_no_batch(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    path = tmp_path / "runs" / _run_id() / "batches.jsonl"
    intact = path.read_text()
    path.write_text(intact + '{"time": "2026-09-16T00:00:00"}\n')
    with pytest.raises(ConfigurationError, match="records no stage and batch id"):
        runner(tmp_path, RecordingFakeClient([]), batch=FakeBatchClient(handlers=[])).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    path.write_text(intact + '"a bare string, not a row"\n')
    with pytest.raises(ConfigurationError, match="line 2 does not hold a JSON object"):
        runner(tmp_path, RecordingFakeClient([]), batch=FakeBatchClient(handlers=[])).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )


def test_recorded_batches_are_taken_by_stage_and_consumed_one_at_a_time() -> None:
    """The queue rule on its own, including the case a whole-run test cannot reach.

    A batch replays deterministically, so in practice the head of the queue is always the
    stage being asked for. This pins what happens when it is not -- a row for another stage
    must never be handed out, and a stage with no row must fall through to a fresh submit --
    because "first not-yet-consumed row whose stage matches" is the rule the reuse rests on,
    not an accident of the order batches happen to be recorded in.
    """
    run = _BatchRun(folder=Path("unused"), reusable=[("stage1", "b1"), ("stage2", "b2")])
    assert Runner._take_reusable(run, "stage2") == "b2"  # looks past the stage1 row
    assert run.reusable == [("stage1", "b1")]  # and consumes only the row it used
    assert Runner._take_reusable(run, "stage1-retry") is None  # no row: submit normally
    assert run.reusable == [("stage1", "b1")]
    assert Runner._take_reusable(run, "stage1") == "b1"
    assert Runner._take_reusable(run, "stage1") is None  # consumed: never handed out twice
    assert run.reusable == []


def test_resume_refuses_a_dirty_tree_against_a_clean_one(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A dirty tree means the code is not the sha, so the sha alone cannot vouch for it."""
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    other = FakeBatchClient(handlers=[])
    with pytest.raises(ConfigurationError, match="dirty was False"):
        runner(tmp_path, RecordingFakeClient([]), batch=other, dirty=True).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert other.submitted == []


def test_resume_of_a_run_that_died_before_its_first_submit_runs_every_stage(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Nothing recorded, nothing to reuse: a stage with no recorded id is submitted normally."""
    with pytest.raises(RuntimeError, match="unreachable"):
        runner(tmp_path, RecordingFakeClient([]), batch=_ExplodingBatchClient()).run(
            BATCH_SPEC, record_fixtures[:1]
        )
    folder = tmp_path / "runs" / _run_id()
    assert not (folder / "batches.jsonl").exists()
    # The real incident's folder shape: a SIGKILL bypasses the abort path, so some of the
    # result files a normal abort leaves behind are simply not there to set aside.
    (folder / "run.jsonl").unlink()
    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),
        ]
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert len(resumed.submitted) == 2  # both stages paid for, none reused
    assert record.batch_ids == ("b1", "b2")
    assert record.finished is not None


def test_resume_refuses_a_spec_json_that_is_not_a_readable_object(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A damaged record is refused like a missing one: it cannot prove the run is the same."""
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    path = tmp_path / "runs" / _run_id() / "spec.json"
    fake = FakeBatchClient(handlers=[])
    path.write_text("{not json at all")
    with pytest.raises(ConfigurationError, match="not readable JSON"):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    path.write_text("[]")
    with pytest.raises(ConfigurationError, match="JSON object"):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    recorded = spec_json(BATCH_SPEC, commit_sha="abc1234", dirty=False, case_ids=["anything"])
    recorded["case_ids"] = "not a list at all"
    path.write_text(json.dumps(recorded))
    with pytest.raises(ConfigurationError, match="not a list of case ids"):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert fake.submitted == []


def test_resume_refuses_a_different_arm(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """0032 point 4: replies bought under one configuration never answer for another."""
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    other = FakeBatchClient(handlers=[])
    with pytest.raises(ConfigurationError, match="arm"):
        runner(tmp_path, RecordingFakeClient([]), batch=other).run(
            RunSpec(sample="dev-400", arm="A", sync=False, expected_cost_per_case_usd=0.001),
            record_fixtures[:1],
            resume=_run_id(),
        )
    assert other.submitted == []


def test_resume_refuses_a_different_model(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    other = FakeBatchClient(handlers=[])
    with pytest.raises(ConfigurationError, match="model"):
        runner(tmp_path, RecordingFakeClient([]), batch=other).run(
            RunSpec(
                sample="dev-400",
                arm="ceiling",
                sync=False,
                model="anthropic/claude-sonnet-5",
                expected_cost_per_case_usd=0.001,
            ),
            record_fixtures[:1],
            resume=_run_id(),
        )
    assert other.submitted == []


def test_resume_refuses_a_different_case_list(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """What makes ``--limit`` safe: a different number of cases is a different request set.

    The message is counts and the first differing index, never the two lists: on
    ``dev-400`` those are 401 ids each, and a refusal nobody can read is one an operator
    works around instead of acting on.
    """
    _died_waiting_on_stage1(tmp_path, record_fixtures[:2])
    other = FakeBatchClient(handlers=[])
    with pytest.raises(ConfigurationError) as excinfo:
        runner(tmp_path, RecordingFakeClient([]), batch=other).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    message = str(excinfo.value)
    assert "case_ids: the run recorded 2 case ids and this one has 1" in message
    assert "index 1" in message
    assert repr(str(record_fixtures[1]["ntsbNumber"])) in message  # the id that went missing
    assert "None" in message  # and nothing in its place
    assert other.submitted == []


def test_resume_refuses_a_case_list_of_the_same_length_in_a_different_order(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Same count, different run: the first differing index is what names it."""
    _died_waiting_on_stage1(tmp_path, record_fixtures[:2])
    other = FakeBatchClient(handlers=[])
    with pytest.raises(ConfigurationError) as excinfo:
        runner(tmp_path, RecordingFakeClient([]), batch=other).run(
            BATCH_SPEC, list(reversed(record_fixtures[:2])), resume=_run_id()
        )
    message = str(excinfo.value)
    assert "recorded 2 case ids and this one has 2" in message
    assert "index 0" in message
    assert other.submitted == []


def test_resume_is_refused_alongside_sync(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A sync run records no batches, so a ``--sync`` resume would silently re-buy the lot."""
    client = RecordingFakeClient([GOOD, REFINE])
    with pytest.raises(ConfigurationError, match="no batches to resume from"):
        runner(tmp_path, client).run(
            RunSpec(
                sample="dev-400",
                arm="ceiling",
                sync=True,
                price_variant="standard",
                expected_cost_per_case_usd=0.001,
            ),
            record_fixtures[:1],
            resume=_run_id(),
        )
    assert client.payloads == []


def test_resume_refuses_a_folder_written_before_the_spec_was_recorded(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """0032 point 5: no ``spec.json``, nothing to check against, so no resume."""
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    (tmp_path / "runs" / _run_id() / "spec.json").unlink()
    with pytest.raises(ConfigurationError, match=r"spec\.json is missing"):
        runner(tmp_path, RecordingFakeClient([]), batch=FakeBatchClient(handlers=[])).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )


def test_resume_refuses_a_folder_that_does_not_exist(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    with pytest.raises(ConfigurationError, match="no run folder"):
        runner(tmp_path, RecordingFakeClient([]), batch=FakeBatchClient(handlers=[])).run(
            BATCH_SPEC, record_fixtures[:1], resume="20260101T000000-abc1234-dev-400-ceiling"
        )
