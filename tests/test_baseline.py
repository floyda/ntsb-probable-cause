"""Tests for the spike's phase-and-weather modal baseline, ported by method (spec §6.3)."""

from collections import Counter, defaultdict

from ntsb_probable_cause.fields import occurrence_codes
from ntsb_probable_cause.scoring import baseline


def test_fit_and_predict_on_fixtures_by_hand(record_fixtures: list[dict[str, object]]) -> None:
    """The model's occurrence prediction matches a by-hand grouping over the fixtures.

    This is a wiring test, not an independent check: it groups with the same
    `Counter.most_common` the implementation itself uses, so it would not catch a shared
    counting bug. `test_finding_prediction_is_the_sample_wide_modal_codes_not_per_key` below
    checks findings against a hand-computed expectation on a small synthetic set instead.
    """
    model = baseline.fit(record_fixtures)
    # Work the expected value by hand from the nine fixtures: group by key_of, count primary codes.
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for raw in record_fixtures:
        groups[baseline.key_of(raw)][occurrence_codes(raw)[0]] += 1
    for raw in record_fixtures:
        expected = tuple(c for c, _ in groups[baseline.key_of(raw)].most_common(3))
        occ, _ = baseline.predict(model, raw)
        assert occ == expected


def _case(
    phase: str, weather: str, primary_code: str, finding_codes: tuple[str, ...]
) -> dict[str, object]:
    """Build a minimal raw record with one defining event and ordered findings."""
    return {
        "aircrafts": [
            {
                "events": [
                    {
                        "isDefiningEvent": True,
                        "sequenceNumber": 1,
                        "cicttPhaseSOEGroup": phase,
                        "eventCode": primary_code,
                    }
                ],
                "findings": [
                    {"findingNumber": i + 1, "findingCode": code}
                    for i, code in enumerate(finding_codes)
                ],
            }
        ],
        "weatherConditions": [{"accidentSiteCondition": weather}],
    }


def test_finding_prediction_is_the_sample_wide_modal_codes_not_per_key() -> None:
    """Findings follow the spike's single sample-wide modal occurrence code, not the case's key.

    The spike's `finding_code_baseline` (`ntsb_spike/src/ntsb_spike/baseline.py:44-58`) predicts
    one fixed top-3 finding set for every case: the finding codes most common among cases whose
    primary occurrence code is the single most common in the whole sample, regardless of any
    case's own phase|weather key. Two cases below share no key but must get the same finding
    prediction.

    Hand-computed expectation (not via the implementation's own Counter/most_common):
    - Key "TAKEOFF|VMC" cases have primary codes AAA, AAA, BBB, AAA -> key top-3 (AAA, BBB).
    - Key "LANDING|IMC" cases have primary codes CCC, CCC, BBB -> key top-3 (CCC, BBB).
    - Sample-wide primary counts: AAA=3, BBB=2, CCC=2 -> the modal primary code is AAA.
    - Findings of the three AAA cases: (F1, F2), (F1,), (F5,) -> exploded F1, F2, F1, F5 ->
      counts F1=2, F2=1, F5=1 -> top-3 (F1, F2, F5), in first-seen order for the tied pair.
    """
    takeoff_vmc_aaa_1 = _case("TAKEOFF", "VMC", "AAA", ("F1", "F2"))
    takeoff_vmc_aaa_2 = _case("TAKEOFF", "VMC", "AAA", ("F1",))
    takeoff_vmc_bbb = _case("TAKEOFF", "VMC", "BBB", ("F9",))
    takeoff_vmc_aaa_3 = _case("TAKEOFF", "VMC", "AAA", ("F5",))
    landing_imc_ccc_1 = _case("LANDING", "IMC", "CCC", ("F3",))
    landing_imc_ccc_2 = _case("LANDING", "IMC", "CCC", ("F3", "F4"))
    landing_imc_bbb = _case("LANDING", "IMC", "BBB", ("F9", "F9"))
    raws = [
        takeoff_vmc_aaa_1,
        takeoff_vmc_aaa_2,
        takeoff_vmc_bbb,
        landing_imc_ccc_1,
        landing_imc_ccc_2,
        landing_imc_bbb,
        takeoff_vmc_aaa_3,
    ]

    model = baseline.fit(raws)

    occ_takeoff, findings_takeoff = baseline.predict(model, takeoff_vmc_aaa_1)
    occ_landing, findings_landing = baseline.predict(model, landing_imc_ccc_1)

    assert occ_takeoff == ("AAA", "BBB")
    assert occ_landing == ("CCC", "BBB")
    assert occ_takeoff != occ_landing
    assert findings_takeoff == ("F1", "F2", "F5")
    assert findings_landing == ("F1", "F2", "F5")


def test_stratified_draw_is_deterministic_and_proportional() -> None:
    """The draw is reproducible under a fixed seed and preserves stratum proportions."""
    rows = [(f"c{i}", "A" if i < 80 else "B") for i in range(100)]
    ids = baseline.stratified_draw(rows, 10, seed=7)
    assert ids == baseline.stratified_draw(rows, 10, seed=7)
    assert len(ids) == 10
    assert sum(1 for i in ids if int(i[1:]) < 80) == 8
