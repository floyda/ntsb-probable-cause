"""Ad-hoc, free: stated confidence against correctness, cost by case kind, and batch timing.

Reads the S3 probe's trails (development cases only) and the run records under the shared runs
folder. Prints counts only -- no case number, no text. Signals for the S3 specification.

Status: exploratory, one-shot learning-probe analysis for S3 (2026-09-30). Output is not a result;
it sets no bar and tunes nothing. Run from the worktree root with PYTHONPATH=.

    PYTHONPATH=. uv run python scripts/exploratory/s3_probe_confidence.py <job id> [<job id> ...]
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from scripts.s3_probe.trail import CaseTrail

DATA = Path("/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data")
BAND = 0.6


def load(job):
    lines = (DATA / "probes/s3-probe" / job / "trails.jsonl").read_text().splitlines()
    return [CaseTrail.model_validate_json(x) for x in lines]


def right_of(rows):
    return f"{sum(ok for _, ok, _ in rows)} of {len(rows)}"


for job in sys.argv[1:]:
    trails = load(job)
    print(f"== {job}")
    for name in ("h0", "h2", "refined"):
        rows = []
        for t in trails:
            stage = getattr(t, name)
            if stage and stage.hypothesis and stage.scores:
                h = stage.hypothesis
                rows.append((h.confidence, bool(stage.scores.occurrence_top1), h.abstain))
        high = [r for r in rows if r[0] >= BAND]
        low = [r for r in rows if r[0] < BAND]
        mean = sum(r[0] for r in rows) / len(rows)
        print(
            f"  {name}: n={len(rows)}; mean stated confidence {mean:.2f}; "
            f"top-1 right at confidence >= {BAND}: {right_of(high)}; below: {right_of(low)}; "
            f"abstained: {sum(r[2] for r in rows)}"
        )

    with_t = [t for t in trails if any(d.transcribed_pages > 0 for d in t.documents)]
    without = [t for t in trails if t not in with_t]

    def mean_cost(group):
        return sum(t.cost_usd for t in group) / len(group) if group else 0.0

    print(
        f"  cost per case: with transcribed documents (n={len(with_t)}) ${mean_cost(with_t):.4f}; "
        f"without (n={len(without)}) ${mean_cost(without):.4f}"
    )
    by_phase = defaultdict(float)
    for t in trails:
        for call in t.calls:
            by_phase[call.phase] += call.cost_usd
    total = sum(by_phase.values())
    shares = ", ".join(
        f"{k} {100 * v / total:.0f}%" for k, v in sorted(by_phase.items(), key=lambda kv: -kv[1])
    )
    print(f"  cost share by phase: {shares}")

# Batch timing: finished GPT-6 Luna runs on dev-400 at the batch price, one answering call per case.
print("== batch runs on dev-400, GPT-6 Luna, more than 300 cases, cost over $0.50")
hours, costs = [], []
for run_file in sorted((DATA / "runs").glob("*/run.jsonl")):
    for line in run_file.read_text().splitlines():
        r = json.loads(line)
        if not r.get("finished") or r.get("sample") != "dev-400" or r.get("cases", 0) <= 300:
            continue
        if "gpt-6" not in r["model"] or r["price_variant"] != "batch" or r["cost_usd"] < 0.5:
            continue
        start, end = datetime.fromisoformat(r["started"]), datetime.fromisoformat(r["finished"])
        hours.append((end - start).total_seconds() / 3600)
        costs.append(r["cost_usd"])
print(
    f"  runs: {len(hours)}; cost ${min(costs):.2f} to ${max(costs):.2f}; "
    f"hours start to finish: min {min(hours):.2f}, median {sorted(hours)[len(hours) // 2]:.2f}, "
    f"max {max(hours):.2f}"
)
