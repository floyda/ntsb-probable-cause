# 0156 — The board runs the loop, named Ellery, as version 1, although the fixed pipeline measured better

From Andy, 2026-10-05 and 2026-10-06, in the S5 site design session. Detail: the Draft
specification `docs/specs/2026-10-04-s5-public-site-design.md`, §1, §3.1 and §12 items 13 and
15.

## Context

1. **S3.2's registered held-out reading**: "On held-out cases, the loop was not shown to improve
   on the fixed pipeline: it was worse." Occurrence top-1 23.5% [19.2%, 27.5%] against arm B's
   33.0% [28.5%, 37.5%], at an equal bill reached only through cached-prompt discounts
   (`docs/results/s32-claims-heldout.txt`, `docs/results/s32-heldout-diagnosis.txt`;
   decision 0146).
2. **The site exists to show judgement about when an agent is warranted**, and S3.2's answer
   is "not warranted".
3. **The loop is the thing being improved**: the precedent tool is its planned second version
   (decision [0140](0140-the-precedent-tool-after-s4-as-a-measured-v2.md)). Version 1 had exactly
   the evidence and tools the fixed pipeline had.

## Decision

1. **The live board runs the loop**, the S3.1 loop frozen at `fd6053f`.
2. **The agent is named Ellery**, and the site too, at `ellery.demo.floyda.dev`. On the site it
   is "Ellery, version 1". The site calls Ellery "it". The name is invented, after Ellery Queen's
   "Challenge to the Reader", and stands for no real person.
3. **The page says the result first**, above the board, in the wording Andy approved on
   2026-10-05: Ellery reads the same evidence, with the same tools, as a simpler fixed method; on
   400 accidents it had never seen it matched the investigator's first code in about one case in
   four, the fixed method in about one case in three; it runs here because it is the version
   being improved.
4. **A later version replaces version 1 on the board when it beats version 1 in a registered
   comparison.** Every version is also measured against the fixed pipeline, which stays the bar
   for calling the loop warranted. Decision 0153 notes `heldout-400` can no longer test a later
   version, so those comparisons are registered on other samples or on live cases.

## Why

1. **Room for improvement is the point of the site's second half.** Version 1 is a fair
   starting point, not a handicap: it had what the fixed pipeline had.
2. **Honesty is kept by the caveat, not by the choice of runner.** The reader meets the loss
   before any row.
3. **A named, numbered version** lets the site show improvement by measurement, version against
   version.

## What this rules out

- **The fixed pipeline on the board, with the loop beside it.** The strongest case, and Claude's
  recommendation in the session: production would run the method that won, which is itself the
  judgement the site exists to show, and the loop's claim would still be tested live beside it.
  Its cost: the board's subject would no longer be the agent being improved, and its trail view
  would show a secondary method.
- **The fixed pipeline only.** Simplest; it loses the live trail of the agent's choices.
- **A real person's name, or a name already used by AI products.** A real name attaches a
  person's reputation to a version that measured worse; several alternatives were in use
  (Archie, Amos, Asa, Ansel, Tracy; searched 2026-10-05 and 2026-10-06, recorded in the Draft).

## Status

Accepted, 2026-10-06 (Andy: "I think A on the basis that there is room for improvement on the
agent"; "Made up name"; "ellery.demo.floyda.dev").

## Glossary

- **Ellery, version 1**: the S3.1 loop frozen at `fd6053f`, as it runs on the live board.
- **Fixed pipeline**: arm B: every readable document, then coding tools and an ordering check,
  in a fixed order.
- **Warranted**: the loop beats the fixed pipeline at equal cost, by S3.2's registered rule.
