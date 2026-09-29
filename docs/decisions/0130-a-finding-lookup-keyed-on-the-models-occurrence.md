# 0130 — A finding lookup: the NTSB's past flagged findings as pool counts, keyed on the model's checked first occurrence code

## Context

Arm B finds about one in nine of the findings the NTSB flags as part of the probable cause
(finding recall@10 10.4% on B-v1, `docs/results/s26-armB-v2-dev.txt`), while the no-model
baseline finds about one in five on held-out cases (23.2%, `docs/results/s1-bars.txt`). The
model's errors are conventions, not rare codes: it almost never gives "Aircraft control / Pilot",
the NTSB's commonest flagged finding, and it gives 1.7 findings a case where the NTSB flags 2.8
(ad-hoc, `scripts/exploratory/s28_design_lookup_keys.py`).

A design-session measurement (ad-hoc, same script and
`s28_design_examples_and_retrieval.py`, three `dev-400` runs) found that a plain table — the
pool's three most often flagged findings for the model's own first occurrence code — reaches
about 34.5% recall with no model call. Keyed on the phase group alone it reaches 30.0%; keyed on
the NTSB's true code (a cheat) 39.7%. Richer keys (weather, engine type) and retrieval of the
nearest past cases by text reached 34.6–36.6%. Every data-only method lands between 34% and 37%.

S2.7's ordering check (0096) already gives the model occurrence counts for its candidates.

## Decision

1. S2.8's lookup is for **findings only**. The occurrence answer stays S2.7's.
2. It holds **plain counts** from the statistics pool of 0094: for each defining occurrence
   code, event suffix and phase group, the number of pool cases and the flagged findings most
   often in their probable cause. `scripts/finding_stats.py` builds it once, codes and counts
   only, reusing 0094's pool and refusal.
3. A case's **key** is the model's first occurrence code **after the ordering check**, falling
   back to its event, then its phase group, then the whole pool, wherever fewer than 20 pool
   cases match.
4. A case's **table** is the key's eight most often flagged findings, each a full ten-digit code
   with its label and "flagged in K of N past cases". A line is called a habit only under 0101's
   rule (at least 60% of at least 20 cases); otherwise it is a count, and the evidence decides.
5. No case text, no worked examples, no retrieval of similar cases (0098 item 2). Retrieval is
   written down as a candidate declared experiment for S3 (spec §11).

## Why

1. **Findings are where the loss is**: 11% against a table's 34.5%, and occurrence already has
   its check.
2. **Plain counts are within about 2 points of every alternative measured**, the easiest to
   audit, and carry no case text anywhere.
3. **The key is the model's own claim**, so the table says "if you are right that it is X, the
   NTSB usually flagged Y". That avoids S2.7's Round 4 trap, where counts rested on what the NTSB
   would code. Its cost, a wrong occurrence looking up the wrong findings, is measured: about 5
   points against the cheat key.
4. **Eight lines** keep most of what a perfect chooser could reach (55%, against 49% at five and
   58% at ten, ad-hoc) without a long list.

## What this rules out

- **Occurrence and findings in one lookup.** One tool for S3. Rejected because the occurrence
  half repeats S2.7's check, and two changes to occurrence in one stage could not be told apart.
- **The phase group as the key.** It cannot inherit a wrong guess and could be a start fact in
  S3. Rejected: about 4.5 points weaker, and it ignores what the model concluded.
- **Similar-case retrieval (RAG) now.** About 2 points better than the table, ad hoc, within what
  `dev-400` can show; it needs other cases' narratives as an index, which the roadmap allows only
  as a declared experiment with its own contamination test.
- **Fatal / non-fatal in the key.** Under a point, ad hoc.

## Status

Proposed, 2026-09-29, with the S2.8 specification; accepted when Andy approves it. Andy chose the
plain counts with a memory (option E, recorded in 0132): "Let's go with E, now we don't need to
pay for the model transcribing we have a bit more room to play with."
