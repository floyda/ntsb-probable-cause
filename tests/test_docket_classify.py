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
    ("title", "doc_type", "category"),
    [
        ("Party Submission - Lycoming Engines", "Submission", "party_submission"),
        ("Pilot/Operator Aircraft Accident Report 6120.1", "Form", "pilot_form_6120"),
        ("Weather Study Report", "Report", "weather"),
        ("MAINTENANCE RECORDS -- ENGINE", "Records", "maintenance_records"),
        ("Medical Factual Report", "Report", "medical_tox"),
        ("Powerplant Examination Report", "Report", "exam_site"),
        ("Record of Conversation - witness", "ROC", "conversation_statement"),
        ("ATC Transcript", "Transcript", "atc_radar_data"),
        ("Photographs", "Photos", "photos"),
        ("Something unusual", "", "other"),
    ],
)
def test_document_category_by_title(title: str, doc_type: str, category: str) -> None:
    assert document_category(title, doc_type) == category
