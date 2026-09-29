# 0101 — Counts act only on a clear habit: the plain rule and guidance follow the NTSB's most common choice only above 60% of 20 cases

Amends [0096](0096-the-ordering-check.md) item 4 (the plain rule) and
[0098](0098-guidance-rounds-stop-rule-and-prediction.md) item 2 (what guidance may say). Taken
before any code, on the S2.7 track 1 plan's walkthrough item W1.

## Context

The ordering check and the guidance use the statistics pool's counts (0094) of how the NTSB
codes. As 0096 wrote it, the plain rule moves a case to the pool's most common event or phase
however small the lead. Andy's concern: that pushes every case toward the most common
combination. Where the NTSB's habit is strong, following it is right, since the score is
agreement with the NTSB. Where the habit is split, a count-based move adds noise and breaks every
case whose true code is the less common one.

Counts from development cases outside `dev-400` (ad hoc, 2026-09-27; Task 3 re-derives them):
within the Landing group, a hard landing is coded in the flare/touchdown phase in 439 of 608
cases (72%), a runway excursion in the landing roll in 163 of 211 (77%), and a loss of control
on the ground in the landing roll in 1,006 of 1,554 (65%). Within Approach, a loss of control in
flight is split between go-around (116 of 390) and final (110); a stall between final (40 of
131), go-around (37) and base (24). Within Maneuvering, a loss of control in flight is split
between the generic phase (167 of 392) and low-altitude flying (142). The same probe found every
phase code the NTSB used for a defining event belongs to exactly one phase group, so the group
membership itself pushes nothing.

## Decision

1. **A clear habit** is an option holding at least 60% of at least 20 pool cases for the same
   question: the defining code among cases containing the model's first guess (the event step),
   or the phase among cases with that phase group and event (the phase step).
2. **The plain rule moves only on a clear habit.** At each step, the model's own choice stands
   unless a clear habit exists and differs from it. `ordering.RULE_MIN_CASES` is replaced by
   `CLEAR_HABIT_SHARE = 3/5` and `CLEAR_HABIT_MIN_CASES = 20`.
3. **Guidance states a habit as a habit only when it is clear.** Below the line, guidance may
   describe the options with their counts and say the evidence decides; it never names one
   option as the usual one.
4. **The push is measured.** Every check step records whether it moved the first code toward a
   more common option (the new code is defining in more pool cases of the phase group than the
   old). Round 1's report and each guidance round's result print how many first codes moved that
   way, with their fixes and breaks.
5. The candidate list (0096 item 3) and what the model-asked checks see are unchanged; their
   instruction already says past habits are a guide and the evidence decides.

## Why

1. **It keeps the strong habits**, where most of the easy fixes are, and leaves split cases to
   the evidence.
2. **It removes predictable noise before measuring.** On a near-tie, a count-based move flips on
   a handful of cases.
3. **It makes the concern measurable** rather than argued: the push is a printed count.

## What this rules out

- **The rule moving on any lead**, as 0096 item 4 first wrote it.
- **Counts withheld entirely.** It would give up the strong habits and leave the plain rule with
  nothing to go on.
- **Choosing the 60% line from `dev-400` results.** It was proposed after seeing the pool's shares
  above, none of which are `dev-400` cases or results; it is fixed now, before any rule is run.

## Status

Accepted, 2026-09-27 (Andy: "A with a 'clear habit' safeguard.").
