"""System prompts and message rendering. Versioned: the run record carries PROMPT_VERSION.

Spec §3.5.
"""

from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis

PROMPT_VERSION = "s1-v2"

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
in the narrative. Reply only with JSON matching the schema."""

SYSTEM_REFINE = """You chose finding categories for this case. For each, choose the single most
specific item from the list of that category's items given in the message. Return only its
eight-digit item code, never its label text. Reply only with JSON matching the schema: one
entry per finding index."""


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
    """Render the stage-1 findings and, for each, its category's items with definitions."""
    parts = ["## Your findings and the items available under each\n"]
    for index, guess in enumerate(hypothesis.findings):
        label = tables.categories[guess.category6]
        parts.append(f"### Finding {index}: {guess.category6}  {label}\n")
        parts.extend(
            f"{code}  {text}" for code, text in sorted(tables.items_under(guess.category6).items())
        )
        parts.append("")
    return "\n".join(parts)
