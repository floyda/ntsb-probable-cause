# 0054 — The party-submission comparison is retired: the population cannot be identified

Retires [0038](0038-docket-documents-are-evidence-by-case-level-authorship.md) item 4, which
requires arm B to be run with and without party submissions and the paired difference published.
Removes the `no-submissions` run variant that existed to serve it.

## Context

0038 item 4: *"The value of submissions is measured, not assumed. On development dockets that hold
a submission, arm B is run with and without them, and the paired difference is published whichever
way it comes out."* A party submission is an account written by an organisation the NTSB admits to
the investigation — the manufacturer, the operator, the engine maker. It is evidence a real
analyst reads, and it is also an interested party's argument, so whether it helps is a fair
question.

Running that comparison requires identifying which documents are party submissions. **We cannot.**

`docket/classify.py`'s pattern is `party submission|reports? from part(y|ies) to the
investigation`. It matches only titles in which the NTSB itself announces the document as a party
submission. The module already records this as a measured limit, on Andy's 2026-09-19 ruling: a
document filed as *"Lycoming Engines — Engine Examination"* is a party submission and does not
match; a document credited to a police department or an independent laboratory may look like one
and is not. Telling them apart from a title is the judgement the hand-check showed cannot be
automated.

So the category counts **documents the NTSB labels**, not documents parties wrote. On `dev-400`
that is 12 documents in 9 of 401 dockets (`docs/results/s2-shape-dev.txt`).

Andy, 2026-09-20: *"I don't believe there are only 9 examples of party submissions, I imagine
there are only 9 with a certain title, but this is where the labelling fell down and why we are
trying to drop it."*

## Decision

1. **0038 item 4 is retired.** The with-and-without comparison is not run, on `dev-400` or on
   held-out.
2. **The `no-submissions` run variant is removed**, with `Variant` and the `--docket-filter`
   argument that selects it. It existed only to serve item 4 and is keyed on the same category.
3. **`make armb` becomes a single run.**
4. The `party_submission` category itself stays as a published statistic in the shape file, with
   the limit above stated wherever it is quoted.

## Why

1. **The comparison would measure the wrong population, not a small one.** It would remove 12
   self-announcing documents while leaving every other party-authored document attached, then
   report the difference as the value of party submissions. An underpowered result is weak; a
   result about the wrong set is misleading, and misleading in the direction of "party
   submissions do not matter".
2. **Nine pairs could not carry a claim even if the population were right.** S1 established that
   40 cases gave an interval too wide to support a conclusion alone. Nine is far worse. Both
   faults would have to be fixed for the measurement to be worth its money.
3. **Identifying parties properly is a new inference layer, and the stage's evidence is against
   adding one.** The docket does carry a "Statement of Party Representatives" roster, so parties
   could in principle be named and matched against document titles. That is more title inference
   of exactly the kind 0051 and 0052 removed after measuring it at 58-72% accurate, and an
   earlier attempt at a broad party pattern produced false positives such as "Tree Branches Cut by
   Propeller Strikes".
4. **It removes the last admission rule keyed on the category.** With 0052 and 0053 already
   landed, the category's remaining jobs are the deny-list and a published statistic.

## What this rules out

- **Running the comparison anyway and publishing the interval.** Considered: 0038 item 4 says the
  difference is published "whichever way it comes out", and demonstrating a negative is usually
  better than asserting one. Rejected because the demonstration would be of the wrong quantity,
  and publishing a wrong-population comparison labelled honestly is still a number a reader will
  quote without the label.
- **Building a party roster parser to identify submissions properly.** Rejected for reason 3. If
  the value of party submissions ever becomes load-bearing, this is the route, and it needs its
  own measurement first.
- **Keeping the `no-submissions` variant for later use.** Rejected: a variant nothing runs is a
  synonym waiting to mislead, which is the argument 0052 used to delete `unfiltered`.

## What is lost, stated plainly

0038 item 4 was a real commitment to measure rather than assume, and it is not being met. The
honest position is that the project cannot identify party submissions reliably enough to measure
their value, and says so, rather than publishing a comparison that looks like an answer.

## Status

Accepted, 2026-09-20 (Andy: "this is where the labelling fell down and why we are trying to drop
it, so for me I don't think decision 0038 is worth continuing on").
