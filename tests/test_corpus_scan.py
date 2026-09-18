import re
from collections import Counter
from pathlib import Path

import pytest
from scripts.corpus_scan import (
    THRESHOLD_LINE,
    choose_threshold,
    docket_hits,
    docket_report,
    duplication_share,
    has_missed_break,
    has_nonempty_prelim_narrative,
    is_amateur_built,
    later_probable_cause_differs,
    leak_kinds,
    missed_break_sources,
    model_contains_make,
    multi_aircraft_with_codes,
    narratives_count,
    raw_aircraft_make,
    raw_aircraft_model,
)
from tests.test_attach import _docket as small_docket

from ntsb_probable_cause import fields
from ntsb_probable_cause.records import guard

RESULTS = Path("docs/results/s0-corpus-scan.txt")


def test_choose_threshold_picks_smallest_length_with_zero_hits() -> None:
    assert choose_threshold({10: 4, 20: 0, 40: 0, 80: 0}) == 20
    assert choose_threshold({10: 0, 20: 0}) == 10
    assert choose_threshold({10: 3, 20: 1}) is None


def test_duplication_share_counts_long_analysis_sentences_found_in_factual() -> None:
    factual = (
        "The pilot reported a loss of engine power during cruise. The airplane landed in a field."
    )
    analysis = (
        "The pilot reported a loss of engine power during cruise. "
        "Examination revealed no anomalies at all."
    )
    assert duplication_share(analysis, factual) == pytest.approx(0.5)
    assert duplication_share(None, factual) == 0.0


def test_fixtures_have_no_leaks_at_any_candidate_length(
    record_fixtures: list[dict[str, object]],
) -> None:
    for raw in record_fixtures:
        for length in (10, 20, 40, 80):
            assert leak_kinds(raw, length) == {}, raw["ntsbNumber"]


def test_guard_threshold_is_the_value_the_scan_recorded() -> None:
    lines = [line for line in RESULTS.read_text().splitlines() if line.startswith(THRESHOLD_LINE)]
    assert len(lines) == 1
    assert int(re.sub(r"\D", "", lines[0])) == guard.MIN_SENTENCE_CHARS


# --- Item F: tripwire coverage limits, fixed in S2 (pure functions, no I/O) ---


def test_has_missed_break_after_a_closing_quote_then_space() -> None:
    assert has_missed_break('He said "stop." The pilot continued.') is True


def test_has_missed_break_after_bold_markers_then_space() -> None:
    assert has_missed_break("engine failure.** The pilot continued.") is True


def test_has_missed_break_after_a_closing_paren_then_space() -> None:
    assert has_missed_break("(see note).) The pilot continued.") is True


def test_has_missed_break_after_a_semicolon_with_no_space() -> None:
    assert has_missed_break("the powerplant;the pilot continued") is True


def test_has_missed_break_is_false_for_an_ordinary_sentence_boundary() -> None:
    assert has_missed_break("The engine lost power. The pilot continued.") is False


def test_missed_break_sources_names_only_the_texts_with_a_missed_break() -> None:
    raw = {
        "narratives": [
            {
                "concatenatedFactualNarrative": 'He said "stop." The pilot continued.',
                "analysisNarrative": "The engine lost power. The pilot continued.",
                "probableCause": "the powerplant;the pilot's inaction.",
            }
        ]
    }
    assert missed_break_sources(raw) == ["factual", "probable_cause"]


def test_narratives_count_reads_the_narratives_list_length() -> None:
    assert narratives_count({"narratives": [{}, {}]}) == 2
    assert narratives_count({"narratives": [{}]}) == 1
    assert narratives_count({}) == 0


def test_later_probable_cause_differs_only_when_a_later_entry_disagrees() -> None:
    same = {
        "narratives": [{"probableCause": "Engine failure."}, {"probableCause": "Engine failure."}]
    }
    different = {
        "narratives": [{"probableCause": "Engine failure."}, {"probableCause": "Pilot error."}]
    }
    assert later_probable_cause_differs(same) is False
    assert later_probable_cause_differs(different) is True
    assert (
        later_probable_cause_differs({"narratives": [{"probableCause": "Engine failure."}]})
        is False
    )


def test_multi_aircraft_with_codes_requires_more_than_one_aircraft_carrying_a_code() -> None:
    one_coded = {
        "aircrafts": [
            {"events": [{"eventCode": "500"}]},
            {"events": [], "findings": []},
        ]
    }
    two_coded = {
        "aircrafts": [
            {"events": [{"eventCode": "500"}]},
            {"findings": [{"findingCode": "22500"}]},
        ]
    }
    assert multi_aircraft_with_codes(one_coded) is False
    assert multi_aircraft_with_codes(two_coded) is True


def test_has_nonempty_prelim_narrative_reads_every_narratives_entry() -> None:
    assert has_nonempty_prelim_narrative({"narratives": [{"prelimNarrative": "  "}]}) is False
    assert (
        has_nonempty_prelim_narrative({"narratives": [{"prelimNarrative": "Some text."}]}) is True
    )
    assert (
        has_nonempty_prelim_narrative(
            {"narratives": [{}, {"prelimNarrative": "Later entry text."}]}
        )
        is True
    )


# --- amateur-built aircraft (decision 0020) — pure functions ---


def test_is_amateur_built_reads_the_flag() -> None:
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": True}]}) is True
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": False}]}) is False
    assert is_amateur_built({"aircrafts": [{}]}) is False
    assert is_amateur_built({}) is False


def test_is_amateur_built_fails_closed_for_a_non_boolean_flag() -> None:
    """Agrees with fields.py's fail-closed rule: only `False`/absent/`None` is not amateur-built."""
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": "true"}]}) is True
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": 1}]}) is True


def test_raw_aircraft_make_and_model_read_the_recorded_values() -> None:
    raw = {"aircrafts": [{"aircraftMake": "INVENTED BUILDER", "aircraftModel": "  "}]}
    assert raw_aircraft_make(raw) == "INVENTED BUILDER"
    assert raw_aircraft_model(raw) is None


def test_model_contains_make_is_case_insensitive() -> None:
    assert model_contains_make("Vans", "RV-8 Vans Kit") is True
    assert model_contains_make("Vans", "rv-8 vans kit") is True
    assert model_contains_make("Vans", "RV-8") is False
    assert model_contains_make(None, "RV-8") is False
    assert model_contains_make("Vans", None) is False


def test_all_fixtures_have_no_missed_break_prelim_or_multi_aircraft_codes(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Sanity check: the scan's new counters are all pure functions of the raw record."""
    for raw in record_fixtures:
        assert isinstance(missed_break_sources(raw), list)
        assert isinstance(narratives_count(raw), int)
        assert isinstance(later_probable_cause_differs(raw), bool)
        assert isinstance(multi_aircraft_with_codes(raw), bool)
        assert isinstance(has_nonempty_prelim_narrative(raw), bool)


# --- docket mode (spec §8.2, §8.3): the threshold on docket text, then the filter measurement ---


def test_docket_hits_finds_a_withheld_sentence_in_a_document(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    narrative = fields.factual_narrative(raw) or ""
    docket = small_docket({1: f"[page 1 of 3]\n{narrative}\n"})
    hits = docket_hits(raw, docket, min_sentence_chars=20)
    assert hits["exam_site/text"] >= 1


def test_docket_report_names_the_threshold_and_the_filter_table() -> None:
    hits = {10: Counter({"exam_site/sentence": 2}), 20: Counter(), 40: Counter(), 80: Counter()}
    text = docket_report(hits, cases=3, documents=7)
    assert f"{THRESHOLD_LINE}20" in text
    assert "misses" in text
    assert "false denies" in text
