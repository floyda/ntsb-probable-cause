"""Tests for the spike's phase-and-weather modal baseline, ported by method (spec §6.3)."""

from collections import Counter, defaultdict

from ntsb_probable_cause.fields import occurrence_codes
from ntsb_probable_cause.scoring import baseline


def test_fit_and_predict_on_fixtures_by_hand(record_fixtures: list[dict[str, object]]) -> None:
    """The model's occurrence prediction matches a by-hand grouping over the fixtures."""
    model = baseline.fit(record_fixtures)
    # Work the expected value by hand from the nine fixtures: group by key_of, count primary codes.
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for raw in record_fixtures:
        groups[baseline.key_of(raw)][occurrence_codes(raw)[0]] += 1
    for raw in record_fixtures:
        expected = tuple(c for c, _ in groups[baseline.key_of(raw)].most_common(3))
        occ, _ = baseline.predict(model, raw)
        assert occ == expected


def test_stratified_draw_is_deterministic_and_proportional() -> None:
    """The draw is reproducible under a fixed seed and preserves stratum proportions."""
    rows = [(f"c{i}", "A" if i < 80 else "B") for i in range(100)]
    ids = baseline.stratified_draw(rows, 10, seed=7)
    assert ids == baseline.stratified_draw(rows, 10, seed=7)
    assert len(ids) == 10
    assert sum(1 for i in ids if int(i[1:]) < 80) == 8
