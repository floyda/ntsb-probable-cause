"""Evidence: observations, the only content a model may see (decision 0013)."""

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.fields import EvidenceRole, EvidenceValue

BOOKKEEPING_FIELDS = frozenset({"case_id", "docket_url", "excluded"})


class Evidence(BaseModel):
    """Allow-listed evidence for one case. Bookkeeping fields are never rendered into a payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    docket_url: str | None
    excluded: frozenset[EvidenceRole] = frozenset()

    prelim_narrative: str | None = None
    aircraft_make: str | None = None
    aircraft_model: str | None = None
    registration: str | None = None
    engine_type: str | None = None
    pilot_certificates: tuple[str, ...] | None = None
    pilot_total_hours: float | None = None
    pilot_hours_in_type: float | None = None
    weather_condition: str | None = None
    weather_metar: str | None = None
    phase_of_flight: str | None = None
    injury_level: str | None = None
    docket_listing: str | None = None
    docket_documents: tuple[str, ...] | None = None

    def role_values(self) -> dict[EvidenceRole, EvidenceValue]:
        """Every non-excluded evidence role and its value."""
        return {
            role: getattr(self, role.value) for role in EvidenceRole if role not in self.excluded
        }
