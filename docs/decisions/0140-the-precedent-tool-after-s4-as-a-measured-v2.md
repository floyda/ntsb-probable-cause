# 0140 — The precedent tool is built after S4, as a measured second version of the agent

From Andy, 2026-10-03, at the end of S3.1 Task 15. Detail: the design note
`docs/specs/2026-10-03-s3-precedent-tool-design.md` (Draft) and the S3.1 plan's Deviations. This
makes the roadmap's placement of similar-case search ("after S3", §13) specific: after S4.

## Context

1. **What the probes measured.** Precedent used mechanically (the program picks the question,
   combines the answers, and the model never reads the past cases) did not help: "in between" for
   occurrence codes (`docs/results/s3-precedent-probe-dev.txt`), "not promising" for findings under
   both pool readings (`docs/results/s3-finding-precedent-dev.txt`;
   [0138](0138-precedent-pool-whole-for-development.md)).
2. **What they did not measure.** An agent that asks past cases its own questions and judges which
   answers apply. The design note proposes that tool, `search_precedents`, and a test of it: the
   same tool used by the loop's choice against the same tool called by a fixed rule in arm B.
3. **Where the roadmap put it.** Similar-case search is allowed "only as a declared experiment:
   stated before it runs, earlier accidents only, with the retrieval-contamination test", deferred
   to "after S3" (`docs/specs/2026-09-12-architecture-and-roadmap.md`, §10 and §13). The S3
   specification lists it under "Not in S3" (§19).
4. **The options Andy weighed.** Build it before S3.2's held-out claims (renaming S3.2 to make
   room, or a stage named S3.1b), so that the held-out run measures the final loop; or build it
   after S4 and show it as a measured improvement on live cases.
5. **Live predictions take months to score.** The NTSB publishes a verdict when a case closes,
   months after the accident, so the sooner S4 locks predictions, the more of them are scored by
   the time the demo page is shown.

## Decision

1. **The precedent tool is not built in S3.** The design note stays a Draft, to be revised and
   approved as its own specification after S4.
2. **It is built after S4 as the agent's second version (v2).** The agent as S3.2 measures it
   is v1.
3. **Its test is registered before it runs**, in two parts:
   - On development samples: v2 against v1, and the loop with the tool against arm B with the
     same tool called by a fixed rule (the agency comparison).
   - On live cases: v1 and v2 both predict the same open cases, both locked before the NTSB
     publishes (S4's machinery), and the NTSB's verdicts score them head to head.
4. **S3.2's held-out claim measures v1 only.** A held-out measurement of v2 needs its own decision
   record before it runs, because held-out cases are touched rarely.
5. **Its development work reads the whole pool** (0138), and the retrieval-contamination test is
   written with the tool.

## Why

1. **The demo page comes sooner.** S3.2, S3.3, S4 and S5 are not held back by a new capability
   whose value is still a hypothesis.
2. **The live head-to-head is the most falsifiable test available.** Both versions' predictions
   are locked before the answer exists, and the NTSB scores them. The page can show the loop being
   improved by measurement, which is the project's argument about agency.
3. **S3.2's claim stays clean.** It measures the loop that was built and frozen, with no
   late-added tool tuned on the same development samples.

## What this rules out

- **Building it before S3.2 (a stage named S3.1b, or S3.2 renamed).** The strongest case: S3.2's
  held-out run, done once, would measure the final loop, and if precedent is what lets the loop
  beat the fixed pipeline, the headline claim would include it. Its cost: about a week or more
  before S3.2 starts, fewer scored live predictions by demo time, and, for renaming, changing a
  stage name that several append-only records use.
- **Building it inside S3.1.** It would mix tuning with a new capability
  ([0139](0139-s31-tuning-closes-without-a-registered-round.md)).
- **Dropping it.** The model-questioned version has not been measured; the probes measured the
  mechanical version only.

## Status

Accepted, 2026-10-03 (Andy: "I want to go with option B, it gets me to a demo page sooner ...
Plus it would be nice to display how the loop is improved and the measured approach to agency").

## Glossary

- **v1 / v2**: the agent as S3.2 measures it, and the agent with the precedent tool added.
- **Mechanical precedent**: the program picks the question and combines the answers; the model
  never reads the past cases.
- **Head to head**: two versions predicting the same cases, scored against the same verdicts.
- **Retrieval-contamination test**: tests proving a search tool can never return a case it must
  not.
