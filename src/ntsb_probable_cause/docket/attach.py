"""The one place docket text enters a record: the case context (decisions 0041, 0042, 0044)."""

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ntsb_probable_cause.docket.listing import render_listing
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.fields import AMATEUR_BUILT_LABEL
from ntsb_probable_cause.paths import resolve_path

DOCKET_KEY = "docket"

# Provenance header (decision 0038 item 2): a label for the type, then the page count, then
# the author's role the category implies. The agent is told what it reads, never that it is wrong.
_LABELS: Mapping[str, tuple[str, str]] = {
    "party_submission": ("Party submission", "submitted by a party to the investigation"),
    "pilot_form_6120": ("Pilot/operator accident report form", "written by the pilot or operator"),
    "photos": ("Photographs", "NTSB or its investigators"),
    "weather": ("Weather study or data", "NTSB or a weather service"),
    "maintenance_records": ("Maintenance records", "the aircraft's maintainers"),
    "medical_tox": ("Medical or toxicology report", "a medical examiner or laboratory"),
    "specialist_factual": ("Specialist factual report", "NTSB or its investigators"),
    "exam_site": ("Examination or site report", "NTSB or its investigators"),
    "conversation_statement": (
        "Statement or record of conversation",
        "a witness or party, recorded by an investigator",
    ),
    "atc_radar_data": ("Air traffic, radar or recorded data", "the FAA or a data source"),
    "manuals_reference": (
        "Manual or reference excerpt",
        "the manufacturer or a reference source",
    ),
    "other": ("Docket document", "author not given by the listing"),
}

_AMATEUR_BUILT_FLAG = "aircrafts[0].aircraftAmateurBuilt"
_MIN_REPLACE_LEN = 3


@dataclass(frozen=True)
class AttachResult:
    """The case context and what the attach step did to build it."""

    context: dict[str, object]
    attached: tuple[int, ...]
    not_available: tuple[str, ...]
    replacements: int


def header(record: DocumentRecord) -> str:
    """Render the provenance header.

    E.g. ``Party submission, 22 pages, submitted by a party to the investigation.``
    """
    label, role = _LABELS.get(record.category, _LABELS["other"])
    return f"{label}, {record.pages} pages, {role}."


def render_document(record: DocumentRecord, text: str) -> str:
    """Render the header line, then the page-marked text."""
    return f"{header(record)}\n{text}"


def amateur_built_replace(text: str, raw: Mapping[str, object]) -> tuple[str, int]:
    """Replace the recorded make and model of an amateur-built aircraft, counting replacements.

    Decision 0044: the strings are known from the record, so the replacement is mechanical; a
    variant spelling passes through, so the count is a floor.
    """
    flag = resolve_path(raw, _AMATEUR_BUILT_FLAG)
    if flag is False or flag is None:
        return text, 0
    count = 0
    for path in ("aircrafts[0].aircraftMake", "aircrafts[0].aircraftModel"):
        value = resolve_path(raw, path)
        if not isinstance(value, str) or len(value.strip()) < _MIN_REPLACE_LEN:
            continue
        # Word-boundary anchored (fix round 1, finding 1): an unanchored pattern matches a
        # builder surname that is also a substring of an ordinary word (a make of "Long"
        # would otherwise corrupt "longitudinal"), which both mangles evidence and inflates
        # ``replacements`` past being a floor on builder-name hits. The accepted trade-off is
        # that a make of "RV-7" no longer matches inside a model of "RV-7X" -- the model
        # field is still replaced whole, by its own pattern, so nothing is missed there.
        pattern = re.compile(rf"(?<!\w){re.escape(value.strip())}(?!\w)", re.IGNORECASE)
        text, n = pattern.subn(AMATEUR_BUILT_LABEL, text)
        count += n
    return text, count


def attach_docket(
    raw: Mapping[str, object], docket: Docket, *, documents: Sequence[int]
) -> AttachResult:
    """Build the case context: the record plus a ``docket`` subtree with the chosen documents.

    The raw record is copied, never mutated. Every document not attached is listed in
    ``not_available`` with its status when it could not have been read; a readable document
    left out by choice is not listed (the step record's ``arguments`` say what was chosen).
    """
    listing_text, replacements = amateur_built_replace(render_listing(docket.listing), raw)
    rendered: list[str] = []
    attached: list[int] = []
    for index in documents:
        record = docket.record(index)
        if record.status != "read":
            continue
        text, n = amateur_built_replace(render_document(record, docket.texts[index]), raw)
        replacements += n
        rendered.append(text)
        attached.append(index)
    not_available = tuple(
        f"{r.entry.index}: {r.status}" for r in docket.documents if r.status != "read"
    )
    context: dict[str, object] = copy.deepcopy(dict(raw))
    context[DOCKET_KEY] = {"listing": listing_text, "documents": rendered, "attached": attached}
    return AttachResult(context, tuple(attached), not_available, replacements)
