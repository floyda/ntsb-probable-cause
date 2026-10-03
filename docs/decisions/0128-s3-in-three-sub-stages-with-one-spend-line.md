# 0128 — S3 in three sub-stages, with one $50 spend line

From the S3 design session (2026-09-29 to 2026-09-30): sub-stages choice A, and spend choice B.
Detail: [the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §3, §14 and §15.

## Context

S3 must build the loop, make claims about it against arm B, and run it on live cases. A claim
made on code that is still changing cannot be trusted. The claims need two things the build
produces, the loop's noise floor and a frozen loop
([0130](0130-the-loops-noise-floor-and-format-gate.md)), and one the recorder produces, the
14-night re-check ([0123](0123-the-staged-replay-is-paused.md)). Live accuracy cannot be
measured in S3: open cases enter a measurement only as numbers (0024), and their verdicts are
not yet published.

**Spend.** September's shared spend stood at $50.24 against the $50 set for September only
(`month_spent`, 2026-09-29, in the probe plan's Deviations; spec §14; 0104). From October the
monthly guard is $40 again (0083). The estimates are arithmetic from the probe at the batch
price (spec §14): S3.1 about $15 to $20; S3.2 about $20 to $25; S3.3 about $7.50 for a first
pass over the watched cases. Their upper ends add to $52.50 ($20 + $25 + $7.50), more than the
$50 line of item 2.

## Decision

1. **Three sub-stages**, each with its own merge, As-built record and tag (0017, 0018):

   | sub-stage | what it does | cases | claims |
   |---|---|---|---|
   | S3.1, the loop | builds the loop, its tools and native tool calling; the shape probe; the noise floor; tuning rounds; the format gate | `dev-400` only | none |
   | S3.2, the claims | arm C against arm B at equal cost; the ablations; the calibration fit; the new sealed sample once; held-out once | `dev-400`, the new sealed sample, `heldout-400` | yes, registered before its first run |
   | S3.3, live shadow | the recorder triggers nightly runs of the loop on open cases; everything logged, nothing locked or published | open cases (0024) | mechanics and cost only |

   The S3 specification holds the shared design and S3.1 in full. S3.2 and S3.3 each get their
   own specification when they start. S3.2 starts from S3.1's frozen commit. Stage-closing pull
   requests are titled `S3.1: the agent loop` and so on, and merged with a merge commit (0033).
2. **One spend line of $50 for all of S3.** It is counted by commit on S3's branches from S3's
   first commit (`777c2a5`, the draft specification), by the stage-spend script: 0098 item 6's
   rule, with 0107's branch-name rule applied to the prefix `s3-`.
3. **The learning probe's spend is outside the line.** Its $1.1954 was spent on commits before
   S3's first commit ([0131](0131-the-probe-spend-kind.md)). The probe's branch, `s3-probe`, has
   the prefix but not S3's first commit, so it is not counted.
4. **No paid S3 work starts before 1 October 2026.** The line spans October and November, under
   the monthly guard.
5. **If a re-estimate passes the line, work stops and Andy decides** (0083 item 2). The upper
   ends of spec §14's estimates already pass it ($52.50 against $50, Context), so this may
   happen before S3 ends. S3.1's share of the line is $20, the upper end of spec §14's S3.1
   estimate: S3.1's tuning rounds stop when S3.1's spend reaches it (spec §10.3; the S3.1 plan's
   Task 15 stop), and S3.2 and S3.3 keep the rest.

## Why

1. **Building and claiming are kept in separate merges**, so a claim is never made on code that
   was still changing.
2. **S3.3 exercises the loop on real arrivals for weeks before S4 needs it**, at a cost that is
   small against the stage.
3. **One line for the stage is judgement, not measurement.** The estimates come from a 20-case
   probe. One line lets a sub-stage that costs less than estimated leave the rest to the next,
   while the stage as a whole stays capped. S2.7 had one line of its own (0098 item 6).
4. **Counting by commit, on branches named for the stage,** is the rule S2.7 settled after a
   date filter caught another stage's runs (0098, 0107).

## What this rules out

- **One stage with one merge.** One specification and one close-out. Rejected: claims would sit
  on code still changing, and the live wiring would wait for the claims.
- **Live shadow deferred to S4.** Less work in S3. Rejected: S4's predictions store and
  resolution watcher would then meet the loop on real arrivals for the first time.
- **A line per sub-stage.** Tighter control of each part. Rejected: it would fix three lines
  from estimates that the noise floor has not yet tested.
- **Counting by date.** Simpler. Rejected by Why 4.
- **Paid work in September.** Rejected: September is already past its $50 (0104).

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
