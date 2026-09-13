from collections.abc import Mapping

import pytest
from tests.boundary import assert_boundary_holds

from ntsb_probable_cause import fields
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict


def test_boundary_holds_for_every_fixture(record_fixtures: list[dict[str, object]]) -> None:
    for raw in record_fixtures:
        assert_boundary_holds(raw)


def test_boundary_test_fails_when_the_splitter_leaks(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Mutation test: a splitter that copies the factual narrative into evidence must be caught."""

    def leaky_split(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
        evidence, synthesis, verdict = split_record(raw)
        leaked = evidence.model_copy(update={"prelim_narrative": synthesis.factual_narrative})
        return leaked, synthesis, verdict

    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    with pytest.raises(AssertionError, match=r"provenance|tripwire"):
        assert_boundary_holds(raw, leaky_split)


def test_boundary_test_fails_when_a_value_comes_from_the_wrong_place(
    record_fixtures: list[dict[str, object]],
) -> None:
    def swapped_split(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
        evidence, synthesis, verdict = split_record(raw)
        return (
            evidence.model_copy(update={"aircraft_make": "NOT FROM THE RECORD"}),
            synthesis,
            verdict,
        )

    with pytest.raises(AssertionError, match="provenance"):
        assert_boundary_holds(record_fixtures[0], swapped_split)


def test_boundary_test_fails_for_a_hand_built_evidence_carrying_withheld_text(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Mutation test: coverage does not depend on split_record's own construction path.

    A splitter that never calls ``split_record`` at all -- it builds an ``Evidence`` by hand,
    with withheld text placed directly in a free-text evidence role -- must still be caught.
    """

    def hand_built_split(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
        _, synthesis, verdict = split_record(raw)
        case_id = raw["ntsbNumber"]
        assert isinstance(case_id, str)
        assert synthesis.factual_narrative is not None
        evidence = Evidence(
            case_id=case_id,
            docket_url=None,
            prelim_narrative=synthesis.factual_narrative,
        )
        return evidence, synthesis, verdict

    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    with pytest.raises(AssertionError, match=r"provenance|tripwire"):
        assert_boundary_holds(raw, hand_built_split)
