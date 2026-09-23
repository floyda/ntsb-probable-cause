# 0077 — Analysis-narrative sentences in docket documents reach the agent and mark the case

Extends [0050](0050-tripwire-skips-factual-narrative-sentences-in-docket-documents.md) from the
factual narrative to the analysis narrative, for the `docket_documents` role only. Revisits the
refusals [0056](0056-the-deny-list-cannot-be-filled-from-titles.md) item 3 accepted.

## Context

After 0050 the tripwire still refuses a case when a docket document shares a sentence with the
analysis narrative. Measured on `dev-400` (`docs/results/s2-docket-leak.txt`): 36 analysis
sentences in 17 cases, and 3 probable-cause sentences in 1 of those 17. The matches sit in
witness statements and records of conversation (7 cases), wreckage and site examinations (3),
specialist reports (2), and one each in five other kinds (`docs/results/s2-threshold.txt`).

0050's argument was the direction of copying: the investigator writes the factual narrative from
the docket. The analysis narrative is written from the docket too. A wreckage examination that
reads "Examination of the engine revealed no mechanical anomalies that would have precluded
normal operation." is routinely pasted into the analysis word for word.

Andy's position, and 0038's principle: the agent gets what the analyst had. A document refused
for having been important enough to quote is the opposite.

## Decision

1. In the `docket_documents` role, a sentence shared with the analysis narrative reaches the
   agent unchanged, and the case is **marked** `analysis_sentence` with the count.
2. A probable-cause sentence, an occurrence or finding code, or a whole withheld text in any
   document still refuses the case.
3. A mark is written to logs and results, never into the agent's text; marked cases are
   reported as their own group beside every result.
4. **Adopted only after a hand-check.** Andy reads each of the 36 matched sentences beside its
   document title and marks it *quotes evidence* or *conclusion in the docket*. If 5 or fewer
   are conclusions, this record takes effect and that count is published as its measured error.
   If more, it returns to Andy before any model run, with a neutral marker for such sentences as
   the fallback. The sheet holds withheld text and is never committed; counts are published.

## Why

1. **0050's argument applies with the same force.** The analysis is written after, and from,
   the evidence.
2. **The answer itself stays protected.** No direction-of-copying argument covers the probable
   cause or the codes.
3. **A marker in the text would leak.** It would tell the agent the NTSB leaned on that sentence,
   and a live case, whose report is not written yet, could never carry one.

## What this rules out

- **Removing the sentence silently.** First proposed in the design session; rejected by Andy as
  against 0038 and 0050.
- **A marker naming the source.** Nearly the answer.
- **Adopting the rule on the document-type argument alone.** That argument reads titles, which
  0056 found unreliable; the hand-check reads the sentences.

## Status

Accepted, 2026-09-23 (Andy: "yes thats much more like it"), conditional on item 4.
