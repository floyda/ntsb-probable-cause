"""Tests for the Hypothesis schema, two-stage parsing, and prompt rendering (S1 Task 6)."""

import json
import re
from typing import Any

import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import (
    HYPOTHESIS_SCHEMA,
    REFINEMENT_SCHEMA,
    parse_hypothesis,
    parse_refinement,
)
from ntsb_probable_cause.scoring.prompt import refine_message, tables_block

GOOD = {
    "evidence_narrative": "The airplane departed the runway during the landing roll.",
    "occurrence": [
        {"phase": "552", "event": "230", "probability": 0.6},
        {"phase": "551", "event": "230", "probability": 0.2},
    ],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.7}],
    "probable_cause": "The pilot's loss of directional control during the landing roll.",
    "lay_explanation": "The plane swerved off the runway after touching down.",
    "confidence": 0.6,
    "abstain": False,
    "evidence_used": ["phase_of_flight", "weather_condition"],
}


def test_parse_good_hypothesis_composes_codes() -> None:
    h = parse_hypothesis(json.dumps(GOOD), load_tables())
    assert h.occurrence_codes(load_tables()) == ("552230", "551230")
    assert h.finding_codes(load_tables()) == ()  # no items yet
    dist = h.occurrence_distribution(load_tables())
    assert dist["552230"] == 0.6
    assert dist["other"] == pytest.approx(0.2)


def test_unknown_code_is_a_schema_error() -> None:
    bad = {**GOOD, "occurrence": [{"phase": "000", "event": "230", "probability": 1.0}]}
    with pytest.raises(SchemaError, match="phase"):
        parse_hypothesis(json.dumps(bad), load_tables())


def test_probabilities_over_one_are_a_schema_error() -> None:
    bad = {
        **GOOD,
        "occurrence": [
            {"phase": "552", "event": "230", "probability": 0.8},
            {"phase": "551", "event": "230", "probability": 0.5},
        ],
    }
    with pytest.raises(SchemaError, match="sum"):
        parse_hypothesis(json.dumps(bad), load_tables())


def test_refinement_attaches_items_and_composes_ten_digits() -> None:
    t = load_tables()
    h = parse_hypothesis(json.dumps(GOOD), t)
    refined = parse_refinement(json.dumps({"items": [{"index": 0, "item8": "02063040"}]}), t, h)
    assert refined.finding_codes(t) == ("0206304044",)
    with pytest.raises(SchemaError, match="child"):
        parse_refinement(json.dumps({"items": [{"index": 0, "item8": "01022214"}]}), t, h)


def test_malformed_json_is_a_schema_error() -> None:
    with pytest.raises(SchemaError, match="not a Hypothesis"):
        parse_hypothesis("not json", load_tables())


def test_unknown_finding_category_and_modifier_are_schema_errors() -> None:
    t = load_tables()
    with pytest.raises(SchemaError, match="category"):
        parse_hypothesis(
            json.dumps(
                {
                    **GOOD,
                    "findings": [{"category6": "999999", "modifier": "44", "probability": 0.5}],
                }
            ),
            t,
        )
    with pytest.raises(SchemaError, match="modifier"):
        parse_hypothesis(
            json.dumps(
                {
                    **GOOD,
                    "findings": [{"category6": "020630", "modifier": "97", "probability": 0.5}],
                }
            ),
            t,
        )


def test_refinement_index_out_of_range_and_malformed_json_are_schema_errors() -> None:
    t = load_tables()
    h = parse_hypothesis(json.dumps(GOOD), t)
    with pytest.raises(SchemaError, match="not a Refinement"):
        parse_refinement("not json", t, h)
    with pytest.raises(SchemaError, match="no finding"):
        parse_refinement(json.dumps({"items": [{"index": 5, "item8": "02063040"}]}), t, h)


def test_every_table_code_matches_its_field_pattern() -> None:
    """Fix-round precondition: the digit patterns must accept every code the tables define."""
    t = load_tables()
    patterns = {
        "phases": r"^[0-9]{3}$",
        "events": r"^[0-9]{3}$",
        "categories": r"^[0-9]{6}$",
        "items": r"^[0-9]{8}$",
        "modifiers": r"^[0-9]{2}$",
    }
    for name, pattern in patterns.items():
        table = getattr(t, name)
        offenders = [code for code in table if not re.match(pattern, code)]
        assert offenders == [], f"{name} has codes that do not match {pattern!r}: {offenders}"


def test_rendered_item_label_in_item8_is_a_schema_error() -> None:
    """The live smoke test saw the model return 'code  label' for item8; the pattern rejects it."""
    t = load_tables()
    h = parse_hypothesis(json.dumps(GOOD), t)
    bad_reply = json.dumps(
        {"items": [{"index": 0, "item8": "02063040  Personnel issues — Aircraft control"}]}
    )
    with pytest.raises(SchemaError, match="not a Refinement"):
        parse_refinement(bad_reply, t, h)


def test_stage1_item8_must_be_a_child_of_its_own_category() -> None:
    t = load_tables()
    finding = {"category6": "020630", "modifier": "44", "probability": 0.7}
    good_child = {**GOOD, "findings": [{**finding, "item8": "02063040"}]}
    h = parse_hypothesis(json.dumps(good_child), t)
    assert h.finding_codes(t) == ("0206304044",)

    wrong_category_item = {**GOOD, "findings": [{**finding, "item8": "01022214"}]}
    with pytest.raises(SchemaError, match="child"):
        parse_hypothesis(json.dumps(wrong_category_item), t)


def test_duplicate_occurrence_codes_are_a_schema_error() -> None:
    bad = {
        **GOOD,
        "occurrence": [
            {"phase": "552", "event": "230", "probability": 0.5},
            {"phase": "552", "event": "230", "probability": 0.1},
        ],
    }
    with pytest.raises(SchemaError, match="duplicate"):
        parse_hypothesis(json.dumps(bad), load_tables())


def test_schema_is_strict_and_tables_block_holds_tables() -> None:
    assert HYPOTHESIS_SCHEMA["additionalProperties"] is False
    block = tables_block(load_tables())
    assert block.startswith("## Phase prefixes")
    assert "552  " in block
    assert "44  Pilot" in block
    assert "## Case number" not in block
    assert tables_block(load_tables(), case_number="CEN16LA001").endswith(
        "## Case number\nCEN16LA001\n"
    )
    h = parse_hypothesis(json.dumps(GOOD), load_tables())
    assert "02063040" in refine_message(h, load_tables())


def _walk_objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect every object-typed schema node, including those under $defs."""
    objects: list[dict[str, Any]] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                objects.append(node)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(schema)
    return objects


@pytest.mark.parametrize("schema", [HYPOTHESIS_SCHEMA, REFINEMENT_SCHEMA])
def test_strict_schemas_are_openai_compatible(schema: dict[str, Any]) -> None:
    objects = _walk_objects(schema)
    assert objects, "expected at least one object node in the schema"
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])

    def no_default(node: object) -> None:
        if isinstance(node, dict):
            assert "default" not in node
            for value in node.values():
                no_default(value)
        elif isinstance(node, list):
            for item in node:
                no_default(item)

    no_default(schema)
