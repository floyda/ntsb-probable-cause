"""Readable / scan / partial by characters per page (spec §5.2), and the title classifier (§7.2)."""

import pytest

from ntsb_probable_cause.docket.classify import (
    BORN_DIGITAL_MIN_CHARS_PER_PAGE,
    SCAN_PAGE_MAX_CHARS,
    classify_pages,
    document_category,
    estimated_tokens,
    readable_pages,
)


def test_thresholds_are_the_spikes() -> None:
    assert (SCAN_PAGE_MAX_CHARS, BORN_DIGITAL_MIN_CHARS_PER_PAGE) == (50, 300)


def test_born_digital_scan_and_partial() -> None:
    assert classify_pages([1200, 900, 400]) == "born-digital"
    assert classify_pages([0, 12, 3]) == "scan"
    assert classify_pages([600, 0, 0, 0]) == "partial"
    assert classify_pages([]) == "scan"


def test_readable_pages_counts_pages_over_the_scan_threshold() -> None:
    assert readable_pages([600, 0, 51, 50]) == 2


def test_estimated_tokens_is_characters_over_four() -> None:
    assert estimated_tokens(4001) == 1000


@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("Party Submission - Lycoming Engines", "party_submission"),
        ("Pilot/Operator Aircraft Accident Report 6120.1", "pilot_form_6120"),
        ("Weather Study Report", "weather"),
        ("MAINTENANCE RECORDS -- ENGINE", "maintenance_records"),
        ("Medical Factual Report", "medical_tox"),
        ("Powerplant Examination Report", "exam_site"),
        ("Record of Conversation - witness", "conversation_statement"),
        ("ATC Transcript", "atc_radar_data"),
        ("Photographs", "photos"),
        ("Something unusual", "other"),
    ],
)
def test_document_category_by_title(title: str, category: str) -> None:
    assert document_category(title) == category


# Fix, morning findings 2026-09-19 finding 1: the old ``r"party submission|submission"``
# pattern never fired on real data -- 0 of 3,790 dev-400 titles contain "submission" in any
# casing, because general-aviation dockets do not use the word. These titles are the NTSB's
# own real shapes, quoted from the findings file (safe: no personal names).
@pytest.mark.parametrize(
    ("title", "category"),
    [
        # The NTSB's explicit convention: high confidence, measured 12 documents in 9 of 401
        # dockets, every one genuinely a party submission.
        (
            "Reports from Parties to the Investigation: Excerpts From Piper Wreckage "
            "Documentation.",
            "party_submission",
        ),
        ("Report from Party to the Investigation - Weldon Pump", "party_submission"),
    ],
)
def test_party_submission_matches_the_ntsb_explicit_convention(title: str, category: str) -> None:
    assert document_category(title) == category


def test_party_submission_still_matches_the_literal_phrase() -> None:
    """Backward compatible: an unambiguous literal title is still recognised."""
    assert document_category("Party Submission - Lycoming Engines") == "party_submission"


def test_the_administrative_roster_is_not_a_submission_and_is_not_shadowed() -> None:
    """Finding 1c: the roster (138 of 3,790 titles) is administrative, not evidence -- it must
    land on "other", not "party_submission" and not "conversation_statement" (which it would
    otherwise match on its own "statement" keyword).
    """
    assert document_category("Statement of Party Representatives to NTSB Investigation") == "other"


# Andy's ruling, 2026-09-19: a first version of the fix also matched an author named after
# "by", capitalised. Measured across all 3,790 dev-400 titles, that shape matched documents
# credited to a body that is not a party to the investigation, and -- decisively -- this title,
# where "by" marks physical causation, not authorship. It is kept as a regression guard: the
# narrowed pattern (explicit convention only) must not classify it as party_submission.
def test_a_by_clause_naming_a_cause_not_an_author_is_not_a_party_submission() -> None:
    assert (
        document_category("Photo 6)View of Recovered Tree Branches Cut by Propeller Strikes.")
        != "party_submission"
    )


# Regression, task 16b: the NTSB writes "Text/Image" in the listing's file-type column for a
# scanned document that holds both text and pictures. Joining that column into the match text
# made "photos" fire on titles like these whatever they said, dropping the whole document from
# arm B before any text was extracted -- 225 documents in 31 of 401 dev-400 dockets, 138 of
# them holding readable text (docs/results/s2-doctype.txt). document_category no longer takes
# doc_type at all, so these assert the title alone gives each document's real category.
@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("WITNESS STATEMENTS", "conversation_statement"),
        ("TOXICOLOGICAL REPORT", "medical_tox"),
        ("TRANSCRIPT OF RADIO COMMUNICATIONS", "atc_radar_data"),
        ("AIRFRAME EXAMINATION SUMMARY", "exam_site"),
        ("MAINTENANCE RECORDS", "maintenance_records"),
    ],
)
def test_the_file_type_column_no_longer_overrides_the_title(title: str, category: str) -> None:
    result = document_category(title)
    assert result == category
    assert result != "photos"
