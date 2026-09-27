"""scoring/ordering.py: the candidate list, the plain rule, the check text and reply (0096)."""

import json
from typing import cast

import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring import ordering
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, PoolCase, build
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess

LOC, STALL, LOC_450, CFIT = "452240", "452241", "450240", "452470"


def _stats() -> CodingStats:
    cases = (
        [PoolCase(2012, "Maneuvering", (LOC, STALL))] * 30  # stall appears: LOC defining 30 times
        + [PoolCase(2016, "Maneuvering", (STALL, LOC))] * 5  # ... stall defining 5 times
        + [PoolCase(2013, "Maneuvering", (LOC_450,))] * 12  # the 450 phase variant, 12 times
        + [PoolCase(2014, "Maneuvering", (CFIT,))] * 3
        + [PoolCase(2015, "Landing", ("552300",))] * 40
    )
    return build(cases, built_from="test")


def test_candidates_are_guesses_then_linked_group_and_phase_variants() -> None:
    options = ordering.candidates((STALL, CFIT), "Maneuvering", _stats())
    assert options[:2] == (STALL, CFIT)
    assert LOC in options  # linked (30 of 35) and a group code
    assert LOC_450 in options  # phase variant of LOC in Maneuvering (12 >= 10)
    assert len(options) == len(set(options)) <= ordering.MAX_CANDIDATES


def test_candidates_without_a_group_still_start_with_the_guesses() -> None:
    options = ordering.candidates(("552300",), None, _stats())
    assert options[0] == "552300"


def test_plain_rule_moves_the_pools_defining_code_first() -> None:
    assert ordering.plain_rule((STALL, CFIT), "Maneuvering", _stats()) == (LOC, STALL, CFIT)


def test_plain_rule_keeps_the_first_guess_on_thin_counts() -> None:
    assert ordering.plain_rule(("999999",), "Maneuvering", _stats())[0] == "999999"


def test_plain_rule_keeps_the_models_phase_when_no_phase_is_a_clear_habit() -> None:
    split = build(
        [PoolCase(2012, "Maneuvering", (LOC_450,))] * 12
        + [PoolCase(2013, "Maneuvering", (LOC,))] * 10,
        built_from="test",
    )
    # 450 holds 12 of 22 (55%): not a clear habit, so the model's 452 stands (decision 0101)
    assert ordering.plain_rule((LOC,), "Maneuvering", split) == (LOC,)


def test_plain_rule_moves_the_phase_on_a_clear_habit() -> None:
    # in _stats(), event 240 in Maneuvering: 452 holds 30 of 42 (71%), a clear habit
    assert ordering.plain_rule((LOC_450,), "Maneuvering", _stats())[0] == LOC


def test_clear_habit_needs_60_percent_of_20_cases() -> None:
    assert ordering.clear_habit({"a": 12, "b": 8}) == "a"
    assert ordering.clear_habit({"a": 11, "b": 9}) is None
    assert ordering.clear_habit({"a": 15}) is None


def test_toward_more_common_compares_pool_counts_in_the_group() -> None:
    stats = _stats()
    assert ordering.toward_more_common(LOC_450, LOC, "Maneuvering", stats)  # 12 -> 30
    assert not ordering.toward_more_common(LOC, LOC_450, "Maneuvering", stats)
    assert not ordering.toward_more_common(LOC, LOC, "Maneuvering", stats)


def test_check_text_holds_codes_counts_group_and_narrative_only() -> None:
    options = ordering.candidates((STALL,), "Maneuvering", _stats())
    text = ordering.check_text(
        (STALL,), options, "Maneuvering", "The airplane stalled.", _stats(), load_tables()
    )
    assert "Maneuvering" in text
    assert "The airplane stalled." in text
    assert STALL in text
    assert LOC in text
    assert "defining in 30 of 35" in text


def test_parse_ranking_accepts_listed_codes_only() -> None:
    options = (STALL, LOC, CFIT)
    assert ordering.parse_ranking(json.dumps({"ranking": [LOC, STALL]}), options) == (LOC, STALL)
    with pytest.raises(SchemaError):
        ordering.parse_ranking(json.dumps({"ranking": ["111111"]}), options)
    with pytest.raises(SchemaError):
        ordering.parse_ranking(json.dumps({"ranking": [LOC, LOC]}), options)
    with pytest.raises(SchemaError):
        ordering.parse_ranking("not json", options)


def test_jev_question_and_ranking() -> None:
    question = ordering.jev_question((STALL, LOC), load_tables())
    assert question["type"] == "choice"
    assert set(cast("dict[str, str]", question["criteria"])) == {STALL, LOC}
    # Ties go by code (the function's stated rule): 452241 (STALL) sorts before 452470 (CFIT), so
    # the tie between them puts STALL first, giving (LOC, STALL, CFIT), not (LOC, CFIT, STALL)
    # as the brief's assertion read (2026-09-27, see plan Deviations).
    assert ordering.ranking_from_probabilities({STALL: 0.2, LOC: 0.7, CFIT: 0.2}) == (
        LOC,
        STALL,
        CFIT,
    )


def test_reorder_keeps_known_probabilities_and_gives_new_codes_zero() -> None:
    hypothesis = Hypothesis(
        evidence_narrative="n",
        occurrence=(OccurrenceGuess(phase="452", event="241", probability=0.6),),
        findings=(),
        probable_cause="p",
        lay_explanation="l",
        confidence=0.5,
        abstain=False,
        evidence_used=(),
    )
    out = ordering.reorder(hypothesis, (LOC, STALL))
    assert [(g.phase + g.event, g.probability) for g in out.occurrence] == [
        (LOC, 0.0),
        (STALL, 0.6),
    ]
    assert out.evidence_narrative == "n"
