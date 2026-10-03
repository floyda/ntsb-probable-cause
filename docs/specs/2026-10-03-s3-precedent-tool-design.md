# S3.1 — A precedent tool the agent questions: design note

Status: Draft, 2026-10-03. Nothing here is built. Decision
[0140](../decisions/0140-the-precedent-tool-after-s4-as-a-measured-v2.md) places the tool after
S4, as the agent's second version (v2); this note is revised and approved as that stage's
specification then. The S3.1-specific parts below (§5 and §6) are kept as first written, for the
record.

## 1. Why

Investigators code a new accident with years of earlier cases in mind. The loop sees earlier cases
only as counts (`occurrence_usage`, `past_findings`, `suggest_codes`). Two probes tested
**mechanical** precedent, where the program chooses the question and combines the answers, and
neither helped:

- **Occurrence codes:** "in between" by its committed rule (`docs/results/s3-precedent-probe-dev.txt`).
- **Findings:** "not promising": the five nearest cases' commonest finding set recovered less than
  the loop's own findings (`docs/results/s3-finding-precedent-dev.txt`).

Neither tested what an investigator does: ask a specific question, read the cases that come
back, and judge which apply. On the precedent reading page, a careful reader could pick the right
code out of the five in about 6 of the 10 cases where it was there; a vote could not (Controller's
reading, not a measurement).

The question this note answers: **given a precedent tool it can question in its own words, does
the agent's choosing do better than the same tool used by a fixed rule?** That is a direct test of
agency (decision [0022](../decisions/0022-loop-must-beat-call-every-tool-arm.md)): the same tool
for both arms, chosen by one and fixed for the other.

## 2. The tool

`search_precedents(question, phase_group=None, occurrence=None)`, offered in the coding step
beside the four coding tools.

- **`question`**: free text, in the agent's words: what it wants to know. Examples:
  - "stall on final approach: does the NTSB code the stall first, or loss of control?"
  - "student pilot loses directional control on landing: which findings are flagged?"
  - "fuel contaminated but tanks low: what did the NTSB conclude?"
- **`phase_group`** (optional): limits the search to pool cases whose phase-of-flight group is
  the one given.
- **`occurrence`** (optional): limits it to pool cases whose occurrence sequence holds that
  six-digit code.
- **Returns** up to five pool cases, ranked by BM25 over their NTSB probable-cause sentences
  against `question` (the search index the precedent probe built and reviewed). For each: its
  event year; the NTSB's probable-cause sentence; its occurrence codes in order, with labels; its
  cause findings, with labels. No case number. The sentence passes through the attach step's name
  replacements, with that case's own record (as the precedent reading page does).
- **Pool**: the S3 statistics pool. In development work, the whole pool less the judged case's
  event date; in held-out and live use, every pool case is earlier anyway
  ([0138](../decisions/0138-precedent-pool-whole-for-development.md)). Never `dev-400`, a sealed
  sample, a held-out or an open case.
- **Budget**: counted inside the coding step's existing limit of six calls, so a run costs about
  what it does now plus the returned text (about 1,000 tokens a call).
- **Logged**: each call's question, filters and the returned cases' codes go into the trail, so
  the live page can show "the agent asked … and read these past cases".

## 3. The two arms

- **Arm C (the loop)** decides whether to call the tool, what to ask, which filters to use, and
  what to make of the answer.
- **Arm B (the fixed pipeline)** calls it once in its tools step (spec §7.1 part 2), after the
  four coding tools, with its own probable-cause sentence as the question and no filter: the
  findings-from-precedent probe's search, given to the model to read. Its one more answer (part 3)
  sees the result.

## 4. What changes in the rules

1. **Other cases' cause text reaches the model.** Until now, coding tools return "codes, labels
   and counts only, never case text" (S3 spec §5.1). This tool returns earlier cases' probable-cause
   sentences and codes. The judged case's own synthesis and verdict stay withheld exactly as now:
   they are never in the pool. A decision record states this and the guard.
2. **Similar-case search moves into S3.1.** The roadmap (§10, §13) places it "after S3", as a declared
   experiment. This brings it forward into S3.1's tuning rounds, declared and registered. A decision
   record states the scope change.
3. **The retrieval-contamination test** (roadmap §9) becomes real: tests prove the tool can never
   return the judged case, a case on its date, a `dev-400`, sealed, held-out or open case.

## 5. How it is measured

1. **Pilot, 20 development cases, standard price** (about $0.30). Read the trails: does the agent
   ask questions about what it is unsure of, and does it use what comes back? No number from it is
   cited. If the questions are poor, stop here.
2. **Round on `dev-400`**, registered before it runs (S3 round template): the loop with the tool
   against noise-floor run a, read by the S3 rule ([0136](../decisions/0136-s3-rounds-count-failed-cases-as-wrong.md)).
   Cost about $2–3, about three hours. The registration names its measures and prediction before
   the run, including how findings are read (see §6).
3. **The agency comparison**, beside it: arm B with the tool (its tools step re-run over the same
   answer run, about $1), paired against the loop with the tool. Same tool; chosen against fixed.
4. **If the round is dropped,** it counts as the first of the two dropped rounds that end S3.1's
   tuning (plan Task 15).

## 6. Open questions for Andy

1. **Filters.** Phase group and occurrence code, or the question only? Filters let the agent ask
   sharper questions ("only stalls on final"); without them it relies on its wording.
2. **What comes back.** Occurrence codes and findings both, or findings only? Both cost more text;
   occurrence codes are where the NTSB is least consistent.
3. **The deciding measure.** Round readings decide on occurrence top-1, with finding recall as a
   do-no-harm measure. If this round targets findings too, its registration must say which measure
   decides, before it runs.
4. **Arm B's fixed question.** Its own probable-cause sentence (as the probe did), or its evidence
   narrative? The probe found the cause sentence the better query.

## Glossary

- **Precedent**: an earlier, closed NTSB case whose verdict the agent may read. Never the case
  being judged.
- **Mechanical precedent**: the program picks the question and combines the answers; the model
  never reads the past cases.
- **Declared experiment**: a change registered in writing, with its prediction, before it runs.
- **BM25**: a keyword ranking that scores how many telling words a past cause sentence shares with
  the question.
- **Retrieval-contamination test**: tests proving a search tool can never return a case it must
  not.
