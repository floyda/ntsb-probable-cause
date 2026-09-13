from ntsb_probable_cause.paths import is_under, normalise_path, resolve_path

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
