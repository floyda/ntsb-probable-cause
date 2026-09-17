"""Jev on dev-400: phase and event as two Choices per case (decision 0036).

Specification: docs/specs/2026-09-17-typesafe-jev-dev400-design.md. Exploratory, so outside
the strict tooling, but every payload is built by ``runner.case_payload`` and so passes
through ``split_record`` and the leakage guard (0013, 0016).

Usage (from the worktree root; data lives in the main checkout):
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
    TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)" \\
        uv run python -m scripts.exploratory.jev_dev400 run [--resume FOLDER]
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
        uv run python -m scripts.exploratory.jev_dev400 report FOLDER [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import cast

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import (
    DEFAULT_MODEL,
    ChoiceAnswer,
    Exchange,
    SystemOneReply,
    TypeSafeClient,
    parse_reply,
)
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import ledger, samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import (
    CaseScores,
    calibration,
    paired_difference,
    primary_occurrence,
    score_case,
    wilson,
)
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.scoring.report import fmt_n, proportion
from ntsb_probable_cause.scoring.runner import RunSpec, case_payload
from ntsb_probable_cause.settings import Settings
from scripts.typesafe_probe import choice_questions

QUESTION_NAMES = ("phase", "event")
# docs/results/s1-baseline.txt: the honest baseline's top-1 on held-out, the bar S1 set.
BASELINE_TOP1 = 0.177
# Spec §5: the calibration thresholds, fixed before the run.
_CALIBRATED_ECE = 0.05
_NOT_CALIBRATED_ECE = 0.10
_MAX_BIN_GAP = 0.10
_MIN_BIN_COUNT = 20

# Spec §2: the hard stop, four requests at a time, and a per-request estimate above the
# probe's 4,344 input tokens for its phase-event-modifier request.
CAP_USD = 0.50
CONCURRENCY = 4
TOKENS_PER_REQUEST_ESTIMATE = 5_000

SAMPLE = "dev-400"
RUN_SUFFIX = "dev-400-jev"
# Spec §4: the saved S1 runs the Jev row is compared with, case by case.
LLM_RUNS = {
    "Luna": "20260916T032106-179520f-dev-400-ceiling",
    "Gemini": "20260917T060746-c366a04-dev-400-ceiling",
}
EXAMPLE_SEED = 20260917
USD_PER_TOKEN = sources.JEV.input_usd_per_mtok / 1_000_000


def questions(tables: CodeTables) -> dict[str, dict[str, object]]:
    """Phase and event, worded exactly as the probe worded them."""
    every = choice_questions(tables)
    return {name: every[name] for name in QUESTION_NAMES}


def ranked_pairs(
    phase: ChoiceAnswer, event: ChoiceAnswer, k: int = 3
) -> list[tuple[str, str, float]]:
    """(phase, event, joint probability), highest first, ties broken by code."""
    pairs = [
        (p, e, pp * ep)
        for p, pp in phase.probabilities.items()
        for e, ep in event.probabilities.items()
    ]
    pairs.sort(key=lambda t: (-t[2], t[0], t[1]))
    return pairs[:k]


def jev_hypothesis(reply: SystemOneReply) -> Hypothesis:
    """Jev's answer in S1's shape, so ``score_case`` scores it exactly as it scored Luna."""
    top = ranked_pairs(reply.choice("phase"), reply.choice("event"))
    return Hypothesis(
        evidence_narrative="",
        occurrence=tuple(
            OccurrenceGuess(phase=p, event=e, probability=min(1.0, prob)) for p, e, prob in top
        ),
        findings=(),
        probable_cause="",
        lay_explanation="",
        confidence=min(1.0, top[0][2]),
        abstain=False,
        evidence_used=(),
    )


@dataclass(frozen=True)
class JevCase:
    """One scored case and the numbers the calibration tables need."""

    case_id: str
    fatal: bool
    scores: CaseScores
    event_confidence: float
    event_top_probability: float
    top1_probability: float
    true_occurrence: str | None
    true_event_probability: float | None
    top_events: tuple[tuple[str, float], ...]


def score_jev_case(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
    case_id: str,
    fatal: bool,
    reply: SystemOneReply,
    verdict: Verdict,
    tables: CodeTables,
    seen_pairs: AbstractSet[str],
) -> JevCase:
    """Score one reply with S1's ``score_case`` and keep what calibration needs."""
    hypothesis = jev_hypothesis(reply)
    scores = score_case(hypothesis, verdict, tables, seen_pairs=seen_pairs)
    event = reply.choice("event")
    truth = primary_occurrence(verdict)
    ranked = sorted(event.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
    return JevCase(
        case_id=case_id,
        fatal=fatal,
        scores=scores,
        event_confidence=event.confidence,
        event_top_probability=event.probabilities[hypothesis.occurrence[0].event],
        top1_probability=hypothesis.occurrence[0].probability,
        true_occurrence=truth,
        true_event_probability=event.probabilities.get(truth[3:], 0.0) if truth else None,
        top_events=tuple(ranked[:5]),
    )


@dataclass(frozen=True)
class FirstGuess:
    """An LLM's first occurrence guess: its stated probability and whether it is right."""

    probability: float
    right: bool
    top1: bool


def llm_first_guesses(cases_file: Path) -> dict[str, FirstGuess]:
    """Per case, from a saved S1 run, whether or not the model abstained (spec §4)."""
    out: dict[str, FirstGuess] = {}
    for result in read_jsonl(cases_file, CaseResult):
        if result.scores is None or not result.steps:
            continue
        first = result.steps[-1].hypothesis.occurrence[0]
        truth = result.verdict_occurrence[0] if result.verdict_occurrence else None
        out[result.case_id] = FirstGuess(
            probability=first.probability,
            right=f"{first.phase}{first.event}" == truth,
            top1=result.scores.occurrence_top1,
        )
    return out


def calibration_reading(confidences: Sequence[float], correct: Sequence[bool]) -> str:
    """Spec §5: calibrated, not calibrated, or inconclusive."""
    bins, ece = calibration(confidences, correct)
    worst = max(
        (abs(b.accuracy - b.mean_confidence) for b in bins if b.count >= _MIN_BIN_COUNT),
        default=0.0,
    )
    if ece > _NOT_CALIBRATED_ECE:
        return "not calibrated"
    if ece <= _CALIBRATED_ECE and worst <= _MAX_BIN_GAP:
        return "calibrated"
    return "inconclusive"


def accuracy_reading(top1: Sequence[bool]) -> str:
    """Spec §5: is the lower bound of top-1's 95% interval above the baseline?"""
    low, _ = wilson(sum(top1), len(top1))
    return "above the baseline" if low > BASELINE_TOP1 else "not above the baseline"


def calibration_block(title: str, confidences: Sequence[float], correct: Sequence[bool]) -> str:
    """One reliability table with its expected calibration error."""
    bins, ece = calibration(confidences, correct)
    lines = [
        f"{title}: n={len(confidences)}, expected calibration error {ece:.3f}",
        "  bin        n   mean stated   share right     gap",
    ]
    lines.extend(
        f"  {b.low:.1f}-{b.high:.1f}  {b.count:4d}   {b.mean_confidence:11.3f}   "
        f"{b.accuracy:11.3f}   {b.accuracy - b.mean_confidence:+.3f}"
        for b in bins
        if b.count
    )
    return "\n".join(lines)


def read_rows(replies: Path) -> list[dict[str, object]]:
    """Every row written so far, oldest first; none if the file does not exist yet."""
    if not replies.exists():
        return []
    return [json.loads(line) for line in replies.read_text().splitlines() if line]


def _attempt(
    case: tuple[str, Payload], ask: Callable[[Payload], Exchange], usd_per_token: float
) -> dict[str, object]:
    case_id, payload = case
    try:
        exchange = ask(payload)
    except ModelError as error:
        return {
            "case_id": case_id, "ok": False, "error": str(error), "attempts": None,
            "retried_statuses": [], "seconds": None, "cost_usd": 0.0, "reply": None,
        }
    return {
        "case_id": case_id,
        "ok": True,
        "error": None,
        "attempts": exchange.attempts,
        "retried_statuses": list(exchange.retried_statuses),
        "seconds": round(exchange.seconds, 3),
        "cost_usd": exchange.reply.usage.input_tokens * usd_per_token,
        "reply": exchange.reply.model_dump(mode="json"),
    }


def ask_all(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
    replies: Path,
    cases: Sequence[tuple[str, Payload]],
    ask: Callable[[Payload], Exchange],
    *,
    cap_usd: float,
    usd_per_token: float,
    concurrency: int = CONCURRENCY,
) -> str:
    """Ask every case without an answered row, ``concurrency`` at a time; stop before the cap."""
    rows = read_rows(replies)
    answered = {row["case_id"] for row in rows if row["ok"]}
    spent = sum(float(str(row["cost_usd"])) for row in rows)
    pending = [case for case in cases if case[0] not in answered]
    estimate = TOKENS_PER_REQUEST_ESTIMATE * usd_per_token
    replies.parent.mkdir(parents=True, exist_ok=True)
    attempt = partial(_attempt, ask=ask, usd_per_token=usd_per_token)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for start in range(0, len(pending), concurrency):
            chunk = pending[start : start + concurrency]
            if spent + estimate * len(chunk) > cap_usd:
                return "cap"
            futures = [pool.submit(attempt, case) for case in chunk]
            new: list[dict[str, object]] = []
            first_error: BaseException | None = None
            for future in futures:
                try:
                    new.append(future.result())
                except Exception as error:  # noqa: BLE001 -- re-raised below, once every
                    # already-completed sibling in the chunk has been collected and paid for.
                    if first_error is None:
                        first_error = error
            if new:
                with replies.open("a") as handle:
                    handle.writelines(json.dumps(row) + "\n" for row in new)
                spent += sum(float(str(row["cost_usd"])) for row in new)
            if first_error is not None:
                raise first_error
    return "complete"


def _latest_ok(rows: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    return {str(row["case_id"]): row for row in rows if row["ok"]}


def _pct(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _example_count(n: int, wanted: int = 5) -> int:
    """How many examples to sample: never more than there are cases (fix round 1)."""
    return min(wanted, n)


def build_report(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
    folder: Path,
    raws: Sequence[Mapping[str, object]],
    ids: Sequence[str],
    tables: CodeTables,
    seen: AbstractSet[str],
    runs_dir: Path,
) -> str:
    """Every table of spec §4 and both readings of spec §5, from saved files only."""
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        raise FileNotFoundError(f"{folder}: no meta.json; is this a run folder?")
    rows = read_rows(folder / "replies.jsonl")
    ok = _latest_ok(rows)
    meta = json.loads(meta_file.read_text())
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases: list[JevCase] = []
    for case_id, raw in zip(ids, raws, strict=True):
        if case_id not in ok:
            continue
        _, _, verdict, _ = case_payload(raw, spec, tables)
        reply = parse_reply(cast("Mapping[str, object]", ok[case_id]["reply"]))
        fatal = raw.get("highestInjuryLevel") == "Fatal"
        cases.append(score_jev_case(case_id, fatal, reply, verdict, tables, seen))
    replies = [parse_reply(cast("Mapping[str, object]", row["reply"])) for row in ok.values()]
    seconds = [float(str(row["seconds"])) for row in ok.values()]
    retried = Counter(s for row in rows for s in cast("list[str]", row["retried_statuses"]))
    input_tokens = sum(r.usage.input_tokens for r in replies)
    out: list[str] = []
    add = out.append

    add(f"run {folder.name}")
    add(
        f"sample={SAMPLE} requested model={meta['model']} "
        f"commit={meta['commit']} dirty={meta['dirty']}"
    )
    add(f"model versions in replies: {dict(Counter(r.model for r in replies))}")
    add(f"cases answered {len(ok)} of {len(ids)}; failed rows {sum(1 for r in rows if not r['ok'])}")
    add(f"input tokens {input_tokens}; output tokens {sum(r.usage.output_tokens for r in replies)}")
    add(
        f"cost at the published, self-reported price: ${input_tokens * USD_PER_TOKEN:.4f} "
        f"(${input_tokens * USD_PER_TOKEN / max(1, len(ok)):.6f} per case; preview, comparison only)"
    )
    # Fix round 1: a capped-or-all-failed run has no seconds to reduce; print the header
    # line anyway rather than let statistics.median/max crash on an empty sequence.
    if seconds:
        add(
            f"latency seconds: median {statistics.median(seconds):.2f}, 90th percentile "
            f"{_pct(seconds, 0.9):.2f}, max {max(seconds):.2f}; requests needing a retry "
            f"{sum(1 for r in ok.values() if int(str(r['attempts'])) > 1)}; "
            f"retried statuses {dict(retried)}"
        )
    else:
        add("latency seconds: none (no answered cases)")

    if not cases:
        add("\nno answered cases were scored; accuracy, calibration and examples skipped")
        return "\n".join(out) + "\n"

    add("\nACCURACY (composed top-1 and top-3; S1's score_case)")
    add("| slice | n | top-1 | top-3 | event | pair unseen |")
    add("|---|---|---|---|---|---|")
    for name, members in (
        ("all", cases),
        ("fatal", [c for c in cases if c.fatal]),
        ("non-fatal", [c for c in cases if not c.fatal]),
    ):
        add(
            f"| {name} | {len(members)} "
            f"| {fmt_n(proportion([c.scores.occurrence_top1 for c in members]))} "
            f"| {fmt_n(proportion([c.scores.occurrence_top3 for c in members]))} "
            f"| {fmt_n(proportion([c.scores.event_match for c in members]))} "
            f"| {fmt_n(proportion([c.scores.pair_unseen for c in members]))} |"
        )
    top1 = [c.scores.occurrence_top1 for c in cases]
    add(f"reading (spec §5, bar {BASELINE_TOP1:.1%}): {accuracy_reading(top1)}")

    event_right = [c.scores.event_match for c in cases]
    add("\nCALIBRATION")
    add(calibration_block("(a) Jev event confidence vs event right", [c.event_confidence for c in cases], event_right))
    add(f"reading on (a) (spec §5): {calibration_reading([c.event_confidence for c in cases], event_right)}")
    add(calibration_block("(b) Jev top event probability vs event right", [c.event_top_probability for c in cases], event_right))

    by_id = {c.case_id: c for c in cases}
    guesses = {name: llm_first_guesses(runs_dir / run / "cases.jsonl") for name, run in LLM_RUNS.items()}
    shared = sorted(set(by_id).intersection(*(set(g) for g in guesses.values())))
    add(f"\n(c) first-guess probability vs first guess right, on the {len(shared)} cases all three scored")
    add(calibration_block("(c) Jev top-1 product", [by_id[i].top1_probability for i in shared], [by_id[i].scores.occurrence_top1 for i in shared]))
    for name, g in guesses.items():
        add(calibration_block(f"(c) {name} first guess", [g[i].probability for i in shared], [g[i].right for i in shared]))

    add("\nPAIRED TOP-1 DIFFERENCE (Jev minus model, same cases, bootstrap 95%)")
    for name, g in guesses.items():
        mean, low, high = paired_difference(
            [by_id[i].scores.occurrence_top1 for i in shared], [g[i].top1 for i in shared]
        )
        add(f"- Jev - {name}: {mean:+.1%} [{low:+.1%}, {high:+.1%}] on n={len(shared)}")

    true_p = [c.true_event_probability for c in cases if c.true_event_probability is not None]
    add("\nPROBABILITY ON THE TRUE EVENT")
    if true_p:
        add(
            f"median {statistics.median(true_p):.3f}; exactly 0 on "
            f"{sum(1 for p in true_p if p == 0.0)} of {len(true_p)} "
            f"({sum(1 for p in true_p if p == 0.0) / len(true_p):.1%})"
        )
    else:
        add("none (no verdict occurrence code scored against)")

    add(f"\nEXAMPLES (seed {EXAMPLE_SEED}; codes and labels only)")
    for c in random.Random(EXAMPLE_SEED).sample(cases, _example_count(len(cases))):
        truth = c.true_occurrence or "none"
        label = tables.events.get(truth[3:], "?") if c.true_occurrence else "-"
        add(f"{c.case_id}: true {truth} ({label}); Jev event confidence {c.event_confidence:.2f}")
        for code, p in c.top_events:
            add(f"    {code} {tables.events[code]:<45} {p:.2f}")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str]) -> int:
    """``run`` asks Jev; ``report`` scores what was saved."""
    parser = argparse.ArgumentParser(prog="jev_dev400")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--resume", help="an existing run folder name under the runs directory")
    run_cmd.add_argument("--limit", type=int, help="first N cases only (smoke run)")
    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("folder")
    report_cmd.add_argument("--out")
    args = parser.parse_args(argv)

    settings = Settings()
    tables = load_tables()
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids(SAMPLE)
    if args.command == "run" and args.limit is not None:
        ids = ids[: args.limit]
    raws = samples.load_cases(processed, ids)

    if args.command == "report":
        text = build_report(
            settings.runs_dir / args.folder, raws, ids, tables,
            samples.seen_pairs(processed), settings.runs_dir,
        )
        print(text, end="")
        if args.out:
            Path(args.out).write_text(text)
        return 0

    sha, dirty = ledger.commit_state()
    name = args.resume or f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{sha}-{RUN_SUFFIX}"
    folder = settings.runs_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        meta_file.write_text(json.dumps({
            "sample": SAMPLE, "model": DEFAULT_MODEL, "questions": list(QUESTION_NAMES),
            "commit": sha, "dirty": dirty, "started": datetime.now(UTC).isoformat(),
            "cap_usd": CAP_USD, "limit": args.limit,
        }, indent=1))
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases = []
    for case_id, raw in zip(ids, raws, strict=True):
        payload, _, _, evidence = case_payload(raw, spec, tables)
        if evidence.case_id != case_id:
            raise ValueError(f"sample order broken: {case_id} != {evidence.case_id}")
        cases.append((case_id, payload))
    asked = questions(tables)
    with TypeSafeClient(settings.require_typesafe_key(), base_url=settings.typesafe_base_url) as client:
        reason = ask_all(
            folder / "replies.jsonl", cases, lambda p: client.ask(p, asked),
            cap_usd=CAP_USD, usd_per_token=USD_PER_TOKEN,
        )
    rows = read_rows(folder / "replies.jsonl")
    print(
        f"{folder.name}: {reason}; answered {len(_latest_ok(rows))} of {len(ids)}; "
        f"spent ${sum(float(str(r['cost_usd'])) for r in rows):.4f} at the published price"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
