"""The names step for text that leaves the live board (decisions 0180, 0182, 0184).

Two rules, and no guessing between them.

* **The case's exact parts** (its owner and operator strings, and every aircraft's
  registration) are replaced, any case, whole string, by ``docket.attach``'s rule, in prose and
  in titles alike (``board_text``, ``board_title`` with the case's names).
* **Titles** then keep the title rule: a capitalised word in neither the title vocabulary nor
  the word list becomes ``NAME_MARKER`` (``board_title``). The title rule's capitalised-word
  pattern never matches an N-number such as ``N123XX``, which is why the registration is
  replaced first.
* **Prose** (Ellery's causes, accounts, notes and coding-lookup reasons, and the NTSB's cause
  statement) has only the case's exact parts replaced. A capitalised word in prose is never
  replaced on a guess: most are ordinary words, makers and places (0182).

The limit is published (:data:`NAMES_LIMIT`).

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
# A registration shorter than this is not replaced: it would hit tokens such as "N1".
MIN_REGISTRATION_LEN: Final = 3
NAMES_LIMIT: Final = (
    "A name the rules cannot recognise is not replaced: in prose, any name other than the "
    "owner, operator and registration; in titles, also a name made only of ordinary words, such "
    "as a common surname or given name. A registration shorter than 3 characters is not "
    'replaced, because it would hit tokens like "N1".'
)


@dataclass(frozen=True)
class CaseNames:
    """What one case's names step replaces: its owner and operator strings and registrations."""

    owner_operator: tuple[str, ...]
    registrations: tuple[str, ...] = ()

    def values(self) -> tuple[str, ...]:
        """Every string to replace: the owner and operator strings, then the registrations."""
        return (*self.owner_operator, *self.registrations)


def _registrations(raw: Mapping[str, object]) -> tuple[str, ...]:
    """Every aircraft's registration, stripped, once each; a short one is left out."""
    found: list[str] = []
    aircrafts = raw.get("aircrafts")
    for aircraft in aircrafts if isinstance(aircrafts, list) else []:
        value = aircraft.get("aircraftRegistrationNumber") if isinstance(aircraft, dict) else None
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if len(stripped) >= MIN_REGISTRATION_LEN and stripped not in found:
            found.append(stripped)
    return tuple(found)


def case_names(raw: Mapping[str, object]) -> CaseNames:
    """The owner, operator and registration strings of ``raw``, from every aircraft.

    The owner and operator strings are selected as ``docket.attach`` selects them.
    """
    return CaseNames(
        owner_operator=tuple(owner_operator_values(raw)), registrations=_registrations(raw)
    )


def board_title(title: str, known: frozenset[str], names: CaseNames | None = None) -> str:
    """``title`` with the case's exact parts replaced, then each capitalised word not in ``known``.

    Args:
        title: a document's title.
        known: the title vocabulary and word list.
        names: the case's names; when given, its owner and operator strings and registrations
            are replaced first, any case (decision 0184).
    """
    if names is not None:
        title = replace_values(title, names.values(), NAME_MARKER)[0]

    def _replace(match: re.Match[str]) -> str:
        word = match.group(0)
        return word if is_ordinary_word(word, known) else NAME_MARKER

    return CAPITALISED_WORD.sub(_replace, title)


def board_text(text: str, names: CaseNames) -> str:
    """``text`` with the case's owner, operator and registration strings replaced, any case."""
    return replace_values(text, names.values(), NAME_MARKER)[0]
