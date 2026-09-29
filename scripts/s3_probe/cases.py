"""Docket facts and the probe's balanced 20-case sample (fatal x has-scan, 5 per cell).

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from ntsb_probable_cause.docket.classify import Kind
from ntsb_probable_cause.docket.manifest import Docket, Status
from ntsb_probable_cause.scoring.samples import sample_ids

# The four cells this probe balances over: whether the case is fatal, and whether its v2
# docket holds at least one scanned or partial-text page with a cached transcription. Fixed
# order, so a cell's position in a report or an error message is always the same.
CELLS: tuple[tuple[bool, bool], ...] = ((False, False), (False, True), (True, False), (True, True))


@dataclass(frozen=True)
class DocketFacts:
    """One document's measured facts, read from its ``DocumentRecord`` -- never its text."""

    index: int
    kind: Kind | None
    pages: int
    readable_pages: int
    estimated_tokens: int
    transcribed_pages: int
    status: Status


def facts(docket: Docket) -> tuple[DocketFacts, ...]:
    """Every document's facts, in the docket's listing order."""
    return tuple(
        DocketFacts(
            index=record.entry.index,
            kind=record.kind,
            pages=record.pages,
            readable_pages=record.readable_pages,
            estimated_tokens=record.estimated_tokens,
            transcribed_pages=record.transcribed_pages,
            status=record.status,
        )
        for record in docket.documents
    )


def has_scan(facts: Sequence[DocketFacts]) -> bool:
    """Whether any document is a scan or partial-text page with at least one read page.

    A scanned or partial document with no transcribed page contributes no words at v2 (its
    pages are absent, not empty), so it does not count as the case having readable scan
    content -- only a transcription makes the page reachable by the agent.
    """
    return any(f.kind in ("scan", "partial") and f.transcribed_pages >= 1 for f in facts)


class CaseInfo(NamedTuple):
    """One case's cell membership: its ID, whether fatal, and whether its docket has a scan."""

    case_id: str
    fatal: bool
    has_scan: bool


def select(
    candidates: Sequence[CaseInfo],
    *,
    per_cell: int = 5,
    seed: int = 20260929,
) -> tuple[str, ...]:
    """Draw ``per_cell`` case IDs from each of the four fatal x has-scan cells.

    Every candidate must be a ``dev-400`` case; refused otherwise, before any cell is drawn.
    Each cell's IDs are sorted, then drawn with a fresh ``random.Random(seed)`` over that
    sorted list -- so one cell's draw never depends on another cell's size or order, and the
    whole selection is deterministic for a given seed.

    Args:
        candidates: every case considered, with its cell membership.
        per_cell: how many IDs to draw from each cell.
        seed: the seed for each cell's draw.

    Returns:
        The chosen case IDs, grouped by cell in ``CELLS`` order.

    Raises:
        ValueError: a candidate is not a ``dev-400`` case, or a cell holds fewer than
            ``per_cell`` candidates.
    """
    dev_ids = frozenset(sample_ids("dev-400"))
    outside = sorted({c.case_id for c in candidates} - dev_ids)
    if outside:
        raise ValueError(f"not in dev-400: {outside}")
    chosen: list[str] = []
    for fatal, scan in CELLS:
        cell_ids = sorted(c.case_id for c in candidates if c.fatal is fatal and c.has_scan is scan)
        if len(cell_ids) < per_cell:
            raise ValueError(
                f"cell fatal={fatal} has_scan={scan}: {len(cell_ids)} candidates, need {per_cell}"
            )
        chosen.extend(random.Random(seed).sample(cell_ids, per_cell))  # noqa: S311 -- reproducible draw, not security
    return tuple(chosen)
