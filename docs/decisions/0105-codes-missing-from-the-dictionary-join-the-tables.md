# 0105 — Six codes the NTSB uses, missing from its data dictionary, join the code tables

Amends [0025](0025-scoring-targets-from-ntsb-code-tables.md) item 1. Everything else in 0025 is
unchanged.

## Context

0025 item 1 builds the code tables the model chooses from out of the NTSB data dictionary in
`avall.zip`. S1 found that the NTSB uses some codes the dictionary does not list
(`docs/results/s1-code-tables.txt`): the defining occurrence code cannot be composed from the
tables in 204 of 13,560 development cases (1.50%) and 77 of 4,241 held-out cases (1.82%). The
missing parts, by case count over both splits, are phase 553 (135 cases), phase 601 (113), and
events 850 (20), 284 (5), 282 (4) and 281 (4). The model can never be right on those cases,
however well it reads the evidence.

On 2026-09-28, Andy's hand-read in S2.7 showed the NTSB placing events on phases of transition.
One of those phases, "Landing-aborted after touchdown" (553), is among the missing ones. On
`dev-400`, 4 cases have a defining code the model cannot choose (two under 553, two under 601),
and the missing codes appear 23 more times later in the NTSB's sequences, in 19 cases in all (ad-hoc counts on
Round 3's run).

The NTSB's own case records name every one of these codes: each occurrence carries its phase
and event labels (`eventTier1Name`, `eventTier2Name`) beside its code. 0025 item 1 already reads
phase labels "from occurrence labels in the same public dataset" where the dictionary lacks
them.

## Decision

1. The code tables gain two phases and four events, with the labels the NTSB's records give
   them, read from development-split records only (event dates 2010–2019):

   | code | table | label |
   |---|---|---|
   | 553 | phases | Landing-aborted after touchdown |
   | 601 | phases | Autorotation |
   | 281 | events | Course deviation |
   | 282 | events | Altitude deviation |
   | 284 | events | Wrong surface or wrong airport |
   | 850 | events | Medical event |

2. They live in their own committed file, `src/ntsb_probable_cause/scoring/tables/supplement.csv`.
   The five dictionary tables `scripts/build_code_tables.py` writes are unchanged, and
   `scoring/codes.py:load_tables` merges the supplement into them. A supplement row never
   replaces a dictionary label (tested).
3. The prompt version moves from `s1-v5` to `s1-v6`, because the tables the prompt shows change.
   The prompt text is unchanged.
4. The fix applies to every run from S2.7's Round 5 onward. It is a correction, not coding
   guidance, so it is not read under decision 0098 item 4 and a dropped round does not remove it.
   Round 5's registration states that its run includes the fix and its reference does not, and
   its result reports the affected cases separately.
5. The three finding parts the dictionary also lacks (modifiers 27 and 98, item `01011100`,
   about 60 flagged findings over both splits) are not added here. They are left for S2.7's
   finding rounds, or a later record.

## Why

1. **Andy's choice**: "Ok let's go with option A otherwise it will be forgotten", against keeping
   the fix inside Round 5's guidance (B), which a dropped round would remove, or waiting until
   after S2.7 (C).
2. **A gap in the options is not a coding habit.** No guidance can make the model choose a code
   it is not shown. The fix removes a ceiling; it does not teach anything.
3. **The labels are the NTSB's own.** They come from the same public records the scoring reads,
   as labels beside codes, not from any case's text. No held-out record was read.
4. **A separate file keeps the dictionary tables reproducible.** Re-running
   `build_code_tables.py` still writes exactly what the dictionary holds, and the supplement
   stays visible as a departure from it.

## What this rules out

- **Keeping the fix inside a guidance round.** A dropped round would remove it (option B).
- **Waiting until after S2.7.** The sealed run would use tables that cannot express about 1.5% of
  cases (option C).
- **Writing the six rows into the dictionary CSVs.** The next rebuild from `avall.zip` would lose
  them without a word.
- **Adding codes the NTSB's records do not use.** Only codes found in use, with the NTSB's own
  labels, are added.

## Status

Accepted, 2026-09-28 (Andy: "Ok let's go with option A otherwise it will be forgotten").
