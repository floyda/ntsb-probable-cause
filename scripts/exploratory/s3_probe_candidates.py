"""Ad-hoc, free: would a pool suggestion have put the true occurrence code on the agent's list?

Reads the S3 probe's trails (development cases only) and S2.7's pool counts. Prints counts
only -- no case number, no text. A signal for the S3 brainstorm.

Status: exploratory, one-shot learning-probe analysis for S3 (2026-09-29). Output is not a result;
it sets no bar and tunes nothing. Run from the worktree root with PYTHONPATH=.
"""

import sys
from pathlib import Path

from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import NO_GROUP, load_stats
from ntsb_probable_cause.scoring.samples import load_cases
from scripts.s3_probe.trail import CaseTrail

DATA = Path("/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data")
JOB = sys.argv[1]
T = load_tables()
S = load_stats()
GROUP = next(f for f in fields.EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)

trails = [
    CaseTrail.model_validate_json(line)
    for line in (DATA / "probes/s3-probe" / JOB / "trails.jsonl").read_text().splitlines()
]
records = load_cases(DATA / "processed", [t.case_id for t in trails])


def top3(stage):
    return set(stage.hypothesis.occurrence_codes(T)) if stage and stage.hypothesis else set()


def args(t):
    return {c for s in t.coding_steps if s.kind in ("occurrence", None) for c in s.codes}


rows = []
for t, raw in zip(trails, records, strict=True):
    truth = t.true_primary
    if truth is None:
        continue
    group = GROUP.extract(raw)
    group = group if isinstance(group, str) else NO_GROUP
    considered = set().union(*(top3(getattr(t, n)) for n in ("h0", "h1", "h2", "final")))
    h2_events = {c[3:] for c in top3(t.h2)}
    rows.append(
        {
            "in_args": truth in args(t),
            "considered": truth in considered,
            "in_h_all": truth in top3(t.h_all),
            "event_known": truth[3:] in h2_events,
            **{f"pool{k}": truth in S.group_top(group, k) for k in (3, 5, 10)},
        }
    )

n = len(rows)
missing = [r for r in rows if not r["in_args"]]
print(f"cases with a true primary occurrence: {n}")
print(f"true code among coding-tool arguments: {n - len(missing)} of {n}")
print(f"true code in any of the agent's own top-3s (H0, H1, H2, final): {sum(r['considered'] for r in rows)} of {n}")
for k in (3, 5, 10):
    print(f"true code in the pool's top-{k} defining codes for the case's phase-of-flight group: "
          f"{sum(r[f'pool{k}'] for r in rows)} of {n}")
print(f"\nof the {len(missing)} cases where the true code was NOT among the arguments:")
print(f"  in the agent's own top-3s at some stage: {sum(r['considered'] for r in missing)}")
print(f"  in the read-everything call's top-3: {sum(r['in_h_all'] for r in missing)}")
print(f"  true event already among H2's top-3 events (phase wrong only): {sum(r['event_known'] for r in missing)}")
for k in (3, 5, 10):
    print(f"  in the pool's top-{k} for the phase group: {sum(r[f'pool{k}'] for r in missing)}")
reach = sum(r["in_args"] or r["pool5"] for r in rows)
print(f"\narguments or pool top-5 together: {reach} of {n}")
print("pool group sizes are counted over the whole pool (0094); dev-400 cases are not in it.")
