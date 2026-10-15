"""The three checks every coding-memory snapshot passes before use (decision 0201).

The identifier check needs no case data and runs in continuous integration; the withheld-text
and copying checks compare against development case text and run locally
(``scripts/memory_check.py``), whose result is the stamp.
"""

import re
from collections.abc import Iterable
from datetime import date
from importlib import resources
from typing import Final

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.memory.lessons import Memory

MIN_SENTENCE_CHARS: Final = 30  # as scripts/check_guidance.py (S2.7)
COPY_WORDS: Final = 8
_WORD: Final = re.compile(r"[A-Za-z][A-Za-z'-]*")
_LOWER_WORD: Final = re.compile(r"[a-z0-9']+")
_FOLD: Final = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)
_POSSESSIVE: Final = re.compile(r"['\u2019]s$")
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


def _allowed_words() -> frozenset[str]:
    text = resources.files("ntsb_probable_cause.memory").joinpath("allowed_words.txt").read_text()
    return frozenset(
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
    )


ALLOWED_WORDS: Final = _allowed_words()


def _texts(memory: Memory) -> list[tuple[str, str]]:
    """Every statement and scope of the kept and pushed-out lessons, with the lesson's id.

    ``Lesson.history`` is not read: the learner script writes it, as years ("edited in 2010"),
    never a model.
    """
    return [
        (lesson.lesson_id, text)
        for lesson in (*memory.lessons, *memory.pushed_out)
        for text in (lesson.statement, lesson.scope)
    ]


def identifier_findings(memory: Memory, allowed: frozenset[str] = ALLOWED_WORDS) -> list[str]:
    """Statements or scopes holding a digit, or a capitalised word not on the allowed list."""
    found: list[str] = []
    for lesson_id, text in _texts(memory):
        if any(ch.isdigit() for ch in text):
            found.append(f"{lesson_id}: a digit in {text!r}")
        found.extend(
            f"{lesson_id}: capitalised word {word!r} is not allowed"
            for word in _WORD.findall(text)
            if word != word.lower() and _POSSESSIVE.sub("", word) not in allowed
        )
    return found


def normalise(text: str) -> str:
    """Curly quotes and dashes folded to plain ones, lower case, whitespace collapsed, stripped."""
    return " ".join(text.translate(_FOLD).lower().split())


def sentences(text: str) -> list[str]:
    """Normalised sentences of at least ``MIN_SENTENCE_CHARS`` characters."""
    return [
        s
        for s in (normalise(part) for part in _SENTENCE_END.split(text))
        if len(s) >= MIN_SENTENCE_CHARS
    ]


def withheld_findings(memory: Memory, withheld: Iterable[str]) -> list[str]:
    """Lesson sentences found inside any withheld text (plain substring, as S2.7's check)."""
    needles = [(lid, s) for lid, text in _texts(memory) for s in sentences(text)]
    found: list[str] = []
    for haystack in withheld:
        hay = normalise(haystack)
        found.extend(f"{lid}: {s!r} is in withheld text" for lid, s in needles if s in hay)
    return found


def windows(text: str, n: int = COPY_WORDS) -> set[tuple[str, ...]]:
    """Every run of ``n`` consecutive lower-case words in ``text``."""
    words = _LOWER_WORD.findall(text.translate(_FOLD).lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def copying_findings(memory: Memory, causes: Iterable[str], n: int = COPY_WORDS) -> list[str]:
    """Lessons sharing a run of ``n`` or more words with any probable-cause sentence."""
    seen: set[tuple[str, ...]] = set()
    for cause in causes:
        seen |= windows(cause, n)
    return [
        f"{lid}: shares {n} words with a probable-cause sentence: {' '.join(w)!r}"
        for lid, text in _texts(memory)
        for w in sorted(windows(text, n) & seen)
    ]


class Stamp(BaseModel):
    """The local checks' record, committed beside the snapshot it names."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: str
    sha256: str
    withheld_texts_compared: int
    causes_compared: int
    checked_on: date
    commit: str
    dirty: bool
