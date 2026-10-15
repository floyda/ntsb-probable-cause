"""The three checks every coding-memory snapshot passes before use (decision 0201).

The identifier check needs no case data and runs in continuous integration; the withheld-text
and copying checks compare against development case text (``development_texts``) and run
locally (``scripts/memory_check.py``), whose result is the stamp. The learner's ``finish``
drops a lesson that would fail them before it saves a snapshot.

A finding names the lesson and the kind of finding only, never the text that failed: findings
are printed and put in errors, and that text may be a name or a copied withheld sentence.
"""

import json
import re
from collections.abc import Iterable
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Final

import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import ConfigurationError
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


DEV_SPLIT: Final = "dev"
DIGIT: Final = "a digit"
CAPITALISED: Final = "a capitalised word not on the allowed list"
WITHHELD: Final = "a sentence found in withheld text"
COPYING_CHECK: Final = "copying"
WITHHELD_CHECK: Final = "withheld text"


def _as_text(hits: Iterable[tuple[str, str]]) -> list[str]:
    """Each lesson-and-kind pair once, in order, as ``"<lesson id>: <kind>"``."""
    return [f"{lid}: {kind}" for lid, kind in dict.fromkeys(hits)]


def identifier_findings(memory: Memory, allowed: frozenset[str] = ALLOWED_WORDS) -> list[str]:
    """Lessons whose statement or scope holds a digit, or a capitalised word not on the list."""
    hits: list[tuple[str, str]] = []
    for lesson_id, text in _texts(memory):
        if any(ch.isdigit() for ch in text):
            hits.append((lesson_id, DIGIT))
        hits.extend(
            (lesson_id, CAPITALISED)
            for word in _WORD.findall(text)
            if word != word.lower() and _POSSESSIVE.sub("", word) not in allowed
        )
    return _as_text(hits)


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


def _withheld_ids(memory: Memory, withheld: Iterable[str]) -> list[str]:
    needles = [(lid, s) for lid, text in _texts(memory) for s in sentences(text)]
    found: list[str] = []
    for haystack in withheld:
        hay = normalise(haystack)
        found.extend(lid for lid, s in needles if s in hay)
    return found


def withheld_findings(memory: Memory, withheld: Iterable[str]) -> list[str]:
    """Lessons with a sentence found inside any withheld text (plain substring, as S2.7's check)."""
    return _as_text((lid, WITHHELD) for lid in _withheld_ids(memory, withheld))


def windows(text: str, n: int = COPY_WORDS) -> set[tuple[str, ...]]:
    """Every run of ``n`` consecutive lower-case words in ``text``."""
    words = _LOWER_WORD.findall(text.translate(_FOLD).lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def _copying_ids(memory: Memory, causes: Iterable[str], n: int) -> list[str]:
    seen: set[tuple[str, ...]] = set()
    for cause in causes:
        seen |= windows(cause, n)
    return [lid for lid, text in _texts(memory) if windows(text, n) & seen]


def copying_findings(memory: Memory, causes: Iterable[str], n: int = COPY_WORDS) -> list[str]:
    """Lessons sharing a run of ``n`` or more words with any probable-cause sentence."""
    kind = f"{n} or more words shared with a probable-cause sentence"
    return _as_text((lid, kind) for lid in _copying_ids(memory, causes, n))


def development_failures(
    memory: Memory, withheld: Iterable[str], causes: Iterable[str]
) -> dict[str, tuple[str, ...]]:
    """Each lesson, kept or pushed out, that fails the copying or withheld-text check, and which.

    The learner's ``finish`` drops these before it counts support and applies the cap, so the
    snapshot it saves passes ``scripts/memory_check.py`` (final review I1).
    """
    failed: dict[str, list[str]] = {}
    for lid in _copying_ids(memory, causes, COPY_WORDS):
        failed.setdefault(lid, []).append(COPYING_CHECK)
    for lid in _withheld_ids(memory, withheld):
        failed.setdefault(lid, []).append(WITHHELD_CHECK)
    return {lid: tuple(dict.fromkeys(names)) for lid, names in failed.items()}


def development_texts(cases_file: Path) -> tuple[list[str], list[str]]:
    """The withheld texts and the probable-cause sentences of every development case.

    Reads only development rows, through ``fields`` (rule 1: no second assembler); rows of any
    other split never enter the comparison.

    Raises:
        ConfigurationError: the processed case file is missing.
    """
    withheld: list[str] = []
    causes: list[str] = []
    columns = ["split", "raw_json"]
    if not cases_file.exists():
        raise ConfigurationError(f"{cases_file} is missing: run make build")
    with pq.ParquetFile(cases_file) as parquet:
        for batch in parquet.iter_batches(batch_size=512, columns=columns):
            rows = zip(*(batch.column(c).to_pylist() for c in columns), strict=True)
            for split, raw_json in rows:
                if split != DEV_SPLIT:
                    continue
                raw = json.loads(raw_json)
                cause = fields.probable_cause(raw)
                texts = (fields.factual_narrative(raw), fields.analysis_narrative(raw), cause)
                withheld.extend(t for t in texts if t)
                if cause:
                    causes.append(cause)
    return withheld, causes


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
