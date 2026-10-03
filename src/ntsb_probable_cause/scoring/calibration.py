"""The confidence curve, its three-group test on held-out, and the abstain cut-off (spec §8).

At its answer the loop states a confidence, and that number barely sorts right from wrong.
Decision 0126: code, not the model, turns the stated number into the confidence shown. The code
is a logistic curve with two numbers, fitted once on the noise-floor runs and frozen in
``scoring/tables/calibration_s3.json`` before any held-out run. This module holds the pieces:

* :func:`fit` finds the two numbers by Newton-Raphson (plain Python, so the result is the same
  on every machine);
* :func:`three_groups` and :func:`calibrated` are the test of result 3 (spec §8.3);
* :func:`sorting` is the figure that is reported and not tested;
* :func:`abstains` is the cut-off of spec §8.4.

Nothing here reads a case. Inputs are numbers and a case id used only to break ties.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from statistics import NormalDist
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.metrics import wilson

# The no-model baseline's top-1 on development (``docs/results/s1-baseline.txt``, spec §8.4). It
# is a meaning ("a lookup table would do better"), not an optimum.
ABSTAIN_BELOW: Final = 0.164
# The chance that a perfectly calibrated curve fails the test overall, shared by the groups.
FAMILY_ALPHA: Final = 0.05
GROUPS: Final = 3
CURVE_FILE: Final = "calibration_s3.json"  # under scoring/tables/
_MAX_STEPS: Final = 100
_WALD_Z: Final = 1.96
_SETTLED: Final = 1e-12  # a Newton step this small changes neither number


def _logistic(z: float) -> float:
    """``1 / (1 + exp(-z))`` without overflow, whatever the size of ``z``."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(frozen=True)
class Curve:
    """A logistic curve from stated confidence to the chance the first occurrence code is right."""

    intercept: float
    slope: float

    def p(self, stated: float) -> float:
        """The fitted chance of being right when the model stated ``stated``."""
        return _logistic(self.intercept + self.slope * stated)


@dataclass(frozen=True)
class GroupCheck:
    """One of the three groups: its size, its average fitted value and the share right.

    ``low`` and ``high`` bound the share right at the family confidence level.
    """

    n: int
    mean_fitted: float
    right: int
    low: float
    high: float

    @property
    def inside(self) -> bool:
        """Whether the average fitted value lies inside the interval for the share right."""
        return self.low <= self.mean_fitted <= self.high


def check_rising(curve: Curve) -> None:
    """Refuse a curve that is not finite or does not rise (spec §8.2: "always rising").

    A curve that does not rise would turn a higher stated confidence into a lower chance of being
    right. The fitting script calls this before it writes a curve; :func:`load_curve` calls it
    before it returns one.

    Raises:
        ValueError: A number is not finite, or the slope is zero or negative.
    """
    if not (math.isfinite(curve.intercept) and math.isfinite(curve.slope)):
        raise ValueError("the curve's numbers must be finite")
    if curve.slope <= 0.0:
        raise ValueError(f"the curve must rise (spec §8.2), but its slope is {curve.slope}")


def fit(stated: Sequence[float], right: Sequence[bool]) -> Curve:
    """Fit the curve by Newton-Raphson on the log-likelihood.

    Args:
        stated: The confidence the model stated for each scored answer.
        right: Whether each answer's first occurrence code was right.

    Returns:
        The curve with the two fitted numbers.

    Raises:
        ValueError: The lists differ in length or are empty; every answer has the same outcome;
            every stated value is the same; the data are separated perfectly (no finite fit
            exists); or the steps did not settle.
    """
    if len(stated) != len(right) or not stated:
        raise ValueError("stated and right must be the same, non-zero length")
    if all(right) or not any(right):
        raise ValueError("a logistic curve needs both right and wrong answers")
    a = b = 0.0
    for _ in range(_MAX_STEPS):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(stated, right, strict=True):
            p = _logistic(a + b * x)
            w = p * (1.0 - p)
            g0 += float(y) - p
            g1 += (float(y) - p) * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        if det <= 0.0:
            raise ValueError(
                "the fit is singular: the stated confidences are all the same, "
                "or the data are separated perfectly"
            )
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a, b = a + da, b + db
        if abs(da) < _SETTLED and abs(db) < _SETTLED:
            return Curve(a, b)
    raise ValueError(f"the fit did not converge in {_MAX_STEPS} steps")


def three_groups(
    fitted: Sequence[tuple[str, float, bool]],
) -> tuple[GroupCheck, GroupCheck, GroupCheck]:
    """Put scored answers in three equal groups by fitted value and check each one (spec §8.3).

    Answers are sorted by ``(fitted value, case id)``, so a tie never depends on input order. A
    remainder goes to the first groups: ten answers make groups of 4, 3 and 3. Each group's
    interval for the share right is a Wilson interval at ``1 - FAMILY_ALPHA / GROUPS``, so a
    perfectly calibrated curve fails somewhere by chance at most once in twenty.

    Args:
        fitted: One ``(case id, fitted value, right)`` row per scored answer.

    Raises:
        ValueError: There are fewer answers than groups.
    """
    if len(fitted) < GROUPS:
        raise ValueError(f"at least {GROUPS} answers are needed for {GROUPS} groups")
    z = NormalDist().inv_cdf(1 - FAMILY_ALPHA / (2 * GROUPS))
    ordered = sorted(fitted, key=lambda row: (row[1], row[0]))
    size, extra = divmod(len(ordered), GROUPS)
    checks: list[GroupCheck] = []
    start = 0
    for index in range(GROUPS):
        stop = start + size + (1 if index < extra else 0)
        rows = ordered[start:stop]
        right = sum(1 for _, _, ok in rows if ok)
        low, high = wilson(right, len(rows), z=z)
        checks.append(
            GroupCheck(
                n=len(rows),
                mean_fitted=sum(p for _, p, _ in rows) / len(rows),
                right=right,
                low=low,
                high=high,
            )
        )
        start = stop
    return checks[0], checks[1], checks[2]


def calibrated(groups: Sequence[GroupCheck]) -> bool:
    """Whether every group's average fitted value lies inside its interval (result 3).

    Raises:
        ValueError: ``groups`` does not hold exactly three groups.
    """
    if len(groups) != GROUPS:
        raise ValueError(f"calibrated needs {GROUPS} groups, got {len(groups)}")
    return all(group.inside for group in groups)


def sorting(groups: Sequence[GroupCheck]) -> tuple[float, float, float]:
    """How well the confidence sorts right from wrong: the high group's share right minus the low's.

    Reported, not tested (spec §8.3). The interval is a Wald 95% interval for the difference of
    two shares.

    Returns:
        The difference, its low end and its high end.

    Raises:
        ValueError: ``groups`` does not hold three groups.
    """
    if len(groups) != GROUPS:
        raise ValueError(f"sorting needs {GROUPS} groups, got {len(groups)}")
    first, last = groups[0], groups[-1]
    p1, p3 = last.right / last.n, first.right / first.n
    diff = p1 - p3
    half = _WALD_Z * math.sqrt(p1 * (1 - p1) / last.n + p3 * (1 - p3) / first.n)
    return diff, diff - half, diff + half


def abstains(p: float) -> bool:
    """Whether the loop abstains: its fitted chance is below the no-model baseline (spec §8.4)."""
    return p < ABSTAIN_BELOW


def load_curve(path: Path | None = None) -> Curve:
    """Load the frozen curve.

    Args:
        path: A JSON file with ``intercept`` and ``slope``. By default, the package file
            ``scoring/tables/calibration_s3.json``, committed with the results file that printed
            its numbers (spec §8.2).

    Raises:
        ConfigurationError: The file is missing, is not JSON, lacks a number for either key, holds
            a number that is not finite, or holds a curve that does not rise (spec §8.2).
    """
    if path is None:
        resource = resources.files("ntsb_probable_cause.scoring").joinpath("tables", CURVE_FILE)
        if not resource.is_file():
            raise ConfigurationError(f"the frozen curve file {CURVE_FILE} is missing")
        text = resource.read_text()
        name = CURVE_FILE
    else:
        if not path.is_file():
            raise ConfigurationError(f"the curve file {path} is missing")
        text = path.read_text()
        name = str(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{name} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"{name} must hold a JSON object")
    for key in ("intercept", "slope"):
        if key not in data:
            raise ConfigurationError(f"{name} has no {key!r}")
        if isinstance(data[key], bool) or not isinstance(data[key], int | float):
            raise ConfigurationError(f"{name}: {key!r} must be a number")
    curve = Curve(float(data["intercept"]), float(data["slope"]))
    try:
        check_rising(curve)
    except ValueError as exc:
        raise ConfigurationError(f"{name}: {exc}") from exc
    return curve
