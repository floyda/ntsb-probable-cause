"""Tests for ``scripts/s3_probe/prompts.py``: system text, schemas, parsers and the menu."""

import json
from typing import Any

import pytest
from scripts.s3_probe.cases import DocketFacts, facts
from scripts.s3_probe.prompts import (
    CODING_ACTION_SCHEMA,
    GUIDANCE,
    READ_CHOICE_SCHEMA,
    CodingAction,
    base_system,
    menu,
    parse_coding_action,
    parse_read_choice,
)

from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables

TABLES = load_tables()

_DISTINCTIVE_TITLE = "Factual Report of the Sole Surviving Witness, Jane Q. Doe"


def _entry(index: int, *, title: str = "doc") -> ListingEntry:
    return ListingEntry(
        index=index,
        title=title,
        pages=1,
        photos=0,
        doc_type="",
        extension="pdf",
        href="/x",
    )


def _docket(rows: list[tuple[int, str, str | None, int, int, str]]) -> Docket:
    """Build a docket from ``(index, status, kind, pages, transcribed_pages, title)`` rows."""
    records = tuple(
        DocumentRecord(
            entry=_entry(index, title=title),
            category="exam_site",
            status=status,
            pages=pages,
            readable_pages=pages if status == "read" else 0,
            estimated_tokens=123,
            kind=kind,
            transcribed_pages=transcribed_pages,
        )
        for index, status, kind, pages, transcribed_pages, title in rows
    )
    listing = Listing(mkey=1, declared_items=len(rows), entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=records, texts={})


# --------------------------------------------------------------------------------------------
# base_system
# --------------------------------------------------------------------------------------------


def test_base_system_matches_runner_system_text_with_no_case_number() -> None:
    expected = (
        f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(TABLES)}{prompt.guidance_block(GUIDANCE)}"
    )
    assert base_system(TABLES) == expected


def test_guidance_is_the_kept_rounds() -> None:
    assert GUIDANCE == ("r3-loc-stall", "r6-aircraft-control")


# --------------------------------------------------------------------------------------------
# Schema strictness
# --------------------------------------------------------------------------------------------


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


def test_read_choice_schema_is_strict() -> None:
    _assert_strict(READ_CHOICE_SCHEMA)


def test_coding_action_schema_is_strict() -> None:
    _assert_strict(CODING_ACTION_SCHEMA)


def test_coding_action_schema_constrains_tool_and_kind_enums() -> None:
    properties: dict[str, Any] = CODING_ACTION_SCHEMA["properties"]  # type: ignore[assignment]
    tool_variants = properties["tool"]["anyOf"]
    kind_variants = properties["kind"]["anyOf"]
    tool_enum = next(v["enum"] for v in tool_variants if "enum" in v)
    kind_enum = next(v["enum"] for v in kind_variants if "enum" in v)
    assert set(tool_enum) == {"describe_codes", "occurrence_usage", "past_findings"}
    assert set(kind_enum) == {"occurrence", "finding_category", "item"}


# --------------------------------------------------------------------------------------------
# parse_read_choice
# --------------------------------------------------------------------------------------------


def _read_choice_reply(pairs: list[tuple[int, bool]], *, reason: str = "reason") -> str:
    return json.dumps(
        {
            "documents": [{"index": i, "read": r, "expected_effect": "effect"} for i, r in pairs],
            "reason": reason,
        }
    )


def test_parse_read_choice_accepts_good_reply() -> None:
    choice = parse_read_choice(_read_choice_reply([(1, True), (2, False)]), offered=[1, 2])
    assert [d.index for d in choice.documents] == [1, 2]
    assert choice.documents[0].read is True
    assert choice.reason == "reason"


def test_parse_read_choice_rejects_missing_index() -> None:
    with pytest.raises(SchemaError, match="missing"):
        parse_read_choice(_read_choice_reply([(1, True)]), offered=[1, 2])


def test_parse_read_choice_rejects_duplicate_index() -> None:
    with pytest.raises(SchemaError, match="more than once"):
        parse_read_choice(_read_choice_reply([(1, True), (1, False)]), offered=[1])


def test_parse_read_choice_rejects_unknown_index() -> None:
    with pytest.raises(SchemaError, match="not offered"):
        parse_read_choice(_read_choice_reply([(1, True), (9, False)]), offered=[1])


def test_parse_read_choice_rejects_invalid_json() -> None:
    with pytest.raises(SchemaError):
        parse_read_choice("not json", offered=[1])


def test_parse_read_choice_rejects_schema_violation() -> None:
    with pytest.raises(SchemaError):
        parse_read_choice(json.dumps({"documents": [], "reason": 5}), offered=[])


# --------------------------------------------------------------------------------------------
# menu
# --------------------------------------------------------------------------------------------


def test_menu_never_contains_a_title() -> None:
    docket = _docket(
        [
            (1, "read", "born-digital", 3, 0, _DISTINCTIVE_TITLE),
            (2, "unreadable: scan", "scan", 5, 2, _DISTINCTIVE_TITLE),
        ]
    )
    rendered = menu(facts(docket), offered=[1])
    assert _DISTINCTIVE_TITLE not in rendered


def test_menu_line_format_with_transcribed_pages() -> None:
    one = DocketFacts(
        index=3,
        kind="scan",
        pages=5,
        readable_pages=2,
        estimated_tokens=400,
        transcribed_pages=2,
        status="read",
    )
    rendered = menu([one], offered=[3])
    assert rendered == "3: 5 pages, 2 readable, about 400 tokens, scan, transcribed pages: 2"


def test_menu_line_format_without_transcribed_pages() -> None:
    one = DocketFacts(
        index=1,
        kind="born-digital",
        pages=3,
        readable_pages=3,
        estimated_tokens=300,
        transcribed_pages=0,
        status="read",
    )
    rendered = menu([one], offered=[1])
    assert rendered == "1: 3 pages, 3 readable, about 300 tokens, born-digital"


def test_menu_unknown_kind_renders_as_unknown() -> None:
    one = DocketFacts(
        index=1,
        kind=None,
        pages=1,
        readable_pages=0,
        estimated_tokens=0,
        transcribed_pages=0,
        status="unreadable: not a pdf",
    )
    rendered = menu([one], offered=[])
    assert "unknown" not in rendered  # not offered, so it appears only in the unavailable line
    rendered_offered = menu([one], offered=[1])
    assert "1: 1 pages, 0 readable, about 0 tokens, unknown" in rendered_offered


def test_menu_already_read_line() -> None:
    one = DocketFacts(
        index=1,
        kind="born-digital",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        transcribed_pages=0,
        status="read",
    )
    two = DocketFacts(
        index=2,
        kind="born-digital",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        transcribed_pages=0,
        status="read",
    )
    rendered = menu([one, two], offered=[2], already_read=[1])
    assert "Already read: 1" in rendered


def test_menu_not_available_line_lists_status() -> None:
    readable = DocketFacts(
        index=1,
        kind="born-digital",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        transcribed_pages=0,
        status="read",
    )
    scan = DocketFacts(
        index=2,
        kind="scan",
        pages=1,
        readable_pages=0,
        estimated_tokens=0,
        transcribed_pages=0,
        status="unreadable: scan",
    )
    rendered = menu([readable, scan], offered=[1])
    assert "Not available to read: 2 (unreadable: scan)" in rendered


def test_menu_no_unavailable_line_when_everything_is_read() -> None:
    one = DocketFacts(
        index=1,
        kind="born-digital",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        transcribed_pages=0,
        status="read",
    )
    rendered = menu([one], offered=[1])
    assert "Not available" not in rendered


# --------------------------------------------------------------------------------------------
# parse_coding_action
# --------------------------------------------------------------------------------------------


def _coding_reply(  # noqa: PLR0913 -- one keyword per schema field under test, all defaulted
    *,
    done: bool = False,
    tool: str | None = "describe_codes",
    kind: str | None = "occurrence",
    codes: list[str] | None = None,
    phase: str = "552",
    event: str = "230",
) -> str:
    return json.dumps(
        {
            "done": done,
            "tool": tool,
            "kind": kind,
            "codes": codes if codes is not None else ["552230"],
            "reason": "reason",
            "expected_effect": "effect",
            "top3": [{"phase": phase, "event": event, "probability": 0.5}],
        }
    )


def _tables() -> CodeTables:
    return CodeTables(
        phases={"552": "Landing"},
        events={"230": "Loss of control on ground"},
        categories={},
        items={},
        modifiers={},
    )


def test_parse_coding_action_accepts_good_tool_call() -> None:
    action = parse_coding_action(_coding_reply(), _tables())
    assert isinstance(action, CodingAction)
    assert action.done is False
    assert action.tool == "describe_codes"


def test_parse_coding_action_accepts_good_done_reply() -> None:
    action = parse_coding_action(
        _coding_reply(done=True, tool=None, kind=None, codes=[]), _tables()
    )
    assert action.done is True
    assert action.tool is None


def test_parse_coding_action_rejects_bad_phase_digits() -> None:
    with pytest.raises(SchemaError):
        parse_coding_action(_coding_reply(phase="X52"), _tables())


def test_parse_coding_action_rejects_unknown_phase() -> None:
    with pytest.raises(SchemaError):
        parse_coding_action(_coding_reply(phase="999"), _tables())


def test_parse_coding_action_rejects_unknown_event() -> None:
    with pytest.raises(SchemaError):
        parse_coding_action(_coding_reply(event="999"), _tables())


def test_parse_coding_action_rejects_done_false_without_tool() -> None:
    with pytest.raises(SchemaError, match="no tool"):
        parse_coding_action(_coding_reply(done=False, tool=None, kind=None, codes=[]), _tables())


def test_parse_coding_action_rejects_invalid_json() -> None:
    with pytest.raises(SchemaError):
        parse_coding_action("not json", _tables())


def test_parse_coding_action_rejects_unknown_tool_name() -> None:
    with pytest.raises(SchemaError):
        parse_coding_action(json.dumps({"tool": "not_a_tool"}), _tables())
