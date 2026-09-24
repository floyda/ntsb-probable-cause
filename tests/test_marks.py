"""Marks: computed in the split, carried as bookkeeping, never rendered (S2.6 §4, 0078)."""

import copy

import pytest

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.guard import (
    NARRATIVE_COVERAGE_MARK,
    narrative_shares,
    sentence_needles,
)
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.records.split import split_record

FACTUAL = (
    "The airplane departed from runway 27 at 0915. "
    "Witnesses observed the airplane climb to about 300 feet. "
    "The engine then lost power and the airplane descended into a field. "
    "The pilot reported that the fuel selector was positioned to the left tank."
)
S1, S2, S3, S4 = (s.strip() for s in FACTUAL.split(". "))


def _case(record_fixtures: list[dict[str, object]], *documents: str) -> dict[str, object]:
    raw = copy.deepcopy(record_fixtures[0])
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["concatenatedFactualNarrative"] = FACTUAL
    raw["docket"] = {"listing": "Docket item 1, 1 page.", "documents": list(documents)}
    return raw


def test_sentence_needles_are_the_guards_own_sentences() -> None:
    needles = sentence_needles(FACTUAL)
    assert len(needles) == 4
    assert "witnesses observed the airplane climb to about 300 feet" in needles


def test_one_share_per_document() -> None:
    shares = narrative_shares([f"{S1}. {S2}.", f"{S3}.", "Nothing shared."], FACTUAL)
    assert shares == (0.5, 0.25, 0.0)
    assert narrative_shares([], FACTUAL) == ()
    assert narrative_shares(["x"], None) == ()


def test_half_the_narrative_in_one_document_marks_the_case(
    record_fixtures: list[dict[str, object]],
) -> None:
    evidence, _, _ = split_record(_case(record_fixtures, f"{S1}. {S2}.", f"{S3}."))
    assert evidence.narrative_share == NARRATIVE_COVERAGE_MARK
    assert evidence.marks == (CaseMark(kind="narrative_coverage", count=1),)


def test_under_half_is_recorded_but_not_marked(record_fixtures: list[dict[str, object]]) -> None:
    evidence, _, _ = split_record(_case(record_fixtures, f"{S1}.", f"{S3}."))
    assert evidence.narrative_share == 0.25
    assert evidence.marks == ()


def test_no_documents_no_share(record_fixtures: list[dict[str, object]]) -> None:
    raw = copy.deepcopy(record_fixtures[0])
    evidence, _, _ = split_record(raw)
    assert evidence.narrative_share is None
    assert evidence.marks == ()


def test_a_mark_never_reaches_the_payload(record_fixtures: list[dict[str, object]]) -> None:
    evidence, _, _ = split_record(_case(record_fixtures, f"{S1}. {S2}. {S3}."))
    assert evidence.marks
    text = Payload.from_evidence(evidence).text
    assert "narrative_coverage" not in text
    assert "narrative_share" not in text
    assert "marks" not in Payload.from_evidence(evidence).fields()


def test_the_whole_narrative_in_a_document_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    with pytest.raises(LeakageError, match="text from factual_narrative"):
        split_record(_case(record_fixtures, FACTUAL))
