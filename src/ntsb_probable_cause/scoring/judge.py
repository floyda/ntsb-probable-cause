"""The judge: labels for the prose outputs, validated before use, never a bar (decision 0028).

This is the only module that renders withheld text for a model. It builds an empty Payload and
carries everything in the system prompt, so the Payload invariant of S0 is untouched and the
boundary test can name this path.
"""

import json
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    cost_usd,
)
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, strict_schema
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.runner import RunSpec, project_cost, refuse_over_budget

JUDGE_MODEL = "anthropic/claude-haiku-4.5"
# Fix round 1 (Task 13, Important 1): the controller's own measured judge cost per case,
# batch and standard, used as the projection `judge_run` refuses over budget with when the
# caller has no better number (mirrors the runner's `project_cost`/`cap_usd` fallback, 0030).
JUDGE_EXPECTED_COST_PER_CASE_USD: dict[Literal["batch", "standard"], float] = {
    "batch": 0.0004,
    "standard": 0.00089,
}
SYSTEM_JUDGE = """You are grading an analyst's written outputs against the official record. \
Return labels only.
narrative: is the analyst's evidence narrative consistent with the official factual \
narrative, does it contradict it, or does it add facts the official narrative does not \
support?
cause: does the analyst's probable cause name the same cause as the official one, a \
related one, or a different one?
lay: does the lay explanation explain, in plain language, the codes the analyst chose?
Reply only with JSON matching the schema."""


class JudgeLabels(BaseModel):
    """The three labels the judge returns (spec §8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    narrative: Literal["consistent", "contradicts", "adds_unsupported_facts"]
    cause: Literal["same_cause", "related", "different"]
    lay: Literal["explains_chosen_codes", "does_not"]


JUDGE_SCHEMA: dict[str, object] = strict_schema(JudgeLabels)


def judge_text(
    hypothesis: Hypothesis, synthesis: Synthesis, verdict: Verdict, tables: CodeTables
) -> str:
    """The comparison text: withheld narrative and cause beside the analyst's outputs.

    The only function in the project allowed to render withheld ``Synthesis``/``Verdict``
    text for a model to read (decision 0028). Its result is carried as a system prompt by
    ``judge_case``, never as a ``Payload``.
    """
    chosen = (
        ", ".join(
            f"{c} {tables.categories.get(c[:6], '')}" for c in hypothesis.finding_codes(tables)
        )
        or "none"
    )
    return (
        f"## Official factual narrative\n{synthesis.factual_narrative or '(none)'}\n\n"
        f"## Official probable cause\n{verdict.probable_cause or '(none)'}\n\n"
        f"## Analyst's evidence narrative\n{hypothesis.evidence_narrative}\n\n"
        f"## Analyst's probable cause\n{hypothesis.probable_cause}\n\n"
        f"## Analyst's chosen codes\n{chosen}\n\n"
        f"## Analyst's lay explanation\n{hypothesis.lay_explanation}\n"
    )


def _parse_judge_reply(content: str | None) -> JudgeLabels:
    """Parse one judge reply's content, or raise ``SchemaError`` for the caller to retry on."""
    try:
        return JudgeLabels.model_validate(json.loads(content or ""))
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"judge reply is not JudgeLabels: {error}") from error


def judge_case(  # noqa: PLR0913 -- interface fixed by spec §8 / decision 0028.
    client: ModelClient,
    hypothesis: Hypothesis,
    synthesis: Synthesis,
    verdict: Verdict,
    tables: CodeTables,
    *,
    price_variant: Literal["batch", "standard"] = "batch",
    max_output_tokens: int = 2000,
) -> tuple[JudgeLabels, ModelReply]:
    """One judge call, retried once on a schema error; the payload is empty by construction.

    ``max_output_tokens`` defaults to ``ModelSettings``'s own default (fix round 1, Important
    2): the judge's reply is a few tokens of JSON, so a generous cap costs nothing, while a
    tight one risks the answering model's own measured failure mode -- reasoning tokens
    consuming the cap and leaving an empty, unparsable reply (``finish_reason: "length"``) --
    for which there is no fixture on this judge model. One retry, with the rejection noted in
    the system text, mirrors ``Runner._two_turns``'s handling of the same failure mode; only
    the retry's reply is returned, so a case that needed a retry is priced from that reply
    alone, not both attempts (see Task 12 report for why the signature stays a single
    ``ModelReply``).
    """
    empty = Payload.from_evidence(Evidence(case_id="judge", docket_url=None))
    settings = ModelSettings(
        model=JUDGE_MODEL,
        price_variant=price_variant,
        json_schema=JUDGE_SCHEMA,
        schema_name="judge",
        max_output_tokens=max_output_tokens,
    )
    system = f"{SYSTEM_JUDGE}\n\n{judge_text(hypothesis, synthesis, verdict, tables)}"
    reply = client.complete(empty, settings, system=system)
    try:
        return _parse_judge_reply(reply.content), reply
    except SchemaError as error:
        retry = client.complete(
            empty,
            settings,
            system=f"{system}\n\nYour previous reply was rejected: {error}",
        )
        return _parse_judge_reply(retry.content), retry


@dataclass(frozen=True)
class JudgeRunResult:
    """One judge pass over a run's cases: labels, scores and what was actually spent."""

    case_ids: tuple[str, ...]
    labels: tuple[JudgeLabels, ...]
    scores: tuple[CaseScores, ...]
    cost_usd: float


JudgeItem = tuple[str, Hypothesis, Synthesis, Verdict, CaseScores]


def judge_run(  # noqa: PLR0913 -- the budget guard needs its own cap/budget/spent triple.
    client: ModelClient,
    tables: CodeTables,
    items: Sequence[JudgeItem],
    *,
    price_variant: Literal["batch", "standard"] = "batch",
    cap_usd: float = 0.01,
    budget_usd: float = 25.0,
    month_spent_usd: float = 0.0,
    max_output_tokens: int = 2000,
    on_row: Callable[[Mapping[str, object]], None] = lambda _row: None,
) -> JudgeRunResult:
    """Judge every item, refusing over budget first (fix round 1, Important 1).

    Library code, not the app: `apps/eval` stays thin argparse wiring, and this loop is
    exercised by the coverage gate the app itself sits outside of. The budget check reuses
    `runner.project_cost`/`refuse_over_budget` exactly as an answering run does, projected
    from `JUDGE_EXPECTED_COST_PER_CASE_USD` unless the caller passes a better one. `on_row`
    is called once per case, immediately after that case is priced, so a caller that appends
    it straight to a file keeps every already-paid label if a later case raises or the
    process is interrupted -- `judge_run` itself does the same for cost: an exception after
    *k* items still leaves `client`'s and `on_row`'s side effects for those *k* items intact,
    even though this function's own return value is then never produced (see `apps/eval`'s
    `_cmd_judge`, which sums `on_row`'s own cost figures rather than only trusting a
    completed `JudgeRunResult`, so a partial run's spend is still recorded).

    The known gap (fix round 1): a case whose `judge_case` call needs its internal retry is
    priced from the retry's reply alone, so that case's cost omits the first attempt's
    tokens (same limitation as `judge_case` itself, logged in Task 12).
    """
    spec = RunSpec(
        sample="judge",
        arm="ceiling",
        price_variant=price_variant,
        cap_usd=cap_usd,
        budget_usd=budget_usd,
        expected_cost_per_case_usd=JUDGE_EXPECTED_COST_PER_CASE_USD[price_variant],
    )
    refuse_over_budget(project_cost(spec, len(items)), month_spent_usd, budget_usd)
    settings = ModelSettings(
        model=JUDGE_MODEL,
        price_variant=price_variant,
        json_schema=JUDGE_SCHEMA,
        schema_name="judge",
        max_output_tokens=max_output_tokens,
    )
    ids: list[str] = []
    labels: list[JudgeLabels] = []
    scores: list[CaseScores] = []
    total_cost = 0.0
    for case_id, hypothesis, synthesis, verdict, score in items:
        label, reply = judge_case(
            client,
            hypothesis,
            synthesis,
            verdict,
            tables,
            price_variant=price_variant,
            max_output_tokens=max_output_tokens,
        )
        cost, _ = cost_usd(reply, settings)
        total_cost += cost
        ids.append(case_id)
        labels.append(label)
        scores.append(score)
        on_row({"case_id": case_id, "cost_usd": cost, **label.model_dump()})
    return JudgeRunResult(
        case_ids=tuple(ids), labels=tuple(labels), scores=tuple(scores), cost_usd=total_cost
    )


def agreement_table(
    labels: Sequence[JudgeLabels], scores: Sequence[CaseScores]
) -> dict[str, dict[str, int]]:
    """Confusion table: judge cause label x occurrence top-1 (spec §8 validation)."""
    table: dict[str, dict[str, int]] = {}
    for label, score in zip(labels, scores, strict=True):
        row = table.setdefault(label.cause, {"top1_right": 0, "top1_wrong": 0})
        row["top1_right" if score.occurrence_top1 else "top1_wrong"] += 1
    return table


def pick_disagreements(
    case_ids: Sequence[str],
    labels: Sequence[JudgeLabels],
    scores: Sequence[CaseScores],
    *,
    n: int = 30,
    seed: int = 20260914,
) -> list[str]:
    """Cases where the judge and the code layer disagree, sampled for Andy's hand-check."""
    candidates = [
        cid
        for cid, label, score in zip(case_ids, labels, scores, strict=True)
        if (label.cause == "same_cause") != score.occurrence_top1
    ]
    rng = random.Random(seed)  # noqa: S311 -- sampling for a hand-check, not security
    return sorted(rng.sample(candidates, min(n, len(candidates))))
