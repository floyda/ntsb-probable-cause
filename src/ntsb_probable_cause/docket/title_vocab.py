"""What counts as an ordinary word in a docket title (finding 6's replacement, decision 0046).

``check_fixtures_redacted.py``'s old name check matched ``of|by|with|from|signed`` followed by
Title Case words. Measured on real data it flagged 16 titles across six drawn listings and 5 of
60 hand-check rows, and every one was a false positive -- ordinary NTSB title grammar such as
"Statement of Party Representatives to NTSB Investigation". This module holds the replacement
rule instead: a capitalised word that appears in **only a few** dockets and is **not an
ordinary word** is very likely a proper noun specific to one case.

``capitalised_words`` finds the candidate tokens: an initial capital letter followed by two or
more lowercase letters (``[A-Z][a-z]{2,}``, three letters minimum). A word such as
``Aircraft`` matches; an ALL-CAPS acronym such as ``NTSB`` or ``FAA`` does not (an all-caps
title is shouting, not signalling a proper noun -- and the old heuristic's trigger words were
case-sensitive for the same reason, so this carries no new gap there); a two-letter word such
as ``Of`` or ``By`` does not either.

``load_title_vocabulary`` reads the committed ``vocab/title_words.txt``: every capitalised word
``scripts/build_title_vocab.py`` found in five or more distinct cached dockets, sorted. That
script's own docstring says how and when to regenerate it. ``known_title_words`` adds the
vendored dictionary (decision 0070) on top. ``is_ordinary_word`` is the membership test itself.
A title's capitalised word that fails it
is what ``check_fixtures_redacted.title_looks_like_a_name`` flags, and what ``redact_title``
replaces -- the hand-check sheet (``scripts/make_docket_fixture.py``'s ``handcheck``
subcommand) cannot be committed with the flagged word left in place, since several of the
words it flags on real titles are genuine surnames.

**Deliberately not a stemmer.** A tried-and-rejected version of ``is_ordinary_word`` also
accepted a word as ordinary when stripping a regular English plural ending ("-s", "-es",
"-ies") landed on a known word -- meant to absorb plurals the system dictionary lists only in
singular form ("parts" -> "part"), which measured as the largest source of noise once the
vocabulary and dictionary were combined (11.2% of the 3,790 cached titles flagged, against
7.2% with the stemmer). It was rejected once measured: the system dictionary lists given
names as well as ordinary nouns, so stripping a plural "-s" also turns most common
"<given name>+s" English surnames -- exactly the shape a great many real surnames take, and
exactly what this check exists to catch -- into a dictionary word, un-flagging them silently.
A plain membership test carries a higher false-positive rate; it does not carry that risk.
"""

import re
from functools import cache
from importlib import resources
from pathlib import Path

#: An initial capital letter followed by two or more lowercase letters: three letters or more,
#: strict Title Case. See the module docstring for why ALL-CAPS acronyms are excluded.
CAPITALISED_WORD = re.compile(r"[A-Z][a-z]{2,}")

#: The vendored word list, committed to the repository (decision 0070). Removes the need
#: for CI to install a system dictionary.
VENDORED_DICTIONARY_PATH = Path("tests/fixtures/words.txt")

#: The minimum number of distinct dockets a word must appear in to be "ordinary NTSB title
#: vocabulary" rather than a proper noun specific to one case (scripts/build_title_vocab.py).
MIN_DOCKETS = 5

_VOCAB_PACKAGE = "ntsb_probable_cause.docket"
_VOCAB_RESOURCE = "vocab/title_words.txt"


def capitalised_words(text: str) -> list[str]:
    """Every strict Title Case token in ``text`` -- see the module docstring for the rule."""
    return CAPITALISED_WORD.findall(text)


def is_ordinary_word(word: str, known: frozenset[str]) -> bool:
    """True if ``word`` (any case) is in ``known``.

    Plain membership -- see the module docstring's "Deliberately not a stemmer" note for why.
    """
    return word.lower() in known


#: The literal marker a redacted word is replaced with (``scripts/make_docket_fixture.py``'s
#: ``handcheck`` sheet). A marker, not a drop: dropping the word would make a title such as
#: "Reports from Parties to the Investigation: Piper Propeller" read as if a word were simply
#: missing, where the marker keeps the title gradeable for what the hand-check actually asks
#: (is this a photograph, could it hold the investigators' conclusions, who wrote it).
PROPER_NOUN_MARKER = "[proper noun]"


def redact_title(title: str, known: frozenset[str]) -> tuple[str, int]:
    """``title`` with every word ``is_ordinary_word`` rejects replaced by ``PROPER_NOUN_MARKER``.

    The same test ``title_looks_like_a_name`` applies, turned into a replacement instead of a
    yes/no check: every capitalised word (``capitalised_words``) absent from ``known`` is
    redacted, brand names and misspellings along with genuine surnames alike (the module
    docstring's "Deliberately not a stemmer" note explains why this test cannot tell the two
    apart, and should not try to). Returns the redacted title and how many words were replaced.
    """
    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        word = match.group(0)
        if is_ordinary_word(word, known):
            return word
        count += 1
        return PROPER_NOUN_MARKER

    return CAPITALISED_WORD.sub(_replace, title), count


@cache
def load_title_vocabulary() -> frozenset[str]:
    """The committed vocabulary file, lowercased.

    Regenerate with ``uv run python -m scripts.build_title_vocab`` (needs the docket cache,
    which is not present in CI or a pre-commit hook -- this reads the committed text file,
    never the cache itself).
    """
    text = resources.files(_VOCAB_PACKAGE).joinpath(_VOCAB_RESOURCE).read_text()
    return frozenset(word.strip().lower() for word in text.splitlines() if word.strip())


@cache
def _system_dictionary(path: Path) -> frozenset[str] | None:
    """The word list at ``path``, lowercased; ``None`` if this machine has none there."""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", errors="replace") as handle:
        return frozenset(word.strip().lower() for word in handle if word.strip())


def known_title_words(
    dictionary_path: Path = VENDORED_DICTIONARY_PATH,
) -> tuple[frozenset[str], bool]:
    """The committed vocabulary, plus the system dictionary if this machine has one.

    Returns the combined set and whether the dictionary was found, so a caller can say so
    instead of silently checking against the much smaller vocabulary alone without a word
    about it -- a missing check input is reported, never passed over in silence.
    """
    vocabulary = load_title_vocabulary()
    dictionary = _system_dictionary(dictionary_path)
    if dictionary is None:
        return vocabulary, False
    return vocabulary | dictionary, True
