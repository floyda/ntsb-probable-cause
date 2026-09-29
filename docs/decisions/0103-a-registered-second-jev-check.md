# 0103 — A registered second Jev check, designed from TypeSafe's documentation

Amends [0096](0096-the-ordering-check.md) item 5 and [0097](0097-jev-as-an-ordering-check-model-on-development-cases.md) item 1 for one extra comparison.

## Context

Round 1 (`docs/results/s27-round1-dev.txt`) kept the GPT-6 Luna ordering check by 0096 item
5's rule. Jev beat "no check" on both answer sets, but beat the plain rule clearly on one set
only, so it could not be chosen.

After Round 1, Andy asked how Jev was used and whether TypeSafe's documentation suggests a
better use. It does. The Round 1 Jev request did four things the vendor's documentation
advises against (docs.typesafe.ai, read 2026-09-27):

- The state was one block of plain text. The documentation recommends an object with named
  fields "for most requests".
- The state was full of counts ("defining in K of N"). The documentation page for
  `jev-1.13` lists "arithmetic/counting" as a weakness.
- Each option's description was only the phase and event words. The documentation says:
  "When two options are similar and the model keeps confusing them, describe each one with an
  object instead of a string", with what the option covers and what it is not for.
- There was no "none of the above" option. The documentation recommends one "when the list
  might not cover every input".

Three independent projects that measured Jev (jev-orderby-bench, Janus, jev-certify; checked
2026-09-27) add two facts. Jev returns probabilities in steps of 0.01, so ties are common.
A confidence cut-off tuned on one dataset does not carry over to another.

## Decision

1. One more way, `jev2`, runs over Round 1's two answer sets (B-v1
   `20260926T082427-d19aafa-dev-400-B` and its repeat `20260927T111202-fbab38a-dev-400-B`).
   Its design is fixed in `docs/rounds/s27-round1-jev2.md`, committed before any code for it
   is written and before any call is made.
2. Every design choice comes from TypeSafe's documentation, the independent projects above, or
   a threshold already fixed by 0096 or 0101. None comes from Round 1's case results.
3. `jev2` replaces Luna as the kept check only if, on both answer sets, its paired top-1
   difference has a lower interval bound above zero against no check, against the plain rule
   and against Luna. Otherwise Luna stays. A replacement is then recorded as a new decision.
4. Round 1's results file is not changed. The comparison has its own results file,
   `docs/results/s27-round1-jev2-dev.txt`, which says it is a second, registered comparison.
5. Jev's probabilities and confidence are recorded on every step. No confidence cut-off is
   used. A later stage may set one, on cases that did not choose it.

## Why

1. **The changes come from the vendor's documentation, not from the case results.** This is
   Andy's point. What remains is the risk of choosing details after seeing Round 1. Writing
   the whole design down, and committing it before the run, removes it.
2. **A second attempt for one way could win by chance.** The win rule is fixed now, and it
   is stricter than Round 1's: `jev2` must beat Luna, not only the rule.
3. **It costs a fraction of a cent** and uses the answer sets already paid for.

## What this rules out

- **Changing anything in the design after the first call.** A different design is a new
  registration and a new record.
- **A confidence cut-off tuned on these answer sets.** Janus found the best cut-off moved from
  0.67 to 0.37 between two datasets; tuning one here would be tuning on the scored cases.
- **Examples in the option descriptions.** They would have to come from real cases.
- **Re-reading Round 1.** Its outcome stands unless rule 3 is met.

## Status

Accepted, 2026-09-27 (Andy: "Yes that sounds good", approving the design; earlier: "Otherwise
yes option B after but more research").
