"""Finding recall of pool-count tables under several keys, against the model's own findings (spec §1).

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
    uv run python scripts/exploratory/s28_design_lookup_keys.py <dev-400 run id>
"""

import json
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
RUN = DATA / "runs" / sys.argv[1]
GROUP = next(f for f in fields.EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)
dev400 = set(samples.sample_ids("dev-400"))
excluded = dev400 | set(samples.sample_ids("dev-seal-400"))

by = defaultdict(Counter)
keyn = Counter()
dev_group = {}
npool = 0
for case, date, split, klass, raw in processed_rows(DATA / "processed"):
    if split != "dev" or klass not in {"C", "F", "L"}:
        continue
    g = GROUP.extract(raw)
    g = g if isinstance(g, str) else "(none)"
    if case in dev400:
        dev_group[case] = g
        continue
    if case in excluded:
        continue
    occ = fields.occurrence_codes(raw)
    fl = set(fields.finding_codes_in_cause(raw))
    if not occ or not fl:
        continue
    npool += 1
    fatal = raw.get("highestInjuryLevel") == "Fatal"
    d = occ[0]
    for k in [("none",), ("group", g), ("code", d), ("event", d[3:]), ("code_fatal", d, fatal)]:
        keyn[k] += 1
        by[k].update(fl)


def top(key, k, min_n=20):
    if keyn[key] < min_n:
        return None
    return [c for c, _ in by[key].most_common(k)]


def backoff(keys, k):
    for key in keys:
        t = top(key, k)
        if t is not None:
            return t
    return top(("none",), k)


cases = [json.loads(line) for line in (RUN / "cases.jsonl").open()]
cases = [c for c in cases if c.get("scores") and c["verdict_findings_in_cause"]]


def mcodes(c):
    h = c["steps"][-1]["hypothesis"]
    occ = [g["phase"] + g["event"] for g in h["occurrence"]]
    model_findings = [f["item8"] + f["modifier"] for f in h["findings"] if f.get("item8")]
    return occ, model_findings


def recall(p, t):
    return len(set(p) & set(t)) / len(set(t))


def prec(p, t):
    return len(set(p) & set(t)) / len(set(p)) if p else 0.0


def pred_for(name, c, k):
    occ, mf = mcodes(c)
    g = dev_group[c["case_id"]]
    fat = c["fatal"]
    m1 = occ[0]
    d = c["verdict_occurrence"][0]
    if name == "model":
        return mf
    if name == "none":
        return top(("none",), k)
    if name == "group":
        return backoff([("group", g)], k)
    if name == "oracle_code":
        return backoff([("code", d), ("event", d[3:]), ("group", g)], k)
    if name == "model_code>event>group":
        return backoff([("code", m1), ("event", m1[3:]), ("group", g)], k)
    if name == "model_code_fatal>...":
        return backoff([("code_fatal", m1, fat), ("code", m1), ("event", m1[3:]), ("group", g)], k)
    raise ValueError(name)


print(f"pool cases with codes and flagged findings: {npool}; dev-400 scored cases: {len(cases)}")
for name in ["model", "none", "group", "model_code>event>group", "model_code_fatal>...", "oracle_code"]:
    for k in (3, 5, 8):
        r = [recall(pred_for(name, c, k), c["verdict_findings_in_cause"]) for c in cases]
        p = [prec(pred_for(name, c, k), c["verdict_findings_in_cause"]) for c in cases]
        print(f"{name:26s} k={k}: recall {100 * sum(r) / len(r):5.1f}%  precision {100 * sum(p) / len(p):5.1f}%")
        if name == "model":
            break
for k in (2, 3, 5):
    r = []
    n = []
    for c in cases:
        occ, mf = mcodes(c)
        lk = pred_for("model_code>event>group", c, k)
        u = list(dict.fromkeys(mf + lk))
        r.append(recall(u, c["verdict_findings_in_cause"]))
        n.append(len(u))
    print(f"union model + lookup k={k}: recall {100 * sum(r) / len(r):5.1f}%, codes/case {sum(n) / len(n):.1f}")
tf = Counter(x for c in cases for x in set(c["verdict_findings_in_cause"]))
mf_all = Counter(x for c in cases for x in set(mcodes(c)[1]))
found = sum(len(set(mcodes(c)[1]) & set(c["verdict_findings_in_cause"])) for c in cases)
print("flagged per case", round(sum(len(set(c["verdict_findings_in_cause"])) for c in cases) / len(cases), 2),
      "model per case", round(sum(len(set(mcodes(c)[1])) for c in cases) / len(cases), 2),
      "flagged total", sum(tf.values()), "found", found)
for code in ["0206304044", "0204101544", "0500000000"]:
    print(code, "NTSB flagged in", tf[code], "cases; model gives in", mf_all[code])
print("modifier 20: NTSB", sum(1 for c in cases for x in set(c["verdict_findings_in_cause"]) if x.endswith("20")),
      "model", sum(1 for c in cases for x in set(mcodes(c)[1]) if x.endswith("20")))
print("NTSB top flagged:", tf.most_common(8))
print("model top:", mf_all.most_common(8))
