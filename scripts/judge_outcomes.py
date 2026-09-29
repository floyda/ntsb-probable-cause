"""The four outcomes from the judge's labels, per run, and how they move between runs.

Status
    Live for S2.7 (spec §4.3, decision 0099), free: reads judge.jsonl and cases.jsonl from
    judged development run folders; counts only. Round 0 runs it on B-v1, its repeat and B-v2;
    each kept guidance round runs it again.

Why
    A miss is either "understood, miscoded" (guidance can fix it) or "misread"/"thin evidence"
    (reading better can). The judge's narrative label separates them, once validated by Andy's
    hand-read (scripts/round0_handread.py); until then every heading says "unvalidated".

Usage
    uv run python -m scripts.judge_outcomes --runs V1 REPEAT V2 [--label-status validated]
    [--out PATH]
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.judge import JudgeLabels
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings

Outcome = Literal["right", "understood, miscoded", "thin evidence", "misread"]
OUTCOMES: tuple[Outcome, ...] = ("right", "understood, miscoded", "thin evidence", "misread")
JUDGE_FILE = "judge.jsonl"
# --runs takes exactly v1, its repeat and v2 for the movement section to print.
_TRIPLE = 3


def outcome(top1: bool, narrative: str) -> Outcome:
    """Decision 0099 item 1."""
    if top1:
        return "right"
    if narrative == "consistent":
        return "understood, miscoded"
    if narrative == "less_detailed":
        return "thin evidence"
    return "misread"


def read_labels(folder: Path) -> dict[str, JudgeLabels]:
    """A judged run's labels by case id."""
    labels: dict[str, JudgeLabels] = {}
    for line in (folder / JUDGE_FILE).read_text().splitlines():
        if line:
            row: dict[str, object] = json.loads(line)
            case_id = row.pop("case_id")
            if not isinstance(case_id, str):  # a malformed row
                raise TypeError(f"judge row case_id is not a string: {case_id!r}")
            labels[case_id] = JudgeLabels.model_validate(
                {k: v for k, v in row.items() if k != "cost_usd"}
            )
    return labels


def outcomes(cases: Sequence[CaseResult], labels: Mapping[str, JudgeLabels]) -> dict[str, Outcome]:
    """Each judged, scored case's outcome."""
    return {
        c.case_id: outcome(c.scores.occurrence_top1, labels[c.case_id].narrative)
        for c in cases
        if c.scores is not None and c.case_id in labels
    }


def _block(
    title: str, ids: Sequence[str], outs: Mapping[str, Outcome], labels: Mapping[str, JudgeLabels]
) -> list[str]:
    counts = Counter(outs[i] for i in ids)
    lines = [f"{title} ({len(ids)} cases):"]
    for name in OUTCOMES:
        causes = Counter(labels[i].cause for i in ids if outs[i] == name)
        cause_text = ", ".join(f"{k} {v}" for k, v in sorted(causes.items()))
        lines.append(f"  {name}: {counts[name]} of {len(ids)}; cause label: {cause_text or '-'}")
    return lines


def shares(
    name: str,
    cases: Sequence[CaseResult],
    outs: Mapping[str, Outcome],
    labels: Mapping[str, JudgeLabels],
    *,
    status: str,
) -> str:
    """One run's outcome shares, all cases and fatal / non-fatal."""
    judged = [c for c in cases if c.case_id in outs]
    lines = [f"## {name} -- outcomes ({status} narrative label, decision 0099)"]
    lines += _block("all", [c.case_id for c in judged], outs, labels)
    lines += _block("fatal", [c.case_id for c in judged if c.fatal], outs, labels)
    lines += _block("non-fatal", [c.case_id for c in judged if not c.fatal], outs, labels)
    return "\n".join(lines)


def movement(a: Mapping[str, Outcome], b: Mapping[str, Outcome]) -> tuple[int, int]:
    """(cases whose outcome differs, cases judged in both)."""
    shared = sorted(set(a) & set(b))
    return sum(a[i] != b[i] for i in shared), len(shared)


def _load(settings: Settings, run_id: str) -> tuple[list[CaseResult], dict[str, JudgeLabels]]:
    """A development run's cases and labels, after every refusal (held-out, sealed, split)."""
    folder = settings.runs_dir / run_id
    try:
        samples.refuse_unless_development(run_id, None)
        record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
        samples.refuse_unless_development(run_id, record.sample)
    except ConfigurationError as error:
        raise SystemExit(f"judge_outcomes: {error}") from error
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        raise SystemExit(f"judge_outcomes: {run_id} holds a case outside the dev split")
    return cases, read_labels(folder)


def main(argv: Sequence[str] | None = None) -> int:
    """Print each run's outcomes, then v1 against v2 and v1 against its repeat."""
    parser = argparse.ArgumentParser(prog="judge_outcomes")
    parser.add_argument("--runs", nargs="+", required=True, metavar="RUN_ID")
    parser.add_argument(
        "--label-status", choices=("validated", "unvalidated"), default="unvalidated"
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    loaded = [(run_id, *_load(settings, run_id)) for run_id in args.runs]
    per_run = [(run_id, cases, labels, outcomes(cases, labels)) for run_id, cases, labels in loaded]
    parts = [
        "judge outcomes (scripts/judge_outcomes.py; counts only, decision 0099)",
        *(shares(r, c, o, lab, status=args.label_status) for r, c, lab, o in per_run),
    ]
    if len(per_run) == _TRIPLE:
        v1, repeat, v2 = (p[3] for p in per_run)
        moved_repeat, n_repeat = movement(v1, repeat)
        moved_v2, n_v2 = movement(v1, v2)
        parts += [
            "## movement between runs (label churn is the repeat's movement)",
            f"v1 against its repeat: {moved_repeat} of {n_repeat} cases change outcome",
            f"v1 against v2: {moved_v2} of {n_v2} cases change outcome",
        ]
    text = "\n\n".join(parts)
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
