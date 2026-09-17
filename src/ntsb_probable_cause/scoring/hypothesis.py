"""The model's answer: one Hypothesis for a one-shot pass and for every step of a trail.

Spec §3.4.
"""

import json
from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import CodeTables


class OccurrenceGuess(BaseModel):
    """One ranked occurrence guess."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    phase: str = Field(pattern=r"^[0-9]{3}$")
    event: str = Field(pattern=r"^[0-9]{3}$")
    probability: float = Field(ge=0, le=1)


class FindingGuess(BaseModel):
    """One finding guess at stage 1 (category + modifier) and, after stage 2, its item."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    category6: str = Field(pattern=r"^[0-9]{6}$")
    modifier: str = Field(pattern=r"^[0-9]{2}$")
    probability: float = Field(ge=0, le=1)
    item8: str | None = Field(default=None, pattern=r"^[0-9]{8}$")


class Hypothesis(BaseModel):
    """The structured answer (decisions 0006, 0013, 0021)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence_narrative: str
    occurrence: tuple[OccurrenceGuess, ...] = Field(min_length=1, max_length=3)
    findings: tuple[FindingGuess, ...]
    probable_cause: str
    lay_explanation: str
    confidence: float = Field(ge=0, le=1)
    abstain: bool
    evidence_used: tuple[str, ...]

    def occurrence_codes(self, tables: CodeTables) -> tuple[str, ...]:
        """Compose the ranked six-digit occurrence codes."""
        return tuple(tables.compose_occurrence(g.phase, g.event) for g in self.occurrence)

    def finding_codes(self, tables: CodeTables) -> tuple[str, ...]:
        """Compose ten-digit finding codes for guesses that already have an item."""
        return tuple(
            tables.compose_finding(g.item8, g.modifier)
            for g in self.findings
            if g.item8 is not None
        )

    def occurrence_distribution(self, tables: CodeTables) -> dict[str, float]:
        """Return the probability per composed occurrence code, remainder under ``other``."""
        dist = {
            code: g.probability
            for code, g in zip(self.occurrence_codes(tables), self.occurrence, strict=True)
        }
        dist["other"] = max(0.0, 1.0 - sum(dist.values()))
        return dist

    def with_items(self, items: Mapping[int, str]) -> Hypothesis:
        """Return a copy with stage-2 items attached, keyed by finding index."""
        findings = tuple(
            g.model_copy(update={"item8": items.get(i, g.item8)})
            for i, g in enumerate(self.findings)
        )
        return self.model_copy(update={"findings": findings})


class RefinedItem(BaseModel):
    """Stage 2: the chosen item for one stage-1 finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int = Field(ge=0)
    item8: str = Field(pattern=r"^[0-9]{8}$")


class Refinement(BaseModel):
    """The stage-2 reply: one item choice per stage-1 finding index."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[RefinedItem, ...]


def _strict(node: object) -> None:
    """Rewrite a JSON-schema node in place for OpenAI strict structured outputs.

    Every object gets ``additionalProperties: false`` and every property listed in
    ``required`` (pydantic's own ``default: null`` optionality is what keeps ``item8``
    nullable); ``default`` and ``title`` keys, which strict mode does not accept or does
    not need, are dropped throughout.
    """
    if isinstance(node, dict):
        node.pop("title", None)
        node.pop("default", None)
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        for value in node.values():
            _strict(value)
    elif isinstance(node, list):
        for item in node:
            _strict(item)


def strict_schema(model: type[BaseModel]) -> dict[str, object]:
    """Build an OpenAI-strict JSON schema from a pydantic model.

    Shared with ``scoring/judge.py`` (fix round 1, Important 1): every caller that sends a
    ``json_schema`` to the provider gets exactly the treatment confirmed live against
    OpenRouter, not a hand-rolled approximation of it.
    """
    schema: dict[str, Any] = model.model_json_schema()
    _strict(schema)
    return schema


def _stage1_schema() -> dict[str, object]:
    """The stage-1 schema: the hypothesis schema with ``item8`` removed from each finding.

    Item codes are stage 2's job. Stage 1 is never shown the item list for a category, so a
    stage-1 reply cannot choose an item code -- it can only invent one, and offering the
    field invited exactly that. On the first full development ceiling run 249 of 401 stage-1
    replies were rejected, almost all of them for an ``item8`` built as ``category6 +
    modifier`` (for example ``020410`` + ``44`` -> ``02041044``). Removing the field leaves
    the model nothing to guess with; ``parse_hypothesis`` still validates an ``item8`` if one
    somehow arrives.
    """
    schema = strict_schema(Hypothesis)
    finding = cast(dict[str, Any], cast(dict[str, Any], schema["$defs"])["FindingGuess"])
    del cast(dict[str, Any], finding["properties"])["item8"]
    finding["required"] = [name for name in finding["required"] if name != "item8"]
    return schema


HYPOTHESIS_SCHEMA: dict[str, object] = _stage1_schema()
REFINEMENT_SCHEMA: dict[str, object] = strict_schema(Refinement)


def parse_hypothesis(text: str, tables: CodeTables) -> Hypothesis:
    """Parse and validate a stage-1 reply against the code tables."""
    try:
        hypothesis = Hypothesis.model_validate(json.loads(text))
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"reply is not a Hypothesis: {error}") from error
    if sum(g.probability for g in hypothesis.occurrence) > 1.0 + 1e-9:
        raise SchemaError("occurrence probabilities sum to more than 1")
    codes = hypothesis.occurrence_codes(tables)
    if len(set(codes)) != len(codes):
        raise SchemaError(f"duplicate occurrence code among guesses: {codes}")
    for g in hypothesis.findings:
        if g.category6 not in tables.categories:
            raise SchemaError(f"unknown finding category {g.category6!r}")
        if g.modifier not in tables.modifiers:
            raise SchemaError(f"unknown modifier {g.modifier!r}")
        if g.item8 is not None and g.item8 not in tables.items_under(g.category6):
            raise SchemaError(f"{g.item8!r} is not a child of category {g.category6!r}")
    return hypothesis


def parse_refinement(text: str, tables: CodeTables, hypothesis: Hypothesis) -> Hypothesis:
    """Parse a stage-2 reply and attach each item to its finding; every item must be a child."""
    try:
        refinement = Refinement.model_validate(json.loads(text))
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"reply is not a Refinement: {error}") from error
    items: dict[int, str] = {}
    for chosen in refinement.items:
        if chosen.index >= len(hypothesis.findings):
            raise SchemaError(f"refinement index {chosen.index} has no finding")
        category = hypothesis.findings[chosen.index].category6
        if chosen.item8 not in tables.items_under(category):
            raise SchemaError(f"{chosen.item8!r} is not a child of category {category!r}")
        items[chosen.index] = chosen.item8
    return hypothesis.with_items(items)
