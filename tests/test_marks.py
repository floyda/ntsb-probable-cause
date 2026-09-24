"""Marks: computed in the split, carried as bookkeeping, never rendered (S2.6 §4, 0078)."""

import copy

import pytest

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.guard import (
    MARKED_SENTENCES,
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


QUOTED = (
    "Examination of the engine revealed no mechanical anomalies"
    " that would have precluded normal operation."
)
ANALYSIS = QUOTED + " The fuel selector was found positioned to an empty tank."
CAUSE = (
    "The pilot's improper fuel management, which resulted in a loss of engine power due to"
    " fuel starvation."
)


def _analysed(record_fixtures: list[dict[str, object]], *documents: str) -> dict[str, object]:
    raw = _case(record_fixtures, *documents)
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["analysisNarrative"] = ANALYSIS
    narratives[0]["probableCause"] = CAUSE
    return raw


def test_only_the_docket_documents_analysis_pair_is_marked() -> None:
    assert frozenset({("docket_documents", "analysis_narrative")}) == MARKED_SENTENCES


def test_an_analysis_sentence_in_a_document_marks_and_reaches_the_agent(
    record_fixtures: list[dict[str, object]],
) -> None:
    document = f"Docket item 1, 2 pages.\n[page 1 of 2]\n{QUOTED}"
    evidence, _, _ = split_record(_analysed(record_fixtures, document))
    assert CaseMark(kind="analysis_sentence", count=1) in evidence.marks
    assert "no mechanical anomalies" in Payload.from_evidence(evidence).text
    assert "analysis_sentence" not in Payload.from_evidence(evidence).text


def test_an_analysis_sentence_outside_the_documents_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = _analysed(record_fixtures)
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["prelimNarrative"] = QUOTED
    with pytest.raises(LeakageError, match="sentence from analysis_narrative in prelim"):
        split_record(raw)


def test_a_probable_cause_in_a_document_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    with pytest.raises(LeakageError, match="from probable_cause in docket_documents"):
        split_record(_analysed(record_fixtures, f"Letter.\n{CAUSE}"))


def test_the_whole_analysis_in_a_document_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    with pytest.raises(LeakageError, match="text from analysis_narrative in docket_documents"):
        split_record(_analysed(record_fixtures, ANALYSIS))


def test_a_code_in_a_document_still_refuses(record_fixtures: list[dict[str, object]]) -> None:
    raw = _analysed(record_fixtures)
    _, _, verdict = split_record(raw)
    code = verdict.codes()[0]
    with pytest.raises(LeakageError, match="code from codes in docket_documents"):
        split_record(_analysed(record_fixtures, f"Table row {code} noted."))
