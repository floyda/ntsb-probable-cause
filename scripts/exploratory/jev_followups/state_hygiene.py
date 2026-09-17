"""Experiment 3: does excluding aircraft/pilot detail from the state change the event answer?

Two arms over the same 401 dev-400 cases, one call each per case, asking only the event
question (``scripts.exploratory.jev_dev400.questions``'s wording, restricted to "event"):
``full`` is today's payload; ``lean`` excludes registration, aircraft make/model, engine type
and the three pilot fields via ``RunSpec.exclusions`` (never a hand-edited payload), leaving
phase of flight, injury level and the weather fields -- what plausibly bears on what
happened. This tests the vendor's "large irrelevant state" / "context rot" failure mode:
unrelated detail acting as a distractor.

Every payload is built by ``runner.case_payload`` (``split_record`` and the leakage guard,
0013/0016); the only difference between arms is ``RunSpec.exclusions``.

Usage (from the worktree root; data lives in the main checkout):
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
    TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)" \\
        uv run python -m scripts.exploratory.jev_followups.state_hygiene run [--resume FOLDER]
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
        uv run python -m scripts.exploratory.jev_followups.state_hygiene report FOLDER [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import (
    ChoiceAnswer,
    Exchange,
    SystemOneReply,
    TypeSafeClient,
    parse_reply,
)
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import ledger, samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.metrics import paired_difference
from ntsb_probable_cause.scoring.report import fmt_n, proportion
from ntsb_probable_cause.scoring.runner import RunSpec, case_payload
from ntsb_probable_cause.settings import Settings
from scripts.exploratory.jev_dev400 import (
    CAP_USD,
    SAMPLE,
    USD_PER_TOKEN,
    ask_all,
    calibration_block,
    event_question,
    read_rows,
)

# The 0009-per-experiment run name suffix; a fresh run folder is
# ``<timestamp>-<sha>-dev-400-state-hygiene``.
RUN_SUFFIX = "dev-400-state-hygiene"

# The exact seven roles excluded in the "lean" arm (spec: via RunSpec.exclusions, never a
# hand-edited payload). What remains: phase of flight, injury level, the weather fields, and
# the preliminary narrative.
LEAN_EXCLUSIONS: frozenset[EvidenceRole] = frozenset(
    {
        EvidenceRole.REGISTRATION,
        EvidenceRole.AIRCRAFT_MAKE,
        EvidenceRole.AIRCRAFT_MODEL,
        EvidenceRole.ENGINE_TYPE,
        EvidenceRole.PILOT_CERTIFICATES,
        EvidenceRole.PILOT_TOTAL_HOURS,
        EvidenceRole.PILOT_HOURS_IN_TYPE,
    }
)
ARMS: tuple[str, ...] = ("full", "lean")
# Fixed in advance (spec of this follow-up).
HYGIENE_MATTERS_READING = "state hygiene matters"
NOT_CONTEXT_ROT_READING = "context rot is not what is holding it back"
_HYGIENE_THRESHOLD = 0.03


def arm_spec(arm: str) -> RunSpec:
    """``full`` excludes nothing; ``lean`` excludes ``LEAN_EXCLUSIONS`` (spec: RunSpec only)."""
    exclusions = LEAN_EXCLUSIONS if arm == "lean" else frozenset()
    return RunSpec(sample=SAMPLE, arm="ceiling", exclusions=exclusions)


@dataclass(frozen=True)
class EventCase:
    """One arm's answer to the event question alone, scored against the verdict."""

    case_id: str
    right: bool
    probability: float
    confidence: float
    input_tokens: int


def score_event_case(case_id: str, reply: SystemOneReply, verdict: Verdict) -> EventCase | None:
    """Score one event-only reply; ``None`` if the verdict has no primary occurrence to score."""
    truth = verdict.occurrence_codes[0] if verdict.occurrence_codes else None
    if truth is None:
        return None
    event: ChoiceAnswer = reply.choice("event")
    return EventCase(
        case_id=case_id,
        right=event.choice == truth[3:],
        probability=event.probabilities[event.choice],
        confidence=event.confidence,
        input_tokens=reply.usage.input_tokens,
    )


def read_arm_cases(
    folder: Path,
    arm: str,
    ids: Sequence[str],
    raws: Sequence[Mapping[str, object]],
    tables: CodeTables,
) -> list[EventCase]:
    """Every answered case of one arm, scored against its own (arm-specific) verdict access.

    The verdict is never affected by ``RunSpec.exclusions`` -- exclusions only ever remove
    evidence roles from the payload -- so both arms are scored against the same truth; this
    reads it via ``case_payload`` purely for consistency with how every other run in this
    project resolves a verdict.
    """
    rows = read_rows(folder / arm / "replies.jsonl")
    ok = {row["case_id"]: row for row in rows if row["ok"]}
    spec = arm_spec(arm)
    out: list[EventCase] = []
    for case_id, raw in zip(ids, raws, strict=True):
        if case_id not in ok:
            continue
        _, _, verdict, _ = case_payload(raw, spec, tables)
        reply = parse_reply(cast("Mapping[str, object]", ok[case_id]["reply"]))
        scored = score_event_case(case_id, reply, verdict)
        if scored is not None:
            out.append(scored)
    return out


def build_report(
    folder: Path,
    ids: Sequence[str],
    raws: Sequence[Mapping[str, object]],
    tables: CodeTables,
) -> str:
    """Accuracy, paired difference, mean tokens and calibration, for both arms."""
    by_arm = {arm: read_arm_cases(folder, arm, ids, raws, tables) for arm in ARMS}
    out: list[str] = [f"experiment 3: state hygiene -- run {folder.name}"]
    for arm in ARMS:
        cases = by_arm[arm]
        out.append(f"\n{arm}: n={len(cases)} answered")
        acc = proportion([c.right for c in cases])
        out.append(f"  event accuracy: {fmt_n(acc)}")
        if cases:
            mean_tokens = statistics.mean(c.input_tokens for c in cases)
            out.append(f"  mean input tokens: {mean_tokens:.1f}")
        out.append(
            calibration_block(
                f"  ({arm}) event probability vs event right",
                [c.probability for c in cases],
                [c.right for c in cases],
            )
        )

    shared = sorted(set(c.case_id for c in by_arm["full"]) & set(c.case_id for c in by_arm["lean"]))
    by_id = {arm: {c.case_id: c for c in cases} for arm, cases in by_arm.items()}
    lean_right = [by_id["lean"][i].right for i in shared]
    full_right = [by_id["full"][i].right for i in shared]
    mean, low, high = paired_difference(lean_right, full_right)
    out.append(
        f"\npaired difference (lean - full), same {len(shared)} cases: "
        f"{mean:+.1%} [{low:+.1%}, {high:+.1%}]"
    )

    full_acc = proportion(full_right).value
    lean_acc = proportion(lean_right).value
    diff_pp = lean_acc - full_acc
    if diff_pp >= _HYGIENE_THRESHOLD:
        reading = HYGIENE_MATTERS_READING
    elif abs(diff_pp) < _HYGIENE_THRESHOLD:
        reading = NOT_CONTEXT_ROT_READING
    else:
        reading = (
            f"lean underperforms full by {abs(diff_pp):.1%} on the shared cases "
            "(neither fixed reading applies)"
        )
    out.append(f"\nreading (fixed in advance): {reading}")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str]) -> int:
    """``run`` asks both arms; ``report`` scores what was saved."""
    parser = argparse.ArgumentParser(prog="state_hygiene")
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
        text = build_report(settings.runs_dir / args.folder, ids, raws, tables)
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
            "arms": list(ARMS),
            "lean_exclusions": sorted(r.value for r in LEAN_EXCLUSIONS),
            "commit": sha,
            "dirty": dirty,
            "started": datetime.now(UTC).isoformat(),
            "cap_usd": CAP_USD,
            "limit": args.limit,
        }
        meta_file.write_text(json.dumps(meta, indent=1))

    q = event_question(tables)
    client_key = settings.require_typesafe_key()
    with TypeSafeClient(client_key, base_url=settings.typesafe_base_url) as client:
        for arm in ARMS:
            spec = arm_spec(arm)
            cases: list[tuple[str, Payload]] = []
            for case_id, raw in zip(ids, raws, strict=True):
                payload, _, _, evidence = case_payload(raw, spec, tables)
                if evidence.case_id != case_id:
                    raise ValueError(f"sample order broken: {case_id} != {evidence.case_id}")
                cases.append((case_id, payload))

            def ask(payload: Payload, *, _q: Mapping[str, Mapping[str, object]] = q) -> Exchange:
                return client.ask(payload, _q)

            reason = ask_all(
                folder / arm / "replies.jsonl",
                cases,
                cast("Callable[[Payload], Exchange]", ask),
                cap_usd=CAP_USD,
                usd_per_token=USD_PER_TOKEN,
            )
            rows = read_rows(folder / arm / "replies.jsonl")
            print(
                f"{folder.name}/{arm}: {reason}; answered "
                f"{sum(1 for r in rows if r['ok'])} of {len(ids)}; "
                f"spent ${sum(float(str(r['cost_usd'])) for r in rows):.4f} at the published price"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
