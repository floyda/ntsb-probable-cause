"""attach_docket builds the case context; the split reads it unchanged (0041, 0042, 0044)."""

import copy
from collections.abc import Mapping

import pytest

from ntsb_probable_cause.docket.attach import (
    DOCKET_KEY,
    amateur_built_replace,
    attach_docket,
    header,
    redact_known_names,
)
from ntsb_probable_cause.docket.classify import CATEGORIES
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.errors import DocketError, LeakageError
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

    # Fix round 1, finding 2: the top-level check above only proves no key was added; it
    # would still pass if the copy were shallow and a nested structure were shared. Mutate a
    # nested structure inside the returned context and confirm the original record is unaffected.
    original_make = raw["aircrafts"][0]["aircraftMake"]  # type: ignore[index]
    context_aircrafts = result.context["aircrafts"]
    assert isinstance(context_aircrafts, list)
    context_aircrafts[0]["aircraftMake"] = "MUTATED-VIA-CONTEXT"
    assert raw["aircrafts"][0]["aircraftMake"] == original_make  # type: ignore[index]


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


# The former category labels (decision 0051), quoted here only as a regression guard --
# decision 0055 removed them from the header, and this list has no other purpose than
# proving none of the twelve reappears in a rendered header.
_FORMER_LABELS = (
    "Party submission",
    "Pilot/operator accident report form",
    "Photographs",
    "Weather study or data",
    "Maintenance records",
    "Medical or toxicology report",
    "Specialist factual report",
    "Examination or site report",
    "Statement or record of conversation",
    "Air traffic, radar or recorded data",
    "Manual or reference excerpt",
    "Docket document",
)


def test_header_names_the_listing_index_and_pages_with_no_clause_when_fully_readable() -> None:
    """Decision 0055: a fully readable document's header ends after the page count."""
    record = _docket({2: "x"}).record(2)
    assert header(record) == "Docket item 2, 3 pages."
    exam = _docket({1: "x"}).record(1)
    assert header(exam) == "Docket item 1, 3 pages."


def test_header_reports_the_readable_page_count_when_partly_readable() -> None:
    """Decision 0055: what was readable follows the listing index and page count."""
    entry = _entry(1, "Partly scanned report", pages=11)
    record = DocumentRecord(
        entry=entry,
        category="exam_site",
        status="read",
        pages=11,
        readable_pages=4,
        estimated_tokens=100,
        kind="partial",
    )
    assert header(record) == "Docket item 1, 11 pages, of which 4 held readable text."


def test_header_uses_singular_page_for_a_one_page_document() -> None:
    entry = _entry(7, "One-page memo", pages=1)
    record = DocumentRecord(
        entry=entry,
        category="exam_site",
        status="read",
        pages=1,
        readable_pages=1,
        estimated_tokens=1,
        kind="born-digital",
    )
    assert header(record) == "Docket item 7, 1 page."


def test_no_header_carries_any_of_the_twelve_former_category_labels() -> None:
    """Decision 0055: the header's identifier is the listing index, not a title-inferred
    category label. Rendered for every category, at both a fully readable and a partly
    readable page count, no header may contain any of the labels that used to appear."""
    categories = {name for name, _pattern in CATEGORIES} | {"other"}
    for category in categories:
        for pages, readable_pages in ((3, 3), (11, 4)):
            entry = _entry(1, "Some document", pages=pages)
            record = DocumentRecord(
                entry=entry,
                category=category,
                status="read",
                pages=pages,
                readable_pages=readable_pages,
                estimated_tokens=100,
                kind="born-digital" if pages == readable_pages else "partial",
            )
            rendered = header(record)
            assert "Docket item 1" in rendered
            for label in _FORMER_LABELS:
                assert label not in rendered, (category, rendered)


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


def test_amateur_built_replacement_does_not_corrupt_an_ordinary_word(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Fix round 1, finding 1: an unanchored pattern would turn "longitudinal" into a leak."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "Long"
    aircrafts[0]["aircraftModel"] = "Invented Two-Seater"
    text, count = amateur_built_replace("The longitudinal axis was undamaged.", raw)
    assert count == 0
    assert text == "The longitudinal axis was undamaged."


def test_amateur_built_replacement_still_matches_the_standalone_make(
    record_fixtures: list[dict[str, object]],
) -> None:
    """The word-boundary anchoring still catches the surname on its own."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "Long"
    aircrafts[0]["aircraftModel"] = "Invented Two-Seater"
    text, count = amateur_built_replace("A Long aircraft was examined at the site.", raw)
    assert count == 1
    assert text == "A Amateur-built aircraft was examined at the site."


def test_record_raises_docket_error_for_an_index_the_docket_does_not_hold() -> None:
    """Fix round 1, finding 3: a missing index is a clean DocketError, not a bare StopIteration."""
    docket = _docket({1: "x"})
    with pytest.raises(DocketError, match="99"):
        docket.record(99)


def test_attach_docket_surfaces_a_missing_index_as_a_docket_error(
    record_fixtures: list[dict[str, object]],
) -> None:
    """The same failure, seen from attach_docket, which calls Docket.record per requested index."""
    docket = _docket({1: "x"})
    with pytest.raises(DocketError, match="99"):
        attach_docket(record_fixtures[0], docket, documents=[99])


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


def test_owner_named_as_two_words_is_replaced_in_a_document_and_counted(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0046: the recorded owner string, an invented name here, is replaced whole."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [{"registeredOwner": "Jordan Vale"}]
    text, count = redact_known_names("The report was signed by Jordan Vale on site.", raw)
    assert text == "The report was signed by Owner or operator on site."
    assert count == 1


def test_operator_name_is_replaced_in_the_listing_and_in_a_document(
    record_fixtures: list[dict[str, object]],
) -> None:
    """redact_known_names is applied to the rendered listing as well as to document text."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [{"operatorName": "Rimrock Aviation"}]
    entry = _entry(1, "Rimrock Aviation - Party Submission")
    record = DocumentRecord(
        entry=entry,
        category="party_submission",
        status="read",
        pages=3,
        readable_pages=3,
        estimated_tokens=10,
        kind="born-digital",
    )
    listing = Listing(mkey=1, declared_items=1, entries=(entry,))
    docket = Docket(
        mkey=1,
        listing=listing,
        documents=(record,),
        texts={1: "[page 1 of 3]\nRimrock Aviation submits this report.\n"},
    )
    result = attach_docket(raw, docket, documents=[1])
    docket_part = result.context[DOCKET_KEY]
    assert isinstance(docket_part, dict)
    assert "Rimrock Aviation" not in str(docket_part)
    assert "Owner or operator" in str(docket_part["listing"])
    assert "Owner or operator" in docket_part["documents"][0]


def test_a_name_embedded_in_an_ordinary_word_is_not_replaced(
    record_fixtures: list[dict[str, object]],
) -> None:
    """The word-boundary property carried from amateur_built_replace."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [{"operatorIndividual": "Long"}]
    text, count = redact_known_names("The longitudinal axis was undamaged.", raw)
    assert count == 0
    assert text == "The longitudinal axis was undamaged."


def test_the_surname_alone_is_not_replaced_when_only_the_full_string_is_recorded(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0046 item 2: the full recorded string only, never its parts."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [{"registeredOwner": "Jordan Vale"}]
    text, count = redact_known_names("Mr. Vale inspected the wreckage.", raw)
    assert count == 0
    assert text == "Mr. Vale inspected the wreckage."


def test_a_malformed_owner_operator_entry_is_skipped_not_raised(
    record_fixtures: list[dict[str, object]],
) -> None:
    """A non-dict entry in ownerOperators (a malformed record) is ignored, not an error."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = ["not a dict", {"registeredOwner": "Jordan Vale"}]
    text, count = redact_known_names("Jordan Vale filed the report.", raw)
    assert text == "Owner or operator filed the report."
    assert count == 1


def test_names_from_a_second_aircraft_and_a_second_owner_operator_entry_are_both_replaced(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Unlike amateur_built_replace, every aircraft and every ownerOperators entry is read."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    first = copy.deepcopy(aircrafts[0])
    second = copy.deepcopy(aircrafts[0])
    first["ownerOperators"] = [
        {"registeredOwner": "Jordan Vale"},
        {"operatorName": "Rimrock Aviation"},
    ]
    second["ownerOperators"] = [{"registeredOwner": "Priya Okafor"}]
    raw["aircrafts"] = [first, second]
    text, count = redact_known_names(
        "Jordan Vale, on behalf of Rimrock Aviation, flew with Priya Okafor.", raw
    )
    assert text == "Owner or operator, on behalf of Owner or operator, flew with Owner or operator."
    assert count == 3


def test_a_trading_name_containing_the_operator_name_is_replaced_whole_not_in_pieces(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Longest value first: no fragment of the trading name is left behind."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [
        {"operatorName": "Rimrock Aviation"},
        {"operatorDoingBusinessAs": "Rimrock Aviation Flight School"},
    ]
    text, count = redact_known_names("Rimrock Aviation Flight School operated the flight.", raw)
    assert text == "Owner or operator operated the flight."
    assert count == 1


def test_a_bare_digit_postcode_does_not_replace_a_matching_number_in_text(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0046 item 5: a bare digit string is never used as a replacement pattern."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [{"ownerZip": "54321"}]
    text, count = redact_known_names("The serial number was 54321.", raw)
    assert count == 0
    assert text == "The serial number was 54321."


def test_a_hyphenated_postcode_is_still_replaced(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0046 item 5: a ZIP+4 is distinctive, unlike a bare digit string, and stays in
    scope."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [{"ownerZip": "54321-6789"}]
    text, count = redact_known_names("The postcode on file was 54321-6789.", raw)
    assert count == 1
    assert text == "The postcode on file was Owner or operator."


def test_replacement_order_is_deterministic_for_two_equal_length_overlapping_values(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Fix round 1, finding 2: with two equal-length values whose matches in the text overlap
    (here, on the shared word "Aviation"), the tie-break must be pinned, not left to `set`
    iteration order -- otherwise which one wins, and so the resulting text, is non-reproducible.
    """
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [
        {"registeredOwner": "North Aviation"},
        {"operatorName": "Aviation Group"},
    ]
    text, count = redact_known_names("North Aviation Group operated the flight.", raw)
    assert count == 1
    assert text == "North Owner or operator operated the flight."


def test_no_replacement_when_the_record_holds_no_owner_or_operator_names(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Fixture records are already redacted of these fields (decision 0015): none to find."""
    raw = record_fixtures[0]
    text, count = redact_known_names("Nothing here identifies anyone.", raw)
    assert count == 0
    assert text == "Nothing here identifies anyone."


def test_owner_operator_replacement_count_adds_to_the_amateur_built_count(
    record_fixtures: list[dict[str, object]],
) -> None:
    """The two mechanisms count separately; neither replaces the other's count."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "Invented Builder"
    aircrafts[0]["aircraftModel"] = "RV-7X"
    aircrafts[0]["ownerOperators"] = [{"registeredOwner": "Jordan Vale"}]
    docket = _docket({1: "[page 1 of 3]\nInvented Builder logbook signed by Jordan Vale.\n"})
    result = attach_docket(raw, docket, documents=[1])
    assert result.replacements == 2
    docket_part = result.context[DOCKET_KEY]
    assert "Invented Builder" not in str(docket_part)
    assert "Jordan Vale" not in str(docket_part)
