"""Option A's examples, richer keys, and nearest-past-case retrieval by text (spec §1, §3).

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
    uv run --with scikit-learn python scripts/exploratory/s28_design_examples_and_retrieval.py <run id>
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

sys.path.insert(0, ".")
from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import load_tables
from scripts.coding_stats import processed_rows

from ntsb_probable_cause.settings import Settings

DATA = Settings().data_dir
RUN = DATA / "runs" / sys.argv[1]
T = load_tables()
ROLE = {f.role: f for f in fields.EVIDENCE_FIELDS}
dev400 = set(samples.sample_ids("dev-400"))
excluded = dev400 | set(samples.sample_ids("dev-seal-400"))


def val(raw, role):
    v = ROLE[role].extract(raw)
    return v if isinstance(v, str) and v else "(none)"


pool = []  # (defining, flagged, group, weather, engine, factual, cause)
dev = {}
for case, date, split, klass, raw in processed_rows(DATA / "processed"):
    if split != "dev" or klass not in {"C", "F", "L"}:
        continue
    g = val(raw, EvidenceRole.PHASE_OF_FLIGHT)
    w = val(raw, EvidenceRole.WEATHER_CONDITION)
    e = val(raw, EvidenceRole.ENGINE_TYPE)
    if case in dev400:
        dev[case] = (g, w, e)
        continue
    if case in excluded:
        continue
    occ = fields.occurrence_codes(raw)
    fl = sorted(set(fields.finding_codes_in_cause(raw)))
    if not occ or not fl:
        continue
    pool.append((occ[0], fl, g, w, e, fields.factual_narrative(raw) or "", fields.probable_cause(raw) or ""))

by = defaultdict(Counter)
n = Counter()
for d, fl, g, w, e, _f, _c in pool:
    for k in [("group", g), ("code", d), ("event", d[3:]), ("code_w", d, w), ("code_e", d, e)]:
        n[k] += 1
        by[k].update(fl)


def top(keys, k):
    for key in keys:
        if n[key] >= 20:
            return [c for c, _ in by[key].most_common(k)], key
    return [], None


def flabel(code):
    return f"{T.categories.get(code[:6], '?')} / {T.items.get(code[:8], '?')} / {T.modifiers.get(code[8:], '?')}"


def olabel(code):
    return f"{T.phases.get(code[:3], '?')} / {T.events.get(code[3:], '?')}"


cases = [json.loads(line) for line in (RUN / "cases.jsonl").open()]
cases = [c for c in cases if c.get("scores") and c["verdict_findings_in_cause"]]


def hyp(c):
    return c["steps"][-1]["hypothesis"]


def m1(c):
    g = hyp(c)["occurrence"][0]
    return g["phase"] + g["event"]


# Examples for option A: the model's four commonest first codes
print("== Option A examples (pool counts; codes and labels only)")
for code, cnt in Counter(m1(c) for c in cases).most_common(4):
    key = ("code", code)
    print(f"\nmodel's first code {code} {olabel(code)}: first in {cnt} dev-400 answers; pool cases with it defining: {n[key]}")
    for f, k in by[key].most_common(5):
        print(f"   {f}  {flabel(f)}: flagged in {k} of {n[key]} ({100 * k / n[key]:.0f}%)")


def recall(p, t):
    return len(set(p) & set(t)) / len(set(t))


def evaluate(name, predict):
    r = [recall(predict(c), c["verdict_findings_in_cause"]) for c in cases]
    print(f"{name:55s} recall {100 * sum(r) / len(r):5.1f}%")


print("\n== Recall of 3 findings per case, dev-400 (Round 3 run's answers)")
evaluate("model alone", lambda c: [f["item8"] + f["modifier"] for f in hyp(c)["findings"] if f.get("item8")])
evaluate("A: counts by model code > event > group", lambda c: top([("code", m1(c)), ("event", m1(c)[3:]), ("group", dev[c["case_id"]][0])], 3)[0])
evaluate("A+weather: code+weather > code > event > group", lambda c: top([("code_w", m1(c), dev[c["case_id"]][1]), ("code", m1(c)), ("event", m1(c)[3:]), ("group", dev[c["case_id"]][0])], 3)[0])
evaluate("A+engine: code+engine > code > event > group", lambda c: top([("code_e", m1(c), dev[c["case_id"]][2]), ("code", m1(c)), ("event", m1(c)[3:]), ("group", dev[c["case_id"]][0])], 3)[0])

# Retrieval: nearest past cases by text similarity to the model's own evidence narrative
queries = [hyp(c)["evidence_narrative"] for c in cases]
for index_name, col in (("past factual narratives", 5), ("past probable-cause sentences", 6)):
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=2)
    X = vec.fit_transform([p[col] for p in pool])
    Q = vec.transform(queries)
    S = (Q @ X.T).toarray()
    for kn in (25, 100):
        preds = []
        same = []
        for i, c in enumerate(cases):
            idx = np.argsort(-S[i])[:kn]
            votes = Counter()
            for j in idx:
                votes.update({f: S[i, j] for f in pool[j][1]})
            preds.append([f for f, _ in votes.most_common(3)])
            # hybrid: neighbours restricted to the model's first code, if 10+ exist in the top 500
            idx2 = [j for j in np.argsort(-S[i])[:500] if pool[j][0] == m1(c)][:kn]
            if len(idx2) >= 10:
                v2 = Counter()
                for j in idx2:
                    v2.update({f: S[i, j] for f in pool[j][1]})
                same.append([f for f, _ in v2.most_common(3)])
            else:
                same.append(top([("code", m1(c)), ("event", m1(c)[3:]), ("group", dev[c["case_id"]][0])], 3)[0])
        r = [recall(p, c["verdict_findings_in_cause"]) for p, c in zip(preds, cases)]
        r2 = [recall(p, c["verdict_findings_in_cause"]) for p, c in zip(same, cases)]
        print(f"{'RAG: ' + str(kn) + ' nearest ' + index_name:55s} recall {100 * sum(r) / len(r):5.1f}%")
        print(f"{'RAG within model code: ' + str(kn) + ' nearest ' + index_name:55s} recall {100 * sum(r2) / len(r2):5.1f}%")
