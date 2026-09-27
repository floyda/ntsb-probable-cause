"""The ordering check as a post-pass over a finished run (decision 0096; plan walkthrough W2).

A finished arm B run is read; each answered case gets a second step whose hypothesis carries the
re-ordered occurrence codes; occurrence scores are recomputed and finding scores kept. The result
is a derived run folder ``<run id>-check-<way>`` that the report compares like any run. Its run
record's cost is the check's alone: the answers were paid for, and counted, in the source run.
Development runs only; the Jev way exists for this purpose alone (decision 0097).
"""

import hashlib
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError, SchemaError
from ntsb_probable_cause.model.client import ModelClient, ModelSettings, Payload, cost_usd
from ntsb_probable_cause.model.typesafe import TypeSafeClient
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.scoring import ordering
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import rescore_occurrence
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl, write_jsonl

Way = Literal["rule", "luna", "jev"]
WAYS: tuple[Way, ...] = ("rule", "luna", "jev")
CHECK_TOOL = "ordering_check"
# Estimates for the budget guard (plan W3): GPT-6 Luna at the standard price, about 1,500
# prompt and 1,500 output tokens a case; Jev at its self-reported input price.
EXPECTED_COST_PER_CASE_USD: Mapping[Way, float] = {"rule": 0.0, "luna": 0.002, "jev": 0.0001}
MAX_OUTPUT_TOKENS = 4000


@dataclass(frozen=True)
class CheckOutcome:
    """One case's check: the ranking, who made it, and what it cost."""

    ranking: tuple[str, ...]
    model: str
    cost_usd: float
    fingerprint: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    note: str = ""
    # Decision 0101: whether the first code moved toward a more common option in the group.
    toward_more_common: bool = False


Checker = Callable[[Hypothesis, str | None], CheckOutcome]


def _codes(hypothesis: Hypothesis) -> tuple[str, ...]:
    return tuple(g.phase + g.event for g in hypothesis.occurrence)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _toward(
    guesses: Sequence[str], ranking: Sequence[str], group: str | None, stats: CodingStats
) -> bool:
    return ordering.toward_more_common(guesses[0], ranking[0], group, stats)


def rule_checker(stats: CodingStats) -> Checker:
    """The free way: :func:`ordering.plain_rule` (clear habits only, decision 0101)."""

    def check(hypothesis: Hypothesis, group: str | None) -> CheckOutcome:
        guesses = _codes(hypothesis)
        ranking = ordering.plain_rule(guesses, group, stats)
        return CheckOutcome(
            ranking=ranking,
            model="rule",
            cost_usd=0.0,
            fingerprint=_fingerprint(f"{guesses}|{group}"),
            toward_more_common=_toward(guesses, ranking, group, stats),
        )

    return check


def luna_checker(
    client: ModelClient,
    stats: CodingStats,
    tables: CodeTables,
    *,
    model: str = sources.DEFAULT_MODEL,
    reasoning_effort: sources.ReasoningEffort | None = sources.DEFAULT_REASONING_EFFORT,
) -> Checker:
    """GPT-6 Luna asked, synchronously at the standard price (plan W3); one retry."""
    settings = ModelSettings(
        model=model,
        price_variant="standard",
        reasoning_effort=reasoning_effort,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        json_schema=ordering.RANKING_SCHEMA,
        schema_name="ranking",
    )
    empty = Payload.from_evidence(Evidence(case_id="check", docket_url=None))

    def check(hypothesis: Hypothesis, group: str | None) -> CheckOutcome:
        guesses = _codes(hypothesis)
        options = ordering.candidates(guesses, group, stats)
        text = ordering.check_text(
            guesses, options, group, hypothesis.evidence_narrative, stats, tables
        )
        system = f"{ordering.CHECK_SYSTEM}\n\n{text}"
        spent = 0.0
        prompt = completion = 0
        error: SchemaError | None = None
        for attempt in range(2):
            this_system = (
                system if attempt == 0 else f"{system}\n\nYour previous reply was rejected: {error}"
            )
            reply = client.complete(empty, settings, system=this_system)
            spent += cost_usd(reply, settings)[0]
            prompt += reply.usage.prompt_tokens
            completion += reply.usage.completion_tokens
            try:
                ranking = ordering.parse_ranking(reply.content or "", options)
            except SchemaError as caught:
                error = caught
                continue
            return CheckOutcome(
                ranking,
                model,
                spent,
                _fingerprint(system),
                prompt,
                completion,
                toward_more_common=_toward(guesses, ranking, group, stats),
            )
        return CheckOutcome(
            guesses,
            model,
            spent,
            _fingerprint(system),
            prompt,
            completion,
            note=f"check failed, answer unchanged: {error}",
        )

    return check


def jev_checker(client: TypeSafeClient, stats: CodingStats, tables: CodeTables) -> Checker:
    """Jev asked, one Choice over the candidates (decision 0097)."""

    def check(hypothesis: Hypothesis, group: str | None) -> CheckOutcome:
        guesses = _codes(hypothesis)
        options = ordering.candidates(guesses, group, stats)
        text = ordering.check_text(
            guesses, options, group, hypothesis.evidence_narrative, stats, tables
        )
        exchange = client.ask_state(text, {"defining": ordering.jev_question(options, tables)})
        answer = exchange.reply.choice("defining")
        tokens = exchange.reply.usage.input_tokens
        ranking = ordering.ranking_from_probabilities(answer.probabilities)
        return CheckOutcome(
            ranking=ranking,
            model=exchange.reply.model,
            cost_usd=tokens * sources.JEV.input_usd_per_mtok / 1_000_000,
            fingerprint=_fingerprint(text),
            prompt_tokens=tokens,
            toward_more_common=_toward(guesses, ranking, group, stats),
        )

    return check


def checked_case(
    case: CaseResult,
    outcome: CheckOutcome,
    *,
    seen_pairs: AbstractSet[str],
    commit: tuple[str, bool],
) -> CaseResult:
    """The case with the check's step appended and its occurrence scores recomputed."""
    last = case.steps[-1]
    hypothesis = ordering.reorder(last.hypothesis, outcome.ranking)
    step = last.model_copy(
        update={
            "step": last.step + 1,
            "tool": CHECK_TOOL,
            "arguments": {
                "ranking": list(outcome.ranking),
                "toward_more_common": outcome.toward_more_common,
            },
            "reason": outcome.note,
            "returned_roles": (),
            "documents_attached": (),
            "documents_not_read": (),
            "payload_fingerprint": outcome.fingerprint,
            "hypothesis": hypothesis,
            "model": outcome.model,
            "price_variant": "standard",
            "prompt_tokens": outcome.prompt_tokens,
            "completion_tokens": outcome.completion_tokens,
            "reasoning_tokens": None,
            "reply_completion_tokens": (),
            "reply_reasoning_tokens": (),
            "reply_finish_reasons": (),
            "cost_usd": outcome.cost_usd,
            "cumulative_cost_usd": last.cumulative_cost_usd + outcome.cost_usd,
            "commit_sha": commit[0],
            "dirty": commit[1],
        }
    )
    if case.scores is None:
        raise ValueError(f"{case.case_id}: check_run passes scored cases only")
    scores = rescore_occurrence(
        case.scores, _codes(hypothesis), case.verdict_occurrence, seen_pairs=seen_pairs
    )
    return case.model_copy(
        update={
            "steps": (*case.steps, step),
            "scores": scores,
            "cost_usd": case.cost_usd + outcome.cost_usd,
        }
    )


def derived_id(run_id: str, way: Way) -> str:
    """The derived run's id."""
    return f"{run_id}-check-{way}"


def _refuse_unless_development(record: RunRecord, cases: Sequence[CaseResult]) -> None:
    if not record.sample.startswith("dev") or "heldout" in record.run_id or record.arm != "B":
        raise ConfigurationError(
            f"the ordering check runs on development arm B runs only; {record.run_id} is "
            f"{record.sample}, arm {record.arm} (decisions 0096, 0097)"
        )
    if any(c.split != "dev" for c in cases):
        raise ConfigurationError(f"{record.run_id} holds a case outside the development split")


def check_run(  # noqa: PLR0913 -- each argument is a separate input the tests vary.
    source: Path,
    way: Way,
    checker: Checker,
    *,
    runs_dir: Path,
    groups: Mapping[str, str | None],
    seen_pairs: AbstractSet[str],
    commit: tuple[str, bool],
    now: Callable[[], datetime],
) -> RunRecord:
    """Run the check over a finished run; write and return the derived run's record."""
    record = read_jsonl(source / "run.jsonl", RunRecord)[0]
    cases = read_jsonl(source / "cases.jsonl", CaseResult)
    _refuse_unless_development(record, cases)
    run_id = derived_id(record.run_id, way)
    folder = runs_dir / run_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ConfigurationError(f"{run_id} exists: a check is run once per source run") from error
    started = now()
    results: list[CaseResult] = []
    spent = 0.0
    finished: datetime | None = None
    try:
        for case in cases:
            if case.scores is None or not case.steps or case.steps[-1].hypothesis.abstain:
                results.append(case)
                continue
            outcome = checker(case.steps[-1].hypothesis, groups.get(case.case_id))
            spent += outcome.cost_usd
            results.append(checked_case(case, outcome, seen_pairs=seen_pairs, commit=commit))
        finished = now()
    finally:
        write_jsonl(folder / "cases.jsonl", results)
        derived = record.model_copy(
            update={
                "run_id": run_id,
                "prompt_version": f"{record.prompt_version}+check-{way}",
                "commit_sha": commit[0],
                "dirty": commit[1],
                "started": started,
                "finished": finished,
                "batch_ids": (),
                "cases": len(results),
                "cost_usd": spent,
                "reported_batch_cost_usd": None,
            }
        )
        write_jsonl(folder / "run.jsonl", [derived])
    return derived
