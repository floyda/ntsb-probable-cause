"""The names step for text that leaves the live board (decisions 0180, 0182).

Two rules, and no guessing between them.

* **Titles** keep the title rule: a capitalised word in neither the title vocabulary nor the
  word list becomes ``NAME_MARKER`` (``board_title``).
* **Prose** (Ellery's causes, accounts, notes and coding-lookup reasons, and the NTSB's cause
  statement) has only the case's own owner and operator strings replaced (``board_text``), by
  ``docket.attach``'s whole-string rule. A capitalised word in prose is never replaced on a
  guess: most are ordinary words, makers and places (0182).

The limit is published: a name that appears only in a document's text, and in neither a title
nor the owner and operator fields, is not removed.

The word list is package data (``docket/vocab/words.txt``), so this runs in the cloud container,
which holds no ``tests/`` folder and no system dictionary.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from ntsb_probable_cause.docket.attach import owner_operator_values, replace_values
from ntsb_probable_cause.docket.title_vocab import CAPITALISED_WORD, is_ordinary_word

NAME_MARKER: Final = "[name]"


@dataclass(frozen=True)
class CaseNames:
    """What one case's names step replaces in prose: its owner and operator strings."""

    owner_operator: tuple[str, ...]


def case_names(raw: Mapping[str, object]) -> CaseNames:
    """The owner and operator strings of ``raw``, as ``docket.attach`` selects them."""
    return CaseNames(owner_operator=tuple(owner_operator_values(raw)))


def board_title(title: str, known: frozenset[str]) -> str:
    """``title`` with each capitalised word absent from ``known`` replaced by ``NAME_MARKER``."""

    def _replace(match: re.Match[str]) -> str:
        word = match.group(0)
        return word if is_ordinary_word(word, known) else NAME_MARKER

    return CAPITALISED_WORD.sub(_replace, title)


def board_text(text: str, names: CaseNames) -> str:
    """``text`` with the case's owner and operator strings replaced by ``NAME_MARKER``."""
    return replace_values(text, names.owner_operator, NAME_MARKER)[0]
