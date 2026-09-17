"""Experiment 5: hierarchical events, beam search, K=3, length-normalised geometric mean.

The vendor documents hierarchical classification (traverse level by level with one Choice per
level) and beam search with length-normalised geometric mean scoring
(``product(edge_probabilities) ** (1/decisions)``) to let later decisions repair earlier ones.
This tests both claims on the 93-label event question, whose flat form
(``scripts.exploratory.jev_dev400.event_question``) already has a saved unconditioned dev-400
run to compare against.

The 93 events group by their first digit into 8 families. The grouping and each family's
label/description are *derived*, not authored: ``group_events_by_family`` partitions the code
table alone, and ``family_description`` joins the family's first three member labels (by code
order) -- nobody on this project asserts these families mean anything beyond "shares a first
digit"; the description exists only so Jev's Choice question has something to read.

Per case: one Choice over the 8 families (call 1), then one Choice per top-K=3 family over
that family's own member events (calls 2-4). Each candidate scores as
``(family_probability * member_probability) ** 0.5`` -- the two-decision case of the vendor's
formula. The four calls are folded into one synthetic ``SystemOneReply`` (answers keyed
``family`` and ``member_<digit>``, usage summed) so ``ask_all``'s existing cost/cap accounting,
built for one reply per case, prices all four calls correctly without being modified.

Usage (from the worktree root; data lives in the main checkout):
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
    TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)" \\
        uv run python -m scripts.exploratory.jev_followups.hierarchical_events run [--resume FOLDER]
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
        uv run python -m scripts.exploratory.jev_followups.hierarchical_events report FOLDER [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import (
    ChoiceAnswer,
    Exchange,
    SystemOneReply,
    SystemOneUsage,
    TypeSafeClient,
    parse_reply,
)
from ntsb_probable_cause.scoring import ledger, samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.metrics import primary_occurrence
from ntsb_probable_cause.scoring.report import fmt_n, proportion
from ntsb_probable_cause.scoring.runner import RunSpec, case_payload
from ntsb_probable_cause.settings import Settings
from scripts.exploratory.jev_dev400 import CAP_USD, SAMPLE, USD_PER_TOKEN, ask_all, read_rows

RUN_SUFFIX = "dev-400-hierarchical-events"
BEAM_K = 3
FAMILY_DESCRIPTION_MEMBERS = 3  # spec: "for example, the first three member labels joined"
CALLS_PER_CASE = 1 + BEAM_K
MEMBER_KEY_PREFIX = "member_"

FAMILY_INSTRUCTIONS = (
    "Which family of events best matches the defining occurrence of this accident, in the "
    "NTSB's sense of the occurrence that the probable cause explains? Each family groups the "
    "NTSB's three-digit event codes that share the same first digit; the family's description "
    "is derived mechanically from its member event labels, not an authored claim about what "
    "the family means."
)
MEMBER_INSTRUCTIONS = (
    "Within the family already identified as most likely, which event defines this accident? "
    "Each label is the NTSB's three-digit event suffix."
)
HIERARCHY_HELPS_READING = "the hierarchy helps"
FLAT_AS_GOOD_READING = "the flat 93-label question is as good as the vendor's hierarchical pattern here"
_HELPS_THRESHOLD = 0.03


def group_events_by_family(tables: CodeTables) -> dict[str, tuple[str, ...]]:
    """Partition the 93 event codes by their first digit, sorted within each family.

    A partition of the whole table: every event code belongs to exactly one family, keyed by
    its own first character. No claim about what shares a first digit *means* is made or
    needed here.
    """
    groups: dict[str, list[str]] = {}
    for code in tables.events:
        groups.setdefault(code[0], []).append(code)
    return {digit: tuple(sorted(codes)) for digit, codes in sorted(groups.items())}


def family_label(digit: str) -> str:
    """A plain, derived name -- never a hand-written domain claim."""
    return f"Family {digit}"


def family_description(digit: str, members: Sequence[str], tables: CodeTables) -> str:
    """Derived, not authored: the first three member labels (by code order), joined.

    This is mechanical summarisation of the code table, not a domain judgement about what the
    family represents -- the docstring at module level says the same.
    """
    chosen = members[:FAMILY_DESCRIPTION_MEMBERS]
    return "; ".join(tables.events[code] for code in chosen)


def family_question(tables: CodeTables) -> dict[str, dict[str, object]]:
    """Call 1: one Choice over the 8 families."""
    families = group_events_by_family(tables)
    criteria = {
        digit: f"{family_label(digit)}: {family_description(digit, members, tables)}"
        for digit, members in families.items()
    }
    return {"family": {"type": "choice", "instructions": FAMILY_INSTRUCTIONS, "criteria": criteria}}


def member_question(digit: str, tables: CodeTables) -> dict[str, dict[str, object]]:
    """One of calls 2-4: a Choice over one family's own member events only."""
    members = group_events_by_family(tables)[digit]
    criteria = {code: tables.events[code] for code in members}
    return {"member": {"type": "choice", "instructions": MEMBER_INSTRUCTIONS, "criteria": criteria}}


@dataclass(frozen=True)
class BeamCandidate:
    """One (family, event) candidate and its length-normalised geometric-mean score."""

    family: str
    event: str
    family_probability: float
    member_probability: float
    score: float


def beam_candidates(reply: SystemOneReply) -> tuple[BeamCandidate, ...]:
    """Every ``member_<digit>`` answer in the reply, scored and ranked best first.

    Pure and reply-shape-only, so it is exercised directly in tests with a hand-built reply
    (no case, no verdict, no I/O).
    """
    family_answer = reply.choice("family")
    candidates = []
    for key, answer in reply.answers.items():
        if not key.startswith(MEMBER_KEY_PREFIX) or not isinstance(answer, ChoiceAnswer):
            continue
        digit = key.removeprefix(MEMBER_KEY_PREFIX)
        event = answer.choice
        member_probability = answer.probabilities[event]
        family_probability = family_answer.probabilities[digit]
        score = (family_probability * member_probability) ** 0.5
        candidates.append(
            BeamCandidate(
                family=digit,
                event=event,
                family_probability=family_probability,
                member_probability=member_probability,
                score=score,
            )
        )
    candidates.sort(key=lambda c: (-c.score, c.event))
    return tuple(candidates)


def choose_event(reply: SystemOneReply) -> BeamCandidate:
    """The beam's winner: the highest-scoring candidate, ties broken by event code."""
    candidates = beam_candidates(reply)
    if not candidates:
        raise ValueError("reply carries no member_<digit> answers to choose from")
    return candidates[0]


def top_family(reply: SystemOneReply) -> str:
    """The family call-1 alone would have chosen (highest family probability)."""
    family_answer = reply.choice("family")
    return sorted(family_answer.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def combine_replies(
    family_exchange: Exchange, member_exchanges: Sequence[tuple[str, Exchange]]
) -> Exchange:
    """Fold one family call and up to K member calls into one synthetic reply.

    So ``ask_all``'s existing per-case cost/cap accounting -- built for one
    ``exchange.reply.usage`` per case -- prices all ``CALLS_PER_CASE`` calls correctly without
    itself needing to know that this experiment makes more than one call per case.
    """
    answers: dict[str, object] = {"family": family_exchange.reply.choice("family")}
    for digit, exchange in member_exchanges:
        answers[f"{MEMBER_KEY_PREFIX}{digit}"] = exchange.reply.choice("member")
    input_tokens = family_exchange.reply.usage.input_tokens + sum(
        e.reply.usage.input_tokens for _, e in member_exchanges
    )
    output_tokens = family_exchange.reply.usage.output_tokens + sum(
        e.reply.usage.output_tokens for _, e in member_exchanges
    )
    combined = SystemOneReply(
        model=family_exchange.reply.model,
        usage=SystemOneUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        answers=cast("dict[str, object]", answers),
    )
    attempts = family_exchange.attempts + sum(e.attempts for _, e in member_exchanges)
    retried = family_exchange.retried_statuses + tuple(
        s for _, e in member_exchanges for s in e.retried_statuses
    )
    seconds = family_exchange.seconds + sum(e.seconds for _, e in member_exchanges)
    return Exchange(reply=combined, attempts=attempts, retried_statuses=tuple(retried), seconds=seconds)


@dataclass(frozen=True)
class HierCase:
    """One scored case: the beam's winning event, whether it is right, and whether call 1
    alone would have picked a different family (the vendor's claimed "error repair")."""

    case_id: str
    right: bool
    repaired: bool
    winner: BeamCandidate
    input_tokens: int


def score_hier_case(case_id: str, reply: SystemOneReply, truth_event: str | None) -> HierCase | None:
    """Score one combined reply; ``None`` if the verdict has no primary occurrence to score."""
    if truth_event is None:
        return None
    winner = choose_event(reply)
    return HierCase(
        case_id=case_id,
        right=winner.event == truth_event,
        repaired=winner.family != top_family(reply),
        winner=winner,
        input_tokens=reply.usage.input_tokens,
    )


def flat_event_accuracy(
    flat_folder: Path,
    ids: Sequence[str],
    raws: Sequence[Mapping[str, object]],
    tables: CodeTables,
) -> tuple[float, int]:
    """The saved unconditioned run's event-alone accuracy, recomputed, never hardcoded.

    Reads the flat run's own ``replies.jsonl`` (the shape ``jev_dev400.py run`` writes: one
    row per case, the reply under the ``reply`` key) rather than ``cases.jsonl``, which only
    an S1 evaluation run produces and the flat Jev run never wrote. This is the same
    event-alone figure ``docs/results/typesafe-jev-dev400.md`` quotes (17.7%), recomputed here
    as a self-check rather than trusted from memory (CLAUDE.md rule 3: every number comes from
    a script).
    """
    rows = read_rows(flat_folder / "replies.jsonl")
    ok = {row["case_id"]: row for row in rows if row["ok"]}
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    right = 0
    total = 0
    for case_id, raw in zip(ids, raws, strict=True):
        if case_id not in ok:
            continue
        _, _, verdict, _ = case_payload(raw, spec, tables)
        truth = primary_occurrence(verdict)
        if truth is None:
            continue
        reply = parse_reply(cast("Mapping[str, object]", ok[case_id]["reply"]))
        total += 1
        if reply.choice("event").choice == truth[3:]:
            right += 1
    return (right / total if total else 0.0), total


def hierarchy_reading(hier_accuracy: float, flat_accuracy: float) -> str:
    """Fixed in advance: helps by >= 3pp, as good within 3pp either way, else name the gap.

    The third branch is not one of the two fixed readings -- neither "helps" nor "as good"
    describes a result outside the +/-3pp band on the losing side -- so it states the measured
    gap plainly instead of forcing it into a reading that would misdescribe it (the same
    pattern ``state_hygiene.build_report`` uses for its own third case).
    """
    diff = hier_accuracy - flat_accuracy
    if diff >= _HELPS_THRESHOLD:
        return HIERARCHY_HELPS_READING
    if abs(diff) < _HELPS_THRESHOLD:
        return FLAT_AS_GOOD_READING
    return (
        f"the hierarchical pattern is far worse here -- event accuracy {hier_accuracy:.1%} "
        f"against the flat question's {flat_accuracy:.1%}, a gap of {diff:+.1%} "
        "(neither fixed reading applies)"
    )


def build_report(
    folder: Path,
    ids: Sequence[str],
    raws: Sequence[Mapping[str, object]],
    tables: CodeTables,
    flat_run: Path,
) -> str:
    """Event accuracy, repair rate, cost -- beside the flat run's recomputed event accuracy.

    ``flat_run`` is the flat run's own folder (holding ``replies.jsonl``), not a file inside
    it: see ``flat_event_accuracy``.
    """
    rows = read_rows(folder / "replies.jsonl")
    ok = {row["case_id"]: row for row in rows if row["ok"]}
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases: list[HierCase] = []
    for case_id, raw in zip(ids, raws, strict=True):
        if case_id not in ok:
            continue
        _, _, verdict, _ = case_payload(raw, spec, tables)
        truth = verdict.occurrence_codes[0][3:] if verdict.occurrence_codes else None
        reply = parse_reply(cast("Mapping[str, object]", ok[case_id]["reply"]))
        scored = score_hier_case(case_id, reply, truth)
        if scored is not None:
            cases.append(scored)

    flat_accuracy, flat_n = flat_event_accuracy(flat_run, ids, raws, tables)
    out = [
        f"experiment 5: hierarchical events, beam K={BEAM_K} -- run {folder.name}",
        f"n={len(cases)} answered and scored cases",
    ]
    acc = proportion([c.right for c in cases])
    out.append(f"event accuracy (hierarchical): {fmt_n(acc)}")
    out.append(
        f"event accuracy (flat, recomputed from {flat_run.name}/replies.jsonl): "
        f"{flat_accuracy:.1%} (n={flat_n})"
    )
    repaired = proportion([c.repaired for c in cases])
    out.append(f"beam winner from a family other than call 1's top family: {fmt_n(repaired)}")
    total_tokens = sum(c.input_tokens for c in cases)
    cost = total_tokens * USD_PER_TOKEN
    out.append(
        f"cost at the published price: ${cost:.4f} (${cost / max(1, len(cases)):.6f} per case, "
        f"{CALLS_PER_CASE} calls/case; preview, comparison only)"
    )
    out.append(f"\nreading (fixed in advance): {hierarchy_reading(acc.value, flat_accuracy)}")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str]) -> int:
    """``run`` asks Jev (4 calls/case); ``report`` scores what was saved."""
    parser = argparse.ArgumentParser(prog="hierarchical_events")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--resume", help="an existing run folder name under the runs directory")
    run_cmd.add_argument("--limit", type=int, help="first N cases only (smoke run)")
    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("folder")
    report_cmd.add_argument("--flat-run", required=True, help="the saved unconditioned dev-400 run")
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
            settings.runs_dir / args.folder,
            ids,
            raws,
            tables,
            settings.runs_dir / args.flat_run,
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
        meta = {
            "sample": SAMPLE,
            "beam_k": BEAM_K,
            "calls_per_case": CALLS_PER_CASE,
            "commit": sha,
            "dirty": dirty,
            "started": datetime.now(UTC).isoformat(),
            "cap_usd": CAP_USD,
            "limit": args.limit,
        }
        meta_file.write_text(json.dumps(meta, indent=1))

    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases: list[tuple[str, Payload]] = []
    for case_id, raw in zip(ids, raws, strict=True):
        payload, _, _, evidence = case_payload(raw, spec, tables)
        if evidence.case_id != case_id:
            raise ValueError(f"sample order broken: {case_id} != {evidence.case_id}")
        cases.append((case_id, payload))

    fam_q = family_question(tables)
    client_key = settings.require_typesafe_key()
    with TypeSafeClient(client_key, base_url=settings.typesafe_base_url) as client:

        def ask(payload: Payload) -> Exchange:
            """Call 1 (family), then one call per top-K family (calls 2-4), combined."""
            family_exchange = client.ask(payload, fam_q)
            family_answer = family_exchange.reply.choice("family")
            top = sorted(family_answer.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))[:BEAM_K]
            member_exchanges = [
                (digit, client.ask(payload, member_question(digit, tables))) for digit, _ in top
            ]
            return combine_replies(family_exchange, member_exchanges)

        reason = ask_all(
            folder / "replies.jsonl",
            cases,
            ask,
            cap_usd=CAP_USD,
            usd_per_token=USD_PER_TOKEN,
            tokens_per_request=5_000 * CALLS_PER_CASE,
        )
    rows = read_rows(folder / "replies.jsonl")
    print(
        f"{folder.name}: {reason}; answered {sum(1 for r in rows if r['ok'])} of {len(ids)}; "
        f"spent ${sum(float(str(r['cost_usd'])) for r in rows):.4f} at the published price"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
