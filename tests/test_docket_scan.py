"""The development shape scan: counts and quantiles only (spec §8.1)."""

from scripts.docket_scan import (
    ShapeState,
    _fmt_count,
    accumulate,
    owner_names,
    quantiles,
    record_attempt,
    record_listing_failed,
    record_missing_mkey,
    report,
)
from tests.test_attach import _docket as small_docket


def test_quantiles_are_nearest_rank() -> None:
    assert quantiles([1, 2, 3, 4]) == {0.5: 2, 0.75: 3, 0.9: 4, 1.0: 4}
    assert quantiles([]) == {}


def test_quantiles_round_up_at_a_half_integer_rank() -> None:
    """Fix round 1, finding 4: nearest-rank is ``math.ceil(q * n)``, not half-to-even
    ``round``, which silently returns one rank low at a half-integer rank with an even floor.
    """
    assert quantiles(list(range(1, 6)), qs=(0.9,)) == {0.9: 5}
    assert quantiles(list(range(1, 151)), qs=(0.75,)) == {0.75: 113}


def test_fmt_count_never_renders_scientific_notation() -> None:
    """Also from the final review's smaller findings: ``:g`` switches a value at or above
    1,000,000 to scientific notation (``1.23457e+06``), which is exactly what makes a reader
    distrust a published results file. A thousands-separated integer instead."""
    assert _fmt_count(1_234_567) == "1,234,567"
    assert _fmt_count(500) == "500"


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
    assert "owner or operator detail" in text
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
    assert "owner or operator detail replacements, by category" in text


def test_report_states_the_denominator_a_reader_needs_to_trust_the_numbers() -> None:
    """Fix round 1, finding 1: a reader cannot tell a complete run from a broken one unless the
    report says how many cases were attempted and how many of those never became a docket.
    """
    state = ShapeState()
    record_attempt(state, fatal=True)
    record_attempt(state, fatal=True)
    record_missing_mkey(state, fatal=True)
    record_attempt(state, fatal=False)
    record_listing_failed(state, fatal=False)
    text = report(state)
    assert "cases attempted: 2; listing fetch failed: 0; skipped for missing mKey: 1" in text
    assert "cases attempted: 1; listing fetch failed: 1; skipped for missing mKey: 0" in text
    assert "cases attempted: 3; listing fetch failed: 1; skipped for missing mKey: 1" in text


def test_report_states_definitions_and_limits() -> None:
    """Fix round 1, finding 2: the name figures, "containing" vs. "replaced", the token sum,
    and "scanned pages" each need one plain sentence saying exactly what they measure.
    """
    text = report(ShapeState())
    assert "## Definitions and limits" in text
    assert "counted only over documents whose text was extracted" in text
    assert "not the same measurement" in text
    assert "characters-divided-by-four floor" in text
    # Task 14 review, correction 6: the sentence must describe what the code at the
    # `state.scan_pages` line actually sums -- pages minus readable pages over every
    # document with a known kind, not only whole scan-classified documents.
    assert '"Scanned pages" sums pages minus readable pages' in text
    assert "individually-unreadable pages inside a partial-classified one" in text
