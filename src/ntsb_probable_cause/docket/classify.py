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

# Fix, morning findings 2026-09-19 finding 1: general-aviation dockets never use the word
# "submission" on its own (measured: 0 of 3,790 dev-400 titles), so the old
# ``r"party submission|submission"`` pattern never fired. Replaced with the NTSB's own explicit
# convention, ``Report(s) from Part(y|ies) to the Investigation`` (measured: 12 documents in 9
# of 401 dockets, every one genuinely a party submission); the literal phrase "party submission"
# is kept as an alternative in case it is ever used verbatim.
#
# Measured limit, not an apology (Andy's ruling, 2026-09-19): other party-authored documents do
# exist under neutral titles -- a manufacturer's technical report, a diagram a manufacturer
# provided -- and this pattern does not catch them; they are counted under whatever category
# their own words put them in. A first version of this fix tried to catch them structurally, by
# matching an author named after "by" wherever it was capitalised (e.g. "Crash Site Diagrams By
# Teledyne Continental"). Measured across all 3,790 dev-400 titles, that shape also matched
# documents credited to a body that is not a party to the investigation -- a police department,
# the FAA, a fuel vendor -- and, decisively, "Photo 6)View of Recovered Tree Branches Cut by
# Propeller Strikes.", where "by" marks physical causation, not authorship: capitalisation alone
# cannot tell the two apart. Telling a genuine party's contribution from an independent body's
# would need a list of organisation names, which is exactly what Andy ruled against (it would go
# stale). So this category reports only the documents the NTSB itself labels as party
# submissions.
_PARTY_SUBMISSION = r"party submission|reports? from part(?:y|ies) to the investigation"
# "Statement of Party Representatives to NTSB Investigation" is the administrative roster (138
# of 3,790 titles): a list of who the parties are, not a submission and not a statement of
# evidence. It must never reach party_submission, and -- left unhandled -- it would fall through
# to conversation_statement's own "statement" match, so it is routed to "other" unconditionally.
_ROSTER = re.compile(r"statement of party representatives")

# Title categories, first match wins (../ntsb-spike/scripts/docket_shape_probe.py CATEGORIES,
# plus party_submission, first so a genuine submission is never shadowed by a later category).
# A judgement, not an NTSB taxonomy; the error rate is measured by Andy's 60-title hand-check
# (decision 0039 item 3).
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("party_submission", _PARTY_SUBMISSION),
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


def document_category(title: str) -> str:
    """The first category whose pattern matches the title.

    The listing's file-type column is never consulted: the NTSB writes ``Text/Image`` for a
    scanned document that holds both text and pictures, and that string contains the word
    *image*, so joining it into the match text made ``photos`` fire on titles like
    ``WITNESS STATEMENTS`` whatever the title said -- 225 documents in 31 of 401 dev-400
    dockets, 138 of them holding readable text, dropped from arm B before extraction
    (``docs/results/s2-doctype.txt``).

    The roster (finding 1c) is checked first and unconditionally: it must land on "other"
    regardless of category order, not merely avoid being caught by ``party_submission``.
    """
    text = title.lower()
    if _ROSTER.search(text):
        return "other"
    for name, pattern in _COMPILED:
        if pattern.search(text):
            return name
    return "other"
