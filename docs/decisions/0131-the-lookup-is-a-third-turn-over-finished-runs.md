# 0131 — The lookup is a third turn in arm B's conversation, run as a pass over finished checked runs, with a closed list of one to five findings

## Context

Arm B answers in two turns (0025), each sending the full evidence and docket: a median of about
27,000 prompt tokens for the pair, $0.0030 a case at batch prices (ad-hoc, Round 3's run). The
ordering check runs afterwards as a pass over the finished run (0096), in a short separate call
of about 800 tokens that sees no docket.

The lookup's value lies in choosing between table lines using the evidence: "landing flare,
incorrect use" against "not attained"; "pilot" against "student pilot". A finished run keeps the
parsed final answer and a fingerprint of the evidence it saw, not the raw text of turns 1 and 2.

The NTSB flags one finding in 17% of `dev-400` cases, two in 35%, three in 24%, four or more in
25% (ad-hoc). The model gives 1.7 a case.

## Decision

1. The lookup is **turn 3** of arm B's conversation, run as a pass over a finished, checked
   run, writing a derived folder `<run>-lookup-<way>`, like the check. Turns 1 and 2 and the
   check are unchanged.
2. Turn 3 sends the evidence rebuilt through `split_record` and the docket attachment, refused
   case by case unless its fingerprint equals the one the run recorded; the model's earlier
   answer rendered as JSON from the stored record, stated as such in every derived run; the
   checked first occurrence code; the table (0130) and, in the memory way, the memory lines
   (0132); and a committed instruction file.
3. The model revises **findings only**, choosing **one to five** from a **closed list**: the
   table's lines, the memory lines and its own findings from turns 1 and 2. Codes outside the
   list are rejected; one retry, then the earlier findings stand with a note.
4. Batch price, the agent's model and reasoning level, the 8,000-token reply budget. Cached
   tokens are recorded on every call; estimates assume none.
5. The pass refuses, before any spend: anything but a checked development arm B run; any
   `dev-seal-400`, held-out or open case; an existing folder; a memory from another model or
   reasoning level.

## Why

1. **Only a turn that sees the evidence can choose between lines on the evidence** (Andy's
   choice: "There will be cached reads in that so A2 isn’t al bad, let’s go with that").
2. **It is the S3 tool's shape**: in the loop the table would arrive as a tool result in a
   conversation that already holds the evidence (0134).
3. **A pass over finished answers keeps the comparison paired**: with and without the lookup
   start from identical answers, so a whole run's variation does not hide the effect. It also
   runs on existing runs, with no new arm B run.
4. **The closed list keeps it a lookup**, not a second analysis, and every line is a full code,
   so no item turn is needed.
5. **One to five, not a fixed count** (Andy: "maybe 1 to 5 and see if it stops under giving"):
   the count is measured, and the test is count-matched (0133), so giving more earns nothing by
   itself.

## What this rules out

- **A separate short call without the docket** (about $0.20 a `dev-400` pass against $0.60).
  Cheaper; rejected because it chooses blind wherever the model's narrative left out the
  deciding fact.
- **The table folded into turn 2.** No extra call. Rejected: it would key the table on the
  unchecked code and need a new arm B run per test, whose run-to-run variation (checked top-1
  26.6%–31.3% across `dev-400` runs) would hide the effect.
- **A fixed count (one to three, or three to five).** Comparable to the baseline's three.
  Rejected by Andy in favour of measuring whether the table cures under-giving.
- **Codes outside the list.** Rejected: a second analyst, not a coding lookup.

## Status

Proposed, 2026-09-29, with the S2.8 specification; accepted when Andy approves it (Andy chose the
placement and the count in the design session, quoted above).
