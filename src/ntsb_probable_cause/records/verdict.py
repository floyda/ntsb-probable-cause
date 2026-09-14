"""Verdict: the NTSB's determination. Withheld; used only for scoring (decision 0013)."""

from pydantic import BaseModel, ConfigDict


class Verdict(BaseModel):
    """Probable cause and codes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    probable_cause: str | None
    occurrence_codes: tuple[str, ...]
    finding_codes: tuple[str, ...]

    def codes(self) -> tuple[str, ...]:
        """Occurrence then finding codes."""
        return self.occurrence_codes + self.finding_codes
