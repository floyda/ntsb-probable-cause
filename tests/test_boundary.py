import copy
from collections.abc import Mapping

import pytest
from tests.boundary import assert_boundary_holds

from ntsb_probable_cause import fields
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records import split as split_module
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict


def test_boundary_holds_for_every_fixture(record_fixtures: list[dict[str, object]]) -> None:
    for raw in record_fixtures:
        assert_boundary_holds(raw)


def test_boundary_holds_and_hides_the_builder_name_for_amateur_built_aircraft(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0020: an invented builder name in aircraftMake never reaches the payload."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "INVENTED BUILDER"

    assert_boundary_holds(raw)

    evidence, _, _ = split_record(raw)
    payload = Payload.from_evidence(evidence)
    assert "INVENTED BUILDER" not in payload.text


def test_boundary_test_fails_when_the_splitter_leaks(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Mutation test: a splitter that copies the factual narrative into evidence must be caught."""

    def leaky_split(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
        evidence, synthesis, verdict = split_record(raw)
        leaked = evidence.model_copy(update={"prelim_narrative": synthesis.factual_narrative})
        return leaked, synthesis, verdict

    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    with pytest.raises(AssertionError, match=r"^provenance"):
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

    with pytest.raises(AssertionError, match=r"^provenance"):
        assert_boundary_holds(record_fixtures[0], swapped_split)


def test_boundary_fails_when_only_the_tripwire_can_catch_a_leak(
    record_fixtures: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation test: prove the tripwire layer itself can fail, not just provenance.

    The other two mutation tests above both fail on provenance, because their mutated evidence
    disagrees with what the real extractor reads from the raw record. This test mutates the raw
    record itself so an evidence extractor's own faithful reading equals the record's probable
    cause -- provenance holds -- and disables ``split_record``'s own leakage guard, so only
    ``assert_boundary_holds``'s tripwire block can catch the leak.
    """
    raw = next(r for r in record_fixtures if fields.probable_cause(r))
    mutated = copy.deepcopy(raw)
    aircrafts = mutated["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftMake"] = fields.probable_cause(raw)

    monkeypatch.setattr(split_module, "find_leaks", lambda *_a, **_k: [])

    with pytest.raises(AssertionError, match=r"^tripwire"):
        assert_boundary_holds(mutated)
