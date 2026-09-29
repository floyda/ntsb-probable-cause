"""Clear habits in the table, recall and precision by count, and paired noise and power (spec §5, §6).

Status
    One-shot, complete (S2.8 design, 2026-09-28/29). Exploratory measurements behind
    docs/specs/2026-09-29-s28-coding-lookup-design.md, kept so its ad-hoc figures can be
    re-derived. Nothing here is a result and nothing imports it: S2.8's committed scripts
    re-derive every figure the stage relies on.

Development cases only. The statistics pool is every development C/F/L case outside dev-400
and dev-seal-400 (decision 0094); dev-seal-400 is read only as a list of ids to exclude. The
run folders named on the command line are dev-400 arm B runs. Codes and counts only are
printed; no case is named.

Usage (from the repository root, NTSB_DATA_DIR pointed at the main checkout's data/):
    uv run python scripts/exploratory/s28_design_grounding.py <checked run id> <second checked run id>
"""

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, ".")
from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import samples
from scripts.coding_stats import processed_rows

from ntsb_probable_cause.settings import Settings

DATA = Settings().data_dir
GROUP = next(f for f in fields.EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)
dev400 = set(samples.sample_ids("dev-400"))
excluded = dev400 | set(samples.sample_ids("dev-seal-400"))
by = defaultdict(Counter)
n = Counter()
grp = {}
for case, _d, split, klass, raw in processed_rows(DATA / "processed"):
    if split != "dev" or klass not in {"C", "F", "L"}:
        continue
    g = GROUP.extract(raw)
    g = g if isinstance(g, str) else "(none)"
    if case in dev400:
        grp[case] = g
        continue
    if case in excluded:
        continue
    occ = fields.occurrence_codes(raw)
    fl = set(fields.finding_codes_in_cause(raw))
    if occ and fl:
        for k in [("group", g), ("code", occ[0]), ("event", occ[0][3:])]:
            n[k] += 1
            by[k].update(fl)


def hyp(c):
    return c["steps"][-1]["hypothesis"]


def m1(c):
    g = hyp(c)["occurrence"][0]
    return g["phase"] + g["event"]


def mf(c):
    return [f["item8"] + f["modifier"] for f in hyp(c)["findings"] if f.get("item8")]


def key_for(c):
    for key in [("code", m1(c)), ("event", m1(c)[3:]), ("group", grp[c["case_id"]])]:
        if n[key] >= 20:
            return key
    return None


def table(c, k):
    key = key_for(c)
    return [(f, x / n[key]) for f, x in by[key].most_common(k)] if key else []


def recall(p, t):
    return len(set(p) & set(t)) / len(set(t))


def prec(p, t):
    return len(set(p) & set(t)) / len(set(p)) if p else 0.0


def load(run):
    cs = [json.loads(line) for line in (DATA / "runs" / run / "cases.jsonl").open()]
    return {c["case_id"]: c for c in cs if c.get("scores") and c["verdict_findings_in_cause"]}


def paired(a, b, reps=2000):
    d = [x - y for x, y in zip(a, b)]
    rng = random.Random(0)
    means = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(reps))
    mean = sum(d) / len(d)
    sd = (sum((x - mean) ** 2 for x in d) / (len(d) - 1)) ** 0.5
    return mean, means[int(0.025 * reps)], means[int(0.975 * reps)], sd


r3 = load(sys.argv[1])
rep = load(sys.argv[2])
cases = list(r3.values())
print("== Q2: clear habits in the table (share >= 60% of >= 20 pool cases), Round 3 answers")
key_kinds = Counter(key_for(c)[0] if key_for(c) else "none" for c in cases)
print("  key used:", dict(key_kinds))
clear = [sum(1 for _, s in table(c, 10) if s >= 0.6) for c in cases]
print("  cases with 0/1/2+ clear habits:", Counter(min(x, 2) for x in clear))
hit_clear = sum(1 for c in cases for f, s in table(c, 10) if s >= 0.6 and f in c["verdict_findings_in_cause"])
all_clear = sum(1 for c in cases for f, s in table(c, 10) if s >= 0.6)
print(f"  clear-habit findings shown: {all_clear}, flagged by the NTSB: {hit_clear}")
print("  share of the top finding, quartiles:", sorted(table(c, 1)[0][1] for c in cases if table(c, 1))[len(cases) // 4 :: len(cases) // 4])

print("\n== Q3: recall and precision by how many findings, Round 3 answers")
print(f"  model alone ({sum(len(set(mf(c))) for c in cases) / len(cases):.1f} per case): recall {100 * sum(recall(mf(c), c['verdict_findings_in_cause']) for c in cases) / len(cases):.1f}%, precision {100 * sum(prec(mf(c), c['verdict_findings_in_cause']) for c in cases) / len(cases):.1f}%")
for k in (1, 2, 3, 4, 5, 8):
    r = sum(recall([f for f, _ in table(c, k)], c["verdict_findings_in_cause"]) for c in cases) / len(cases)
    p = sum(prec([f for f, _ in table(c, k)], c["verdict_findings_in_cause"]) for c in cases) / len(cases)
    print(f"  table top {k}: recall {100 * r:.1f}%, precision {100 * p:.1f}%")
for k in (5, 8, 10):
    r = sum(recall([f for f, _ in table(c, k)] + mf(c), c["verdict_findings_in_cause"]) for c in cases) / len(cases)
    print(f"  truth reachable if the model chose perfectly from table top {k} + its own: {100 * r:.1f}%")

print("\n== Q4: noise and power for finding recall (paired, per case)")
ids = sorted(set(r3) & set(rep))
a = [recall(mf(r3[i]), r3[i]["verdict_findings_in_cause"]) for i in ids]
b = [recall(mf(rep[i]), rep[i]["verdict_findings_in_cause"]) for i in ids]
m, lo, hi, sd = paired(a, b)
print(f"  model findings, Round 3 vs repeat: {100 * m:+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%], per-case sd {100 * sd:.1f}")
t3 = [recall([f for f, _ in table(r3[i], 3)], r3[i]["verdict_findings_in_cause"]) for i in ids]
tr = [recall([f for f, _ in table(rep[i], 3)], rep[i]["verdict_findings_in_cause"]) for i in ids]
m, lo, hi, sd = paired(t3, tr)
print(f"  table top 3, keyed on Round 3's vs the repeat's occurrence: {100 * m:+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%], sd {100 * sd:.1f}")
m, lo, hi, sd = paired(t3, a)
print(f"  table top 3 vs the model's findings (Round 3): {100 * m:+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%], sd {100 * sd:.1f}")
un = [recall([f for f, _ in table(r3[i], 2)] + mf(r3[i]), r3[i]["verdict_findings_in_cause"]) for i in ids]
m, lo, hi, sd = paired(un, t3)
print(f"  model's own + table top 2 vs table top 3: {100 * m:+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%], sd {100 * sd:.1f}")
print(f"  smallest gain showing at n={len(ids)} with sd 20 / 30 points: about {100 * 2.8 * 0.20 / len(ids) ** 0.5:.1f} / {100 * 2.8 * 0.30 / len(ids) ** 0.5:.1f} points (80% power)")
