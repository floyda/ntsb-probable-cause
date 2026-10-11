"""The board/1 format, its committed JSON Schema and its invented sample (decision 0173)."""

import json
from pathlib import Path
from typing import get_args

from tests import board_sample

from ntsb_probable_cause.live.export import (
    NOT_CODED_SENTENCES,
    BoardIndex,
    CaseFile,
    Grade,
    board_json_schema,
)
from ntsb_probable_cause.live.records import FAILURE_KINDS

SAMPLE = Path("tests/fixtures/board")
SCHEMA = Path("docs/schemas/board-1.schema.json")


def test_sample_index_validates() -> None:
    BoardIndex.model_validate_json((SAMPLE / "index.json").read_text())


def test_sample_cases_validate_and_cover_every_grade() -> None:
    files = sorted((SAMPLE / "cases").glob("*.json"))
    grades = {CaseFile.model_validate_json(f.read_text()).grade for f in files}
    assert grades == set(get_args(Grade))


def test_committed_schema_matches_the_models() -> None:
    committed = json.loads(SCHEMA.read_text())
    assert committed == board_json_schema()


def test_committed_sample_matches_its_builder() -> None:
    built = board_sample.build()
    on_disk = {p.relative_to(SAMPLE).as_posix(): p.read_text() for p in SAMPLE.rglob("*.json")}
    assert built == on_disk


def test_every_failure_kind_has_a_sentence() -> None:
    assert set(NOT_CODED_SENTENCES) >= {*FAILURE_KINDS, "cap: context", "other", "unreachable"}


def test_the_sample_holds_no_forbidden_value() -> None:
    text = "\n".join(p.read_text() for p in SAMPLE.rglob("*.json"))
    for forbidden in board_sample.FORBIDDEN:
        assert forbidden not in text


def test_sample_shape_for_the_site() -> None:
    index = BoardIndex.model_validate_json((SAMPLE / "index.json").read_text())
    assert index.rows[0].case_number == "XXX26XX001"
    first = CaseFile.model_validate_json((SAMPLE / "cases/XXX26XX001.json").read_text())
    assert first.trail is not None
    assert len(first.trail.read_choices) == 2
    assert [b.kind for b in first.trail.beliefs] == ["h0", "h1", "h2", "answer"]
    assert any(d.decision == "scan_only" for rc in first.trail.read_choices for d in rc.documents)


def test_trails_agree_with_the_facts() -> None:
    for path in sorted((SAMPLE / "cases").glob("*.json")):
        case = CaseFile.model_validate_json(path.read_text())
        if case.trail is None or case.facts is None:
            continue
        docs = [d for rc in case.trail.read_choices for d in rc.documents]
        listed = {d.position for d in docs}
        read = {d.position for d in docs if d.decision == "read"}
        if case.facts.documents_listed:
            assert len(listed) == case.facts.documents_listed, path.name
            assert len(read) == case.facts.documents_read, path.name
        assert case.trail.total_usd == round(
            sum(b.cost_usd for b in case.trail.beliefs)
            + sum(r.cost_usd for r in case.trail.read_choices)
            + sum(x.cost_usd for x in case.trail.lookups),
            4,
        ), path.name


def test_schema_requires_the_format_field() -> None:
    schema = board_json_schema()
    assert "format" in schema["index"]["required"]  # type: ignore[index]
    assert "format" in schema["case"]["required"]  # type: ignore[index]
