"""Tests for the TypeSafe probe's request builders (decision 0036). No socket is opened."""

import pytest
from scripts.typesafe_probe import choice_questions, noul_questions, payload_text, request_bodies

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.fields import WITHHELD_ROLE_NAMES
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.settings import Settings


def test_every_table_fits_one_choice_question() -> None:
    questions = choice_questions(load_tables())
    sizes = {name: len(questions[name]["criteria"]) for name in ("phase", "event", "modifier")}  # type: ignore[arg-type]
    assert sizes == {"phase": 47, "event": 93, "modifier": 73}
    assert all(n <= sources.TYPESAFE_MAX_CHOICE_LABELS for n in sizes.values())
    assert questions["evidence_detail"]["type"] == "score"
    assert len(questions["evidence_detail"]["criteria"]) == 3  # type: ignore[arg-type]


def test_one_noul_per_finding_category() -> None:
    tables = load_tables()
    nouls = noul_questions(tables)
    assert len(nouls) == len(tables.categories) == 130
    assert all(q["type"] == "noul" for q in nouls.values())
    assert set(nouls) == {f"category_{code}" for code in tables.categories}


def test_request_bodies_carry_the_evidence_payload_only() -> None:
    state = payload_text()
    bodies = request_bodies(state, load_tables(), "jev-latest")
    assert set(bodies) == {"choices", "nouls"}
    for body in bodies.values():
        assert body["state"] == state
        assert body["model"] == "jev-latest"
    assert not any(name in state for name in WITHHELD_ROLE_NAMES)
    assert "probableCause" not in state
    assert "findings" not in state


def test_typesafe_key_is_required_when_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="TYPESAFE_API_KEY"):
        Settings(_env_file=None).require_typesafe_key()
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    assert Settings(_env_file=None).require_typesafe_key() == "ts-key"
    assert Settings(_env_file=None).typesafe_base_url == "https://api.typesafe.ai"


def test_jev_price_is_recorded_as_self_reported() -> None:
    assert sources.price_of("jev-latest") is sources.JEV
    assert sources.JEV.output_usd_per_mtok == 0.0
    assert "self-reported" in sources.JEV.source
