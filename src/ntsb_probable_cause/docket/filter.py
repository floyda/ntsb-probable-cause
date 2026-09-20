"""Arm B's document filter (spec §7, §9; decisions 0022, 0043, 0048, 0052, 0054, 0056).

Every constant here is chosen on the development split and published before any held-out run.
"""

from ntsb_probable_cause.docket.manifest import Docket


def arm_b_documents(docket: Docket) -> list[int]:
    """Listing indices of the read documents arm B attaches, smallest measured size first.

    Decision 0052: admission is the measured outcome of text extraction, not a guess from the
    document's title. A document is given status ``"read"`` only when extraction found text
    on it, so that status *is* the admission test -- there is no separate category check, and
    a title misread can no longer delete a document from arm B. Every document at that
    status is attached; decision 0056 found the deny-list cannot be filled from titles
    without denying the taxonomy's largest bucket, and decision 0054 retired the
    ``no-submissions`` run variant on the same ground (the population it excluded could not
    be identified from titles either). The category now carries no admission decision at
    all -- it survives only as a published statistic and the header/step-log diagnostic word.

    Decision 0048: order is each document's own ``estimated_tokens``, ascending, so the
    largest number of whole documents fit under the cap (0043's reason, unchanged). Ties
    break by listing index, never by set iteration order. The category is not consulted for
    order.
    """
    chosen = [r for r in docket.documents if r.status == "read"]
    chosen.sort(key=lambda r: (r.estimated_tokens, r.entry.index))
    return [r.entry.index for r in chosen]
