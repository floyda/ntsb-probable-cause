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
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, strict_schema
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
