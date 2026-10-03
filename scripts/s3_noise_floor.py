"""The agent loop's noise floor and format gate: two or three identical arm C runs on dev-400.

Status
    Live measurement for S3.1 (spec §10.2 to §10.4, decision 0130; plan Task 13), free: reads two
    or three finished run folders and makes no model call. Counts only (decision 0024): no case
    number, no title, no prose, and every figure is printed with its denominator. Its output is
    ``docs/results/s3-noise-floor-dev.txt`` (``make s3-noise-report RUNS="<a> <b>"``).

Why
    A tuning round can be read only against the loop's own noise: two identical arm B runs in
    S2.7 differed by top-1 +4.0% [+0.5%, +7.5%], and the loop has more sources of chance (read
    choices, tool arguments, state over many turns). The same runs decide the format gate and
    whether a third run is needed, so this script is the instrument for both.

What it prints
    For each run: its provenance; failures by reason (``report.failure_summary``); the format
    gate; the round limit; cost for the run and per case, both computed (``cost_usd``) and
    billed (the batch rounds' reported total), and which of the two the spend line and the
    monthly guard count (decision 0135); the cached share of prompt tokens
    (``trail.jsonl``); and the raw stated confidence at the answer (mean, and right or wrong on
    occurrence top-1 in the bands below 0.4, 0.4 to below 0.6, 0.6 to below 0.8, and 0.8 or
    more), kept for S3.2's calibration fit (decision 0126); nothing is fitted here.

    For each pair of runs: occurrence top-1 and top-3 paired differences and finding recall@10's
    mean difference, with intervals, overall and by fatal and non-fatal
    (``report.compare_by_fatal``, which labels them ``(a - b)``; a line before them names the two
    runs a and b stand for in that block); the cases whose first occurrence code changed, with
    ``scripts.occurrence_misses.churn``; read-or-skip agreement; coding-call agreement.

    - **Read or skip.** From ``trail.jsonl``: each accepted ``choose_documents`` call's parsed
      arguments (``ReadRecord`` is not written to disk), kept only for the documents its row's
      ``offered`` names. The arguments are as the model sent them, so they may hold decisions
      on documents not on offer (decision 0134); those never enter the count. A row with no
      ``offered`` predates 0134, when such a decision refused the call, and all its decisions
      count. A document's decision in a run is ``read`` if any read choice of its case read it,
      else ``skip``. Compared per document offered in both runs (same case, same listing
      index).
    - **Coding calls.** From ``trail.jsonl``: per case scored in both runs, the multiset of
      ``(tool, arguments)`` over its accepted coding-tool calls (``agent.schemas.CODING_TOOLS``,
      ``protocol_error`` None), the arguments without ``reason`` and ``expected_effect`` and
      written with their keys sorted; the order inside a list argument is kept, so the same codes
      in another order are another call. A case that made no coding call in either run agrees,
      and is counted apart as well.

The format gate (spec §10.4, decision 0130 item 5)
    Counts the cases whose ``failure`` starts ``failed: ``, except ``failed: leak`` and
    ``failed: rounds``. Arm C writes these as ``failed: <step>``, for ``h0``, ``choice1``, ``h1``,
    ``choice2``, ``h2``, ``coding``, ``answer`` or ``refine``: a call of that step failed twice
    in a row, for no tool call, a tool not allowed at that step, arguments that did not parse or
    check, a coding tool that could not run, a refinement that did not parse, or a batch item
    that came back with no result. Any other ``failed: `` reason a later loop writes is counted
    too, so the gate fails closed. **Not counted:** ``cap`` (the per-case cap); ``leak: <message>``
    (the guard refused a document; arm C writes it as arm B does, never ``failed: leak``, which
    is left out as well should it appear); ``failed: rounds`` (the run's batch-round limit, a
    fact about the batch service rather than the loop's format or tools, which is all spec §10.4
    names: it is printed on its own line beside the gate, so a run that hits it is still seen);
    and ``aborted: <error>`` (only in an unfinished run, which is refused). The gate passes at
    most 8 such cases of dev-400's 401 (2%). A batch item that failed twice with no reply (a
    provider error) ends ``failed: <step>`` and stays counted, so the gate fails closed; beside
    the count, ``of which K had no reply on the failing call`` says how many of the counted cases
    that was, read from each case's last call in ``trail.jsonl`` (a call with no reply has no
    tool, no hypothesis, no finish reason and zero tokens).

The third-run rule (spec §10.2, decision 0130 item 2)
    ``third run: needed`` if the absolute paired occurrence top-1 difference between the first
    two runs named (on the cases scored in both) is larger than 4.0 points, S2.7's figure; else
    ``not needed``. Decided on whole counts (``100 x |net hits| > 4.0 x cases``), so a difference
    of exactly 4.0 points is never pushed over by a float's rounding.

Refusals, before any case or trail is read
    A held-out run id; a folder with no ``run.jsonl``, or whose record names another run (a
    copied or renamed folder); a run on any sample but ``dev-400``, of any arm but C, or not
    finished; a run on part of ``dev-400`` (a ``--limit`` run: decision 0130 measures the whole
    sample); a run from a tree with uncommitted changes (the noise floor is measured on one
    frozen commit, plan Task 14); a run with no readable ``spec.json`` or no ``trail.jsonl``; a
    run named twice; and runs configured differently. Two runs are configured alike when their
    ``spec.json`` files are equal key for key (it records no times), apart from ``budget_usd``
    and ``expected_cost_per_case_usd``: those two only size the budget reservation and never
    reach a model call, so a difference in them is printed, not refused. Once the cases are
    read, a case outside the development split is refused too.

Usage
    uv run python -m scripts.s3_noise_floor RUN_A RUN_B [RUN_C] [--out PATH]
"""

import argparse
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Final, NoReturn

from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.schemas import CODING_TOOLS, ChooseDocuments
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import budget, report, samples
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts.occurrence_misses import churn

SAMPLE: Final = "dev-400"
# Decision 0130 item 5: at most 2% of cases, 8 of dev-400's 401, may fail for format or tools.
GATE_MAX: Final = 8
# Decision 0130 item 2: S2.7's figure, in points of occurrence top-1.
THIRD_RUN_POINTS: Final = Fraction(4)
_FAILED: Final = "failed: "
_ROUNDS: Final = "failed: rounds"
_NOT_FORMAT: Final = frozenset({"failed: leak", _ROUNDS})
# Settings that only size the budget reservation; they never reach a model call.
_RESERVATION_ONLY: Final = ("budget_usd", "expected_cost_per_case_usd")
_WHY: Final = frozenset({"reason", "expected_effect"})
# Half-open bands of the stated confidence: "0.4-0.6" is at least 0.4 and below 0.6.
_BANDS: Final = (
    (0.0, 0.4, "<0.4"),
    (0.4, 0.6, "0.4-0.6"),
    (0.6, 0.8, "0.6-0.8"),
    (0.8, math.inf, "≥0.8"),
)
_LABELS: Final = "abc"
_MISSING: Final = "(not recorded)"


@dataclass(frozen=True)
class Run:
    """One run, read whole: its label in the report, record, ``spec.json``, cases and trail."""

    label: str
    record: RunRecord
    spec: dict[str, object]
    cases: list[CaseResult]
    calls: list[AgentCall]


@dataclass(frozen=True)
class Gate:
    """The format gate of one run.

    Attributes:
        failed: each counted failure reason, with its cases.
        rounds: the cases stopped ``failed: rounds`` (listed apart, not counted).
        cases: every case of the run, the denominator.
        no_reply: of the counted cases, those whose failing call (the case's last call in
            ``trail.jsonl``) came back with no reply: a provider error, or no result in a batch.
            They stay counted, so the gate fails closed; the number says how many they are.
    """

    failed: Counter[str]
    rounds: int
    cases: int
    no_reply: int = 0

    @property
    def count(self) -> int:
        """The cases that failed for format or tool reasons."""
        return sum(self.failed.values())

    @property
    def passed(self) -> bool:
        """At most ``GATE_MAX`` of them."""
        return self.count <= GATE_MAX


@dataclass(frozen=True)
class ReadAgreement:
    """Read-or-skip decisions on the documents two runs both offered.

    Attributes:
        both_read: read in both runs.
        both_skipped: skipped in both runs.
        first_only: read in the first run only.
        second_only: read in the second run only.
        cases: the cases those documents belong to.
        one_run_only: documents offered in one run and not the other (not compared).
    """

    both_read: int
    both_skipped: int
    first_only: int
    second_only: int
    cases: int
    one_run_only: int

    @property
    def same(self) -> int:
        """Documents with the same decision in both runs."""
        return self.both_read + self.both_skipped

    @property
    def offered(self) -> int:
        """Documents offered in both runs: the denominator."""
        return self.same + self.first_only + self.second_only


@dataclass(frozen=True)
class CodingAgreement:
    """Coding calls on the cases two runs both scored.

    Attributes:
        same: cases whose coding calls are the same multiset in both runs.
        cases: cases scored in both runs, the denominator.
        none: of ``same``, the cases that made no coding call in either run.
    """

    same: int
    cases: int
    none: int


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"s3_noise_floor: {message}")


# --- the measures ---


def _counted(case: CaseResult) -> bool:
    """Whether the format gate counts the case (see the module docstring for the strings)."""
    failure = case.failure
    return failure is not None and failure.startswith(_FAILED) and failure not in _NOT_FORMAT


def _no_reply(call: AgentCall) -> bool:
    """Whether a trail row is a call that came back with no reply at all.

    The loop writes such a call (``accept(None, ...)``) with no tool, no hypothesis, no finish
    reason and zero prompt and completion tokens; a reply always reports its prompt tokens.
    """
    return (
        call.tool is None
        and call.hypothesis is None
        and call.finish_reason is None
        and call.prompt_tokens == 0
        and call.completion_tokens == 0
    )


def format_gate(cases: Sequence[CaseResult], calls: Sequence[AgentCall] = ()) -> Gate:
    """The format gate's count over a run's cases (see the module docstring for the strings).

    ``calls`` is the run's ``trail.jsonl``; from it, ``no_reply`` counts the counted cases whose
    last call (the failing one) had no reply. With no trail it is 0.
    """
    counted = [c for c in cases if _counted(c)]
    last: dict[str, AgentCall] = {}
    for call in calls:
        held = last.get(call.case_id)
        if held is None or (call.trigger, call.call_index) >= (held.trigger, held.call_index):
            last[call.case_id] = call
    no_reply = sum(1 for c in counted if c.case_id in last and _no_reply(last[c.case_id]))
    failed = Counter(c.failure for c in counted if c.failure is not None)
    return Gate(failed, sum(c.failure == _ROUNDS for c in cases), len(cases), no_reply)


def third_run_needed(net: int, cases: int) -> bool:
    """Whether ``|net| / cases`` is larger than 4.0 points; never for no case (decided apart)."""
    return cases > 0 and Fraction(100 * abs(net), cases) > THIRD_RUN_POINTS


def top1_net(first: Sequence[CaseResult], second: Sequence[CaseResult]) -> tuple[int, int]:
    """Top-1 hits of the first run minus the second's, and the cases scored in both."""
    left = {c.case_id: c.scores.occurrence_top1 for c in first if c.scores is not None}
    right = {c.case_id: c.scores.occurrence_top1 for c in second if c.scores is not None}
    shared = left.keys() & right.keys()
    return sum(left[i] for i in shared) - sum(right[i] for i in shared), len(shared)


def _first_codes(cases: Sequence[CaseResult]) -> dict[str, str]:
    """Each scored case's first occurrence guess, read as ``occurrence_misses.churn`` reads it."""
    return {
        c.case_id: c.steps[-1].hypothesis.occurrence[0].phase
        + c.steps[-1].hypothesis.occurrence[0].event
        for c in cases
        if c.scores is not None and c.steps
    }


def first_code_changes(
    first: Sequence[CaseResult], second: Sequence[CaseResult]
) -> tuple[int, int]:
    """Cases whose first occurrence code differs between the runs, of the cases scored in both."""
    left, right = _first_codes(first), _first_codes(second)
    shared = left.keys() & right.keys()
    return sum(left[i] != right[i] for i in shared), len(shared)


def _decisions(calls: Sequence[AgentCall]) -> dict[tuple[str, int], bool]:
    """Each document a read choice offered, by case and listing index: whether it was read.

    A decision on a document the row does not name as offered is left out (decision 0134: the
    arguments keep the model's decisions on documents not on offer). A row with no offer is
    from a trail written before 0134, when such a decision refused the call, so every decision
    of an accepted row of that kind was on offer, and all of them count.
    """
    read: dict[tuple[str, int], bool] = {}
    for call in calls:
        if call.tool != "choose_documents" or call.protocol_error is not None:
            continue
        for decision in ChooseDocuments.model_validate(call.arguments).decisions:
            if call.offered and decision.document not in call.offered:
                continue
            key = (call.case_id, decision.document)
            read[key] = read.get(key, False) or decision.read
    return read


def read_agreement(first: Sequence[AgentCall], second: Sequence[AgentCall]) -> ReadAgreement:
    """Read-or-skip agreement on every document offered in both runs."""
    left, right = _decisions(first), _decisions(second)
    shared = left.keys() & right.keys()
    return ReadAgreement(
        both_read=sum(left[k] and right[k] for k in shared),
        both_skipped=sum(not left[k] and not right[k] for k in shared),
        first_only=sum(left[k] and not right[k] for k in shared),
        second_only=sum(right[k] and not left[k] for k in shared),
        cases=len({case for case, _ in shared}),
        one_run_only=len(left.keys() ^ right.keys()),
    )


def _coding_calls(calls: Sequence[AgentCall]) -> dict[str, Counter[tuple[str, str]]]:
    """Each case's accepted coding calls, as a multiset of (tool, arguments without the why)."""
    by_case: dict[str, Counter[tuple[str, str]]] = {}
    for call in calls:
        if call.tool not in CODING_TOOLS or call.protocol_error is not None:
            continue
        arguments = {k: v for k, v in call.arguments.items() if k not in _WHY}
        key = (call.tool, json.dumps(arguments, sort_keys=True))
        by_case.setdefault(call.case_id, Counter())[key] += 1
    return by_case


def coding_agreement(
    first_cases: Sequence[CaseResult],
    second_cases: Sequence[CaseResult],
    first_calls: Sequence[AgentCall],
    second_calls: Sequence[AgentCall],
) -> CodingAgreement:
    """Coding-call agreement on the cases scored in both runs."""
    scored = {c.case_id for c in first_cases if c.scores is not None} & {
        c.case_id for c in second_cases if c.scores is not None
    }
    left, right = _coding_calls(first_calls), _coding_calls(second_calls)
    empty: Counter[tuple[str, str]] = Counter()
    same = [i for i in scored if left.get(i, empty) == right.get(i, empty)]
    none = sum(not left.get(i) and not right.get(i) for i in same)
    return CodingAgreement(same=len(same), cases=len(scored), none=none)


# --- the lines ---


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.1%})" if whole else f"{part} of {whole}"


def gate_lines(label: str, gate: Gate) -> list[str]:
    """The gate's verdict and count, and the round limit beside it."""
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(gate.failed.items())) or "none"
    verdict = "PASS" if gate.passed else "FAIL"
    return [
        f"format gate, run {label}: {verdict} -- {gate.count} of {gate.cases} cases failed for "
        f"format or tool reasons ({reasons}); of which {gate.no_reply} had no reply on the "
        f"failing call; at most {GATE_MAX} pass (2% of dev-400's 401 "
        "cases, spec §10.4, decision 0130 item 5)",
        f"round limit (failed: rounds), run {label}: {gate.rounds} of {gate.cases} cases (the "
        "batch rounds ran out; not a format or tool failure, so not in the gate)",
    ]


def _per_case(cost: float, cases: int) -> float:
    return cost / cases if cases else 0.0


def cost_line(label: str, record: RunRecord) -> str:
    """The run's computed and billed cost, each for the run and per case, and which is counted.

    Computed: ``cost_usd``, every prompt token priced at the full input rate. Billed: the batch
    rounds' own reported total, cached prompt tokens at their lower rate. The spend line and
    the monthly guard count the billed figure when there is one (``budget.counts_billed``,
    decision 0135).
    """
    cases = record.cases
    billed = record.reported_batch_cost_usd
    computed = (
        f"computed ${record.cost_usd:.4f} for {cases} cases, "
        f"${_per_case(record.cost_usd, cases):.4f} per case"
    )
    reported = (
        "billed: no total (a batch round reported none)"
        if billed is None
        else f"billed ${billed:.4f}, ${_per_case(billed, cases):.4f} per case (the batch rounds' "
        "own reports)"
    )
    counted = "billed" if budget.counts_billed(record) else "computed"
    return (
        f"cost, run {label}: {computed}; {reported}; the spend line and the monthly guard count "
        f"the {counted} figure (decision 0135)"
    )


def cached_line(label: str, calls: Sequence[AgentCall]) -> str:
    """The provider's cached share of the prompt tokens, over every model call in the trail."""
    cached = sum(c.cached_tokens or 0 for c in calls)
    prompt_tokens = sum(c.prompt_tokens for c in calls)
    unreported = sum(c.cached_tokens is None for c in calls)
    return (
        f"cached share of prompt tokens, run {label}: {_share(cached, prompt_tokens)} over "
        f"{len(calls)} model calls; {unreported} calls reported no cached count (counted as none)"
    )


def confidence_lines(label: str, cases: Sequence[CaseResult]) -> list[str]:
    """The raw stated confidence at the answer, over the scored cases: mean, then the bands."""
    scored = [c.scores for c in cases if c.scores is not None]
    if not scored:
        return [f"confidence at the answer, run {label}: no scored case, of {len(cases)}"]
    mean = sum(s.confidence for s in scored) / len(scored)
    lines = [
        f"confidence at the answer, run {label}: mean {mean:.3f} over {len(scored)} scored "
        f"cases of {len(cases)} (raw, as stated; right or wrong on occurrence top-1; kept for "
        "S3.2's fit, decision 0126; nothing is fitted here)"
    ]
    for low, high, name in _BANDS:
        band = [s for s in scored if low <= s.confidence < high]
        right = sum(s.occurrence_top1 for s in band)
        lines.append(f"- {name}: right {right}, wrong {len(band) - right}, of {len(band)}")
    abstained = sum(s.abstained for s in scored)
    lines.append(
        f"abstained, run {label}: {abstained} of {len(scored)} scored cases (each counted wrong, "
        "as top-1 counts it)"
    )
    return lines


def third_run_line(first: Run, second: Run) -> str:
    """The rule's verdict on the first two runs, with the difference it was read from."""
    net, cases = top1_net(first.cases, second.cases)
    if cases == 0:
        return (
            f"third run: not decided -- no case was scored in both run {first.label} and run "
            f"{second.label}"
        )
    needed = third_run_needed(net, cases)
    points = float(Fraction(100 * net, cases))
    return (
        f"third run: {'needed' if needed else 'not needed'} -- the paired occurrence top-1 "
        f"difference between runs {first.label} and {second.label} is {points:+.2f} points "
        f"(net {net:+d} of {cases} cases scored in both), "
        f"{'larger' if needed else 'not larger'} than {float(THIRD_RUN_POINTS):.1f} points "
        "(spec §10.2, decision 0130 item 2)"
    )


def run_block(run: Run) -> str:
    """One run's own figures."""
    gate = format_gate(run.cases, run.calls)
    lines = [
        f"## run {run.label}",
        "",
        report.provenance(run.record).rstrip("\n"),
        report.failure_summary(run.cases),
        *gate_lines(run.label, gate),
        cost_line(run.label, run.record),
        cached_line(run.label, run.calls),
        *confidence_lines(run.label, run.cases),
    ]
    return "\n".join(lines)


def pair_block(first: Run, second: Run) -> str:
    """Two runs against each other: scores, read choices, coding calls, then first codes.

    ``report.compare_by_fatal`` labels every difference ``(a - b)``, which in a three-run report
    is not always run a minus run b; a line before it names what a and b are in this block, so
    its output, shared with other callers, is unchanged. ``churn``'s block comes last because it
    opens with its own heading; the line of first codes changed goes under it.
    """
    changed, both = first_code_changes(first.cases, second.cases)
    reads = read_agreement(first.calls, second.calls)
    coding = coding_agreement(first.cases, second.cases, first.calls, second.calls)
    lines = [
        f"## run {first.label} against run {second.label}",
        "",
        f"(a - b) here is run {first.label} minus run {second.label}",
        report.compare_by_fatal(first.cases, second.cases),
        "",
        f"read-or-skip agreement: {reads.same} of {reads.offered} documents offered in both runs "
        f"got the same decision (read in both {reads.both_read}, skipped in both "
        f"{reads.both_skipped}; read in run {first.label} only {reads.first_only}, in run "
        f"{second.label} only {reads.second_only}), over {reads.cases} cases; "
        f"{reads.one_run_only} documents offered in one run only",
        f"coding-call agreement: {coding.same} of {coding.cases} cases scored in both runs made "
        "the same coding calls (tool and arguments, list order inside the arguments kept, "
        "reason and expected_effect left out, as a multiset); "
        f"{coding.none} of those {coding.same} made no coding call in either run",
        churn(first.cases, second.cases).rstrip("\n"),
        f"first occurrence code changed: {changed} of {both} cases scored in both runs",
    ]
    return "\n".join(lines)


def spec_line(runs: Sequence[Run]) -> str:
    """How alike the runs' ``spec.json`` files are: compared settings, and the budget ones."""
    first = runs[0]
    compared = len([k for k in first.spec if k not in _RESERVATION_ONLY])
    differing = [
        key
        for key in _RESERVATION_ONLY
        if len({json.dumps(run.spec.get(key, _MISSING)) for run in runs}) > 1
    ]
    if not differing:
        return (
            f"spec.json: identical in the {len(runs)} runs ({compared} settings compared; "
            f"{' and '.join(_RESERVATION_ONLY)} size the budget reservation only and are not "
            "compared)"
        )
    lines = [
        f"spec.json: identical in the {len(runs)} runs apart from {', '.join(differing)}, which "
        f"size the budget reservation only ({compared} settings compared)"
    ]
    for key in differing:
        values = "; ".join(f"{run.spec.get(key, _MISSING)} in {run.record.run_id}" for run in runs)
        lines.append(f"- {key}: {values}")
    return "\n".join(lines)


def noise_report(runs: Sequence[Run]) -> str:
    """The whole report: the decisions first, then each run, then each pair."""
    first, second = runs[0], runs[1]
    lines = [
        "S3.1 noise floor and format gate (scripts/s3_noise_floor.py; spec §10.2 to §10.4, "
        "decision 0130)",
        "Counts only: no case number. Every figure is printed with its denominator.",
        *(f"run {run.label} = {run.record.run_id}" for run in runs),
        spec_line(runs),
        "",
        "## the decisions",
        "",
        *(
            line
            for run in runs
            for line in gate_lines(run.label, format_gate(run.cases, run.calls))
        ),
        third_run_line(first, second),
    ]
    if len(runs) > 2:  # noqa: PLR2004 -- the third run of decision 0130 item 2
        lines.append(
            f"a third run was given: run {runs[2].label} = {runs[2].record.run_id}; the rule "
            "reads the first two"
        )
    blocks = [run_block(run) for run in runs]
    blocks += [pair_block(x, y) for x, y in combinations(runs, 2)]
    return "\n\n".join(["\n".join(lines), *blocks])


# --- reading the runs ---


def _head(run_id: str) -> tuple[RunRecord, dict[str, object]]:
    """A run's record and ``spec.json``, after every refusal that needs no case."""
    try:
        samples.refuse_unless_development(run_id, None)
    except ConfigurationError as error:
        _refuse(str(error))
    folder = Settings().runs_dir / run_id
    if not (folder / "run.jsonl").is_file():
        _refuse(f"{run_id}: no run.jsonl in {folder}")
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    if record.run_id != run_id:
        _refuse(f"{run_id}: its run.jsonl names run {record.run_id}: a copied or renamed folder")
    if record.sample != SAMPLE:
        _refuse(f"{run_id} is on {record.sample}; the noise floor is measured on {SAMPLE} only")
    if record.arm != "C":
        _refuse(f"{run_id} is arm {record.arm}, not arm C")
    if record.finished is None:
        _refuse(f"{run_id} has not finished: it did not complete a pass")
    spec = _spec(folder, run_id)
    if record.dirty or spec.get("dirty"):
        _refuse(
            f"{run_id} ran from a tree with uncommitted changes; the noise floor is measured on "
            "one frozen commit, from a clean tree (plan Task 14)"
        )
    if spec.get("case_ids") != list(samples.sample_ids(SAMPLE)):
        _refuse(
            f"{run_id} is not the whole of {SAMPLE} (a --limit run?); decision 0130 measures the "
            "noise floor on the whole sample"
        )
    if not (folder / TRAIL_FILE).is_file():
        _refuse(f"{run_id}: no {TRAIL_FILE} in {folder}")
    return record, spec


def _spec(folder: Path, run_id: str) -> dict[str, object]:
    path = folder / "spec.json"
    try:
        recorded = json.loads(path.read_text()) if path.is_file() else None
    except json.JSONDecodeError:
        recorded = None
    if not isinstance(recorded, dict):
        _refuse(f"{run_id}: no readable spec.json in {folder}")
    return recorded


def refuse_mismatched(heads: Sequence[tuple[RunRecord, dict[str, object]]]) -> None:
    """Refuse runs whose ``spec.json`` differ at any key but the reservation-only ones."""
    (first, mine), *others = heads
    for other, theirs in others:
        for key in dict.fromkeys([*mine, *theirs]):
            if key in _RESERVATION_ONLY:
                continue
            a, b = mine.get(key, _MISSING), theirs.get(key, _MISSING)
            if a != b:
                # A case list is case numbers: never repeated in a message.
                shown = (
                    "" if key == "case_ids" else f" ({first.run_id}: {a!r}; {other.run_id}: {b!r})"
                )
                _refuse(
                    f"{other.run_id} is configured differently from {first.run_id}: spec.json "
                    f"differs at {key!r}{shown}; the noise floor compares identical runs "
                    "(spec §10.2)"
                )


def _read(label: str, run_id: str, head: tuple[RunRecord, dict[str, object]]) -> Run:
    folder = Settings().runs_dir / run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        _refuse(f"{run_id} holds a case outside the dev split")
    calls = read_jsonl(folder / TRAIL_FILE, AgentCall)
    record, spec = head
    return Run(label, record, spec, cases, calls)


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the noise floor of two or three arm C runs."""
    parser = argparse.ArgumentParser(prog="s3_noise_floor")
    parser.add_argument("runs", nargs="+", metavar="RUN_ID", help="two or three arm C run ids")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if not 2 <= len(args.runs) <= len(_LABELS):  # noqa: PLR2004 -- two runs, or three
        parser.error("give two or three run ids")
    if len(set(args.runs)) != len(args.runs):
        _refuse("a run is named twice; the noise floor compares distinct runs")
    heads = [_head(run_id) for run_id in args.runs]
    refuse_mismatched(heads)
    runs = [
        _read(label, run_id, head)
        for label, run_id, head in zip(_LABELS, args.runs, heads, strict=False)
    ]
    text = noise_report(runs)
    print(text)
    if args.out is not None:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
