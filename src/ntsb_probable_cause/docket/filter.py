"""Arm B's document filter and the deny-list (spec §7, §9; decisions 0022, 0039, 0043, 0048, 0052).

Every constant here is chosen on the development split and published before any held-out run.
"""

from typing import Literal

from ntsb_probable_cause.docket.manifest import Docket

Variant = Literal["published", "no-submissions"]

# Title categories that carry the NTSB's case-level write-up. Starts empty and is filled only by
# tripwire hits on dev-400 (decision 0039 item 2); source: docs/results/s2-filter.txt.
DENY_LIST: frozenset[str] = frozenset()


def is_denied(category: str) -> bool:
    """True if the category is on the deny-list."""
    return category in DENY_LIST


def arm_b_documents(docket: Docket, *, variant: Variant = "published") -> list[int]:
    """Listing indices of the read documents arm B attaches, smallest measured size first.

    Decision 0052: admission is the measured outcome of text extraction, not a guess from the
    document's title. A document is given status ``"read"`` only when extraction found text
    on it, so that status *is* the admission test -- there is no separate category check, and
    a title misread can no longer delete a document from arm B. The category survives for
    three things only, none of them admission: the ``no-submissions`` variant below, the
    deny-list (0039), and the header label plus step-log lines (0051).

    Decision 0048: order is each document's own ``estimated_tokens``, ascending, so the
    largest number of whole documents fit under the cap (0043's reason, unchanged). Ties
    break by listing index, never by set iteration order. The category is not consulted for
    order -- only, under ``no-submissions``, for admission.
    """
    chosen = [
        r
        for r in docket.documents
        if r.status == "read"
        and not (variant == "no-submissions" and r.category == "party_submission")
    ]
    chosen.sort(key=lambda r: (r.estimated_tokens, r.entry.index))
    return [r.entry.index for r in chosen]
