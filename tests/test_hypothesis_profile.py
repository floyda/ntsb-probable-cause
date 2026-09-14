"""Hypothesis determinism in CI (final review, item E): a derandomized profile under CI=true."""

import importlib

import pytest
from hypothesis import settings
from tests import conftest


def test_ci_profile_is_registered_with_derandomize() -> None:
    assert settings.get_profile("ci").derandomize is True


def test_ci_env_var_loads_the_ci_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    importlib.reload(conftest)
    try:
        assert settings.get_current_profile_name() == "ci"
    finally:
        settings.load_profile("default")


def test_no_ci_env_var_keeps_the_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.load_profile("default")
    monkeypatch.delenv("CI", raising=False)
    importlib.reload(conftest)
    assert settings.get_current_profile_name() == "default"
