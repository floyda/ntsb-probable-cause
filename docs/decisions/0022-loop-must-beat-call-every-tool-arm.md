# 0022 — The loop must beat a call-every-tool arm at equal cost

## Context

`CLAUDE.md` and the roadmap planned one comparison for agency: the agent against an ablation
with the docket tool removed. That shows the docket matters. It does not show the loop
matters, because a fixed pipeline that reads every readable document would also gain from
the docket.

The spike's docket-shape addendum (`scripts/docket_shape_probe.py`, register A13) found that
about four in five development-era dockets hold under 10,000 estimated tokens of readable
text, and that most of the excess in large dockets is weather data, radio transcripts and
party submissions, which a title filter could also drop. Its stated consequence: a tool loop
must beat a filtered fetch-everything pipeline, not only the no-docket ablation.

S1's re-measured one-shot ceiling (every structured evidence role, one call, no docket) is
already on the roadmap.

## Decision

1. Every agency result is reported for three **arms**, with the same model, price variant,
   cases and per-case cost cap
   ([agency design §6.1](../specs/2026-09-14-agency-hypothesis-trail-design.md)):
   - **A** — start facts only, one call;
   - **B** — every available tool in a fixed order, then one call;
   - **C** — the loop (0021).
2. **Arm B's document filter** is a fixed list of document types and titles, chosen on the
   development split and published before any held-out run. The unfiltered version is
   reported on the development split only.
3. S1's one-shot ceiling is arm B without the docket. Arm B with the docket is run once S2's
   docket module exists and before any loop code is written; its score is recorded as a bar
   for the loop.
4. The loop is warranted only if arm C beats arm B on accuracy at equal cost, or matches it
   at lower cost. **Any one of these results counts against the loop**, and each is published
   whichever way the others go; if one holds, the published result is that retrieval was
   warranted and the loop was not:
   - arm C calls every tool on most cases;
   - arm C matches arm B only at the same or greater cost;
   - the intermediate hypotheses are not calibrated;
   - stated and actual effects do not agree.
5. **Six predictions are fixed here, before any measurement,** and published whichever way
   they come out. They are stated by fatal / non-fatal, not by investigation class. This
   record is append-only, so they cannot be edited after a result is seen.

   | # | prediction |
   |---|---|
   | P1 | Fatal cases take more steps than non-fatal cases. |
   | P2 | In the full condition, arm C matches arm B's accuracy at lower cost on non-fatal cases. |
   | P3 | Any accuracy advantage of C over B is concentrated in fatal cases. |
   | P4 | In the masked condition, C abstains more often than in the full condition, and asks for the missing evidence. |
   | P5 | On average, the probability on the true codes rises with each step. |
   | P6 | Stated and actual effects agree more often than chance. |

   P1 and P3 rest on fatal dockets being larger in every class the spike sampled; P2 rests on
   development-era docket sizes, which S2 re-measures for the current era (0024).

## Why

1. **Arm B is the alternative a sceptic would build.** "Why not read everything and answer
   once?" is the question the project must survive, and for most dockets reading everything
   is cheap.
2. **A filtered arm B is the stronger opponent.** An unfiltered pipeline wastes its budget on
   weather attachments and transcripts, so beating it would prove little.
3. **The bar exists before the loop does.** Running arm B before any loop code is written
   keeps the loop from being tuned against its own comparison.
4. **Predictions by fatality survive the change of era.** The corpus scan
   (`docs/results/s0-corpus-scan.txt`) counts C-class cases as 6,126 of 13,560 development
   cases, 397 of 4,241 held-out cases and 0 of 1,840 closed open-split cases. A prediction
   about CA cases would be about cases that barely occur where it is tested. Injury level
   means the same in every era.

## What this rules out

- **Only the no-docket ablation.** The roadmap's plan, and simpler. Rejected because a loop
  that is a pipeline in costume would pass it.
- **An unfiltered arm B as the headline comparison.** Needs no filter design. Rejected for
  reason 2.
- **Letting the loop choose its filter while arm B has none.** Rejected as an unequal
  comparison.
- **Predictions by investigation class.** Matches the spike's strata. Rejected for reason 4;
  class is still reported, second.
- **Predictions kept in the design specification.** Next to the detail they refer to.
  Rejected because a specification can be edited; a prediction written in advance is only
  worth something if nobody can change it afterwards.

Cost: arm B roughly doubles evaluation spend on the cases it runs, and the filter needs its
own development-split measurement in S2.

## Status

Accepted on Andy's squash merge of the pull request that carries the agency design revision,
2026-09-14.
