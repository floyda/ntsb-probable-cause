# 0209 — A lesson's finding categories are alternatives, and the 2010 lessons are recounted

From Andy, 2026-10-16 ("recount first as you recommend"). Detail: the lookup plan
`docs/plans/2026-10-16-coding-memory-lookup.md` and its Deviations; the pilot plan's Deviations,
2026-10-16.

## Context

1. **The support count asked too much.** `curate.agrees` counted a lesson as fitting a case only
   when every finding category the lesson names was flagged in that case. The learner writes
   categories as alternatives ("the power plant, ignition, fuel or oil system"), and its
   instructions never said which reading was meant. A lesson naming twelve alternatives could fit
   no case.
2. **What it changed in the pilot**, recounted on 2026-10-16 from the 2010 finish step's saved
   answers (no call; figures from `docs/results/memory-recount-dev.txt`):
   - Of the 106 lessons that apply to at least 10 cases, the median fit was 0% under the old rule
     and 48% when one flagged category is enough. Their first codes matched about half the time
     all along (median 50%, over the 103 that predict a first code).
   - On the final support, 101 of those 106 disagree more than they agree by the old rule, the
     test that sends a lesson back to the learner; by the corrected rule, 54 do. The finish step
     revised 104 lessons (`finish.json` of the 2010 run).
   - The cap ranks by agreements, so it kept lessons that name few categories, not the best ones.
   - Every rendered lesson showed its count ("agrees in 9"), so the coding model read good lessons
     as unreliable.
3. **The pilot's verdict was read as registered** (`docs/results/memory-pilot-dev.txt`). Its memory
   was ranked, revised and labelled by the faulty count.

## Decision

1. **One flagged category is enough.** A lesson agrees with a case when the case's first
   occurrence code is one it predicts (if it predicts any) and at least one finding category it
   names is flagged (if it names any).
2. **Each part is counted on its own.** Support also records how often the first code was one of
   those predicted and how often at least one listed category was flagged, and a lesson shows both
   counts in place of the single agreement count.
3. **The 2010 lessons are recounted, not relearned.** A script rebuilds the 2010 finish step's
   final apply answers from the run's saved replies, refusing unless every rebuilt request matches
   a saved one, counts support by the corrected rule, applies the 6,000-token cap, and saves a new
   snapshot, `pilot-2010-recount`, checked and stamped like any other. The lesson texts are the
   ones `pilot-2010` holds.
4. **Saved snapshots are not rewritten.** `pilot-2009` and `pilot-2010` keep their counts and render
   as they were read, so the pilot's runs stay reproducible. The pilot's verdict stands as read.
5. **`finish` keeps its final apply answers** (`applies.json` in the run folder), so a later count
   needs no rebuild.

## Why

1. **The learner's lists are alternatives in practice.** Well-used lessons name up to twelve
   categories, the median three (`docs/results/memory-recount-dev.txt`); no reading in which all must hold is one a lesson could meet.
2. **Recounting is free and exact.** The replies are on disk; nothing is sent, and the check
   against the saved request keys proves the rebuilt answers are the ones Sonnet gave.
3. **Relearning waits for a reason.** It would cost about $20–35 of plan credit, judged by the
   pilot's learner spend of $33.1308, before the lookup test (0210) shows whether the lessons help.

## What this rules out

- **Relearning 2009 and 2010 with the corrected rule now.** Rejected by Andy for now: see Why 3.
  The recounted lessons are still the ones the faulty rule sent into revision.
- **Correcting `pilot-2009` and `pilot-2010` in place.** Rejected: it would change what the pilot's
  runs read after the fact.
- **Asking the learner to mark lists as "all" or "any".** Not now: it changes the learner's
  instructions, which only a relearn would use.

## Status

Accepted. Amends the counting step of the design note's §4 (step 3) and 0201's cap ranking, which
now ranks by the corrected count.
