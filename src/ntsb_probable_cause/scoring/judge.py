"""The judge: labels for the prose outputs, validated before use, never a bar (decision 0028).

This is the only module that renders withheld text for a model. It builds an empty Payload and
carries everything in the system prompt, so the Payload invariant of S0 is untouched and the
boundary test can name this path.
"""

import json
import random
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.model.client import ModelClient, ModelReply, ModelSettings, Payload
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import CaseScores

JUDGE_MODEL = "anthropic/claude-haiku-4.5"
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


JUDGE_SCHEMA: dict[str, object] = JudgeLabels.model_json_schema()
JUDGE_SCHEMA["additionalProperties"] = False


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


def judge_case(  # noqa: PLR0913 -- interface fixed by spec §8 / decision 0028.
    client: ModelClient,
    hypothesis: Hypothesis,
    synthesis: Synthesis,
    verdict: Verdict,
    tables: CodeTables,
    *,
    price_variant: Literal["batch", "standard"] = "batch",
) -> tuple[JudgeLabels, ModelReply]:
    """One judge call. The payload is empty by construction; everything is in the system text."""
    empty = Payload.from_evidence(Evidence(case_id="judge", docket_url=None))
    settings = ModelSettings(
        model=JUDGE_MODEL,
        price_variant=price_variant,
        json_schema=JUDGE_SCHEMA,
        schema_name="judge",
        max_output_tokens=200,
    )
    reply = client.complete(
        empty,
        settings,
        system=f"{SYSTEM_JUDGE}\n\n{judge_text(hypothesis, synthesis, verdict, tables)}",
    )
    try:
        return JudgeLabels.model_validate(json.loads(reply.content or "")), reply
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"judge reply is not JudgeLabels: {error}") from error


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
