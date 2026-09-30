"""The agent's fixed texts: the system text, the protocol, the menus and the result strings.

Everything here is a plain ``str``. The loop wraps the ones it sends as tool results with
``ToolText.of``; nothing here is evidence, and nothing here receives a record, a document title
or document text. The menu holds numbers keyed by listing index (pages, pages with a text layer,
estimated tokens), never a title: titles reach the model only in the listing payload, which went
through the split and the guard (``agent/documents.py``; decision 0016).

This module imports no ``records``, ``docket`` or ``data`` module, directly or indirectly (Task
10's import contract counts chains): a document's facts come in as ``agent.facts.DocumentFacts``,
and the prompt pieces from ``scoring.prompt``, which reads only the code tables.
"""

from collections.abc import Sequence
from typing import Final

from ntsb_probable_cause.agent.facts import DocumentFacts
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables

# What elicits the answer, for the loop: the base version, then ``+g`` and a short fingerprint
# of the coding guidance, then ``+r`` and the tuning round's number when there is one (Task 13).
AGENT_PROMPT_VERSION: Final = "s3-v1"

PROTOCOL: Final = """## How you work through a case

You work through one case in steps, using tools. First record your hypothesis from the evidence
given. Then, when docket documents are offered, decide for each whether to read it and what you
expect it to show; reading costs time and money, so read what your hypothesis needs. Record your
hypothesis again after reading. Then check your coding with the coding tools: give for each call
why you make it and what you expect. The counts the tools return describe past accidents; they
are not evidence about this one. Keep a less usual code when this case's evidence supports it.
Check the occurrence (which event defines the accident, and its phase) before the findings.
Give codes to the coding tools as they appear in the code tables above: describe_codes takes up
to six codes in one call, and occurrence_usage takes up to three. Submit your answer when your
coding is settled. Make one tool call at a time."""

CHOOSE: Final = "Choose read or skip for every document listed above."
CHOOSE_AGAIN: Final = "You may read more. Choose read or skip for every document listed."
RECORD_NOW: Final = "Record your hypothesis now."
CODE_NOW: Final = "Check your coding with the coding tools, then submit your answer."
# The coding ablation's CODE_NOW (spec §7.2): the run sends no coding tools, so it names none.
ANSWER_NOW: Final = "Submit your answer now."
NO_DOCUMENTS: Final = "No docket documents are available for this case."
ONE_CALL: Final = "Only one tool call is run per turn; this call was not run."


def system_text(tables: CodeTables, guidance: Sequence[str]) -> str:
    """The system text: arm B's answer prompt, the code tables, the guidance, then the protocol.

    The same bytes for every case of a run, so the provider's prompt cache can hold it (spec
    §5.3). ``tables_block`` is called without its ``case_number`` keyword, which exists for the
    development-split probe and would make the text differ by case.

    Args:
        tables: the code tables the answer chooses from.
        guidance: the coding guidance names, in stacking order (may be empty).

    Returns:
        The system text.
    """
    answer = (
        f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables)}{prompt.guidance_block(guidance)}"
    )
    return f"{answer.rstrip()}\n\n{PROTOCOL}"


def prompt_version(guidance: Sequence[str], round_number: int | None = None) -> str:
    """What elicits the agent's answer, as recorded on a run.

    Args:
        guidance: the coding guidance names; a short fingerprint of them is appended.
        round_number: a tuning round's number, appended as ``+r<N>``, or None.

    Returns:
        ``AGENT_PROMPT_VERSION``, then ``+g`` and the first twelve characters of the guidance
        fingerprint when there is guidance, then ``+r<N>`` when there is a round.
    """
    version = AGENT_PROMPT_VERSION
    fingerprint = prompt.guidance_sha256(guidance)
    if fingerprint is not None:
        version += f"+g{fingerprint[: prompt.FINGERPRINT_CHARS]}"
    if round_number is not None:
        version += f"+r{round_number}"
    return version


def menu(
    offered: Sequence[DocumentFacts],
    not_readable: Sequence[DocumentFacts],
    already_read: Sequence[int] = (),
) -> str:
    """The menu of documents: numbers keyed by listing index, never a title.

    One line per offered document, in the order given, then an ``Already read`` line when there
    is one, then one line per document that has no text layer to read. E.g.::

        [3] 6 pages, 6 with a text layer, about 2100 tokens
        Already read: [1]
        Not readable (no text layer): [5] 14 pages

    Args:
        offered: the documents the agent may read, in offer order.
        not_readable: the documents that cannot be read.
        already_read: listing indices the agent read at an earlier step.

    Returns:
        The menu text; empty when there is nothing to list.
    """
    lines = [
        f"[{f.index}] {f.pages} pages, {f.readable_pages} with a text layer, "
        f"about {f.estimated_tokens} tokens"
        for f in offered
    ]
    if already_read:
        lines.append(f"Already read: {_indices(already_read)}")
    lines.extend(f"Not readable (no text layer): [{f.index}] {f.pages} pages" for f in not_readable)
    return "\n".join(lines)


def read_summary(read: Sequence[int], skipped: Sequence[int]) -> str:
    """Say what the agent chose, by listing index only.

    E.g. ``You read: [1], [3]. You skipped: [2].``; an empty side reads ``none``.
    """
    return f"You read: {_indices(read)}. You skipped: {_indices(skipped)}."


def not_accepted(error: str) -> str:
    """The text that answers a call the loop did not accept, naming why."""
    return f"That call was not accepted: {error}"


def _indices(indices: Sequence[int]) -> str:
    """Listing indices as ``[1], [3]``, or ``none``."""
    return ", ".join(f"[{i}]" for i in indices) or "none"
