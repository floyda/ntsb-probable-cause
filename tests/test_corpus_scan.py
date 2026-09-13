import re
from pathlib import Path

import pytest
from scripts.corpus_scan import THRESHOLD_LINE, choose_threshold, duplication_share, leak_kinds

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
