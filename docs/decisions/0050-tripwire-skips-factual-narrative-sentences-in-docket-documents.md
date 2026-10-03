# 0050 — In docket documents, the tripwire skips sentences from the factual narrative

Extends [0019](0019-tripwire-skips-sentence-check-on-weather-report.md), which made the same
exemption for the `weather_metar` evidence role, to the `docket_documents` role. The guard
itself (decision 0016, check 4) is unchanged; this record only adds one pair to its exemption
constant.

## Context

`MIN_SENTENCE_CHARS = 20` was measured in S0 over the record's own fields
(`docs/results/s0-corpus-scan.txt`), before any docket text existed. S2 attaches docket
documents as evidence, which puts a large new body of text under the same tripwire.

It fires hard. Measured over the whole development sample with every readable document
attached — not only the subset the cost cap admits, because the S3 loop may read any document
(`scripts/docket_leak_scan.py`, `docs/results/s2-docket-leak.txt`, 401 cases):

| | cases | matches |
|---|---|---|
| tripwire fires, as the guard stands | **156 of 401 (38.9%)** | 1,147 |
| by source: factual narrative | 155 cases | 1,108 |
| by source: analysis narrative | 17 cases | 36 |
| by source: probable cause | **1 case** | 3 |
| by source: occurrence or finding codes | 0 cases | 0 |

Every match is in the `docket_documents` role; none in `docket_listing`. Matched fragments run
from 20 to 499 characters, median 79 — real sentences, not boilerplate.

**Raising the threshold is not a lever.** The sweep reaches zero only at 400 characters, which
is a paragraph, not a sentence. Choosing that would disable the sentence check rather than tune
it, and would stop the guard catching the analysis narrative and the probable cause as well.

**The direction of the copying is known, and it is the whole argument.** An investigator writes
the factual narrative at the end of the investigation *from* the docket: they read the wreckage
examination and the records of conversation, then summarise them. A sentence appearing in both
is the narrative quoting the evidence, not the answer reaching the evidence. The guard compares
strings and cannot see direction; we can. This is the same shape 0019 met in the weather field,
where the narrative was quoting the weather observation, at a much larger scale.

Treating these as leaks would refuse 38.9% of cases before they are answered — and would refuse
a document precisely for having been important enough to summarise, which biases the measurement
against the strongest cases.

## Decision

1. For the `docket_documents` evidence role only, the tripwire does not compare **sentences taken
   from the factual narrative**. One more pair in `SENTENCE_CHECK_EXEMPTIONS`
   (`records/guard.py`), citing this record.
2. **Everything else stays compared, everywhere.** In that same role the tripwire still compares
   sentences from the analysis narrative and the probable cause, whole withheld texts, and
   occurrence and finding codes. `MIN_SENTENCE_CHARS` stays 20.
3. **`docket_listing` is not exempted.** Zero matches were measured in it. If a listing ever
   trips the guard, that is something we want to hear about, not something already waived.
4. Whole withheld texts are never exempted by this or any other pair: `find_leaks` applies
   exemptions only to split-out sentences. A whole factual narrative pasted into a document
   still stops the case.

After this change the tripwire fires on **17 of 401 cases (4.2%)**, 39 matches: the 17 cases
whose documents carry analysis-narrative sentences, and the 1 case whose documents carry the
probable cause. Those refusals stand.

## Why

1. **The verdict is still protected, because the guard matches per source.** The exemption names
   one source. The case whose docket holds the probable cause is still refused, as are the 17
   holding the investigators' reasoning.
2. **A 38.9% refusal rate is not a safety property, it is a broken measurement.** Arm B cannot
   be evaluated if two cases in five never produce an answer, and the cases lost are not random.
3. **0019 already settled the principle** on the same evidence: where the direction of copying
   is known and the withheld text is the derived work, the overlap is evidence, not leakage.
4. **The alternative levers were measured and fail.** The threshold sweep is in the results file.

## What this rules out

- **Raising `MIN_SENTENCE_CHARS` to clear the docket matches.** Measured: needs 400 characters,
  which disables the sentence check for every source and role, including the probable cause.
- **Exempting the factual narrative everywhere.** Rejected: the exemption is justified by the
  direction of copying, which is known for docket documents and the weather observation. It is
  not known for an arbitrary evidence field, and 0019 deliberately made it role-scoped.
- **Exempting the docket roles from the tripwire entirely.** Rejected: it would waive the 17
  analysis-narrative cases and the probable-cause case, which are the matches that mean what the
  guard was built to mean.
- **Dropping documents that trip the guard and answering from the rest.** Rejected for now: it
  silently changes what arm B reads on 38.9% of cases, and the drop would correlate with how
  thoroughly a case was documented. Reconsider only with a measurement behind it.

## Accepted gap

A factual-narrative sentence placed inside a docket document passes unseen. Stated as 0019
states its own gap: this is the price of the exemption, and it is accepted knowingly.

## Status

Accepted, 2026-09-20 (Andy, asked whether a sentence shared between a docket document and the
factual narrative should count as a leak: "i would say no").

## Clarification, 2026-09-20 (appended after review; nothing above is edited)

The task review probed the committed guard directly and found that **item 4 above, read as a
backstop, promises more than the code delivers.** It is literally true — an exact, complete copy
of the factual narrative in a docket document still stops the case, as `kind == "text"` — but the
whole-text needle is an exact contiguous substring match on the *entire* narrative. Drop one
trailing sentence, or let PDF extraction insert a single stray character, and that needle no
longer matches; every remaining sentence is then exempt and the near-complete copy passes unseen.

This is not a defect introduced by the implementation, which is faithful to this record. It is
the direct consequence of the exemption, and it is the same gap the "Accepted gap" section
already states — N exempt sentences are still N exempt sentences, whether they arrive one at a
time or nearly all at once. It is written down here so that no later reader takes item 4 for a
safety net it is not.

Two related facts, both verified against the code rather than assumed:

- **Per-source matching holds under adversarial input.** A sentence present in both the factual
  narrative and the probable cause, placed in a docket document, is still caught — as a
  `probable_cause` match. The same is true for a sentence shared with the analysis narrative.
  That is the claim "Why" item 1 rests on, and it survived direct testing.
- **The exemption cannot widen by accident.** Membership is exact tuple matching, so an evidence
  role whose name merely contains "docket" is not exempt, and `docket_listing` is not exempt.

Layer note: `tests/boundary.py` calls `find_leaks` with the same default exemptions, so guard
layer 5 is relaxed by exactly the same amount as layer 4. That is the intended design — one
constant, one policy, no divergence — but for this specific case the layered guard has one fewer
*independent* layer, and decision 0016's "layered" claim should be read with that in mind.

**Extended by [0077](0077-analysis-sentences-in-docket-documents-mark-the-case.md), 2026-09-23**,
which lets analysis-narrative sentences in docket documents reach the agent and marks the case,
on the same direction-of-copying argument, after a hand-check of the matched sentences. The
probable cause and the codes stay fully protected. Nothing in this record changes.
