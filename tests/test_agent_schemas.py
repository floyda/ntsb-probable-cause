"""Tests for ``agent/schemas.py``: tool definitions, argument models, parsing (S3.1 Task 6)."""

import json
import os
import subprocess
import sys
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from ntsb_probable_cause.agent.schemas import (
    CODING_TOOLS,
    PHASE_GROUPS,
    REQUIRED,
    TOOL_DEFINITIONS,
    ChooseDocuments,
    CodingToolName,
    DescribeCodes,
    DescribeKind,
    DocumentChoice,
    DocumentDecision,
    ExtraDecision,
    ExtraKind,
    OccurrenceUsage,
    PastFindings,
    PhaseGroup,
    SuggestCodes,
    ToolName,
    Without,
    definitions,
    force,
    parse_call,
)
from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.hypothesis import HYPOTHESIS_SCHEMA, Hypothesis

TABLES = load_tables()

ORDER = (
    "record_hypothesis",
    "choose_documents",
    "describe_codes",
    "occurrence_usage",
    "past_findings",
    "suggest_codes",
    "submit_answer",
)

DESCRIPTIONS = {
    "record_hypothesis": (
        "Record your current hypothesis: up to three occurrence codes with probabilities, "
        "findings, a working cause, and your confidence."
    ),
    "choose_documents": (
        "Decide, for every document offered, whether to read it, and what you expect it to show."
    ),
    "describe_codes": (
        "Look up the labels of occurrence codes, finding categories or finding items."
    ),
    "occurrence_usage": (
        "Count how often past accidents recorded each occurrence code, and each pair of them, "
        "and how often each was the defining event."
    ),
    "past_findings": (
        "List the findings most often recorded in past accidents whose defining event matches "
        "this occurrence code's event."
    ),
    "suggest_codes": (
        "List the five commonest defining events in past accidents of one phase-of-flight group."
    ),
    "submit_answer": "Submit your final answer. This ends your work on the case.",
}

GOOD_HYPOTHESIS = {
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

WHY = {"reason": "why I call it", "expected_effect": "what I expect it to show"}


def _function(definition: dict[str, object]) -> dict[str, Any]:
    function: dict[str, Any] = definition["function"]  # type: ignore[assignment]
    return function


# --------------------------------------------------------------------------------------------
# Names and phase groups
# --------------------------------------------------------------------------------------------


def test_tool_names_are_the_seven_the_loop_knows() -> None:
    assert get_args(CodingToolName) == (
        "describe_codes",
        "occurrence_usage",
        "past_findings",
        "suggest_codes",
    )
    assert set(get_args(ToolName)) == set(ORDER)
    assert len(get_args(ToolName)) == 7
    assert frozenset(get_args(CodingToolName)) == CODING_TOOLS


def test_describe_kinds() -> None:
    assert get_args(DescribeKind) == ("occurrence", "finding_category", "item")


def test_phase_groups_are_the_twelve_names_in_the_briefs_order() -> None:
    assert PHASE_GROUPS == (
        "Approach",
        "EmergencyDescent",
        "Enroute",
        "InitialClimb",
        "Landing",
        "Maneuvering",
        "Post-Impact",
        "Standing",
        "Takeoff",
        "Taxi",
        "UncontrolledDescent",
        "Unknown",
    )


def test_the_phase_group_type_and_the_tuple_agree() -> None:
    assert get_args(PhaseGroup) == PHASE_GROUPS


def test_phase_groups_are_the_group_names_of_the_s3_statistics() -> None:
    """Every half's names are among PHASE_GROUPS, and together they are all of them."""
    halves = load_stats("s3").group_defining
    assert len(halves) >= 2
    seen: set[str] = set()
    for half, groups in halves.items():
        assert set(groups) <= set(PHASE_GROUPS), half
        seen |= set(groups)
    assert seen == set(PHASE_GROUPS)


# --------------------------------------------------------------------------------------------
# Definitions
# --------------------------------------------------------------------------------------------


def test_tool_definitions_are_the_seven_tools_in_a_fixed_order() -> None:
    assert len(TOOL_DEFINITIONS) == 7
    assert tuple(_function(d)["name"] for d in TOOL_DEFINITIONS) == ORDER


def test_each_definition_has_the_native_shape_and_the_fixed_description() -> None:
    for definition in TOOL_DEFINITIONS:
        assert list(definition) == ["type", "function"]
        assert definition["type"] == "function"
        function = _function(definition)
        assert list(function) == ["name", "description", "parameters", "strict"]
        assert function["strict"] is True
        assert function["description"] == DESCRIPTIONS[function["name"]]
        assert "\n" not in function["description"]
        assert function["parameters"]["type"] == "object"


def test_record_hypothesis_and_submit_answer_take_the_hypothesis_schema() -> None:
    by_name = {_function(d)["name"]: _function(d) for d in TOOL_DEFINITIONS}
    assert by_name["record_hypothesis"]["parameters"] == HYPOTHESIS_SCHEMA
    assert by_name["submit_answer"]["parameters"] == HYPOTHESIS_SCHEMA


def _assert_strict(node: object) -> None:
    """Every object node has ``additionalProperties: false`` and lists every property required."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False
            assert set(node["required"]) == set(node["properties"].keys())
        for value in node.values():
            _assert_strict(value)
    elif isinstance(node, list):
        for item in node:
            _assert_strict(item)


def test_every_definition_is_strict() -> None:
    for definition in TOOL_DEFINITIONS:
        _assert_strict(_function(definition)["parameters"])


def test_the_strict_check_can_fail() -> None:
    loose = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
    with pytest.raises(AssertionError):
        _assert_strict(loose)
    with pytest.raises(AssertionError):
        _assert_strict({"type": "object", "properties": {}, "required": []})


def test_the_argument_schemas_carry_no_docstring_text() -> None:
    """Class docstrings stay out of the wire format, so editing one cannot change the prefix."""

    def descriptions(node: object) -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            if isinstance(node.get("description"), str):
                found.append(node["description"])
            for value in node.values():
                found += descriptions(value)
        elif isinstance(node, list):
            for item in node:
                found += descriptions(item)
        return found

    for definition in TOOL_DEFINITIONS:
        function = _function(definition)
        if function["name"] in ("record_hypothesis", "submit_answer"):
            continue
        assert descriptions(function["parameters"]) == [], function["name"]


def test_argument_properties_of_each_tool() -> None:
    by_name = {_function(d)["name"]: _function(d)["parameters"] for d in TOOL_DEFINITIONS}
    assert list(by_name["describe_codes"]["properties"]) == [
        "reason",
        "expected_effect",
        "kind",
        "codes",
    ]
    assert list(by_name["occurrence_usage"]["properties"]) == ["reason", "expected_effect", "codes"]
    assert list(by_name["past_findings"]["properties"]) == [
        "reason",
        "expected_effect",
        "occurrence",
    ]
    assert list(by_name["suggest_codes"]["properties"]) == [
        "reason",
        "expected_effect",
        "phase_group",
    ]
    assert list(by_name["choose_documents"]["properties"]) == ["decisions", "reason"]
    assert by_name["suggest_codes"]["properties"]["phase_group"]["enum"] == list(PHASE_GROUPS)
    assert by_name["describe_codes"]["properties"]["kind"]["enum"] == [
        "occurrence",
        "finding_category",
        "item",
    ]
    decision = by_name["choose_documents"]["$defs"]["DocumentDecision"]
    assert list(decision["properties"]) == ["document", "read", "expected_effect"]


def test_without_suggest_codes_drops_that_one_tool() -> None:
    names = [_function(d)["name"] for d in definitions(frozenset({"suggest_codes"}))]
    assert names == [n for n in ORDER if n != "suggest_codes"]


def test_without_coding_drops_the_four_coding_tools() -> None:
    names = [_function(d)["name"] for d in definitions(frozenset({"coding"}))]
    assert names == ["record_hypothesis", "choose_documents", "submit_answer"]


def test_without_both_ablations_is_the_same_as_without_coding() -> None:
    both: frozenset[Without] = frozenset({"suggest_codes", "coding"})
    assert definitions(both) == definitions(frozenset({"coding"}))


def test_definitions_with_nothing_dropped_are_the_tool_definitions() -> None:
    assert definitions() == TOOL_DEFINITIONS
    assert definitions(frozenset()) == TOOL_DEFINITIONS


def test_a_definition_left_in_place_is_the_same_bytes_in_every_ablation() -> None:
    full = {_function(d)["name"]: json.dumps(d) for d in TOOL_DEFINITIONS}
    ablations: tuple[frozenset[Without], ...] = (
        frozenset({"suggest_codes"}),
        frozenset({"coding"}),
    )
    for without in ablations:
        for definition in definitions(without):
            assert json.dumps(definition) == full[_function(definition)["name"]]


def test_a_caller_changing_a_definition_changes_no_other_copy() -> None:
    before = json.dumps(TOOL_DEFINITIONS)
    schema_before = json.dumps(HYPOTHESIS_SCHEMA)
    mine = definitions()
    _function(mine[0])["description"] = "changed"
    _function(mine[0])["parameters"]["properties"].clear()
    _function(mine[6])["parameters"]["properties"].clear()
    assert json.dumps(TOOL_DEFINITIONS) == before
    assert json.dumps(definitions()) == before
    assert json.dumps(HYPOTHESIS_SCHEMA) == schema_before


_DUMP = (
    "import json; "
    "from ntsb_probable_cause.agent.schemas import TOOL_DEFINITIONS; "
    "print(json.dumps(TOOL_DEFINITIONS))"
)


def _dump_in_a_fresh_interpreter(hash_seed: str) -> str:
    result = subprocess.run(  # noqa: S603 -- this interpreter, a fixed program, no shell
        [sys.executable, "-c", _DUMP],
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_tool_definitions_serialise_identically_across_imports() -> None:
    """The prompt cache holds only if every import builds the same bytes (spec §5.3)."""
    first = _dump_in_a_fresh_interpreter("0")
    second = _dump_in_a_fresh_interpreter("12345")
    assert first == second
    assert first == json.dumps(TOOL_DEFINITIONS)
    assert json.dumps(json.loads(first), sort_keys=True) == json.dumps(
        TOOL_DEFINITIONS, sort_keys=True
    )


def test_force_names_one_tool() -> None:
    assert force("record_hypothesis") == {
        "type": "function",
        "function": {"name": "record_hypothesis"},
    }
    assert force("suggest_codes")["function"] == {"name": "suggest_codes"}


def test_required_is_the_string_required() -> None:
    assert REQUIRED == "required"


# --------------------------------------------------------------------------------------------
# Argument models
# --------------------------------------------------------------------------------------------


def test_argument_models_refuse_extra_and_missing_fields() -> None:
    with pytest.raises(ValidationError):
        SuggestCodes.model_validate({**WHY, "phase_group": "Landing", "extra": 1})
    with pytest.raises(ValidationError):
        SuggestCodes.model_validate({"reason": "why", "phase_group": "Landing"})
    with pytest.raises(ValidationError):
        SuggestCodes.model_validate({**WHY, "phase_group": "Hovering"})


def test_argument_models_are_frozen() -> None:
    arguments = PastFindings(occurrence="452240", **WHY)
    with pytest.raises(ValidationError):
        arguments.occurrence = "452241"  # type: ignore[misc]


def test_document_decision_and_choose_documents_fields() -> None:
    decision = DocumentDecision(document=3, read=True, expected_effect="the gear position")
    choice = ChooseDocuments(decisions=(decision,), reason="the hypothesis needs it")
    assert choice.decisions[0].document == 3


# --------------------------------------------------------------------------------------------
# parse_call
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["record_hypothesis", "submit_answer"])
def test_parse_call_reads_a_hypothesis(name: str) -> None:
    parsed = parse_call(name, json.dumps(GOOD_HYPOTHESIS), TABLES)
    assert isinstance(parsed, Hypothesis)
    assert parsed.occurrence_codes(TABLES) == ("552230", "551230")


@pytest.mark.parametrize("name", ["record_hypothesis", "submit_answer"])
def test_parse_call_refuses_a_bad_hypothesis(name: str) -> None:
    bad = {**GOOD_HYPOTHESIS, "occurrence": [{"phase": "000", "event": "230", "probability": 1.0}]}
    with pytest.raises(SchemaError, match="phase"):
        parse_call(name, json.dumps(bad), TABLES)
    with pytest.raises(SchemaError):
        parse_call(name, "not json", TABLES)


def test_parse_call_reads_describe_codes() -> None:
    parsed = parse_call(
        "describe_codes",
        json.dumps({**WHY, "kind": "finding_category", "codes": ["020630", "010620"]}),
        TABLES,
    )
    assert parsed == DescribeCodes(kind="finding_category", codes=("020630", "010620"), **WHY)


def test_parse_call_reads_occurrence_usage() -> None:
    parsed = parse_call(
        "occurrence_usage", json.dumps({**WHY, "codes": ["452240", "452241"]}), TABLES
    )
    assert parsed == OccurrenceUsage(codes=("452240", "452241"), **WHY)


def test_parse_call_reads_past_findings() -> None:
    parsed = parse_call("past_findings", json.dumps({**WHY, "occurrence": "452240"}), TABLES)
    assert parsed == PastFindings(occurrence="452240", **WHY)


def test_parse_call_reads_suggest_codes() -> None:
    parsed = parse_call("suggest_codes", json.dumps({**WHY, "phase_group": "Landing"}), TABLES)
    assert parsed == SuggestCodes(phase_group="Landing", **WHY)


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("describe_codes", {**WHY, "kind": "bogus", "codes": ["452240"]}),
        ("describe_codes", {**WHY, "kind": "item"}),
        ("describe_codes", {**WHY, "kind": "item", "codes": "452240"}),
        ("describe_codes", {**WHY, "kind": "item", "codes": [452240]}),
        ("occurrence_usage", {**WHY, "codes": ["452240"], "pairs": True}),
        ("occurrence_usage", {"reason": "why", "codes": ["452240"]}),
        ("past_findings", {**WHY, "occurrence": ["452240"]}),
        ("suggest_codes", {**WHY, "phase_group": "Hovering"}),
        ("suggest_codes", {**WHY, "phase_group": ""}),
    ],
)
def test_parse_call_refuses_bad_arguments(name: str, arguments: dict[str, object]) -> None:
    with pytest.raises(SchemaError, match=name):
        parse_call(name, json.dumps(arguments), TABLES)


@pytest.mark.parametrize("text", ["", "not json", "[]", "null", '{"reason": '])
def test_parse_call_refuses_arguments_that_are_not_a_json_object(text: str) -> None:
    with pytest.raises(SchemaError, match="suggest_codes"):
        parse_call("suggest_codes", text, TABLES)


def test_the_error_names_the_field_and_never_echoes_the_input() -> None:
    marker = "MARKER-" + "x" * 500
    with pytest.raises(SchemaError) as caught:
        parse_call("describe_codes", json.dumps({**WHY, "kind": marker, "codes": marker}), TABLES)
    message = str(caught.value)
    assert "kind" in message
    assert "codes" in message
    assert "MARKER" not in message
    assert "https://" not in message


def test_parse_call_refuses_an_unknown_tool_name() -> None:
    with pytest.raises(SchemaError, match="bogus_tool"):
        parse_call("bogus_tool", "{}", TABLES)


def _decisions(pairs: list[tuple[int, bool]], *, reason: str = "reason") -> str:
    return json.dumps(
        {
            "decisions": [
                {"document": d, "read": r, "expected_effect": "effect"} for d, r in pairs
            ],
            "reason": reason,
        }
    )


def _choice(
    pairs: list[tuple[int, bool]],
    offered: list[int],
    *,
    already_read: tuple[int, ...] = (),
    not_readable: tuple[int, ...] = (),
) -> DocumentChoice:
    parsed = parse_call(
        "choose_documents",
        _decisions(pairs),
        TABLES,
        offered,
        already_read=already_read,
        not_readable=not_readable,
    )
    assert isinstance(parsed, DocumentChoice)
    return parsed


def _extras(choice: DocumentChoice) -> list[tuple[int, str]]:
    return [(extra.document, extra.kind) for extra in choice.extras]


def test_choose_documents_accepts_a_decision_for_every_offered_document() -> None:
    parsed = _choice([(2, False), (1, True)], [1, 2])
    assert [(d.document, d.read) for d in parsed.decisions] == [(2, False), (1, True)]
    assert parsed.extras == ()
    assert parsed.arguments == ChooseDocuments.model_validate_json(
        _decisions([(2, False), (1, True)])
    )


def test_choose_documents_with_nothing_offered_and_nothing_decided_is_accepted() -> None:
    parsed = parse_call("choose_documents", _decisions([]), TABLES)
    assert isinstance(parsed, DocumentChoice)
    assert (parsed.decisions, parsed.extras) == ((), ())


def test_choose_documents_with_a_missing_document_names_it() -> None:
    with pytest.raises(SchemaError, match=r"missing \[3, 4\]") as caught:
        parse_call("choose_documents", _decisions([(1, True), (2, False)]), TABLES, [1, 2, 3, 4])
    assert "repeated" not in str(caught.value)
    assert "not offered" not in str(caught.value)


def test_choose_documents_with_a_repeated_document_names_it() -> None:
    with pytest.raises(SchemaError, match=r"repeated \[2\]"):
        parse_call(
            "choose_documents", _decisions([(1, True), (2, True), (2, False)]), TABLES, [1, 2]
        )


def test_choose_documents_names_every_fault_at_once_and_no_extra() -> None:
    """Decision 0134: a document not on offer is no fault; a missing or repeated one still is."""
    with pytest.raises(SchemaError) as caught:
        parse_call(
            "choose_documents",
            _decisions([(1, True), (1, False), (7, True)]),
            TABLES,
            [1, 2],
        )
    message = str(caught.value)
    assert message == (
        "choose_documents must decide every offered document exactly once: "
        "missing [2]; repeated [1]"
    )


# Decision 0134 (Andy, 2026-10-01, after the S3.1 smoke run): a decision on a document that is not
# on offer is tolerated, set aside as an extra with its kind, and never acted on.


def test_the_smoke_runs_first_choice_is_accepted_with_its_seven_extras() -> None:
    """Run 20261001T115444: 11 listed, [2], [3], [4] and [11] offered, a decision on all 11."""
    pairs = [(n, n in (1, 2, 3, 4)) for n in range(1, 12)]
    parsed = _choice(pairs, [2, 3, 4, 11], not_readable=(1, 5, 6, 7, 8, 9, 10))
    assert [(d.document, d.read) for d in parsed.decisions] == [
        (2, True),
        (3, True),
        (4, True),
        (11, False),
    ]
    assert _extras(parsed) == [(n, "not_readable") for n in (1, 5, 6, 7, 8, 9, 10)]
    assert parsed.arguments == ChooseDocuments.model_validate_json(_decisions(pairs))
    assert len(parsed.arguments.decisions) == 11, "the arguments are kept as the model sent them"


def test_the_smoke_runs_second_choice_is_accepted_with_its_three_extras() -> None:
    """Choice 2 decided again on [2], [3] and [4], read at choice 1, and on [11], on offer."""
    parsed = _choice(
        [(2, True), (3, False), (4, True), (11, False)],
        [11],
        already_read=(2, 3, 4),
        not_readable=(1, 5, 6, 7, 8, 9, 10),
    )
    assert [(d.document, d.read) for d in parsed.decisions] == [(11, False)]
    assert _extras(parsed) == [(2, "already_read"), (3, "already_read"), (4, "already_read")]


def test_a_number_not_in_the_listing_is_tolerated_as_unknown() -> None:
    parsed = _choice([(1, True), (14, True)], [1], not_readable=(3,))
    assert [(d.document, d.read) for d in parsed.decisions] == [(1, True)]
    assert _extras(parsed) == [(14, "unknown")]


def test_with_nothing_offered_a_decision_is_an_unknown_extra() -> None:
    parsed = parse_call("choose_documents", _decisions([(1, True)]), TABLES)
    assert isinstance(parsed, DocumentChoice)
    assert parsed.decisions == ()
    assert _extras(parsed) == [(1, "unknown")]


def test_an_extra_named_twice_is_reported_once_in_the_order_first_named() -> None:
    parsed = _choice(
        [(14, True), (1, False), (5, True), (14, False), (5, False), (2, True)],
        [1],
        already_read=(2,),
        not_readable=(5,),
    )
    assert _extras(parsed) == [(14, "unknown"), (5, "not_readable"), (2, "already_read")]


@pytest.mark.parametrize(
    ("pairs", "fault"),
    [
        ([(2, True), (5, True), (6, False)], r"missing \[3\]"),
        ([(2, True), (3, False), (3, True), (5, True)], r"repeated \[3\]"),
    ],
    ids=["missing", "repeated"],
)
def test_extras_never_excuse_a_missing_or_repeated_offered_decision(
    pairs: list[tuple[int, bool]], fault: str
) -> None:
    with pytest.raises(SchemaError, match=fault) as caught:
        parse_call("choose_documents", _decisions(pairs), TABLES, [2, 3], not_readable=(5, 6))
    assert "[5]" not in str(caught.value), "an extra is never named as a fault"
    assert "not offered" not in str(caught.value)


def test_the_choice_and_its_extras_are_frozen() -> None:
    parsed = _choice([(1, True), (9, False)], [1])
    with pytest.raises(ValidationError):
        parsed.extras = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        parsed.extras[0].kind = "unknown"  # type: ignore[misc]
    assert ExtraDecision(document=9, kind="unknown") == parsed.extras[0]
    assert get_args(ExtraKind) == ("not_readable", "already_read", "unknown")


def test_already_read_and_not_readable_are_ignored_by_the_other_tools() -> None:
    parsed = parse_call(
        "suggest_codes",
        json.dumps({**WHY, "phase_group": "Landing"}),
        TABLES,
        [1],
        already_read=(2,),
        not_readable=(3,),
    )
    assert isinstance(parsed, SuggestCodes)


def test_choose_documents_refuses_bad_arguments() -> None:
    with pytest.raises(SchemaError, match="choose_documents"):
        parse_call("choose_documents", json.dumps({"decisions": "all", "reason": "r"}), TABLES)
    with pytest.raises(SchemaError, match="choose_documents"):
        parse_call("choose_documents", json.dumps({"decisions": []}), TABLES)


def test_offered_is_ignored_by_the_other_tools() -> None:
    parsed = parse_call(
        "suggest_codes", json.dumps({**WHY, "phase_group": "Landing"}), TABLES, [1, 2, 3]
    )
    assert isinstance(parsed, SuggestCodes)
