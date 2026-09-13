# 0013 — Evidence, synthesis and verdict: the factual narrative is withheld and the agent writes its own

**Amends 0006** (adds an evidence-narrative field to the output). **Replaces the spike's
evidence/answer field roles**, and with them the narrative router and the narrative slices
in `docs/specs/2026-09-12-architecture-and-roadmap.md`.

## Context

The spike split each record into evidence (sent to the model) and answer (withheld). The
factual narrative was evidence. The spike's headline result followed from that: 88% top-1
on cases with a factual narrative, 12% on cases without one, so the roadmap routed cases
with a narrative down a cheap single call.

Andy's point in the S0 design session: the factual narrative is not raw evidence. An
investigator writes it at the end of the investigation, as a summary of everything found,
and it is directed toward the probable cause they have reached. The agent being built runs
on live investigations, where no factual narrative exists yet; its job is to write that
narrative from the evidence, and then determine the cause.

Measured while designing the leakage guard (`scripts/exploratory/s0_design_measurements.py`,
development split): 1,999 cases contain the whole analysis text inside the factual
narrative (M5); all 6,126 C-class cases are `Basic (no factual)` reports that still carry a
"factual" narrative, 62% of which duplicate the analysis (M7). In those cases the spike's
roles put the same text on both sides of the boundary.

## Decision

Each field has one of three roles:

- **Evidence** — observations: aircraft, engine, pilot certificate and hours, weather and
  METAR, injury level, phase of flight, preliminary narrative, and (S2) docket evidence
  documents. Sent to the model.
- **Synthesis** — the investigator's write-up: factual narrative, analysis narrative. Not
  sent. The reference against which the agent's own narrative is compared.
- **Verdict** — probable cause, occurrence codes, finding codes. Not sent. Scored by exact
  match.

Evaluation gives the agent a closed case's record without synthesis or verdict, plus the
docket as it stands at closure. The agent's output gains an **evidence narrative**, written
before its probable cause. Grading it is decided in S1, together with the lay explanation.

## Why

1. **It evaluates the task the live agent will do.** Live cases have no factual narrative.
   An evaluation that supplies one measures a different task, however good the number.
2. **It removes an ambiguity the data forces.** Where the NTSB duplicated analysis text
   into the factual field, the old roles made one paragraph both evidence and answer.
3. **It makes the case for an agent stronger, not weaker.** Every case now needs the
   docket, not half of them.

## Consequences

- The narrative router is removed; every case takes the docket path.
- The spike's 57% one-shot ceiling is no longer a reference; the nearest precedent is its
  12% on 16 cases without a narrative. S1 measures the new ceiling and sets the bars.
- Slices by narrative presence are replaced; investigation class is proposed (S1).
- Cost per case rises; the £0.05 cap is re-measured in S1 and S3.
- The main leakage risk moves to the docket, which can contain NTSB-written factual
  reports. S2 filters documents by type and title and measures the filter.
- Held-out scores differ from live in both directions: complete dockets, but no
  preliminary narrative (the API deletes it at closure; 0 of 13,560 development cases,
  M4).

## What this rules out

- **Keep the spike's roles.** Like-for-like with the spike's numbers, and a cheap path for
  about half of cases. Rejected because it evaluates reading an investigator's summary,
  which the live agent never has.
- **Withhold only the factual narratives that duplicate the analysis.** Keeps most
  narratives. Rejected because it defines evidence by a similarity threshold, and because
  an independent factual narrative is still synthesis.

## Status

Accepted, 2026-09-13.
