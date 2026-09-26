"""The runner: sync and batch answering passes, the cap, the budget (spec §6)."""

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from tests.test_attach import _docket as small_docket
from tests.test_marks import FACTUAL, S1, S2

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.docket.transcribe import (
    ReadingLookup,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
)
from ntsb_probable_cause.errors import (
    BatchNotFoundError,
    BudgetError,
    ConfigurationError,
    LeakageError,
    ModelError,
)
from ntsb_probable_cause.fields import EvidenceRole, factual_narrative
from ntsb_probable_cause.model.batch import BatchCounts, BatchRequest, BatchResult, BatchStatus
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
from ntsb_probable_cause.scoring.budget import (
    RESERVATION_FILE,
    month_spent,
    open_reservations,
    reserve,
)
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, read_jsonl
from ntsb_probable_cause.scoring.runner import (
    ANSWERING_TURNS,
    BatchRunner,
    CachedDocketReader,
    DocketReader,
    Runner,
    RunSpec,
    _BatchRun,
    case_payload,
    dead_batches,
    estimated_cost_usd,
    over_cap,
    prepare_case,
    project_cost,
    recorded_batches,
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


def runner(  # noqa: PLR0913 -- every parameter is a seam a test needs.
    tmp_path: Path,
    client: ModelClient,
    spent: float = 0.0,
    batch: BatchRunner | None = None,
    *,
    dirty: bool = False,
    now: Callable[[], datetime] = lambda: datetime(2026, 9, 15, tzinfo=UTC),
    docket: DocketReader | None = None,
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
        now=now,
        docket=docket,
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


def test_case_number_probe_refused_off_dev_on_the_batch_path(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix finding 4 is scoped to arm B: a non-arm-B ``LeakageError`` still aborts the whole
    run, on the batch path (``_prepare_contexts``) just as it does on the sync path above."""
    with pytest.raises(LeakageError, match="case number"):
        runner(tmp_path, RecordingFakeClient([])).run(
            RunSpec(
                sample="heldout-40",
                arm="ceiling",
                sync=False,
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
                budget_usd=25.0,
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
            model="openai/gpt-5.6-luna",
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
            model="openai/gpt-5.6-luna",
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


def _status(  # noqa: PLR0913 -- every parameter is a seam a test needs.
    batch_id: str,
    requests: Sequence[BatchRequest],
    content: str | None,
    *,
    reported_cost: float | None = None,
    status: str = "completed",
    counts: BatchCounts | None = None,
) -> BatchStatus:
    return BatchStatus(
        batch_id=batch_id,
        status=status,
        results=tuple(_batch_result(r, content) for r in requests),
        reported_cost_usd=reported_cost,
        counts=counts if counts is not None else BatchCounts(None, None, None),
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
        self, batch_id: str, *, on_status: Callable[[BatchStatus], None] = lambda _s: None
    ) -> BatchStatus:
        self.waited.append(batch_id)
        handler = self.handlers[len(self.waited) - 1]
        known = {**self.preloaded, **self._pending}
        status = handler(batch_id, known[batch_id])  # KeyError on an id from nowhere
        on_status(status)
        return status


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
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=False,
            model="openai/gpt-5.6-luna",
            expected_cost_per_case_usd=0.001,
        ),
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
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=False,
            model="openai/gpt-5.6-luna",
            expected_cost_per_case_usd=0.001,
        ),
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
        RunSpec(
            sample="dev-400",
            arm="ceiling",
            sync=False,
            model="openai/gpt-5.6-luna",
            expected_cost_per_case_usd=0.001,
        ),
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
            RunSpec(
                sample="dev-400",
                arm="ceiling",
                sync=False,
                model="openai/gpt-5.6-luna",
                expected_cost_per_case_usd=0.001,
            ),
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
            RunSpec(
                sample="dev-400",
                arm="ceiling",
                sync=False,
                model="openai/gpt-5.6-luna",
                expected_cost_per_case_usd=0.001,
            ),
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


BATCH_SPEC = RunSpec(
    sample="dev-400",
    arm="ceiling",
    sync=False,
    model="openai/gpt-5.6-luna",  # pinned: expected costs below are Luna 5.6's batch price
    expected_cost_per_case_usd=0.001,
)


class _ExplodingBatchClient:
    """A batch client that dies on its first submit: nothing is called, nothing is paid for."""

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        raise RuntimeError("the provider was unreachable")

    def wait(
        self, batch_id: str, *, on_status: Callable[[BatchStatus], None] = lambda _s: None
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


def _died_waiting_on_stage2(tmp_path: Path, raws: Sequence[dict[str, object]]) -> FakeBatchClient:
    """A batch run whose stage-1 batch completed and stage-2 batch was recorded, then lost its
    waiter -- so ``batches.jsonl`` holds one row for each stage (fix round 1's scenario)."""

    def die(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise ModelError("the waiter died")

    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD),  # stage1 completes
            die,  # stage2
        ]
    )
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


# --- resume: a batch the provider has lost is resubmitted, not retried forever (task 7b) ---


def test_recorded_batches_skips_a_batch_marked_lost_later_in_the_file(tmp_path: Path) -> None:
    """The resume queue must never hand back a dead id, or the row marking it dead."""
    folder = tmp_path / "runs" / "x"
    folder.mkdir(parents=True)
    lines = [
        {"batch_id": "b1", "stage": "stage1", "time": "2026-09-24T00:00:00"},
        {"batch_id": "b1", "stage": "stage1", "lost": True, "time": "2026-09-24T10:00:00"},
        {"batch_id": "c1", "stage": "stage1", "time": "2026-09-24T10:00:01"},
        {"batch_id": "b2", "stage": "stage2", "time": "2026-09-24T00:00:02"},
    ]
    (folder / "batches.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    assert recorded_batches(folder) == [
        ("stage1", "c1", "2026-09-24T10:00:01"),
        ("stage2", "b2", "2026-09-24T00:00:02"),
    ]


def test_resume_resubmits_a_batch_the_provider_has_lost(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The reused batch has vanished at the provider: this pass pays for it again, once,
    logs a `lost` row so a later resume never waits on it again, and otherwise completes."""
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])

    def gone(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise BatchNotFoundError(f"batch {bid}: still not found after 120s: gone")

    resumed = FakeBatchClient(
        handlers=[
            gone,  # b1 replayed: the provider has lost it
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),  # b1 resubmitted fresh
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),  # stage 2
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resumed.waited == ["b1", "c1", "c2"]  # the dead id, then a fresh stage 1, then stage 2
    assert len(resumed.submitted) == 2  # stage 1 paid for again exactly once, plus stage 2
    assert record.batch_ids == ("c1", "c2")  # the lost id never counts as one this run paid for
    assert record.finished is not None

    folder = tmp_path / "runs" / _run_id()
    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [(row["stage"], row["batch_id"], row.get("lost", False)) for row in rows] == [
        ("stage1", "b1", False),  # the dead run's original row: never deleted
        ("stage1", "b1", True),  # marks it lost
        ("stage1", "c1", False),  # the fresh replacement
        ("stage2", "c2", False),
    ]
    # A later resume's queue would never wait on the lost id again.
    assert recorded_batches(folder) == [
        ("stage1", "c1", rows[2]["time"]),
        ("stage2", "c2", rows[3]["time"]),
    ]


def test_a_freshly_submitted_batch_that_the_provider_loses_still_aborts_the_run(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """No silent re-spending within a run: only a REUSED batch is treated as recoverable.

    A batch submitted fresh in this run raising ``BatchNotFoundError`` propagates and the
    run aborts, exactly as any other ``ModelError`` would -- resubmitting automatically here
    would let one run pay for the same stage an unbounded number of times.
    """

    def gone(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise BatchNotFoundError(f"batch {bid}: still not found after 120s: gone")

    fake = FakeBatchClient(handlers=[gone])
    with pytest.raises(BatchNotFoundError):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(BATCH_SPEC, record_fixtures[:1])
    assert len(fake.submitted) == 1  # never retried automatically
    folder = tmp_path / "runs" / _run_id()
    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert rows == [{"batch_id": "b1", "stage": "stage1", "time": rows[0]["time"]}]


def test_a_lost_batch_supersedes_the_batches_recorded_after_it(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 1: stage 2's requests are built from stage 1's replies (``history``/
    ``system``), so once the stage-1 batch is found lost, the dead run's stage-2 batch is not
    a valid replay of anything either -- it must not be reused, only resubmitted fresh."""
    dead = _died_waiting_on_stage2(tmp_path, record_fixtures[:1])

    def gone(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise BatchNotFoundError(f"batch {bid}: still not found after 120s: gone")

    resumed = FakeBatchClient(
        handlers=[
            gone,  # b1 replayed: the provider has lost it
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),  # stage1, resubmitted
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),  # stage2, resubmitted
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0], "b2": dead.submitted[1]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resumed.waited == ["b1", "c1", "c2"]  # b2 is never waited on
    assert len(resumed.submitted) == 2  # both stages paid for fresh; b2 was never reused
    assert record.batch_ids == ("c1", "c2")
    assert record.finished is not None

    folder = tmp_path / "runs" / _run_id()
    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [
        (row["stage"], row["batch_id"], row.get("lost", False), row.get("superseded", False))
        for row in rows
    ] == [
        ("stage1", "b1", False, False),  # the dead run's original rows: never deleted
        ("stage2", "b2", False, False),
        ("stage2", "b2", False, True),  # marks b2 superseded: it depended on b1
        ("stage1", "b1", True, False),  # marks b1 lost -- written after its superseded rows
        ("stage1", "c1", False, False),  # the fresh replacement
        ("stage2", "c2", False, False),
    ]
    assert rows[2]["depends_on_batch_id"] == "b1"
    # A later resume's queue would wait on neither dead id again.
    assert recorded_batches(folder) == [
        ("stage1", "c1", rows[4]["time"]),
        ("stage2", "c2", rows[5]["time"]),
    ]


def test_a_superseded_batch_stays_superseded_across_a_second_resume(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The stronger case: resume #1 loses b1, resubmits it as c1, then dies again waiting on
    the freshly submitted stage-2 batch; resume #2 must reuse c1 (not b1) and never touch the
    superseded b2, proving the supersession survives past the resume that discovered it."""
    dead = _died_waiting_on_stage2(tmp_path, record_fixtures[:1])

    def gone(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise BatchNotFoundError(f"batch {bid}: still not found after 120s: gone")

    def die_again(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        raise ModelError("the waiter died again")

    resume1 = FakeBatchClient(
        handlers=[
            gone,  # b1 replayed: lost
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),  # c1: stage1, fresh
            die_again,  # c2: stage2, fresh, waiter dies again
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0], "b2": dead.submitted[1]},
    )
    with pytest.raises(ModelError, match="waiter died again"):
        runner(tmp_path, RecordingFakeClient([]), batch=resume1).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert len(resume1.submitted) == 2  # c1 and c2, neither of which was waited on to success

    resume2 = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),  # c1, reused
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.02),  # c2, reused
        ],
        prefix="d",
        preloaded={"c1": resume1.submitted[0], "c2": resume1.submitted[1]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resume2).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resume2.waited == ["c1", "c2"]  # reused, in order; b1 and b2 are never touched again
    assert resume2.submitted == []  # nothing paid for a third time
    assert record.batch_ids == ("c1", "c2")
    assert record.finished is not None


# --- resume: a batch that ended failed/expired/cancelled is resubmitted (task 9B) ---


@pytest.mark.parametrize("ended_status", ["expired", "failed", "cancelled"])
def test_resume_resubmits_a_recorded_batch_that_ended_unusable(
    tmp_path: Path, record_fixtures: list[dict[str, object]], ended_status: str
) -> None:
    """A reused batch that ran to a terminal, non-completed status has no replies left to
    reuse: it is recorded, resubmitted fresh exactly once, and the run completes."""
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])

    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, None, status=ended_status, reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.02),  # b1 resubmitted fresh
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.03),  # stage 2
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resumed.waited == ["b1", "c1", "c2"]
    assert len(resumed.submitted) == 2  # stage 1 paid for again exactly once, plus stage 2
    assert record.batch_ids == ("b1", "c1", "c2")  # the dead batch's id stays in the totals
    assert record.reported_batch_cost_usd == pytest.approx(0.01 + 0.02 + 0.03)
    assert record.finished is not None
    (case,) = read_jsonl(tmp_path / "runs" / _run_id() / "cases.jsonl", CaseResult)
    assert case.failure is None
    assert case.scores is not None

    folder = tmp_path / "runs" / _run_id()
    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [(row["stage"], row["batch_id"], row.get("ended")) for row in rows] == [
        ("stage1", "b1", None),  # the dead run's original row: never deleted
        ("stage1", "b1", ended_status),  # marks it ended
        ("stage1", "c1", None),  # the fresh replacement
        ("stage2", "c2", None),
    ]
    # Fix round 1 (review Minors 3-4): the ended row carries the dead batch's reported cost,
    # so a later resume can add it back into RunRecord.cost_usd.
    assert rows[1]["reported_cost_usd"] == pytest.approx(0.01)
    assert dead_batches(folder) == [("b1", 0.01)]


def test_an_ended_batch_supersedes_the_batches_recorded_after_it(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Stage 2's recorded batch depended on stage 1's replies; once stage 1 is found to have
    ended unusably, stage 2's recorded id is superseded and never waited on."""
    dead = _died_waiting_on_stage2(tmp_path, record_fixtures[:1])

    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, None, status="expired", reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.02),  # stage1, resubmitted
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.03),  # stage2, resubmitted
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0], "b2": dead.submitted[1]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resumed.waited == ["b1", "c1", "c2"]  # b2 is never waited on
    assert len(resumed.submitted) == 2  # both stages paid for fresh; b2 was never reused
    assert record.finished is not None

    folder = tmp_path / "runs" / _run_id()
    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [
        (row["stage"], row["batch_id"], row.get("ended"), row.get("superseded", False))
        for row in rows
    ] == [
        ("stage1", "b1", None, False),  # the dead run's original rows: never deleted
        ("stage2", "b2", None, False),
        ("stage2", "b2", None, True),  # marks b2 superseded, written BEFORE the ended row (9B)
        ("stage1", "b1", "expired", False),  # marks b1 ended -- after its superseded rows
        ("stage1", "c1", None, False),  # the fresh replacement
        ("stage2", "c2", None, False),
    ]
    assert rows[2]["depends_on_batch_id"] == "b1"


def test_a_fresh_batch_that_ends_failed_still_raises(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A fresh resubmission that itself ends unusably still raises: a run never re-spends
    more than once on one stage in one call. Fix round 3 (review Minor C): that fresh
    batch's ``ended`` row is written right there, before the raise, so a second resume never
    waits on it again -- it finds no row to reuse for stage 1 at all, and resubmits directly
    -- the recoverability this task exists for -- and this time the fresh batch completes.

    Also pins fix round 1 (review Minors 3-4): both dead batches' reported costs ($0.01 for
    b1, $0.02 for c1) survive into the final ``RunRecord`` -- in ``batch_ids``, in
    ``cost_usd`` and in ``month_spent`` -- even though neither batch's replies are ever
    priced into the scored case.
    """
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])

    resume1 = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, None, status="expired", reported_cost=0.01),
            lambda bid, reqs: _status(bid, reqs, None, status="failed", reported_cost=0.02),
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    with pytest.raises(ModelError, match="ended failed"):
        runner(tmp_path, RecordingFakeClient([]), batch=resume1).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert len(resume1.submitted) == 1  # no second resubmission in this call

    folder = tmp_path / "runs" / _run_id()
    # Fix round 3: c1's ``ended`` row already exists after resume 1 -- it is written on the
    # fresh path itself, not only rediscovered by a later resume's reused-branch wait.
    assert dead_batches(folder) == [("b1", 0.01), ("c1", 0.02)]

    resume2 = FakeBatchClient(
        handlers=[
            # c1 is already marked ``ended`` (fix round 3), so ``recorded_batches`` offers no
            # row for stage 1 at all: this pass resubmits directly, without waiting on c1
            # first. That is also what protects this money from fix round 2's Minor C -- a
            # provider that has since purged c1 is never asked about it again.
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.03),  # d1: stage1, fresh
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.04),  # d2: stage2, fresh
        ],
        prefix="d",
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resume2).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resume2.waited == ["d1", "d2"]  # never c1 -- it is already known dead
    assert len(resume2.submitted) == 2  # stage 1 paid for again exactly once, plus stage 2
    assert record.finished is not None
    (case,) = read_jsonl(tmp_path / "runs" / _run_id() / "cases.jsonl", CaseResult)
    assert case.failure is None

    rows = [json.loads(line) for line in (folder / "batches.jsonl").read_text().splitlines()]
    assert [(row["stage"], row["batch_id"], row.get("ended")) for row in rows] == [
        ("stage1", "b1", None),
        ("stage1", "b1", "expired"),
        ("stage1", "c1", None),
        ("stage1", "c1", "failed"),
        ("stage1", "d1", None),
        ("stage2", "d2", None),
    ]
    assert dead_batches(folder) == [("b1", 0.01), ("c1", 0.02)]

    # Fix round 1: both dead batches' money stays visible in the final record and to the
    # monthly budget guard, even though neither batch's replies were ever priced into the case.
    assert record.batch_ids == ("b1", "c1", "d1", "d2")
    assert record.reported_batch_cost_usd == pytest.approx(0.01 + 0.02 + 0.03 + 0.04)
    case_cost = 2 * (100 * 0.10 + 50 * 0.60) / 1e6  # the two replies that scored the case
    assert record.cost_usd == pytest.approx(case_cost + 0.01 + 0.02)
    assert month_spent(tmp_path / "runs", now=datetime(2026, 9, 15, tzinfo=UTC)) == pytest.approx(
        record.cost_usd
    )


def test_a_dead_batch_with_no_reported_cost_adds_nothing_and_does_not_crash(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 1: an ended batch that reported no cost is carried through as ``None``, not
    coerced to ``0.0`` or dropped -- and it must not make ``cost_usd`` crash either."""
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])

    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, None, status="expired", reported_cost=None),
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.02),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.03),
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    folder = tmp_path / "runs" / _run_id()
    assert dead_batches(folder) == [("b1", None)]
    case_cost = 2 * (100 * 0.10 + 50 * 0.60) / 1e6
    assert record.cost_usd == pytest.approx(case_cost)  # b1's None cost adds nothing


def test_a_batch_that_dies_fresh_still_counts_in_the_runs_cost(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 2 (review Minor A) plus fix round 3 (review Minor C): a batch that ends
    unusably on the *fresh* path (not reused) is now recorded ``ended`` at once, right there,
    before the raise -- carrying its reported cost -- exactly as a reused batch's ending is.
    Three things this must get right, each pinned below:

    (i) the aborted record from the call that found it dead counts the cost once;
    (ii) a later resume that completes counts it exactly once more, not twice, because the
        batch is already ``ended`` and is never waited on again (``recorded_batches`` excludes
        its id, so ``_take_reusable`` finds no row for the stage and resubmits directly); and
    (iii) that same fact makes the resume immune to review round 2's Minor C (a resume that
        re-waits on a fresh-dead batch can race the provider purging it, undercounting the
        cost) -- there is nothing left to wait on, so nothing can be purged out from under it.
    ``resumed`` below carries no reply for ``"b1"`` at all: if the fix regressed and the code
    tried to wait on it anyway, the fake would raise ``KeyError`` rather than silently pass.
    """
    fake = FakeBatchClient(
        handlers=[lambda bid, reqs: _status(bid, reqs, None, status="expired", reported_cost=0.05)]
    )
    with pytest.raises(ModelError, match="ended expired"):
        runner(tmp_path, RecordingFakeClient([]), batch=fake).run(BATCH_SPEC, record_fixtures[:1])

    folder = tmp_path / "runs" / _run_id()
    (aborted,) = read_jsonl(folder / "run.jsonl", RunRecord)
    assert aborted.finished is None
    assert aborted.cost_usd == pytest.approx(0.05)  # (i)
    # Fix round 3: the fresh batch's ``ended`` row exists already, cost carried on it.
    assert dead_batches(folder) == [("b1", 0.05)]
    assert month_spent(tmp_path / "runs", now=datetime(2026, 9, 15, tzinfo=UTC)) == pytest.approx(
        0.05
    )

    # b1 is already known ``ended``: this resume never waits on it again (ii, iii) -- it is
    # excluded from ``recorded_batches``, so stage 1 resubmits directly as a fresh batch.
    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.02),  # stage1, fresh
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.03),  # stage2, fresh
        ],
        prefix="c",
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resumed.waited == ["c1", "c2"]  # never "b1"
    assert record.finished is not None
    assert dead_batches(folder) == [("b1", 0.05)]  # unchanged: no new dead batch this call
    case_cost = 2 * (100 * 0.10 + 50 * 0.60) / 1e6  # the two replies that scored the case
    # Seeded once from ``dead_batches`` at the top of this resume, never re-discovered: b1's
    # cost is counted exactly once (ii).
    assert record.cost_usd == pytest.approx(case_cost + 0.05)
    assert month_spent(tmp_path / "runs", now=datetime(2026, 9, 15, tzinfo=UTC)) == pytest.approx(
        record.cost_usd
    )


def test_dead_batches_reads_ended_rows_with_their_reported_cost(tmp_path: Path) -> None:
    """Pins ``dead_batches``' own contract: one ``(batch_id, reported_cost_usd)`` pair per
    ``ended`` row, ``None`` carried through rather than dropped or coerced to zero, and a
    non-``ended`` row ignored."""
    folder = tmp_path / "runs" / "y"
    folder.mkdir(parents=True)
    lines = [
        {"batch_id": "a1", "stage": "stage1", "time": "2026-09-25T00:00:00"},
        {
            "batch_id": "a1",
            "stage": "stage1",
            "ended": "failed",
            "reported_cost_usd": 0.01,
            "time": "2026-09-25T00:00:01",
        },
        {
            "batch_id": "b1",
            "stage": "stage2",
            "ended": "expired",
            "reported_cost_usd": None,
            "time": "2026-09-25T00:00:02",
        },
        {"batch_id": "c1", "stage": "stage2", "time": "2026-09-25T00:00:03"},
    ]
    (folder / "batches.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    assert dead_batches(folder) == [("a1", 0.01), ("b1", None)]


def test_dead_batches_deduplicates_by_batch_id(tmp_path: Path) -> None:
    """Fix round 2 (review Nit B): two ``ended`` rows for one id count once, first row wins.
    The runner itself can never produce this (an id is hidden from ``recorded_batches`` as
    soon as its first ``ended`` row exists, so it can never be found dead a second time), but
    a hand-edited file should not be double-counted."""
    folder = tmp_path / "runs" / "z"
    folder.mkdir(parents=True)
    lines = [
        {
            "batch_id": "a1",
            "stage": "stage1",
            "ended": "failed",
            "reported_cost_usd": 0.01,
            "time": "2026-09-25T00:00:00",
        },
        {
            "batch_id": "a1",
            "stage": "stage1",
            "ended": "expired",
            "reported_cost_usd": 0.02,
            "time": "2026-09-25T00:00:01",
        },
    ]
    (folder / "batches.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    assert dead_batches(folder) == [("a1", 0.01)]


def test_recorded_batches_skips_ended_rows(tmp_path: Path) -> None:
    """The resume queue must never hand back an id that ended unusably, or its ``ended`` row."""
    folder = tmp_path / "runs" / "x"
    folder.mkdir(parents=True)
    lines = [
        {"batch_id": "a1", "stage": "stage1", "time": "2026-09-25T00:00:00"},
        {"batch_id": "a1", "stage": "stage1", "ended": "failed", "time": "2026-09-25T00:00:01"},
        {"batch_id": "b1", "stage": "stage2", "time": "2026-09-25T00:00:02"},
    ]
    (folder / "batches.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    assert recorded_batches(folder) == [("stage2", "b1", "2026-09-25T00:00:02")]


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


def test_resume_refuses_a_reused_batch_that_answers_cases_it_never_asked_about(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """An unexpected id is evidence of the wrong batch: the replay was not reproduced.

    Carrying on would score one case's replies against another's record, so this refuses
    rather than continuing.
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
    with pytest.raises(ConfigurationError, match="never asked about"):
        runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert resumed.submitted == []  # refused rather than quietly retried at full price


def test_resume_retries_a_case_the_reused_batch_did_not_answer(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A missing reply is retried, exactly as the fresh path retries it -- never refused.

    ``_run_stage1_pass`` already files a custom id with no result row as ``model: no
    reply`` and puts it in the retry batch. Holding a reused batch to a stricter standard
    would make a partly-delivered batch unresumable *deterministically* -- every attempt
    failing identically -- which is the recovery this feature was built to perform: the
    stranded dev-400 batch has 3 of its 401 replies unusable.
    """
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:2])
    answered, unanswered = (str(raw["ntsbNumber"]) for raw in record_fixtures[:2])

    def one_case_short(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        kept = [request for request in reqs if request.custom_id == answered]
        return _status(bid, kept, GOOD, reported_cost=0.01)

    resumed = FakeBatchClient(
        handlers=[
            one_case_short,  # b1 replayed: one of the two cases has no reply
            lambda bid, reqs: _status(bid, reqs, GOOD),  # stage1-retry, submitted fresh
            lambda bid, reqs: _status(bid, reqs, REFINE),  # stage2, both cases
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:2], resume=_run_id()
    )
    assert record.finished is not None
    # The retry batch carries exactly the case the reused batch left out.
    assert [request.custom_id for request in resumed.submitted[0]] == [unanswered]
    cases = read_jsonl(tmp_path / "runs" / _run_id() / "cases.jsonl", CaseResult)
    assert {case.case_id for case in cases} == {answered, unanswered}
    assert all(case.failure is None and case.scores is not None for case in cases)


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


def test_resume_refuses_a_folder_carrying_a_finished_judge_pass(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A judged folder is refused, and the message names this run, not ``<run-id>-judge``.

    The judge pass's row is a second ``RunRecord`` in the same file, with its own synthetic
    id; a resume would set it aside with the rest and never rewrite it, taking that spend
    out of the month for good.
    """
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    path = tmp_path / "runs" / _run_id() / "run.jsonl"
    (answering,) = path.read_text().splitlines()
    judge = json.loads(answering)
    judge["run_id"] = f"{_run_id()}-judge"
    judge["finished"] = "2026-09-15T00:00:00Z"
    path.write_text(f"{answering}\n{json.dumps(judge)}\n")
    with pytest.raises(ConfigurationError, match="carries a finished judge pass") as excinfo:
        runner(tmp_path, RecordingFakeClient([]), batch=FakeBatchClient(handlers=[])).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    assert "-judge" not in str(excinfo.value)  # names a run id an operator can act on


def test_resume_of_a_folder_with_only_batches_jsonl(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The recovery this feature was built for, in the shape the folder is actually in.

    A SIGKILL bypasses the abort path, so the killed run wrote no ``run.jsonl``, no
    ``cases.jsonl`` and no ``steps.jsonl`` — only ``spec.json``, written before the first
    call, and ``batches.jsonl``, appended before the wait began. A folder in that state is
    not "finished", has nothing to set aside, and resumes from its recorded batch.
    """
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    folder = tmp_path / "runs" / _run_id()
    for name in ("run.jsonl", "cases.jsonl", "steps.jsonl"):
        (folder / name).unlink()
    assert sorted(p.name for p in folder.iterdir()) == ["batches.jsonl", "spec.json"]

    resumed = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.26),
            lambda bid, reqs: _status(bid, reqs, REFINE, reported_cost=0.01),
        ],
        prefix="c",
        preloaded={"b1": dead.submitted[0]},
    )
    record = runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
        BATCH_SPEC, record_fixtures[:1], resume=_run_id()
    )
    assert resumed.waited == ["b1", "c1"]
    assert len(resumed.submitted) == 1  # only stage 2 was paid for again
    assert record.finished is not None
    (case,) = read_jsonl(folder / "cases.jsonl", CaseResult)
    assert case.failure is None
    assert case.scores is not None


def test_a_resume_that_aborts_does_not_erase_the_dead_runs_recorded_spend(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The record written never reports less than the record it supersedes.

    The dead run was billed for its stage-1 batch. If the resume aborts before re-reading
    those replies, its own cases cost nothing — and the superseded ``run.jsonl`` has been
    renamed out of ``month_spent``'s glob, so a $0 record would erase real spending from
    the month. The floor is the dead run's own figure.
    """
    dead = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.26),  # stage 1, billed
            lambda bid, reqs: BatchStatus(  # stage 2 never returns
                batch_id=bid, status="expired", results=(), reported_cost_usd=None
            ),
        ]
    )
    with pytest.raises(ModelError, match="expired"):
        runner(tmp_path, RecordingFakeClient([]), batch=dead).run(BATCH_SPEC, record_fixtures[:1])
    folder = tmp_path / "runs" / _run_id()
    (before,) = read_jsonl(folder / "run.jsonl", RunRecord)
    billed = before.cost_usd
    assert billed > 0.0  # or the rest of this test proves nothing

    def wait_fails(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(batch_id=bid, status="failed", results=(), reported_cost_usd=None)

    resumed = FakeBatchClient(
        # b1 (reused) ends "failed" -- task 9B resubmits it fresh as c1, which also ends
        # "failed": a fresh batch that ends unusably still raises, so this resume aborts too.
        handlers=[wait_fails, wait_fails],
        prefix="c",
        preloaded={"b1": dead.submitted[0], "b2": dead.submitted[1]},
    )
    with pytest.raises(ModelError, match="failed"):
        runner(tmp_path, RecordingFakeClient([]), batch=resumed).run(
            BATCH_SPEC, record_fixtures[:1], resume=_run_id()
        )
    (after,) = read_jsonl(folder / "run.jsonl", RunRecord)
    assert after.finished is None
    assert after.cases == 1
    assert sum(case.cost_usd for case in read_jsonl(folder / "cases.jsonl", CaseResult)) == 0.0
    assert after.cost_usd == pytest.approx(billed)  # the floor, not the $0 this attempt read
    # The superseded record is still there to read, it is just no longer the run's own.
    assert read_jsonl(folder / "run.aborted-1.jsonl", RunRecord)[0].cost_usd == billed


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
    run = _BatchRun(
        folder=Path("unused"),
        reusable=[("stage1", "b1", "t1"), ("stage2", "b2", "t2")],
    )
    assert Runner._take_reusable(run, "stage2") == ("b2", "t2")  # looks past the stage1 row
    assert run.reusable == [("stage1", "b1", "t1")]  # and consumes only the row it used
    assert Runner._take_reusable(run, "stage1-retry") is None  # no row: submit normally
    assert run.reusable == [("stage1", "b1", "t1")]
    assert Runner._take_reusable(run, "stage1") == ("b1", "t1")
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


# --- Task 9D: a fresh run claims its folder atomically ---


def test_a_fresh_run_refuses_a_folder_that_already_exists(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Task 9D: two runs started in the same second share an id; the second is refused."""
    existing = tmp_path / "runs" / _run_id(arm="ceiling")
    existing.mkdir(parents=True)
    (existing / "cases.jsonl").write_text("sentinel\n")
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    with pytest.raises(ConfigurationError, match="already exists"):
        runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert client.payloads == []
    assert (existing / "cases.jsonl").read_text() == "sentinel\n"
    assert not (existing / "spec.json").exists()
    assert open_reservations(tmp_path / "runs") == {}


def test_two_fresh_runs_in_the_same_second_cannot_share_a_folder(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The first run completes; a second fresh run with the same clock is refused."""
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    runner(tmp_path, RecordingFakeClient([GOOD, REFINE])).run(spec, record_fixtures[:1])
    second = RecordingFakeClient([GOOD, REFINE])
    with pytest.raises(ConfigurationError, match="already exists"):
        runner(tmp_path, second).run(spec, record_fixtures[:1])
    assert second.payloads == []


# --- the run log: elapsed, counts and cost per poll; reuse vs. fresh spend; the header ---


def test_format_elapsed_pins_minutes_and_seconds() -> None:
    assert Runner._format_elapsed(timedelta(minutes=18, seconds=11)) == "18m11s"
    assert Runner._format_elapsed(timedelta(minutes=1, seconds=0)) == "1m00s"
    assert Runner._format_elapsed(timedelta(minutes=13, seconds=42)) == "13m42s"


def test_format_elapsed_crosses_the_hour_boundary() -> None:
    assert Runner._format_elapsed(timedelta(minutes=59, seconds=59)) == "59m59s"
    assert Runner._format_elapsed(timedelta(hours=1, minutes=0, seconds=0)) == "1h00m"
    assert Runner._format_elapsed(timedelta(hours=1, minutes=1, seconds=1)) == "1h01m"
    assert Runner._format_elapsed(timedelta(hours=2, minutes=5, seconds=59)) == "2h05m"


def test_format_counts_known_values() -> None:
    status = _status("b", [], None, counts=BatchCounts(total=401, completed=401, failed=0))
    assert Runner._format_counts(status) == ("401/401", "0")


def test_format_counts_dash_when_the_provider_sent_none() -> None:
    """0032/brief: unknown must be distinguishable from zero, both in the type and the line."""
    status = _status("b", [], None, counts=BatchCounts(total=None, completed=None, failed=None))
    assert Runner._format_counts(status) == ("-/-", "-")


def test_log_status_line_pins_the_briefs_completed_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 9, 16, 7, 10, 22, tzinfo=UTC)
    wait_started = now - timedelta(minutes=18, seconds=11)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    status = _status("bx", [], None, reported_cost=0.2384, counts=BatchCounts(401, 401, 0))
    r._log_status("stage1", status, wait_started)
    assert capsys.readouterr().err == (
        "07:10:22Z stage1       completed   401/401   failed=0 $0.2384 (18m11s)\n"
    )


def test_log_ended_says_resubmitting_only_for_a_reused_batch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Final review, Minor 1: a fresh batch that ends unusably stops the run; nothing is
    resubmitted then, so the line must not say so."""
    now = datetime(2026, 9, 16, 7, 10, 22, tzinfo=UTC)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    r._log_ended("stage1", "b1", "expired")
    r._log_ended("stage1", "c1", "failed", reused=False)
    reused, fresh = capsys.readouterr().err.splitlines()
    assert reused.endswith("b1 ended expired; resubmitting (new money)")
    assert fresh.endswith("c1 ended failed; the run stops; a resume resubmits it")


def test_log_status_line_pins_the_briefs_retry_example_with_no_cost(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 9, 16, 7, 11, 23, tzinfo=UTC)
    wait_started = now - timedelta(minutes=1)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    status = _status(
        "bx", [], None, status="in_progress", counts=BatchCounts(total=3, completed=0, failed=0)
    )
    r._log_status("stage1-retry", status, wait_started)
    assert capsys.readouterr().err == (
        "07:11:23Z stage1-retry in_progress 0/3       failed=0 (1m00s)\n"
    )


def test_log_status_line_pins_the_briefs_stage2_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 9, 16, 7, 24, 5, tzinfo=UTC)
    wait_started = now - timedelta(minutes=13, seconds=42)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    status = _status(
        "bx", [], None, status="in_progress", counts=BatchCounts(total=398, completed=143, failed=2)
    )
    r._log_status("stage2", status, wait_started)
    assert capsys.readouterr().err == (
        "07:24:05Z stage2       in_progress 143/398   failed=2 (13m42s)\n"
    )


def test_log_status_line_fits_a_four_digit_count_without_losing_the_column_gap() -> None:
    """M6: ``_COUNTS_WIDTH`` must fit ``9999/9999`` (9 chars) with at least one gap column."""
    counts_str, _ = Runner._format_counts(_status("b", [], None, counts=BatchCounts(9999, 9999, 0)))
    assert counts_str == "9999/9999"
    assert len(counts_str) < Runner._COUNTS_WIDTH


def test_log_status_line_shows_dashes_when_the_provider_sent_no_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 9, 16, 7, 0, 0, tzinfo=UTC)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    status = _status("bx", [], None, status="in_progress")  # no counts, no cost
    r._log_status("stage1", status, now)
    err = capsys.readouterr().err
    assert "-/-" in err
    assert "failed=-" in err
    assert "$" not in err


def test_log_reused_pins_the_briefs_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 9, 16, 7, 10, 21, tzinfo=UTC)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    r._log_reused("stage1", "batch-1789528868-uJRGBbMh4Hxp07qRRB9m", "2026-09-16T03:21:11+00:00")
    assert capsys.readouterr().err == (
        "07:10:21Z stage1       REUSED     batch-1789528868-uJRGBbMh4Hxp07qRRB9m "
        "(recorded 03:21:11Z)\n"
    )


def test_log_reused_falls_back_to_unknown_for_an_unreadable_recorded_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A logging failure must never kill a run: an odd or missing ``time`` field is reported,
    not raised, and the run log says so plainly (brief: "log what is known and carry on")."""
    now = datetime(2026, 9, 16, 7, 10, 21, tzinfo=UTC)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    r._log_reused("stage1", "b1", "not a timestamp")
    assert "(recorded unknown)" in capsys.readouterr().err
    r._log_reused("stage1", "b1", None)
    assert "(recorded unknown)" in capsys.readouterr().err


def test_write_log_line_survives_a_body_builder_that_raises(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 2, I1: the guard covers *construction*, not only the final ``write``.

    The brief's own case -- writing to a closed file -- raises ``ValueError``, not
    ``OSError``; a bug in a formatter (an ``AttributeError``, a ``KeyError``, anything) is
    exactly as fatal to a paid batch mid-``wait()`` if it is allowed to propagate. Neither
    may kill the run.
    """
    r = runner(tmp_path, RecordingFakeClient([]))

    def exploding_body() -> str:
        raise AttributeError("boom")

    r._write_log_line(exploding_body)  # must not raise
    assert capsys.readouterr().err == ""


def test_log_submitted_pins_the_briefs_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 9, 16, 7, 10, 23, tzinfo=UTC)
    r = runner(tmp_path, RecordingFakeClient([]), now=lambda: now)
    r._log_submitted("stage1-retry", "batch-1789542619-7KCpMax2HcPd9lgJlg30", 3)
    assert capsys.readouterr().err == (
        "07:10:23Z stage1-retry SUBMITTED  batch-1789542619-7KCpMax2HcPd9lgJlg30 3 requests\n"
    )


def test_resume_logs_reused_for_the_recorded_batch_and_never_submitted_anywhere_for_it(
    tmp_path: Path, record_fixtures: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    """0032/brief §3: check *every* line mentioning each batch id, not just one picked line.

    Fix round 2, I3: the previous assertion picked the line containing REUSED and then
    asserted it did not also contain SUBMITTED -- true by construction, since the line was
    selected for containing REUSED. This checks every line mentioning the reused batch id
    for a spurious SUBMITTED (new money claimed where none was spent) and every line
    mentioning the fresh batch id for a spurious REUSED.
    """
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    capsys.readouterr()  # discard the dead run's own log lines
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
    lines = capsys.readouterr().err.splitlines()
    b1_lines = [line for line in lines if "b1" in line]
    c1_lines = [line for line in lines if "c1" in line]
    assert any("REUSED" in line for line in b1_lines)
    assert not any("SUBMITTED" in line for line in b1_lines)
    assert any("SUBMITTED" in line for line in c1_lines)
    assert not any("REUSED" in line for line in c1_lines)


class _AdvancingClock:
    """A clock whose ``now()`` only moves when told to -- ``advance`` simulates real wait time
    passing inside a fake batch client's handler, between the moment ``_submit_and_wait``
    captures ``wait_started`` and the moment its ``on_status`` callback reads the clock again.
    A runner test built on the fixed clock in ``runner()`` cannot exercise elapsed time at
    all, since every call to ``self._now()`` then returns the same instant.
    """

    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


def test_batch_run_logs_a_per_poll_line_with_the_right_stage_and_real_elapsed_time(
    tmp_path: Path, record_fixtures: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 2, I2: drives the per-poll line through ``_submit_and_wait``, not the
    formatters directly, so a wrong stage, a frozen ``wait_started`` (elapsed stuck at
    ``0m00s``, defeating the whole point of spotting a stalled batch) or a no-op ``on_status``
    would each be caught here.
    """
    clock = _AdvancingClock(datetime(2026, 9, 15, 7, 0, 0, tzinfo=UTC))

    def stage1(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        clock.advance(65)  # 1m05s of "real" wait time before the terminal poll
        return _status(bid, reqs, GOOD, reported_cost=0.01, counts=BatchCounts(1, 1, 0))

    def stage2(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        clock.advance(5)
        return _status(bid, reqs, REFINE, reported_cost=0.02, counts=BatchCounts(1, 1, 0))

    fake = FakeBatchClient(handlers=[stage1, stage2])
    runner(tmp_path, RecordingFakeClient([]), batch=fake, now=clock.now).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    err = capsys.readouterr().err
    stage1_lines = [
        line for line in err.splitlines() if line.split()[1:2] == ["stage1"] and "completed" in line
    ]
    assert len(stage1_lines) == 1
    line = stage1_lines[0]
    assert "completed" in line
    assert "1/1" in line
    assert "failed=0" in line
    assert "(1m05s)" in line


def test_run_header_logs_fresh_with_the_specs_facts(
    tmp_path: Path, record_fixtures: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeBatchClient(handlers=[lambda bid, reqs: _status(bid, reqs, ABSTAIN)])
    runner(tmp_path, RecordingFakeClient([]), batch=fake).run(BATCH_SPEC, record_fixtures[:1])
    header = capsys.readouterr().err.splitlines()[0]
    assert header == (
        f"00:00:00Z run {_run_id()} FRESH sample=dev-400 arm=ceiling cases=1 "
        "model=openai/gpt-5.6-luna price=batch"
    )


def test_run_header_logs_resumed_with_the_specs_facts(
    tmp_path: Path, record_fixtures: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    dead = _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    capsys.readouterr()  # discard the dead run's own log lines
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
    header = capsys.readouterr().err.splitlines()[0]
    assert header == (
        f"00:00:00Z run {_run_id()} RESUMED sample=dev-400 arm=ceiling cases=1 "
        "model=openai/gpt-5.6-luna price=batch"
    )


def test_run_reserves_at_start_and_settles_at_the_end(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The reservation must exist *while the run is in flight*, not merely be absent after.

    Deleting the ``reserve(...)`` call from the runner would leave every other assertion in
    this suite passing, since they only check the state before and after the run. The model
    client is the seam that sees inside that window: it snapshots ``open_reservations`` on
    every call, before returning its scripted reply.
    """
    inner = RecordingFakeClient([GOOD, REFINE])
    snapshots: list[dict[str, float]] = []

    class SnapshottingClient:
        def complete(
            self, payload: object, settings: object, *, system: str = "", history: object = ()
        ) -> ModelReply:
            snapshots.append(open_reservations(tmp_path / "runs"))
            return inner.complete(
                cast(Payload, payload),
                cast(ModelSettings, settings),
                system=system,
                history=cast("Sequence[Turn]", history),
            )

    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    run = runner(tmp_path, SnapshottingClient()).run(spec, record_fixtures[:1])
    projected = project_cost(spec, 1)
    assert snapshots  # both turns saw a reservation; the loop below checks every one
    for snapshot in snapshots:
        assert snapshot == pytest.approx({run.run_id: projected})
    assert not (tmp_path / "runs" / run.run_id / RESERVATION_FILE).exists()
    assert open_reservations(tmp_path / "runs") == {}


def test_run_is_refused_by_another_runs_open_reservation(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    reserve(tmp_path / "runs", "other-run", 24.99, now=datetime(2026, 9, 15, tzinfo=UTC))
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.05,
        budget_usd=25.0,
    )
    with pytest.raises(BudgetError, match="reserved"):
        runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert client.payloads == []


def test_an_aborted_run_settles_its_reservation(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    class Dies:
        def complete(
            self, payload: object, settings: object, *, system: str = "", history: object = ()
        ) -> ModelReply:
            raise KeyboardInterrupt

    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    with pytest.raises(KeyboardInterrupt):
        runner(tmp_path, Dies()).run(spec, record_fixtures[:1])
    assert open_reservations(tmp_path / "runs") == {}


def test_estimated_cost_reserves_the_maximum_output_at_the_output_price() -> None:
    """Fix finding 1: the estimate is a case (``ANSWERING_TURNS`` calls), not one call."""
    spec = RunSpec(
        sample="dev-400", arm="ceiling", model="anthropic/claude-sonnet-5", price_variant="standard"
    )
    price = sources.price_of("anthropic/claude-sonnet-5")
    call_reserve = spec.max_output_tokens * price.output_usd_per_mtok / 1e6
    assert estimated_cost_usd("", "", spec) == pytest.approx(ANSWERING_TURNS * call_reserve)
    assert estimated_cost_usd("x" * 4000, "", spec) == pytest.approx(
        ANSWERING_TURNS * (call_reserve + 1000 * price.input_usd_per_mtok / 1e6)
    )


def test_cap_binds_on_output_alone_for_a_dear_model() -> None:
    """M1: at Sonnet 5's standard price the two-turn output reserve is $0.04 of a $0.05
    default cap (fix finding 1: ``ANSWERING_TURNS`` doubles the single-call $0.02)."""
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        model="anthropic/claude-sonnet-5",
        price_variant="standard",
        cap_usd=0.01,
    )
    assert over_cap("", "", spec)


# --- arm B: the docket reader, the drop rule, the step record (Task 12, decision 0043) ---


class FakeDocketReader:
    def __init__(self, docket: Docket, version: Literal["v1", "v2"] = "v1") -> None:
        self.docket = docket
        self.reads: list[int] = []
        self.version: Literal["v1", "v2"] = version

    def read(self, mkey: int) -> Docket:
        self.reads.append(mkey)
        return self.docket


class _ByMkeyDocketReader:
    """A DocketReader keyed by mKey: each case in a multi-case test gets its own docket."""

    version: Literal["v1", "v2"] = "v1"

    def __init__(self, by_mkey: Mapping[int, Docket]) -> None:
        self._by_mkey = by_mkey
        self.reads: list[int] = []

    def read(self, mkey: int) -> Docket:
        self.reads.append(mkey)
        return self._by_mkey[mkey]


def test_cached_docket_reader_delegates_to_read_docket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``CachedDocketReader`` is a thin seam: it calls ``manifest.read_docket`` with the
    client it was built with (spec §7.1). Decision 0056: no deny-list predicate to pass."""
    captured: dict[str, object] = {}
    docket = small_docket({1: "[page 1 of 3]\nx\n"})

    def fake_read_docket(client: object, mkey: int) -> Docket:
        captured["client"] = client
        captured["mkey"] = mkey
        return docket

    monkeypatch.setattr("ntsb_probable_cause.scoring.runner.read_docket", fake_read_docket)
    sentinel_client = object()
    reader = CachedDocketReader(cast(DocketClient, sentinel_client))
    result = reader.read(42)
    assert captured == {"client": sentinel_client, "mkey": 42}
    assert result is docket


def test_prepare_case_with_no_docket_matches_case_payload(
    record_fixtures: list[dict[str, object]],
) -> None:
    """``prepare_case(..., docket=None)`` is what ``case_payload`` now delegates to."""
    raw = record_fixtures[0]
    spec = RunSpec(sample="dev-400", arm="ceiling")
    tables = load_tables()
    prepared = prepare_case(raw, spec, tables, None)
    payload, system, verdict, evidence = case_payload(raw, spec, tables)
    assert prepared.payload == payload
    assert prepared.system == system
    assert prepared.verdict == verdict
    assert prepared.evidence == evidence
    assert prepared.attached == ()


def test_prepare_case_arm_b_without_a_docket_raises(
    record_fixtures: list[dict[str, object]],
) -> None:
    with pytest.raises(ConfigurationError, match="docket"):
        prepare_case(record_fixtures[0], RunSpec(sample="dev-400", arm="B"), load_tables(), None)


def test_prepare_case_fails_closed_when_an_attached_document_holds_the_narrative(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Fix round 1, Finding 1: the leakage guard is only pinned in ``tests/test_attach.py``,
    which calls ``split_record`` directly -- nothing proved ``prepare_case`` (the actual arm
    B production path) also runs it over every attached document. It does: this drives
    ``prepare_case`` itself with a docket document holding a fixture's own withheld factual
    narrative, and asserts the guard fails closed at that call, not just inside the helper.
    """
    raw = next(r for r in record_fixtures if factual_narrative(r))
    narrative = factual_narrative(raw) or ""
    docket = small_docket({1: f"[page 1 of 3]\nAs the NTSB found: {narrative}\n"})
    spec = RunSpec(sample="dev-400", arm="B")
    with pytest.raises(LeakageError, match="docket_documents"):
        prepare_case(raw, spec, load_tables(), docket)


def test_sync_leaking_case_fails_alone_and_the_run_continues(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix 4: a tripwire hit on one case's docket must fail that case, not abort the run.

    Before the fix, ``self._prepare``'s ``LeakageError`` propagated out of ``_answer_case``
    to ``run()``'s ``except BaseException``, which writes partial outputs and re-raises --
    aborting a paid run over one document. Two cases go in, one carrying a docket document
    that holds its own withheld factual narrative; the other must still be answered and
    scored, and the run must not raise.
    """
    leaking = next(r for r in record_fixtures if factual_narrative(r))
    clean = next(r for r in record_fixtures if r["mKey"] != leaking["mKey"])
    narrative = factual_narrative(leaking) or ""
    leak_docket = small_docket({1: f"[page 1 of 3]\nAs the NTSB found: {narrative}\n"})
    clean_docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    reader = _ByMkeyDocketReader(
        {leaking["mKey"]: leak_docket, clean["mKey"]: clean_docket}  # type: ignore[dict-item]
    )
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="B",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    run = runner(tmp_path, client, docket=reader).run(spec, [leaking, clean])
    results = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    by_id = {r.case_id: r for r in results}
    leaking_result = by_id[str(leaking["ntsbNumber"])]
    clean_result = by_id[str(clean["ntsbNumber"])]
    assert leaking_result.failure is not None
    assert leaking_result.failure.startswith("leak:")
    assert leaking_result.cost_usd == 0.0
    assert leaking_result.steps == ()
    assert leaking_result.scores is None
    assert clean_result.failure is None
    assert clean_result.scores is not None


def test_prepare_case_refuses_arm_b_when_a_docket_role_is_excluded(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Fix round 1, Finding 2: an arm B run that excludes a docket role must be refused, not
    silently run as arm B with an ever-growing ``documents_attached`` and a payload that
    never actually grows -- ``masked_exclusions`` (spec §6.2) excludes both roles regardless
    of day, and the masked condition arrives in the next stage."""
    spec = RunSpec(sample="dev-400", arm="B", exclusions=frozenset({EvidenceRole.DOCKET_DOCUMENTS}))
    with pytest.raises(ConfigurationError, match="docket_documents"):
        prepare_case(record_fixtures[0], spec, load_tables(), None)


def test_arm_b_without_a_docket_reader_is_refused_before_any_call(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="B",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    with pytest.raises(ConfigurationError, match="docket"):
        runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert client.payloads == []


def test_arm_b_attaches_the_filtered_documents_and_records_them(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    docket = small_docket(
        {1: "[page 1 of 3]\nThe crankshaft was intact.\n", 2: "[page 1 of 3]\nWe submit.\n"}
    )
    reader = FakeDocketReader(docket)
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="B",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    run = runner(tmp_path, client, docket=reader).run(spec, record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    (step,) = case.steps
    assert step.tool == "docket"
    # Decision 0048: order is by each document's own estimated_tokens, ascending -- document 2
    # (6 tokens) is smaller than document 1 (10 tokens), so it is attached first.
    assert step.arguments == {"documents": [2, 1]}
    assert step.documents_attached == ("2: party_submission, 6 tokens", "1: exam_site, 10 tokens")
    assert step.not_available == ("3: unreadable: scan",)
    assert "crankshaft" in client.payloads[0].text
    assert reader.reads == [record_fixtures[0]["mKey"]]


def test_arm_b_case_result_carries_the_narrative_coverage_mark(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """A docket document holding half the factual narrative marks the CaseResult (S2.6 §4.4),

    and the mark itself never reaches a payload the model sees (0078).
    """
    raw = copy.deepcopy(record_fixtures[0])
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["concatenatedFactualNarrative"] = FACTUAL
    docket = small_docket({1: f"[page 1 of 3]\n{S1}. {S2}.\n"})
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="B",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    run = runner(tmp_path, client, docket=FakeDocketReader(docket)).run(spec, [raw])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.marks == (CaseMark(kind="narrative_coverage", count=1),)
    assert case.narrative_share == 0.5
    for payload in client.payloads:
        assert "narrative_coverage" not in payload.text


def test_arm_b_drops_whole_documents_smallest_first_at_the_cap(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Decision 0043: stop before the first document that would break the cap; record it.

    Decision 0048: the order documents are added in is by each document's own measured size,
    smallest first, not a category rank -- the small document here is admitted and the big
    one is refused because of their own token counts, not their categories.

    Fix finding 1: the cap now bounds a case (``ANSWERING_TURNS`` calls), not one call, so
    the cap here is double the pre-fix value and the boundary it sits at is double too --
    the ratio between "admits the small document" and "refuses the big one" is unchanged.
    """
    big = "[page 1 of 3]\n" + "x" * 40_000 + "\n"
    docket = small_docket({1: "[page 1 of 3]\nsmall\n", 2: big})
    client = RecordingFakeClient([GOOD, REFINE])
    # Sonnet 5 standard, measured (``estimated_cost_usd`` on this fixture and code tables,
    # now counting both answering turns): base + the 5-token small document costs about
    # $0.0568; base + both documents (the big one adds 10,003 tokens) costs about $0.0969.
    # A $0.08 cap sits between the two, so it admits the small document and refuses the big
    # one. If the base prompt alone is over the cap the case fails "cap" before any
    # document, which is the existing behaviour.
    spec = RunSpec(
        sample="dev-400",
        arm="B",
        sync=True,
        price_variant="standard",
        model="anthropic/claude-sonnet-5",
        cap_usd=0.08,
        # The costs above were measured at a 2,000-token reply budget; pinned so the
        # boundary stays where it was measured when the default changes (decision 0084).
        max_output_tokens=2000,
        expected_cost_per_case_usd=0.001,
    )
    run = runner(tmp_path, client, docket=FakeDocketReader(docket)).run(spec, record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    (step,) = case.steps
    assert step.documents_attached == ("1: exam_site, 5 tokens",)
    assert step.documents_not_read == ("2: cap, 10003 tokens",)
    assert "xxxx" not in client.payloads[0].text


def test_ceiling_and_arm_a_never_read_the_docket(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    reader = FakeDocketReader(small_docket({1: "[page 1 of 3]\na\n"}))
    for arm in cast(tuple[Literal["A", "ceiling"], ...], ("A", "ceiling")):
        client = RecordingFakeClient([GOOD, REFINE])
        spec = RunSpec(
            sample="dev-400",
            arm=arm,
            sync=True,
            price_variant="standard",
            expected_cost_per_case_usd=0.001,
        )
        runner(tmp_path, client, docket=reader).run(spec, record_fixtures[:1])
    assert reader.reads == []


def test_batch_arm_b_attaches_documents_too(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD),
            lambda bid, reqs: _status(bid, reqs, REFINE),
        ]
    )
    runner(tmp_path, RecordingFakeClient([]), batch=fake, docket=FakeDocketReader(docket)).run(
        RunSpec(sample="dev-400", arm="B", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert "crankshaft" in fake.submitted[0][0].payload.text


def test_batch_leaking_case_fails_alone_and_the_run_continues(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix 4, batch path: the same guarantee as the sync test, for ``_prepare_contexts``.

    Before the fix, a ``LeakageError`` here propagated out of ``_answer_batch`` (via
    ``_prepare_contexts``) to ``run()``'s ``except BaseException`` -- aborting a batch that
    may already have paid for the rest of its cases. Only the clean case reaches the batch
    client; the leaking one is filed as failed before any request is ever built.
    """
    leaking = next(r for r in record_fixtures if factual_narrative(r))
    clean = next(r for r in record_fixtures if r["mKey"] != leaking["mKey"])
    narrative = factual_narrative(leaking) or ""
    leak_docket = small_docket({1: f"[page 1 of 3]\nAs the NTSB found: {narrative}\n"})
    clean_docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    reader = _ByMkeyDocketReader(
        {leaking["mKey"]: leak_docket, clean["mKey"]: clean_docket}  # type: ignore[dict-item]
    )
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD),
            lambda bid, reqs: _status(bid, reqs, REFINE),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake, docket=reader).run(
        RunSpec(sample="dev-400", arm="B", sync=False, expected_cost_per_case_usd=0.001),
        [leaking, clean],
    )
    results = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    by_id = {r.case_id: r for r in results}
    leaking_result = by_id[str(leaking["ntsbNumber"])]
    clean_result = by_id[str(clean["ntsbNumber"])]
    assert leaking_result.failure is not None
    assert leaking_result.failure.startswith("leak:")
    assert leaking_result.cost_usd == 0.0
    assert clean_result.failure is None
    assert clean_result.scores is not None
    submitted_ids = {req.custom_id for batch in fake.submitted for req in batch}
    assert submitted_ids == {str(clean["ntsbNumber"])}


def test_every_call_states_the_runs_reasoning_level_and_the_run_records_it(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """S2.4 spec §4.1: stated on both stages, written to spec.json and to the run record."""
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.0,
    )
    run = runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert [s.reasoning_effort for s in client.settings] == ["medium", "medium"]
    folder = tmp_path / "runs" / run.run_id
    assert json.loads((folder / "spec.json").read_text())["reasoning_effort"] == "medium"
    assert read_jsonl(folder / "run.jsonl", RunRecord)[-1].reasoning_effort == "medium"


# --- the reply budget, finish reasons and reasoning tokens (S2.6 Task 9A) ---


def test_every_call_states_the_runs_reply_budget_and_the_run_records_it(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The budget is stated on both stages, written to spec.json, right after reasoning_effort,
    and to the run record."""
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        max_output_tokens=4000,
        expected_cost_per_case_usd=0.0,
    )
    run = runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert [s.max_output_tokens for s in client.settings] == [4000, 4000]
    folder = tmp_path / "runs" / run.run_id
    recorded = json.loads((folder / "spec.json").read_text())
    assert recorded["max_output_tokens"] == 4000
    keys = list(recorded)
    assert keys.index("max_output_tokens") == keys.index("reasoning_effort") + 1
    assert read_jsonl(folder / "run.jsonl", RunRecord)[-1].max_output_tokens == 4000


def test_stage1_truncated_reply_fails_schema_with_finish_reason_and_token_counts(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """S2.6 Task 9A: the reply budget's own fingerprint on a truncated stage-1 reply."""

    def truncated(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(
            batch_id=bid,
            status="completed",
            results=tuple(
                BatchResult(
                    custom_id=r.custom_id,
                    reply=ModelReply(
                        content='{"probable_cause": "the eng',
                        finish_reason="length",
                        usage=Usage(
                            prompt_tokens=90_000, completion_tokens=2000, reasoning_tokens=1900
                        ),
                        model=r.settings.model_id(),
                        response_id="fake",
                    ),
                    error=None,
                )
                for r in reqs
            ),
            reported_cost_usd=None,
            counts=BatchCounts(None, None, None),
        )

    fake = FakeBatchClient(handlers=[truncated, truncated])
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema:")
    assert case.failure.endswith(
        "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1900)"
    )


def test_batch_retry_prompt_never_carries_the_reply_detail(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 1: the model-facing retry text must stay byte-for-byte what it was before
    Task 9A -- only the *recorded* failure carries ``(finish_reason=..., ...)``.

    Both stage-1 attempts are truncated (``finish_reason="length"``) so the case ends up
    failed after its retry; the retry batch's own request is what would have carried a
    leaked detail if ``need_retry``'s text (also used as the retry prompt) had not been kept
    separate from the failure text.
    """

    def truncated(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(
            batch_id=bid,
            status="completed",
            results=tuple(
                BatchResult(
                    custom_id=r.custom_id,
                    reply=ModelReply(
                        content='{"probable_cause": "the eng',
                        finish_reason="length",
                        usage=Usage(
                            prompt_tokens=90_000, completion_tokens=2000, reasoning_tokens=1900
                        ),
                        model=r.settings.model_id(),
                        response_id="fake",
                    ),
                    error=None,
                )
                for r in reqs
            ),
            reported_cost_usd=None,
            counts=BatchCounts(None, None, None),
        )

    fake = FakeBatchClient(handlers=[truncated, truncated])
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(fake.submitted) == 2  # stage1, stage1-retry
    retry_request = fake.submitted[1][0]
    assert "Your previous reply was rejected: schema:" in retry_request.system
    assert "finish_reason=" not in retry_request.system
    assert "reasoning_tokens=" not in retry_request.system
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.endswith(
        "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1900)"
    )


def test_batch_stage2_retry_prompt_never_carries_the_reply_detail(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Fix round 2: the stage-2 twin of ``test_batch_retry_prompt_never_carries_the_reply_detail``.

    Stage 1 succeeds; both stage-2 attempts are truncated, so the case fails after its
    stage-2 retry -- the retry that ``_stage2_system`` builds is what would have carried a
    leaked detail if ``_run_stage2_pass``'s ``need_retry`` text had not been kept separate
    from ``ctx.schema_detail``.
    """

    def truncated(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(
            batch_id=bid,
            status="completed",
            results=tuple(
                BatchResult(
                    custom_id=r.custom_id,
                    reply=ModelReply(
                        content='{"items": [',
                        finish_reason="length",
                        usage=Usage(
                            prompt_tokens=90_000, completion_tokens=2000, reasoning_tokens=1850
                        ),
                        model=r.settings.model_id(),
                        response_id="fake",
                    ),
                    error=None,
                )
                for r in reqs
            ),
            reported_cost_usd=None,
            counts=BatchCounts(None, None, None),
        )

    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD, reported_cost=0.01),
            truncated,
            truncated,
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert len(fake.submitted) == 3  # stage1, stage2, stage2-retry
    retry_request = fake.submitted[2][0]
    assert "Your previous reply was rejected: schema:" in retry_request.system
    assert "finish_reason=" not in retry_request.system
    assert "reasoning_tokens=" not in retry_request.system
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.endswith(
        "(finish_reason=length, completion_tokens=2000, reasoning_tokens=1850)"
    )


def test_sync_retry_prompt_never_carries_the_reply_detail(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Mirrors the batch-path test for the sync path (fix round 1).

    The sync retry already builds its prompt from the bare ``SchemaError`` (``_two_turns``
    never sees ``_reply_detail``, which is only appended in ``_answer_case``'s except
    block) -- this pins that it stays that way.
    """
    client = RecordingFakeClient(["not json", "still not json"])
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
    assert len(client.systems) == 2  # first attempt, retry
    retry_system = client.systems[1]
    assert "Your previous reply was rejected: reply is not a Hypothesis" in retry_system
    assert "finish_reason=" not in retry_system
    assert "reasoning_tokens=" not in retry_system
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema:")
    assert "finish_reason=" in case.failure


def test_successful_case_records_reasoning_tokens_summed_over_its_replies(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    usage = [
        Usage(prompt_tokens=300, completion_tokens=40, reasoning_tokens=100),  # stage 1
        Usage(prompt_tokens=150, completion_tokens=10, reasoning_tokens=20),  # stage 2
    ]
    client = RecordingFakeClient([GOOD, REFINE], usage=usage)
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
    (step,) = read_jsonl(tmp_path / "runs" / run.run_id / "steps.jsonl", StepRecord)
    assert step.reasoning_tokens == 120


def test_step_reasoning_tokens_is_none_when_no_reply_reported_one(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])  # default usage: no reasoning_tokens
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
    (step,) = read_jsonl(tmp_path / "runs" / run.run_id / "steps.jsonl", StepRecord)
    assert step.reasoning_tokens is None


def test_resume_refuses_a_different_reply_budget(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Beside S2.4's test_resume_refuses_a_different_model (0032 point 4).

    ``refuse_unresumable`` compares every ``spec.json`` field, so recording
    ``max_output_tokens`` is what makes a mismatched resume refuse -- an unrecorded setting
    is a silent variable, the argument S2.4's reasoning-level decision made.
    """
    _died_waiting_on_stage1(tmp_path, record_fixtures[:1])
    other = FakeBatchClient(handlers=[])
    recorded = RunSpec.max_output_tokens
    assert recorded != 4000
    with pytest.raises(ConfigurationError, match=f"max_output_tokens was {recorded}"):
        runner(tmp_path, RecordingFakeClient([]), batch=other).run(
            RunSpec(
                sample="dev-400",
                arm="ceiling",
                sync=False,
                model="openai/gpt-5.6-luna",
                max_output_tokens=4000,
                expected_cost_per_case_usd=0.001,
            ),
            record_fixtures[:1],
            resume=_run_id(),
        )
    assert other.submitted == []


class _FinishingFakeClient(RecordingFakeClient):
    """``RecordingFakeClient`` that also stamps each reply with a scripted ``finish_reason``."""

    def __init__(
        self, replies: Sequence[str], usage: Sequence[Usage], finish_reasons: Sequence[str]
    ) -> None:
        super().__init__(replies, usage=usage)
        self._finish_reasons = tuple(finish_reasons)

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        reply = super().complete(payload, settings, system=system, history=history)
        finish = self._finish_reasons[len(self.payloads) - 1]
        return reply.model_copy(update={"finish_reason": finish})


def test_sync_step_records_every_reply_figure_in_call_order(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Task 9A fix round 4: ``Runner._step`` fills the three per-reply tuples on the sync path.

    Stage 1 is cut off (``length``), its retry succeeds and stage 2 succeeds, so the step
    carries three replies -- each with its own figures, in call order, never a sum.
    """
    usage = [
        Usage(prompt_tokens=90_000, completion_tokens=2000, reasoning_tokens=1900),
        Usage(prompt_tokens=90_100, completion_tokens=300, reasoning_tokens=250),
        Usage(prompt_tokens=1_000, completion_tokens=250, reasoning_tokens=200),
    ]
    client = _FinishingFakeClient(
        ['{"probable_cause": "the eng', GOOD, REFINE],
        usage=usage,
        finish_reasons=["length", "stop", "stop"],
    )
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
    (step,) = read_jsonl(tmp_path / "runs" / run.run_id / "steps.jsonl", StepRecord)
    assert step.reply_completion_tokens == (2000, 300, 250)
    assert step.reply_reasoning_tokens == (1900, 250, 200)
    assert step.reply_finish_reasons == ("length", "stop", "stop")
    # S2.6 Task 9C: a scored case's own tuples equal its step's.
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.reply_completion_tokens == step.reply_completion_tokens
    assert case.reply_reasoning_tokens == step.reply_reasoning_tokens
    assert case.reply_finish_reasons == step.reply_finish_reasons


def _replying(
    content: str, finish: str, usage: Usage
) -> Callable[[str, Sequence[BatchRequest]], BatchStatus]:
    """A ``FakeBatchClient`` handler: every request answered with one scripted reply."""

    def handler(bid: str, reqs: Sequence[BatchRequest]) -> BatchStatus:
        return BatchStatus(
            batch_id=bid,
            status="completed",
            results=tuple(
                BatchResult(
                    custom_id=r.custom_id,
                    reply=ModelReply(
                        content=content,
                        finish_reason=finish,
                        usage=usage,
                        model=r.settings.model_id(),
                        response_id="fake",
                    ),
                    error=None,
                )
                for r in reqs
            ),
            reported_cost_usd=None,
            counts=BatchCounts(None, None, None),
        )

    return handler


def test_batch_step_records_every_reply_figure_in_call_order(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Task 9A fix round 4: the batch twin of the sync per-reply test above."""
    fake = FakeBatchClient(
        handlers=[
            _replying(
                '{"probable_cause": "the eng',
                "length",
                Usage(prompt_tokens=90_000, completion_tokens=2000, reasoning_tokens=1900),
            ),
            _replying(
                GOOD,
                "stop",
                Usage(prompt_tokens=90_100, completion_tokens=300, reasoning_tokens=250),
            ),
            _replying(
                REFINE,
                "stop",
                Usage(prompt_tokens=1_000, completion_tokens=250, reasoning_tokens=200),
            ),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert run.batch_ids == ("b1", "b2", "b3")  # stage 1, stage-1 retry, stage 2
    (step,) = read_jsonl(tmp_path / "runs" / run.run_id / "steps.jsonl", StepRecord)
    assert step.reply_completion_tokens == (2000, 300, 250)
    assert step.reply_reasoning_tokens == (1900, 250, 200)
    assert step.reply_finish_reasons == ("length", "stop", "stop")
    # S2.6 Task 9C: a scored case's own tuples equal its step's.
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.reply_completion_tokens == step.reply_completion_tokens
    assert case.reply_reasoning_tokens == step.reply_reasoning_tokens
    assert case.reply_finish_reasons == step.reply_finish_reasons


def test_sync_failed_case_records_every_reply_including_an_earlier_cut_off_one(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """S2.6 Task 9C: stage 1 is cut off (``length``) and retried successfully; stage 2 then
    fails schema on both its attempt and its retry. The case's failure text names only its
    *last* reply, but ``CaseResult`` carries every reply it made, in call order.
    """
    usage = [
        Usage(prompt_tokens=90_000, completion_tokens=2000, reasoning_tokens=1900),
        Usage(prompt_tokens=90_100, completion_tokens=300, reasoning_tokens=250),
        Usage(prompt_tokens=1_000, completion_tokens=250, reasoning_tokens=200),
        Usage(prompt_tokens=1_000, completion_tokens=260, reasoning_tokens=210),
    ]
    client = _FinishingFakeClient(
        ['{"probable_cause": "the eng', GOOD, "not json", "still not json"],
        usage=usage,
        finish_reasons=["length", "stop", "stop", "stop"],
    )
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
    assert case.failure.startswith("schema:")
    assert case.steps == ()  # a failed case has no step
    assert case.reply_completion_tokens == (2000, 300, 250, 260)
    assert case.reply_reasoning_tokens == (1900, 250, 200, 210)
    assert case.reply_finish_reasons == ("length", "stop", "stop", "stop")


def test_batch_failed_case_records_every_reply_including_an_earlier_cut_off_one(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Task 9C: the batch twin of the sync test above -- four batches, one per attempt."""
    fake = FakeBatchClient(
        handlers=[
            _replying(
                '{"probable_cause": "the eng',
                "length",
                Usage(prompt_tokens=90_000, completion_tokens=2000, reasoning_tokens=1900),
            ),
            _replying(
                GOOD,
                "stop",
                Usage(prompt_tokens=90_100, completion_tokens=300, reasoning_tokens=250),
            ),
            _replying(
                "not json",
                "stop",
                Usage(prompt_tokens=1_000, completion_tokens=250, reasoning_tokens=200),
            ),
            _replying(
                "still not json",
                "stop",
                Usage(prompt_tokens=1_000, completion_tokens=260, reasoning_tokens=210),
            ),
        ]
    )
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake).run(
        RunSpec(sample="dev-400", arm="ceiling", sync=False, expected_cost_per_case_usd=0.001),
        record_fixtures[:1],
    )
    assert run.batch_ids == ("b1", "b2", "b3", "b4")
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is not None
    assert case.failure.startswith("schema:")
    assert case.steps == ()
    assert case.reply_completion_tokens == (2000, 300, 250, 260)
    assert case.reply_reasoning_tokens == (1900, 250, 200, 210)
    assert case.reply_finish_reasons == ("length", "stop", "stop", "stop")


def test_spec_json_records_the_evidence_version_after_the_arm() -> None:
    spec = RunSpec(sample="dev-400", arm="B")
    keys = list(spec_json(spec, commit_sha="abc1234", dirty=False, case_ids=()))
    assert keys[keys.index("arm") + 1] == "evidence_version"
    assert (
        spec_json(spec, commit_sha="abc1234", dirty=False, case_ids=())["evidence_version"] == "v1"
    )


def test_run_refuses_an_evidence_version_that_is_not_built_yet(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """v3 has no reader (deferred by decision 0090); the refusal fires before any model call.

    Task 14 built v2, so this test moved from v2 to v3, the version still unbuilt.
    """
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        evidence_version="v3",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.0,
    )
    with pytest.raises(ConfigurationError, match="v3 is not built"):
        runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert client.payloads == []


@pytest.mark.parametrize("arm", ["A", "ceiling"])
def test_an_arm_that_reads_no_docket_refuses_a_version_past_v1(
    tmp_path: Path, record_fixtures: list[dict[str, object]], arm: Literal["A", "ceiling"]
) -> None:
    """Andy's decision, 2026-09-26 (Task 14 review I1): arm A and the ceiling read no docket,
    so a v2 label on their run would be false. Refused before any folder or reservation."""
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(
        sample="dev-400",
        arm=arm,
        evidence_version="v2",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    with pytest.raises(ConfigurationError, match="reads no docket") as refused:
        runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert f"arm {arm}" in str(refused.value)
    assert "false label" in str(refused.value)
    assert client.payloads == []
    assert not (tmp_path / "runs").exists()  # no run folder, so no reservation either


# --- Task 14: evidence version v2, the reader's version, preparation cost per case ---


def _transcribed_docket(cost: float = 0.003) -> Docket:
    """One document whose first page was read from a transcription costing ``cost``."""
    docket = small_docket(
        {1: "[page 1 of 3, transcribed from an image]\nThe crankshaft was intact.\n"}
    )
    reading = Transcription(
        key=TranscriptionKey(
            document_sha256="d" * 64, page=1, model="m", instruction="t1", dpi=150
        ),
        status="transcribed",
        text="The crankshaft was intact.",
        cost_usd=cost,
        created=datetime(2026, 10, 1, tzinfo=UTC),
    )
    return docket.model_copy(update={"readings": {1: {1: reading}}})


def _arm_b(version: Literal["v1", "v2", "v3"], *, sync: bool = True) -> RunSpec:
    return RunSpec(
        sample="dev-400",
        arm="B",
        evidence_version=version,
        sync=sync,
        price_variant="standard" if sync else "batch",
        expected_cost_per_case_usd=0.001,
    )


def test_a_v2_run_refuses_a_v1_reader_and_a_v1_run_a_v2_reader(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Decision 0076: v2 evidence is never recorded as v1, nor the reverse; before any call."""
    client = RecordingFakeClient([GOOD, REFINE])
    docket = _transcribed_docket()
    with pytest.raises(ConfigurationError, match="v1 evidence"):
        runner(tmp_path, client, docket=FakeDocketReader(docket, "v1")).run(
            _arm_b("v2"), record_fixtures[:1]
        )
    with pytest.raises(ConfigurationError, match="v2 evidence"):
        runner(tmp_path, client, docket=FakeDocketReader(docket, "v2")).run(
            _arm_b("v1"), record_fixtures[:1]
        )
    assert client.payloads == []
    assert not (tmp_path / "runs").exists()  # refused before any run folder is claimed


def test_a_v2_run_answers_and_records_the_preparation_cost(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    reader = FakeDocketReader(_transcribed_docket(0.003), "v2")
    run = runner(tmp_path, client, docket=reader).run(_arm_b("v2"), record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.failure is None
    assert case.preparation_cost_usd == pytest.approx(0.003)
    assert run.evidence_version == "v2"
    # Decision 0081: the preparation cost is apart from the agent's own cost.
    assert run.cost_usd == pytest.approx(case.cost_usd)
    assert "transcribed from an image" in client.payloads[0].text


def test_a_v2_batch_run_records_the_preparation_cost_too(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    fake = FakeBatchClient(
        handlers=[
            lambda bid, reqs: _status(bid, reqs, GOOD),
            lambda bid, reqs: _status(bid, reqs, REFINE),
        ]
    )
    reader = FakeDocketReader(_transcribed_docket(0.004), "v2")
    run = runner(tmp_path, RecordingFakeClient([]), batch=fake, docket=reader).run(
        _arm_b("v2", sync=False), record_fixtures[:1]
    )
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.preparation_cost_usd == pytest.approx(0.004)


def test_a_v1_run_records_no_preparation_cost(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    reader = FakeDocketReader(small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"}))
    run = runner(tmp_path, client, docket=reader).run(_arm_b("v1"), record_fixtures[:1])
    (case,) = read_jsonl(tmp_path / "runs" / run.run_id / "cases.jsonl", CaseResult)
    assert case.preparation_cost_usd == 0.0


def test_v3_is_still_refused_for_arm_b(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    reader = FakeDocketReader(_transcribed_docket(), "v2")
    with pytest.raises(ConfigurationError, match="v3 is not built"):
        runner(tmp_path, client, docket=reader).run(_arm_b("v3"), record_fixtures[:1])


def test_the_cached_reader_is_v2_only_with_readings_and_passes_them_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    docket = small_docket({1: "[page 1 of 3]\nx\n"})

    def fake_read_docket(client: object, mkey: int, *, readings: object = None) -> Docket:
        captured["readings"] = readings
        return docket

    monkeypatch.setattr("ntsb_probable_cause.scoring.runner.read_docket", fake_read_docket)
    client = cast(DocketClient, object())
    assert CachedDocketReader(client).version == "v1"
    lookup = ReadingLookup(TranscriptionCache(tmp_path))
    reader = CachedDocketReader(client, readings=lookup)
    assert reader.version == "v2"
    assert reader.read(7) is docket
    assert captured["readings"] is lookup
