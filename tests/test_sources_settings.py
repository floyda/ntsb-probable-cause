from pathlib import Path

import pytest

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import (
    BudgetError,
    ConfigurationError,
    ModelError,
    NtsbError,
    SchemaError,
)
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.sources import SONNET_5, SONNET_5_BATCH, docket_url


@pytest.fixture(autouse=True)
def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove settings env vars and .env file so tests are isolated."""
    for var in [
        "NTSB_API_KEY",
        "NTSB_DATA_DIR",
        "NTSB_REQUESTS_PER_MINUTE",
        "DATA_DIR",
        "REQUESTS_PER_MINUTE",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_docket_url_is_built_from_mkey() -> None:
    assert docket_url(104739) == "https://data.ntsb.gov/Docket?ProjectID=104739"


def test_model_prices_match_decision_0009() -> None:
    assert (SONNET_5.input_usd_per_mtok, SONNET_5.output_usd_per_mtok) == (2.0, 10.0)
    assert (SONNET_5_BATCH.input_usd_per_mtok, SONNET_5_BATCH.output_usd_per_mtok) == (
        1.0,
        5.0,
    )
    assert SONNET_5_BATCH.model_id == "anthropic/claude-sonnet-5:batch"


def test_settings_read_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_API_KEY", "abc123")
    assert Settings(_env_file=None).require_api_key() == "abc123"


def test_missing_key_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTSB_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="NTSB_API_KEY"):
        Settings(_env_file=None).require_api_key()


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTSB_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.requests_per_minute == 30
    assert str(settings.data_dir) == "data"


def test_ntsb_prefixed_env_vars_are_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NTSB_REQUESTS_PER_MINUTE", "5")
    monkeypatch.setenv("NTSB_DATA_DIR", "/elsewhere")
    settings = Settings(_env_file=None)
    assert settings.requests_per_minute == 5
    assert str(settings.data_dir) == "/elsewhere"


def test_unprefixed_env_vars_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", "/elsewhere")
    monkeypatch.setenv("REQUESTS_PER_MINUTE", "5")
    settings = Settings(_env_file=None)
    assert settings.requests_per_minute == 30
    assert str(settings.data_dir) == "data"


def test_openrouter_key_is_required_when_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        Settings(_env_file=None).require_openrouter_key()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert Settings(_env_file=None).require_openrouter_key() == "or-key"


def test_openrouter_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.openrouter_base_url == "https://openrouter.ai"
    assert s.runs_dir == Path("data/runs")
    assert s.monthly_budget_usd == 25.0


def test_price_of_known_and_unknown_model() -> None:
    assert sources.price_of("openai/gpt-5.6-luna:batch") is sources.LUNA_BATCH
    assert sources.LUNA_BATCH.input_usd_per_mtok == 0.10
    assert sources.LUNA_BATCH.output_usd_per_mtok == 0.60
    with pytest.raises(KeyError):
        sources.price_of("nobody/nothing")


def test_new_errors_are_ntsb_errors() -> None:
    for kind in (ModelError, SchemaError, BudgetError):
        assert issubclass(kind, NtsbError)


def test_docket_settings_have_polite_defaults() -> None:
    settings = Settings()
    assert settings.docket_dir == Path("data/docket")
    assert settings.docket_seconds_per_request == 2.0


def test_docket_document_url_joins_the_relative_href() -> None:
    href = "/Docket/Document/docBLOB?ID=1&FileExtension=.pdf&FileName=x.pdf"
    assert sources.docket_document_url(href) == "https://data.ntsb.gov" + href


def test_unset_dirs_default_to_the_literal_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTSB_DATA_DIR", raising=False)
    monkeypatch.delenv("NTSB_RUNS_DIR", raising=False)
    monkeypatch.delenv("NTSB_DOCKET_DIR", raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_dir == Path("data")
    assert settings.runs_dir == Path("data/runs")
    assert settings.docket_dir == Path("data/docket")


def test_unset_dirs_derive_from_an_explicit_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", "/somewhere")
    monkeypatch.delenv("NTSB_RUNS_DIR", raising=False)
    monkeypatch.delenv("NTSB_DOCKET_DIR", raising=False)
    settings = Settings(_env_file=None)
    assert settings.runs_dir == Path("/somewhere/runs")
    assert settings.docket_dir == Path("/somewhere/docket")


def test_explicit_runs_dir_and_docket_dir_override_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", "/somewhere")
    monkeypatch.setenv("NTSB_RUNS_DIR", "/elsewhere/runs")
    monkeypatch.setenv("NTSB_DOCKET_DIR", "/elsewhere/docket")
    settings = Settings(_env_file=None)
    assert settings.runs_dir == Path("/elsewhere/runs")
    assert settings.docket_dir == Path("/elsewhere/docket")


def test_store_default_is_the_literal_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTSB_DATA_DIR", raising=False)
    monkeypatch.delenv("NTSB_STORE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.store == "data/recorder.sqlite"


def test_unset_store_derives_from_an_explicit_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", "/somewhere")
    monkeypatch.delenv("NTSB_STORE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.store == "/somewhere/recorder.sqlite"


def test_explicit_s3_store_survives_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    # `Path("s3://bucket/key")` would collapse the double slash to `s3:/bucket/key`; `store`
    # is a plain `str` so Task 10's S3 location round-trips untouched (controller resolution 1).
    monkeypatch.setenv("NTSB_STORE", "s3://bucket/key")
    settings = Settings(_env_file=None)
    assert settings.store == "s3://bucket/key"


def test_unset_commit_sha_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTSB_COMMIT_SHA", raising=False)
    assert Settings(_env_file=None).commit_sha is None


def test_empty_commit_sha_env_var_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # The container image's `ARG COMMIT_SHA` has no default (Dockerfile, Task 12); built with
    # no `--build-arg`, `NTSB_COMMIT_SHA` in the environment is `""`, not absent. That must
    # read the same as unset, so `apps/recorder/__main__.py:_commit_identity` falls back to
    # `git` instead of recording a fabricated empty commit (controller note 2).
    monkeypatch.setenv("NTSB_COMMIT_SHA", "")
    assert Settings(_env_file=None).commit_sha is None


def test_real_commit_sha_env_var_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_COMMIT_SHA", "abc1234")
    assert Settings(_env_file=None).commit_sha == "abc1234"
