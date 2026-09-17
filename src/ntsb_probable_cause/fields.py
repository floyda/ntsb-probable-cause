"""Field roles and the raw paths each role reads (decisions 0013 and 0016).

Method constants carried from the spike's config.yaml field map, less the factual narrative,
which is synthesis. Change only with a decision record.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.paths import is_well_formed, normalise_path, overlaps, resolve_path

Raw = Mapping[str, object]
EvidenceValue = str | float | tuple[str, ...] | None


class EvidenceRole(StrEnum):
    """Observations. The only roles rendered into a model payload."""

    PRELIM_NARRATIVE = "prelim_narrative"
    AIRCRAFT_MAKE = "aircraft_make"
    AIRCRAFT_MODEL = "aircraft_model"
    REGISTRATION = "registration"
    ENGINE_TYPE = "engine_type"
    PILOT_CERTIFICATES = "pilot_certificates"
    PILOT_TOTAL_HOURS = "pilot_total_hours"
    PILOT_HOURS_IN_TYPE = "pilot_hours_in_type"
    WEATHER_CONDITION = "weather_condition"
    WEATHER_METAR = "weather_metar"
    PHASE_OF_FLIGHT = "phase_of_flight"
    INJURY_LEVEL = "injury_level"


class SynthesisRole(StrEnum):
    """The investigator's write-up. Withheld."""

    FACTUAL_NARRATIVE = "factual_narrative"
    ANALYSIS_NARRATIVE = "analysis_narrative"


class VerdictRole(StrEnum):
    """The determination. Withheld; used for scoring."""

    PROBABLE_CAUSE = "probable_cause"
    OCCURRENCE_CODES = "occurrence_codes"
    FINDING_CODES = "finding_codes"


WITHHELD_ROLE_NAMES = frozenset({*SynthesisRole, *VerdictRole})

# Decision 0020: on an amateur-built aircraft the recorded make (and sometimes model) usually
# holds the builder's own name, copied from the registration, and the builder is often the
# pilot or owner. Both evidence roles hold this fixed label instead when the flag is set. The
# check fails closed: the label is used unless the flag is exactly `False` or absent/`None`; any
# other value, including a non-boolean one, gives the label rather than the recorded value.
AMATEUR_BUILT_LABEL = "Amateur-built"

WITHHELD_SUBTREES = (
    "narratives[].concatenatedFactualNarrative",
    "narratives[].analysisNarrative",
    "narratives[].probableCause",
    "aircrafts[].events[]",
    "aircrafts[].findings[]",
    "richNarratives",
)

_PHASE_OF_FLIGHT_CITATION = (
    "decision 0016: open cases carry the coded event sequence from day 1; "
    "spike ablation: at most 2.5 points of one-shot top-1"
)

# Keyed on (role, the source's exact normalised leaf path) — never a whole subtree — so an
# exception covers only the paths decision 0016 names, not every path under their parent.
PATH_CHECK_EXCEPTIONS: Mapping[tuple[EvidenceRole, str], str] = MappingProxyType(
    {
        (EvidenceRole.PHASE_OF_FLIGHT, "aircrafts[].events[].isDefiningEvent"): (
            _PHASE_OF_FLIGHT_CITATION
        ),
        (EvidenceRole.PHASE_OF_FLIGHT, "aircrafts[].events[].sequenceNumber"): (
            _PHASE_OF_FLIGHT_CITATION
        ),
        (EvidenceRole.PHASE_OF_FLIGHT, "aircrafts[].events[].cicttPhaseSOEGroup"): (
            _PHASE_OF_FLIGHT_CITATION
        ),
    }
)


@dataclass(frozen=True)
class EvidenceField:
    """One evidence role, every raw path it reads, and how to read it."""

    role: EvidenceRole
    sources: tuple[str, ...]
    extract: Callable[[Raw], EvidenceValue]


def _dicts(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _text_at(path: str) -> Callable[[Raw], EvidenceValue]:
    def extract(raw: Raw) -> EvidenceValue:
        value = resolve_path(raw, path)
        return value if isinstance(value, str) and value.strip() else None

    return extract


_AMATEUR_BUILT_FLAG = "aircrafts[0].aircraftAmateurBuilt"


def _amateur_built_or_text_at(path: str) -> Callable[[Raw], EvidenceValue]:
    """Decision 0020: the fixed label unless the amateur-built flag is `False` or absent/`None`.

    Fails closed: any value other than `False`/`None` (including a non-boolean, truthy-looking
    value such as the string "true") gives the label, never the recorded make or model.
    """

    def extract(raw: Raw) -> EvidenceValue:
        flag = resolve_path(raw, _AMATEUR_BUILT_FLAG)
        if flag is False or flag is None:
            return _text_at(path)(raw)
        return AMATEUR_BUILT_LABEL

    return extract


def _strings_at(path: str) -> Callable[[Raw], EvidenceValue]:
    def extract(raw: Raw) -> EvidenceValue:
        value = resolve_path(raw, path)
        items = tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()
        return items or None

    return extract


def _pilot_hours(craft: str) -> Callable[[Raw], EvidenceValue]:
    def extract(raw: Raw) -> EvidenceValue:
        rows = _dicts(resolve_path(raw, "aircrafts[0].crewAndOccupants[0].pilotsFlightTimeMatrix"))
        for row in rows:
            hours = row.get("flightHours")
            if row.get("flightTimeType") == "Total" and row.get("flightTimeCraft") == craft:
                return float(hours) if isinstance(hours, int | float) else None
        return None

    return extract


def _sequence(event: Mapping[str, object]) -> int:
    value = event.get("sequenceNumber")
    return value if isinstance(value, int) else 0


def _finding_number(finding: Mapping[str, object]) -> int:
    value = finding.get("findingNumber")
    return value if isinstance(value, int) else 0


def _ordered_events(raw: Raw) -> list[Mapping[str, object]]:
    events = _dicts(resolve_path(raw, "aircrafts[0].events"))
    defining = [e for e in events if e.get("isDefiningEvent") is True]
    rest = sorted((e for e in events if e.get("isDefiningEvent") is not True), key=_sequence)
    return defining + rest


def _phase_of_flight(raw: Raw) -> EvidenceValue:
    events = _dicts(resolve_path(raw, "aircrafts[0].events"))
    defining = [e for e in events if e.get("isDefiningEvent") is True]
    ordered = defining or sorted(events, key=_sequence)
    phase = ordered[0].get("cicttPhaseSOEGroup") if ordered else None
    return phase if isinstance(phase, str) and phase.strip() else None


_MATRIX = "aircrafts[0].crewAndOccupants[0].pilotsFlightTimeMatrix[]"

EVIDENCE_FIELDS: tuple[EvidenceField, ...] = (
    EvidenceField(
        EvidenceRole.PRELIM_NARRATIVE,
        ("narratives[0].prelimNarrative",),
        _text_at("narratives[0].prelimNarrative"),
    ),
    EvidenceField(
        EvidenceRole.AIRCRAFT_MAKE,
        ("aircrafts[0].aircraftMake", _AMATEUR_BUILT_FLAG),
        _amateur_built_or_text_at("aircrafts[0].aircraftMake"),
    ),
    EvidenceField(
        EvidenceRole.AIRCRAFT_MODEL,
        ("aircrafts[0].aircraftModel", _AMATEUR_BUILT_FLAG),
        _amateur_built_or_text_at("aircrafts[0].aircraftModel"),
    ),
    EvidenceField(
        EvidenceRole.REGISTRATION,
        ("aircrafts[0].aircraftRegistrationNumber",),
        _text_at("aircrafts[0].aircraftRegistrationNumber"),
    ),
    EvidenceField(
        EvidenceRole.ENGINE_TYPE,
        ("aircrafts[0].engines[0].engineType",),
        _text_at("aircrafts[0].engines[0].engineType"),
    ),
    EvidenceField(
        EvidenceRole.PILOT_CERTIFICATES,
        ("aircrafts[0].crewAndOccupants[0].pilotCertificates",),
        _strings_at("aircrafts[0].crewAndOccupants[0].pilotCertificates"),
    ),
    EvidenceField(
        EvidenceRole.PILOT_TOTAL_HOURS,
        (f"{_MATRIX}.flightTimeType", f"{_MATRIX}.flightTimeCraft", f"{_MATRIX}.flightHours"),
        _pilot_hours("All AC"),
    ),
    EvidenceField(
        EvidenceRole.PILOT_HOURS_IN_TYPE,
        (f"{_MATRIX}.flightTimeType", f"{_MATRIX}.flightTimeCraft", f"{_MATRIX}.flightHours"),
        _pilot_hours("Make and Model"),
    ),
    EvidenceField(
        EvidenceRole.WEATHER_CONDITION,
        ("weatherConditions[0].accidentSiteCondition",),
        _text_at("weatherConditions[0].accidentSiteCondition"),
    ),
    EvidenceField(
        EvidenceRole.WEATHER_METAR,
        ("weatherConditions[0].metar",),
        _text_at("weatherConditions[0].metar"),
    ),
    EvidenceField(
        EvidenceRole.PHASE_OF_FLIGHT,
        (
            "aircrafts[0].events[].isDefiningEvent",
            "aircrafts[0].events[].sequenceNumber",
            "aircrafts[0].events[].cicttPhaseSOEGroup",
        ),
        _phase_of_flight,
    ),
    EvidenceField(
        EvidenceRole.INJURY_LEVEL, ("highestInjuryLevel",), _text_at("highestInjuryLevel")
    ),
)


def check_evidence_paths(fields: Sequence[EvidenceField] = EVIDENCE_FIELDS) -> None:
    """Raise LeakageError if a source overlaps a withheld subtree, or is malformed (guard layer 2).

    "Overlaps" means the source lies under the subtree OR is a parent of it: reading a parent
    reads the withheld subtree too (e.g. ``aircrafts[0].events`` reads every event, including
    the withheld ``eventCode``).
    """
    for field in fields:
        for source in field.sources:
            if not is_well_formed(source):
                raise LeakageError(
                    f"evidence role {field.role} has a malformed source path: {source}"
                )
            key = (field.role, normalise_path(source))
            for subtree in WITHHELD_SUBTREES:
                if overlaps(source, subtree) and key not in PATH_CHECK_EXCEPTIONS:
                    raise LeakageError(
                        f"evidence role {field.role} reads {source}, under withheld {subtree}"
                    )


def check_path_exceptions(
    exceptions: Mapping[tuple[EvidenceRole, str], str] = PATH_CHECK_EXCEPTIONS,
) -> None:
    """Raise LeakageError if a declared exception no longer overlaps any withheld subtree.

    Catches a stale entry: an exception that was valid when written but whose path has since
    moved, or whose withheld subtree was removed, so it would silently stop protecting anything.
    """
    for role, path in exceptions:
        if not any(overlaps(path, subtree) for subtree in WITHHELD_SUBTREES):
            raise LeakageError(
                f"stale path-check exception: {role} / {path} is not under any withheld subtree"
            )


def factual_narrative(raw: Raw) -> str | None:
    """Synthesis: the factual narrative."""
    value = _text_at("narratives[0].concatenatedFactualNarrative")(raw)
    return value if isinstance(value, str) else None


def analysis_narrative(raw: Raw) -> str | None:
    """Synthesis: the analysis narrative."""
    value = _text_at("narratives[0].analysisNarrative")(raw)
    return value if isinstance(value, str) else None


def probable_cause(raw: Raw) -> str | None:
    """Verdict: the probable-cause text."""
    value = _text_at("narratives[0].probableCause")(raw)
    return value if isinstance(value, str) else None


def occurrence_codes(raw: Raw) -> tuple[str, ...]:
    """Verdict: event codes, defining event first, then by sequence number."""
    return tuple(code for e in _ordered_events(raw) if isinstance(code := e.get("eventCode"), str))


def finding_codes(raw: Raw) -> tuple[str, ...]:
    """Verdict: finding codes ordered by finding number."""
    findings = sorted(_dicts(resolve_path(raw, "aircrafts[0].findings")), key=_finding_number)
    return tuple(code for f in findings if isinstance(code := f.get("findingCode"), str))


def finding_codes_in_cause(raw: Raw) -> tuple[str, ...]:
    """Verdict: the finding codes the NTSB flagged as in the probable cause, by finding number."""
    findings = sorted(_dicts(resolve_path(raw, "aircrafts[0].findings")), key=_finding_number)
    return tuple(
        code
        for f in findings
        if f.get("inProbableCause") is True and isinstance(code := f.get("findingCode"), str)
    )


check_path_exceptions()
check_evidence_paths()
