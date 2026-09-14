import copy
from types import MappingProxyType

import pytest

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import (
    AMATEUR_BUILT_LABEL,
    EVIDENCE_FIELDS,
    EvidenceField,
    EvidenceRole,
    analysis_narrative,
    check_evidence_paths,
    check_path_exceptions,
    factual_narrative,
    finding_codes,
    occurrence_codes,
    probable_cause,
)

RAW: dict[str, object] = {
    "highestInjuryLevel": "Fatal",
    "narratives": [
        {
            "prelimNarrative": None,
            "probableCause": "Cause.",
            "analysisNarrative": "A.",
            "concatenatedFactualNarrative": (
                "The airplane departed controlled flight during the approach and impacted "
                "terrain in a wooded area short of the runway."
            ),
        }
    ],
    "weatherConditions": [{"accidentSiteCondition": "Visual (VMC)", "metar": "KABC 011200Z"}],
    "aircrafts": [
        {
            "aircraftMake": "CESSNA",
            "aircraftModel": "172SP",
            "aircraftRegistrationNumber": "N2228L",
            "engines": [{"engineType": "Reciprocating"}],
            "crewAndOccupants": [
                {
                    "pilotCertificates": ["Private"],
                    "pilotsFlightTimeMatrix": [
                        {
                            "flightTimeType": "Total",
                            "flightTimeCraft": "All AC",
                            "flightHours": 250,
                        },
                        {
                            "flightTimeType": "Total",
                            "flightTimeCraft": "Make and Model",
                            "flightHours": 40,
                        },
                        {
                            "flightTimeType": "24 Hours",
                            "flightTimeCraft": "All AC",
                            "flightHours": 2,
                        },
                    ],
                }
            ],
            "events": [
                {
                    "eventCode": "300300",
                    "sequenceNumber": 2,
                    "isDefiningEvent": False,
                    "cicttPhaseSOEGroup": "Takeoff",
                },
                {
                    "eventCode": "300230",
                    "sequenceNumber": 1,
                    "isDefiningEvent": True,
                    "cicttPhaseSOEGroup": "Initial Climb",
                },
                {
                    "eventCode": "400100",
                    "sequenceNumber": 3,
                    "isDefiningEvent": False,
                    "cicttPhaseSOEGroup": "Landing",
                },
            ],
            "findings": [
                {"findingCode": "0203000046", "findingNumber": 2},
                {"findingCode": "0106202020", "findingNumber": 1},
            ],
        }
    ],
}


def extracted() -> dict[EvidenceRole, object]:
    return {f.role: f.extract(RAW) for f in EVIDENCE_FIELDS}


def test_every_evidence_role_has_one_field() -> None:
    assert sorted(f.role for f in EVIDENCE_FIELDS) == sorted(EvidenceRole)


def test_simple_extractions() -> None:
    values = extracted()
    assert values[EvidenceRole.AIRCRAFT_MAKE] == "CESSNA"
    assert values[EvidenceRole.REGISTRATION] == "N2228L"
    assert values[EvidenceRole.ENGINE_TYPE] == "Reciprocating"
    assert values[EvidenceRole.WEATHER_METAR] == "KABC 011200Z"
    assert values[EvidenceRole.INJURY_LEVEL] == "Fatal"
    assert values[EvidenceRole.PRELIM_NARRATIVE] is None
    assert values[EvidenceRole.PILOT_CERTIFICATES] == ("Private",)


def test_amateur_built_flag_replaces_make_and_model() -> None:
    make_field = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.AIRCRAFT_MAKE)
    model_field = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.AIRCRAFT_MODEL)
    raw = copy.deepcopy(RAW)
    aircraft = raw["aircrafts"][0]  # type: ignore[index]
    aircraft["aircraftAmateurBuilt"] = True
    aircraft["aircraftMake"] = "INVENTED BUILDER"
    aircraft["aircraftModel"] = "INVENTED BUILDER MODEL"
    assert make_field.extract(raw) == AMATEUR_BUILT_LABEL
    assert model_field.extract(raw) == AMATEUR_BUILT_LABEL


@pytest.mark.parametrize("flag", [False, None])
def test_non_amateur_built_keeps_recorded_make_and_model(flag: bool | None) -> None:
    make_field = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.AIRCRAFT_MAKE)
    model_field = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.AIRCRAFT_MODEL)
    raw = copy.deepcopy(RAW)
    aircraft = raw["aircrafts"][0]  # type: ignore[index]
    if flag is None:
        aircraft.pop("aircraftAmateurBuilt", None)
    else:
        aircraft["aircraftAmateurBuilt"] = flag
    assert make_field.extract(raw) == "CESSNA"
    assert model_field.extract(raw) == "172SP"


def test_amateur_built_flag_is_a_declared_source() -> None:
    make_field = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.AIRCRAFT_MAKE)
    model_field = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.AIRCRAFT_MODEL)
    assert "aircrafts[0].aircraftAmateurBuilt" in make_field.sources
    assert "aircrafts[0].aircraftAmateurBuilt" in model_field.sources


def test_pilot_hours_from_matrix() -> None:
    values = extracted()
    assert values[EvidenceRole.PILOT_TOTAL_HOURS] == 250.0
    assert values[EvidenceRole.PILOT_HOURS_IN_TYPE] == 40.0


def test_phase_of_flight_uses_defining_event() -> None:
    assert extracted()[EvidenceRole.PHASE_OF_FLIGHT] == "Initial Climb"


def test_phase_of_flight_falls_back_to_first_by_sequence() -> None:
    aircraft = {
        "events": [
            {"sequenceNumber": 2, "isDefiningEvent": False, "cicttPhaseSOEGroup": "Landing"},
            {"sequenceNumber": 1, "isDefiningEvent": False, "cicttPhaseSOEGroup": "Approach"},
        ]
    }
    field = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)
    assert field.extract({"aircrafts": [aircraft]}) == "Approach"


def test_verdict_codes_are_ordered() -> None:
    assert occurrence_codes(RAW) == ("300230", "300300", "400100")
    assert finding_codes(RAW) == ("0106202020", "0203000046")


def test_extractors_tolerate_empty_record() -> None:
    assert all(f.extract({}) is None for f in EVIDENCE_FIELDS)
    assert occurrence_codes({}) == ()


def test_withheld_text_extractors_on_raw() -> None:
    assert factual_narrative(RAW) == (
        "The airplane departed controlled flight during the approach and impacted "
        "terrain in a wooded area short of the runway."
    )
    assert analysis_narrative(RAW) == "A."
    assert probable_cause(RAW) == "Cause."


def test_real_field_map_passes_path_check() -> None:
    check_evidence_paths()


def test_real_exceptions_are_not_stale() -> None:
    check_path_exceptions()


def test_path_check_rejects_role_pointed_at_withheld_field() -> None:
    bad = EvidenceField(
        EvidenceRole.AIRCRAFT_MAKE, ("narratives[0].analysisNarrative",), lambda _: None
    )
    with pytest.raises(LeakageError, match="analysisNarrative"):
        check_evidence_paths((bad,))


def test_phase_of_flight_exception_does_not_cover_event_code() -> None:
    bad = EvidenceField(
        EvidenceRole.PHASE_OF_FLIGHT, ("aircrafts[0].events[].eventCode",), lambda _: None
    )
    with pytest.raises(LeakageError, match="eventCode"):
        check_evidence_paths((bad,))


def test_exception_is_specific_to_role_not_just_path() -> None:
    bad = EvidenceField(
        EvidenceRole.INJURY_LEVEL, ("aircrafts[0].events[].isDefiningEvent",), lambda _: None
    )
    with pytest.raises(LeakageError, match="isDefiningEvent"):
        check_evidence_paths((bad,))


@pytest.mark.parametrize(
    "source",
    [
        "aircrafts[0].events",
        "aircrafts[0]",
        "narratives[0]",
        "richNarratives[0].x",
    ],
)
def test_path_check_rejects_parent_paths(source: str) -> None:
    bad = EvidenceField(EvidenceRole.INJURY_LEVEL, (source,), lambda _: None)
    with pytest.raises(LeakageError):
        check_evidence_paths((bad,))


def test_path_check_rejects_malformed_source() -> None:
    bad = EvidenceField(EvidenceRole.INJURY_LEVEL, ("aircrafts[0.events",), lambda _: None)
    with pytest.raises(LeakageError, match="malformed"):
        check_evidence_paths((bad,))


def test_check_path_exceptions_detects_a_stale_entry() -> None:
    stale = MappingProxyType(
        {
            (EvidenceRole.PHASE_OF_FLIGHT, "aircrafts[].engines[].engineType"): "not withheld",
        }
    )
    with pytest.raises(LeakageError, match="stale"):
        check_path_exceptions(stale)
