"""Synthesis: the investigator's write-up. Withheld from any model (decision 0013)."""

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.fields import SynthesisRole


class Synthesis(BaseModel):
    """Factual and analysis narratives."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    factual_narrative: str | None
    analysis_narrative: str | None

    def texts(self) -> dict[str, str | None]:
        """Each synthesis text keyed by role name."""
        return {
            SynthesisRole.FACTUAL_NARRATIVE: self.factual_narrative,
            SynthesisRole.ANALYSIS_NARRATIVE: self.analysis_narrative,
        }
