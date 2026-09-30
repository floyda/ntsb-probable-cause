"""scoring/coding_stats.py: counts of how the NTSB codes occurrences (decision 0094)."""

import hashlib
import re
from pathlib import Path

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.coding_stats import (
    NO_GROUP,
    STATS_NAMES,
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


def test_event_pairs_sum_every_phase_by_event_suffix() -> None:
    stats = build(
        [
            PoolCase(year=2010, group="Enroute", sequence=("402192", "402341")),
            PoolCase(year=2011, group="Enroute", sequence=("402341", "402192")),
            PoolCase(year=2016, group="Approach", sequence=("500192", "502341")),
            PoolCase(year=2017, group="Approach", sequence=("502341", "502341")),
        ],
        built_from="test",
    )
    assert stats.event_pair("192", "341") == {"both": 3, "192": 2, "341": 1}
    assert stats.event_pair("341", "341") == {"both": 0}
    assert stats.event_pair("192", "999") == {"both": 0}


def test_findings_given_event_count_flagged_findings_by_defining_event() -> None:
    aircraft_control, airspeed = "0206304044", "0106201020"
    stats = build(
        [
            PoolCase(2010, "Maneuvering", (LOC, STALL), (aircraft_control, airspeed)),
            PoolCase(2011, "Takeoff", ("300240",), (aircraft_control, aircraft_control)),
            PoolCase(2016, "Maneuvering", (LOC,), ()),
            PoolCase(2017, "Maneuvering", (STALL, LOC), (airspeed,)),
        ],
        built_from="test",
    )
    assert stats.findings_given_event("240") == (3, {aircraft_control: 2, airspeed: 1})
    assert stats.findings_given_event("241") == (1, {airspeed: 1})
    assert stats.findings_given_event("999") == (0, {})


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


# SHA-256 of S2.7's two committed files at the base of S3.1. Decision 0129 item 5: S2.7's
# statistics file stays as it is, so S2.7's numbers stay citable. A change to either file is a
# decision, not a rebuild: change a pin only with a decision record that says why.
_S27_JSON_SHA256 = "b3096de4d7556050e97b0cd89eaff3d5f20125ae9f3599aabf383648ed453cbd"
_S27_TEXT_SHA256 = "d3f3a1c08af8ffce70a69db7105a9189dacea351eff08b3a7c38e9eaf99811ec"


def test_the_s27_counts_and_their_readable_file_are_byte_identical_to_their_commit() -> None:
    files = {
        Path("src/ntsb_probable_cause/scoring/tables/coding_stats.json"): _S27_JSON_SHA256,
        Path("docs/results/s27-coding-stats.txt"): _S27_TEXT_SHA256,
    }
    for path, pinned in files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pinned, path


def test_load_stats_defaults_to_s27_and_keeps_one_object_per_name() -> None:
    assert load_stats() is load_stats("s27")
    assert "excluding dev-400 and dev-seal-400" in load_stats("s27").built_from
    assert "dev-seal-s3-400" not in load_stats("s27").built_from


def test_the_s3_counts_name_all_three_samples_and_the_decision() -> None:
    s3, s27 = load_stats("s3"), load_stats("s27")
    assert s3.built_from == (
        "development split, classes C/F/L, excluding dev-400, dev-seal-400 and dev-seal-s3-400 "
        "(scripts/coding_stats.py, decisions 0094, 129)"
    )
    assert load_stats("s3") is load_stats("s3")
    assert s3 is not s27


def test_the_s3_pool_is_the_s27_pool_less_the_new_sample() -> None:
    """Decision 0129 item 5: the pool shrinks by the new sample's cases, and by no more."""
    s3, s27 = load_stats("s3"), load_stats("s27")
    assert set(s3.cases) == set(s27.cases)
    for half, n in s3.cases.items():
        assert n < s27.cases[half], half
    removed = sum(s27.cases.values()) - sum(s3.cases.values())
    assert 0 < removed <= len(samples.sample_ids("dev-seal-s3-400"))


def test_the_committed_s3_counts_load_and_name_no_case() -> None:
    for path in (
        Path("src/ntsb_probable_cause/scoring/tables/coding_stats_s3.json"),
        Path("docs/results/s3-coding-stats.txt"),
    ):
        assert not _CASE_NUMBER.search(path.read_text()), path


def test_the_stats_names_are_the_two_stages() -> None:
    assert STATS_NAMES == ("s27", "s3")


def test_group_n_counts_every_past_case_in_a_group() -> None:
    stats = _stats()
    assert stats.group_n("Maneuvering") == 3
    assert stats.group_n("Landing") == 1  # the empty-sequence case is not counted
    assert stats.group_n(NO_GROUP) == 1
    assert stats.group_n("Cruise") == 0
