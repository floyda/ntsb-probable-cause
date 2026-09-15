"""The three fixed samples, arms as exclusion sets, and the day-N mask (spec §5, §6.1)."""

from pathlib import Path

import pytest

from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import samples


def test_arm_a_keeps_only_start_facts() -> None:
    kept = set(EvidenceRole) - samples.arm_exclusions("A")
    assert kept == samples.START_FACTS
    assert samples.arm_exclusions("ceiling") == frozenset()


def test_mask_hides_late_fields_early() -> None:
    day1 = samples.masked_exclusions(1)
    assert EvidenceRole.PILOT_TOTAL_HOURS in day1
    assert EvidenceRole.WEATHER_METAR in day1
    assert EvidenceRole.PRELIM_NARRATIVE in samples.masked_exclusions(400)
    assert EvidenceRole.PHASE_OF_FLIGHT not in day1


def test_mask_lifts_late_fields_at_day_14() -> None:
    day14 = samples.masked_exclusions(14)
    assert EvidenceRole.PILOT_TOTAL_HOURS not in day14
    assert EvidenceRole.WEATHER_METAR not in day14
    assert day14 == frozenset({EvidenceRole.PRELIM_NARRATIVE})


def test_sample_ids_are_loaded(eval_ids: dict[str, dict[str, str]]) -> None:
    assert len(samples.sample_ids("heldout-40")) == 40


def test_sample_ids_are_in_file_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(samples, "EVAL_DIR", tmp_path)
    monkeypatch.setitem(samples._FILES, "heldout-40", "ordered.csv")
    (tmp_path / "ordered.csv").write_text("case_id,event_date\nB2,2021-01-01\nA1,2020-01-01\n")
    assert samples.sample_ids("heldout-40") == ("B2", "A1")
