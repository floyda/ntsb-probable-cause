"""The ``board/1`` export format: what the public site is built against (decision 0173).

The export is JSON. Every file carries ``"format": "board/1"``. There are two kinds:

- ``index.json`` (:class:`BoardIndex`): the build stamp, the site-wide counts, and one row per
  closed case, newest closure first, then case number.
- ``cases/<case number>.json`` (:class:`CaseFile`): one closed case and the agent's trail.

The models here are the format. ``docs/schemas/board-1.schema.json`` is generated from them by
``scripts/board_schema.py`` and a test fails when the two drift apart, so any language can check
a file against the schema.

Version rule: adding an optional field keeps ``board/1``. Removing a field, renaming it, or
changing what it means makes ``board/2``.

An export never holds: the registration; the explanation written for a non-expert; any document
text; the evidence fingerprint; an aircraft's make and model; personal names; or anything about
an open case beyond the counts (specification S4 section 10.2). Titles, the agent's text and the
NTSB's cause statement pass through the names step before they reach these models.

This module is pure pydantic. It reads no run folder and no store.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

BOARD_FORMAT: Final = "board/1"

Grade = Literal[
    "same_first",
    "same_codes_other_order",
    "different",
    "abstained",
    "not_coded",
    "awaiting_ntsb",
]
CodeMark = Literal["same_place", "other_place", "not_in_other"]
NotOfferedReason = Literal[
    "not_pdf", "photo_only", "fetch_failed", "already_read", "over_size_limit"
]


class _Model(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )


class Code(_Model):
    """One occurrence or finding code and its label."""

    code: str
    label: str


class MarkedCode(Code):
    """An occurrence code marked against the other list: same place, other place, or absent."""

    mark: CodeMark


class Aircraft(_Model):
    """The aircraft as category and engines. Never make, model or registration."""

    category: str | None = Field(description="aircrafts[0].aircraftCategory, e.g. 'Airplane'.")
    engines: int | None = Field(description="aircrafts[0].aircraftNumberOfEngines.")
    engine_type: str | None = Field(description="aircrafts[0].engines[0].engineType.")


class BuildStamp(_Model):
    """When and from what the export was built."""

    built_at: datetime
    commit: str
    model: str
    training_cutoff: date
    training_cutoff_source: str
    launched_on: date | None = Field(
        default=None,
        description=(
            "The date of the first cloud night: the date the launch's backfill list was fixed "
            "(decision 0179). None when there is no backfill yet."
        ),
    )


class Counts(_Model):
    """The site-wide counts. The only thing the export says about open cases."""

    open_watched: int
    open_with_docket: int
    closures_per_night: dict[date, int] = Field(
        description=(
            "Cases closed on each night, counting only the closures the live queue takes "
            "(closed on or after 2026-09-23); the keys are ISO dates (YYYY-MM-DD)."
        )
    )
    coded: int
    not_coded: dict[str, int] = Field(description="Failure kind to number of cases.")
    awaiting_ntsb: int


class BoardRow(_Model):
    """One closed case on the board."""

    case_number: str
    mkey: int | None = Field(
        default=None,
        description=(
            "The NTSB's internal case key; the docket link is built from it. None in a file "
            "written before the field existed."
        ),
    )
    closed_on: date
    took_days: int = Field(description="Days from the accident to closure: closed_on - event date.")
    aircraft: Aircraft
    agent_first: Code | None
    ntsb_first: Code | None
    grade: Grade
    backfilled: bool | None = Field(
        default=None,
        description=(
            "True when the case closed before the live queue began and is in the launch's "
            "backfill list, False when it is not, None when there is no backfill. The list "
            "itself is never exported."
        ),
    )


class BoardIndex(_Model):
    """``index.json``: the build stamp, the counts and the board."""

    format: Literal["board/1"] = BOARD_FORMAT
    stamp: BuildStamp
    counts: Counts
    rows: tuple[BoardRow, ...] = Field(description="Newest closure first, then case number.")


class Facts(_Model):
    """The case's plain facts."""

    state: str | None = Field(description="eventStateOrRegion.")
    kind_of_flight: str | None = Field(
        description="aircrafts[0].ownerOperators[0].flightOperationType."
    )
    injury_level: str | None = Field(description="highestInjuryLevel.")
    documents_read: int
    documents_listed: int


class Withheld(_Model):
    """The line that says when and how the case was coded."""

    coded_at: datetime | None = Field(description="When the first call was sent, UTC.")
    commit: str
    prompt_version: str
    model: str = Field(description="The model asked for.")
    replied_models: tuple[str, ...]
    providers: tuple[str, ...]


class Answer(_Model):
    """Ellery's answer."""

    occurrence: tuple[Code, ...]
    findings: tuple[Code, ...]
    cause: str
    confidence: float
    abstained: bool


class Verdict(_Model):
    """The NTSB's verdict."""

    occurrence: tuple[Code, ...]
    findings: tuple[Code, ...]
    cause: str | None


class Comparison(_Model):
    """The answer set against the verdict."""

    agent_occurrence: tuple[MarkedCode, ...]
    ntsb_occurrence: tuple[MarkedCode, ...]
    findings_both: tuple[Code, ...]
    findings_ntsb_only: tuple[Code, ...]
    findings_agent_only: tuple[Code, ...]
    finding_precision_10: float | None
    finding_recall_10: float | None


class Belief(_Model):
    """The agent's belief at one checkpoint."""

    kind: Literal["h0", "h1", "h2", "answer"]
    first: Code
    cause: str
    account: str = Field(
        description="Ellery's evidence_narrative after the names step: the account that takes "
        "the place of the investigator's factual narrative."
    )
    confidence: float
    changed: bool = Field(description="The first code differs from the belief before.")
    cost_usd: float


class DocumentChoice(_Model):
    """One document of the docket and what the agent did with it."""

    position: int
    title: str = Field(description="After the names step.")
    decision: Literal["read", "skipped", "scan_only", "not_offered"] = Field(
        description=(
            "What the agent did with the document. read and skipped are its choices over a "
            "document it was offered. scan_only is a scan the reader could not turn into text. "
            "not_offered is a document not on offer at this read choice, other than a scan "
            "(see not_offered_reason); it never means a withheld document. A docket document "
            "that holds the NTSB's probable cause makes the whole case not coded (leak) instead."
        )
    )
    note: str | None = Field(description="The agent's expected_effect, after the names step.")
    pages: int | None = Field(
        default=None,
        description="The document's page count. None when not recorded.",
    )
    not_offered_reason: NotOfferedReason | None = Field(
        default=None,
        description=(
            "Why the document was not on offer at this read choice; set only when decision is "
            "not_offered, else None. not_pdf, photo_only and fetch_failed: the docket reader "
            "could not offer it as text. already_read: it was read at an earlier read choice, "
            "and a document read is never offered again. over_size_limit: a readable document "
            "left out by the prompt-size ceiling of decision 0152."
        ),
    )


class ReadChoice(_Model):
    """One read-or-skip choice over the docket."""

    step: Literal["choice1", "choice2"]
    reason: str
    documents: tuple[DocumentChoice, ...]
    cost_usd: float


class Lookup(_Model):
    """One coding lookup the agent made."""

    tool: str
    arguments: dict[str, object]
    cost_usd: float


class Trail(_Model):
    """The agent's steps and their cost."""

    beliefs: tuple[Belief, ...]
    read_choices: tuple[ReadChoice, ...]
    lookups: tuple[Lookup, ...]
    total_usd: float


class NotCoded(_Model):
    """Why a case was not coded: its failure kind and one fixed plain sentence."""

    kind: str
    sentence: str = Field(
        description="Chosen in code from NOT_CODED_SENTENCES, never failure text."
    )


class CaseFile(_Model):
    """``cases/<case number>.json``: one closed case and its trail."""

    format: Literal["board/1"] = BOARD_FORMAT
    case_number: str
    mkey: int | None = Field(
        default=None,
        description=(
            "The NTSB's internal case key; the docket link is built from it. None in a file "
            "written before the field existed."
        ),
    )
    closed_on: date
    took_days: int = Field(description="Days from the accident to closure.")
    aircraft: Aircraft
    grade: Grade
    facts: Facts | None = Field(description="None when the record was unreachable.")
    withheld: Withheld | None
    answer: Answer | None
    verdict: Verdict | None
    comparison: Comparison | None
    trail: Trail | None
    not_coded: NotCoded | None


NOT_CODED_SENTENCES: Final[Mapping[str, str]] = {
    "leak": (
        "A document in the docket held the NTSB's probable cause, "
        "so the case could not be shown to the agent."
    ),
    "schema": "The agent's reply failed a technical check twice.",
    "failed": "The agent's run stopped at a step that failed twice.",
    "model": "The model service did not return a usable reply.",
    "cap": "The case reached its cost limit before the agent answered.",
    "cap: context": "The case's documents were too long to send to the model.",
    "aborted": "The run was stopped before this case finished.",
    "missing result": "The run finished without a result for this case.",
    "unreachable": "The case's record or docket could not be read on seven nights.",
    "other": "The case could not be coded, for a reason the system does not name.",
}


def board_json_schema() -> dict[str, object]:
    """The JSON Schemas of both file kinds: ``{"index": ..., "case": ...}``.

    Generated in serialization mode, so a defaulted field such as ``format`` is required: the
    files are written by the export, and the site reads them as serialized. The optional
    fields added within ``board/1`` (``mkey``, ``launched_on``, ``backfilled``, ``pages``,
    ``not_offered_reason``) are therefore listed as required too, and every file written
    carries them (``null`` when unknown); the models still accept a file that lacks them.
    The schema lists these fields as required because every file we write carries them; a
    reader should still treat a missing key as null.
    """
    return {
        "index": BoardIndex.model_json_schema(mode="serialization"),
        "case": CaseFile.model_json_schema(mode="serialization"),
    }
