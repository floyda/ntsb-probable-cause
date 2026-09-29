# 0133 — The model must beat the count-matched plain table on two answer sets; memory must then beat the model; spend in order; a $10 line; four predictions

## Context

The plain table alone finds about three times as many flagged findings as the model (0130).
Crediting the model step with a gain over "no lookup" would credit it with the table's work.
Finding recall rises with every finding given and precision falls, and the step lets the model
give one to five (0131). Two identical `dev-400` runs differ in finding recall by −0.9%
[−2.6%, +0.8%]; per-case spreads of 17–25 points put the smallest gain `dev-400` can reliably
show at about 3 points (ad-hoc, `scripts/exploratory/s28_design_grounding.py`). S2.7 found that one
pair of identical runs understates how much results move (Round 4's note).

## Decision

1. **Four ways**, on the same answers of one checked `dev-400` run: no lookup; the plain table at
   the model's count on each case; the model with the table; the model with the table and memory.
2. **Two answer sets**, both existing checked runs: S2.7's final setup's run and the run before it
   in the kept line. No new `dev-400` arm B run.
3. **Deciding score**: flagged finding recall, exact to ten digits, paired.
4. **The model step is kept** if its gain over the count-matched plain table has a lower interval
   bound above zero on both sets; otherwise the plain table goes forward if it beats no lookup on
   both; otherwise nothing. **Memory is kept** if it beats the model step by the same test.
5. **In order**: the model step runs first on both sets. Memory's runs and the memory way run only
   if the model step is kept.
6. **Registration**: `docs/rounds/s28-lookup.md` is committed before the first paid pass; the pass
   refuses without it.
7. **A $10 stage line**, counted by commit from S2.8's first commit; the monthly budget applies
   separately.
8. **Four predictions**, published whichever way they come out:
   - P1: with the table in view, the model gives 2.5 to 3.5 findings a case on average (1.7
     today);
   - P2: the model with the table beats no lookup by at least 15 points on both sets;
   - P3: it beats the count-matched plain table by less than 3 points on each set;
   - P4: memory adds less than 2 points over the model with the table.

## Why

1. **A model must beat the free rule** (0096's principle): a call costs money and a transport,
   and has to earn its place over a table.
2. **Count-matching** stops either side winning by giving more; at equal counts recall and
   precision agree.
3. **Two sets** catch a lucky gain; existing runs make the second set cost only the pass (Andy:
   "Can we run it on top of an existing run since we are adding a turn?").
4. **In order** spends on memory only when the step it adds to has earned its place; a failed
   first step stops at about $1.20.
5. **Predictions written first** are the project's habit (0022, 0098).

## What this rules out

- **Kept if it beats no lookup.** Almost certain to pass; rejected because it credits the model
  with the table's gain.
- **One answer set.** About $1.20 cheaper across both ways; rejected on S2.7's evidence that runs
  move more than one pair shows.
- **A new repeat run as the second set.** About $1.20; unnecessary once the step is a pass over
  existing runs.
- **Memory tested regardless of the step's outcome.** Would spend on a memory for a step that is
  not going forward.

## Status

Proposed, 2026-09-29, with the S2.8 specification; accepted when Andy approves it. Andy chose the
rule and its order ("Let's just get it done", after the order was proposed); the predictions are
Claude's, proposed for his sign-off.
