"""The document payloads: the only place the agent turns a record and its docket into model text.

Every payload built here is ``Payload.from_evidence(split_record(context, exclude=...)[0])``
(CLAUDE.md rule 1; decision 0016), never a second assembler. The agent's conversation reads in
three pieces, each a split of its own with every other role excluded, so each is screened by the
layered guard on its own text:

* the first user message: the record's evidence without its docket (:func:`evidence_payload`);
* the listing, sent once, as the tool result of the first hypothesis (:func:`listing_payload`);
* the documents the agent chose to read, as the tool result of the choice
  (:func:`documents_payload`).

The refinement, a separate request that is exactly the runner's stage 2, re-sends arm B's payload
shape instead: the evidence, the listing and the documents read, in one split
(:func:`answer_payload`).

Within the agent's conversation, titles come only from the listing payload. A ``LeakageError``
from any function here propagates: the loop turns it into ``failed: leak`` and never sends the
text.

An exclusion set is the run's (an ablation, or a masked availability condition). A docket role in
it empties the matching payload to ``{}``; the loop refuses that configuration up front, as arm
B does, because an agent with no docket has nothing to choose.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ntsb_probable_cause.agent.facts import DocumentFacts
from ntsb_probable_cause.docket.attach import DOCKET_KEY, Attachment, prepare_attachment
from ntsb_probable_cause.docket.filter import arm_b_documents
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.records.split import split_record

_ALL_ROLES: Final = frozenset(EvidenceRole)
_DOCKET_ROLES: Final = frozenset({EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS})


@dataclass(frozen=True)
class DocketView:
    """A case's docket as the agent meets it: the prepared text, and the facts it may see.

    Attributes:
        attachment: the listing and every readable document, rendered and redacted once.
        offered: the readable documents, smallest first (arm B's order); what the agent chooses
            between.
        not_readable: every document whose status is not ``"read"``, in listing order.
    """

    attachment: Attachment
    offered: tuple[DocumentFacts, ...]
    not_readable: tuple[DocumentFacts, ...]


def _facts(record: DocumentRecord) -> DocumentFacts:
    return DocumentFacts(
        index=record.entry.index,
        pages=record.pages,
        readable_pages=record.readable_pages,
        estimated_tokens=record.estimated_tokens,
        kind=record.kind,
        status=record.status,
    )


def docket_view(raw: Mapping[str, object], docket: Docket) -> DocketView:
    """Prepare a case's docket once: the attachment, the offered documents and the rest.

    Args:
        raw: the case record (without a docket).
        docket: the case's listing, document records and text.

    Returns:
        The view. ``offered`` follows ``arm_b_documents`` (measured size ascending, ties by
        listing index); ``not_readable`` holds every document that is not ``read``.
    """
    return DocketView(
        attachment=prepare_attachment(raw, docket),
        offered=tuple(_facts(docket.record(index)) for index in arm_b_documents(docket)),
        not_readable=tuple(_facts(r) for r in docket.documents if r.status != "read"),
    )


def evidence_payload(raw: Mapping[str, object], exclusions: frozenset[EvidenceRole]) -> Payload:
    """The first user message: the record's evidence, with no docket listing or documents.

    Args:
        raw: the case record; a ``docket`` key, if it has one, is dropped from a copy.
        exclusions: the run's excluded evidence roles.

    Returns:
        The payload of every evidence role the run keeps, except the two docket roles.

    Raises:
        LeakageError: the guard found withheld text in the evidence.
    """
    record = {key: value for key, value in raw.items() if key != DOCKET_KEY}
    evidence, _, _ = split_record(record, exclude=exclusions | _DOCKET_ROLES)
    return Payload.from_evidence(evidence)


def listing_payload(view: DocketView, exclusions: frozenset[EvidenceRole]) -> Payload:
    """The docket listing alone: the only place a document's title reaches the model.

    Args:
        view: the case's prepared docket.
        exclusions: the run's excluded evidence roles.

    Returns:
        A payload holding only the ``docket_listing`` role.

    Raises:
        LeakageError: the guard found withheld text in the listing.
    """
    context = view.attachment.context_for(()).context
    evidence, _, _ = split_record(
        context, exclude=(_ALL_ROLES - {EvidenceRole.DOCKET_LISTING}) | exclusions
    )
    return Payload.from_evidence(evidence)


def documents_payload(
    view: DocketView, indices: Sequence[int], exclusions: frozenset[EvidenceRole]
) -> Payload:
    """The documents the agent chose, and nothing else, each with its header line.

    Args:
        view: the case's prepared docket.
        indices: listing indices to attach, in the order to render them; one the docket holds
            but cannot read is left out, as ``Attachment.context_for`` leaves it out.
        exclusions: the run's excluded evidence roles.

    Returns:
        A payload holding only the ``docket_documents`` role.

    Raises:
        DocketError: an index the docket has never heard of.
        LeakageError: the guard found withheld text in a document.
    """
    context = view.attachment.context_for(indices).context
    evidence, _, _ = split_record(
        context, exclude=(_ALL_ROLES - {EvidenceRole.DOCKET_DOCUMENTS}) | exclusions
    )
    return Payload.from_evidence(evidence)


def answer_payload(
    view: DocketView, read: Sequence[int], exclusions: frozenset[EvidenceRole]
) -> Payload:
    """Arm B's payload shape for the refinement: the evidence, the listing, the documents read.

    The runner's stage 2 re-sends the payload stage 1 answered from, which for arm B holds every
    attached document (``scoring/runner.py``, ``prepare``). The same route: the attachment's
    context for ``read``, split once, rendered.

    Args:
        view: the case's prepared docket.
        read: the listing indices the agent read, in the order to render them; with none, the
            payload holds the evidence and the listing.
        exclusions: the run's excluded evidence roles.

    Returns:
        The payload.

    Raises:
        LeakageError: the guard found withheld text in the evidence, the listing or a document.
    """
    evidence, _, _ = split_record(view.attachment.context_for(read).context, exclude=exclusions)
    return Payload.from_evidence(evidence)


def case_marks(
    view: DocketView | None,
    raw: Mapping[str, object],
    read: Sequence[int],
    exclusions: frozenset[EvidenceRole],
) -> tuple[tuple[CaseMark, ...], float | None]:
    """The case's marks over every document read: bookkeeping, never sent to the model.

    One split over all the documents the agent read, as arm B's split is over all it attached,
    so the marks mean the same in both arms (S2.6, decisions 0077, 0078).

    Args:
        view: the case's prepared docket, or None when the case has no docket.
        raw: the case record the view was built from; checked to be that record.
        read: the listing indices the agent read.
        exclusions: the run's excluded evidence roles.

    Returns:
        The marks and the largest share of the factual narrative held by one document read;
        ``((), None)`` when there is no docket or nothing was read.

    Raises:
        ValueError: ``view`` was built from a different record than ``raw``.
        LeakageError: the guard found withheld text in the documents read.
    """
    if view is None or not read:
        return (), None
    if view.attachment.template.get("ntsbNumber") != raw.get("ntsbNumber"):
        raise ValueError("the docket view was built from another record")
    context = view.attachment.context_for(read).context
    evidence, _, _ = split_record(
        context, exclude=(_ALL_ROLES - {EvidenceRole.DOCKET_DOCUMENTS}) | exclusions
    )
    return evidence.marks, evidence.narrative_share
