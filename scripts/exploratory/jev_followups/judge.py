"""Experiment 2: is Jev usable as the judge of decision 0028? (decision 0060 point 5).

WARNING -- withheld text: ``build_state`` below renders the official NTSB probable cause,
which is *verdict* text withheld from every answering call (decisions 0013, 0016). Doing so
here is allowed only under the same narrow exception decision 0028 carved out for
``ntsb_probable_cause.scoring.judge.judge_text``: comparing an analyst's output with the
official record for grading, never for answering. This module must NEVER be imported by
answering code, and ``build_state``'s output must NEVER be sent as, or folded into, a
``Payload`` (``Payload.from_evidence`` already refuses withheld roles by construction --
this module does not try to route the withheld text through a ``Payload`` at all, precisely
because it cannot).

The 30 rows come from decision 0028's own hand-check sample (``judge.pick_disagreements``):
cases where the LLM judge (``JUDGE_MODEL``) called the analyst's probable cause "same_cause"
as the official one. Two inputs are joined on ``row``:
- the working sheet (outside git, read-only): case id and both prose causes plus the
  analyst's lay explanation, from the S1 run that produced the LLM judge's labels;
- ``docs/results/s1-judge-handcheck.csv`` (in git): Andy's own mark on each row.

Jev is asked, in one call per row, a Choice named ``cause`` over exactly
``JudgeLabels`` model's three ``cause`` labels, and a Score named ``agreement`` over three
ordered levels of the same rubric -- so both question shapes decision 0060 point 4 named are
exercised. Both questions' instructions are the ``cause:`` sentence of the judge's own
``SYSTEM_JUDGE`` rubric (decision 0028), extracted programmatically so the wording can never
drift from the LLM judge's own.

The 30 rows are a disagreement sample, not a random one (only cases the LLM judge and the
code-layer scorer disagreed on were ever hand-checked) -- ``report`` prints exactly what the
loaded rows' own ``judge_said``/``codes_said`` columns show, rather than asserting it.

Usage (from the worktree root; data lives in the main checkout):
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
    TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)" \\
        uv run python -m scripts.exploratory.jev_followups.judge run [--resume FOLDER]
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
        uv run python -m scripts.exploratory.jev_followups.judge report FOLDER [--out PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import ChoiceAnswer, Exchange, ScoreAnswer, TypeSafeClient, parse_reply
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.scoring import ledger
from ntsb_probable_cause.scoring.judge import SYSTEM_JUDGE, JudgeLabels
from ntsb_probable_cause.settings import Settings
from scripts.exploratory.jev_dev400 import CAP_USD, USD_PER_TOKEN, ask_all, read_rows

RUN_SUFFIX = "jev-followups-judge"
# The S1 run whose hand-check working sheet this experiment joins against (spec: fixed input).
HANDCHECK_RUN_FOLDER = "20260916T032106-179520f-dev-400-ceiling"
HANDCHECK_WORKING_FILE = "s1-judge-handcheck-working.csv"
HANDCHECK_MARKED_FILE = Path("docs/results/s1-judge-handcheck.csv")
REGISTRATION_MARKER = "row-{row}"
# One judge-sized call: SYSTEM_JUDGE alone is a few hundred tokens; two short prose causes
# and a lay explanation add a few hundred more. Rounded well above the probe's smallest call.
TOKENS_PER_REQUEST_ESTIMATE = 1_500

CAUSE_LABELS: tuple[str, ...] = get_args(JudgeLabels.model_fields["cause"].annotation)
# Ordered low (no agreement) to high (full agreement), per the spec's Score wording.
AGREEMENT_LEVELS: tuple[str, ...] = ("different cause", "related cause", "same cause")
USABLE_READING = "Jev is usable as a judge"
NOT_USABLE_READING = "Jev does not reproduce Andy's judgement on this sample"
# Spec's rule: >= 2/3 of judge-wrong rows called related/different; >= 80% of judge-right
# rows called same_cause.
WRONG_CAUGHT_THRESHOLD = 2 / 3
RIGHT_CONFIRMED_THRESHOLD = 0.8
# andy_mark values this experiment expects to see and how to read them (spec: "if andy_mark
# has values you do not expect, print the distribution and apply the rule to whatever value
# means the judge was wrong, naming which value you used"). Observed on
# docs/results/s1-judge-handcheck.csv: {"judge_right", "codes_right", "both_defensible"} --
# not the {"judge_right", "judge_wrong"} the spec's prose assumes. "codes_right" is read as
# the judge being wrong (the code layer's mismatch was the correct call); "both_defensible"
# is neither, and is reported on its own rather than folded into either group.
JUDGE_WRONG_MARK = "codes_right"
JUDGE_RIGHT_MARK = "judge_right"


def _extract_sentence(system_judge: str, label: str) -> str:
    """Pull the ``label:`` sentence out of ``SYSTEM_JUDGE`` (0028), joining wrapped lines.

    Programmatic extraction, not a hand-copied quote, so this module's questions can never
    drift from the LLM judge's own rubric wording.
    """
    labels = ("narrative", "cause", "lay")
    lines = system_judge.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{label}:"))
    collected = [lines[start].removeprefix(f"{label}:").strip()]
    for line in lines[start + 1 :]:
        if any(line.startswith(f"{other}:") for other in labels):
            break
        collected.append(line.strip())
    return " ".join(collected).strip()


CAUSE_INSTRUCTIONS = _extract_sentence(SYSTEM_JUDGE, "cause")


def judge_questions() -> dict[str, dict[str, object]]:
    """One Choice (``JudgeLabels.cause``'s three labels) and one Score, same rubric."""
    return {
        "cause": {
            "type": "choice",
            "instructions": CAUSE_INSTRUCTIONS,
            "criteria": {label: label.replace("_", " ") for label in CAUSE_LABELS},
        },
        "agreement": {
            "type": "score",
            "instructions": CAUSE_INSTRUCTIONS,
            "criteria": list(AGREEMENT_LEVELS),
        },
    }


@dataclass(frozen=True)
class JoinedRow:
    """One hand-checked row: the two prose causes, the lay explanation, and both marks."""

    row: int
    case_id: str
    judge_said: str
    codes_said: str
    andy_mark: str
    model_probable_cause: str
    ntsb_probable_cause: str
    model_lay_explanation: str


def load_joined_rows(working_csv: Path, marked_csv: Path) -> list[JoinedRow]:
    """Join the two hand-check sheets on ``row``, keeping every one of the 30 marked rows."""
    with working_csv.open(newline="") as handle:
        working = {int(r["row"]): r for r in csv.DictReader(handle)}
    joined: list[JoinedRow] = []
    with marked_csv.open(newline="") as handle:
        for marked in csv.DictReader(handle):
            row = int(marked["row"])
            if row not in working:
                raise ValueError(f"row {row}: in {marked_csv} but not in {working_csv}")
            w = working[row]
            joined.append(
                JoinedRow(
                    row=row,
                    case_id=w["case_id"],
                    judge_said=marked["judge_said"],
                    codes_said=marked["codes_said"],
                    andy_mark=marked["andy_mark"],
                    model_probable_cause=w["model_probable_cause"],
                    ntsb_probable_cause=w["ntsb_probable_cause"],
                    model_lay_explanation=w["model_lay_explanation"],
                )
            )
    return joined


def build_state(row: JoinedRow) -> str:
    """The comparison text for one row -- WITHHELD verdict text, judge role only (see module docstring)."""
    return (
        f"## Analyst's probable cause\n{row.model_probable_cause}\n\n"
        f"## Official probable cause\n{row.ntsb_probable_cause}\n\n"
        f"## Analyst's lay explanation\n{row.model_lay_explanation}\n"
    )


def _placeholder_payload(row: JoinedRow) -> Payload:
    """A Payload carrying nothing but ``row`` as a marker, so ``ask_all`` can price the case.

    Never sent to Jev: ``run`` looks the real (withheld-carrying) state up by this marker and
    calls ``TypeSafeClient.ask_state`` directly, because ``Payload`` can only ever hold
    evidence roles (``Payload.from_evidence`` refuses anything else by construction) and so
    structurally cannot carry the official probable cause this experiment needs to show Jev.
    """
    return Payload.from_evidence(
        Evidence(case_id=str(row.row), docket_url=None, registration=REGISTRATION_MARKER.format(row=row.row))
    )


@dataclass(frozen=True)
class JudgedRow:
    """One row's Jev answer, joined back with its hand-check marks."""

    row: JoinedRow
    cause: str
    cause_confidence: float
    agreement_level: float


def build_report(folder: Path, rows: Sequence[JoinedRow]) -> str:  # noqa: PLR0912 -- one report, many small tables.
    """The distributions, cross-tables and fixed reading spec'd for this experiment."""
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        raise FileNotFoundError(f"{folder}: no meta.json; is this a run folder?")
    replies = read_rows(folder / "replies.jsonl")
    ok = {r["case_id"]: r for r in replies if r["ok"]}
    by_row = {row.row: row for row in rows}
    judged: list[JudgedRow] = []
    for row in rows:
        raw = ok.get(str(row.row))
        if raw is None:
            continue
        reply = parse_reply(cast("Mapping[str, object]", raw["reply"]))
        cause = reply.choice("cause")
        agreement = reply.answers["agreement"]
        if not isinstance(agreement, ScoreAnswer):
            raise TypeError(f"row {row.row}: 'agreement' answer is not a Score")
        judged.append(
            JudgedRow(
                row=by_row[row.row],
                cause=cause.choice,
                cause_confidence=cause.confidence,
                agreement_level=agreement.score,
            )
        )

    out: list[str] = []
    add = out.append
    add(f"run {folder.name}")
    add(f"rows answered {len(judged)} of {len(rows)}")
    add(
        "\nThis is a disagreement sample, not a random one (0028's judge.pick_disagreements): "
        "every row was hand-checked because the LLM judge and the code-layer scorer disagreed "
        "on it. What the loaded rows' own columns show:"
    )
    add(f"judge_said distribution: {dict(Counter(r.judge_said for r in rows))}")
    add(f"codes_said distribution: {dict(Counter(r.codes_said for r in rows))}")
    mark_counts = Counter(r.andy_mark for r in rows)
    add(f"andy_mark distribution: {dict(mark_counts)}")
    expected_marks = {JUDGE_RIGHT_MARK, JUDGE_WRONG_MARK}
    if set(mark_counts) - expected_marks - {"both_defensible"}:
        add(f"NOTE: andy_mark has values beyond the expected set: {set(mark_counts)}")
    add(
        f"reading uses {JUDGE_WRONG_MARK!r} as \"the judge was wrong\" and {JUDGE_RIGHT_MARK!r} "
        "as \"the judge was right\"; 'both_defensible' is neither and is excluded from both "
        "groups below (reported on its own)."
    )

    if not judged:
        add("\nno answered rows were scored; the rest of this report is skipped")
        return "\n".join(out) + "\n"

    add(f"\nJev cause label distribution (n={len(judged)}): {dict(Counter(j.cause for j in judged))}")

    add("\nJev cause label x andy_mark")
    add("| andy_mark | " + " | ".join(CAUSE_LABELS) + " |")
    add("|---|" + "---|" * len(CAUSE_LABELS))
    for mark in sorted({j.row.andy_mark for j in judged}):
        counts = Counter(j.cause for j in judged if j.row.andy_mark == mark)
        add(f"| {mark} | " + " | ".join(str(counts.get(label, 0)) for label in CAUSE_LABELS) + " |")

    add("\nJev cause label x LLM judge's judge_said")
    judge_saids = sorted({j.row.judge_said for j in judged})
    add("| judge_said | " + " | ".join(CAUSE_LABELS) + " |")
    add("|---|" + "---|" * len(CAUSE_LABELS))
    for said in judge_saids:
        counts = Counter(j.cause for j in judged if j.row.judge_said == said)
        add(f"| {said} | " + " | ".join(str(counts.get(label, 0)) for label in CAUSE_LABELS) + " |")

    add("\nJev's mean confidence per cause label")
    for label in CAUSE_LABELS:
        confidences = [j.cause_confidence for j in judged if j.cause == label]
        if confidences:
            add(f"  {label}: mean {statistics.mean(confidences):.3f} (n={len(confidences)})")
        else:
            add(f"  {label}: n=0")

    add("\nagreement Score's mean level per andy_mark group")
    for mark in sorted({j.row.andy_mark for j in judged}):
        levels = [j.agreement_level for j in judged if j.row.andy_mark == mark]
        add(f"  {mark}: mean {statistics.mean(levels):.3f} (n={len(levels)})")

    wrong = [j for j in judged if j.row.andy_mark == JUDGE_WRONG_MARK]
    right = [j for j in judged if j.row.andy_mark == JUDGE_RIGHT_MARK]
    caught = sum(1 for j in wrong if j.cause in {"related", "different"}) / len(wrong) if wrong else None
    confirmed = sum(1 for j in right if j.cause == "same_cause") / len(right) if right else None
    add(
        f"\njudge-wrong rows ({JUDGE_WRONG_MARK}, n={len(wrong)}) Jev called related/different: "
        f"{f'{caught:.1%}' if caught is not None else 'n/a (no rows)'} "
        f"(bar: >= {WRONG_CAUGHT_THRESHOLD:.1%})"
    )
    add(
        f"judge-right rows ({JUDGE_RIGHT_MARK}, n={len(right)}) Jev called same_cause: "
        f"{f'{confirmed:.1%}' if confirmed is not None else 'n/a (no rows)'} "
        f"(bar: >= {RIGHT_CONFIRMED_THRESHOLD:.1%})"
    )
    usable = (
        caught is not None
        and confirmed is not None
        and caught >= WRONG_CAUGHT_THRESHOLD
        and confirmed >= RIGHT_CONFIRMED_THRESHOLD
    )
    add(f"\nreading (fixed in advance): {USABLE_READING if usable else NOT_USABLE_READING}")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str]) -> int:
    """``run`` asks Jev the cause Choice and agreement Score; ``report`` scores what was saved."""
    parser = argparse.ArgumentParser(prog="jev_followups.judge")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--resume", help="an existing run folder name under the runs directory")
    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("folder")
    report_cmd.add_argument("--out")
    args = parser.parse_args(argv)

    settings = Settings()
    working_csv = settings.runs_dir / HANDCHECK_RUN_FOLDER / HANDCHECK_WORKING_FILE
    rows = load_joined_rows(working_csv, HANDCHECK_MARKED_FILE)

    if args.command == "report":
        text = build_report(settings.runs_dir / args.folder, rows)
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
        meta: dict[str, object] = {
            "rows": len(rows), "commit": sha, "dirty": dirty,
            "started": datetime.now(UTC).isoformat(), "cap_usd": CAP_USD,
        }
        meta_file.write_text(json.dumps(meta, indent=1))
    states = {REGISTRATION_MARKER.format(row=row.row): build_state(row) for row in rows}
    cases = [(str(row.row), _placeholder_payload(row)) for row in rows]
    client_key = settings.require_typesafe_key()
    questions = judge_questions()
    with TypeSafeClient(client_key, base_url=settings.typesafe_base_url) as client:

        def ask(payload: Payload) -> Exchange:
            """Look the real, withheld-carrying state up by the placeholder's marker field."""
            marker = payload.fields()["registration"]
            return client.ask_state(states[cast("str", marker)], questions)

        reason = ask_all(
            folder / "replies.jsonl", cases, ask,
            cap_usd=CAP_USD, usd_per_token=USD_PER_TOKEN,
            tokens_per_request=TOKENS_PER_REQUEST_ESTIMATE,
        )
    saved = read_rows(folder / "replies.jsonl")
    answered = sum(1 for r in saved if r["ok"])
    spent = sum(float(str(r["cost_usd"])) for r in saved)
    print(f"{folder.name}: {reason}; answered {answered} of {len(rows)}; spent ${spent:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
