"""scripts/s3_probe/prompts.py: system text, reply schemas and the document menu (task 3).

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

Every string here that reaches the model is either an existing prompt text
(:mod:`ntsb_probable_cause.scoring.prompt`), this probe's own instructions, or numbers keyed
by listing index (never a title, never docket text) -- the "one payload route" constraint in
``constraints.md``. Task 4's loop builds the full system text for each step by concatenating
these pieces with :data:`ntsb_probable_cause.scoring.tools.TOOL_DESCRIPTIONS` (via
:mod:`scripts.s3_probe.tools`) and its own running tool-result log; nothing here embeds the
tool list, so the description is composed once, at call time, not duplicated in two places.
"""

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import OccurrenceGuess, strict_schema
from scripts.s3_probe.cases import DocketFacts
from scripts.s3_probe.tools import TOOL_NAMES

# S2.7's kept rounds (round 3; round 6 kept by decision 0106) -- fixed for this probe, per
# constraints.md's "Prompt" bullet. Task 5's run records it in ``probe.json``.
GUIDANCE: tuple[str, ...] = ("r3-loc-stall", "r6-aircraft-control")


def base_system(tables: CodeTables) -> str:
    r"""The H0 system text: ``runner._system_text`` with no case number and this guidance.

    Equal, by construction, to
    ``f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables)}{prompt.guidance_block(GUIDANCE)}"``
    -- the same call the runner makes for arm B with ``include_case_number=False`` -- because
    it is built from the same two functions, never a copy of their text.
    """
    tables_text = prompt.tables_block(tables)
    return f"{prompt.SYSTEM_ANSWER}\n\n{tables_text}{prompt.guidance_block(GUIDANCE)}"


# --------------------------------------------------------------------------------------------
# Read choice (flow steps 2 and 4)
# --------------------------------------------------------------------------------------------

READ_CHOICE_INSTRUCTIONS = """For each document listed below, decide whether to read it, given
your current hypothesis. For each one, say what you expect it to show against that hypothesis --
what would change your coding, and what would leave it as it is. Reading a document costs money
and time, so read only what your hypothesis needs, not everything offered. A scanned or
handwritten document is read through a transcription of its pages, which may contain
"[illegible]" where a word could not be read; it is not the original image. Decide for every
document listed, including the ones you choose not to read, and say why in one line."""


class DocumentChoice(BaseModel):
    """One offered document: read it or not, and what the agent expects from it."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int
    read: bool
    expected_effect: str


class ReadChoice(BaseModel):
    """The reply to a read-choice step: one decision per offered document, plus a reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    documents: tuple[DocumentChoice, ...]
    reason: str


READ_CHOICE_SCHEMA: dict[str, object] = strict_schema(ReadChoice)


def parse_read_choice(text: str, offered: Sequence[int]) -> ReadChoice:
    """Parse a read-choice reply; every offered index must appear exactly once.

    Args:
        text: the raw JSON reply.
        offered: the listing indices offered at this step.

    Returns:
        The parsed :class:`ReadChoice`.

    Raises:
        SchemaError: invalid JSON, a validation failure, an index not offered, a duplicate
            index, or an offered index missing from the reply.
    """
    try:
        choice = ReadChoice.model_validate(json.loads(text))
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"reply is not a ReadChoice: {error}") from error
    offered_set = set(offered)
    seen: set[int] = set()
    for document in choice.documents:
        if document.index not in offered_set:
            raise SchemaError(f"read choice named index {document.index}, not offered")
        if document.index in seen:
            raise SchemaError(f"read choice named index {document.index} more than once")
        seen.add(document.index)
    missing = sorted(offered_set - seen)
    if missing:
        raise SchemaError(f"read choice is missing offered index(es): {missing}")
    return choice


def menu(
    facts: Sequence[DocketFacts],
    offered: Sequence[int],
    *,
    already_read: Sequence[int] = (),
) -> str:
    """Render the document menu for a read-choice step: numbers and kinds only, never a title.

    One line per offered document, in listing-index order, then an "Already read:" line if
    any index was already read, then a "Not available to read:" line naming every document in
    ``facts`` whose status is not ``"read"`` (the docket's own unreadable and undelivered
    entries -- offered documents are already ``"read"``, so this line never repeats one of
    them).

    Args:
        facts: every document's measured facts (:func:`scripts.s3_probe.cases.facts`).
        offered: the listing indices offered at this step.
        already_read: indices the agent chose to read at an earlier step.

    Returns:
        The rendered menu text.
    """
    by_index = {f.index: f for f in facts}
    lines: list[str] = []
    for index in offered:
        one = by_index[index]
        kind = one.kind if one.kind is not None else "unknown"
        line = (
            f"{index}: {one.pages} pages, {one.readable_pages} readable, "
            f"about {one.estimated_tokens} tokens, {kind}"
        )
        if one.transcribed_pages > 0:
            line += f", transcribed pages: {one.transcribed_pages}"
        lines.append(line)
    if already_read:
        lines.append("Already read: " + ", ".join(str(i) for i in already_read))
    unavailable = [f for f in facts if f.status != "read"]
    if unavailable:
        lines.append(
            "Not available to read: " + ", ".join(f"{f.index} ({f.status})" for f in unavailable)
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# Coding checks (flow step 7)
# --------------------------------------------------------------------------------------------

CODING_INSTRUCTIONS = """You have written your own coding (your last hypothesis). Now check it
against how the NTSB has coded past accidents, using the tools below. The counts describe what
is usual across past cases; they are not evidence about this accident. Keep a less usual code
when this case's evidence supports it. Check the occurrence -- which event defines the accident,
and its phase -- before the findings.

To call a tool, set done to false and give the tool name, its kind, and the codes to pass it.
Say in reason why you make the call, and in expected_effect what you expect it to show. Give
top3 on every reply: your current best occurrence guesses (up to three, with probabilities),
updated as the checks change your view. When your coding is settled, set done to true, tool and
kind to null, codes to an empty list, and give your final top3 with a reason for stopping."""


_ToolName = Literal[*TOOL_NAMES]  # type: ignore[valid-type]
_CodingKind = Literal["occurrence", "finding_category", "item"]


class CodingAction(BaseModel):
    """One coding-check step: either a tool call, or the settled reply (``done=True``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    done: bool
    tool: _ToolName | None
    kind: _CodingKind | None
    codes: tuple[str, ...]
    reason: str
    expected_effect: str
    top3: tuple[OccurrenceGuess, ...] = Field(min_length=1, max_length=3)


CODING_ACTION_SCHEMA: dict[str, object] = strict_schema(CodingAction)


def parse_coding_action(text: str, tables: CodeTables) -> CodingAction:
    """Parse a coding-check reply and validate its codes against the code tables.

    Follows :func:`ntsb_probable_cause.scoring.hypothesis.parse_hypothesis`: digit patterns
    are enforced by the pydantic fields, and each ``top3`` guess's phase and event are checked
    against the tables through ``tables.compose_occurrence`` -- the same call
    ``Hypothesis.occurrence_codes`` makes -- rather than a second lookup.

    Args:
        text: the raw JSON reply.
        tables: the code tables.

    Returns:
        The parsed :class:`CodingAction`.

    Raises:
        SchemaError: invalid JSON, a validation failure, a ``top3`` phase or event not in the
            tables, an unknown tool name, or ``done=False`` with no tool named.
    """
    try:
        action = CodingAction.model_validate(json.loads(text))
    except (ValueError, ValidationError) as error:
        raise SchemaError(f"reply is not a CodingAction: {error}") from error
    for guess in action.top3:
        tables.compose_occurrence(guess.phase, guess.event)
    if action.tool is not None and action.tool not in TOOL_NAMES:
        raise SchemaError(f"unknown tool {action.tool!r}")
    if not action.done and action.tool is None:
        raise SchemaError("done is false but no tool was named")
    return action


FINAL_INSTRUCTION = "Give your final hypothesis after the checks."

# Appended to the system text of every call that carries history (Task 4 fix round 2): the
# transport sends the payload before the history, so the model reads the current evidence
# before its own earlier replies, some of which were written with less of it.
HISTORY_NOTE = """Your earlier replies follow the evidence in this conversation. Some of them were
written before you had read every document now included in the evidence. Where they differ
from the evidence, the evidence given here is current."""
