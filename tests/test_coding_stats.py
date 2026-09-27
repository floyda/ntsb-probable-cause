"""scoring/coding_stats.py: counts of how the NTSB codes occurrences (decision 0094)."""

import re
from pathlib import Path

from ntsb_probable_cause.scoring.coding_stats import (
    NO_GROUP,
    CodingStats,
    PoolCase,
    build,
    load_stats,
)

LOC, STALL, CFIT = "452240", "452241", "452120"

CASES = [
    PoolCase(year=2010, group="Maneuvering", sequence=(LOC, STALL)),
    PoolCase(year=2012, group="Maneuvering", sequence=(LOC, STALL, CFIT)),
    PoolCase(year=2016, group="Maneuvering", sequence=(STALL, LOC)),
    PoolCase(year=2017, group="Landing", sequence=("552300",)),
    PoolCase(year=2018, group=None, sequence=(CFIT,)),
    PoolCase(year=2019, group="Landing", sequence=()),  # no codes: not counted
]


def _stats() -> CodingStats:
    return build(CASES, built_from="test")


def test_cases_are_counted_by_half_and_empty_sequences_skipped() -> None:
    stats = _stats()
    assert stats.cases == {"2009-2014": 2, "2015-2019": 3}


def test_present_and_defining_given_present() -> None:
    stats = _stats()
    assert stats.present_n(STALL) == 3
    assert stats.defining_given(STALL) == {LOC: 2, STALL: 1}
    assert stats.defining_given(CFIT) == {LOC: 1, CFIT: 1}


def test_pairs_count_both_and_each_side_defining() -> None:
    stats = _stats()
    assert stats.pair(STALL, LOC) == {"both": 3, LOC: 2, STALL: 1}
    assert stats.pair(LOC, "999999") == {"both": 0}


def test_groups_give_defining_codes_and_phase_prefixes() -> None:
    stats = _stats()
    assert stats.group_defining_n("Maneuvering", LOC) == 2
    assert stats.group_top("Maneuvering", 2) == [LOC, STALL]
    assert stats.group_phases("Maneuvering") == {"452": 3}
    assert stats.group_defining_n(NO_GROUP, CFIT) == 1


def test_defining_n_counts_over_every_group_and_half() -> None:
    stats = _stats()
    assert stats.defining_n(LOC) == 2
    assert stats.defining_n(STALL) == 1
    assert stats.defining_n(CFIT) == 1


def test_json_round_trip() -> None:
    stats = _stats()
    assert CodingStats.model_validate_json(stats.to_json()) == stats


_CASE_NUMBER = re.compile(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}[A-Z]?\b")


def test_the_committed_counts_load_and_name_no_case() -> None:
    stats = load_stats()
    assert "excluding dev-400 and dev-seal-400" in stats.built_from
    for path in (
        Path("src/ntsb_probable_cause/scoring/tables/coding_stats.json"),
        Path("docs/results/s27-coding-stats.txt"),
    ):
        assert not _CASE_NUMBER.search(path.read_text()), path


def test_group_n_counts_every_past_case_in_a_group() -> None:
    stats = _stats()
    assert stats.group_n("Maneuvering") == 3
    assert stats.group_n("Landing") == 1  # the empty-sequence case is not counted
    assert stats.group_n(NO_GROUP) == 1
    assert stats.group_n("Cruise") == 0
