# 0216 — Finding rounds are decided on an interval, with pooled noise and a precision clause

From Andy, 2026-10-21: "lets go with option A", after an independent review of the finding mark
(Fable 5.1, 2026-10-21; its report was not committed). The figures below marked [exploratory]
were computed from development run folders by that review and re-run once by Claude Code, free
and offline; they decide nothing (0059).

## Context

1. **Recall@10 means recall at ten digits over a list of any length.** The code compares the
   whole set of codes the answer gives at 10 digits with the NTSB's flagged set and never cuts
   the list (`scoring/metrics.py:_precision_recall`); `Hypothesis.findings` has no maximum
   length. The memory pilot's glossary says "among the answer's first ten finding codes"
   (`docs/rounds/memory-pilot.md`, glossary). That is wrong; no other committed glossary
   defines the term.
2. **Recall alone rewards listing more codes.** On `dev-400`, the same answer for every case,
   S3's pool's five commonest flagged codes, scores finding recall@10 34.0% at precision@10
   16.8%; S3's full arm B scores 27.3% (`docs/results/s3-armb-full-dev.txt`). Adding the pool's
   single commonest code to every arm B answer raises it to 31.6% [exploratory]. Precision is
   printed in every table, but no registered rule reads it (0098 item 4, 0136, 0204).
3. **The memory's stop rule compares single numbers.** S2.7's guidance rounds kept a gain only
   if its interval's lower end was above zero and it beat the noise (0098 item 4). The memory's
   rule, 0204 item 5, used by 0210 to 0214, dropped the interval: it passes when M(find) >
   |N(find)|, with M and N each a point estimate and N from one pair of identical runs
   (`scripts/memory_pilot_result.py:stop_rule`). When there is no effect, M and N
   are two draws from the same noise, and the first is larger than the absolute value of the
   second about one time in four. The review's simulation from real arm B per-case noise gave
   24% for the finding clause alone [exploratory].
4. **One pair is a thin estimate of noise.** On `dev-400` the coding test's top-3 noise was
   +0.0 (`docs/results/memory-confirm-dev400.txt`), so any fall at all would have failed that
   clause. Two identical S2.7 arm B answer runs differed by top-1 +4.0 [+0.5, +7.5]
   (`docs/results/s27-round0-dev.txt`).

## Decision

1. **Scope.** Every round registered from today whose rule reads a finding measure. That
   includes the coding memory's transfer check (an uncommitted draft, which is rewritten to this
   rule before it is accepted), any further memory round, and version 2's tuning rounds. Rounds
   already read keep their registered rules and their published results (0204 to 0214, S2.7's
   rounds, S3.2's claims).
2. **The finding gain must clear zero.** With D the paired difference, new condition minus its
   reference, on the same cases and with failed cases counted wrong (0136), the round passes on
   findings only if the lower end of D(finding recall@10)'s 95% interval is above zero. The
   interval is the harness's paired bootstrap (`metrics.paired_difference`, default seed).
3. **Noise is pooled.** For each measure, the noise is the mean absolute difference between
   identical runs over every identical pair the registration names. Pairs are named by run id,
   and must have the same sample and the same part (answer, tools post-pass, or coding test).
   The round's own pair is always one of them.
4. **Three do-no-harm clauses**, each against its pooled noise: D(top-1) ≥ −noise(top-1),
   D(top-3) ≥ −noise(top-3), and **D(finding precision@10) ≥ −noise(finding precision@10)**.
5. **Length is printed beside every finding result**: the mean number of finding codes per case
   in each run, and finding recall and precision at 6, 8 and 10 digits. They are descriptions;
   they do not decide.
6. **The headline mark is unchanged.** Finding recall@10 (flagged) stays the published finding
   measure in the bars, the claims and the board, with precision beside it as now.
7. **The pilot's glossary is corrected by an appended dated note** in
   `docs/rounds/memory-pilot.md`; the signed text above it is not edited.
8. **Code.** The rule is written as a function with its docstring copied word for word from the
   first registration that uses it, as 0214's selection rule was, and tested on invented runs.
   It is built with that registration's plan, not before.

## Why

1. **It closes the two ways a finding round could pass without a real gain:** a lucky noise
   draw (items 2 and 3) and a longer list (item 4's precision clause).
2. **It costs nothing in money and touches nothing published.** Option B, a new headline, would
   amend 0025 and 0029 and every published table and site figure, which slows the demo page
   for a change that the precision clause mostly delivers.
3. **It returns to S2.7's form.** 0098 already read rounds on an interval. Making the interval the
   pass also removes the transfer check draft's "thin pass" tier, which decided nothing.

## What this rules out

- **Changing the headline to F1 or recall at a fixed k now (Option B).** The strongest case for
  it: a headline that cannot be gamed by length, and one figure for a reader. It stays open for
  version 2's design, with the published bars re-read from their run folders, which is free.
- **Re-reading closed rounds by the new rule as if it had been registered.** A reader may compute
  it; the registered outcome stands.
- **Deciding on point estimates against one pair** for any new finding round.
- **A precision clause on occurrence codes.** Top-1 and top-3 are fixed-length, so length cannot
  inflate them.

## Status

Accepted. Amends 0204 item 5 (and so 0210 to 0214's form of it) for rounds registered from
2026-10-21; adds to 0098 item 4 and 0136.
