# 0037 — Every docket document is evidence; the line is the NTSB's case-level write-up

Amends 0013's definition of evidence ("observations") and settles the role of party
submissions, which the roadmap's S2 entry and 0022 left to S2.

## Context

S2's filter sorts every docket document into evidence (the model may read it) or synthesis
(withheld). A **party submission** is a written statement the aircraft manufacturer, engine
maker or operator sends the NTSB near the end of an investigation, arguing for a cause. The
spike's shape probe (`../ntsb-spike/scripts/docket_shape_probe.py`, register A13) found one
in 0.62 of FA dockets, 0.25 of fatal LA, 0.18 of non-fatal LA and none of the CA dockets it
sampled; two of its twelve largest documents were submissions, at roughly 19,700 and 23,000
estimated tokens.

The first proposal was to withhold them as synthesis: they argue a cause, they arrive late,
and they are bulk. Andy's objection: a submission is written evidence or an argument for one
cause, and the NTSB's own analysts weigh it. The agent replaces the analysis step; taking
away an input the analyst has falsifies the process of engineers gathering evidence, rather
than protecting it.

On examination the first proposal did not hold. "It argues a cause" also describes a witness
statement. Late arrival is what the masked condition measures (0023), not a reason to
withhold. Cost is a budget question for arm B's filter (0022), not a leakage question.

## Decision

1. **Every docket document is evidence, whatever its author.** The evidence / synthesis line
   is drawn at the NTSB's case-level write-up: the factual narrative, the analysis narrative,
   the probable cause and the codes are withheld (0013); everything in the docket, including
   party submissions and NTSB specialist reports that contain conclusions, is evidence.
   0013's definition is extended from "observations" to "what investigators gathered,
   including arguments submitted to them".
2. **Every document is rendered with a provenance header**: title, the document type from the
   listing, page count, and the author's role where the listing gives it. Example: "Party
   submission, 22 pages, submitted by the engine manufacturer." The agent is told what kind of
   document it is reading. It is never told the document is wrong.
3. **The tripwire runs on every document** (0016). A submission written after the NTSB's
   factual reports were public may quote a sentence that also sits in the withheld factual
   narrative; the case then fails closed. The number of development cases the tripwire stops,
   by document type, is measured and published.
4. **The value of submissions is measured, not assumed.** On development dockets that hold a
   submission, arm B is run with and without them, and the paired difference is published
   whichever way it comes out. Arm B's filter is then chosen on the whole development
   measurement, as 0022 says; a document type is dropped from arm B only if the numbers say it
   costs more than it gives.

## Why

1. **The agent replaces the analyst, and the analyst reads submissions.** An evaluation that
   removes an input the real analysis step has measures a different task.
2. **Authorship at case level is a line that can be checked.** "Is this the NTSB's own
   narrative or codes" is a fact about a document; "does this argue a cause" is a judgement
   that would also catch witness statements and specialist studies.
3. **Whether the agent is swayed by persuasive prose is a claim about model behaviour.** A
   manufacturer's twenty pages are written to persuade, and the NTSB sometimes disagrees with
   them. Item 4 measures it instead of assuming it either way.
4. **Leakage stays mechanical.** The tripwire, not a role assignment, is what stops quoted
   withheld text, and it fails closed (0016).

## What this rules out

- **Party submissions as synthesis.** Simpler filter, smaller arm B. Rejected: it withholds an
  input the analysis step has, and its reasons (argues a cause, arrives late, is bulk) each
  belong to another mechanism.
- **A third role, "argument", between evidence and synthesis.** Would let a prompt treat
  submissions differently by rule. Rejected: the provenance header already says what the
  document is, and a separate role would need its own guard layer for no measured gain.
- **Dropping submissions from arm B by rule, while the loop may read them.** Rejected as an
  unequal comparison (0022).
- **Assuming the agent discounts a party's interest.** Rejected: item 4 measures it.

## Status

Accepted, 2026-09-17 (Andy).
