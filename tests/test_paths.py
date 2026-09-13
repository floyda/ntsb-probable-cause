from ntsb_probable_cause.paths import (
    is_under,
    is_well_formed,
    normalise_path,
    overlaps,
    resolve_path,
)

RECORD: dict[str, object] = {
    "a": {"b": [{"c": 1}, {"c": 2}]},
    "s": "text",
}


def test_resolves_nested_index() -> None:
    assert resolve_path(RECORD, "a.b[1].c") == 2


def test_missing_hop_returns_none() -> None:
    assert resolve_path(RECORD, "a.x.c") is None


def test_index_out_of_range_returns_none() -> None:
    assert resolve_path(RECORD, "a.b[5].c") is None


def test_wrong_type_returns_none() -> None:
    assert resolve_path(RECORD, "s[0]") is None
    assert resolve_path(RECORD, "s.x") is None


def test_malformed_segment_returns_none() -> None:
    assert resolve_path(RECORD, "a.b[].c") is None


def test_normalise_replaces_indices() -> None:
    assert normalise_path("aircrafts[0].events[3].eventCode") == "aircrafts[].events[].eventCode"


def test_is_under_compares_whole_segments() -> None:
    assert is_under("aircrafts[0].events[].eventCode", "aircrafts[].events[]")
    assert is_under("narratives[0].probableCause", "narratives[].probableCause")
    assert not is_under("narratives[0].probableCauseDate", "narratives[].probableCause")
    assert not is_under("aircrafts[0].aircraftMake", "aircrafts[].events[]")


def test_is_under_ignores_bracket_presence() -> None:
    assert is_under("aircrafts[0].events", "aircrafts[].events[]")
    assert is_under("richNarratives[0].x", "richNarratives")


def test_overlaps_catches_a_parent_path() -> None:
    assert overlaps("aircrafts[0]", "aircrafts[].events[]")
    assert overlaps("narratives[0]", "narratives[].probableCause")


def test_overlaps_catches_a_child_path() -> None:
    assert overlaps("aircrafts[0].events[].eventCode", "aircrafts[].events[]")


def test_overlaps_false_for_unrelated_paths() -> None:
    assert not overlaps("aircrafts[0].aircraftMake", "aircrafts[].events[]")


def test_is_well_formed_accepts_declared_grammar() -> None:
    assert is_well_formed("aircrafts[0].events[].eventCode")
    assert is_well_formed("narratives[0].probableCause")
    assert is_well_formed("aircrafts")


def test_is_well_formed_rejects_unclosed_bracket() -> None:
    assert not is_well_formed("aircrafts[0.events")
