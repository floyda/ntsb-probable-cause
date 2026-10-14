# 0150 — S3.2's share of S3's spend line is $12

From the S3.2 design session (2026-10-03): spend. Splits the line of
[0128](0128-s3-in-three-sub-stages-with-one-spend-line.md) item 2 between S3.2 and S3.3, as 0128
item 5 did for S3.1. Detail: [the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md)
§17.

## Context

- S3 has one spend line of $50, counted by commit on `s3-` branches
  (`scripts/stage_spend.py --stage s3`, 0128 and
  [0135](0135-s3-spend-counts-what-was-billed.md)). 0128 item 5 gave S3.1 a share of $20 and left
  the rest to S3.2 and S3.3.
- S3.1 spent $5.11 (scripted, `scripts/stage_spend.py --stage s3`, 2026-10-03).
- The estimate for S3.2's five runs is about $6.50 billed
  ([0141](0141-s32-five-runs-and-the-sealed-sample-kept-for-v2.md), spec §3). S3.3's first pass
  over the watched cases is estimated at about $7.50.
- Each run reserves its cost when it starts and releases it when it ends (0135 item 4). The
  held-out loop run reserves about $4.60 (estimate, the noise-floor runs' computed cost). The
  monthly guard is $40 ([0083](0083-the-monthly-budget-is-forty-dollars-in-development.md)).

## Decision

1. **S3.2's share of the line is $12**, about twice the estimate of $6.50.
2. **How it is counted:** by commit on `s3-` branches, as 0128 and 0135 count S3's spend. S3.2's
   share is the line's total less the $5.11 S3.1 spent. Runs count what was billed (0135).
3. **The stop:** if a re-estimate passes the share, work stops and Andy decides (0083 item 2).
4. **Reservations:** each run reserves its computed cost when it starts and releases it when it
   ends. The monthly guard has room for one run at a time.
5. **S3.3 keeps the rest:** over $30 of the line, against a first-pass estimate of about $7.50.

## Why

1. **The estimate is a billed figure and has not been measured on held-out.** Held-out fatal
   dockets may be larger than `dev-400`'s. The share leaves room for that, and for one run to be
   repeated.
2. **A share with room is still a limit.** If a re-estimate passes it, Andy decides before more is
   spent.
3. **S3.3 is not squeezed.** It keeps over $30 for a pass estimated at about $7.50.

## What this rules out

- **Keeping the share at the estimate, about $6.50.** The strongest case: it is the tightest
  limit. Rejected: any run repeated, or any larger docket, would stop work for a decision on a
  few dollars.
- **No share for S3.2, only the line's total.** Less to track. Rejected: 0128 split the line by
  sub-stage so that no sub-stage can spend what the next needs.
- **Counting the computed price.** Rejected by 0135.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Billed cost**: what the provider charged (0135).
- **Reservation**: the budget a run holds from its start to its end, so that two runs cannot
  both spend the same headroom (0045).
- **Spend line**: a stage's limit on what it may spend, counted by commit (`make s3-spend`).

## Amended in part, 2026-10-07 (appended; nothing above is edited)

- **S3.3's share of the remainder is limited by [0163](0163-the-live-shadows-caps.md)**: S3.3 stops
  for Andy when its own spend reaches $10, a line of $21.46 on S3's spend, checked in code by
  `scripts/stage_spend.py --stage s33`.
