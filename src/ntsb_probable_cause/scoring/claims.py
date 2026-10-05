"""The rules of S3.2's claim, in one pure module (spec §6, §7, §9.2, §10).

The registration fixes these rules before any held-out case is read. They live here, in
code, so that the report, the calibration script and the tests all apply the same words:

* a guard refusal removes a case from both arms; every other failure counts as wrong (§7.3);
* the difference between arms is a paired mean with the project's bootstrap interval (§7.2);
* beats, matches, worse and undecided are read from that interval (§7.2);
* the cost band compares billed cost, lower, equal or greater (§6);
* the loop is warranted, and result 2 holds, by two small tables (§7.4, §9.2);
* the headline is one of a fixed set of sentences (§10).

This module imports nothing from ``agent``: the library never imports the agent.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from ntsb_probable_cause.scoring.metrics import CaseScores, bootstrap_mean
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord

Metric = Literal["top1", "top3", "recall10"]
Outcome = Literal["beats", "matches", "worse", "undecided"]
CostBand = Literal["lower", "equal", "greater"]

MARGIN: Final = 0.06
"""Six points, as a fraction: the margin of "matches" (spec §7.2)."""

COST_BAND: Final = 0.10
"""Ten per cent: the band of "equal" cost (spec §6)."""


@dataclass(frozen=True)
class Paired:
    """A paired difference (first arm minus second), in fractions: 0.01 is one point."""

    mean: float
    low: float
    high: float
    n: int


@dataclass(frozen=True)
class Billed:
    """What a run cost: the billed figure and the computed one, kept apart (spec §6).

    Attributes:
        usd: the figure that decides the cost band.
        computed_usd: every token at the list rate (printed beside, never deciding).
        is_billed: False when the computed figure stood in because no bill was reported.
    """

    usd: float
    computed_usd: float
    is_billed: bool


@dataclass(frozen=True)
class SavingSplit:
    """Where a saving comes from (spec §10): the work done, and each arm's cache discount."""

    work_usd: float
    """Loop computed minus arm B computed; positive when the loop did more work."""
    loop_discount_usd: float
    """Loop computed minus loop billed."""
    armb_discount_usd: float
    """Arm B computed minus arm B billed."""


def is_guard_refusal(case: CaseResult) -> bool:
    """Whether the leakage guard refused a document of this case (spec §7.3).

    The runner writes ``"leak: <message>"`` for arm B and arm C alike (``leaked_case``). The
    loop's own stop reason ``"failed: leak"`` is accepted as well. This is not only a safety
    net: arm B's tool post-pass (``agent/armb.py``) writes the loop's stop reason as it is, so
    a record in that form does reach a run folder, and it must leave both arms too.
    """
    return case.failure is not None and (
        case.failure.startswith("leak") or case.failure == "failed: leak"
    )


def answered(case: CaseResult) -> CaseScores | None:
    """The case's scores if it answered and did not fail, else None (decision 0136 item 1)."""
    return case.scores if case.failure is None and case.steps else None


def per_case(cases: Sequence[CaseResult], metric: Metric) -> dict[str, float]:
    """One value per case: a failure counts as wrong; a guard refusal is left out (spec §7.3).

    An abstained case is wrong on top-1 and top-3 because ``metrics.score_case`` already
    scores it ``False``. For ``recall10``, a failed case scores 0 only when the NTSB flagged
    findings in the cause, and a scored case with no recall (nothing flagged) is left out.

    Args:
        cases: one run's case results.
        metric: ``top1`` and ``top3`` are occurrence scores; ``recall10`` is finding recall@10.

    Returns:
        Case id to value, 0.0 or 1.0 for the occurrence metrics.
    """
    values: dict[str, float] = {}
    for case in cases:
        if is_guard_refusal(case):
            continue
        scores = answered(case)
        if metric == "recall10":
            if scores is None:
                if case.verdict_findings_in_cause:
                    values[case.case_id] = 0.0
            elif scores.finding_recall_10 is not None:
                values[case.case_id] = scores.finding_recall_10
            continue
        hit = (
            False
            if scores is None
            else (scores.occurrence_top1 if metric == "top1" else scores.occurrence_top3)
        )
        values[case.case_id] = float(hit)
    return values


def _refuse_different_cases(a: Sequence[CaseResult], b: Sequence[CaseResult]) -> None:
    """Refuse two runs that do not cover the same cases (spec §6, §7.2: "the same cases").

    The check is made before any guard refusal is removed. The message gives counts only, never
    a case id.
    """
    ids_a = {c.case_id for c in a}
    ids_b = {c.case_id for c in b}
    if ids_a != ids_b:
        raise ValueError(
            f"the two runs do not cover the same cases: {len(ids_a)} and {len(ids_b)} cases, "
            f"{len(ids_a ^ ids_b)} in only one of them"
        )


def _paired(a: Mapping[str, float], b: Mapping[str, float]) -> Paired:
    shared = sorted(set(a) & set(b))
    if not shared:
        # bootstrap_mean([]) is (0, 0, 0), which outcome() would read as "matches".
        raise ValueError("no case is left to pair: a difference of nothing is not a reading")
    mean, low, high = bootstrap_mean([a[i] - b[i] for i in shared])
    return Paired(mean, low, high, len(shared))


def paired(a: Sequence[CaseResult], b: Sequence[CaseResult], metric: Metric) -> Paired:
    """The paired difference a minus b on the cases both arms keep (spec §7.2, §7.3).

    A case refused by the guard in either arm is in neither. Every other failure counts as
    wrong in its own arm. The interval is ``metrics.bootstrap_mean`` with its default seed.

    Raises:
        ValueError: if the two runs do not cover the same case ids (checked before refusals are
            removed), or if no case is left to pair.
    """
    _refuse_different_cases(a, b)
    return _paired(per_case(a, metric), per_case(b, metric))


def both_answered(a: Sequence[CaseResult], b: Sequence[CaseResult], metric: Metric) -> Paired:
    """The same difference on the cases both arms answered: printed beside (spec §7.3).

    Raises:
        ValueError: as ``paired``, including when no case was answered in both arms.
    """
    _refuse_different_cases(a, b)
    keep = {c.case_id for c in a if answered(c) is not None} & {
        c.case_id for c in b if answered(c) is not None
    }
    pa = {k: v for k, v in per_case(a, metric).items() if k in keep}
    pb = {k: v for k, v in per_case(b, metric).items() if k in keep}
    return _paired(pa, pb)


def outcome(d: Paired, margin: float = MARGIN) -> Outcome:
    """Beats, matches, worse or undecided, in the order of spec §7.2.

    Beats: the interval lies wholly above zero. Matches: its bottom is above minus the
    margin, and it does not beat. Worse: its top is below zero. Undecided: anything else.
    The margin is tested before "worse", so a low just inside it matches.
    """
    if d.low > 0:
        return "beats"
    if d.low > -margin:
        return "matches"
    if d.high < 0:
        return "worse"
    return "undecided"


def billed(record: RunRecord) -> Billed:
    """A run's billed cost (spec §6 item 1).

    A batch run's billed figure is its ``reported_batch_cost_usd``. A synchronous run's
    replies carry the provider's own cost, so its ``cost_usd`` is what was billed. A batch run
    with no reported figure falls back to its computed cost, marked ``is_billed=False``.
    """
    if record.reported_batch_cost_usd is not None:
        return Billed(record.reported_batch_cost_usd, record.cost_usd, True)
    return Billed(record.cost_usd, record.cost_usd, not record.batch_ids)


def cost_band(loop_usd: float, armb_usd: float, band: float = COST_BAND) -> CostBand:
    """The loop's cost against arm B's: lower, greater (each beyond the band) or equal (§6)."""
    if loop_usd < armb_usd * (1 - band):
        return "lower"
    if loop_usd > armb_usd * (1 + band):
        return "greater"
    return "equal"


def warranted(o: Outcome, band: CostBand) -> bool:
    """Beats at equal or lower cost, or matches at lower cost (spec §7.4)."""
    return (o == "beats" and band != "greater") or (o == "matches" and band == "lower")


def result2_holds(o: Outcome, band: CostBand) -> bool:
    """Result 2 holds when the loop does not beat arm B and costs equal or more (spec §9.2)."""
    return o != "beats" and band != "lower"


def saving_split(loop: Sequence[Billed], armb: Sequence[Billed]) -> SavingSplit:
    """Where the loop's saving comes from (spec §10).

    The difference in computed cost between the arms is the work done. The difference between
    computed and billed within each arm is its discount. Each argument is one arm's runs
    (arm B's three parts), summed.
    """
    loop_computed = sum(b.computed_usd for b in loop)
    armb_computed = sum(b.computed_usd for b in armb)
    return SavingSplit(
        work_usd=loop_computed - armb_computed,
        loop_discount_usd=loop_computed - sum(b.usd for b in loop),
        armb_discount_usd=armb_computed - sum(b.usd for b in armb),
    )


_NOT_SHOWN: Final = "On held-out cases, the loop was not shown to improve on the fixed pipeline: "


def headline(o: Outcome, band: CostBand) -> str:
    """The headline sentence, one of those written in advance (spec §10)."""
    if warranted(o, band):
        if o == "beats":
            return "On held-out cases, the loop beat the fixed pipeline at equal or lower cost."
        return "On held-out cases, the loop matched the fixed pipeline at lower cost."
    if o == "beats":
        return _NOT_SHOWN + "it beat it only at greater cost."
    if o == "matches":
        return _NOT_SHOWN + "it matched it at equal or greater cost."
    if o == "worse":
        return _NOT_SHOWN + "it was worse."
    return _NOT_SHOWN + "it was undecided."
