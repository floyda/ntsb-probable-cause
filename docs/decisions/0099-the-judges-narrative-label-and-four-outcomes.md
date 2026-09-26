# 0099 — The judge's narrative label gives four outcomes, validated by Andy's hand-read before it is cited

## Context

A miss is either **understood but miscoded** (the model's account is right, its code is not) or
**misread** (the account itself is wrong or thin). Coding guidance can fix the first, not the
second; reading better (transcription, pictures, S3's loop) can fix the second. The judge
(0028) labels each case's evidence narrative against the factual narrative — `consistent`,
`less_detailed` (0035), `contradicts`, `adds_unsupported_facts` — in the same call as its cause
label. Only the cause label was validated in S1; the narrative label was recorded, not tested
(`docs/results/s1-judge-validation.txt`). And the factual narrative is written toward the
investigators' conclusion, so "contradicts" can mean "framed differently".

## Decision

1. **Four outcomes** per case: right (top-1 hit); understood, miscoded (miss, `consistent`);
   thin evidence (miss, `less_detailed`); misread (miss, `contradicts` or
   `adds_unsupported_facts`). The cause label is printed beside them.
2. The judge runs on B-v1, its Round 0 repeat and B-v2, so that what transcription buys in
   understanding is measured beyond the label churn of two identical runs.
3. **Validation** by Andy's hand-read: about 50 seeded B-v1 cards (8 from each of five miss
   groups, 10 hits), each the model's narrative and code beside the NTSB's probable cause and
   code, blind to the judge, with the factual narrative collapsed. Question: does the model's
   account contain the fact the NTSB's cause rests on (yes / no / can't tell)? `consistent` maps
   to yes, the other three labels to no. The label is **validated** if Andy and the judge agree
   on at least 75% of the cards Andy could decide and the judge errs at least once in each
   direction. Otherwise the four outcomes are printed "unvalidated" and carry no claim.
4. The cards also ask why each miss happened; those counts order the guidance rounds (0098).
   Only counts are committed.

## Why

1. **It separates the two kinds of miss** that S2.7 and S3 respectively exist to fix.
2. **It costs nothing extra**: the label comes with the judge call S2.7 already makes.
3. **Validated against what S2.7 needs it to mean** — the key fact is there — not the judge's
   exact wording.
4. **Andy reads no evidence**: two short texts per card, about an hour in all (estimate).

## What this rules out

- **Reporting the label unvalidated as a finding.** It could not carry a claim, least of all
  in S3, where it would be the loop's clearest test.
- **A separate hand-check for the label.** The same cards answer both questions.

## Status

Proposed, 2026-09-26: written with the S2.7 specification (Andy: "A"; "hopefully i wont have to
read any evidence"). Accepted when Andy approves the specification.
