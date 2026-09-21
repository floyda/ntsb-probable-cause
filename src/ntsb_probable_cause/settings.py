"""Per-run settings, read from the environment (decision 0012)."""

from pathlib import Path
from typing import Any

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
    typesafe_api_key: SecretStr | None = Field(default=None, validation_alias="TYPESAFE_API_KEY")
    typesafe_base_url: str = "https://api.typesafe.ai"
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
    # `gt=0`, not `ge=0`: the plan's Global Constraints fix the docket rate at one request
    # every two seconds to `data.ntsb.gov`, a real government site, and 0 would remove that
    # floor in production. Tests never need 0 -- they inject `sleep` (fix round 1, Finding 4).
    docket_seconds_per_request: float = Field(default=2.0, gt=0)

    # `runs_dir` and `docket_dir` used to be independent literal defaults. On 2026-09-21 a run
    # was launched with `NTSB_DATA_DIR` pointing at the main checkout but `NTSB_DOCKET_DIR`
    # unset; the docket cache resolved relative to the process's working directory -- inside a
    # git worktree -- and 19 GB of politely fetched docket documents (three hours of requests to
    # data.ntsb.gov at one every two seconds) landed somewhere the worktree's removal would have
    # deleted. They were rescued by hand. So an unset directory setting now derives from
    # `data_dir`, and only an explicitly supplied value overrides that.
    #
    # A `@model_validator(mode="after")` that returns `self.model_copy(update=...)` is the
    # documented way to do this on a plain `BaseModel`, but `pydantic-settings` warns and
    # silently ignores the returned copy when the model is built through `__init__` (as every
    # `Settings()` call here is) -- see the pydantic-settings issue tracker for "Returning
    # anything other than `self` from a top level model validator isn't supported when
    # validating via `__init__`". `model_post_init` runs after that `__init__` has already
    # produced the real instance, so mutating it there (via `object.__setattr__`, since the
    # model is frozen) takes effect; nothing here bypasses field validation, since the values
    # written are already-validated `Path`s.
    def model_post_init(self, _context: Any) -> None:
        """Derive `runs_dir` and `docket_dir` from `data_dir` where left unset."""
        if "runs_dir" not in self.model_fields_set:
            object.__setattr__(self, "runs_dir", self.data_dir / "runs")
        if "docket_dir" not in self.model_fields_set:
            object.__setattr__(self, "docket_dir", self.data_dir / "docket")

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

    def require_typesafe_key(self) -> str:
        """Return the TypeSafe key, or raise if it is not set (decision 0060)."""
        if self.typesafe_api_key is None or not self.typesafe_api_key.get_secret_value():
            raise ConfigurationError(
                "TYPESAFE_API_KEY is not set; export it or load it from the password store."
            )
        return self.typesafe_api_key.get_secret_value()
