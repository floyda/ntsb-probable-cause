"""Arm B's fixed document filter and the deny-list (spec §7, §9; decisions 0022, 0039, 0043).

Every constant here is chosen on the development split and published before any held-out run.
"""

from typing import Literal

from ntsb_probable_cause.docket.classify import CATEGORIES
from ntsb_probable_cause.docket.manifest import Docket

Variant = Literal["published", "unfiltered", "no-submissions"]

# Title categories that carry the NTSB's case-level write-up. Starts empty and is filled only by
# tripwire hits on dev-400 (decision 0039 item 2); source: docs/results/s2-filter.txt.
DENY_LIST: frozenset[str] = frozenset()

# The types arm B attaches. Initial value: every category but photo sets, which hold no text.
# Re-set by the rule in spec §10 after the dev-400 runs; source: docs/results/s2-filter.txt.
ARM_B_TYPES: frozenset[str] = frozenset(name for name, _ in CATEGORIES if name != "photos") | {
    "other"
}

# Rank order: types listed first are attached first (decision 0043). Empty means listing order.
# Re-set to the ascending median-tokens order measured on dev-400; source: s2-filter.txt.
ARM_B_RANK: tuple[str, ...] = ()


def is_denied(category: str) -> bool:
    """True if the category is on the deny-list."""
    return category in DENY_LIST


def arm_b_documents(docket: Docket, *, variant: Variant = "published") -> list[int]:
    """Listing indices of the read documents arm B attaches, in rank order then index order."""
    admitted = (
        {name for name, _ in CATEGORIES} | {"other"}
        if variant == "unfiltered"
        else ARM_B_TYPES - ({"party_submission"} if variant == "no-submissions" else set())
    )
    rank = {name: position for position, name in enumerate(ARM_B_RANK)}
    chosen = [r for r in docket.documents if r.status == "read" and r.category in admitted]
    chosen.sort(key=lambda r: (rank.get(r.category, len(rank)), r.entry.index))
    return [r.entry.index for r in chosen]
