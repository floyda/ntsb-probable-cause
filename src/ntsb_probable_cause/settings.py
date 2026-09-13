"""Per-run settings, read from the environment (decision 0012)."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ntsb_probable_cause.errors import ConfigurationError


class Settings(BaseSettings):
    """Values that may change between runs. Recorded with each run's output."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    ntsb_api_key: SecretStr | None = Field(default=None, alias="NTSB_API_KEY")
    requests_per_minute: int = Field(default=30, gt=0)
    data_dir: Path = Path("data")

    def require_api_key(self) -> str:
        """Return the NTSB API key, or raise if it is not set."""
        if self.ntsb_api_key is None or not self.ntsb_api_key.get_secret_value():
            raise ConfigurationError(
                "NTSB_API_KEY is not set; export it or load it from the password store."
            )
        return self.ntsb_api_key.get_secret_value()
