# 0135 — S3's spend counts what the provider billed for its batch runs

From Andy, 2026-10-01, after the S3.1 batch smoke run. Detail: the S3.1 plan's Deviations
(`docs/plans/2026-09-30-s3-1-agent-loop.md`). This changes how
[0128](0128-s3-in-three-sub-stages-with-one-spend-line.md) item 2's spend line and the monthly
guard ([0045](0045-monthly-budget-is-a-reservation-under-a-lock.md),
[0083](0083-the-monthly-budget-is-forty-dollars-in-development.md)) count
S3's runs. It does not change their limits.

## Context

1. **A run record holds two costs.**
   - `cost_usd`, the *computed* price: the sum of each call's cost. A batch reply carries no cost
     of its own, so the code prices it from the price table, at the `:batch` input rate for every
     prompt token. A synchronous reply carries the provider's own cost, and that is used.
   - `reported_batch_cost_usd`, the *billed* total: the sum of what each batch round reported it
     cost. It is None when any round reported no cost, and for a run with no rounds.
2. **Until now, the spend counted the computed price.** `month_spent` (the monthly guard, which
   every paid command checks) and `stage_spent` (`scripts/stage_spend.py`, S3's $50 line and
   S3.1's $20 stop in plan Task 15) summed `cost_usd`. Plan Task 3 kept it so on purpose: "cached
   tokens are recorded, not priced, until a measured cached price exists (the batch-level
   reported cost stays the run's reported total)".
3. **The loop's prompts are mostly cached.** Arm C sends one conversation per case, and each call
   repeats the turns before it. The provider bills a cached prompt token at a lower rate. The
   computed price does not.
4. **The batch smoke run measured the gap.** Run `20261001T140150-5a63002-dev-400-C` (arm C,
   `dev-400`'s first 20 cases, 12 batches, 192 calls; its `run.jsonl` and `trail.jsonl`):
   - computed: $0.1458 (`cost_usd` 0.1458389);
   - billed: $0.0484 (`reported_batch_cost_usd` 0.048429965), about one third of the computed;
   - cached: 2,164,643 of 2,618,428 prompt tokens, 82.7% (the `cached share of prompt tokens`
     line of `ntsb-eval report`).

## Decision

1. **What a run counts as spent** is `budget.spent_usd(record)` (`scoring/budget.py`):
   - the billed total, when the run is one of S3's own kinds and every round reported its cost
     (`budget.counts_billed`);
   - else the computed price.
2. **S3's own kinds** are arm C runs, and arm B's tool post-pass (a derived arm B run whose prompt
   version holds `+tools-`). Every other run counts the computed price, as before. So no run from
   before S3 changes what it counts.
3. **The monthly guard and the stage spend line use it.** `month_spent` and `stage_spent` count
   each run record with `spent_usd`. So S3's $50 line and S3.1's $20 stop count what was billed.
4. **Unchanged:**
   - The per-case cap still uses the computed estimate, which errs high. A case is stopped on what
     its calls could cost, not on a bill that arrives with the round.
   - Reservations are unchanged: a run still reserves its expected cost per case times its cases.
   - Preparation spend rows (`spend.jsonl`) are unchanged.
   - Both figures stay in every record. No record is rewritten.
   - A judge pass and an ordering check record no billed total, so each counts its own cost, as
     before. So does a synchronous arm C run: it has no rounds, and its replies' costs are the
     provider's own.
5. **The noise-floor report prints both figures.** `scripts/s3_noise_floor.py` prints, for each
   run, the computed and the billed cost, each for the run and per case, and which one the spend
   line counts.
6. **S3.2's registration fixes how equal cost is measured** for arm C against arm B. This record
   says what the spend counts, not what "equal cost" means.

## Why

1. **The spend line exists to stop spending.** It should count the money that was spent. On the
   smoke run, the computed price was about three times the bill.
2. **The bill is measured.** It is what the provider reported for each batch. The computed price
   is a model of the bill that leaves out caching.
3. **The guard stays safe where it matters.** The per-case cap and the reservations still use the
   computed estimate. Only spend already billed is counted at the billed figure.
4. **The past stays as it was counted.** September 2026's `month_spent` is $50.2395 before and
   after this change, and S2.7's `stage_spend` output is byte for byte the same. Earlier
   decisions and results cite those figures.

## What this rules out

- **Keep counting the computed price everywhere.** It always errs high, so no limit could be
  passed by mistake. Rejected (Andy): the spend line and S3.1's $20 stop would run about three
  times fast, and S3 would stop well before it had spent its line. S3.2 would also have to
  correct arm C's cost before comparing it with arm B at equal cost.
- **Count the billed total for every run, S1 to S2.7 too.** One rule for all runs. Not chosen:
  it would change September's counted spend and S2.7's spend line after decisions cited them.
- **Price cached tokens in `cost_usd`.** This would make the computed price nearer the bill.
  Not chosen: there is no measured cached price (plan Task 3), and it would change what the
  per-case cap measures.

## Status

Accepted, 2026-10-01 (Andy, after the S3.1 batch smoke run).

## Glossary

- **Batch round**: one set of calls sent together at half price. Its total cost is reported when
  the batch ends.
- **Billed total**: `reported_batch_cost_usd`, the sum of the costs the batch rounds reported.
- **Cached token**: a prompt token the provider has already seen in an earlier call of the same
  conversation. It is billed at a lower rate.
- **Computed price**: `cost_usd`, the sum of each call's cost; a batch call is priced from the
  price table, every prompt token at the full rate.
- **Monthly guard**: the check every paid command makes that the month's spend, plus open
  reservations, plus its own projection, fits the monthly budget.
- **Spend line**: a stage's limit on what it may spend, counted by commit (`make s3-spend`).
- **Tool post-pass**: arm B's coding tools and answer, run over a finished arm B run
  (`ntsb-eval tools`), written as a derived run `<run id>-tools`.
