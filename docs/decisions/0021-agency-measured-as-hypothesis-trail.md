# 0021 — Agency is measured as a scored hypothesis trail

## Context

The spike's agency figure, 38%, shows that fetching evidence changes the answer
(`decidability.py`, `scripts/decidability_crosscheck.py`). It does not show that an agent
choosing what to fetch does better than fetching everything. The spike's docket-shape
addendum (`scripts/docket_shape_probe.py`, register A13, report §10) found that about four
in five development-era dockets can be read whole in one call, so for most cases a loop that
chooses documents has nothing to choose.

The roadmap planned a trajectory log in S3 and "tool steps per case" as the metric. A count
of steps says how busy the agent was, not whether any step was a good decision. Full
reasoning: [the agency design](../specs/2026-09-14-agency-hypothesis-trail-design.md),
sections 2 to 4.

## Decision

1. After every tool call the agent records its **hypothesis**: the top three occurrence
   codes with probabilities, the finding codes it believes with probabilities, a
   one-sentence working cause, the reason for the call, the effect it expected, and the
   effect it observed. The sequence of these records is the **hypothesis trail**.
2. Each step is one stored row (design §3.4), carrying the arm, the availability condition,
   cost, and the commit SHA with an uncommitted-changes flag (0018). These rows are the S3
   trajectory log.
3. The trail is scored step by step against the NTSB's verdict: occurrence top-1 and top-3,
   finding-code precision and recall, probability on the true codes, calibration,
   information gain per call, and stated versus actual effect (design §4.3).
4. The agent stops and answers at a confidence threshold, and stops and abstains at the
   step budget, the cost cap, or when nothing more is available. The threshold is chosen on
   the development split only.
5. The public name is "the hypothesis trail": *the agent's working hypothesis after each
   piece of evidence*. It is not presented as the model's reasoning.

## Why

1. **It makes each step measurable, not only countable.** Information gain per call shows
   whether a call changed anything; a wasted call is counted, rather than hidden inside a
   step total.
2. **Codes need no judge.** Hypotheses as codes are scored by exact match (0006). Finding
   codes and the working cause keep the trail scoreable on live cases, where the occurrence
   code is often public from day 1 (S0 specification §2.4).
3. **It tests the agent's reasons instead of trusting them.** A model's stated reasons are
   not guaranteed to be what produced its answer. Stated versus actual measures how far they
   can be trusted, which is what a sceptical reader would ask.
4. **It is the most legible artefact the demo can publish.** The demo criteria call the
   trajectory view the most compelling artefact; a trail of scored hypotheses explains it to
   a reader with no domain knowledge.

## What this rules out

- **Steps per case as the only agency metric.** Cheaper to build. Rejected because it cannot
  tell a useful call from a wasted one.
- **A final answer only, with free-text reasoning in the log.** No per-step schema. Rejected
  because free text needs a judge, and the spike's judge agreed with Andy 62.5% of the time
  (0006).
- **Calling the trail the model's thinking.** More appealing to a lay reader. Rejected
  because it claims something the project cannot show.
- **Choosing the threshold on held-out cases.** Rejected: it makes the held-out scores
  meaningless.

Cost: every step is a structured model call with a growing context, so cost per case rises.
The cap is re-measured in S1 and S3.

## Status

Accepted on Andy's squash merge of the pull request that carries the agency design revision,
2026-09-14.
