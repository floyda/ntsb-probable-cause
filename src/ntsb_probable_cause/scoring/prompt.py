"""System prompts and message rendering. Versioned: the run record carries PROMPT_VERSION.

PROMPT_VERSION names everything that elicits the answer, not only the text here: v5 differs
from v4 in the stage-1 JSON schema (``item8`` removed -- see ``hypothesis._stage1_schema``),
with the prompt text unchanged. v6 differs from v5 in the code tables the prompt shows: two
phases and four events the NTSB uses, missing from its data dictionary, are added (decision
0105), with the prompt text unchanged.

From S2.7 (decision 0098) a run may add coding guidance files; ``prompt_version`` then names
them.

Spec §3.5.
"""

import hashlib
import re
from collections.abc import Sequence
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

PROMPT_VERSION = "s1-v6"

SYSTEM_ANSWER = """You are an aviation accident analyst working from the evidence investigators
recorded. First write an evidence narrative: what the evidence shows, in plain clinical prose,
without naming any person. Then decide the probable cause.

Choose codes only from the tables in the message. For the occurrence, give up to three guesses,
each a phase prefix and an event suffix with a probability; the probabilities may sum to less
than 1. For the findings in the probable cause, give one or more six-digit categories, each with
a modifier (who or what) and a probability. Write the probable cause in one or two sentences in
the NTSB's style, and a lay explanation a reader with no aviation knowledge can follow. State
your confidence that your first occurrence guess is right.

Name the most probable cause the evidence supports, even when the evidence is thin. Thin
evidence is expressed through low probabilities and a low confidence value, not through
declining to answer: a partial or ambiguous record still favors some causes over others, and
that is what the analyst is asked to report. Set abstain to true only when the evidence supports
no cause at all -- for example, no occurrence or finding information was recorded -- and say why
in the narrative.

The official record names a specific occurrence and specific findings. The codes that mean
"unknown", "undetermined" or "not determined" -- event suffix 000, finding category 050000 and
item 05000000, modifier 00 -- are a last resort, not a safe default: they are marked wrong
whenever the official record names something specific, which is most of the time. Choose the
most specific event suffix that names what actually happened and the most specific finding
category that names a real factor, and put your doubt into the probabilities and the confidence
value instead of retreating to an undetermined code. Use an undetermined code only when the
official record itself would have nothing more specific to say. Reply only with JSON matching
the schema."""

SYSTEM_REFINE = """You already chose a finding category and a modifier for each finding in this
case; the modifier is settled and is not part of what you choose now. For each finding, the
message below lists the eight-digit item codes that belong to that finding's category, one per
line as "item code, two spaces, label". Choose one of those listed item codes exactly as
written. The item code is not the six-digit category code, and it is never the category code
with the modifier appended -- it is one specific line from the list, copied exactly. Return
only that eight-digit item code, never its label text. Reply only with JSON matching the
schema: one entry per finding index."""

# The start of the line a retry adds to the system text after a rejected reply; the reason
# follows it. One constant for every caller (the runner, the ordering check, the agent loop and
# arm B's tool post-pass), so the agent's text fingerprint covers it (decision 0133). The bytes
# are the ones every caller wrote out before.
REJECTED = "Your previous reply was rejected: "

GUIDANCE_DIR: Traversable = resources.files("ntsb_probable_cause.scoring").joinpath("guidance")
_GUIDANCE_NAME = re.compile(r"^r(?P<round>[1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*$")
GUIDANCE_HEADING = "## Coding guidance (how the NTSB codes)"


def guidance_round(name: str) -> int:
    """The round a guidance file belongs to, from its name ``r<N>-<slug>``."""
    match = _GUIDANCE_NAME.match(name)
    if match is None:
        raise ConfigurationError(
            f"guidance {name!r}: names are r<N>-<slug>, lower case (decision 0098)"
        )
    return int(match["round"])


def guidance_text(names: Sequence[str]) -> str:
    """The guidance files' text, in stacking order."""
    parts: list[str] = []
    for name in names:
        guidance_round(name)
        path = GUIDANCE_DIR.joinpath(f"{name}.md")
        if not path.is_file():
            raise ConfigurationError(f"no guidance file {name}.md in scoring/guidance")
        parts.append(path.read_text().strip())
    return "\n\n".join(parts)


def guidance_sha256(names: Sequence[str]) -> str | None:
    """The SHA-256 of the names and their text, or None with no guidance."""
    if not names:
        return None
    return hashlib.sha256(f"{list(names)}\n{guidance_text(names)}".encode()).hexdigest()


# Plan W5 (Andy): the version carries a short fingerprint of the guidance, not the names; the
# names are stored beside it on every run record. Twelve characters, as the transcription
# marker's stamp (docket/transcribe.py:ReadingLookup.done_file).
FINGERPRINT_CHARS = 12


def prompt_version(names: Sequence[str]) -> str:
    """What elicits the answer: the base version, plus a short fingerprint of the guidance."""
    fingerprint = guidance_sha256(names)
    if fingerprint is None:
        return PROMPT_VERSION
    return f"{PROMPT_VERSION}+g{fingerprint[:FINGERPRINT_CHARS]}"


def registration_path(name: str) -> Path:
    """The round registration a guidance file needs committed before any run (0098 item 3)."""
    return Path("docs/rounds") / f"s27-round-{guidance_round(name)}.md"


def guidance_block(names: Sequence[str]) -> str:
    """The text appended to the system prompt after the tables; empty with no guidance."""
    return "" if not names else f"\n\n{GUIDANCE_HEADING}\n{guidance_text(names)}"


def tables_block(tables: CodeTables, *, case_number: str | None = None) -> str:
    """Render the four choice tables, appended to the system text.

    The Payload stays the evidence alone, so S0's provenance check still reads it unchanged.
    The case-number line exists only for the development-split probe (spec §6.2); the runner
    refuses it elsewhere.
    """
    block = (
        "## Phase prefixes (first three digits of the occurrence code)\n"
        f"{tables.render('phases')}\n\n"
        "## Event suffixes (last three digits of the occurrence code)\n"
        f"{tables.render('events')}\n\n"
        "## Finding categories (first six digits of a finding code)\n"
        f"{tables.render('categories')}\n\n"
        "## Modifiers (last two digits of a finding code: who or what)\n"
        f"{tables.render('modifiers')}\n"
    )
    if case_number is not None:
        block += f"\n## Case number\n{case_number}\n"
    return block


def refine_message(hypothesis: Hypothesis, tables: CodeTables) -> str:
    """Render the stage-1 findings and, for each, its category's items with definitions.

    Each finding's heading names its category and modifier as already chosen, separately
    from the item list, and the list itself holds only the eight-digit item codes that are
    valid choices -- nothing in this rendering pairs a category digit string with a modifier
    digit string the way an ``item8 = category6 + modifier`` mistake would (Task 14 step 2,
    third prompt iteration: the model built ``02041044`` from category ``020410`` and
    modifier ``44`` instead of choosing a listed item).
    """
    parts = ["## For each finding, choose one item code from the list below\n"]
    for index, guess in enumerate(hypothesis.findings):
        label = tables.categories[guess.category6]
        parts.append(
            f"### Finding {index}: category {guess.category6} ({label}), "
            f"modifier {guess.modifier} already chosen\n"
        )
        parts.append("Item codes for this finding (choose one, exactly as listed):\n")
        parts.extend(
            f"{code}  {text}" for code, text in sorted(tables.items_under(guess.category6).items())
        )
        parts.append("")
    return "\n".join(parts)
