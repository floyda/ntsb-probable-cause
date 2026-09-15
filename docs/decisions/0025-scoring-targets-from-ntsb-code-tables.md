# 0025 — Scoring targets come from the NTSB's code tables, in two stages

## Context

Decision 0006 said the model picks codes from a supplied list and the headline is exact
match, and it put the occurrence vocabulary at "58 codes". The S1 design measurements
(`docs/specs/2026-09-14-s1-design-measurements.txt`) show what the vocabulary actually is.
An occurrence code is six digits, a phase prefix and an event suffix; the development years
hold 829 distinct primary codes, and listing them with labels would cost about 10,600
tokens per call (M1, M6). A finding code is ten digits in five pairs; the development years
hold 2,928 distinct codes, 1,241 of them seen once, and the list would cost about 75,700
tokens (M2, M6). A pair's meaning depends on the pairs before it, except for tier 1 and the
two-digit modifier, whose 73 values mean the same thing everywhere.

The NTSB publishes its full code lists in the data dictionary inside its public download
`avall.zip`: 1,019 finding items in 130 six-digit categories, 73 modifiers, 94 events, each
with a meaning and a definition (M10). They compose 99.8% of held-out finding codes and
99.5% of held-out occurrence codes. The NTSB also flags each finding as in the probable
cause or not: 84.6% of findings are flagged and 99.0% of cases have at least one (M3).

S0's import boundary allows only the splitter to read `Verdict` and `Synthesis`, with a note
that S1's scoring module would be added by decision.

## Decision

1. The code tables — phases, events, finding categories, finding items and modifiers — are
   built from the NTSB data dictionary and committed as `docs/results/s1-code-tables.txt`
   with the dataset's date. Phase labels, which the dictionary lacks for the post-2008
   scheme, are read from occurrence labels in the same public dataset. No held-out case is
   read to build a table.
2. The occurrence code is composed: the model picks a phase and an event from two short
   tables and the harness joins them. Top-1 is exact match of the six digits against the
   defining event's code. Event match, the suffix alone, is a reported column, never the
   headline.
3. Finding codes are answered in two stages in one answering pass: the model picks
   six-digit categories and modifiers in the answering turn, then picks the eight-digit
   item from each chosen category's official children in a second short turn. The harness
   composes item and modifier. The headline is precision and recall of the ten-digit codes
   against the findings the NTSB flagged as in the probable cause; eight- and six-digit
   columns are reported beside it. `Verdict` gains `finding_codes_in_cause`.
4. The one-shot ceiling of 0022, "every structured evidence role, one call", is read as one
   answering pass of two turns with no tools. In a trail, each step's hypothesis stays at
   stage 1 and the refinement turn runs once at stop, for every arm alike.
5. `ntsb_probable_cause.scoring.metrics`, `scoring.runner` and `scoring.judge` may import
   `records.verdict`; `scoring.judge` alone may import `records.synthesis`. The model
   package still cannot see any of them.

## Why

1. **The tables must fit a call.** Two lists of under a thousand tokens replace a list of
   ten thousand; a 130-row category list plus a short child list replaces one of 75,000.
2. **A public reference beats our own corpus.** The dictionary covers codes the development
   years never used, it comes with definitions, and building it reads no case.
3. **The pairs are a tree, not five choices.** Choosing five pairs independently would
   compose codes with the wrong meaning; the modifier is the one pair that is independent,
   so it is the one chosen separately.
4. **The flagged set is the NTSB's own answer to "why".** Scoring against unflagged
   observations would penalise the model for not repeating context.
5. **Scoring needs the verdict, by definition.** Naming the modules that may see it keeps
   the boundary as narrow as S0 made it.

## What this rules out

- **Ten-digit codes from a single list.** Cannot be presented at the cost cap, and a code
  seen once is not a category a model picks reliably from a list of thousands.
- **Six digits as the headline.** Easier than the NTSB's task and would overstate the
  score; it survives as a reported column with a baseline at the same level.
- **Five independent pair tables.** Rejected on the measurement that 44 of 52 tier-4 values
  change meaning with their path.
- **Tables from the development corpus.** About 4% of held-out finding codes would be
  unreachable, and the choice would need defending every time a new code appears.

## Status

Accepted. Amends 0006 (the vocabulary and the finding granularity) and the wording of the
ceiling in 0022.
