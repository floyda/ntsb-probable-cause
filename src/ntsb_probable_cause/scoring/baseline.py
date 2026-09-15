"""The spike's phase-and-weather modal baseline, ported by method (spec §6.3).

The spike's ``modal_baseline`` (`ntsb_spike/src/ntsb_spike/baseline.py`) predicts, for each
case, the most common primary occurrence code among cases sharing its phase-of-flight and
weather-condition key, and used the three most common as its top-3. It fits and scores on the
same in-sample draw for the reproduction row; the honest row (Task 13) fits on development and
scores on held-out instead, using the same `fit`/`predict` pair. `stratified_draw` ports the
spike's `stratified_sample` (`ntsb_spike/src/ntsb_spike/common.py`): each stratum contributes
``max(1, round(share * n))`` members, then the pooled picks are shuffled and truncated to `n`.
"""

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceRole


@dataclass(frozen=True)
class BaselineModel:
    """Most common codes per phase|weather key, and per primary code for findings.

    Attributes:
        top_by_key: ``"phase|weather"`` to up to three most common primary occurrence codes,
            most common first.
        findings_by_code: primary occurrence code to its top-3 finding codes (ten digits).
        fallback: the unconditional top-3 primary occurrence codes, used when a case's key was
            never seen while fitting.
    """

    top_by_key: Mapping[str, tuple[str, ...]]
    findings_by_code: Mapping[str, tuple[str, ...]]
    fallback: tuple[str, ...]


def _extract(raw: Mapping[str, object], role: EvidenceRole) -> str:
    """Read one evidence role's value as a string, or "" if absent.

    Args:
        raw: the case record.
        role: the evidence role to read.

    Returns:
        The extracted value as a string, or the empty string if the field is unset.
    """
    field = next(f for f in fields.EVIDENCE_FIELDS if f.role is role)
    value = field.extract(raw)
    return str(value) if value is not None else ""


def key_of(raw: Mapping[str, object]) -> str:
    """Compute the spike's conditioning key: phase of flight and weather condition.

    Args:
        raw: the case record.

    Returns:
        ``"{phase_of_flight}|{weather_condition}"`` via the evidence extractors.
    """
    phase = _extract(raw, EvidenceRole.PHASE_OF_FLIGHT)
    weather = _extract(raw, EvidenceRole.WEATHER_CONDITION)
    return f"{phase}|{weather}"


def fit(raws: Iterable[Mapping[str, object]]) -> BaselineModel:
    """Count primary occurrence codes per key and finding codes per primary code.

    Args:
        raws: the case records to fit on (development split, or the same in-sample draw being
            scored, per spec §6.3).

    Returns:
        A `BaselineModel` with the top-3 codes for every key seen, the top-3 finding codes for
        every primary code seen, and the unconditional top-3 as a fallback.
    """
    by_key: dict[str, Counter[str]] = defaultdict(Counter)
    by_code: dict[str, Counter[str]] = defaultdict(Counter)
    overall: Counter[str] = Counter()
    for raw in raws:
        codes = fields.occurrence_codes(raw)
        if not codes:
            continue
        primary = codes[0]
        by_key[key_of(raw)][primary] += 1
        overall[primary] += 1
        by_code[primary].update(fields.finding_codes(raw))
    return BaselineModel(
        top_by_key={k: tuple(c for c, _ in v.most_common(3)) for k, v in by_key.items()},
        findings_by_code={k: tuple(c for c, _ in v.most_common(3)) for k, v in by_code.items()},
        fallback=tuple(c for c, _ in overall.most_common(3)),
    )


def predict(
    model: BaselineModel, raw: Mapping[str, object]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Predict top-3 occurrence codes for the case's key, and top-3 findings for the top-1 code.

    Args:
        model: a fitted `BaselineModel`.
        raw: the case record to predict for.

    Returns:
        A pair of (occurrence top-3, finding top-3). The occurrence prediction falls back to
        the model's unconditional top-3 when the case's key was never seen while fitting.
    """
    occ = model.top_by_key.get(key_of(raw), model.fallback)
    findings = model.findings_by_code.get(occ[0], ()) if occ else ()
    return occ, findings


def stratified_draw(rows: Sequence[tuple[str, str]], n: int, seed: int = 7) -> list[str]:
    """Draw a stratified sample of case ids, the spike's ``stratified_sample`` rule.

    Each stratum (grouped by the second element of each row, the primary code) contributes
    ``max(1, round(share * n))`` members, sampled without replacement; the pooled picks are
    then shuffled and truncated to `n`.

    Args:
        rows: ``(case_id, primary_code)`` pairs to draw from.
        n: the target sample size.
        seed: the random seed (the spike used pandas' ``sample(random_state=7)``; see the
            Deviations note in the plan for why the draw itself differs from a literal port).

    Returns:
        The drawn case ids, in shuffled order, truncated to `n`.
    """
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security-sensitive
    strata: dict[str, list[str]] = defaultdict(list)
    for case_id, code in rows:
        strata[code].append(case_id)
    picked: list[str] = []
    for code in sorted(strata):
        members = strata[code]
        k = max(1, round(len(members) / len(rows) * n))
        picked.extend(rng.sample(sorted(members), min(k, len(members))))
    rng.shuffle(picked)
    return picked[:n]
