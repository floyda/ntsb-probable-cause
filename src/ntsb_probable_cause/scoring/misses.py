"""Where a first occurrence guess lands in the NTSB's sequence, and how deep a finding miss goes.

S2.7 spec §4.1. Pure functions over codes: no case, no text but the model's own. A six-digit
occurrence code is a three-digit phase and a three-digit event; the NTSB's sequence lists the
defining event first (``fields.occurrence_codes``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

MissGroup = Literal[
    "exact",
    "right event, wrong phase",
    "in sequence, not defining",
    "a later guess in sequence",
    "event under another phase",
    "nothing in common",
    "abstained",
]
GROUPS: tuple[MissGroup, ...] = (
    "exact",
    "right event, wrong phase",
    "in sequence, not defining",
    "a later guess in sequence",
    "event under another phase",
    "nothing in common",
    "abstained",
)
MISS_GROUPS: tuple[MissGroup, ...] = GROUPS[1:6]


def miss_group(  # noqa: PLR0911 -- one early return per group, tested in GROUPS' order
    guesses: Sequence[str], truth: Sequence[str], *, abstain: bool
) -> MissGroup:
    """The one group a case's first guess falls in, tested in the order of :data:`GROUPS`."""
    if abstain:
        return "abstained"
    if not truth or not guesses:
        return "nothing in common"
    first, defining = guesses[0], truth[0]
    if first == defining:
        return "exact"
    if first[3:] == defining[3:]:
        return "right event, wrong phase"
    if first in truth:
        return "in sequence, not defining"
    if any(guess in truth for guess in guesses[1:]):
        return "a later guess in sequence"
    if any(guess[3:] == code[3:] for guess in guesses for code in truth):
        return "event under another phase"
    return "nothing in common"


@dataclass(frozen=True)
class FindingDepth:
    """For the NTSB's flagged findings: how many the model found, and how deep each miss was."""

    flagged: int
    found: int
    item_right_modifier_wrong: int
    category_right_item_wrong: int
    category_wrong: int

    def __add__(self, other: FindingDepth) -> FindingDepth:
        return FindingDepth(
            self.flagged + other.flagged,
            self.found + other.found,
            self.item_right_modifier_wrong + other.item_right_modifier_wrong,
            self.category_right_item_wrong + other.category_right_item_wrong,
            self.category_wrong + other.category_wrong,
        )


def finding_depth(predicted: Sequence[str], flagged: Sequence[str]) -> FindingDepth:
    """Each flagged ten-digit finding at its deepest match among the model's findings."""
    found = modifier = item = category = 0
    for code in flagged:
        if code in predicted:
            found += 1
        elif any(p[:8] == code[:8] for p in predicted):
            modifier += 1
        elif any(p[:6] == code[:6] for p in predicted):
            item += 1
        else:
            category += 1
    return FindingDepth(len(flagged), found, modifier, item, category)


# A fixed, crude list, committed so "the model's own words name the NTSB's event" is counted
# the same way every time (spec §4.1 item 4). Lower case; matched as substrings.
EVENT_PHRASES: Mapping[str, tuple[str, ...]] = {
    "090": ("bounced", "porpois", "abnormal runway contact"),
    "092": ("hard landing", "landed hard"),
    "120": ("controlled flight into terrain", "cfit"),
    "191": ("fuel starvation", "starved", "fuel selector"),
    "192": ("fuel exhaustion", "ran out of fuel", "exhausted the fuel", "no usable fuel"),
    "220": ("low altitude", "low-altitude", "low level", "low-level"),
    "230": ("loss of control", "lost control", "ground loop", "veered"),
    "240": ("loss of control", "lost control", "loss of aircraft control"),
    "241": ("stall", "spin"),
    "300": ("runway excursion", "departed the runway", "exited the runway", "ran off", "overran"),
    "341": ("total loss of engine power", "total loss of power", "engine stopped", "engine quit"),
    "342": ("partial loss of engine power", "partial loss of power", "lost partial power"),
    "401": ("instrument meteorological", "imc", "cloud", "fog", "visibility"),
    "470": ("collided with", "collision with", "struck", "impacted"),
}


def names_event(text: str, event: str) -> bool | None:
    """Whether ``text`` names ``event`` by the fixed list; None when the event has no list."""
    phrases = EVENT_PHRASES.get(event)
    if phrases is None:
        return None
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)
