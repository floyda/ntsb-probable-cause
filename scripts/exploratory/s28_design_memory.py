"""A memory of the model's own answers, five-fold on dev-400, against a size-matched pool table (spec §4).

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
    uv run python scripts/exploratory/s28_design_memory.py <dev-400 run id> [<run id> ...]
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
POOL_ROWS = []
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
        POOL_ROWS.append((occ[0], fl))
        for k in [("group", g), ("code", occ[0]), ("event", occ[0][3:])]:
            n[k] += 1
            by[k].update(fl)


def pool_top(c, k=3):
    for key in [("code", m1(c)), ("event", m1(c)[3:]), ("group", grp[c["case_id"]])]:
        if n[key] >= 20:
            return [f for f, _ in by[key].most_common(k)]
    return []


def hyp(c):
    return c["steps"][-1]["hypothesis"]


def m1(c):
    g = hyp(c)["occurrence"][0]
    return g["phase"] + g["event"]


def mf(c):
    return [f["item8"] + f["modifier"] for f in hyp(c)["findings"] if f.get("item8")]


def recall(p, t):
    return len(set(p) & set(t)) / len(set(t))


SMALL = []
for seed in range(5):
    rows = random.Random(seed).sample(POOL_ROWS, 320)
    mem = defaultdict(Counter); cnt = Counter()
    for d, fl in rows:
        mem[d].update(fl); cnt[d] += 1
    SMALL.append((mem, cnt))
for run in sys.argv[1:]:
    cases = [json.loads(line) for line in (DATA / "runs" / run / "cases.jsonl").open()]
    cases = [c for c in cases if c.get("scores") and c["verdict_findings_in_cause"]]
    random.Random(1).shuffle(cases)
    folds = [cases[i::5] for i in range(5)]
    res = defaultdict(list)
    for i, test in enumerate(folds):
        train = [c for j, f in enumerate(folds) if j != i for c in f]
        occ_mem = defaultdict(Counter)
        occ_n = Counter()
        tr_mem = defaultdict(Counter)
        tr_n = Counter()
        for c in train:
            t = set(c["verdict_findings_in_cause"])
            occ_mem[m1(c)].update(t)
            occ_n[m1(c)] += 1
            for m in set(mf(c)):
                tr_mem[m].update(t)
                tr_n[m] += 1
        for c in test:
            t = c["verdict_findings_in_cause"]
            res["model alone"].append(recall(mf(c), t))
            res["A: pool counts by model code"].append(recall(pool_top(c), t))
            o = m1(c)
            pred = [f for f, _ in occ_mem[o].most_common(3)] if occ_n[o] >= 5 else pool_top(c)
            res["memory: when you said occurrence X (5+ cases)"].append(recall(pred, t))
            if occ_n[o] >= 5:
                res["covered: memory by model's occurrence"].append(recall(pred, t))
                res["covered: A, full pool"].append(recall(pool_top(c), t))
                for seed in range(5):
                    sm = SMALL[seed]
                    if sm[1][o] >= 5:
                        res[f"covered: A from 320 random pool cases"].append(recall([f for f, _ in sm[0][o].most_common(3)], t))
                    else:
                        res[f"covered: A from 320 random pool cases"].append(recall(pool_top(c), t))
            votes = Counter()
            for m in set(mf(c)):
                if tr_n[m] >= 5:
                    votes.update({f: k / tr_n[m] for f, k in tr_mem[m].items()})
            pred2 = [f for f, _ in votes.most_common(3)] or pool_top(c)
            res["memory: when you said finding Y (5+ cases)"].append(recall(pred2, t))
            both = Counter({f: 1.0 for f in pool_top(c, 3)})
            both.update(votes)
            res["A + finding memory, added"].append(recall([f for f, _ in both.most_common(3)], t))
    print("==", run)
    for name, r in res.items():
        print(f"  {name:48s} recall {100 * sum(r) / len(r):5.1f}%  (n={len(r)})")
