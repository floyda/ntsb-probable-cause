"""Ad-hoc, free: the S3 probe's noise floor -- two identical runs paired by case. Counts only.

Status: exploratory, one-shot learning-probe analysis for S3 (2026-09-29). Output is not a result;
it sets no bar and tunes nothing. Run from the worktree root with PYTHONPATH=.
"""

import sys
from pathlib import Path

from ntsb_probable_cause.scoring.codes import load_tables
from scripts.s3_probe.trail import CaseTrail

DATA = Path("/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/probes/s3-probe")
T = load_tables()


def load(job):
    lines = (DATA / job / "trails.jsonl").read_text().splitlines()
    return {t.case_id: t for t in (CaseTrail.model_validate_json(x) for x in lines)}


a, b = load(sys.argv[1]), load(sys.argv[2])
ids = sorted(a.keys() & b.keys())
print(f"paired cases: {len(ids)}")
print(f"cost: run 1 ${sum(t.cost_usd for t in a.values()):.4f}, run 2 ${sum(t.cost_usd for t in b.values()):.4f}")
print(f"failed: run 1 {sum(t.stop_reason.startswith('failed') for t in a.values())}, "
      f"run 2 {sum(t.stop_reason.startswith('failed') for t in b.values())}")


def top1(t, name):
    s = getattr(t, name)
    return s.hypothesis.occurrence_codes(T)[0] if s and s.hypothesis else None


def right(t, name):
    s = getattr(t, name)
    return bool(s and s.scores and s.scores.occurrence_top1)


print("\nstage: top-1 correct run 1 / run 2; cases whose top-1 code differs between runs; "
      "cases right in one run only")
for name in ("h0", "h1", "h2", "h_all", "refined"):
    both = [i for i in ids if top1(a[i], name) and top1(b[i], name)]
    differ = sum(top1(a[i], name) != top1(b[i], name) for i in both)
    one = sum(right(a[i], name) != right(b[i], name) for i in both)
    ra = sum(right(a[i], name) for i in ids)
    rb = sum(right(b[i], name) for i in ids)
    print(f"  {name:7} {ra} / {rb} of {len(ids)}; code differs {differ} of {len(both)}; "
          f"right in one run only {one} of {len(both)}")


def read(t):
    chosen = set()
    for c in (t.choice1, t.choice2):
        if c:
            chosen |= set(c.chosen)
    return chosen


def offered(t):
    return set(t.choice1.offered) if t.choice1 else set()


same = total = 0
for i in ids:
    for d in offered(a[i]) & offered(b[i]):
        total += 1
        same += (d in read(a[i])) == (d in read(b[i]))
ra = sum(len(read(a[i])) for i in ids)
rb = sum(len(read(b[i])) for i in ids)
off = sum(len(offered(a[i])) for i in ids)
print(f"\ndocuments read (either choice): run 1 {ra} of {off}, run 2 {rb} of {off}")
print(f"same read-or-skip decision on a document in both runs: {same} of {total}")
skipped_a = sum(bool(offered(a[i]) - read(a[i])) for i in ids)
skipped_b = sum(bool(offered(b[i]) - read(b[i])) for i in ids)
print(f"cases that skipped at least one document: run 1 {skipped_a}, run 2 {skipped_b}")


def regret(t):
    return top1(t, "h_all") is not None and top1(t, "h_all") != top1(t, "h2")


for label, runs in (("run 1", a), ("run 2", b)):
    skip = [i for i in ids if offered(runs[i]) - read(runs[i])]
    ctrl = [i for i in ids if not offered(runs[i]) - read(runs[i])]
    hr = sum(right(runs[i], "h_all") and not right(runs[i], "h2") for i in skip)
    rh = sum(right(runs[i], "h2") and not right(runs[i], "h_all") for i in skip)
    print(f"{label}: skip cases H_all differs from H2 {sum(regret(runs[i]) for i in skip)} of {len(skip)} "
          f"(H_all right & H2 wrong {hr}, reverse {rh}); controls differ "
          f"{sum(regret(runs[i]) for i in ctrl)} of {len(ctrl)}")

for label, runs in (("run 1", a), ("run 2", b)):
    reached = [t for t in runs.values() if t.true_in_arguments is not None]
    moved = [t for t in reached if top1(t, "refined") and top1(t, "refined") != top1(t, "h2")]
    w2r = sum(right(t, "refined") and not right(t, "h2") for t in moved)
    r2w = sum(right(t, "h2") and not right(t, "refined") for t in moved)
    conf0 = sum(t.h0.hypothesis.confidence for t in runs.values()) / len(runs)
    conf2 = sum(t.h2.hypothesis.confidence for t in runs.values() if t.h2.hypothesis) / len(runs)
    rec = [t.refined.scores.finding_recall_10 for t in runs.values() if t.refined.scores]
    print(f"{label}: true code among arguments {sum(bool(t.true_in_arguments) for t in reached)} of "
          f"{len(reached)}; final differs from H2 {len(moved)} (wrong->right {w2r}, right->wrong {r2w}); "
          f"confidence H0 {conf0:.2f} -> H2 {conf2:.2f}; finding recall@10 "
          f"{100 * sum(rec) / len(rec):.1f}% (n={len(rec)})")
