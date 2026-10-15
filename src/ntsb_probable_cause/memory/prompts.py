"""What the learner and the coding test read (decisions 0200-0204).

The learner reads learning-part verdicts: a case's probable-cause sentence and its codes, with
their labels, under a position label (K1, K2, ...), never its case number. The apply step reads a
case's cause sentence alone (``apply_user``), so a lesson is judged to apply by its situation and
never by its codes.
"""

from collections.abc import Sequence
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.memory.checks import ALLOWED_WORDS
from ntsb_probable_cause.memory.lessons import Kind, Memory, render_memory
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables

MAX_NEW_PER_CALL: Final = 5
_ALLOWED: Final = ", ".join(sorted(ALLOWED_WORDS))

SYSTEM_PROPOSE: Final = f"""You study how the NTSB codes closed US general-aviation accidents, to \
write short coding lessons another model will use. You are given the current lessons and a batch \
of closed cases, each with the NTSB's probable-cause sentence, its occurrence codes in the NTSB's \
order (the first is the defining event), and the findings it flagged as causal.

Write lessons about how the NTSB codes, not about any one accident. Each lesson is one of three \
kinds:
- convention: in this situation the NTSB codes the same way nearly every time; it predicts the \
first occurrence code, or finding categories, or both.
- split: the situation is clear but the NTSB's first code divides between two or more codes, \
usually the same event in different phases; it predicts every code in the split, and says what in \
the evidence decides between them.
- evidence: the finding category follows from the situation but the specific item depends on the \
evidence; it predicts the category and says what to read for the item.

Rules for every statement and scope:
- One sentence. Start in lower case. Use capital letters only for these acronyms: {_ALLOWED}.
- No digits at all. Never state a count, share or percentage: those are counted for you later.
- No names of people, places, operators or aircraft, no dates, no registrations, no case details.
- Do not copy wording from a probable-cause sentence; say what the NTSB does in your own words.
- Codes go only in first_occurrence and finding_categories, from the codes shown in the cases.

Return at most {MAX_NEW_PER_CALL} new lessons. Edit an existing lesson (by its id) when the cases \
show it should be broader, narrower or corrected. Retire a lesson (by its id) only when the \
cases show it is wrong. Return empty lists when nothing should change."""

SYSTEM_APPLY: Final = """You decide which coding lessons cover an accident, from the NTSB's \
probable-cause sentence alone. A lesson covers the accident when its situation and scope describe \
what the sentence says happened. Judge by the situation only; do not guess how the accident was \
coded. Answer with the ids of every lesson that covers it, or an empty list.

The lessons:
"""

SYSTEM_REVISE: Final = f"""You maintain coding lessons about how the NTSB codes closed US \
general-aviation accidents. The lesson below was judged to cover the cases shown, but the NTSB's \
codes disagree with it in more of them than they agree. Either edit it so its situation, scope and \
prediction fit what the NTSB does, or retire it if no correct lesson can be made from it. The same \
rules hold as when it was written: one sentence, lower case except the acronyms {_ALLOWED}, no \
digits, no names, places, operators, aircraft, dates or registrations, no copied wording, and \
codes only in first_occurrence and finding_categories."""

CODING_PREFACE: Final = """In this task you are not given the evidence. You are given the NTSB's \
own probable-cause statement for one accident, as the field `ntsb_probable_cause`. Code it as the \
NTSB would. Write the evidence narrative as a one-sentence restatement of that statement, and name \
`ntsb_probable_cause` as the evidence used.

"""

MEMORY_HEADING: Final = "\n\n## Coding memory (lessons learned from earlier NTSB cases)\n"


class LessonDraft(BaseModel):
    """A lesson as the learner writes it; the script assigns its id and counts its support."""

    model_config = ConfigDict(extra="forbid")
    kind: Kind
    statement: str
    scope: str
    first_occurrence: list[str]
    finding_categories: list[str]


class LessonEdit(LessonDraft):
    """A change to an existing lesson."""

    lesson_id: str


class ProposeReply(BaseModel):
    """The propose step's reply."""

    model_config = ConfigDict(extra="forbid")
    new: list[LessonDraft]
    edits: list[LessonEdit]
    retire: list[str]


class ApplyReply(BaseModel):
    """The apply step's reply: the ids of the lessons that cover the case."""

    model_config = ConfigDict(extra="forbid")
    applies: list[str]


class ReviseReply(LessonDraft):
    """The revise step's reply: an edited lesson, or a retirement."""

    action: Literal["edit", "retire"]


def _occurrence(code: str, tables: CodeTables) -> str:
    return f"{code} {tables.phases.get(code[:3], '?')} / {tables.events.get(code[3:], '?')}"


def _finding(code: str, tables: CodeTables) -> str:
    return f"{code} {tables.items.get(code[:8], '?')} / {tables.modifiers.get(code[8:], '?')}"


def render_case(case: LearningCase, label: str, tables: CodeTables) -> str:
    """One case for the learner, under a position label, never its case number."""
    occurrence = "; ".join(_occurrence(c, tables) for c in case.occurrence)
    findings = "; ".join(_finding(c, tables) for c in case.findings) or "(none flagged)"
    return (
        f"{label}. cause: {case.cause}\n   occurrence codes in order: {occurrence}\n"
        f"   flagged findings: {findings}"
    )


def propose_user(memory_text: str, cases: Sequence[LearningCase], tables: CodeTables) -> str:
    """The propose step's user text: the current lessons, then the batch of cases."""
    lessons = memory_text or "(no lessons yet)"
    batch = "\n".join(render_case(c, f"K{i}", tables) for i, c in enumerate(cases, start=1))
    return f"Current lessons:\n{lessons}\n\nCases:\n{batch}"


def apply_user(cause: str) -> str:
    """The apply step's user text: the cause sentence and nothing else."""
    return f"Probable cause: {cause}\n\nWhich lessons cover this accident?"


def revise_user(
    lesson_text: str,
    disagreeing: Sequence[LearningCase],
    agreeing: Sequence[LearningCase],
    tables: CodeTables,
) -> str:
    """The revise step's user text: the lesson, cases that disagree, and cases that agree."""
    bad = "\n".join(render_case(c, f"D{i}", tables) for i, c in enumerate(disagreeing, start=1))
    good = "\n".join(render_case(c, f"A{i}", tables) for i, c in enumerate(agreeing, start=1))
    return (
        f"The lesson:\n{lesson_text}\n\nCases where the NTSB's codes disagree with it:\n{bad}"
        f"\n\nCases where they agree:\n{good or '(none)'}"
    )


def coding_system(tables: CodeTables, guidance: Sequence[str], memory: Memory | None) -> str:
    """The coding test's system text: the preface, arm B's answer text, tables, guidance, memory."""
    base = (
        f"{CODING_PREFACE}{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables)}"
        f"{prompt.guidance_block(guidance)}"
    )
    if memory is None or not memory.lessons:
        return base
    return f"{base}{MEMORY_HEADING}{render_memory(memory, tables)}"
