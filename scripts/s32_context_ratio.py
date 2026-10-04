"""How far the four-characters-a-token estimate undercounts a prompt, and the ceiling it sets.

Status
    Live measurement for S3.2 Task 15a (decision 152), free: reads finished ``dev-400`` run
    folders and makes no model call. Counts only (decision 0024): no case number, no prose.
    Its output is ``docs/results/s32-context-ratio-dev.txt`` (``make s32-context-ratio``). It
    sets ``sources.PROMPT_TOKEN_CEILING`` and shows that no development run made so far is
    changed by it.

Why
    Held-out arm B's answer batch was refused because one request was over GPT-6 Luna's
    1,050,000-token context window, and one such request fails a whole batch. The runner and
    the loop size a prompt at four characters a token. Document text, with its numbers and
    tables, tokenizes more densely than that, so a ceiling on the estimate must allow for the
    estimate's undercount. This script measures that undercount on the two noise-floor runs.

What it reads
    The two noise-floor runs (arm C, ``dev-400``; ``scripts/_s3_runs.py`` refuses anything else)
    and S3's ``dev-400`` arm B run with its tool post-pass (``<arm B run>-tools``). A held-out run
    or a sealed sample is refused before anything is read.

How a call's estimate is recovered
    ``agent/loop.py:estimate_usd`` prices a call as its prompt characters over 4 at the input
    price, plus ``max_output_tokens`` at the output price. So the estimate in tokens is
    ``(estimated_usd x 1e6 - max_output_tokens x output price) / input price``, with the run's
    model, price variant and reply budget. The real count is the reply's ``prompt_tokens``; a
    call with no reply (0) has no ratio, but its estimate is still counted against the ceiling.

The ceiling
    ``floor(0.8 x 1,050,000 / max ratio)``, rounded down to a thousand: at the largest measured
    undercount, a call at the ceiling is 80% of the window. The literal in ``sources.py`` is
    checked against it.

The three counts that must be 0
    - Noise-floor calls whose estimate is over the ceiling.
    - Arm B ``dev-400`` prompts over the ceiling. The payload text is not stored, so each case is
      bounded from above by its post-pass's first call: that call sends arm B's own payload and
      system text (the post-pass refuses a case whose payload has changed) plus the tool
      definitions and a turn, so its estimate is at least arm B's. A case the post-pass made no
      call for is bounded by its real prompt tokens (all its calls together) over the smallest
      measured ratio, and said so.
      A case that failed before any call (a guard refusal) sent nothing.
    - Arm B post-pass calls whose estimate is over the ceiling.

Usage
    uv run python -m scripts.s32_context_ratio RUN_A RUN_B [--armb RUN_ID] [--out PATH]
"""

import argparse
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts._s3_runs import SAMPLE, load_runs, refuse, refuse_unclean_results, write_result

PROG: Final = "s32_context_ratio"
# S3's dev-400 arm B run, whose tool post-pass is ``<this>-tools`` (CLAUDE.md, S3.1).
ARMB_RUN: Final = "20260929T053953-674c92e-dev-400-B"
TOOLS_SUFFIX: Final = "-tools"
WINDOW_SHARE: Final = 0.8
OVER_RATIO: Final = 1.5


def estimated_tokens(call: AgentCall, record: RunRecord) -> float:
    """The call's prompt estimate in tokens, recovered from its ``estimated_usd``."""
    variant = f"{record.model}:batch" if record.price_variant == "batch" else record.model
    price = sources.price_of(variant)
    reply = record.max_output_tokens * price.output_usd_per_mtok
    return (call.estimated_usd * 1e6 - reply) / price.input_usd_per_mtok


def ratios(calls: Sequence[AgentCall], record: RunRecord) -> list[float]:
    """Real over estimated prompt tokens for every call with a reply, sorted."""
    return sorted(
        c.prompt_tokens / estimated_tokens(c, record) for c in calls if c.prompt_tokens > 0
    )


def percentile(values: Sequence[float], share: float) -> float:
    """The nearest-rank percentile of sorted ``values``: the smallest with ``share`` at or below."""
    return values[max(math.ceil(share * len(values)) - 1, 0)]


def ceiling(max_ratio: float) -> tuple[int, int]:
    """The rule's value before rounding, and after rounding down to a thousand."""
    exact = math.floor(WINDOW_SHARE * sources.LUNA_6_CONTEXT_TOKENS / max_ratio)
    return exact, exact // 1000 * 1000


@dataclass(frozen=True)
class ArmBBound:
    """Arm B's prompts against the ceiling, case by case (see the module docstring)."""

    by_post_pass: int
    by_post_pass_largest: float
    by_real: int
    by_real_largest: float
    sent_none: int
    over: int


def armb_bound(
    cases: Sequence[CaseResult],
    post_pass: Sequence[AgentCall],
    record: RunRecord,
    *,
    min_ratio: float,
    limit: int,
) -> ArmBBound:
    """Bound each arm B case's prompt estimate from above and count those over ``limit``."""
    first: dict[str, AgentCall] = {}
    for call in post_pass:
        held = first.get(call.case_id)
        if held is None or call.call_index < held.call_index:
            first[call.case_id] = call
    by_post: list[float] = []
    by_real: list[float] = []
    sent_none = 0
    for case in cases:
        if case.case_id in first:
            by_post.append(estimated_tokens(first[case.case_id], record))
        elif case.steps:  # every call's prompt tokens together: at least the largest call's
            by_real.append(sum(step.prompt_tokens for step in case.steps) / min_ratio)
        else:
            sent_none += 1
    return ArmBBound(
        by_post_pass=len(by_post),
        by_post_pass_largest=max(by_post, default=0.0),
        by_real=len(by_real),
        by_real_largest=max(by_real, default=0.0),
        sent_none=sent_none,
        over=sum(1 for value in (*by_post, *by_real) if value > limit),
    )


def _armb_record(run_id: str) -> RunRecord:
    """A finished ``dev-400`` arm B run's record, after the refusals a reading needs."""
    try:
        samples.refuse_unless_development(run_id, None)
    except ConfigurationError as error:
        refuse(PROG, str(error))
    path = Settings().runs_dir / run_id / "run.jsonl"
    if not path.is_file():
        refuse(PROG, f"{run_id}: no run.jsonl in {path.parent}")
    record = read_jsonl(path, RunRecord)[0]
    if record.run_id != run_id:
        refuse(PROG, f"{run_id}: its run.jsonl names run {record.run_id}")
    if (record.sample, record.arm) != (SAMPLE, "B"):
        refuse(PROG, f"{run_id} is arm {record.arm} on {record.sample}, not arm B on {SAMPLE}")
    if record.finished is None:
        refuse(PROG, f"{run_id} has not finished")
    return record


def _armb(run_id: str) -> tuple[RunRecord, list[CaseResult], RunRecord, list[AgentCall]]:
    """Arm B's record and cases, and its post-pass's record and trail."""
    record = _armb_record(run_id)
    tools = _armb_record(run_id + TOOLS_SUFFIX)
    runs = Settings().runs_dir
    cases = read_jsonl(runs / run_id / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        refuse(PROG, f"{run_id} holds a case outside the dev split")
    trail = runs / tools.run_id / TRAIL_FILE
    if not trail.is_file():
        refuse(PROG, f"{tools.run_id}: no {TRAIL_FILE}")
    return record, cases, tools, read_jsonl(trail, AgentCall)


def report(run_ids: Sequence[str], armb_run: str) -> str:
    """The reading, as the text the results file holds."""
    runs = load_runs(PROG, run_ids)
    _, cases, tools, post_pass = _armb(armb_run)
    limit = sources.PROMPT_TOKEN_CEILING
    lines = [
        "S3.2 context ratio (scripts/s32_context_ratio.py; decision 152)",
        "Counts only: no case number.",
        *(f"run {run.label} = {run.record.run_id}" for run in runs),
        f"arm B = {armb_run}; its post-pass = {tools.run_id}",
        "estimate: a call's prompt characters / 4, recovered as (estimated_usd x 1e6 - "
        "max_output_tokens x output price) / input price (agent/loop.py estimate_usd); real: "
        "the reply's prompt_tokens",
    ]
    every: list[float] = []
    for run in runs:
        values = ratios(run.calls, run.record)
        every.extend(values)
        lines.append(
            f"run {run.label}: {len(values)} calls with a reply of {len(run.calls)}; ratio "
            f"real/estimated: min {values[0]:.4f}, median {statistics.median(values):.4f}, "
            f"p99 {percentile(values, 0.99):.4f}, max {values[-1]:.4f}; above {OVER_RATIO}: "
            f"{sum(1 for v in values if v > OVER_RATIO)}"
        )
    every.sort()
    top = every[-1]
    exact, rounded = ceiling(top)
    lines += [
        f"both runs: {len(every)} calls; ratio median {statistics.median(every):.4f}, p99 "
        f"{percentile(every, 0.99):.4f}, max {top:.4f}; above {OVER_RATIO}: "
        f"{sum(1 for v in every if v > OVER_RATIO)}",
        f"ceiling: floor({WINDOW_SHARE} x {sources.LUNA_6_CONTEXT_TOKENS:,} / {top:.4f}) = "
        f"{exact:,} -> {rounded:,} estimated tokens (rounded down to a thousand); "
        f"sources.PROMPT_TOKEN_CEILING = {limit:,} "
        f"({'the same' if rounded == limit else 'DIFFERENT: correct the literal'})",
    ]
    noise = [estimated_tokens(c, run.record) for run in runs for c in run.calls]
    lines.append(
        f"over the ceiling: noise-floor calls {sum(1 for v in noise if v > limit)} of "
        f"{len(noise)} (largest estimate {max(noise):,.0f})"
    )
    bound = armb_bound(cases, post_pass, tools, min_ratio=every[0], limit=limit)
    lines.append(
        f"over the ceiling: arm B dev-400 prompts {bound.over} of "
        f"{bound.by_post_pass + bound.by_real} cases that sent one; {bound.by_post_pass} bounded "
        f"by their post-pass's first call, which sends arm B's payload and system text and more "
        f"(largest {bound.by_post_pass_largest:,.0f}); {bound.by_real} with no post-pass call, "
        f"bounded by real prompt tokens / the smallest measured ratio {every[0]:.4f} (largest "
        f"{bound.by_real_largest:,.0f}); {bound.sent_none} failed before any call"
    )
    post = [estimated_tokens(c, tools) for c in post_pass]
    lines.append(
        f"over the ceiling: arm B post-pass calls {sum(1 for v in post if v > limit)} of "
        f"{len(post)} (largest estimate {max(post, default=0.0):,.0f})"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the context ratio reading."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("runs", nargs=2, metavar="RUN_ID", help="the two noise-floor runs")
    parser.add_argument("--armb", default=ARMB_RUN, help="the dev-400 arm B run (default S3's)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if args.out is not None:
        refuse_unclean_results(PROG, Path(args.out))
    text = report(args.runs, args.armb)
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
