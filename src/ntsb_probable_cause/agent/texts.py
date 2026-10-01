"""The agent's fixed texts: the system text, the protocol, the menus and the result strings.

Everything here is a plain ``str``. The loop wraps the ones it sends as tool results with
``ToolText.of``; nothing here is evidence, and nothing here receives a record, a document title
or document text. The menu holds numbers keyed by listing index (pages, pages with a text layer,
estimated tokens), never a title: titles reach the model only in the listing payload, which went
through the split and the guard (``agent/documents.py``; decision 0016). The one text built from
the agent's own words is a later trigger's summary (:func:`prior_summary`, Task 11): listing
indices, its read and skip decisions with its reasons and expected effects, and trigger numbers,
which the plan's constraints allow in a ``ToolText``.

The prompt version fingerprints the source of every module that holds or composes the text the
agent sends (:data:`TEXT_SOURCES`, :func:`agent_text_sha256`; decision 0133).

This module imports no ``records``, ``docket`` or ``data`` module, directly or indirectly (Task
10's import contract counts chains): a document's facts come in as ``agent.facts.DocumentFacts``,
a later trigger's start as ``agent.trail.Prior``, the tool definitions from ``agent.schemas``, and
the prompt pieces from ``scoring.prompt``, which reads the code tables and the coding guidance
files, never a case record. The fingerprint reads the other modules' source as package files; it
imports none of them.
"""

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from importlib import resources
from typing import Final

from ntsb_probable_cause.agent import schemas
from ntsb_probable_cause.agent.facts import DocumentFacts
from ntsb_probable_cause.agent.trail import Prior
from ntsb_probable_cause.scoring import hypothesis, prompt
from ntsb_probable_cause.scoring.codes import CodeTables

# What elicits the answer, for the loop: the base version, then ``+g`` and a short fingerprint
# of the coding guidance, then ``+p`` and a short fingerprint of the agent's model-facing text
# (Andy, 2026-10-01), then ``+r`` and the tuning round's number when there is one (Task 13).
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
# H0's result when the docket lists documents but none can be read (Andy, 2026-10-01; decision
# 0074, equal evidence): it follows the listing and the menu's not-readable lines, as arm B's
# payload holds the listing whatever it could attach. NO_DOCUMENTS stays for a case with no
# docket, or a docket that lists nothing.
NONE_READABLE: Final = "None of the documents listed can be read."
# A later trigger's move to coding when every document on offer was read on an earlier one.
ALL_READ: Final = "Every docket document on offer has been read; none is left to choose."
ONE_CALL: Final = "Only one tool call is run per turn; this call was not run."

# A later trigger's summary of the earlier ones (Task 11): its fixed lines, then the read choices.
PRIOR_HEADING: Final = (
    "You have worked on this case before. Each time new evidence arrived was a trigger; "
    "this is a later one."
)
PRIOR_HYPOTHESIS: Final = "The record_hypothesis call above is the last hypothesis you recorded."
_CHOICE_NAMES: Final = {"choice1": "first read choice", "choice2": "second look"}

# The words of a refusal (``not_accepted``), which ``agent/steps.py`` and ``agent/loop.py``
# build: every fixed text of the agent in one module. ``WRONG_TOOL`` takes the step's tools and
# the tool called; a name that is no tool of ours is ``UNKNOWN_TOOL``; arguments that are not
# JSON are ``NOT_JSON``; a problem with the arguments as a whole is placed at
# ``WHOLE_ARGUMENTS``; a coding tool that raised is ``TOOL_FAULT``, with the error's type name.
WRONG_TOOL: Final = "this step takes {wanted}, not {called}"
UNKNOWN_TOOL: Final = "an unknown tool"
NOT_JSON: Final = "not valid JSON"
WHOLE_ARGUMENTS: Final = "arguments"
TOOL_FAULT: Final = "the tool could not run ({error})"

# The modules whose source holds or composes the text the agent (arm C) and arm B's tool
# post-pass send a model, as (package, file), in the order the fingerprint reads them
# (decision 0133). See :func:`agent_text_sha256` for what is in them and what is not.
TEXT_SOURCES: Final[tuple[tuple[str, str], ...]] = (
    ("ntsb_probable_cause.scoring", "prompt.py"),
    ("ntsb_probable_cause.scoring", "hypothesis.py"),
    ("ntsb_probable_cause.scoring", "codes.py"),
    ("ntsb_probable_cause.agent", "texts.py"),
    ("ntsb_probable_cause.agent", "steps.py"),
    ("ntsb_probable_cause.agent", "tools.py"),
    ("ntsb_probable_cause.agent", "schemas.py"),
    ("ntsb_probable_cause.agent", "later.py"),
    ("ntsb_probable_cause.agent", "loop.py"),
    ("ntsb_probable_cause.agent", "armb.py"),
)

# The text fingerprint's place in a prompt version: ``+p`` and twelve hex characters.
_TEXT_PART: Final = re.compile(rf"\+p[0-9a-f]{{{prompt.FINGERPRINT_CHARS}}}")


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

    The text fingerprint (``+p``, :func:`text_mark`) is cut from :func:`agent_text_sha256`
    (decision 0133): a kept tuning round that changes the protocol, a step text, a tool's result
    wording or a tool description changes it, so later plain runs never share a version with
    runs made on the old text. Nothing is bumped by hand.

    Args:
        guidance: the coding guidance names; a short fingerprint of them is appended.
        round_number: a tuning round's number, appended as ``+r<N>``, or None.

    Returns:
        ``AGENT_PROMPT_VERSION``, then ``+g`` and the first twelve characters of the guidance
        fingerprint when there is guidance, then ``+p`` and the first twelve characters of the
        text fingerprint, then ``+r<N>`` when there is a round. E.g.
        ``s3-v1+g0123456789ab+pba9876543210+r2``.
    """
    version = AGENT_PROMPT_VERSION
    fingerprint = prompt.guidance_sha256(guidance)
    if fingerprint is not None:
        version += f"+g{fingerprint[: prompt.FINGERPRINT_CHARS]}"
    version += text_mark()
    if round_number is not None:
        version += f"+r{round_number}"
    return version


def text_mark() -> str:
    """``+p`` and the first twelve characters of :func:`agent_text_sha256`.

    Arm C's prompt version carries it after the guidance, and arm B's tool post-pass label after
    ``+tools-<stats>`` (``agent/armb.py``): the post-pass sends the same tools and texts.
    """
    return f"+p{agent_text_sha256()[: prompt.FINGERPRINT_CHARS]}"


def is_plain(version: str, guidance: Sequence[str]) -> bool:
    """Whether ``version`` is a run's with this guidance and no tuning round, on any agent text.

    The text fingerprint is not compared: a run made before a kept round changed the text is
    still a plain run of its day. ``resolve_latest`` (``apps/eval``) reads arm C's plain runs
    so.

    Args:
        version: a run's recorded prompt version.
        guidance: the guidance a plain run reads.

    Returns:
        True when ``version`` is ``prompt_version(guidance)`` with any text fingerprint.
    """
    stem = _TEXT_PART.sub("", prompt_version(guidance))
    return re.fullmatch(f"{re.escape(stem)}{_TEXT_PART.pattern}", version) is not None


def source_text(package: str, name: str) -> str:
    """One module's source, read as a file of its package (never from a live object).

    Args:
        package: the package, e.g. ``ntsb_probable_cause.agent``.
        name: the file, e.g. ``texts.py``.

    Returns:
        The file's text, decoded as UTF-8.
    """
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def agent_text_sha256(read: Callable[[str, str], str] | None = None) -> str:
    """The fingerprint of the text the agent sends a model: a SHA-256, in hexadecimal.

    Decision 0133 (Andy, 2026-10-01): the version follows the text automatically, so no run can
    be mislabelled. It hashes, as one JSON list, in this order:

    1. the source of every module in :data:`TEXT_SOURCES`, read as package files:
       ``scoring/prompt.py`` (the answer and refinement prompts, the tables' headings, the
       guidance heading, the refinement message, the retry line ``prompt.REJECTED``),
       ``scoring/hypothesis.py`` (the answer and refinement schemas, and the parse errors a
       refusal repeats), ``scoring/codes.py`` (how a table line is written, and its parse
       errors), and ``agent/`` ``texts.py``, ``steps.py``, ``tools.py`` (the coding tools'
       result wording), ``schemas.py`` (the tool definitions), ``later.py``, ``loop.py`` and
       ``armb.py`` (how the turns and the system texts are put together);
    2. ``json.dumps(schemas.TOOL_DEFINITIONS, sort_keys=True)`` and
       ``json.dumps(hypothesis.REFINEMENT_SCHEMA, sort_keys=True)``: the schemas as sent, which
       can change with the pydantic version even when no file above does.

    **Any edit to those files changes the version, a comment or a docstring included.** A false
    change only separates runs that were in fact alike; it never merges two different prompts.

    Not covered: the code tables and the statistics (data files, which the commit SHA and
    ``spec.json``'s ``stats`` name), the coding guidance (its own fingerprint, ``+g``), and the
    evidence with its rendering and the transport (``records``, ``docket``, ``model``), which
    are the same for every arm and named by the commit SHA and the evidence version.

    Args:
        read: how a module's source is read; :func:`source_text` (looked up when called), or a
            stand-in in tests.

    Returns:
        The SHA-256 of the JSON list, in hexadecimal; the same in every interpreter.
    """
    reader = source_text if read is None else read
    parts = [[f"{package}/{name}", reader(package, name)] for package, name in TEXT_SOURCES]
    parts.append(["TOOL_DEFINITIONS", json.dumps(schemas.TOOL_DEFINITIONS, sort_keys=True)])
    parts.append(["REFINEMENT_SCHEMA", json.dumps(hypothesis.REFINEMENT_SCHEMA, sort_keys=True)])
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def menu(
    offered: Sequence[DocumentFacts],
    not_readable: Sequence[DocumentFacts],
    already_read: Sequence[int] = (),
) -> str:
    """The menu of documents: numbers keyed by listing index, never a title.

    One line per offered document, in the order given, then an ``Already read`` line when there
    is one, then one line per document that cannot be read. That line names no cause: a scan
    has no text layer, but a fetch that failed or a file that is not a PDF is not read either,
    and the cause is not measured for every status. A one-page document reads ``1 page``, as
    ``docket/attach.py``'s document header does. E.g.::

        [3] 6 pages, 6 with a text layer, about 2100 tokens
        Already read: [1]
        Not readable: [5] 14 pages

    Args:
        offered: the documents the agent may read, in offer order.
        not_readable: the documents that cannot be read.
        already_read: listing indices the agent read at an earlier step.

    Returns:
        The menu text; empty when there is nothing to list.
    """
    lines = [
        f"[{f.index}] {_pages(f.pages)}, {f.readable_pages} with a text layer, "
        f"about {f.estimated_tokens} tokens"
        for f in offered
    ]
    if already_read:
        lines.append(f"Already read: {_indices(already_read)}")
    lines.extend(f"Not readable: [{f.index}] {_pages(f.pages)}" for f in not_readable)
    return "\n".join(lines)


def _pages(count: int) -> str:
    """``1 page`` or ``N pages``, as ``docket/attach.py``'s document header words a count."""
    return f"{count} {'page' if count == 1 else 'pages'}"


def read_summary(read: Sequence[int], skipped: Sequence[int]) -> str:
    """Say what the agent chose, by listing index only.

    E.g. ``You read: [1], [3]. You skipped: [2].``; an empty side reads ``none``.
    """
    return f"You read: {_indices(read)}. You skipped: {_indices(skipped)}."


def not_accepted(error: str) -> str:
    """The text that answers a call the loop did not accept, naming why."""
    return f"That call was not accepted: {error}"


def prior_summary(prior: Prior) -> str:
    """A later trigger's summary of the earlier ones (spec §4.3; decision 0122 item 5).

    Listing indices, the agent's own read and skip decisions with its reasons and expected
    effects, and the trigger each choice was made on; never a title or document text. The last
    hypothesis is not repeated here: it is the ``record_hypothesis`` call this text answers. E.g.::

        You have worked on this case before. Each time new evidence arrived was a trigger; ...
        The record_hypothesis call above is the last hypothesis you recorded.
        Documents you read, attached above in full: [1].
        Trigger 1, first read choice. Your reason: the examination decides
        [1] read. You expected: the engine's condition
        [2] skipped. You expected: the weather at the field

    Args:
        prior: the earlier triggers' work.

    Returns:
        The summary, one line per fact; ``Documents you read: none.`` and ``Read choices:
        none.`` when there is nothing to list.
    """
    lines = [PRIOR_HEADING, PRIOR_HYPOTHESIS]
    if prior.read:
        lines.append(f"Documents you read, attached above in full: {_indices(prior.read)}.")
    else:
        lines.append("Documents you read: none.")
    if not prior.reads:
        lines.append("Read choices: none.")
    for record in prior.reads:
        lines.append(
            f"Trigger {record.trigger}, {_CHOICE_NAMES[record.step]}. Your reason: {record.reason}"
        )
        lines.extend(
            f"[{d.document}] {'read' if d.read else 'skipped'}. You expected: {d.expected_effect}"
            for d in record.decisions
        )
    return "\n".join(lines)


def _indices(indices: Sequence[int]) -> str:
    """Listing indices as ``[1], [3]``, or ``none``."""
    return ", ".join(f"[{i}]" for i in indices) or "none"
