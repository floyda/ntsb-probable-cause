# 0027 — The registration rule, and the case-number probe measure memorisation

## Context

Held-out cases closed between 2020 and 2023, and their reports are public. A model may have
read them in training, so a held-out score could measure recall rather than reasoning. The
roadmap's risk table asks S1 to measure this, keeps the case number and docket URL out of
every payload, and leaves the aircraft registration — a day-1 fact that is also a name a
published report uses — to an ablation (0023). Make, model and engine type are separate
start facts, so the registration adds nothing to a closed-case evaluation except identity.

## Decision

1. **The registration rule.** The ceiling runs with and without the registration on
   `dev-400` and then on `heldout-400`; the paired difference in top-1, with a bootstrap
   interval, decides. If the interval includes zero, the registration stays a start fact. If
   the difference favours having it, the registration is removed from every evidence
   payload, and the difference is published as the memorisation estimate. The outcome is
   recorded in the S1 As-built record, and the second branch also produces a new decision
   record amending 0023.
2. **The case-number probe.** One run on `dev-400` with the NTSB case number added to the
   payload, through a separate code path that the guard rejects on any other sample. The
   paired difference against the ceiling is the memorisation ceiling for that model, and it
   is published whichever way it comes out.
3. Live cases, which no training set holds, are the control once the board runs (S3, S5).

## Why

1. **The rule is written before the run**, so the answer is read off, not chosen.
2. **There is no branch that keeps a fact that only helps by memory.** A registration that
   does not help is harmless and true to what a live case has; one that helps is a leak.
3. **The case number is the direct test.** A jump when the model is told which report it is
   reading is evidence it has seen the report, and the development split is the one place a
   leak costs nothing.

## What this rules out

- **Dropping the registration by default.** It is a true day-1 fact and the live board will
  have it; removing it unmeasured would be a guess.
- **Keeping it whatever the ablation says.** Would let memorisation into the bar.
- **The case-number probe on held-out cases.** It would be a deliberate leak into the
  reported split.

## Status

Accepted.
