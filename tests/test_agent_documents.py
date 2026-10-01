"""Tests for ``agent/documents.py``: the only place the agent turns a record and its docket into
model-bound payloads (S3.1 Task 7).

Every payload is ``Payload.from_evidence(split_record(...))`` (decision 0016): the first user
message is the evidence without the docket, the listing and each document read arrive apart, and
a leak in any of them raises ``LeakageError`` for the loop to turn into ``failed: leak``.
"""

import copy
import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError

import pytest
from tests.conftest import FIXTURES
from tests.test_attach import _docket as small_docket

from ntsb_probable_cause.agent.documents import (
    DocketView,
    answer_payload,
    case_marks,
    docket_view,
    documents_payload,
    evidence_payload,
    listing_payload,
)
from ntsb_probable_cause.agent.facts import DocumentFacts
from ntsb_probable_cause.agent.texts import menu
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.samples import arm_exclusions

NO_EXCLUSIONS: frozenset[EvidenceRole] = frozenset()
TITLES = (
    "Powerplant Examination Report",
    "Party Submission - engine manufacturer",
    "Pilot Operator Report 6120",
)
ONE = "[page 1 of 3]\nThe crankshaft was intact and turned freely.\n"
TWO = "[page 1 of 3]\nWe submit this statement on behalf of the engine manufacturer.\n"

FACTUAL = (
    "The airplane departed from runway 27 at 0915. "
    "Witnesses observed the airplane climb to about 300 feet. "
    "The engine then lost power and the airplane descended into a field. "
    "The pilot reported that the fuel selector was positioned to the left tank."
)
S1, S2, _S3, _S4 = (s.strip() for s in FACTUAL.split(". "))
QUOTED = (
    "Examination of the engine revealed no mechanical anomalies"
    " that would have precluded normal operation."
)
ANALYSIS = QUOTED + " The fuel selector was found positioned to an empty tank."
CAUSE = (
    "The pilot's improper fuel management, which resulted in a loss of engine power due to"
    " fuel starvation."
)


def _raw() -> dict[str, object]:
    """The ANC09CA024 development fixture: a real record, redacted of owner and operator."""
    raw = json.loads((FIXTURES / "records" / "ANC09CA024.json").read_text())["record"]
    assert raw["ntsbNumber"] == "ANC09CA024"
    assert isinstance(raw, dict)
    return raw


def _withheld(raw: dict[str, object]) -> dict[str, object]:
    """A copy whose narratives hold text the guard can match (as tests/test_marks.py does)."""
    raw = copy.deepcopy(raw)
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["concatenatedFactualNarrative"] = FACTUAL
    narratives[0]["analysisNarrative"] = ANALYSIS
    narratives[0]["probableCause"] = CAUSE
    return raw


def _view(raw: dict[str, object] | None = None) -> DocketView:
    return docket_view(raw or _raw(), small_docket({1: ONE, 2: TWO}))


class TestDocketView:
    def test_offers_the_read_documents_smallest_first_with_their_facts(self) -> None:
        short, long = "[page 1 of 3]\nShort.\n", "[page 1 of 3]\n" + "A long statement. " * 80
        view = docket_view(_raw(), small_docket({1: long, 2: short}))
        assert [f.index for f in view.offered] == [2, 1]
        assert view.offered[0] == DocumentFacts(
            index=2,
            pages=3,
            readable_pages=3,
            estimated_tokens=len(short) // 4,
            kind="born-digital",
            status="read",
        )
        assert view.offered[1].estimated_tokens == len(long) // 4

    def test_equal_sizes_break_by_listing_index(self) -> None:
        view = docket_view(_raw(), small_docket({1: ONE, 2: ONE}))
        assert [f.index for f in view.offered] == [1, 2]

    def test_lists_every_document_that_is_not_read_as_not_readable(self) -> None:
        view = _view()
        assert view.not_readable == (
            DocumentFacts(
                index=3,
                pages=3,
                readable_pages=0,
                estimated_tokens=0,
                kind="scan",
                status="unreadable: scan",
            ),
        )
        assert {f.index for f in view.offered}.isdisjoint(f.index for f in view.not_readable)

    def test_a_docket_with_nothing_readable_offers_nothing(self) -> None:
        view = docket_view(_raw(), small_docket({}))
        assert view.offered == ()
        assert [f.index for f in view.not_readable] == [1, 2, 3]

    def test_is_a_frozen_record(self) -> None:
        view = _view()
        with pytest.raises(FrozenInstanceError):
            view.offered = ()  # type: ignore[misc]

    def test_the_menu_built_from_it_holds_no_title(self) -> None:
        view = _view()
        text = menu(view.offered, view.not_readable)
        for title in TITLES:
            assert title not in text
        assert "[1] 3 pages, 3 with a text layer, about" in text
        assert "Not readable: [3] 3 pages" in text


class TestEvidencePayload:
    def test_holds_the_evidence_and_no_docket_key(self) -> None:
        fields = evidence_payload(_raw(), NO_EXCLUSIONS).fields()
        assert fields["aircraft_make"] == "CESSNA"
        assert "docket_listing" not in fields
        assert "docket_documents" not in fields

    def test_drops_a_docket_subtree_the_record_carries(self) -> None:
        raw = _raw()
        raw["docket"] = {
            "listing": "1. A Title",
            "documents": ["Some document text."],
            "attached": [1],
        }
        payload = evidence_payload(raw, NO_EXCLUSIONS)
        assert "A Title" not in payload.text
        assert "Some document text." not in payload.text
        assert "docket_listing" not in payload.fields()
        assert "docket_documents" not in payload.fields()
        assert "docket" in raw, "the record is not mutated"

    def test_is_a_payload_built_from_the_split(self) -> None:
        assert isinstance(evidence_payload(_raw(), NO_EXCLUSIONS), Payload)

    def test_an_exclusion_removes_its_role(self) -> None:
        with_role = evidence_payload(_raw(), NO_EXCLUSIONS).fields()
        assert "weather_condition" in with_role
        fields = evidence_payload(_raw(), frozenset({EvidenceRole.WEATHER_CONDITION})).fields()
        assert "weather_condition" not in fields
        assert fields["aircraft_make"] == "CESSNA"

    def test_arm_a_exclusions_leave_the_start_facts_only(self) -> None:
        fields = evidence_payload(_raw(), arm_exclusions("A")).fields()
        assert set(fields) == {
            "aircraft_make",
            "aircraft_model",
            "engine_type",
            "injury_level",
            "phase_of_flight",
            "registration",
        }

    def test_a_leak_in_the_evidence_raises(self) -> None:
        raw = _withheld(_raw())
        narratives = raw["narratives"]
        assert isinstance(narratives, list)
        narratives[0]["prelimNarrative"] = f"Report. {CAUSE}"
        with pytest.raises(LeakageError):
            evidence_payload(raw, NO_EXCLUSIONS)


class TestListingPayload:
    def test_holds_only_the_listing_and_every_title(self) -> None:
        payload = listing_payload(_view(), NO_EXCLUSIONS)
        assert set(payload.fields()) == {"docket_listing"}
        for title in TITLES:
            assert title in payload.text

    def test_holds_no_evidence_field_and_no_document_text(self) -> None:
        text = listing_payload(_view(), NO_EXCLUSIONS).text
        assert "CESSNA" not in text
        assert "crankshaft" not in text
        assert "We submit" not in text

    def test_excluding_the_listing_role_empties_the_payload(self) -> None:
        payload = listing_payload(_view(), frozenset({EvidenceRole.DOCKET_LISTING}))
        assert payload.fields() == {}

    def test_a_leak_in_a_title_raises(self) -> None:
        raw = _withheld(_raw())
        docket = small_docket({1: ONE})
        entry = docket.listing.entries[0].model_copy(update={"title": f"Letter. {CAUSE}"})
        listing = docket.listing.model_copy(
            update={"entries": (entry, *docket.listing.entries[1:])}
        )
        view = docket_view(raw, docket.model_copy(update={"listing": listing}))
        with pytest.raises(LeakageError):
            listing_payload(view, NO_EXCLUSIONS)


class TestDocumentsPayload:
    def test_one_index_holds_only_that_documents_rendered_text(self) -> None:
        payload = documents_payload(_view(), (1,), NO_EXCLUSIONS)
        assert set(payload.fields()) == {"docket_documents"}
        rendered = payload.fields()["docket_documents"]
        assert rendered == [f"Docket item 1, 3 pages.\n{ONE}"]
        assert "We submit" not in payload.text

    def test_holds_no_listing_title_and_no_evidence_field(self) -> None:
        text = documents_payload(_view(), (1, 2), NO_EXCLUSIONS).text
        for title in TITLES:
            assert title not in text
        assert "CESSNA" not in text

    def test_several_indices_are_rendered_in_the_order_given(self) -> None:
        rendered = documents_payload(_view(), (2, 1), NO_EXCLUSIONS).fields()["docket_documents"]
        assert rendered == [f"Docket item 2, 3 pages.\n{TWO}", f"Docket item 1, 3 pages.\n{ONE}"]

    def test_a_document_that_cannot_be_read_is_not_attached(self) -> None:
        """Nothing attached is an empty payload; the loop sends one only after a read."""
        assert documents_payload(_view(), (3,), NO_EXCLUSIONS).fields() == {}
        mixed = documents_payload(_view(), (3, 1), NO_EXCLUSIONS).fields()["docket_documents"]
        assert mixed == [f"Docket item 1, 3 pages.\n{ONE}"]

    def test_an_index_the_docket_lacks_raises(self) -> None:
        with pytest.raises(DocketError):
            documents_payload(_view(), (9,), NO_EXCLUSIONS)

    def test_consecutive_calls_do_not_carry_state(self) -> None:
        view = _view()
        first = documents_payload(view, (1,), NO_EXCLUSIONS)
        listing = listing_payload(view, NO_EXCLUSIONS)
        second = documents_payload(view, (2,), NO_EXCLUSIONS)
        assert "crankshaft" not in second.text
        assert documents_payload(view, (1,), NO_EXCLUSIONS) == first
        assert listing_payload(view, NO_EXCLUSIONS) == listing

    def test_excluding_the_documents_role_empties_the_payload(self) -> None:
        payload = documents_payload(_view(), (1,), frozenset({EvidenceRole.DOCKET_DOCUMENTS}))
        assert payload.fields() == {}

    def test_a_leak_in_a_document_raises(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: ONE, 2: f"[page 1 of 3]\nLetter.\n{CAUSE}\n"}))
        assert isinstance(documents_payload(view, (1,), NO_EXCLUSIONS), Payload)
        with pytest.raises(LeakageError, match="docket_documents"):
            documents_payload(view, (2,), NO_EXCLUSIONS)

    def test_the_whole_narrative_in_a_document_raises(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: f"[page 1 of 3]\n{FACTUAL}\n"}))
        with pytest.raises(LeakageError, match="text from factual_narrative"):
            documents_payload(view, (1,), NO_EXCLUSIONS)

    def test_an_analysis_sentence_reaches_the_agent(self) -> None:
        """Decision 0077: a docket sentence shared with the analysis is marked, not refused."""
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: f"[page 1 of 3]\n{QUOTED}\n"}))
        assert "no mechanical anomalies" in documents_payload(view, (1,), NO_EXCLUSIONS).text


class TestAnswerPayload:
    """Arm B's payload shape, for the refinement (Task 8, fix round 1)."""

    def test_holds_the_evidence_the_listing_and_the_documents_read(self) -> None:
        payload = answer_payload(_view(), (1,), NO_EXCLUSIONS)
        fields = payload.fields()
        assert fields["aircraft_make"] == "CESSNA"
        assert all(title in payload.text for title in TITLES)
        assert fields["docket_documents"] == [f"Docket item 1, 3 pages.\n{ONE}"]
        assert "We submit" not in payload.text

    def test_is_arm_bs_split_of_the_attachments_context(self) -> None:
        view = _view()
        context = view.attachment.context_for((1, 2)).context
        expected = Payload.from_evidence(split_record(context, exclude=NO_EXCLUSIONS)[0])
        assert answer_payload(view, (1, 2), NO_EXCLUSIONS) == expected

    def test_with_nothing_read_holds_the_listing_and_no_documents(self) -> None:
        fields = answer_payload(_view(), (), NO_EXCLUSIONS).fields()
        assert "docket_listing" in fields
        assert "docket_documents" not in fields
        assert fields["aircraft_make"] == "CESSNA"

    def test_an_exclusion_removes_its_role(self) -> None:
        excluded = frozenset({EvidenceRole.WEATHER_CONDITION})
        assert "weather_condition" not in answer_payload(_view(), (1,), excluded).fields()

    def test_a_leak_in_a_document_raises(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: ONE, 2: f"[page 1 of 3]\nLetter.\n{CAUSE}\n"}))
        assert isinstance(answer_payload(view, (1,), NO_EXCLUSIONS), Payload)
        with pytest.raises(LeakageError):
            answer_payload(view, (2,), NO_EXCLUSIONS)


class TestOnePayloadRoute:
    def test_every_payload_comes_from_split_record_with_its_roles_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exclusions each function hands the split are the ones its payload depends on."""
        calls: list[frozenset[EvidenceRole]] = []

        def spy(
            raw: Mapping[str, object], *, exclude: frozenset[EvidenceRole]
        ) -> tuple[Evidence, Synthesis, Verdict]:
            calls.append(exclude)
            return split_record(raw, exclude=exclude)

        monkeypatch.setattr("ntsb_probable_cause.agent.documents.split_record", spy)
        view = _view()
        evidence_payload(_raw(), NO_EXCLUSIONS)
        listing_payload(view, NO_EXCLUSIONS)
        documents_payload(view, (1,), NO_EXCLUSIONS)
        answer_payload(view, (1,), NO_EXCLUSIONS)
        docket_roles = {EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS}
        everything = set(EvidenceRole)
        assert calls == [
            frozenset(docket_roles),
            frozenset(everything - {EvidenceRole.DOCKET_LISTING}),
            frozenset(everything - {EvidenceRole.DOCKET_DOCUMENTS}),
            NO_EXCLUSIONS,
        ]


class TestCaseMarks:
    def test_nothing_read_gives_no_marks_and_no_share(self) -> None:
        assert case_marks(_view(), _raw(), (), NO_EXCLUSIONS) == ((), None)

    def test_no_docket_gives_no_marks_and_no_share(self) -> None:
        assert case_marks(None, _raw(), (1,), NO_EXCLUSIONS) == ((), None)

    def test_half_the_narrative_in_one_document_marks_the_case(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: f"{S1}. {S2}.", 2: "Nothing shared here."}))
        marks, share = case_marks(view, raw, (1, 2), NO_EXCLUSIONS)
        assert marks == (CaseMark(kind="narrative_coverage", count=1),)
        assert share == 0.5

    def test_only_the_documents_read_count(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: f"{S1}. {S2}.", 2: "Nothing shared here."}))
        assert case_marks(view, raw, (2,), NO_EXCLUSIONS) == ((), 0.0)

    def test_an_analysis_sentence_is_marked(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: f"[page 1 of 3]\n{QUOTED}\n"}))
        marks, _ = case_marks(view, raw, (1,), NO_EXCLUSIONS)
        assert CaseMark(kind="analysis_sentence", count=1) in marks

    def test_a_leak_propagates(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: f"[page 1 of 3]\nLetter.\n{CAUSE}\n"}))
        with pytest.raises(LeakageError):
            case_marks(view, raw, (1,), NO_EXCLUSIONS)

    def test_excluding_the_documents_role_gives_no_marks(self) -> None:
        raw = _withheld(_raw())
        view = docket_view(raw, small_docket({1: f"{S1}. {S2}."}))
        excluded = frozenset({EvidenceRole.DOCKET_DOCUMENTS})
        assert case_marks(view, raw, (1,), excluded) == ((), None)

    def test_refuses_a_view_built_for_another_record(
        self, record_fixtures: list[dict[str, object]]
    ) -> None:
        other = next(r for r in record_fixtures if r["ntsbNumber"] != "ANC09CA024")
        with pytest.raises(ValueError, match="another record"):
            case_marks(_view(), other, (1,), NO_EXCLUSIONS)
