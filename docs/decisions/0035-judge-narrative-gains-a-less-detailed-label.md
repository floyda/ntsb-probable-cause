# 0035 — The judge's narrative dimension gains a fourth label, "less detailed"

Amends the narrative label set in §8 of
`docs/specs/2026-09-14-s1-scoring-and-evaluation-design.md`. Everything else in §8 stands,
including the validation rule and 0028's "never a bar".

## Context

Spec §8 gives the judge three labels for the evidence narrative: `consistent`, `contradicts`,
`adds unsupported facts`. The first real judge pass, over 178 development cases, returned
`contradicts` on 159 of them and `adds_unsupported_facts` on 1.

That distribution is not credible as a description of the prose, and the reason is visible in
what the agent is asked to do. Decision 0013 withholds the factual narrative from every case,
so the analyst writes its evidence narrative from structured fields alone — no docket, no
investigator write-up. What it produces is *thinner* than the official narrative: it says the
aircraft was in the landing phase and nobody was hurt, where the official text describes a
gust, a bounce and a runway excursion. Nothing in it conflicts. It simply says less.

With three labels there is nowhere for that to go. `consistent` overstates the match,
`adds_unsupported_facts` is plainly wrong, and `contradicts` becomes the bucket every partial
narrative falls into. The label then measures the thinness of the evidence, which S1 already
measures directly and far better, instead of measuring whether the prose is trustworthy.

A separate defect was fixed at the same time and is not this record's subject: the judge was
never shown the model's occurrence codes, so the `lay` dimension's 158-of-178 `does_not` was
an artefact of our rendering. That was a bug, not a decision.

## Decision

1. The narrative dimension takes four labels: `consistent`, **`less_detailed`**,
   `contradicts`, `adds_unsupported_facts`.
2. `less_detailed` means the analyst's narrative says less than the official one and nothing
   in it conflicts. The rubric states explicitly that leaving things out is not the same as
   being wrong.
3. `contradicts` is narrowed to actual disagreement about a fact.
4. The judge's validation rule is unchanged: it is the `cause` dimension that is compared with
   the code layer, and the judge is used on held-out runs only if that agreement is at least
   the spike's 62.5% *and* the hand-check shows no one-sided error.
5. The first judge pass, run before this change, is discarded rather than reported. It was
   stopped at 204 of 401 cases.

## Why

The purpose of the narrative label is to tell us whether the agent's account of the evidence
can be trusted. "Contradicts" and "says less" are different answers to that question. The
first is a reason to distrust the prose; the second is a description of how little evidence
there was, which the ablations already quantify — removing phase of flight alone takes top-1
from 8.7% to 0.2%. Collapsing them loses the only information the label was there to provide.

The distribution is what forced the issue. A label that fires on 89% of cases separates
nothing, and would have gone into S1's results as though it described the writing.

Four labels is the smallest change that fixes it. The alternative — keeping three and
rewording the prompt so partial narratives count as `consistent` — was rejected because it
hides the distinction instead of recording it: a reader of the results could no longer tell a
genuinely matching narrative from a vague one, and that difference matters when S2 adds the
docket and the narratives should get richer. The point of S1's numbers is to be a baseline
that later stages move; a label that cannot move is worth nothing.

Discarding the first pass rather than mapping its labels forward is the honest option: those
labels were produced under a rubric that had no way to express the distinction, so there is no
sound rule for translating them.

## What this rules out

- **Reporting the first judge pass.** Its `lay` dimension measured our rendering and its
  `narrative` dimension had no label for the common case. Both are discarded.
- **Rewording within three labels.** Rejected above: it conceals the distinction rather than
  recording it.
- **Treating `less_detailed` as a pass or a failure.** It is neither. It is a description, and
  0028 still forbids any judge label from being a bar.
- **Re-judging with a changed rubric to improve a published number.** This change is made
  before any judge result is published, and the pass taken under the old rubric is discarded
  rather than compared against.

## Status

Accepted.
