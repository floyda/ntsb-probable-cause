"""A guidance round's result, by decision 0098 item 4's rule; appended to its registration.

Status
    Live for S2.7 (spec §6.4) and S3.1's tuning rounds (S3 spec §10.3), free: reads run
    folders; counts only.

Why
    The rule was fixed before the first round: kept only if the gain is real, larger than the
    difference between two identical runs, and costs the other score nothing clear.

Usage
    uv run python -m scripts.round_result --run RUN --reference REF --noise A B
    [--finding-round] [--supplement] [--append PATH]

    ``--supplement`` (decision 0105 item 4) adds a line for the cases a code added to the tables
    touches, for the first round whose run has the added codes and whose reference does not.

    S3's rounds (S3.1 Task 13) read arm C runs the same way. Their tools count in S3's
    statistics file (decision 0129 item 4), which the run's ``spec.json`` names (``stats``), so
    the push line counts in that file too and says so; a run whose ``spec.json`` names none (every
    S2.7 run) reads S2.7's, as before.
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import codes, samples
from ntsb_probable_cause.scoring.coding_stats import (
    STATS_NAMES,
    CodingStats,
    StatsName,
    load_stats,
)
from ntsb_probable_cause.scoring.metrics import bootstrap_mean
from ntsb_probable_cause.scoring.ordering import toward_more_common
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings


@dataclass(frozen=True)
class Diff:
    """A paired mean difference (a - b) with its interval."""

    mean: float
    low: float
    high: float
    n: int


@dataclass(frozen=True)
class Reading:
    """A round's reading."""

    primary: Diff
    noise: float
    secondary: Diff
    kept: bool
    reason: str


def _top1(cases: Sequence[CaseResult]) -> dict[str, float]:
    return {
        c.case_id: float(c.scores.occurrence_top1)
        for c in cases
        if c.scores is not None and c.steps
    }


def _recall(cases: Sequence[CaseResult]) -> dict[str, float]:
    return {
        c.case_id: c.scores.finding_recall_10
        for c in cases
        if c.scores is not None and c.steps and c.scores.finding_recall_10 is not None
    }


def diff(a: Mapping[str, float], b: Mapping[str, float]) -> Diff:
    """Paired over the shared case ids."""
    shared = sorted(set(a) & set(b))
    if not shared:
        return Diff(0.0, 0.0, 0.0, 0)
    mean, low, high = bootstrap_mean([a[i] - b[i] for i in shared])
    return Diff(mean, low, high, len(shared))


def read(
    run: Sequence[CaseResult],
    reference: Sequence[CaseResult],
    noise_a: Sequence[CaseResult],
    noise_b: Sequence[CaseResult],
    *,
    finding_round: bool,
) -> Reading:
    """Decision 0098 item 4."""
    first, second = (_recall, _top1) if finding_round else (_top1, _recall)
    primary = diff(first(run), first(reference))
    noise = abs(diff(first(noise_a), first(noise_b)).mean)
    secondary = diff(second(run), second(reference))
    if secondary.high < 0:
        return Reading(
            primary,
            noise,
            secondary,
            False,
            "dropped: harm to the other score (interval wholly below zero)",
        )
    if primary.low <= 0:
        return Reading(
            primary, noise, secondary, False, "dropped: the gain's interval includes zero"
        )
    if primary.mean <= noise:
        return Reading(
            primary, noise, secondary, False, "dropped: the gain is inside the noise floor"
        )
    return Reading(primary, noise, secondary, True, "kept")


def _first(case: CaseResult) -> str:
    guess = case.steps[-1].hypothesis.occurrence[0]
    return guess.phase + guess.event


def push_line(
    run: Sequence[CaseResult],
    reference: Sequence[CaseResult],
    groups: Mapping[str, str | None],
    stats: CodingStats,
) -> str:
    """Decision 0101 item 4: first codes changed against the reference.

    Counts how many moved toward a more common option in the case's phase group, with their
    fixes and breaks.
    """
    before = {c.case_id: c for c in reference if c.scores is not None and c.steps}
    changed = toward = fixes = breaks = 0
    for case in run:
        old = before.get(case.case_id)
        if case.scores is None or not case.steps or old is None or old.scores is None:
            continue
        if _first(case) == _first(old):
            continue
        changed += 1
        if toward_more_common(_first(old), _first(case), groups.get(case.case_id), stats):
            toward += 1
            fixes += case.scores.occurrence_top1 and not old.scores.occurrence_top1
            breaks += old.scores.occurrence_top1 and not case.scores.occurrence_top1
    return (
        f"- first codes changed: {changed}; toward a more common option: {toward}, "
        f"fixes {fixes}, breaks {breaks} (decision 0101 item 4)"
    )


def _added(code: str, supplement: Mapping[codes.TableName, Mapping[str, str]]) -> bool:
    return code[:3] in supplement.get("phases", {}) or code[3:] in supplement.get("events", {})


def supplement_line(run: Sequence[CaseResult], reference: Sequence[CaseResult]) -> str:
    """Decision 0105 item 4: the cases a code added to the tables touches, apart from the rest."""
    supplement = codes.read_supplement()
    touched = {
        c.case_id for c in run if any(_added(code, supplement) for code in c.verdict_occurrence)
    }
    defining = len(
        [c for c in run if c.verdict_occurrence and _added(c.verdict_occurrence[0], supplement)]
    )
    ran, ref = _top1(run), _top1(reference)
    rest = diff(
        {k: v for k, v in ran.items() if k not in touched},
        {k: v for k, v in ref.items() if k not in touched},
    )
    return (
        f"- cases whose NTSB sequence holds a code decision 0105 added: {len(touched)} "
        f"(defining: {defining}); top-1 hits there: reference "
        f"{sum(v for k, v in ref.items() if k in touched):.0f}, run "
        f"{sum(v for k, v in ran.items() if k in touched):.0f}; occurrence top-1 on the other "
        f"cases: {_fmt(rest)}"
    )


_GROUP_FIELD = next(f for f in fields.EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)


def _groups(cases: Sequence[CaseResult]) -> dict[str, str | None]:
    """Each case's phase group, the evidence value (read from the processed file, locally)."""
    ids = [c.case_id for c in cases]
    raws = samples.load_cases(Settings().data_dir / "processed", ids)
    return {
        i: (value if isinstance(value := _GROUP_FIELD.extract(raw), str) else None)
        for i, raw in zip(ids, raws, strict=True)
    }


def _record(run_id: str) -> RunRecord:
    """A run's own record, after every refusal but the per-case split.

    Held-out, sealed, finished. 2026-09-27 addition beyond the brief: mirrors the sibling
    scripts already on this branch (``judge_outcomes._load``, ``round0_handread._run``,
    ``round1_report._load``), which check
    ``run.jsonl``'s recorded sample before ``cases.jsonl`` is read at all, on top of the run-id
    substring check -- so a run whose id does not say "heldout" but whose recorded sample is a
    held-out one is still refused before any per-case data is touched; the sealed sample is
    refused too, until its registration is committed (decision 0095). Final review, Minor 3: a
    check pass that died mid-write leaves a run whose ``finished`` is ``None`` and a partial
    ``cases.jsonl``; refused here before it is read at all.
    """
    try:
        samples.refuse_unless_development(run_id, None)
        record = read_jsonl(Settings().runs_dir / run_id / "run.jsonl", RunRecord)[0]
        samples.refuse_unless_development(run_id, record.sample)
    except ConfigurationError as error:
        raise SystemExit(f"round_result: {error}") from error
    if record.finished is None:
        raise SystemExit(f"round_result: {run_id} has not finished: it did not complete a pass")
    return record


def _refuse_mismatched(
    label: str, reference: RunRecord, other_label: str, other: RunRecord
) -> None:
    """Refuse a run/reference/noise pairing whose sample, arm or evidence version differ.

    Final review, Minor 3: nothing checked that the run, the reference and the noise pair were
    even comparable -- ``n`` was printed either way, so a mismatch would be silent rather than
    refused.
    """
    for attribute in ("sample", "arm", "evidence_version"):
        mine, theirs = getattr(reference, attribute), getattr(other, attribute)
        if mine != theirs:
            raise SystemExit(
                f"round_result: {other_label} {attribute}={theirs!r} does not match "
                f"{label} {attribute}={mine!r}"
            )


def _stats_name(run_id: str) -> StatsName:
    """The statistics file the run's own tools counted in: its ``spec.json``'s ``stats``.

    S3.1 Task 13: arm C records ``"stats": "s3"`` (decision 0129 item 4). A run that records none
    (S2.7's arm B runs, which have no such key) counted in S2.7's file.
    """
    path = Settings().runs_dir / run_id / "spec.json"
    recorded = json.loads(path.read_text()) if path.is_file() else {}
    named = recorded.get("stats", "s27") if isinstance(recorded, dict) else "s27"
    for name in STATS_NAMES:
        if name == named:
            return name
    raise SystemExit(
        f"round_result: {run_id}'s spec.json names the statistics file {named!r}, which is "
        f"none of {', '.join(STATS_NAMES)}"
    )


def _load(run_id: str) -> list[CaseResult]:
    """A development run's cases, after every refusal (held-out, sealed, finished, split)."""
    _record(run_id)
    folder = Settings().runs_dir / run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        raise SystemExit(f"round_result: {run_id} holds a case outside the dev split")
    return cases


def _fmt(d: Diff) -> str:
    return f"{d.mean:+.1%} [{d.low:+.1%}, {d.high:+.1%}] on n={d.n}"


def main(argv: Sequence[str] | None = None) -> int:
    """Print the reading; with ``--append``, add it under the registration."""
    parser = argparse.ArgumentParser(prog="round_result")
    parser.add_argument("--run", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--noise", nargs=2, required=True, metavar="RUN_ID")
    parser.add_argument("--finding-round", action="store_true")
    parser.add_argument("--append", default=None, type=Path)
    parser.add_argument("--supplement", action="store_true")
    args = parser.parse_args(argv)
    run_record = _record(args.run)
    reference_record = _record(args.reference)
    noise_a_record = _record(args.noise[0])
    noise_b_record = _record(args.noise[1])
    _refuse_mismatched(args.run, run_record, args.reference, reference_record)
    _refuse_mismatched(args.run, run_record, args.noise[0], noise_a_record)
    _refuse_mismatched(args.run, run_record, args.noise[1], noise_b_record)
    stats = _stats_name(args.run)
    run, reference = _load(args.run), _load(args.reference)
    reading = read(
        run,
        reference,
        _load(args.noise[0]),
        _load(args.noise[1]),
        finding_round=args.finding_round,
    )
    push = push_line(run, reference, _groups(run), load_stats(stats))
    if stats != "s27":  # S2.7's results read exactly as they always have
        push += (
            f"\n- statistics file for the line above: {stats} (the run's spec.json; decision "
            "0129 item 4)"
        )
    primary, secondary = (
        ("finding recall@10", "occurrence top-1")
        if args.finding_round
        else ("occurrence top-1", "finding recall@10")
    )
    text = "\n".join(
        [
            "## Result (scripts/round_result.py, decision 0098 item 4)",
            "",
            f"- run: {args.run} (prompt {run_record.prompt_version}); "
            f"reference: {args.reference} (prompt {reference_record.prompt_version}); "
            f"noise pair: {args.noise[0]}, {args.noise[1]}",
            f"- {primary}: {_fmt(reading.primary)}",
            f"- noise floor ({primary}, the two identical runs): {reading.noise:.1%}",
            f"- {secondary} (do no harm): {_fmt(reading.secondary)}",
            push,
            *([supplement_line(run, reference)] if args.supplement else []),
            f"- outcome: {reading.reason}",
        ]
    )
    print(text)
    if args.append is not None:
        with args.append.open("a") as handle:
            handle.write("\n" + text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
