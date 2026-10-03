"""The confidence curve, its three-group test, the sorting figure and the abstain cut-off."""

import json
import math
import random
from pathlib import Path
from statistics import NormalDist

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import calibration
from ntsb_probable_cause.scoring.calibration import (
    ABSTAIN_BELOW,
    FAMILY_ALPHA,
    GROUPS,
    Curve,
    GroupCheck,
    abstains,
    calibrated,
    check_rising,
    fit,
    load_curve,
    sorting,
    three_groups,
)
from ntsb_probable_cause.scoring.metrics import wilson


def test_fit_recovers_known_parameters() -> None:
    rng = random.Random(7)  # noqa: S311 -- statistics, not security
    stated = [rng.random() for _ in range(5000)]
    right = [rng.random() < 1 / (1 + math.exp(-(-2 + 1.5 * x))) for x in stated]
    curve = fit(stated, right)
    assert curve.intercept == pytest.approx(-2, abs=0.15)
    assert curve.slope == pytest.approx(1.5, abs=0.25)


@pytest.mark.parametrize("outcome", [True, False])
def test_fit_refuses_data_with_one_outcome(outcome: bool) -> None:
    with pytest.raises(ValueError, match="both right and wrong"):
        fit([0.1, 0.5, 0.9], [outcome] * 3)


def test_fit_refuses_mismatched_and_empty_input() -> None:
    with pytest.raises(ValueError, match="same, non-zero length"):
        fit([0.1, 0.2], [True])
    with pytest.raises(ValueError, match="same, non-zero length"):
        fit([], [])


def test_fit_refuses_one_stated_value() -> None:
    with pytest.raises(ValueError, match="singular"):
        fit([0.5, 0.5, 0.5, 0.5], [True, False, True, False])


def test_fit_refuses_perfectly_separated_data() -> None:
    # The likelihood has no maximum here; the weights shrink to nothing.
    with pytest.raises(ValueError, match="singular"):
        fit([0.1, 0.2, 0.8, 0.9], [False, False, True, True])


def test_curve_is_increasing_and_half_at_its_midpoint() -> None:
    curve = Curve(intercept=-2.0, slope=1.5)
    values = [curve.p(x / 10) for x in range(11)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert curve.p(2.0 / 1.5) == pytest.approx(0.5)


def test_three_groups_split_four_three_three_with_family_interval() -> None:
    items = [(f"c{i}", i / 10, i >= 5) for i in range(10)]
    groups = three_groups(items)
    assert [g.n for g in groups] == [4, 3, 3]
    z = 2.3940
    assert z == pytest.approx(NormalDist().inv_cdf(1 - FAMILY_ALPHA / (2 * GROUPS)), abs=1e-3)
    assert groups[0].right == 0
    assert groups[1].right == 2  # fitted 0.4, 0.5, 0.6 -> right only for 0.5 and 0.6
    assert groups[2].right == 3
    assert groups[0].mean_fitted == pytest.approx(0.15)
    assert (groups[1].low, groups[1].high) == pytest.approx(
        wilson(2, 3, z=NormalDist().inv_cdf(1 - FAMILY_ALPHA / (2 * GROUPS)))
    )


def test_three_groups_sort_ties_by_case_id() -> None:
    items = [("b", 0.3, True), ("a", 0.3, False), ("c", 0.3, False), ("d", 0.3, True)]
    # Ties: order is a, b, c, d; with 4 items the groups are 2, 1, 1.
    groups = three_groups(items)
    assert [g.n for g in groups] == [2, 1, 1]
    assert [g.right for g in groups] == [1, 0, 1]
    assert three_groups(list(reversed(items))) == groups


def test_three_groups_need_three_items() -> None:
    with pytest.raises(ValueError, match="at least"):
        three_groups([("a", 0.1, True), ("b", 0.2, False)])


def _group(mean: float, right: int, n: int, low: float, high: float) -> GroupCheck:
    return GroupCheck(n=n, mean_fitted=mean, right=right, low=low, high=high)


def test_inside_and_calibrated() -> None:
    ok = _group(0.2, 20, 100, 0.1, 0.3)
    assert ok.inside
    assert _group(0.3, 20, 100, 0.1, 0.3).inside  # the edge counts
    out = _group(0.5, 20, 100, 0.1, 0.3)
    assert not out.inside
    assert calibrated([ok, ok, ok])
    assert not calibrated([ok, out, ok])


def test_sorting_is_high_minus_low_with_a_wald_interval() -> None:
    low = _group(0.2, 20, 100, 0.0, 1.0)
    mid = _group(0.3, 30, 100, 0.0, 1.0)
    high = _group(0.4, 50, 100, 0.0, 1.0)
    diff, lo, hi = sorting([low, mid, high])
    assert diff == pytest.approx(0.30)
    half = 1.96 * math.sqrt(0.2 * 0.8 / 100 + 0.5 * 0.5 / 100)
    assert lo == pytest.approx(0.30 - half)
    assert hi == pytest.approx(0.30 + half)


def test_sorting_needs_three_groups() -> None:
    with pytest.raises(ValueError, match="needs 3 groups"):
        sorting([_group(0.2, 1, 10, 0.0, 1.0)])


def test_abstain_cut_off() -> None:
    assert ABSTAIN_BELOW == 0.164
    assert abstains(0.163)
    assert not abstains(0.164)


def test_load_curve_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"intercept": -1.5, "slope": 0.8, "built_from": "x"}))
    assert load_curve(path) == Curve(-1.5, 0.8)


@pytest.mark.parametrize("missing", ["intercept", "slope"])
def test_load_curve_refuses_a_file_missing_a_key(tmp_path: Path, missing: str) -> None:
    body = {"intercept": -1.5, "slope": 0.8}
    del body[missing]
    path = tmp_path / "c.json"
    path.write_text(json.dumps(body))
    with pytest.raises(ConfigurationError, match=missing):
        load_curve(path)


def test_load_curve_refuses_a_file_that_is_not_json_numbers(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"intercept": "a", "slope": 1}))
    with pytest.raises(ConfigurationError, match="must be a number"):
        load_curve(path)
    path.write_text("not json")
    with pytest.raises(ConfigurationError, match="not valid JSON"):
        load_curve(path)


def test_load_curve_names_the_missing_package_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calibration, "CURVE_FILE", "no_such_curve.json")
    with pytest.raises(ConfigurationError, match=r"no_such_curve\.json"):
        load_curve()


@pytest.mark.parametrize("slope", [0.0, -0.4])
def test_load_curve_refuses_a_curve_that_does_not_rise(tmp_path: Path, slope: float) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"intercept": -1.0, "slope": slope}))
    with pytest.raises(ConfigurationError, match=r"c\.json.*must rise"):
        load_curve(path)


def test_check_rising_accepts_a_rising_curve_and_refuses_the_rest() -> None:
    check_rising(Curve(-2.0, 0.1))
    for bad in (Curve(-2.0, 0.0), Curve(-2.0, -1.0)):
        with pytest.raises(ValueError, match="must rise"):
            check_rising(bad)
    with pytest.raises(ValueError, match="finite"):
        check_rising(Curve(float("nan"), 1.0))


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_load_curve_refuses_numbers_that_are_not_finite(tmp_path: Path, literal: str) -> None:
    path = tmp_path / "c.json"
    path.write_text(f'{{"intercept": {literal}, "slope": 1.0}}')
    with pytest.raises(ConfigurationError, match="finite"):
        load_curve(path)


def test_fit_on_larger_separated_data_raises_value_error_not_overflow() -> None:
    with pytest.raises(ValueError, match=r"singular|converge"):
        fit([i / 100 for i in range(100)], [i >= 50 for i in range(100)])


def test_curve_p_does_not_overflow_for_extreme_values() -> None:
    assert Curve(intercept=-5000.0, slope=1.0).p(0.0) == 0.0
    assert Curve(5000.0, 1.0).p(0.0) == 1.0


def test_calibrated_needs_exactly_three_groups() -> None:
    ok = _group(0.2, 20, 100, 0.1, 0.3)
    for groups in ([], [ok], [ok, ok], [ok, ok, ok, ok]):
        with pytest.raises(ValueError, match="needs 3 groups"):
            calibrated(groups)


def test_the_committed_curve_loads_and_rises() -> None:
    """The packaged file, fitted by ``scripts/s32_calibration.py`` (S3.2 Task 9), is read as is."""
    curve = load_curve()
    check_rising(curve)
    assert curve.p(0.9) > curve.p(0.1)
    stored = json.loads(
        (Path(calibration.__file__).parent / "tables" / calibration.CURVE_FILE).read_text()
    )
    assert curve.intercept == stored["intercept"]
    assert curve.slope == stored["slope"]
    assert stored["n"] == 785
