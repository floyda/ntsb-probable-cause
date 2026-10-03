"""Guard layer 4: withheld text or codes must never appear in evidence (decision 0016)."""

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ntsb_probable_cause.fields import EvidenceRole, EvidenceValue

# Measured: the smallest candidate minimum sentence length with zero tripwire hits over the
# whole corpus, after decision 0019's weather_metar/factual_narrative sentence exemption.
# Source: docs/results/s0-corpus-scan.txt (scripts/corpus_scan.py). Change only by re-running
# the scan.
# Caveat, decision 0050: that scan runs with whatever SENTENCE_CHECK_EXEMPTIONS holds, which is
# now two pairs rather than one, so a re-run no longer reproduces the recorded figure. The 20 is
# still the number 0019 measured; it is no longer the number the scan would print today.
MIN_SENTENCE_CHARS = 20

# Sentence-level exemptions, one role/source pair each. In every listed role, sentences taken
# from the named withheld source are not compared; sentences from every other withheld source,
# whole texts and codes are still compared there, and no other role is affected. Each pair is
# justified by a measurement showing the matches are the named source quoting that evidence, not
# the evidence reaching an answer -- the guard compares strings and cannot see that direction, so
# the exemption is added only where the data forces it, and as narrowly as it allows (0019).
# - weather_metar / factual_narrative (0019): the narrative quoting the weather observation.
#   Accepted gap: a factual-narrative sentence placed in a plain-English weather value would
#   pass unseen.
# - docket_documents / factual_narrative (0050): the factual narrative is written from the
#   docket at the end of the investigation, so a shared sentence is the narrative quoting a
#   document, not the document containing the answer. docket_listing is not exempted (0050
#   item 3). Accepted gap: a factual-narrative sentence placed inside a docket document would
#   pass unseen.
SENTENCE_CHECK_EXEMPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (EvidenceRole.WEATHER_METAR.value, "factual_narrative"),
        (EvidenceRole.DOCKET_DOCUMENTS.value, "factual_narrative"),
    }
)

_WHITESPACE = re.compile(r"\s+")
# Break on ".", "!", "?" or ";" followed by whitespace, and also on ".", "!" or "?" directly
# followed by a letter with no space (a trivial edit that would otherwise hide a sentence).
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|(?<=[.!?])(?=[A-Za-z])")
# Trailing sentence punctuation, closing quotes/brackets, the comma of a dropped clause, and any
# whitespace mixed in with them (e.g. a space left behind once a final mark is stripped), stripped
# from every needle so a dropped or appended final mark -- or the whitespace it leaves -- cannot
# defeat a match. A single character class with "+" already consumes any run of these mixed
# together, so no separate repeat-until-stable step is needed.
_NEEDLE_EDGE = re.compile(r"[\s.!?;:,'\")\]}]+$")
# Leading opening quotes/brackets and whitespace, stripped the same way from the front of every
# needle so a dropped or added opening mark cannot defeat a match either.
_NEEDLE_LEADING_EDGE = re.compile(r"""^[\s"'(\[{]+""")
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
    fragment: str = field(repr=False)

    def __str__(self) -> str:
        chars = len(self.fragment)
        return f"{self.kind} from {self.source} in {self.evidence_role} ({chars} chars withheld)"


def normalise_text(text: str) -> str:
    """Fold Unicode compatibility forms and curly quotes, collapse whitespace, lower-case."""
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTE_FOLD)
    return _WHITESPACE.sub(" ", folded).strip().lower()


def _strip_needle(text: str) -> str:
    """Strip leading opening marks/whitespace and trailing punctuation/closing marks/whitespace."""
    return _NEEDLE_EDGE.sub("", _NEEDLE_LEADING_EDGE.sub("", text))


def _as_text(value: EvidenceValue) -> str:
    if isinstance(value, tuple):
        return " | ".join(value)
    return "" if value is None else str(value)


def _needles(source: str, text: str | None, min_sentence_chars: int) -> list[tuple[str, str, str]]:
    """The whole text and each sentence of one withheld text, as the tripwire searches them."""
    if not text:
        return []
    whole = normalise_text(text)
    whole_stripped = _strip_needle(whole)
    needles: list[tuple[str, str, str]] = []
    # Never exempted for boilerplate: only a single isolated sentence can be boilerplate.
    if len(whole_stripped) >= min_sentence_chars:
        needles.append(("text", source, whole_stripped))
    for sentence in _SENTENCE_END.split(whole):
        stripped = _strip_needle(sentence)
        if (
            len(stripped) >= min_sentence_chars
            and stripped != whole_stripped
            and not _BOILERPLATE_SENTENCE.match(stripped)
        ):
            needles.append(("sentence", source, stripped))
    return needles


def find_leaks(
    evidence: Mapping[str, EvidenceValue],
    withheld_text: Mapping[str, str | None],
    codes: Iterable[str],
    *,
    min_sentence_chars: int = MIN_SENTENCE_CHARS,
    exemptions: frozenset[tuple[str, str]] = SENTENCE_CHECK_EXEMPTIONS,
) -> list[Leak]:
    """Return every place withheld text, sentence or code appears in an evidence value."""
    haystacks = {role: normalise_text(_as_text(value)) for role, value in evidence.items()}
    needles = [
        needle
        for source, text in withheld_text.items()
        for needle in _needles(source, text, min_sentence_chars)
    ]
    patterns = [
        (code, re.compile(rf"\b{re.escape(code)}\b"))
        for code in dict.fromkeys(code for code in codes if code and code.strip())
    ]
    found: list[Leak] = []
    for role, haystack in haystacks.items():
        found.extend(
            Leak(role, kind, source, needle)
            for kind, source, needle in needles
            if not (kind == "sentence" and (role, source) in exemptions) and needle in haystack
        )
        found.extend(
            Leak(role, "code", "codes", code)
            for code, pattern in patterns
            if pattern.search(haystack)
        )
    return found


# Decision 0078: a case is marked narrative_coverage when one docket document holds at least
# this share of the factual narrative's sentences (docs/results/s2-narrative-coverage.txt:
# 3 of 379 development cases).
NARRATIVE_COVERAGE_MARK = 0.5

# Sentence matches that mark the case instead of refusing it, one role/source pair each.
# Only a sentence is ever marked: a whole withheld text, a probable-cause sentence or a code
# still refuses, in every role.
# - docket_documents / analysis_narrative (0077, adopted after Andy's hand-check,
#   docs/results/s26-analysis-handcheck.txt): the analysis is written from the docket at the
#   end of the investigation, so a shared sentence is usually the analysis quoting evidence.
#   Measured error: the conclusions that file counts.
MARKED_SENTENCES: frozenset[tuple[str, str]] = frozenset(
    {(EvidenceRole.DOCKET_DOCUMENTS.value, "analysis_narrative")}
)


def sentence_needles(
    text: str | None, *, min_sentence_chars: int = MIN_SENTENCE_CHARS
) -> frozenset[str]:
    """The sentences of one withheld text, normalised exactly as the tripwire searches them."""
    return frozenset(
        needle for kind, _, needle in _needles("", text, min_sentence_chars) if kind == "sentence"
    )


def narrative_shares(
    documents: Sequence[str],
    narrative: str | None,
    *,
    min_sentence_chars: int = MIN_SENTENCE_CHARS,
) -> tuple[float, ...]:
    """Per document, the share of the narrative's sentences found in it (decision 0078).

    Empty when there are no documents or the narrative has no sentence long enough to
    search for -- a case with nothing to compare has no share, not a share of zero.
    """
    needles = sentence_needles(narrative, min_sentence_chars=min_sentence_chars)
    if not needles or not documents:
        return ()
    return tuple(
        sum(1 for needle in needles if needle in haystack) / len(needles)
        for haystack in (normalise_text(document) for document in documents)
    )


@dataclass(frozen=True)
class Screen:
    """What the tripwire found: leaks, which refuse the case, and marked sentences."""

    leaks: tuple[Leak, ...]
    marked: tuple[Leak, ...]


def screen(  # noqa: PLR0913 -- find_leaks' parameters plus the marked pairs.
    evidence: Mapping[str, EvidenceValue],
    withheld_text: Mapping[str, str | None],
    codes: Iterable[str],
    *,
    min_sentence_chars: int = MIN_SENTENCE_CHARS,
    exemptions: frozenset[tuple[str, str]] = SENTENCE_CHECK_EXEMPTIONS,
    marked: frozenset[tuple[str, str]] = MARKED_SENTENCES,
) -> Screen:
    """``find_leaks``, with sentence matches in the marked role/source pairs set apart."""
    found = find_leaks(
        evidence,
        withheld_text,
        codes,
        min_sentence_chars=min_sentence_chars,
        exemptions=exemptions,
    )

    def is_marked(leak: Leak) -> bool:
        return leak.kind == "sentence" and (leak.evidence_role, leak.source) in marked

    return Screen(
        leaks=tuple(leak for leak in found if not is_marked(leak)),
        marked=tuple(leak for leak in found if is_marked(leak)),
    )
