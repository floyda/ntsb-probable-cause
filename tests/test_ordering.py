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


# --- jev2, the registered second Jev check (decision 0103; docs/rounds/s27-round1-jev2.md) ---


@pytest.mark.parametrize(
    ("share_k", "base_n", "words"),
    [
        (19, 19, "too few past cases to say"),
        (0, 0, "too few past cases to say"),
        (12, 20, "usually the defining event (a clear habit)"),
        (11, 20, "often the defining event"),
        (5, 20, "often the defining event"),
        (4, 20, "seldom the defining event"),
        (1, 20, "seldom the defining event"),
        (0, 20, "never the defining event in past cases"),
    ],
)
def test_habit_words_follow_the_registered_order(share_k: int, base_n: int, words: str) -> None:
    assert ordering.habit_words(share_k, base_n) == words


def _jev2_state(narrative: str = "The airplane stalled.") -> dict[str, object]:
    stats = _stats()
    options = ordering.candidates((STALL, CFIT), "Maneuvering", stats)
    return ordering.jev2_state(
        (STALL, CFIT), options, "Maneuvering", narrative, stats, load_tables()
    )


def test_jev2_state_has_exactly_the_four_named_fields() -> None:
    state = _jev2_state()
    assert list(state) == [
        "phase_of_flight_group",
        "analyst_guesses",
        "candidates",
        "analyst_account",
    ]
    assert state["phase_of_flight_group"] == "Maneuvering"
    assert state["analyst_account"] == "The airplane stalled."
    tables = load_tables()
    assert state["analyst_guesses"] == [
        {"code": STALL, "meaning": f"{tables.phases['452']} / {tables.events['241']}"},
        {"code": CFIT, "meaning": f"{tables.phases['452']} / {tables.events['470']}"},
    ]


def test_jev2_state_without_a_group_says_not_recorded() -> None:
    stats = _stats()
    options = ordering.candidates(("552300",), None, stats)
    state = ordering.jev2_state(("552300",), options, None, "n", stats, load_tables())
    assert state["phase_of_flight_group"] == "not recorded"


def test_jev2_state_candidates_carry_the_words_fields_in_candidate_order() -> None:
    state = _jev2_state()
    rows = cast("list[dict[str, str]]", state["candidates"])
    stats = _stats()
    assert [r["code"] for r in rows] == list(
        ordering.candidates((STALL, CFIT), "Maneuvering", stats)
    )
    first, *rest = rows
    assert set(first) == {
        "code",
        "meaning",
        "past_cases_when_it_appears",
        "past_cases_in_this_phase_group",
    }
    for row in rest:
        assert set(row) == {
            "code",
            "meaning",
            "past_cases_when_it_appears",
            "past_cases_in_this_phase_group",
            "past_cases_with_the_first_guess",
        }
    by_code = {r["code"]: r for r in rows}
    # STALL appears in 35 past cases and is defining in 5: seldom.
    assert by_code[STALL]["past_cases_when_it_appears"] == "seldom the defining event"
    # Maneuvering holds 50 past cases; STALL is defining in 5 of them: seldom.
    assert by_code[STALL]["past_cases_in_this_phase_group"] == "seldom the defining event"
    # LOC: 30 of 35 when it appears; 30 of 50 in the group (60%); 30 of 35 with STALL.
    assert by_code[LOC]["past_cases_when_it_appears"] == (
        "usually the defining event (a clear habit)"
    )
    assert by_code[LOC]["past_cases_in_this_phase_group"] == (
        "usually the defining event (a clear habit)"
    )
    assert by_code[LOC]["past_cases_with_the_first_guess"] == (
        "usually the defining event (a clear habit)"
    )
    # CFIT appears in only 3 past cases, and never with STALL.
    assert by_code[CFIT]["past_cases_when_it_appears"] == "too few past cases to say"
    assert by_code[CFIT]["past_cases_with_the_first_guess"] == "too few past cases to say"
    # LOC_450: 12 of 50 in the group (24%): below a quarter, so seldom.
    assert by_code[LOC_450]["past_cases_in_this_phase_group"] == "seldom the defining event"


def _strings(value: object, path: str = "") -> list[tuple[str, str]]:
    """Every (path, leaf string) in a JSON value; any other leaf is itself a failure."""
    if isinstance(value, dict):
        out: list[tuple[str, str]] = []
        for key, item in value.items():
            out.append((f"{path}/<key>", str(key)))
            out += _strings(item, f"{path}/{key}")
        return out
    if isinstance(value, list):
        return [pair for item in value for pair in _strings(item, f"{path}/[]")]
    assert isinstance(value, str), f"{path} holds a non-string leaf: {value!r}"
    return [(path, value)]


def test_jev2_state_holds_no_digit_but_the_codes_and_the_narrative() -> None:
    state = _jev2_state(narrative="The airplane stalled at 400 feet, 2 miles out.")
    leaves = _strings(state)
    assert leaves  # the walk saw the whole state
    for path, text in leaves:
        if path == "/analyst_account" or path.endswith("/code"):
            continue
        assert not any(ch.isdigit() for ch in text), f"{path} holds a number: {text!r}"
    codes = [text for path, text in leaves if path.endswith("/code")]
    assert codes
    assert all(len(c) == 6 and c.isdigit() for c in codes)


def test_jev2_question_is_registered_verbatim() -> None:
    question = ordering.jev2_question((STALL, LOC), load_tables())
    assert question["type"] == "choice"
    assert question["instructions"] == {
        "question": (
            "Which of these occurrence codes would the NTSB flag as the defining event of "
            "this accident?"
        ),
        "focus": (
            "Judge from the analyst's account which event began the accident sequence. Past "
            "habits are a guide, not a rule: prefer the option the account supports."
        ),
    }
    criteria = cast("dict[str, dict[str, str]]", question["criteria"])
    assert list(criteria) == [STALL, LOC, ordering.NONE_OF_THESE]
    assert criteria[ordering.NONE_OF_THESE] == {
        "what": "The defining event is none of the codes listed",
        "not_for": "any listed code",
    }


def test_jev2_question_not_for_comes_from_other_candidates_sharing_a_phase_or_event() -> None:
    tables = load_tables()
    options = (STALL, CFIT, LOC, LOC_450, "552300")
    criteria = cast(
        "dict[str, dict[str, str]]", ordering.jev2_question(options, tables)["criteria"]
    )
    p452, p450 = tables.phases["452"], tables.phases["450"]
    e240, e241, e470 = tables.events["240"], tables.events["241"], tables.events["470"]
    assert criteria[STALL] == {
        "what": f"{p452} / {e241}",
        "not_for": (
            f"{e470}, which is listed separately ({CFIT}); "
            f"{e240}, which is listed separately ({LOC})"
        ),
    }
    assert criteria[LOC]["not_for"] == (
        f"{e241}, which is listed separately ({STALL}); "
        f"{e470}, which is listed separately ({CFIT}); "
        f"the same event in the {p450} phase ({LOC_450})"
    )
    assert criteria[LOC_450]["not_for"] == f"the same event in the {p452} phase ({LOC})"
    # 552300 shares neither its phase nor its event with any other candidate: no not_for.
    assert criteria["552300"] == {"what": _words("552300")}


def _words(code: str) -> str:
    tables = load_tables()
    return f"{tables.phases[code[:3]]} / {tables.events[code[3:]]}"


def test_jev2_ranking_breaks_ties_by_the_models_order_not_by_code() -> None:
    options = (CFIT, LOC_450, LOC)  # guesses CFIT then LOC_450; LOC from the candidate list
    probabilities = {LOC: 0.3, LOC_450: 0.3, CFIT: 0.3, ordering.NONE_OF_THESE: 0.1}
    # By code the order would be LOC_450, LOC, CFIT; the model's order is CFIT, LOC_450, LOC.
    assert ordering.jev2_ranking(probabilities, (CFIT, LOC_450), options) == (CFIT, LOC_450, LOC)
    # A later guess ties the first: the model's order still wins.
    assert ordering.jev2_ranking(
        {CFIT: 0.2, LOC_450: 0.4, LOC: 0.4, ordering.NONE_OF_THESE: 0.0}, (CFIT, LOC_450), options
    ) == (LOC_450, LOC, CFIT)


def test_jev2_ranking_is_empty_when_none_of_these_ranks_first() -> None:
    options = (STALL, LOC)
    probabilities = {STALL: 0.2, LOC: 0.2, ordering.NONE_OF_THESE: 0.6}
    assert ordering.jev2_ranking(probabilities, (STALL,), options) == ()


def test_jev2_ranking_never_returns_none_of_these() -> None:
    options = (STALL, LOC, CFIT, LOC_450)
    probabilities = {STALL: 0.4, ordering.NONE_OF_THESE: 0.3, LOC: 0.2, CFIT: 0.1, LOC_450: 0.0}
    assert ordering.jev2_ranking(probabilities, (STALL,), options) == (STALL, LOC, CFIT)
    # A tie with a code puts none_of_these after every code: it is neither a guess nor a
    # candidate, so the model's order does not place it first.
    tied = {STALL: 0.5, ordering.NONE_OF_THESE: 0.5, LOC: 0.0, CFIT: 0.0, LOC_450: 0.0}
    assert ordering.jev2_ranking(tied, (STALL,), options) == (STALL, LOC, CFIT)


def test_jev2_ranking_refuses_labels_it_did_not_ask_for() -> None:
    with pytest.raises(SchemaError, match="labels"):
        ordering.jev2_ranking({STALL: 0.9, "111111": 0.1}, (STALL,), (STALL,))


def test_jev2_order_puts_probabilities_in_the_tie_order() -> None:
    options = (CFIT, LOC_450, LOC)
    order = ordering.jev2_order(
        {LOC: 0.3, ordering.NONE_OF_THESE: 0.1, LOC_450: 0.3, CFIT: 0.3}, (CFIT, LOC_450), options
    )
    assert order == (CFIT, LOC_450, LOC, ordering.NONE_OF_THESE)
