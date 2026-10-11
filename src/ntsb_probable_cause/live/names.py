"""The names step for text that leaves the live board (decisions 0180, 0182).

Two rules, and no guessing between them.

* **Titles** keep the title rule: a capitalised word in neither the title vocabulary nor the
  word list becomes ``NAME_MARKER`` (``board_title``).
* **Prose** (Ellery's causes, accounts, notes and coding-lookup reasons, and the NTSB's cause
  statement) has only the case's own owner and operator strings, and its registration, replaced
  (``board_text``), by ``docket.attach``'s whole-string rule. A capitalised word in prose is
  never replaced on a guess: most are ordinary words, makers and places (0182).
* **The registration** is replaced in titles too (``board_title`` with the case's names): the title
  rule's capitalised-word pattern never matches an N-number such as ``N123XX``.

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
from ntsb_probable_cause.paths import resolve_path

NAME_MARKER: Final = "[name]"


@dataclass(frozen=True)
class CaseNames:
    """What one case's names step replaces: its owner and operator strings and registration."""

    owner_operator: tuple[str, ...]
    registration: str | None = None

    def values(self) -> tuple[str, ...]:
        """Every string to replace, the registration included when the case has one."""
        if self.registration is None:
            return self.owner_operator
        return (*self.owner_operator, self.registration)


def case_names(raw: Mapping[str, object]) -> CaseNames:
    """The owner, operator and registration strings of ``raw``.

    The owner and operator strings are selected as ``docket.attach`` selects them.
    """
    registration = resolve_path(raw, "aircrafts[0].aircraftRegistrationNumber")
    return CaseNames(
        owner_operator=tuple(owner_operator_values(raw)),
        registration=registration.strip()
        if isinstance(registration, str) and registration.strip()
        else None,
    )


# Decision 0183 lets prose name the make and model, so only the registration is replaced here.


def board_title(title: str, known: frozenset[str], names: CaseNames | None = None) -> str:
    """``title`` with the registration replaced, then each capitalised word absent from ``known``.

    Args:
        title: a document's title.
        known: the title vocabulary and word list.
        names: the case's names; when given, its registration is replaced first.
    """
    if names is not None and names.registration is not None:
        title = replace_values(title, (names.registration,), NAME_MARKER)[0]

    def _replace(match: re.Match[str]) -> str:
        word = match.group(0)
        return word if is_ordinary_word(word, known) else NAME_MARKER

    return CAPITALISED_WORD.sub(_replace, title)


def board_text(text: str, names: CaseNames) -> str:
    """``text`` with the case's owner, operator and registration strings replaced."""
    return replace_values(text, names.values(), NAME_MARKER)[0]
