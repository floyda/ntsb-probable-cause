"""Experiment 4: 130 finding-category Nouls per case against Luna's LLM findings (decision 0060).

One call per case, over the first 150 case IDs of ``dev-400``, carrying all 130 finding-category
Nouls worded exactly as ``scripts/typesafe_probe.py:noul_questions`` words them. The payload is
the ordinary evidence payload from ``runner.case_payload`` with ``RunSpec(sample="dev-400",
arm="ceiling")`` -- no withheld text, so this module is an answering-shaped probe, not a judge:
it never renders synthesis or verdict text into a state (0013, 0016).

A category is "believed" when its probability is at or above a threshold. The believed set is
compared against the case's true finding codes' first six digits: ``verdict.finding_codes_in_cause``
(the strict set S1 scores Luna's P@6/R@6 against) and ``verdict.finding_codes`` (all findings,
a looser reference). Luna's dev-400 numbers are quoted from ``docs/results/s1-ceiling-dev.txt``
at report time, never hardcoded.

Usage (from the worktree root; data lives in the main checkout):
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
    TYPESAFE_API_KEY="$(pass show api/typesafe | head -1)" \\
        uv run python -m scripts.exploratory.jev_followups.findings run [--resume FOLDER]
    NTSB_DATA_DIR=<main>/data NTSB_RUNS_DIR=<main>/data/runs \\
        uv run python -m scripts.exploratory.jev_followups.findings report FOLDER [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ntsb_probable_cause.model.typesafe import NoulAnswer, TypeSafeClient, parse_reply
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import ledger, samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.runner import RunSpec, case_payload
from ntsb_probable_cause.settings import Settings
from scripts.exploratory.jev_dev400 import CAP_USD, USD_PER_TOKEN, ask_all, read_rows
from scripts.typesafe_probe import noul_questions

SAMPLE = "dev-400"
CASE_LIMIT = 150
RUN_SUFFIX = "jev-followups-findings"
# A noul question per case runs to about 7,150 input tokens on the probe's single fixture
# (tests/fixtures/typesafe/nouls.json), against the phase/event probe's 4,344; round up.
TOKENS_PER_REQUEST_ESTIMATE = 8_000
CATEGORY_PREFIX = "category_"
FINDING_DIGITS = 6
# Spec: sweep 0.05..0.50 in steps of 0.05 (0.50 is both the sweep's last point and the fixed
# threshold the reading also checks on its own, named separately so nothing is silently tuned).
THRESHOLDS: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(1, 11))
FIXED_THRESHOLD = 0.5
LUNA_RESULT_FILE = Path("docs/results/s1-ceiling-dev.txt")
BEATS_READING = "the Noul shape beats the LLM on findings"
NOT_BEATS_READING = "the Noul shape does not beat the LLM on findings"


def believed_categories(reply_answers: Mapping[str, object], threshold: float) -> frozenset[str]:
    """Six-digit category codes whose Noul probability is at or above ``threshold``."""
    believed: set[str] = set()
    for name, answer in reply_answers.items():
        if not isinstance(answer, NoulAnswer) or not name.startswith(CATEGORY_PREFIX):
            continue
        if answer.noul >= threshold:
            believed.add(name.removeprefix(CATEGORY_PREFIX))
    return frozenset(believed)


@dataclass(frozen=True)
class PrecisionRecall:
    """Precision/recall at ``FINDING_DIGITS`` digits, or ``None`` when the truth side is empty."""

    precision: float | None
    recall: float | None


def precision_recall(predicted: frozenset[str], truth: Sequence[str]) -> PrecisionRecall:
    """Set precision/recall at six digits (S1's ``_precision_recall`` convention, no abstention).

    Jev's Nouls never abstain, so unlike ``metrics._precision_recall`` there is no abstained
    case to force precision to 0.0: precision is ``None`` only when nothing was believed,
    exactly as an answered-but-empty prediction reads there.
    """
    t = {c[:FINDING_DIGITS] for c in truth}
    p = predicted
    precision = len(p & t) / len(p) if p else None
    recall = len(p & t) / len(t) if t else None
    return PrecisionRecall(precision=precision, recall=recall)


@dataclass(frozen=True)
class ThresholdRow:
    """One threshold's aggregate numbers over every scored case."""

    threshold: float
    mean_believed: float
    precision_strict: float | None
    recall_strict: float | None
    n_precision_strict: int
    n_recall_strict: int
    precision_all: float | None
    recall_all: float | None


def _mean(values: Sequence[float]) -> float | None:
    return statistics.mean(values) if values else None


def threshold_row(
    threshold: float, believed_sets: Sequence[frozenset[str]], verdicts: Sequence[Verdict]
) -> ThresholdRow:
    """Aggregate precision/recall at one threshold, over every case's believed set."""
    strict = [precision_recall(b, v.finding_codes_in_cause) for b, v in zip(believed_sets, verdicts, strict=True)]
    all_findings = [precision_recall(b, v.finding_codes) for b, v in zip(believed_sets, verdicts, strict=True)]
    strict_p = [pr.precision for pr in strict if pr.precision is not None]
    strict_r = [pr.recall for pr in strict if pr.recall is not None]
    all_p = [pr.precision for pr in all_findings if pr.precision is not None]
    all_r = [pr.recall for pr in all_findings if pr.recall is not None]
    return ThresholdRow(
        threshold=threshold,
        mean_believed=statistics.mean([len(b) for b in believed_sets]) if believed_sets else 0.0,
        precision_strict=_mean(strict_p),
        recall_strict=_mean(strict_r),
        n_precision_strict=len(strict_p),
        n_recall_strict=len(strict_r),
        precision_all=_mean(all_p),
        recall_all=_mean(all_r),
    )


@dataclass(frozen=True)
class LunaFindings:
    """Luna's dev-400 "all" slice P@6/R@6, quoted from a saved report file."""

    precision_6: float
    recall_6: float


_LUNA_ROW = re.compile(r"^\|\s*all\s*\|.*$")
_PCT = re.compile(r"(\d+(?:\.\d+)?)%")


def read_luna_findings(path: Path = LUNA_RESULT_FILE) -> LunaFindings:
    """Parse the "all" row's P@6 and R@6 from ``docs/results/s1-ceiling-dev.txt``.

    The header row names the columns; P@6 and R@6 are the twelfth and thirteenth data
    columns (after "slice", "n", "top-1", "top-3", "event", "pair unseen", "abstain",
    "answered top-1", "finding P@10", "R@10", "P@8", "R@8"). Located by header text rather
    than a fixed index, so a reordering of the table breaks loudly instead of misreading it.
    """
    lines = path.read_text().splitlines()
    header = next(line for line in lines if line.strip().startswith("| slice"))
    columns = [c.strip() for c in header.strip("|").split("|")]
    p6_index = columns.index("P@6")
    r6_index = columns.index("R@6")
    row = next(line for line in lines if _LUNA_ROW.match(line))
    cells = [c.strip() for c in row.strip("|").split("|")]
    return LunaFindings(precision_6=_pct(cells[p6_index]), recall_6=_pct(cells[r6_index]))


def _pct(cell: str) -> float:
    """Parse a leading ``NN.N%`` out of a table cell such as ``18.1% [15.0%, 21.4%]``."""
    match = _PCT.match(cell)
    if match is None:
        raise ValueError(f"cell has no leading percentage: {cell!r}")
    return float(match.group(1)) / 100


def beats_llm_reading(rows: Sequence[ThresholdRow], luna: LunaFindings) -> tuple[str, float | None]:
    """Spec's fixed reading: is there a swept threshold beating Luna's P@6 and R@6 together?"""
    candidates = [
        r.threshold
        for r in rows
        if r.precision_strict is not None
        and r.recall_strict is not None
        and r.precision_strict > luna.precision_6
        and r.recall_strict > luna.recall_6
    ]
    if not candidates:
        return NOT_BEATS_READING, None
    # "Best" threshold among those that beat both bars: the one with the higher precision,
    # ties broken by recall -- an arbitrary but stated tie-break, since both already beat Luna.
    best = max(
        candidates,
        key=lambda t: next(
            (r.precision_strict or 0.0, r.recall_strict or 0.0) for r in rows if r.threshold == t
        ),
    )
    return BEATS_READING, best


def build_report(  # noqa: PLR0913 -- mirrors the sibling follow-ups' Interfaces block.
    folder: Path,
    raws: Sequence[Mapping[str, object]],
    ids: Sequence[str],
    tables: CodeTables,
    luna: LunaFindings,
) -> str:
    """Every threshold's precision/recall, the sweep, the fixed threshold, and the reading."""
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        raise FileNotFoundError(f"{folder}: no meta.json; is this a run folder?")
    rows = read_rows(folder / "replies.jsonl")
    ok = {row["case_id"]: row for row in rows if row["ok"]}
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    believed_by_threshold: dict[float, list[frozenset[str]]] = {t: [] for t in THRESHOLDS}
    verdicts: list[Verdict] = []
    for case_id, raw in zip(ids, raws, strict=True):
        if case_id not in ok:
            continue
        _, _, verdict, _ = case_payload(raw, spec, tables)
        reply = parse_reply(cast("Mapping[str, object]", ok[case_id]["reply"]))
        verdicts.append(verdict)
        for threshold in THRESHOLDS:
            believed_by_threshold[threshold].append(believed_categories(reply.answers, threshold))

    out: list[str] = []
    add = out.append
    add(f"run {folder.name}")
    add(f"sample={SAMPLE} first {CASE_LIMIT} case ids; cases answered {len(verdicts)} of {len(ids)}")
    if not verdicts:
        add("no answered cases were scored")
        return "\n".join(out) + "\n"

    rows_by_threshold = [
        threshold_row(t, believed_by_threshold[t], verdicts) for t in THRESHOLDS
    ]
    add(
        "\nquoted from docs/results/s1-ceiling-dev.txt, slice 'all': Luna P@6 "
        f"{luna.precision_6:.1%}, R@6 {luna.recall_6:.1%}. Luna's file also reports P@10/R@10 "
        "(ten-digit finding codes, a different, stricter pairing than the six-digit category "
        "codes here); P@6/R@6 is the comparable pair -- both are six-digit."
    )
    add("\nSTRICT SET (verdict.finding_codes_in_cause), six digits")
    add("| threshold | mean believed | precision | n | recall | n |")
    add("|---|---|---|---|---|---|")
    for r in rows_by_threshold:
        marker = " (fixed)" if r.threshold == FIXED_THRESHOLD else ""
        add(
            f"| {r.threshold:.2f}{marker} | {r.mean_believed:.2f} "
            f"| {r.precision_strict:.1%} | {r.n_precision_strict} "
            f"| {r.recall_strict:.1%} | {r.n_recall_strict} |"
            if r.precision_strict is not None and r.recall_strict is not None
            else f"| {r.threshold:.2f}{marker} | {r.mean_believed:.2f} | -- | 0 | -- | 0 |"
        )
    add("\nALL FINDINGS (verdict.finding_codes), six digits -- a looser reference, not compared")
    add("| threshold | precision | recall |")
    add("|---|---|---|")
    for r in rows_by_threshold:
        p = f"{r.precision_all:.1%}" if r.precision_all is not None else "--"
        rc = f"{r.recall_all:.1%}" if r.recall_all is not None else "--"
        add(f"| {r.threshold:.2f} | {p} | {rc} |")

    reading, best = beats_llm_reading(rows_by_threshold, luna)
    add(f"\nreading (fixed in advance): {reading}")
    if best is not None:
        add(f"best swept threshold beating both bars: {best:.2f}")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str]) -> int:
    """``run`` asks Jev the 130 Nouls per case; ``report`` scores what was saved."""
    parser = argparse.ArgumentParser(prog="jev_followups.findings")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--resume", help="an existing run folder name under the runs directory")
    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("folder")
    report_cmd.add_argument("--out")
    args = parser.parse_args(argv)

    settings = Settings()
    tables = load_tables()
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids(SAMPLE)[:CASE_LIMIT]
    raws = samples.load_cases(processed, ids)

    if args.command == "report":
        luna = read_luna_findings()
        text = build_report(settings.runs_dir / args.folder, raws, ids, tables, luna)
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
            "sample": SAMPLE, "case_limit": CASE_LIMIT, "commit": sha, "dirty": dirty,
            "started": datetime.now(UTC).isoformat(), "cap_usd": CAP_USD,
        }
        meta_file.write_text(json.dumps(meta, indent=1))
    spec = RunSpec(sample=SAMPLE, arm="ceiling")
    cases = []
    for case_id, raw in zip(ids, raws, strict=True):
        payload, _, _, evidence = case_payload(raw, spec, tables)
        if evidence.case_id != case_id:
            raise ValueError(f"sample order broken: {case_id} != {evidence.case_id}")
        cases.append((case_id, payload))
    client_key = settings.require_typesafe_key()
    with TypeSafeClient(client_key, base_url=settings.typesafe_base_url) as client:
        questions = noul_questions(tables)
        reason = ask_all(
            folder / "replies.jsonl", cases, lambda p: client.ask(p, questions),
            cap_usd=CAP_USD, usd_per_token=USD_PER_TOKEN,
            tokens_per_request=TOKENS_PER_REQUEST_ESTIMATE,
        )
    rows = read_rows(folder / "replies.jsonl")
    answered = sum(1 for r in rows if r["ok"])
    spent = sum(float(str(r["cost_usd"])) for r in rows)
    print(f"{folder.name}: {reason}; answered {answered} of {len(ids)}; spent ${spent:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
