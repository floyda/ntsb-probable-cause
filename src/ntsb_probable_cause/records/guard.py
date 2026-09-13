"""Guard layer 4: withheld text or codes must never appear in evidence (decision 0016)."""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ntsb_probable_cause.fields import EvidenceValue

# Provisional until Task 13 sets it from docs/results/s0-corpus-scan.txt.
MIN_SENTENCE_CHARS = 20

_WHITESPACE = re.compile(r"\s+")
# Break on ".", "!", "?" or ";" followed by whitespace, and also on ".", "!" or "?" directly
# followed by a letter with no space (a trivial edit that would otherwise hide a sentence).
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|(?<=[.!?])(?=[A-Za-z])")
# Trailing sentence punctuation and closing quotes/brackets, stripped from every needle so a
# dropped or appended final mark cannot defeat a match.
_TRAILING_PUNCT = re.compile(r"[.!?;:'\")\]}]+$")
# Curly quote variants folded to their straight ASCII form. The keys are the actual characters
# being matched (ruff's ambiguous-character check would otherwise flag every one; noqa is scoped
# to this one rule, on this one construct, not a blanket ignore).
_QUOTE_FOLD = str.maketrans(
    {
        "‘": "'",  # noqa: RUF001 - left single quotation mark
        "’": "'",  # noqa: RUF001 - right single quotation mark
        "‚": "'",  # noqa: RUF001 - single low-9 quotation mark
        "‛": "'",  # noqa: RUF001 - single high-reversed-9 quotation mark
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
    }
)
# The exact boilerplate sentence found verbatim in development narratives (M5; verified against
# real records in data/raw/v2/2014-06 and data/raw/v2/2016-08): "**This report was modified on
# <date>.**", date as "Month D, YYYY" or "M/D/YYYY", wrapped in **/*** and optional quotes.
# Matched only against a single split-out sentence, never the whole withheld text.
_BOILERPLATE_SENTENCE = re.compile(
    r"^\W*this report was modified on (?:[a-z]+ \d{1,2}, \d{4}|\d{1,2}/\d{1,2}/\d{4})\W*$"
)


@dataclass(frozen=True)
class Leak:
    """Withheld content found in one evidence value.

    ``fragment`` is kept for callers that need the structured detail (tests, an audit trail),
    but ``__str__`` never renders it -- from S3 an error message could reach a model or a board.
    """

    evidence_role: str
    kind: str
    source: str
    fragment: str

    def __str__(self) -> str:
        chars = len(self.fragment)
        return f"{self.kind} from {self.source} in {self.evidence_role} ({chars} chars withheld)"


def normalise_text(text: str) -> str:
    """Fold Unicode compatibility forms and curly quotes, collapse whitespace, lower-case."""
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTE_FOLD)
    return _WHITESPACE.sub(" ", folded).strip().lower()


def _strip_trailing_punct(text: str) -> str:
    return _TRAILING_PUNCT.sub("", text)


def _as_text(value: EvidenceValue) -> str:
    if isinstance(value, tuple):
        return " | ".join(value)
    return "" if value is None else str(value)


def find_leaks(
    evidence: Mapping[str, EvidenceValue],
    withheld_text: Mapping[str, str | None],
    codes: Iterable[str],
    *,
    min_sentence_chars: int = MIN_SENTENCE_CHARS,
) -> list[Leak]:
    """Return every place withheld text, sentence or code appears in an evidence value."""
    haystacks = {role: normalise_text(_as_text(value)) for role, value in evidence.items()}
    needles: list[tuple[str, str, str]] = []
    for source, text in withheld_text.items():
        if not text:
            continue
        whole = normalise_text(text)
        whole_stripped = _strip_trailing_punct(whole)
        # Never exempted for boilerplate: only a single isolated sentence can be boilerplate.
        if len(whole_stripped) >= min_sentence_chars:
            needles.append(("text", source, whole_stripped))
        for sentence in _SENTENCE_END.split(whole):
            stripped = _strip_trailing_punct(sentence)
            if (
                len(stripped) >= min_sentence_chars
                and stripped != whole_stripped
                and not _BOILERPLATE_SENTENCE.match(stripped)
            ):
                needles.append(("sentence", source, stripped))
    patterns = [
        (code, re.compile(rf"\b{re.escape(code)}\b"))
        for code in dict.fromkeys(code for code in codes if code and code.strip())
    ]
    found: list[Leak] = []
    for role, haystack in haystacks.items():
        found.extend(
            Leak(role, kind, source, needle)
            for kind, source, needle in needles
            if needle in haystack
        )
        found.extend(
            Leak(role, "code", "codes", code)
            for code, pattern in patterns
            if pattern.search(haystack)
        )
    return found
