"""The development shape scan: counts and quantiles only (spec §8.1)."""

from scripts.docket_scan import ShapeState, accumulate, owner_names, quantiles, report
from tests.test_attach import _docket as small_docket


def test_quantiles_are_nearest_rank() -> None:
    assert quantiles([1, 2, 3, 4]) == {0.5: 2, 0.75: 3, 0.9: 4, 1.0: 4}
    assert quantiles([]) == {}


def test_owner_names_reuses_the_attach_modules_selection_rule() -> None:
    """Correction 1 (decision 0046): the floor is 3 characters and a bare digit string is
    excluded regardless of field name -- not a 4-character floor with a name-based "zip"
    exclusion. ``ownerZip`` here is a bare 5-digit postcode (excluded by the digit rule, not
    because its key name contains "zip"), and ``operatorName`` is too short at 2 characters.
    """
    raw = {
        "aircrafts": [
            {
                "ownerOperators": [
                    {
                        "registeredOwner": "Example Flying Club",
                        "ownerZip": "54321",
                        "operatorName": "Ab",
                    }
                ]
            }
        ]
    }
    assert owner_names(raw) == ["Example Flying Club"]


def test_owner_names_keeps_a_hyphenated_postcode_in_scope() -> None:
    """Decision 0046 item 5: a ZIP+4 is distinctive and is still replaced, unlike a bare
    digit string -- so it must still be counted here.
    """
    raw = {"aircrafts": [{"ownerOperators": [{"ownerZip": "54321-6789"}]}]}
    assert owner_names(raw) == ["54321-6789"]


def test_accumulate_counts_documents_pages_tokens_and_names() -> None:
    state = ShapeState()
    docket = small_docket(
        {1: "[page 1 of 3]\nExample Flying Club report.\n", 2: "[page 1 of 3]\nx\n"}
    )
    raw = {"aircrafts": [{"ownerOperators": [{"registeredOwner": "Example Flying Club"}]}]}
    accumulate(state, docket, fatal=True, raw=raw)
    text = report(state)
    assert "documents per docket" in text
    assert "fatal" in text
    assert "non-fatal" in text
    assert "owner or operator name" in text
    assert state.name_hits["fatal/exam_site"] == 1
    assert state.dockets["fatal"] == 1


def test_accumulate_counts_amateur_built_and_owner_operator_replacements_separately() -> None:
    """Correction 2: ``AttachResult.replacements`` (and this scan) now carries two mechanisms
    -- the amateur-built make/model and the owner/operator details (decision 0046). Both must
    be measured; neither may be reported under the old single "amateur-built replacements"
    label with the other mechanism's hits silently folded in or dropped.
    """
    state = ShapeState()
    docket = small_docket({1: "[page 1 of 3]\nInvented Builder logbook signed by Jordan Vale.\n"})
    raw = {
        "aircrafts": [
            {
                "aircraftAmateurBuilt": True,
                "aircraftMake": "Invented Builder",
                "aircraftModel": "RV-7X",
                "ownerOperators": [{"registeredOwner": "Jordan Vale"}],
            }
        ]
    }
    accumulate(state, docket, fatal=False, raw=raw)
    assert state.amateur_built_replacements["non-fatal/exam_site"] == 1
    assert state.owner_operator_replacements["non-fatal/exam_site"] == 1
    text = report(state)
    assert "amateur-built replacements, by category" in text
    assert "owner or operator name replacements, by category" in text
