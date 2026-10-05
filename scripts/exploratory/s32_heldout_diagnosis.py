"""Where the loop lost to the fixed pipeline on held-out: six counts-only breakdowns (0153).

Status
    Exploratory (decision 0059), free and offline: no model call, no new run. It decides nothing
    and claims nothing (decision 0153 item 3): every figure is a lead, read with its interval,
    used to choose what to work on next. Its six breakdowns were fixed by decision 0153 item 2
    before any of them was read, and it prints those six and no others. ``make
    s32-heldout-diagnosis`` writes ``docs/results/s32-heldout-diagnosis.txt``. Counts only
    (decision 0024): no case number, no case or model text. Reading these runs costs
    ``heldout-400`` its use for any later version of the agent (0153 item 4).

What it reads
    S3.2's six held-out runs (arm A; arm B's answer, tool post-pass and ordering check; the loop;
    the loop without the docket), through ``scripts/s32_claims.py``'s own held-out path: its id
    rules (:func:`scripts.s32_claims.refuse_ids`; this reading names no noise-floor run, so that
    one rule is met by construction) and :func:`scripts.s32_claims.load_heldout`, with every
    refusal it makes (each run against the registration, a ledger row for each, held-out cases
    only and the whole sample). Those refusals name ``s32_claims`` as the refusing program.

Refusals, in this order, before any held-out run is opened
    1. The ids, as ``s32_claims`` refuses them.
    2. ``docs/decisions/0153-a-counts-only-diagnosis-of-s32s-held-out-runs.md`` is not committed.
    3. ``docs/rounds/s3-registration.md`` (the S3.2 registration) is not committed.
    4. ``--out`` is under ``docs/results/`` and the tree has another uncommitted change.

The rules it applies (none new)
    * Occurrence top-1 and top-3 per case under S3.2's failure rule (decision 0146):
      ``claims.per_case`` (a guard refusal leaves the case out of both arms; every other failure
      counts as wrong). Paired differences are ``claims.paired``, first minus second, with its
      95% bootstrap interval.
    * Within the loop, a hypothesis from the trail is scored with ``metrics.score_case`` against
      the case's own verdict codes (``CaseResult.verdict_occurrence``), exactly as the answer is
      scored; the answer's own score is the one its case result records. Two of the loop's own
      hypotheses are paired with ``metrics.paired_difference`` (the same bootstrap and seed as
      ``claims.paired``), on the cases the loop answered (``claims.answered``).
    * H0 is the loop's ``record_hypothesis`` before any read choice (trail step ``h0``); its last
      hypothesis before coding is the latest of the ``h0``, ``h1`` and ``h2`` checkpoints. A
      case result's answer is its last step's hypothesis (arm B's tool post-pass and check each
      append a step); its first code is that hypothesis's first occurrence code.
    * Documents offered, read every one, left some unread, nothing on offer: per case, from the
      loop's trail, by ``scripts.s32_behaviour.read_counts`` (bands none, 1, 2-4, 5 or more).
    * A fix is a change of first code that turns a wrong answer right; a break turns a right one
      wrong (0153 glossary). A change of score without a change of first code (an abstain flag
      that changed) is counted apart.

Usage
    uv run python -m scripts.exploratory.s32_heldout_diagnosis --loop RUN --nodocket RUN
        --arm-a RUN --armb-answer RUN --armb-tools RUN --armb-check RUN [--out PATH]
"""

import argparse
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts import s32_claims
from scripts._s3_runs import refuse, refuse_unclean_results, write_result
from scripts.s32_behaviour import read_counts
from scripts.s32_claims import Held, failure_lines, level, load_heldout
from scripts.s32_coding_ablation import NOISE_RUNS, points

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import checkpass, claims
from ntsb_probable_cause.scoring.claims import Metric, Paired
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import paired_difference, score_case
from ntsb_probable_cause.scoring.records import CaseResult

PROG: Final = "s32_heldout_diagnosis"
DECISION: Final = Path("docs/decisions/0153-a-counts-only-diagnosis-of-s32s-held-out-runs.md")
NONE_LEFT: Final = "no case is left to pair"
FATAL: Final = ("fatal", "non-fatal")
# The documents-offered bands, in s32_behaviour's order, read from its own (empty) counts.
BANDS: Final = tuple(read_counts([], []).by_offered)
READ_ALL: Final = "read every document on offer"
READ_SOME: Final = "left some unread"
NOTHING: Final = "nothing on offer"
NO_TRAIL: Final = "no trail row"
_BEFORE_CODING: Final = frozenset({"h0", "h1", "h2"})
_METRICS: Final[tuple[tuple[Metric, str], ...]] = (("top1", "top-1"), ("top3", "top-3"))


# --------------------------------------------------------------------------------------------
# Per case: the loop's trail, and the scores of its hypotheses
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopCase:
    """What the loop's trail says about one case.

    Attributes:
        band: the documents-offered band, or None when the case has no row in the trail.
        reading: read every document on offer, left some unread, nothing on offer, or no trail.
        h0: the hypothesis recorded before any read choice, when one was.
        before_coding: the latest hypothesis checkpoint before the coding step, when one was.
    """

    band: str | None
    reading: str
    h0: Hypothesis | None
    before_coding: Hypothesis | None


def _last_hypothesis(rows: Sequence[AgentCall], steps: frozenset[str]) -> Hypothesis | None:
    found = [row.hypothesis for row in rows if row.step in steps and row.hypothesis is not None]
    return found[-1] if found else None


def loop_cases(calls: Sequence[AgentCall], cases: Sequence[CaseResult]) -> dict[str, LoopCase]:
    """Each loop case's band, reading, H0 and last hypothesis before coding."""
    by_case: dict[str, list[AgentCall]] = defaultdict(list)
    for call in calls:
        by_case[call.case_id].append(call)
    out: dict[str, LoopCase] = {}
    for case in cases:
        rows = sorted(by_case.get(case.case_id, []), key=lambda c: (c.trigger, c.call_index))
        counts = read_counts(rows, [case])
        if not counts.counted:
            out[case.case_id] = LoopCase(None, NO_TRAIL, None, None)
            continue
        band = next(name for name, tally in counts.by_offered.items() if tally.counted)
        if not counts.with_offer:
            reading = NOTHING
        elif counts.read_everything:
            reading = READ_ALL
        else:
            reading = READ_SOME
        out[case.case_id] = LoopCase(
            band,
            reading,
            _last_hypothesis(rows, frozenset({"h0"})),
            _last_hypothesis(rows, _BEFORE_CODING),
        )
    return out


def hypothesis_top1(hypothesis: Hypothesis, case: CaseResult, tables: CodeTables) -> bool:
    """A hypothesis's occurrence top-1 against the case's verdict, as the answer is scored."""
    verdict = Verdict(
        probable_cause=None,
        occurrence_codes=case.verdict_occurrence,
        finding_codes=case.verdict_findings,
        finding_codes_in_cause=case.verdict_findings_in_cause,
    )
    return score_case(hypothesis, verdict, tables, seen_pairs=frozenset()).occurrence_top1


def first_code(hypothesis: Hypothesis, tables: CodeTables) -> str:
    """The hypothesis's first occurrence code."""
    return hypothesis.occurrence_codes(tables)[0]


@dataclass(frozen=True)
class Point:
    """One case at one stage: its first code and whether it was right on top-1."""

    code: str
    right: bool


def answer_point(case: CaseResult, tables: CodeTables) -> Point | None:
    """A case result's answer: its last step's first code and its recorded top-1; None if failed."""
    scores = claims.answered(case)
    if scores is None:
        return None
    return Point(first_code(case.steps[-1].hypothesis, tables), scores.occurrence_top1)


@dataclass(frozen=True)
class Transition:
    """How a stage changed the first code on the cases present at both ends."""

    cases: int
    changed: int
    fixes: int
    breaks: int
    score_only: int


def transition(pairs: Sequence[tuple[Point, Point]]) -> Transition:
    """Count changes of first code, fixes and breaks, and score changes with the code kept."""
    changed = fixes = breaks = score_only = 0
    for before, after in pairs:
        if before.code != after.code:
            changed += 1
            fixes += not before.right and after.right
            breaks += before.right and not after.right
        elif before.right != after.right:
            score_only += 1
    return Transition(len(pairs), changed, fixes, breaks, score_only)


def _transition_line(label: str, t: Transition) -> str:
    return (
        f"- {label}: {t.cases} cases; first code changed on {_share(t.changed, t.cases)}; "
        f"fixes {t.fixes}, breaks {t.breaks} (net {t.fixes - t.breaks:+d}); score changed with "
        f"the first code kept {t.score_only}"
    )


# --------------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------------


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.1%})" if whole else f"{part} of {whole}"


def _only(cases: Sequence[CaseResult], ids: set[str]) -> list[CaseResult]:
    return [c for c in cases if c.case_id in ids]


def pair_text(first: Sequence[CaseResult], second: Sequence[CaseResult], metric: Metric) -> str:
    """``first`` minus ``second`` under the failure rule, or why there is no reading."""
    try:
        return points(claims.paired(first, second, metric))
    except ValueError:
        return NONE_LEFT


def _level_text(cases: Sequence[CaseResult]) -> str:
    mean, low, high, n = level(cases)
    return f"{mean:.1%} [{low:.1%}, {high:.1%}], n={n}"


# --------------------------------------------------------------------------------------------
# The six breakdowns (decision 0153 item 2)
# --------------------------------------------------------------------------------------------


def groups_of(loop: Sequence[CaseResult], per_case: dict[str, LoopCase]) -> dict[str, set[str]]:
    """Item 2's groups: fatal and non-fatal, then each documents-offered band."""
    groups: dict[str, set[str]] = {name: set() for name in (*FATAL, *BANDS)}
    for case in loop:
        groups[FATAL[0] if case.fatal else FATAL[1]].add(case.case_id)
        band = per_case[case.case_id].band
        if band is not None:
            groups[band].add(case.case_id)
    return groups


def stage_lines(held: Held) -> list[str]:
    """Item 1: the loop against each of arm B's stages, and arm B's stages against each other."""
    loop, answer, tools, check = (
        held.loop.cases,
        held.answer.cases,
        held.tools.cases,
        held.check.cases,
    )
    pairs = (
        ("loop - arm B answer", loop, answer),
        ("loop - arm B tools", loop, tools),
        ("loop - arm B check", loop, check),
        ("arm B tools - arm B answer", tools, answer),
        ("arm B check - arm B tools", check, tools),
    )
    lines = ["## 1. Arm B by stage (paired, first minus second)"]
    for name, cases in (
        ("the loop", loop),
        ("arm B answer", answer),
        ("arm B tools", tools),
        ("arm B check", check),
    ):
        lines.append(f"{name} top-1: {_level_text(cases)} (a failure counts as wrong)")
    for metric, metric_name in _METRICS:
        lines += [f"{metric_name}, {label}: {pair_text(a, b, metric)}" for label, a, b in pairs]
    return lines


def group_lines(
    held: Held, groups: dict[str, set[str]], per_case: dict[str, LoopCase]
) -> list[str]:
    """Item 2: loop minus arm B (check) by fatal and non-fatal, and by documents offered."""
    loop, check = held.loop.cases, held.check.cases
    lines = ["## 2. The gap by group (top-1, loop - arm B check)"]
    for name, ids in groups.items():
        label = name if name in FATAL else f"documents offered {name}"
        lines.append(
            f"- {label}: {len(ids)} cases; {pair_text(_only(loop, ids), _only(check, ids), 'top1')}"
        )
    missing = sum(1 for c in per_case.values() if c.band is None)
    lines.append(
        f"- cases with no row in the loop's trail (in no documents-offered band): {missing}"
    )
    return lines


def reading_lines(held: Held, per_case: dict[str, LoopCase], tables: CodeTables) -> list[str]:
    """Item 3: the gap by how much the loop read, and H0 against the answer within the loop."""
    loop, check = held.loop.cases, held.check.cases
    lines = ["## 3. Reading", "top-1, loop - arm B check, by what the loop read:"]
    for reading in (READ_ALL, READ_SOME, NOTHING, NO_TRAIL):
        ids = {case_id for case_id, c in per_case.items() if c.reading == reading}
        lines.append(
            f"- {reading}: {len(ids)} cases; "
            f"{pair_text(_only(loop, ids), _only(check, ids), 'top1')}"
        )
    h0: list[bool] = []
    answer: list[bool] = []
    pairs: list[tuple[Point, Point]] = []
    no_h0 = 0
    for case in loop:
        point = answer_point(case, tables)
        if point is None:
            continue
        hypothesis = per_case[case.case_id].h0
        if hypothesis is None:
            no_h0 += 1
            continue
        before = Point(first_code(hypothesis, tables), hypothesis_top1(hypothesis, case, tables))
        h0.append(before.right)
        answer.append(point.right)
        pairs.append((before, point))
    lines.append(
        "within the loop, on the cases it answered, H0 (before any read choice) and answer:"
    )
    if not pairs:
        lines.append(f"- {NONE_LEFT} (answered cases with no H0 in the trail: {no_h0})")
        return lines
    mean, low, high = paired_difference(answer, h0)
    t = transition(pairs)
    lines += [
        f"- H0 right {_share(sum(h0), len(h0))}; answer right {_share(sum(answer), len(answer))}",
        f"- answer - H0: {points(Paired(mean, low, high, len(pairs)))}",
        f"- H0 -> answer: fixes {t.fixes}, breaks {t.breaks} (first code changed on "
        f"{_share(t.changed, t.cases)}; score changed with the first code kept {t.score_only})",
        f"- answered cases with no H0 in the trail (left out): {no_h0}",
    ]
    return lines


def coding_lines(held: Held, per_case: dict[str, LoopCase], tables: CodeTables) -> list[str]:
    """Item 4: what the coding step did to the first code, in the loop and in arm B."""
    loop_pairs: list[tuple[Point, Point]] = []
    no_checkpoint = 0
    for case in held.loop.cases:
        after = answer_point(case, tables)
        if after is None:
            continue
        hypothesis = per_case[case.case_id].before_coding
        if hypothesis is None:
            no_checkpoint += 1
            continue
        before = Point(first_code(hypothesis, tables), hypothesis_top1(hypothesis, case, tables))
        loop_pairs.append((before, after))
    lines = [
        "## 4. Coding (first code before and after; on the cases answered at both ends)",
        _transition_line(
            "the loop, last hypothesis before coding -> answer", transition(loop_pairs)
        ),
        f"  (loop cases answered with no checkpoint before coding, left out: {no_checkpoint})",
    ]
    for label, first, second in (
        ("arm B answer -> tools", held.answer.cases, held.tools.cases),
        ("arm B tools -> check", held.tools.cases, held.check.cases),
    ):
        lines.append(_transition_line(label, transition(_stage_pairs(first, second, tables))))
    return lines


def _stage_pairs(
    first: Sequence[CaseResult], second: Sequence[CaseResult], tables: CodeTables
) -> list[tuple[Point, Point]]:
    after = {c.case_id: c for c in second}
    pairs: list[tuple[Point, Point]] = []
    for case in first:
        before = answer_point(case, tables)
        other = after.get(case.case_id)
        point = answer_point(other, tables) if other is not None else None
        if before is not None and point is not None:
            pairs.append((before, point))
    return pairs


def failure_section(held: Held) -> list[str]:
    """Item 5: each run's failures by kind, and the gap with the loop's failed cases left out."""
    kept = {c.case_id for c in held.loop.cases if c.failure is None}
    gap = pair_text(_only(held.loop.cases, kept), _only(held.check.cases, kept), "top1")
    return [
        "## 5. Failures",
        *failure_lines(held),
        f"top-1, loop - arm B check, the loop's {len(held.loop.cases) - len(kept)} failed cases "
        f"left out of both: {gap}",
    ]


@dataclass(frozen=True)
class WinLoss:
    """Cases right in arm B (check) only, in the loop only, in both, in neither."""

    armb_only: int
    loop_only: int
    both: int
    neither: int


def win_loss(loop: Sequence[CaseResult], check: Sequence[CaseResult]) -> WinLoss:
    """Top-1 under the failure rule; a guard refusal in either arm leaves the case out."""
    a, b = claims.per_case(loop, "top1"), claims.per_case(check, "top1")
    shared = set(a) & set(b)
    return WinLoss(
        armb_only=sum(1 for i in shared if b[i] and not a[i]),
        loop_only=sum(1 for i in shared if a[i] and not b[i]),
        both=sum(1 for i in shared if a[i] and b[i]),
        neither=sum(1 for i in shared if not a[i] and not b[i]),
    )


def _win_loss_line(label: str, w: WinLoss) -> str:
    n = w.armb_only + w.loop_only + w.both + w.neither
    return (
        f"- {label}: n={n}; right in arm B only {w.armb_only}, in the loop only {w.loop_only}, "
        f"in both {w.both}, in neither {w.neither}"
    )


def win_loss_lines(held: Held, groups: dict[str, set[str]]) -> list[str]:
    """Item 6: wins and losses, overall and in each group of item 2."""
    loop, check = held.loop.cases, held.check.cases
    lines = ["## 6. Wins and losses (top-1; arm B is its check run)"]
    lines.append(_win_loss_line("all", win_loss(loop, check)))
    for name, ids in groups.items():
        label = name if name in FATAL else f"documents offered {name}"
        lines.append(_win_loss_line(label, win_loss(_only(loop, ids), _only(check, ids))))
    return lines


def report_lines(held: Held, tables: CodeTables) -> list[str]:
    """The whole report: a header, the runs, then the six breakdowns in 0153's order."""
    per_case = loop_cases(held.loop.calls, held.loop.cases)
    groups = groups_of(held.loop.cases, per_case)
    names = ("arm A", "arm B answer", "arm B tools", "arm B check", "the loop", "no docket")
    sections = [
        stage_lines(held),
        group_lines(held, groups, per_case),
        reading_lines(held, per_case, tables),
        coding_lines(held, per_case, tables),
        failure_section(held),
        win_loss_lines(held, groups),
    ]
    header = [
        "S3.2 held-out diagnosis (scripts/exploratory/s32_heldout_diagnosis.py; decision 0153)",
        "Exploratory (decision 0059): it decides nothing and claims nothing; every figure is a "
        "lead, read with its interval.",
        "Counts only: no case number. Occurrence top-1 under S3.2's failure rule unless stated: "
        "a guard refusal leaves the case out of both arms, every other failure counts as wrong. "
        "Differences are in points, first minus second, with the 95% bootstrap interval and the "
        "cases they rest on.",
        *(f"{name}: {run.record.run_id}" for name, run in zip(names, held.runs, strict=True)),
        "",
    ]
    return header + [line for section in sections for line in (*section, "")][:-1]


# --------------------------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------------------------


def refuse_ids(args: argparse.Namespace) -> None:
    """``s32_claims``'s id rules; no noise-floor run is read, so that rule is met as written."""
    s32_claims.refuse_ids(argparse.Namespace(**vars(args), noise=list(NOISE_RUNS)))


def main(
    argv: Sequence[str] | None = None, *, is_committed: Callable[[Path], bool] | None = None
) -> int:
    """Print, and with ``--out`` also write, the six breakdowns.

    Args:
        argv: the command line.
        is_committed: whether a path is committed; ``gitinfo.is_committed`` unless a test
            passes its own.
    """
    parser = argparse.ArgumentParser(prog=PROG)
    for flag, help_text in (
        ("loop", "the held-out loop run"),
        ("nodocket", "the held-out loop run without the docket"),
        ("arm-a", "the held-out arm A run"),
        ("armb-answer", "the held-out arm B answer run"),
        ("armb-tools", "arm B's tool post-pass: <armb-answer>-tools"),
        ("armb-check", "arm B's ordering check: <armb-tools>-check-luna"),
    ):
        parser.add_argument(f"--{flag}", required=True, help=help_text)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    committed = is_committed or gitinfo.is_committed
    refuse_ids(args)
    if not committed(DECISION):
        refuse(
            PROG, f"{DECISION} is not committed: the diagnosis reads held-out runs only once it is"
        )
    if not committed(checkpass.S32_REGISTRATION):
        refuse(
            PROG,
            f"{checkpass.S32_REGISTRATION} is not committed: the held-out runs are read only "
            "after the registration is on record (decision 0142)",
        )
    if args.out is not None:
        refuse_unclean_results(PROG, Path(args.out))
    held = load_heldout(args)
    try:
        text = "\n".join(report_lines(held, load_tables()))
    except ValueError as error:
        refuse(PROG, str(error))
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
