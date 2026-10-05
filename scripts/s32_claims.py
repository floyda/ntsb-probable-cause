"""The held-out claims: the verdict, the four results, the ablations, the predictions (Task 11).

Status
    Live measurement for S3.2 (spec §6 to §12), free: reads finished run folders and makes no
    model call. Counts only (decision 0024): no case number, no case text, no model text.
    Its output is ``docs/results/s32-claims-heldout.txt`` (``make s32-claims``). It is the one
    script that reads the six held-out runs, and it reads them once they exist: the registration
    must be committed first. It decides nothing about a later stage.

The held-out loading path is this script's own
    ``scripts/_s3_runs.py`` loads ``dev-400`` arm C runs and refuses every held-out run; it is
    not loosened. This script reads its six held-out runs through :func:`load_heldout`, which
    checks each run against the registration (below) and is not shared. The coding ablation and
    the two noise-floor runs are ``dev-400`` runs: they go through the shared loader, by way of
    ``scripts/s32_coding_ablation.py``. It never opens ``dev-seal-400`` or ``dev-seal-s3-400``.

Refusals, in this order, before any case is read
    1. Ids: a run named twice; ``--armb-tools`` that is not ``<--armb-answer>-tools``;
       ``--armb-check`` that is not ``checkpass.derived_id(<--armb-tools>, "luna")``; noise runs
       that are not the two noise-floor runs.
    2. ``docs/rounds/s3-registration.md`` must be committed; the tree must be clean when the
       result is written under ``docs/results/``.
    3. Each held-out run, from its ``run.jsonl`` (and ``spec.json`` for the loop): a finished
       run on ``heldout-400`` from a clean tree, GPT-6 Luna at reasoning ``medium``, evidence v1,
       reply budget 8,000 and a cap of $0.30 (spec §2, §5); arm A, B or C as named; arm B's
       three parts and both arm C runs on S3's two guidance files, arm A on none; the loop and
       the no-docket run with the frozen ``agent_prompt_version`` and ``without: []``; the
       no-docket run excluding exactly the two docket roles and the others none; arm B's tool
       post-pass labelled ``<answer>+tools-s3+p947fac1c86a4`` and its check ending
       ``+check-luna-s3``.
    4. Each of the six runs has a row in ``docs/results/heldout-ledger.md`` (decision 0026).
    5. Each case file holds held-out cases only, and the whole of ``heldout-400``.

What it prints
    Nine sections, in this order: provenance (with each run's ledger row, and each held-out
    run's failures by kind); the verdict (the loop minus arm B's final run on top-1, its outcome,
    the billed cost of each arm, the band, the work done in prompt and reply tokens,
    ``warranted`` and the headline); the secondary readings (top-3 and finding recall@10); where
    the saving comes from; the four results; the abstain reading; the no-docket ablation, each
    arm's own top-1 and arm A; the nine predictions; and the reading (spec §10).

Usage
    uv run python -m scripts.s32_claims --loop RUN --nodocket RUN --arm-a RUN --armb-answer RUN
        --armb-tools RUN --armb-check RUN --ablation RUN --noise RUN RUN [--out PATH]
"""

import argparse
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring import calibration, checkpass, claims, report, samples
from ntsb_probable_cause.scoring.calibration import ABSTAIN_BELOW, GroupCheck
from ntsb_probable_cause.scoring.claims import Billed, CostBand, Metric, Outcome, Paired
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.metrics import bootstrap_mean
from ntsb_probable_cause.scoring.records import (
    CONTEXT_FAILURE,
    CaseResult,
    RunRecord,
    read_jsonl,
)
from ntsb_probable_cause.settings import Settings
from scripts._s3_runs import Run, refuse, refuse_unclean_results, write_result
from scripts.s3_noise_floor import Gate, format_gate
from scripts.s32_behaviour import (
    ReadCounts,
    Routes,
    effect_routes,
    effects_naming_codes,
    read_counts,
    result1_holds,
    tally_line,
)
from scripts.s32_coding_ablation import (
    NOISE_RUNS,
    Prediction6,
    load_ablation,
    points,
    prediction6,
    prediction6_line,
)

PROG: Final = "s32_claims"
SAMPLE: Final = "heldout-400"
# What the registration names (spec §2, §5, §3). Literals, not the code's defaults: a default
# that moved later must not change what this script holds the held-out runs to.
FROZEN_PROMPT: Final = "s3-v1+ge17fecdc66ec+p947fac1c86a4"
FROZEN_MARK: Final = "+" + FROZEN_PROMPT.rsplit("+", 1)[1]
MODEL: Final = "openai/gpt-6-luna"
EFFORT: Final = "medium"
MAX_OUTPUT_TOKENS: Final = 8000
CAP_USD: Final = 0.30
STATS: Final = "s3"
GUIDANCE: Final = ("r3-loc-stall", "r6-aircraft-control")
DOCKET_ROLES: Final = ("docket_documents", "docket_listing")
TOOLS_SUFFIX: Final = "-tools"
TOOLS_LABEL: Final = "+tools-s3"
CHECK_LABEL: Final = "+check-luna-s3"
WAY: Final = "luna"
FORMAT_GATE_MAX: Final = 8  # prediction 9 (spec §12)
SMALL_DROP: Final = -0.10  # prediction 5: ten points
RARE: Final = 20  # "fewer than 5%" is 20 * part < whole
GUARD: Final = "guard refusals"
CAP: Final = "cap"
OTHER: Final = "other"
# The loop's and the tool post-pass's own stop reason, ``failed: <step>`` (agent/loop.py,
# agent/armb.py): a step name, never a case number or a reply's text.
_FAILED_STEP: Final = re.compile(r"failed: [a-z0-9_]+")
# Arm B's answer run records a document left out at the context ceiling as
# ``<index>: context, <N> tokens`` (scoring/runner.py, decision 152).
_CONTEXT_DOCUMENT: Final = re.compile(r"\d+: context, ")
_METRICS: Final[tuple[tuple[Metric, str], ...]] = (
    ("top1", "top-1"),
    ("top3", "top-3"),
    ("recall10", "recall@10"),
)


@dataclass(frozen=True)
class Role:
    """What the registration names for one held-out run.

    Attributes:
        flag: the command-line flag that names the run, without its dashes.
        arm: the run record's arm.
        guidance: the guidance files the run read.
        exclusions: the evidence roles the run left out; None when not checked (arm A).
        batch: whether the run was priced in batch.
        loop: whether the run is an arm C run (its ``spec.json`` is read).
        trail: whether the run keeps a ``trail.jsonl`` that must be present.
    """

    flag: str
    arm: str
    guidance: tuple[str, ...]
    exclusions: tuple[str, ...] | None
    batch: bool = True
    loop: bool = False
    trail: bool = False


ROLES: Final = (
    Role("arm-a", "A", (), None),
    Role("armb-answer", "B", GUIDANCE, ()),
    Role("armb-tools", "B", GUIDANCE, (), trail=True),
    Role("armb-check", "B", GUIDANCE, (), batch=False),
    Role("loop", "C", GUIDANCE, (), loop=True, trail=True),
    Role("nodocket", "C", GUIDANCE, DOCKET_ROLES, loop=True, trail=True),
)


@dataclass(frozen=True)
class Held:
    """The six held-out runs, read whole."""

    arm_a: Run
    answer: Run
    tools: Run
    check: Run
    loop: Run
    nodocket: Run

    @property
    def runs(self) -> tuple[Run, ...]:
        """The six, in the order of the ledger section."""
        return (self.arm_a, self.answer, self.tools, self.check, self.loop, self.nodocket)


# --------------------------------------------------------------------------------------------
# Refusals and loading: the held-out path, this script's own
# --------------------------------------------------------------------------------------------


def refuse_ids(args: argparse.Namespace) -> None:
    """Refuse bad ids, before anything is read (spec §3: arm B is answer, tools, check)."""
    ids = [
        args.loop,
        args.nodocket,
        args.arm_a,
        args.armb_answer,
        args.armb_tools,
        args.armb_check,
    ]
    if len(set(ids)) != len(ids):
        refuse(PROG, "a run is named twice; the six held-out runs are distinct")
    if args.armb_tools != args.armb_answer + TOOLS_SUFFIX:
        refuse(PROG, f"--armb-tools must be the --armb-answer id followed by {TOOLS_SUFFIX}")
    if args.armb_check != checkpass.derived_id(args.armb_tools, WAY):
        refuse(
            PROG,
            f"--armb-check must be the folder checkpass.derived_id names: the --armb-tools id "
            f"followed by -check-{WAY}",
        )
    if sorted(args.noise) != sorted(NOISE_RUNS):
        refuse(
            PROG, "--noise must be the two noise-floor runs named in scripts/s32_coding_ablation"
        )
    for run_id in ids:
        if SAMPLE not in run_id:
            refuse(PROG, f"{run_id} is not a {SAMPLE} run id")


def _expect(run_id: str, name: str, got: object, want: object) -> None:
    if got != want:
        refuse(PROG, f"{run_id}: {name} is {got!r}; the registration names {want!r}")


def _spec(run_id: str, folder: Path) -> dict[str, object]:
    path = folder / "spec.json"
    try:
        recorded = json.loads(path.read_text()) if path.is_file() else None
    except json.JSONDecodeError:
        recorded = None
    if not isinstance(recorded, dict):
        refuse(PROG, f"{run_id}: no readable spec.json in {folder}")
    return recorded


def _head(role: Role, run_id: str) -> tuple[RunRecord, dict[str, object]]:
    """A held-out run's record (and ``spec.json`` for an arm C run), after every head refusal."""
    folder = Settings().runs_dir / run_id
    if not (folder / "run.jsonl").is_file():
        refuse(PROG, f"{run_id}: no run.jsonl in {folder}")
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    _expect(run_id, "run_id in run.jsonl", record.run_id, run_id)
    _expect(run_id, "sample", record.sample, SAMPLE)
    _expect(run_id, "arm", record.arm, role.arm)
    if record.finished is None:
        refuse(PROG, f"{run_id} has not finished: it did not complete a pass")
    if record.dirty:
        refuse(PROG, f"{run_id} ran from a tree with uncommitted changes (decision 0026)")
    _expect(run_id, "model", record.model, MODEL)
    _expect(run_id, "reasoning_effort", record.reasoning_effort, EFFORT)
    _expect(run_id, "max_output_tokens", record.max_output_tokens, MAX_OUTPUT_TOKENS)
    _expect(run_id, "cap_usd", record.cap_usd, CAP_USD)
    _expect(run_id, "evidence_version", record.evidence_version, "v1")
    _expect(run_id, "guidance", record.guidance, role.guidance)
    if role.batch:
        _expect(run_id, "price_variant", record.price_variant, "batch")
    if role.exclusions is not None:
        _expect(run_id, "exclusions", tuple(sorted(record.exclusions)), role.exclusions)
    spec: dict[str, object] = {}
    if role.loop:
        spec = _spec(run_id, folder)
        _expect(run_id, "agent_prompt_version", spec.get("agent_prompt_version"), FROZEN_PROMPT)
        _expect(run_id, "prompt_version", record.prompt_version, FROZEN_PROMPT)
        _expect(run_id, "without", spec.get("without"), [])
        _expect(run_id, "stats", spec.get("stats"), STATS)
        if spec.get("dirty"):
            refuse(PROG, f"{run_id}: spec.json says it ran from a tree with uncommitted changes")
    if role.trail and not (folder / TRAIL_FILE).is_file():
        refuse(PROG, f"{run_id}: no {TRAIL_FILE} in {folder}")
    return record, spec


def _refuse_labels(answer: RunRecord, tools: RunRecord, check: RunRecord) -> None:
    """Arm B's three parts name one another in their prompt versions (spec §2, §3)."""
    want = answer.prompt_version + TOOLS_LABEL
    if not (tools.prompt_version.startswith(want) and tools.prompt_version.endswith(FROZEN_MARK)):
        refuse(
            PROG,
            f"{tools.run_id}: its prompt version is not the answer run's followed by "
            f"{TOOLS_LABEL} and the frozen text mark {FROZEN_MARK}",
        )
    if not (
        check.prompt_version.startswith(tools.prompt_version)
        and check.prompt_version.endswith(CHECK_LABEL)
    ):
        refuse(
            PROG,
            f"{check.run_id}: its prompt version is not the tool post-pass's followed by "
            f"{CHECK_LABEL}",
        )


def ledger_rows(run_ids: Sequence[str]) -> dict[str, list[str]]:
    """The held-out ledger's rows for each run; a run with none is refused (decision 0026)."""
    path = Settings().heldout_ledger_path
    if not path.is_file():
        refuse(PROG, f"the held-out ledger {path} is missing")
    lines = path.read_text().splitlines()
    found: dict[str, list[str]] = {}
    for run_id in run_ids:
        rows = [ln.strip() for ln in lines if ln.rstrip().endswith(f"| {run_id}/cases.jsonl |")]
        if not rows:
            refuse(PROG, f"{run_id} has no row in the held-out ledger {path}")
        found[run_id] = rows
    return found


def _read(role: Role, run_id: str, head: tuple[RunRecord, dict[str, object]]) -> Run:
    """A held-out run's cases and trail: held-out cases only, and the whole sample."""
    folder = Settings().runs_dir / run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != "heldout" for c in cases):
        refuse(PROG, f"{run_id} holds a case outside the held-out split")
    if {c.case_id for c in cases} != set(samples.sample_ids(SAMPLE)) or len(cases) != len(
        samples.sample_ids(SAMPLE)
    ):
        refuse(PROG, f"{run_id} is not the whole of {SAMPLE} ({len(cases)} cases)")
    calls = read_jsonl(folder / TRAIL_FILE, AgentCall) if role.trail else []
    return Run(role.flag, head[0], head[1], cases, calls)


def load_heldout(args: argparse.Namespace) -> Held:
    """Refuse what must be refused, then read the six held-out runs.

    The only code path that opens a held-out run folder. It is reached after
    :func:`refuse_ids` and the registration check.

    Raises:
        SystemExit: any refusal in the module's docstring.
    """
    ids = [
        args.arm_a,
        args.armb_answer,
        args.armb_tools,
        args.armb_check,
        args.loop,
        args.nodocket,
    ]
    heads = [_head(role, run_id) for role, run_id in zip(ROLES, ids, strict=True)]
    _refuse_labels(heads[1][0], heads[2][0], heads[3][0])
    ledger_rows(ids)
    runs = [_read(role, run_id, head) for role, run_id, head in zip(ROLES, ids, heads, strict=True)]
    return Held(*runs)


# --------------------------------------------------------------------------------------------
# The measures
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """One paired reading (first arm minus second), and the both-answered one beside it."""

    paired: Paired
    both: Paired | None


def read_pair(a: Sequence[CaseResult], b: Sequence[CaseResult], metric: Metric) -> Reading:
    """The paired difference and, when any case was answered by both, the one beside it."""
    paired = claims.paired(a, b, metric)
    try:
        both: Paired | None = claims.both_answered(a, b, metric)
    except ValueError:
        both = None
    return Reading(paired, both)


def _reading_text(reading: Reading) -> str:
    beside = (
        f"both answered {points(reading.both)}"
        if reading.both is not None
        else "both answered: no case was answered by both"
    )
    return f"{points(reading.paired)}; {beside}"


Level = tuple[float, float, float, int]
"""One arm's own top-1: the mean, its 95% bootstrap interval, and the cases it rests on."""


def level(cases: Sequence[CaseResult]) -> Level:
    """One arm's own top-1 under the failure rule (spec §7.3), alone, not paired.

    Every failure counts as wrong; a guard refusal is left out of this arm (in a paired
    reading it leaves both).
    """
    values = list(claims.per_case(cases, "top1").values())
    return (*bootstrap_mean(values), len(values))


def failure_kinds(cases: Sequence[CaseResult]) -> dict[str, int]:
    """Failed cases counted by kind, never naming a case or quoting a message.

    The kinds are guard refusals (``claims.is_guard_refusal``), each ``failed: <step>`` the loop
    or the tool post-pass wrote, ``cap``, ``cap: context`` (decision 152) and other. All but the
    steps are always present, at zero when none; the steps come in their alphabetical order.
    """
    steps: dict[str, int] = {}
    fixed = dict.fromkeys((GUARD, CAP, CONTEXT_FAILURE, OTHER), 0)
    for case in cases:
        failure = case.failure
        if failure is None:
            continue
        if claims.is_guard_refusal(case):
            fixed[GUARD] += 1
        elif failure in (CAP, CONTEXT_FAILURE):
            fixed[failure] += 1
        elif _FAILED_STEP.fullmatch(failure):
            steps[failure] = steps.get(failure, 0) + 1
        else:
            fixed[OTHER] += 1
    return {GUARD: fixed[GUARD], **dict(sorted(steps.items()))} | {
        k: fixed[k] for k in (CAP, CONTEXT_FAILURE, OTHER)
    }


def context_left_out(cases: Sequence[CaseResult]) -> tuple[int, int]:
    """Documents arm B left out at the context ceiling, and the cases that had one (152)."""
    per_case = [sum(1 for d in c.documents_not_read if _CONTEXT_DOCUMENT.match(d)) for c in cases]
    return sum(per_case), sum(1 for n in per_case if n)


@dataclass(frozen=True)
class Abstain:
    """The abstain cut-off applied to the loop's scored answers (spec §8.4)."""

    scored: int
    fired: int
    right_fired: int
    right_kept: int


@dataclass(frozen=True)
class Figures:
    """Every figure the report prints, measured once."""

    reading: dict[Metric, Reading]
    outcome: Outcome
    loop_billed: Billed
    armb_billed: tuple[Billed, Billed, Billed]
    armb_usd: float
    armb_computed: float
    band: CostBand
    warranted: bool
    split: claims.SavingSplit
    counts: ReadCounts
    routes: Routes
    named: tuple[int, int]
    groups: tuple[GroupCheck, GroupCheck, GroupCheck]
    calibrated: bool
    sorting: tuple[float, float, float]
    floor: float
    abstain: Abstain
    nodocket: dict[Metric, Reading]
    arm_a: Level
    levels: tuple[tuple[str, Level], ...]
    gate: Gate
    p6: Prediction6


def measure(held: Held, ablation: Run, noise: Sequence[Run]) -> Figures:
    """Measure everything the report prints.

    Raises:
        ValueError: two runs do not cover the same cases, or a reading has no case to pair.
    """
    loop, final = held.loop.cases, held.check.cases
    reading = {metric: read_pair(loop, final, metric) for metric, _ in _METRICS}
    outcome = claims.outcome(reading["top1"].paired)
    loop_billed = claims.billed(held.loop.record)
    parts = (
        claims.billed(held.answer.record),
        claims.billed(held.tools.record),
        claims.billed(held.check.record),
    )
    armb_usd = sum(b.usd for b in parts)
    band = claims.cost_band(loop_billed.usd, armb_usd)
    curve = calibration.load_curve()
    answers = [
        (c.case_id, curve.p(s.confidence), s.occurrence_top1)
        for c in loop
        if (s := claims.answered(c)) is not None
    ]
    groups = calibration.three_groups(answers)
    fired = [right for _, p, right in answers if calibration.abstains(p)]
    kept = [right for _, p, right in answers if not calibration.abstains(p)]
    tables = load_tables()
    return Figures(
        reading=reading,
        outcome=outcome,
        loop_billed=loop_billed,
        armb_billed=parts,
        armb_usd=armb_usd,
        armb_computed=sum(b.computed_usd for b in parts),
        band=band,
        warranted=claims.warranted(outcome, band),
        split=claims.saving_split([loop_billed], parts),
        counts=read_counts(held.loop.calls, loop),
        routes=effect_routes(held.loop.calls, tables),
        named=effects_naming_codes(held.loop.calls, tables),
        groups=groups,
        calibrated=calibration.calibrated(groups),
        sorting=calibration.sorting(groups),
        floor=curve.p(0.0),
        abstain=Abstain(len(answers), len(fired), sum(fired), sum(kept)),
        nodocket={metric: read_pair(held.nodocket.cases, loop, metric) for metric, _ in _METRICS},
        arm_a=level(held.arm_a.cases),
        levels=(
            ("the loop", level(loop)),
            ("arm B (final)", level(final)),
            ("the loop without the docket", level(held.nodocket.cases)),
        ),
        gate=format_gate(loop, held.loop.calls),
        p6=prediction6(ablation.cases, [r.cases for r in noise]),
    )


# --------------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------------


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.1%})" if whole else f"{part} of {whole}"


def _usd(value: float) -> str:
    return f"{value:.4f} USD"


def _tokens(label: str, calls: Sequence[AgentCall]) -> str:
    prompt = sum(c.prompt_tokens for c in calls)
    cached = sum(c.cached_tokens or 0 for c in calls)
    reply = sum(c.completion_tokens for c in calls)
    return f"{label}: {prompt} prompt tokens, {cached} cached, {reply} reply tokens"


def _step_tokens(label: str, cases: Sequence[CaseResult], tool: str | None, note: str) -> str:
    """The prompt and reply tokens a run's steps record; ``tool`` keeps that tool's steps only."""
    steps = [s for c in cases for s in c.steps if tool is None or s.tool == tool]
    prompt = sum(s.prompt_tokens for s in steps)
    reply = sum(s.completion_tokens for s in steps)
    return f"{label}: {prompt} prompt tokens, {reply} reply tokens ({note})"


def _run_names(held: Held) -> list[tuple[str, Run]]:
    names = (
        "arm A",
        "arm B answer",
        "arm B tool post-pass",
        "arm B ordering check",
        "the loop",
        "the loop without the docket",
    )
    return list(zip(names, held.runs, strict=True))


def provenance_lines(held: Held, ablation: Run, noise: Sequence[Run]) -> list[str]:
    """Section 1: every run's provenance, and the ledger rows found for the held-out ones."""
    rows = ledger_rows([run.record.run_id for run in held.runs])
    lines = ["## 1. Provenance"]
    for name, run in _run_names(held):
        lines += [f"[{name}]", report.provenance(run.record).rstrip()]
        lines += [f"ledger: {row}" for row in rows[run.record.run_id]]
    for name, run in (
        ("coding ablation (dev-400)", ablation),
        ("noise run a (dev-400)", noise[0]),
        ("noise run b (dev-400)", noise[1]),
    ):
        lines += [f"[{name}]", report.provenance(run.record).rstrip()]
    return [*lines, *failure_lines(held)]


def failure_lines(held: Held) -> list[str]:
    """Each held-out run's failures by kind, and arm B's documents left out at the ceiling."""
    lines = [
        "failures by kind (a guard refusal leaves the case out of both arms; every other "
        "failure counts as wrong; spec §7.3):"
    ]
    for name, run in _run_names(held):
        kinds = failure_kinds(run.cases)
        detail = ", ".join(f"{kind} {count}" for kind, count in kinds.items())
        line = f"- {name}: {sum(kinds.values())} of {len(run.cases)} failed: {detail}"
        if run is held.answer:
            documents, cases = context_left_out(run.cases)
            line += (
                "; documents left out at the context ceiling (recorded context): "
                f"{documents} in {cases} case{'' if cases == 1 else 's'}"
            )
        lines.append(line)
    return lines


def _billing_notes(fig: Figures) -> list[str]:
    unbilled = [
        name
        for name, billed in (
            ("the loop", fig.loop_billed),
            ("arm B's answer run", fig.armb_billed[0]),
            ("arm B's tool post-pass", fig.armb_billed[1]),
            ("arm B's ordering check", fig.armb_billed[2]),
        )
        if not billed.is_billed
    ]
    if not unbilled:
        return ["every figure used is a billed figure"]
    return [
        f"NOTE: no billed figure was reported for {name}; its computed cost stands in"
        for name in unbilled
    ]


def verdict_lines(held: Held, fig: Figures) -> list[str]:
    """Section 2: top-1 decides, cost is billed, the headline is one of the fixed sentences."""
    top1 = fig.reading["top1"]
    parts = " + ".join(
        f"{name} {b.usd:.4f}"
        for name, b in zip(("answer", "tools", "check"), fig.armb_billed, strict=True)
    )
    change = (fig.loop_billed.usd - fig.armb_usd) / fig.armb_usd if fig.armb_usd else 0.0
    return [
        "## 2. The verdict (occurrence top-1 decides; spec §7)",
        f"top-1, loop - arm B: {_reading_text(top1)}",
        f"bottom of the interval: {top1.paired.low * 100:+.1f} points "
        "(a stricter margin can be applied to this figure)",
        f"outcome: {fig.outcome}",
        f"cost, billed (spec §6): loop billed {_usd(fig.loop_billed.usd)}, "
        f"computed {_usd(fig.loop_billed.computed_usd)}",
        f"arm B billed {_usd(fig.armb_usd)} ({parts})",
        f"arm B computed {_usd(fig.armb_computed)}",
        *_billing_notes(fig),
        f"the loop's bill against arm B's: {change:+.1%}",
        f"cost band: {fig.band} (lower or greater: more than 10% below or above arm B's bill)",
        "work done (printed beside, never deciding; spec §6 rule 3):",
        _tokens("loop", held.loop.calls),
        _step_tokens(
            "arm B answer",
            held.answer.cases,
            None,
            "the steps of the cases that answered; a failed case records no step",
        ),
        _tokens("arm B tool post-pass", held.tools.calls),
        _step_tokens(
            "arm B ordering check", held.check.cases, checkpass.CHECK_TOOL, "its own steps"
        ),
        f"warranted: {'yes' if fig.warranted else 'no'}",
        claims.headline(fig.outcome, fig.band),
    ]


def secondary_lines(fig: Figures) -> list[str]:
    """Section 3: top-3 and finding recall@10 under the same rule; neither decides."""
    lines = ["## 3. Secondary readings (same rule; neither decides)"]
    for metric, name in _METRICS[1:]:
        reading = fig.reading[metric]
        lines += [
            f"{name}, loop - arm B: {_reading_text(reading)}",
            f"{name} outcome (not deciding): {claims.outcome(reading.paired)}; bottom of the "
            f"interval {reading.paired.low * 100:+.1f} points",
        ]
    return lines


def saving_lines(fig: Figures) -> list[str]:
    """Section 4: the work done and each arm's cache discount (spec §10)."""
    split = fig.split
    lines = [
        "## 4. Where the saving comes from (spec §10)",
        f"work (loop computed - arm B computed): {split.work_usd:+.4f} USD",
        f"loop discount (computed - billed): {_usd(split.loop_discount_usd)}",
        f"arm B discount (computed - billed): {_usd(split.armb_discount_usd)}",
    ]
    saving = fig.armb_usd - fig.loop_billed.usd
    lines.append(
        f"billed saving (arm B billed - loop billed) {saving:+.4f} USD = reading less "
        f"(-work) {-split.work_usd:+.4f} USD + cache discounts (loop discount - arm B "
        f"discount) {split.loop_discount_usd - split.armb_discount_usd:+.4f} USD"
    )
    lines.append(
        'a negative "reading less" figure means the loop did more list-price work than arm B '
        "(not a saving but a cost)"
    )
    if fig.band == "lower":
        lines.append(
            f"the loop's saving comes from reading less: {-split.work_usd:+.4f} USD, and from "
            f"cache discounts: {split.loop_discount_usd - split.armb_discount_usd:+.4f} USD "
            "(a negative figure is not a saving but a cost)"
        )
    return lines


def _result1_finding(counts: ReadCounts) -> str:
    """What was found, in words: the bracket after result 1 states the finding, not the rule."""
    if result1_holds(counts):
        return "more than half on at least one reading"
    return "not more than half on either reading"


def _result2_finding(top1: Outcome, band: CostBand) -> str:
    """What was found, in words: the bracket after result 2 states the finding, not the rule."""
    if claims.result2_holds(top1, band):
        return "the loop does not beat arm B on top-1 and its bill is not lower"
    return "the loop beats arm B on top-1 or its bill is lower"


def _result3_finding(calibrated: bool) -> str:
    """What was found, in words: result 3 holds when the curve fails the three-group test.

    Passing the test does not show the curve is calibrated, only that it was not shown to be
    miscalibrated; the words say so.
    """
    state = (
        "passes the three-group test (not shown to be miscalibrated)"
        if calibrated
        else "fails the three-group test"
    )
    return f"the fitted confidence {state} on held-out"


def results_lines(fig: Figures) -> list[str]:
    """Section 5: the four results that count against the loop (spec §9)."""
    counts, routes = fig.counts, fig.routes
    top1 = claims.outcome(fig.reading["top1"].paired)
    lines = [
        "## 5. The four results",
        f"result 1: {'holds' if result1_holds(counts) else 'does not hold'} "
        f"({_result1_finding(counts)}; spec §9.1)",
        f"- cases counted {counts.counted}, with documents on offer {counts.with_offer}",
        f"- read every document on offer: {_share(counts.read_everything, counts.with_offer)} "
        "of the cases with documents on offer",
        "- first used the coding tools in arm B's fixed order: "
        f"{_share(counts.fixed_order, counts.counted)} of the cases counted",
        "- by fatal and non-fatal:",
        *(tally_line(name, t) for name, t in counts.by_fatal.items()),
        "- by documents offered (docket size):",
        *(tally_line(name, t) for name, t in counts.by_offered.items()),
        f"result 2: {'holds' if claims.result2_holds(top1, fig.band) else 'does not hold'} "
        f"({_result2_finding(top1, fig.band)}; outcome {top1}, band {fig.band}; spec §9.2)",
        f"result 3: {'does not hold' if fig.calibrated else 'holds'} "
        f"({_result3_finding(fig.calibrated)}; spec §9.3, §8.3)",
    ]
    for name, group in zip(("low", "middle", "high"), fig.groups, strict=True):
        lines.append(
            f"- group {name}: n={group.n}, mean fitted {group.mean_fitted:.3f}, right "
            f"{_share(group.right, group.n)}, 98.3% interval [{group.low:.3f}, "
            f"{group.high:.3f}], {'inside' if group.inside else 'outside'}"
        )
    diff, low, high = fig.sorting
    lines += [
        "- three-group test: "
        + (
            "passes (every group inside its interval)"
            if fig.calibrated
            else "fails (a group outside its interval)"
        ),
        "- sorting (share right in the high group minus the low group): "
        f"{diff * 100:+.1f} points [{low * 100:+.1f}, {high * 100:+.1f}] (reported, not tested)",
        "result 4: not shown (spec §9.4)",
        f"- stated effects on documents read: {routes.total}",
        f"- naming an event or a finding category, any route (an upper bound; the "
        f"category-leaf route is loose): {fig.named[0]} of {fig.named[1]}",
        f"- by route: event label (strict) {routes.event_label}, category leaf (loose) "
        f"{routes.category_leaf}, event code {routes.event_code} (an effect can match more "
        "than one route)",
    ]
    return lines


def abstain_lines(fig: Figures) -> list[str]:
    """Section 6: the abstain cut-off on the loop's scored answers (spec §8.4)."""
    ab = fig.abstain
    can = fig.floor < ABSTAIN_BELOW
    reach = "can" if can else "cannot"
    fired = (
        f"fired on {ab.fired} of {ab.scored} scored loop cases ({ab.fired / ab.scored:.1%})"
        if ab.scored
        else "no scored loop case"
    )
    return [
        "## 6. Abstain",
        f"curve floor p(0) = {fig.floor:.3f}; the abstain cut-off {ABSTAIN_BELOW} {reach} fire "
        "on this curve" + ("" if can else " at all"),
        fired,
        f"right among abstained: {_share(ab.right_fired, ab.fired)}",
        f"right among answered: {_share(ab.right_kept, ab.scored - ab.fired)}",
    ]


def ablation_lines(fig: Figures) -> list[str]:
    """Section 7: the no-docket ablation (paired against the loop) and arm A."""
    mean, low, high, n = fig.arm_a
    lines = ["## 7. The no-docket ablation and arm A"]
    lines += [
        f"no-docket - loop, {name}: {_reading_text(fig.nodocket[metric])}"
        for metric, name in _METRICS
    ]
    lines += [_level_line(name, value) for name, value in fig.levels]
    lines.append(
        f"arm A top-1: {mean:.1%} [{low:.1%}, {high:.1%}], n={n} (start facts only; decides "
        "nothing)"
    )
    return lines


def _level_line(name: str, value: Level) -> str:
    mean, low, high, n = value
    return f"{name} top-1: {mean:.1%} [{low:.1%}, {high:.1%}], n={n} (a failure counts as wrong)"


def _verdict(met: bool) -> str:
    return "met" if met else "not met"


def gate_lines(label: str, gate: Gate) -> list[str]:
    """The format gate of a held-out run, naming the run's own case count."""
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(gate.failed.items())) or "none"
    return [
        f"format gate, run {label}: {'PASS' if gate.count <= FORMAT_GATE_MAX else 'FAIL'} -- "
        f"{gate.count} of {gate.cases} cases failed for format or tool reasons ({reasons}); of "
        f"which {gate.no_reply} had no reply on the failing call; at most {FORMAT_GATE_MAX} of "
        f"{gate.cases} pass (prediction 9, counted as scripts/s3_noise_floor.py counts it)",
        f"round limit (failed: rounds), run {label}: {gate.rounds} of {gate.cases} cases (not a "
        "format or tool failure, so not in the gate)",
    ]


def prediction_lines(fig: Figures) -> list[str]:
    """Section 8: the nine predictions, each with the figure it was read from."""
    top1 = fig.reading["top1"].paired
    top3 = fig.reading["top3"].paired
    recall = fig.reading["recall10"].paired
    nodocket = fig.nodocket["top1"].paired
    counts = fig.counts
    p7 = (
        2 * counts.read_everything > counts.with_offer
        and RARE * counts.fixed_order < counts.counted
    )
    p8 = fig.calibrated and RARE * fig.abstain.fired < fig.abstain.scored
    p9 = fig.gate.count <= FORMAT_GATE_MAX
    return [
        "## 8. The predictions (registered in docs/rounds/s3-registration.md; spec §12)",
        *gate_lines("loop", fig.gate),
        f"P1: {_verdict(fig.outcome == 'matches')} -- top-1: the loop matches but does not beat "
        f"arm B (outcome {fig.outcome}; interval [{top1.low * 100:+.1f}, {top1.high * 100:+.1f}])",
        f"P2: {_verdict(fig.band == 'lower')} -- cost: the loop's bill is more than 10% below "
        f"arm B's (loop {_usd(fig.loop_billed.usd)}, arm B {_usd(fig.armb_usd)}, band {fig.band})",
        f"P3: {_verdict(top3.high < 0)} -- top-3: the loop is below arm B, the interval wholly "
        f"below zero (top of the interval {top3.high * 100:+.1f} points)",
        f"P4: {_verdict(recall.low <= 0 <= recall.high)} -- findings: recall@10 is level, the "
        f"interval including zero ([{recall.low * 100:+.1f}, {recall.high * 100:+.1f}])",
        f"P5: {_verdict(round(nodocket.mean, 9) <= SMALL_DROP)} -- without the docket the loop "
        f"loses at least 10.0 points of top-1 (without - with {nodocket.mean * 100:+.1f} points)",
        prediction6_line(fig.p6, "P6"),
        f"P7: {_verdict(p7)} -- result 1: reads every offered document on more than half "
        f"({_share(counts.read_everything, counts.with_offer)}) and uses arm B's exact order on "
        f"fewer than 5% ({_share(counts.fixed_order, counts.counted)})",
        f"P8: {_verdict(p8)} -- the three-group test passes ({'yes' if fig.calibrated else 'no'}) "
        f"and the abstain cut-off fires on fewer than 5% of scored cases "
        f"({fig.abstain.fired} of {fig.abstain.scored}){_by_construction(fig.floor)}",
        f"P9: {_verdict(p9)} -- format: at most {FORMAT_GATE_MAX} cases fail for format or tool "
        f"reasons in the loop run ({fig.gate.count} of {fig.gate.cases})",
    ]


def _by_construction(floor: float) -> str:
    """Prediction 8's disclosure: a curve whose lowest value is not below the cut-off never fires.

    The curve rises (``calibration.check_rising``), so its lowest value is ``p(0)``.
    """
    if floor < ABSTAIN_BELOW:
        return ""
    where = "above" if floor > ABSTAIN_BELOW else "at"
    return (
        f" (the abstain half is met by construction: the curve's lowest value is {floor:.3f}, "
        f"{where} the {ABSTAIN_BELOW} cut-off; registration disclosure)"
    )


def reading_lines(fig: Figures) -> list[str]:
    """Section 9: how the results are read together (spec §10)."""
    counts = fig.counts
    top1 = claims.outcome(fig.reading["top1"].paired)
    result3 = not fig.calibrated
    return [
        "## 9. The reading (spec §10)",
        f"question 1: {claims.headline(fig.outcome, fig.band)}",
        "results 1 to 4 say how that came about; they do not overturn it:",
        f"result 1: {'holds' if result1_holds(counts) else 'does not hold'} "
        f"(read every offered document on {_share(counts.read_everything, counts.with_offer)})",
        f"result 2: {'holds' if claims.result2_holds(top1, fig.band) else 'does not hold'} "
        f"(outcome {top1}, cost band {fig.band})",
        f"result 3: {'holds' if result3 else 'does not hold'} ({_result3_finding(fig.calibrated)})",
        "result 4: not shown (the stated effects are descriptions, not predictions of change)",
        "question 2: what the board may show",
        "- the board shows its confidence "
        + (
            "with a plain warning (result 3 holds)"
            if result3
            else "as fitted (result 3 does not hold)"
        ),
        '- the board labels a stated effect "the agent\'s note", never a prediction '
        "(result 4 is not shown)",
    ]


def report_lines(held: Held, ablation: Run, noise: Sequence[Run], fig: Figures) -> list[str]:
    """The whole report, nine sections."""
    sections = [
        provenance_lines(held, ablation, noise),
        verdict_lines(held, fig),
        secondary_lines(fig),
        saving_lines(fig),
        results_lines(fig),
        abstain_lines(fig),
        ablation_lines(fig),
        prediction_lines(fig),
        reading_lines(fig),
    ]
    header = [
        "S3.2 held-out claims (scripts/s32_claims.py; spec §6 to §12)",
        "Counts only: no case number. Differences are in points, with the 95% bootstrap "
        "interval and the cases they rest on. A guard refusal removes a case from both arms; "
        "every other failure counts as wrong (spec §7.3).",
        "",
    ]
    return header + [line for section in sections for line in (*section, "")][:-1]


def _fail(error: ValueError) -> NoReturn:
    refuse(PROG, str(error))


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the held-out claims."""
    parser = argparse.ArgumentParser(prog=PROG)
    for flag, help_text in (
        ("loop", "the held-out loop run"),
        ("nodocket", "the held-out loop run without the docket"),
        ("arm-a", "the held-out arm A run"),
        ("armb-answer", "the held-out arm B answer run"),
        ("armb-tools", "arm B's tool post-pass: <armb-answer>-tools"),
        ("armb-check", "arm B's ordering check: <armb-tools>-check-luna"),
        ("ablation", "the finished dev-400 coding-ablation run"),
    ):
        parser.add_argument(f"--{flag}", required=True, help=help_text)
    parser.add_argument("--noise", nargs=2, required=True, metavar="RUN")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    refuse_ids(args)
    if not gitinfo.is_committed(checkpass.S32_REGISTRATION):
        refuse(
            PROG,
            f"{checkpass.S32_REGISTRATION} is not committed: the held-out runs are read only "
            "after the registration is on record (decision 0142)",
        )
    if args.out is not None:
        refuse_unclean_results(PROG, Path(args.out))
    ablation, noise = load_ablation(PROG, args.ablation, args.noise)
    held = load_heldout(args)
    try:
        fig = measure(held, ablation, noise)
    except ValueError as error:
        _fail(error)
    text = "\n".join(report_lines(held, ablation, noise, fig))
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
