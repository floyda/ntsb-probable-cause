# 0149 — How the results are read together

From the S3.2 design session (2026-10-03): the reading. Fulfils the last paragraph of
[0121](0121-agency-moves-to-reading-and-coding.md) item 5, which Andy decided on 2026-10-01: S3.2's
registration states, before its first run, how the four results are read together. Detail:
[the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §10.

## Context

0121 item 5 lists four results that count against the loop. Andy decided that no single one gives
a blanket verdict, and that each is published as it stands. His reason (spelling corrected):
"because this is a demo I want to be able to reason about my decisions ... as long as I am honest
about what I found." So the way the results combine has to be written down in advance.

On `dev-400` the loop was cheaper only on the bill, and did about twice arm B's work at list
price ([0145](0145-equal-cost-is-billed-cost-with-a-ten-percent-band.md)). A critic could fairly
say that is good engineering rather than good choosing, since a fixed pipeline built as one
cached conversation might earn the same discount.

## Decision

1. **Two questions, answered separately.**
   - **Question 1, is the loop warranted?** Decided by the headline test
     ([0146](0146-the-headline-test-and-failed-cases.md), spec §7.4) alone. Results 1 and 2 say
     how that outcome came about. They do not overturn it.
   - **Question 2, can the board's numbers and reasons be trusted?** Results 3 and 4. They do not
     change question 1. They decide what the board may show:
     - if result 3 holds (not calibrated), the board shows its confidence with a plain warning;
     - while result 4 is "not shown", the board labels a stated effect "the agent's note", never
       a prediction.
2. **The headline is one of these sentences, written now:**
   - "On held-out cases, the loop beat the fixed pipeline at equal or lower cost." (warranted)
   - "On held-out cases, the loop matched the fixed pipeline at lower cost." (warranted)
   - "On held-out cases, the loop was not shown to improve on the fixed pipeline: it [matched it
     at equal or greater cost / beat it only at greater cost / was worse / was undecided]." (not
     warranted)

   Results 1 to 4 follow, one line each, as they came out.
3. **Where any saving comes from.** If the verdict rests on cost, the report says how much of
   the loop's saving comes from reading less and how much from cache discounts. A committed
   script splits it from the token counts every run records: the difference in computed cost
   between the arms is the work done, and the difference between computed and billed within each
   arm is the discount.
4. **The likely case, worked through,** if held-out looks like `dev-400`: "matched the fixed
   pipeline at lower cost" (warranted); result 1 holds, mostly on small dockets, with its
   choosing on large fatal ones; the saving is mainly cache discounts; result 3 as measured;
   result 4 not shown. The page explains each part.

## Why

1. **It keeps one test and one verdict.** The test of 0121 item 5 decides question 1. The other
   results add context and set what is shown.
2. **It carries out Andy's decision of 2026-10-01.** No blanket conclusion follows from any one
   result.
3. **The saving's source answers the fair criticism.** It lets a reader see whether the loop
   saved money by choosing to read less or only by the cache discount.
4. **The sentences are written before the data.** No one can choose the wording to suit the
   outcome.

## What this rules out

- **Carrying 0022 item 4's conclusion over:** one failed result and "the published result is
  that retrieval was warranted and the loop was not". Already rejected in 0121 item 5. It keeps
  a public bar set before any measurement, but a single failed result would override an accuracy
  win.
- **One combined score or verdict.** It is easier to quote. Rejected: it would hide which result
  moved it, and Andy's decision calls for each to stand as it is.
- **Reporting cost without its source.** Rejected in Why 3.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Board**: the live public page for open cases, with the agent's steps and costs.
- **Cache discount**: the lower rate the provider bills for the start of a prompt it has seen
  recently.
- **Computed cost**: every token priced at the list rate, ignoring the cache discount.
- **Results 1 to 4**: the four results that count against the loop (0121 item 5; 0148 and 0147
  make them measurable).
- **Warranted**: the loop beats arm B at equal or lower cost, or matches it at lower cost.
