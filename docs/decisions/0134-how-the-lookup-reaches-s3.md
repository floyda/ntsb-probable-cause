# 0134 — How S2.8's result fills S3's coding-lookup tool and arm B's fixed call

## Context

Decision 0022 makes arm B "every tool the loop has, in a fixed order, then one answer", and the
loop must beat it at equal cost; the bar exists before any loop code (0022, reason 3), and is set
after S2.7 (0089). S3's design can start before S2.8's result, but two parts of it depend on
that result. Decision 0023 says every tool result goes through `split_record`, which assumes a
tool returns part of the case's own record; the lookup returns other cases' coding habits as
counts.

## Decision

1. **If the model step is kept** (0133): `coding_lookup` is a tool the S3 loop may call once it
   holds a hypothesis. Its result is the table of 0130 (and the memory lines of 0132, if kept) for
   the loop's current first occurrence code. Arm B's fixed call is then: answer (turns 1 and 2),
   the ordering check, the lookup turn, exactly as S2.8 ran it, and S3's bar and cost per case are
   measured with it.
2. **If only the plain table is kept**: no tool. The table's top lines become a fixed step after
   the answer for every arm alike.
3. **If nothing is kept**: no tool and no step; arm B is as S2.7 leaves it.
4. **The lookup's result is not evidence about the case.** It is kept apart from evidence
   payloads, as the conversation keeps the agent's own output apart, and the provenance check does
   not count it as evidence. S3's tool design records this as an explicit exception to 0023.
5. **The live table's pool** holds only cases closed before the prediction was made. Whether
   held-out years or closed open-split cases may join it (open-split only as numbers, 0024), and
   whether a live memory is built from resolved predictions, each need their own decision before
   the board uses the tool.

## Why

1. **Slots written as conditions** let S3's design start now without being amended by a negative
   S2.8 result.
2. **A tool only where there is a choice**: if the model adds nothing over the table, a loop that
   "chooses" to call it is a pipeline in costume, the thing 0022 exists to catch.
3. **Arm B mirrors the tool exactly**, so the loop is compared with the fixed version of the same
   tool.
4. **Counts are not the case's evidence**, and treating them as such would blur the provenance
   check that the leakage guard rests on (0016).

## What this rules out

- **Deciding S3's tool list before S2.8's result.** Faster; rejected because a negative result
  would force amendments, and the bar must exist before loop code.
- **The lookup as a tool whatever the result.** More for the loop to do; rejected by reason 2.
- **Passing the table through `split_record`.** One path for every tool; rejected because the
  splitter's roles describe the case's record, and this is not part of it.

## Status

Proposed, 2026-09-29, with the S2.8 specification; accepted when Andy approves it. Written on
Claude's recommendation after Andy asked for the design to be finished ("Let's just get it done,
there won't be spend on the agent for a while until have evals setup").
