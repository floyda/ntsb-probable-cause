# 0163 — The live shadow's caps: $0.30 a case, $5 a month, and S3.3's stop at $10, each in code

From the S3.3 design session with Andy (2026-10-07). Detail:
[the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §9. Limits S3.3's share of
the line [0150](0150-s32s-share-of-the-spend-line.md) left it.

## Context

1. **Expected cost** (estimates from the held-out loop run's $3.9270 computed and $2.0610 billed
   for 400 cases, `docs/results/s32-claims-heldout.txt`): about $0.0098 a case computed. The
   backfill, perhaps 60 to 100 cases, about $0.60 to $1; about 100 closures a month, about $1 a
   month; S3.3 in all about $2 to $4.
2. **S3's line:** $11.46 of $50 spent on 2026-10-07 (`scripts/stage_spend.py --stage s3`), all of
   the remaining $38.54 S3.3's by 0150.
3. **Version 1 was measured on held-out with a $0.30 per-case cap**
   ([0144](0144-one-per-case-cap-for-every-arm.md)); the code's default is $0.15.
4. **S3.2's share was not enforced in code** (S3.2 As-built, "Known issues").

## Decision

1. **$0.30 a case**, the cap version 1 was measured with. With 10 cases a day
   ([0157](0157-s33-codes-closures-through-a-queue.md)), the worst possible day is $3.
2. **$5 a calendar month of live spend.** Before each morning the command adds this month's live
   spend to the queue's expected cost and refuses if that passes $5; the cases stay queued.
3. **S3.3 stops for Andy when its own spend reaches $10**: S3's spend by commit on `s3-` branches
   at billed cost, less the $11.46 S3.1 and S3.2 spent, so a line of $21.46 on S3's spend,
   checked by `scripts/stage_spend.py --stage s33` before every paid morning.
4. **The $40 monthly guard and S3's $50 line still apply.**

## Why

1. **Each cap catches a different failure**: the per-case cap one runaway case, the monthly cap a
   fault repeated over mornings, the stop a stage that costs more than it should.
2. **$5 is three to five times the expected spend**, so it never bites in normal use; a fault that
   ran every case to its cap would be stopped after about 16 cases.
3. **The $10 stop leaves most of the line unspent**, away from version 2's and S4's needs.
4. **Andy, 2026-10-07:** "A".

## What this rules out

- **$2 a month.** Close to the expected spend, so drift shows at once. Rejected: a month with the
  backfill and a burst could reach it and hold cases for days.
- **No shadow cap, only the guard and the line.** Simplest. Rejected: a fault would draw on money
  other work needs that month.
- **The $0.15 default.** Rejected: version 1 was measured at $0.30.

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).

## Glossary

- **Billed / computed cost**: what the provider charged after cached-prompt discounts, and every
  token at the list rate.
- **Spend line**: a stage's allowance, counted by commit on its branches.

## Clarified, 2026-10-09 (appended; nothing above is edited)

- Decision item 1's "the worst possible day is $3" held at 10 cases a day. From [0167](0167-the-live-shadows-daily-limit-is-raised-to-50.md) (50 a day) the worst day is 50 × $0.30 = $15 in principle: the $5 month is checked before a morning as a projection at $0.04 a case, not as a stop during the run, whose budget is the $40 monthly guard. The caps themselves are unchanged.
