"""Readable, scanned or partial by characters per page (spec §5.2); document type by title.

Spec §7.2.
"""

import re
from collections.abc import Sequence
from typing import Literal

# Thresholds from the spike's session A9 (../ntsb-spike/scripts/a9_pdf_extract.py), carried
# over so the eras compare (decision 0040 item 2); the characters-per-page distribution of
# dev-400 is published in docs/results/s2-shape-dev.txt (spec §10, first row).
SCAN_PAGE_MAX_CHARS = 50
BORN_DIGITAL_MIN_CHARS_PER_PAGE = 300

Kind = Literal["born-digital", "scan", "partial"]

# Title categories, first match wins (../ntsb-spike/scripts/docket_shape_probe.py CATEGORIES,
# plus party_submission). A judgement, not an NTSB taxonomy; the error rate is measured by
# Andy's 60-title hand-check (decision 0039 item 3).
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("party_submission", r"party submission|submission"),
    (
        "pilot_form_6120",
        r"6120|pilot/operator|pilot operator|pilot.s aircraft accident"
        r"|operator.s aircraft accident",
    ),
    ("photos", r"photo|image|picture|video still"),
    ("weather", r"weather|metar|meteorolog|forecast|sigmet|airmet|carburetor icing"),
    (
        "maintenance_records",
        r"maintenance|logbook|log book|engine log|aircraft log|airframe log|work order|invoice"
        r"|annual inspection",
    ),
    ("medical_tox", r"autopsy|toxicolog|medical|pathology|coroner|medical examiner"),
    (
        "specialist_factual",
        r"factual report|specialist|group chair|laboratory|metallurg|performance|study"
        r"|recorded flight data|engine data monitor",
    ),
    ("exam_site", r"exam|wreckage|teardown|site|inspection|memorandum for record"),
    (
        "conversation_statement",
        r"record of conversation|conversation|\broc\b|interview|statement|witness"
        r"|correspondence|email",
    ),
    (
        "atc_radar_data",
        r"\batc\b|air traffic|radar|ads-b|track|audio|transcript|video|tower|gps|recorder"
        r"|csv|data",
    ),
    (
        "manuals_reference",
        r"manual|\bpoh\b|handbook|excerpt|specification|airport information|chart|map|advisory",
    ),
)
_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in CATEGORIES)


def classify_pages(chars_by_page: Sequence[int]) -> Kind:
    """Born-digital over 300 characters a page on average, scan under 50, else partial."""
    if not chars_by_page:
        return "scan"
    per_page = sum(chars_by_page) / len(chars_by_page)
    if per_page > BORN_DIGITAL_MIN_CHARS_PER_PAGE:
        return "born-digital"
    return "scan" if per_page < SCAN_PAGE_MAX_CHARS else "partial"


def readable_pages(chars_by_page: Sequence[int]) -> int:
    """Pages with more than the scan threshold of characters."""
    return sum(1 for c in chars_by_page if c > SCAN_PAGE_MAX_CHARS)


def estimated_tokens(chars: int) -> int:
    """The spike's estimate: one token per four characters."""
    return chars // 4


def document_category(title: str, doc_type: str) -> str:
    """The first category whose pattern matches the title or the page's type column."""
    text = f"{title} {doc_type}".lower()
    for name, pattern in _COMPILED:
        if pattern.search(text):
            return name
    return "other"
