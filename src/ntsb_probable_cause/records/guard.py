"""Guard layer 4: withheld text or codes must never appear in evidence (decision 0016)."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ntsb_probable_cause.fields import EvidenceValue

# Provisional until Task 13 sets it from docs/results/s0-corpus-scan.txt.
MIN_SENTENCE_CHARS = 20

_WHITESPACE = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# The only probable-cause sentences found verbatim in development factual narratives (M5).
_BOILERPLATE = re.compile(r"^\W*this report was modified on\b")


@dataclass(frozen=True)
class Leak:
    """Withheld content found in one evidence value."""

    evidence_role: str
    kind: str
    source: str
    fragment: str

    def __str__(self) -> str:
        return f"{self.kind} from {self.source} in {self.evidence_role}: {self.fragment!r}"


def normalise_text(text: str) -> str:
    """Collapse whitespace and lower-case, so formatting differences cannot hide a copy."""
    return _WHITESPACE.sub(" ", text).strip().lower()


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
        if len(whole) >= min_sentence_chars and not _BOILERPLATE.match(whole):
            needles.append(("text", source, whole))
        needles.extend(
            ("sentence", source, sentence)
            for sentence in _SENTENCE_END.split(whole)
            if len(sentence) >= min_sentence_chars
            and sentence != whole
            and not _BOILERPLATE.match(sentence)
        )
    patterns = [
        (code, re.compile(rf"(?<!\d){re.escape(code)}(?!\d)")) for code in dict.fromkeys(codes)
    ]
    found: list[Leak] = []
    for role, haystack in haystacks.items():
        found.extend(
            Leak(role, kind, source, needle[:80])
            for kind, source, needle in needles
            if needle in haystack
        )
        found.extend(
            Leak(role, "code", "codes", code)
            for code, pattern in patterns
            if pattern.search(haystack)
        )
    return found
