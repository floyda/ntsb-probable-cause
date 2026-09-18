"""Per-run settings, read from the environment (decision 0012)."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ntsb_probable_cause.errors import ConfigurationError


class Settings(BaseSettings):
    """Values that may change between runs. Recorded with each run's output."""

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="NTSB_", extra="ignore", frozen=True
    )

    ntsb_api_key: SecretStr | None = Field(default=None, validation_alias="NTSB_API_KEY")
    requests_per_minute: int = Field(default=30, gt=0)
    data_dir: Path = Path("data")
    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    openrouter_base_url: str = "https://openrouter.ai"
    runs_dir: Path = Path("data/runs")
    monthly_budget_usd: float = Field(default=25.0, gt=0)
    expected_cost_per_case_usd: float | None = Field(
        default=None, validation_alias="NTSB_EXPECTED_COST_PER_CASE_USD"
    )
    heldout_ledger_path: Path = Field(
        default=Path("docs/results/heldout-ledger.md"),
        validation_alias="NTSB_HELDOUT_LEDGER_PATH",
    )
    docket_dir: Path = Path("data/docket")
    docket_seconds_per_request: float = Field(default=2.0, ge=0)

    def require_api_key(self) -> str:
        """Return the NTSB API key, or raise if it is not set."""
        if self.ntsb_api_key is None or not self.ntsb_api_key.get_secret_value():
            raise ConfigurationError(
                "NTSB_API_KEY is not set; export it or load it from the password store."
            )
        return self.ntsb_api_key.get_secret_value()

    def require_openrouter_key(self) -> str:
        """Return the OpenRouter key, or raise if it is not set (decision 0009)."""
        if self.openrouter_api_key is None or not self.openrouter_api_key.get_secret_value():
            raise ConfigurationError(
                "OPENROUTER_API_KEY is not set; export it or load it from the password store."
            )
        return self.openrouter_api_key.get_secret_value()
