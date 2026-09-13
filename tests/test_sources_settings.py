import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.sources import SONNET_5, SONNET_5_BATCH, docket_url


def test_docket_url_is_built_from_mkey() -> None:
    assert docket_url(104739) == "https://data.ntsb.gov/Docket?ProjectID=104739"


def test_model_prices_match_decision_0009() -> None:
    assert (SONNET_5.input_usd_per_mtok, SONNET_5.output_usd_per_mtok) == (2.0, 10.0)
    assert (SONNET_5_BATCH.input_usd_per_mtok, SONNET_5_BATCH.output_usd_per_mtok) == (1.0, 5.0)
    assert SONNET_5_BATCH.model_id == "anthropic/claude-sonnet-5:batch"


def test_settings_read_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_API_KEY", "abc123")
    assert Settings().require_api_key() == "abc123"


def test_missing_key_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTSB_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="NTSB_API_KEY"):
        Settings(_env_file=None).require_api_key()


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NTSB_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.requests_per_minute == 30
    assert str(settings.data_dir) == "data"
