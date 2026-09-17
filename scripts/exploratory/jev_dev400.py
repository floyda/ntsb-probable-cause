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

import json
from collections.abc import Callable, Sequence
from collections.abc import Set as AbstractSet
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from ntsb_probable_cause.errors import ModelError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import ChoiceAnswer, Exchange, SystemOneReply
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import (
    CaseScores,
    calibration,
    primary_occurrence,
    score_case,
    wilson,
)
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
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
            new = list(pool.map(attempt, chunk))
            with replies.open("a") as handle:
                handle.writelines(json.dumps(row) + "\n" for row in new)
            spent += sum(float(str(row["cost_usd"])) for row in new)
    return "complete"
