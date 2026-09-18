"""attach_docket builds the case context; the split reads it unchanged (0041, 0042, 0044)."""

import copy
from collections.abc import Mapping

import pytest

from ntsb_probable_cause.docket.attach import (
    DOCKET_KEY,
    amateur_built_replace,
    attach_docket,
    header,
)
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole, factual_narrative
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.split import split_record


def _entry(index: int, title: str, pages: int = 3) -> ListingEntry:
    return ListingEntry(
        index=index,
        title=title,
        pages=pages,
        photos=0,
        doc_type="Report",
        extension="pdf",
        href="/x",
    )


def _docket(texts: Mapping[int, str]) -> Docket:
    titles = {
        1: "Powerplant Examination Report",
        2: "Party Submission - engine manufacturer",
        3: "Pilot Operator Report 6120",
    }
    records = []
    for index, title in titles.items():
        read = index in texts
        records.append(
            DocumentRecord(
                entry=_entry(index, title),
                category={1: "exam_site", 2: "party_submission", 3: "pilot_form_6120"}[index],
                status="read" if read else "unreadable: scan",
                pages=3,
                readable_pages=3 if read else 0,
                estimated_tokens=len(texts.get(index, "")) // 4,
                kind="born-digital" if read else "scan",
            )
        )
    listing = Listing(mkey=1, declared_items=3, entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=tuple(records), texts=dict(texts))


def test_context_carries_listing_and_selected_documents_under_the_docket_key(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = record_fixtures[0]
    docket = _docket(
        {1: "[page 1 of 3]\nThe crankshaft was intact.\n", 2: "[page 1 of 3]\nWe submit.\n"}
    )
    result = attach_docket(raw, docket, documents=[2])
    docket_part = result.context[DOCKET_KEY]
    assert isinstance(docket_part, dict)
    assert "1. Powerplant Examination Report" in str(docket_part["listing"])
    assert len(docket_part["documents"]) == 1
    assert "We submit." in docket_part["documents"][0]
    assert "crankshaft" not in docket_part["documents"][0]
    assert result.attached == (2,)
    assert result.not_available == ("3: unreadable: scan",)
    assert raw.get(DOCKET_KEY) is None, "the raw record is not mutated"


def test_split_reads_the_docket_roles_and_the_payload_renders_them(
    record_fixtures: list[dict[str, object]],
) -> None:
    docket = _docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    context = attach_docket(record_fixtures[0], docket, documents=[1]).context
    evidence, _, _ = split_record(context)
    assert evidence.docket_listing is not None
    assert evidence.docket_documents is not None
    assert len(evidence.docket_documents) == 1
    payload = Payload.from_evidence(evidence)
    assert "crankshaft" in payload.text
    assert "[page 1 of 3]" in payload.text


def test_excluding_the_documents_role_keeps_the_listing(
    record_fixtures: list[dict[str, object]],
) -> None:
    docket = _docket({1: "[page 1 of 3]\nx\n"})
    context = attach_docket(record_fixtures[0], docket, documents=[1]).context
    evidence, _, _ = split_record(context, exclude=frozenset({EvidenceRole.DOCKET_DOCUMENTS}))
    fields_sent = Payload.from_evidence(evidence).fields()
    assert "docket_listing" in fields_sent
    assert "docket_documents" not in fields_sent


def test_document_holding_a_withheld_sentence_fails_the_split_closed(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0038 item 3, 0039: the tripwire runs on every document."""
    raw = next(r for r in record_fixtures if factual_narrative(r))
    narrative = factual_narrative(raw) or ""
    docket = _docket({1: f"[page 1 of 3]\nAs the NTSB found: {narrative}\n"})
    context = attach_docket(raw, docket, documents=[1]).context
    with pytest.raises(LeakageError, match="docket_documents"):
        split_record(context)


def test_requesting_an_unreadable_document_leaves_it_unattached(
    record_fixtures: list[dict[str, object]],
) -> None:
    """A requested index that turns out not to be ``read`` is skipped, not attached blank."""
    docket = _docket({1: "[page 1 of 3]\nx\n"})
    result = attach_docket(record_fixtures[0], docket, documents=[3])
    assert result.attached == ()
    assert result.context[DOCKET_KEY]["documents"] == []  # type: ignore[index]
    assert result.not_available == ("2: unreadable: scan", "3: unreadable: scan")


def test_header_names_type_pages_and_author_role() -> None:
    record = _docket({2: "x"}).record(2)
    assert header(record) == "Party submission, 3 pages, submitted by a party to the investigation."
    exam = _docket({1: "x"}).record(1)
    assert header(exam) == "Examination or site report, 3 pages, NTSB or its investigators."


def test_amateur_built_make_and_model_are_replaced_in_text_and_counted(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "Invented Builder"
    aircrafts[0]["aircraftModel"] = "RV-7X"
    text, count = amateur_built_replace(
        "The INVENTED BUILDER rv-7x was built by Invented Builder.", raw
    )
    assert text == "The Amateur-built Amateur-built was built by Amateur-built."
    assert count == 3
    docket = _docket({1: "[page 1 of 3]\nInvented Builder logbook.\n"})
    result = attach_docket(raw, docket, documents=[1])
    assert "Invented Builder" not in str(result.context[DOCKET_KEY])
    assert result.replacements == 1


def test_no_replacement_on_a_factory_built_aircraft(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = record_fixtures[0]
    make = raw["aircrafts"][0]["aircraftMake"]  # type: ignore[index]
    text, count = amateur_built_replace(f"A {make} aircraft.", raw)
    assert count == 0
    assert make in text


def test_a_too_short_or_missing_make_or_model_is_never_used_as_a_replacement_pattern(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0044's floor: a value under the minimum length, or absent, is skipped, not
    turned into a pattern that would match nearly anything.
    """
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "NX"
    aircrafts[0]["aircraftModel"] = None
    text, count = amateur_built_replace("An NX aircraft, model unknown.", raw)
    assert count == 0
    assert text == "An NX aircraft, model unknown."
