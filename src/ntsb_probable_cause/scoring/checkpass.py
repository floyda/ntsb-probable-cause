"""The ordering check as a post-pass over a finished run (decision 0096; plan walkthrough W2).

A finished arm B run is read; each answered case gets a second step whose hypothesis carries the
re-ordered occurrence codes; occurrence scores are recomputed and finding scores kept. The result
is a derived run folder ``<run id>-check-<way>`` that the report compares like any run. Its run
record's cost is the check's alone: the answers were paid for, and counted, in the source run.
Its prompt version is the source's with ``+check-<way>``, or ``+check-<way>-<stats>`` when the
check counts in a statistics file other than S2.7's (decision 0129). Development runs only; the
Jev ways exist for this purpose alone (decisions 0097, 0103).
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError, SchemaError
from ntsb_probable_cause.model.client import ModelClient, ModelSettings, Payload, cost_usd
from ntsb_probable_cause.model.typesafe import JEV_PINNED, TypeSafeClient
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.scoring import ordering
from ntsb_probable_cause.scoring.budget import settle
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, StatsName
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import rescore_occurrence
from ntsb_probable_cause.scoring.prompt import REJECTED
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl, write_jsonl

Way = Literal["rule", "luna", "jev", "jev2"]
# Round 1's ways, exactly as ``scripts/round1_report.py`` reads them; that report and its
# results file are not changed by the second, registered Jev check (decision 0103 item 4).
WAYS: tuple[Way, ...] = ("rule", "luna", "jev")
# Every way ``ntsb-eval check`` accepts: Round 1's, and ``jev2`` (decision 0103).
CHECK_WAYS: tuple[Way, ...] = (*WAYS, "jev2")
CHECK_TOOL = "ordering_check"
# Estimates for the budget guard (plan W3): GPT-6 Luna at the standard price, about 1,500
# prompt and 1,500 output tokens a case; Jev at its self-reported input price.
EXPECTED_COST_PER_CASE_USD: Mapping[Way, float] = {
    "rule": 0.0,
    "luna": 0.002,
    "jev": 0.0001,
    "jev2": 0.0001,
}
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
    # Anything else a way records, written into the step's ``arguments`` beside the ranking and
    # the push; empty for rule, luna and jev, so their steps are exactly as before. ``jev2``
    # records Jev's choice, confidence and every option's probability here (decision 0103),
    # because no record gains a field (a new field once broke track 2's budget checks, 42e67a7).
    details: Mapping[str, object] = field(default_factory=dict)


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
            this_system = system if attempt == 0 else f"{system}\n\n{REJECTED}{error}"
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


JEV2_UNCHANGED = "none_of_these ranked first: answer unchanged (decision 0103)"


def jev2_checker(client: TypeSafeClient, stats: CodingStats, tables: CodeTables) -> Checker:
    """The registered second Jev check (decision 0103; ``docs/rounds/s27-round1-jev2.md``).

    One request per case, one Choice named ``defining``, sent to the pinned model with the
    object state. Options are ranked by Jev's probabilities, ties by the model's own order; if
    ``none_of_these`` ranks first the answer is left unchanged. No confidence cut-off: the
    confidence is recorded, never used to decide.
    """

    def check(hypothesis: Hypothesis, group: str | None) -> CheckOutcome:
        guesses = _codes(hypothesis)
        options = ordering.candidates(guesses, group, stats)
        state = ordering.jev2_state(
            guesses, options, group, hypothesis.evidence_narrative, stats, tables
        )
        question = ordering.jev2_question(options, tables)
        exchange = client.ask_state(state, {"defining": question}, model=JEV_PINNED)
        answer = exchange.reply.choice("defining")
        tokens = exchange.reply.usage.input_tokens
        order = ordering.jev2_order(answer.probabilities, guesses, options)
        ranking = ordering.jev2_ranking(answer.probabilities, guesses, options)
        details: dict[str, object] = {
            "choice": answer.choice,
            "confidence": answer.confidence,
            # Jev's full ranked option order after the tie rules, none_of_these included: the
            # report reads "none_of_these ranked first" from this, not from dict order.
            "jev_order": list(order),
            "probabilities": {label: answer.probabilities[label] for label in order},
        }
        cost = tokens * sources.JEV.input_usd_per_mtok / 1_000_000
        fingerprint = _fingerprint(json.dumps({"state": state, "question": question}))
        if not ranking:
            return CheckOutcome(
                ranking=guesses,
                model=exchange.reply.model,
                cost_usd=cost,
                fingerprint=fingerprint,
                prompt_tokens=tokens,
                note=JEV2_UNCHANGED,
                details=details,
            )
        return CheckOutcome(
            ranking=ranking,
            model=exchange.reply.model,
            cost_usd=cost,
            fingerprint=fingerprint,
            prompt_tokens=tokens,
            toward_more_common=_toward(guesses, ranking, group, stats),
            details=details,
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
                **outcome.details,
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


# S2.7's statistics: every check made before S3 read them, and its suffix names no file.
STATS_DEFAULT: StatsName = "s27"
# The statistics arm B's tool post-pass counts in (``agent/armb.py``, ``+tools-s3``; decision
# 0129 item 4): the check over its derived run must read the same file.
TOOLS_STATS: StatsName = "s3"


def suffix(way: Way, stats: StatsName = STATS_DEFAULT) -> str:
    """What a check adds to its source's prompt version.

    ``+check-<way>`` for S2.7's statistics, so every check made before S3 keeps its label, and
    ``+check-<way>-<stats>`` for any other file, so the label says which counts the check read.
    """
    return f"+check-{way}" if stats == STATS_DEFAULT else f"+check-{way}-{stats}"


def _refuse_unless_development(record: RunRecord, cases: Sequence[CaseResult]) -> None:
    if not record.sample.startswith("dev") or "heldout" in record.run_id or record.arm != "B":
        raise ConfigurationError(
            f"the ordering check runs on development arm B runs only; {record.run_id} is "
            f"{record.sample}, arm {record.arm} (decisions 0096, 0097)"
        )
    if "-check-" in record.run_id:
        raise ConfigurationError(
            f"{record.run_id} is itself a derived check run: no stacked checks"
        )
    if record.finished is None:
        raise ConfigurationError(
            f"{record.run_id} has not finished: the check needs a complete answer for every case"
        )
    if any(c.split != "dev" for c in cases):
        raise ConfigurationError(f"{record.run_id} holds a case outside the development split")


@dataclass(frozen=True)
class Preflight:
    """Everything `check_run` would refuse, read and checked once, before any side effect.

    Fix round 2, Important: a caller who reserves a check's projected cost calls this first,
    so the reservation is only ever made once every refusal below has already passed -- the
    same "nothing refusable after the reservation" rule ``scoring/preparation.py``'s jobs
    follow.
    """

    record: RunRecord
    cases: tuple[CaseResult, ...]
    run_id: str


def preflight(
    source: Path, way: Way, runs_dir: Path, *, stats: StatsName = STATS_DEFAULT
) -> Preflight:
    """Read and refuse a source run exactly as `check_run` would, before any side effect.

    Refuses a source that isn't a finished development arm B run, that is itself a derived
    check run, or that holds a case outside the development split (`_refuse_unless_development`);
    a tool post-pass (its prompt version holds ``+tools-``) checked with statistics other than
    ``TOOLS_STATS``, the file its tools counted in (decision 0129 item 4); and a derived id whose
    folder already holds a finished check's output. Read-only: no folder is created and no
    reservation is touched, so a refusal here -- including of a source whose own id already
    contains ``-check-`` -- leaves nothing behind to clean up.
    """
    record = read_jsonl(source / "run.jsonl", RunRecord)[0]
    cases = read_jsonl(source / "cases.jsonl", CaseResult)
    _refuse_unless_development(record, cases)
    if "+tools-" in record.prompt_version and stats != TOOLS_STATS:
        raise ConfigurationError(
            f"{record.run_id} is arm B's tool post-pass, whose tools counted in the "
            f"{TOOLS_STATS} statistics: its ordering check reads the same file, so pass "
            f"--stats {TOOLS_STATS}, not {stats} (decision 0129 item 4)"
        )
    run_id = derived_id(record.run_id, way)
    folder = runs_dir / run_id
    if (folder / "cases.jsonl").exists() or (folder / "run.jsonl").exists():
        raise ConfigurationError(
            f"{run_id} exists: a check is run once per source run; if this is a dead pass "
            f"(one that died mid-write, leaving a partial cases.jsonl/run.jsonl), delete "
            f"{folder} by hand and try again"
        )
    return Preflight(record=record, cases=tuple(cases), run_id=run_id)


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
    stats: StatsName = STATS_DEFAULT,
) -> RunRecord:
    """Run the check over a finished run; write and return the derived run's record.

    Calls :func:`preflight` itself (fix round 2): a caller that already reserved a budget
    against this pass has necessarily called it first and found nothing to refuse, so this is
    defence in depth, not the first line -- it will not fire in the normal CLI path. ``stats``
    names the statistics ``checker`` counts in; the derived prompt version records it
    (:func:`suffix`), and a tool post-pass's check must name ``TOOLS_STATS``.
    """
    pre = preflight(source, way, runs_dir, stats=stats)
    cases = pre.cases
    run_id = pre.run_id
    folder = runs_dir / run_id
    # `exist_ok=True`, not an atomic claim (fix round 1, Important 1): the caller may have
    # already created this folder to hold a budget reservation (`reserve_within_budget`,
    # under this same derived id) before any client is built. `preflight` just confirmed
    # neither of this folder's own output files exists yet.
    folder.mkdir(parents=True, exist_ok=True)
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
        derived = pre.record.model_copy(
            update={
                "run_id": run_id,
                "prompt_version": f"{pre.record.prompt_version}{suffix(way, stats)}",
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
        # Settled here, not by the caller (fix round 1, Important 1): a reservation the
        # caller made under this derived id is released the moment its actual spend is on
        # disk, whether the pass finished or was interrupted; a `rule` pass never reserved
        # one, and `settle` is a no-op then.
        settle(runs_dir, run_id)
    return derived
