"""One evaluation run: cases → payloads → answering pass → scored results (spec §6)."""

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Protocol

from ntsb_probable_cause import sources
from ntsb_probable_cause.data.build import investigation_class
from ntsb_probable_cause.errors import (
    BudgetError,
    ConfigurationError,
    LeakageError,
    ModelError,
    SchemaError,
)
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.batch import BatchRequest, BatchResult, BatchStatus
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    cost_usd,
)
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import (
    HYPOTHESIS_SCHEMA,
    REFINEMENT_SCHEMA,
    Hypothesis,
    parse_hypothesis,
    parse_refinement,
)
from ntsb_probable_cause.scoring.ledger import append_row, refuse_if_heldout_and_dirty
from ntsb_probable_cause.scoring.metrics import CaseScores, score_case
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    RunRecord,
    StepRecord,
    fingerprint,
    write_jsonl,
)
from ntsb_probable_cause.scoring.samples import arm_exclusions
from ntsb_probable_cause.splits import Split, split_of


@dataclass(frozen=True)
class RunSpec:
    """Everything that varies between runs (spec §2)."""

    sample: str
    arm: Literal["A", "ceiling"]
    exclusions: frozenset[EvidenceRole] = frozenset()
    include_case_number: bool = False
    model: str = "openai/gpt-5.6-luna"
    price_variant: Literal["batch", "standard"] = "batch"
    cap_usd: float = 0.05
    budget_usd: float = 25.0
    sync: bool = False
    expected_cost_per_case_usd: float | None = None


class BatchRunner(Protocol):
    """The subset of ``BatchClient`` the runner uses.

    A ``Protocol`` rather than importing ``BatchClient`` directly, so a scripted fake batch
    client can stand in structurally without inheriting from the real one (controller
    resolution 2 for Task 11).
    """

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        """Submit one batch of requests and return its id."""
        ...

    def wait(
        self, batch_id: str, *, on_status: Callable[[str], None] = lambda _s: None
    ) -> BatchStatus:
        """Poll until the batch is terminal."""
        ...


def project_cost(spec: RunSpec, cases: int) -> float:
    """Cases times the measured cost per case, or the cap where there is no measurement (0030)."""
    per_case = (
        spec.expected_cost_per_case_usd
        if spec.expected_cost_per_case_usd is not None
        else spec.cap_usd
    )
    return cases * per_case


def refuse_over_budget(projected: float, month_spent: float, budget: float) -> None:
    """Refuse a run that would take the month past its budget."""
    if month_spent + projected > budget:
        raise BudgetError(
            f"projected ${projected:.2f} plus ${month_spent:.2f} spent "
            f"exceeds the ${budget:.2f} budget"
        )


def _settings(spec: RunSpec, schema: dict[str, object], name: str) -> ModelSettings:
    """Model settings for one call; ``schema`` and ``name`` vary between the two stages."""
    return ModelSettings(
        model=spec.model, price_variant=spec.price_variant, json_schema=schema, schema_name=name
    )


def _sample_split(sample: str) -> Split:
    """The split a sample name implies, from its prefix (``dev-400``, ``heldout-40``, ...)."""
    if sample.startswith("dev"):
        return Split.DEV
    if sample.startswith("heldout"):
        return Split.HELDOUT
    return Split.OPEN


def case_payload(
    raw: Mapping[str, object], spec: RunSpec, tables: CodeTables
) -> tuple[Payload, str, Verdict, Evidence]:
    """The only route to a payload; the case-number line exists on development cases alone.

    The probe is refused unless *both* the run's sample name implies development and the
    record's own event date falls in the development split (spec §6.2: "development split
    only, refused on any other sample"). Checking the sample alone would let a run labelled
    ``dev-400`` leak a case number on a record that is not actually a development case;
    checking the date alone would not refuse a run explicitly requested against a held-out
    sample when it is (as in this module's own tests) handed a development-dated record.
    """
    evidence, _, verdict = split_record(raw, exclude=spec.exclusions | arm_exclusions(spec.arm))
    payload = Payload.from_evidence(evidence)
    case_number: str | None = None
    if spec.include_case_number:
        event = date.fromisoformat(str(raw["eventDate"])[:10])
        if _sample_split(spec.sample) is not Split.DEV or split_of(event) is not Split.DEV:
            raise LeakageError(
                f"{evidence.case_id}: the case number may be included on development cases only"
            )
        case_number = evidence.case_id
    system = f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables, case_number=case_number)}"
    return payload, system, verdict, evidence


def over_cap(payload_text: str, system: str, spec: RunSpec) -> bool:
    """Would the prompt alone, at one token per four characters, cost more than the cap?"""
    price = sources.price_of(_settings(spec, HYPOTHESIS_SCHEMA, "hypothesis").model_id())
    estimated_tokens = (len(payload_text) + len(system)) / 4
    return estimated_tokens * price.input_usd_per_mtok / 1e6 > spec.cap_usd


@dataclass
class _CaseContext:
    """Per-case working state, kept from the payload build until the case has a result.

    ``stage1_content`` pins the *accepted* stage-1 reply's text once, for the stage-2 turn's
    history: a batch run may resubmit stage 2 as a retry batch, and ``replies[-1]`` at that
    point is the *rejected* stage-2 reply, not the stage-1 hypothesis (fix round 1, Important
    1). The sync path pins the same content into a local ``history`` tuple and reuses it for
    both stage-2 attempts, so it never had this bug.
    """

    raw: Mapping[str, object]
    evidence: Evidence
    verdict: Verdict
    payload: Payload
    system: str
    spec: RunSpec
    replies: list[ModelReply] = field(default_factory=list)
    stage1_content: str | None = None


@dataclass
class _BatchRun:
    """Mutable state threaded through one batch answering pass (spec §7.2).

    ``costs`` holds one entry per batch submitted, in order, ``None`` where that batch did
    not report a cost — so the caller can tell a genuine total from a partial one (fix round
    1, Minor 4) instead of silently summing only the batches that happened to report.
    """

    folder: Path
    contexts: dict[str, _CaseContext] = field(default_factory=dict)
    results: dict[str, CaseResult] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    hyps: dict[str, Hypothesis] = field(default_factory=dict)
    finals: dict[str, Hypothesis] = field(default_factory=dict)
    batch_ids: list[str] = field(default_factory=list)
    costs: list[float | None] = field(default_factory=list)


class Runner:
    """Runs one RunSpec over raw records and writes the records (spec §6.4)."""

    def __init__(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        client: ModelClient,
        *,
        batch: BatchRunner | None,
        tables: CodeTables,
        seen_pairs: frozenset[str],
        runs_dir: Path,
        ledger_path: Path,
        month_spent_usd: float,
        commit: tuple[str, bool],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._batch = batch
        self._tables = tables
        self._seen = seen_pairs
        self._runs_dir = runs_dir
        self._ledger = ledger_path
        self._spent = month_spent_usd
        self._sha, self._dirty = commit
        self._now = now

    def run(self, spec: RunSpec, raws: Sequence[Mapping[str, object]]) -> RunRecord:
        """Run every case, write three JSON-lines files, append the ledger for held-out samples.

        On any exception once answering has started — a batch ending badly, a
        ``LeakageError`` partway through a sync run, anything — the cases and cost paid so
        far are still written (``finished=None`` marks the run incomplete) before the
        exception is re-raised, so a crashed run's spend is never invisible to the next
        run's budget check (fix round 1, Important 2).
        """
        refuse_if_heldout_and_dirty(spec.sample, self._dirty)
        refuse_over_budget(project_cost(spec, len(raws)), self._spent, spec.budget_usd)
        started = self._now()
        run_id = f"{started:%Y%m%dT%H%M%S}-{self._sha}-{spec.sample}-{spec.arm}"
        folder = self._runs_dir / run_id
        results: list[CaseResult] = []
        batch_ids: tuple[str, ...] = ()
        reported_batch_cost: float | None = None

        def build_record(finished: datetime | None) -> RunRecord:
            return RunRecord(
                run_id=run_id,
                sample=spec.sample,
                arm=spec.arm,
                exclusions=tuple(sorted(e.value for e in spec.exclusions)),
                includes=("case_number",) if spec.include_case_number else (),
                prompt_version=prompt.PROMPT_VERSION,
                model=spec.model,
                price_variant=spec.price_variant,
                cap_usd=spec.cap_usd,
                budget_usd=spec.budget_usd,
                commit_sha=self._sha,
                dirty=self._dirty,
                started=started,
                finished=finished,
                batch_ids=batch_ids,
                cases=len(results),
                cost_usd=sum(r.cost_usd for r in results),
                reported_batch_cost_usd=reported_batch_cost,
            )

        try:
            if spec.sync:
                for raw in raws:
                    results.append(self._answer_case(raw, spec))
            else:
                batch_run = _BatchRun(folder=folder)
                try:
                    self._answer_batch(raws, spec, batch_run)
                finally:
                    results = [
                        batch_run.results[cid]
                        for cid in batch_run.order
                        if cid in batch_run.results
                    ]
                    batch_ids = tuple(batch_run.batch_ids)
                    reported_batch_cost = self._reported_total(batch_run.costs)
        except Exception:
            self._write_files(folder, results)
            write_jsonl(folder / "run.jsonl", [build_record(None)])
            raise

        self._write_files(folder, results)
        record = build_record(self._now())
        write_jsonl(folder / "run.jsonl", [record])
        if spec.sample.startswith("heldout"):
            append_row(self._ledger, record, str(folder / "cases.jsonl"))
        return record

    # --- shared helpers (sync and batch) ---

    @staticmethod
    def _write_files(folder: Path, results: Sequence[CaseResult]) -> None:
        """cases.jsonl and steps.jsonl; called both on success and on a mid-run abort."""
        write_jsonl(folder / "cases.jsonl", results)
        write_jsonl(folder / "steps.jsonl", (s for r in results for s in r.steps))

    @staticmethod
    def _reported_total(costs: Sequence[float | None]) -> float | None:
        """Sum of batch-level reported costs; ``None`` if any batch stayed silent (Minor 4)."""
        if not costs or any(c is None for c in costs):
            return None
        return sum(c for c in costs if c is not None)

    def _cost(self, replies: Sequence[ModelReply], spec: RunSpec) -> float:
        """Dollars for a case, summed over every reply obtained for it (even failed ones)."""
        settings = _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis")
        return sum(cost_usd(reply, settings)[0] for reply in replies)

    def _step(self, ctx: _CaseContext, hypothesis: Hypothesis, cost: float) -> StepRecord:
        return StepRecord(
            case_id=ctx.evidence.case_id,
            step=0,
            arm=ctx.spec.arm,
            condition="full",
            day=None,
            tool="none",
            arguments={},
            reason="",
            expected_effect="",
            returned_roles=tuple(sorted(ctx.payload.fields())),
            not_available=(),
            payload_fingerprint=fingerprint(ctx.payload),
            hypothesis=hypothesis,
            observed_effect="",
            stop_reason="abstained" if hypothesis.abstain else "answered",
            model=ctx.spec.model,
            price_variant=ctx.spec.price_variant,
            prompt_tokens=sum(r.usage.prompt_tokens for r in ctx.replies),
            completion_tokens=sum(r.usage.completion_tokens for r in ctx.replies),
            cost_usd=cost,
            cumulative_cost_usd=cost,
            commit_sha=self._sha,
            dirty=self._dirty,
        )

    def _case_result(
        self,
        ctx: _CaseContext,
        steps: tuple[StepRecord, ...],
        scores: CaseScores | None,
        cost: float,
        failure: str | None,
    ) -> CaseResult:
        event = date.fromisoformat(str(ctx.raw["eventDate"])[:10])
        flavour = ctx.raw.get("factualFinalReportFlavor")
        return CaseResult(
            case_id=ctx.evidence.case_id,
            split=split_of(event).value,
            fatal=ctx.raw.get("highestInjuryLevel") == "Fatal",
            investigation_class=investigation_class(ctx.evidence.case_id),
            report_flavour=str(flavour) if flavour is not None else None,
            verdict_occurrence=ctx.verdict.occurrence_codes,
            verdict_findings=ctx.verdict.finding_codes,
            verdict_findings_in_cause=ctx.verdict.finding_codes_in_cause,
            steps=steps,
            scores=scores,
            cost_usd=cost,
            failure=failure,
        )

    def _failed(
        self, ctx: _CaseContext, failure: str, cost: float, steps: tuple[StepRecord, ...] = ()
    ) -> CaseResult:
        return self._case_result(ctx, steps, None, cost, failure)

    def _result(
        self, ctx: _CaseContext, steps: tuple[StepRecord, ...], scores: CaseScores, cost: float
    ) -> CaseResult:
        return self._case_result(ctx, steps, scores, cost, None)

    # --- the sync path ---

    def _answer_case(self, raw: Mapping[str, object], spec: RunSpec) -> CaseResult:
        payload, system, verdict, evidence = case_payload(raw, spec, self._tables)
        ctx = _CaseContext(
            raw=raw, evidence=evidence, verdict=verdict, payload=payload, system=system, spec=spec
        )
        if over_cap(payload.text, system, spec):
            return self._failed(ctx, "cap", 0.0)
        hypothesis: Hypothesis | None = None
        failure: str | None = None
        try:
            hypothesis = self._two_turns(ctx)
        except SchemaError as error:
            failure = f"schema: {error}"
        except ModelError as error:
            failure = f"model: {error}"
        cost = self._cost(ctx.replies, spec)
        if failure is not None or hypothesis is None:
            return self._failed(ctx, failure or "model: no reply", cost)
        scores = score_case(hypothesis, verdict, self._tables, seen_pairs=self._seen)
        step = self._step(ctx, hypothesis, cost)
        return self._result(ctx, (step,), scores, cost)

    def _two_turns(self, ctx: _CaseContext) -> Hypothesis:
        """Stage 1 then stage 2, each with one retry on a schema error.

        ``ctx.replies`` is appended to as calls are made, including calls that end up
        failing, so the caller can still price a case that never produced a usable answer
        (controller resolution: the brief's version returned replies only on success, which
        recorded $0 for a case that made two real calls and failed both — see the Deviations
        log).
        """
        spec, payload, system = ctx.spec, ctx.payload, ctx.system
        first = self._client.complete(
            payload, _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis"), system=system
        )
        ctx.replies.append(first)
        try:
            hypothesis = parse_hypothesis(first.content or "", self._tables)
        except SchemaError as error:
            retry = self._client.complete(
                payload,
                _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis"),
                system=f"{system}\n\nYour previous reply was rejected: {error}",
            )
            ctx.replies.append(retry)
            hypothesis = parse_hypothesis(retry.content or "", self._tables)
        if hypothesis.abstain or not hypothesis.findings:
            return hypothesis
        history = (Turn(role="assistant", content=ctx.replies[-1].content),)
        refine_system = (
            f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(hypothesis, self._tables)}"
        )
        second = self._client.complete(
            payload,
            _settings(spec, REFINEMENT_SCHEMA, "refinement"),
            system=refine_system,
            history=history,
        )
        ctx.replies.append(second)
        try:
            return parse_refinement(second.content or "", self._tables, hypothesis)
        except SchemaError as error:
            retry = self._client.complete(
                payload,
                _settings(spec, REFINEMENT_SCHEMA, "refinement"),
                system=f"{refine_system}\n\nYour previous reply was rejected: {error}",
                history=history,
            )
            ctx.replies.append(retry)
            return parse_refinement(retry.content or "", self._tables, hypothesis)

    # --- the batch path ---

    @staticmethod
    def _log_status(stage: str, batch_id: str, status: str) -> None:
        """One line of batch status, to stderr, never stdout (controller resolution 7)."""
        sys.stderr.write(f"{stage} {batch_id}: {status}\n")

    def _record_batch_id(self, folder: Path, batch_id: str, stage: str) -> None:
        """Append the batch id before waiting (spec §7.2: an interrupted run can resume)."""
        folder.mkdir(parents=True, exist_ok=True)
        row = {"batch_id": batch_id, "stage": stage, "time": self._now().isoformat()}
        with (folder / "batches.jsonl").open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    def _submit_and_wait(
        self, requests: Sequence[BatchRequest], run: _BatchRun, stage: str
    ) -> BatchStatus:
        """Submit one batch, record its id, wait for a terminal status; status to stderr."""
        if self._batch is None:
            raise ConfigurationError("a batch client is required for a non-sync run")
        batch_id = self._batch.submit(requests)
        self._record_batch_id(run.folder, batch_id, stage)
        status = self._batch.wait(
            batch_id,
            on_status=lambda s: self._log_status(stage, batch_id, s),
        )
        if status.status != "completed":
            raise ModelError(f"batch {batch_id} ended {status.status}")
        return status

    def _answer_batch(
        self, raws: Sequence[Mapping[str, object]], spec: RunSpec, run: _BatchRun
    ) -> None:
        """Two batches (stage 1, stage 2), each with one retry batch on failures (spec §7.2).

        Populates ``run`` in place rather than returning, so the caller (``Runner.run``)
        still has ``run.results``/``run.order``/``run.batch_ids``/``run.costs`` to write a
        partial run from if this raises partway through (fix round 1, Important 2).
        """
        self._prepare_contexts(raws, spec, run)
        try:
            self._stage1(run)
            stage2_ids = [cid for cid, h in run.hyps.items() if not (h.abstain or not h.findings)]
            for cid, hypothesis in run.hyps.items():
                if cid not in stage2_ids:
                    self._finish_case(cid, hypothesis, run)
            if stage2_ids:
                self._stage2(stage2_ids, run)
        except Exception as error:
            self._abort_unresolved(run, error)
            raise

    def _abort_unresolved(self, run: _BatchRun, error: BaseException) -> None:
        """Give every case with no result yet one, priced from whatever it already cost.

        Reached when a batch ends ``expired``/``failed``/``cancelled`` (or any other
        exception) partway through a run: cases that already had a stage-1 (or stage-2)
        reply billed to them keep that cost instead of it vanishing (fix round 1,
        Important 2).
        """
        for case_id, ctx in run.contexts.items():
            if case_id not in run.results:
                cost = self._cost(ctx.replies, ctx.spec)
                run.results[case_id] = self._failed(ctx, f"aborted: {error}", cost)

    def _prepare_contexts(
        self, raws: Sequence[Mapping[str, object]], spec: RunSpec, run: _BatchRun
    ) -> None:
        for raw in raws:
            payload, system, verdict, evidence = case_payload(raw, spec, self._tables)
            run.order.append(evidence.case_id)
            ctx = _CaseContext(
                raw=raw,
                evidence=evidence,
                verdict=verdict,
                payload=payload,
                system=system,
                spec=spec,
            )
            if over_cap(payload.text, system, spec):
                run.results[evidence.case_id] = self._failed(ctx, "cap", 0.0)
                continue
            run.contexts[evidence.case_id] = ctx

    def _finish_case(self, case_id: str, hypothesis: Hypothesis, run: _BatchRun) -> None:
        ctx = run.contexts[case_id]
        scores = score_case(hypothesis, ctx.verdict, self._tables, seen_pairs=self._seen)
        cost = self._cost(ctx.replies, ctx.spec)
        step = self._step(ctx, hypothesis, cost)
        run.results[case_id] = self._result(ctx, (step,), scores, cost)

    def _fail_case(self, case_id: str, failure: str, run: _BatchRun) -> None:
        ctx = run.contexts[case_id]
        cost = self._cost(ctx.replies, ctx.spec)
        run.results[case_id] = self._failed(ctx, failure, cost)

    def _stage1(self, run: _BatchRun) -> None:
        ids = [cid for cid in run.contexts if cid not in run.results]
        need_retry = self._run_stage1_pass(ids, run, "stage1", errors={})
        if need_retry:
            # The retry pass's own return value carries the retry's own error text, not
            # pass 1's — using ``need_retry`` here instead would file a case that failed
            # with a model error on retry as "schema: ..." from the first attempt (fix
            # round 1, Minor 5).
            still_failing = self._run_stage1_pass(
                list(need_retry), run, "stage1-retry", errors=need_retry
            )
            for cid, error in still_failing.items():
                if cid not in run.hyps and cid not in run.results:
                    self._fail_case(cid, error, run)

    def _run_stage1_pass(
        self, ids: Sequence[str], run: _BatchRun, stage: str, *, errors: dict[str, str]
    ) -> dict[str, str]:
        """One stage-1 batch (first pass or retry); returns ids still needing a retry, with why."""
        if not ids:
            return {}
        requests = [
            BatchRequest(
                custom_id=cid,
                payload=run.contexts[cid].payload,
                settings=_settings(run.contexts[cid].spec, HYPOTHESIS_SCHEMA, "hypothesis"),
                system=self._retry_system(run.contexts[cid].system, errors.get(cid)),
            )
            for cid in ids
        ]
        status = self._submit_and_wait(requests, run, stage)
        run.batch_ids.append(status.batch_id)
        run.costs.append(status.reported_cost_usd)
        by_id = {r.custom_id: r for r in status.results}
        need_retry: dict[str, str] = {}
        for cid in ids:
            result = by_id.get(cid)
            if result is None or result.reply is None:
                need_retry[cid] = self._reply_error(result)
                continue
            run.contexts[cid].replies.append(result.reply)
            try:
                hypothesis = parse_hypothesis(result.reply.content or "", self._tables)
            except SchemaError as error:
                need_retry[cid] = f"schema: {error}"
            else:
                run.hyps[cid] = hypothesis
                # Pinned once, so a stage-2 retry batch replays the accepted stage-1
                # content, never a rejected stage-2 reply (fix round 1, Important 1).
                run.contexts[cid].stage1_content = result.reply.content
        return need_retry

    def _stage2(self, ids: list[str], run: _BatchRun) -> None:
        need_retry = self._run_stage2_pass(ids, run, "stage2", errors={})
        if need_retry:
            # Same fix as _stage1: use the retry pass's own errors, not pass 1's (Minor 5).
            still_failing = self._run_stage2_pass(
                list(need_retry), run, "stage2-retry", errors=need_retry
            )
            for cid, error in still_failing.items():
                if cid not in run.finals:
                    self._fail_case(cid, error, run)
        for cid, hypothesis in run.finals.items():
            self._finish_case(cid, hypothesis, run)

    def _run_stage2_pass(
        self, ids: Sequence[str], run: _BatchRun, stage: str, *, errors: dict[str, str]
    ) -> dict[str, str]:
        """One stage-2 batch (first pass or retry); returns ids still needing a retry, with why."""
        if not ids:
            return {}
        requests = [
            BatchRequest(
                custom_id=cid,
                payload=run.contexts[cid].payload,
                settings=_settings(run.contexts[cid].spec, REFINEMENT_SCHEMA, "refinement"),
                system=self._stage2_system(run.hyps[cid], errors.get(cid)),
                # The accepted stage-1 content, pinned in _run_stage1_pass — never
                # ``replies[-1]``, which on a stage-2 retry pass is the *rejected* stage-2
                # reply, not the stage-1 hypothesis (fix round 1, Important 1).
                history=(Turn(role="assistant", content=run.contexts[cid].stage1_content),),
            )
            for cid in ids
        ]
        status = self._submit_and_wait(requests, run, stage)
        run.batch_ids.append(status.batch_id)
        run.costs.append(status.reported_cost_usd)
        by_id = {r.custom_id: r for r in status.results}
        need_retry: dict[str, str] = {}
        for cid in ids:
            result = by_id.get(cid)
            if result is None or result.reply is None:
                need_retry[cid] = self._reply_error(result)
                continue
            run.contexts[cid].replies.append(result.reply)
            try:
                run.finals[cid] = parse_refinement(
                    result.reply.content or "", self._tables, run.hyps[cid]
                )
            except SchemaError as error:
                need_retry[cid] = f"schema: {error}"
        return need_retry

    @staticmethod
    def _reply_error(result: BatchResult | None) -> str:
        """The ``model:`` failure text for a batch result with no usable reply."""
        error = result.error if result is not None else None
        return f"model: {error if error else 'no reply'}"

    @staticmethod
    def _retry_system(system: str, error: str | None) -> str:
        if error is None:
            return system
        return f"{system}\n\nYour previous reply was rejected: {error}"

    def _stage2_system(self, hypothesis: Hypothesis, error: str | None) -> str:
        base = f"{prompt.SYSTEM_REFINE}\n\n"
        if error is not None:
            base += f"Your previous reply was rejected: {error}\n\n"
        return base + prompt.refine_message(hypothesis, self._tables)
