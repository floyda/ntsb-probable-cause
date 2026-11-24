"""Verdict: the NTSB's determination. Withheld; used only for scoring (decision 0013)."""

from pydantic import BaseModel, ConfigDict, model_validator


class Verdict(BaseModel):
    """Probable cause and codes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    probable_cause: str | None
    occurrence_codes: tuple[str, ...]
    finding_codes: tuple[str, ...]
    finding_codes_in_cause: tuple[str, ...]
    # The NTSB's own words for each finding, aligned with finding_codes; empty when not read.
    # Only the board reads them, to label a code the tables cannot (decision 0224).
    finding_descriptions: tuple[str | None, ...] = ()

    @model_validator(mode="after")
    def _descriptions_align(self) -> Verdict:
        if self.finding_descriptions and len(self.finding_descriptions) != len(self.finding_codes):
            raise ValueError("finding_descriptions must align with finding_codes")
        return self

    def codes(self) -> tuple[str, ...]:
        """Occurrence then finding codes."""
        return self.occurrence_codes + self.finding_codes
