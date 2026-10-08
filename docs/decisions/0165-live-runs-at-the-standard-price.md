# 0165 — Live runs use the standard price, one call at a time, and a sync loop run can be resumed

From Andy, 2026-10-08, during S3.3's first paid live morning. Supersedes
[0158](0158-live-runs-on-the-mac-at-the-batch-price.md) items 2 and 3 (the batch price, and the
batch-window timing); 0158 item 1 (runs on the Mac through `paid_run.sh`) and item 4 (S4 chooses its
own service) stand. Detail: the S3.3 plan's Deviations (Task 11).

## Context

1. **0158 chose the batch price** because nobody watches a closure run as it happens, so speed
   seemed to buy nothing, and batch was half the price and the service Ellery version 1 was
   measured on. The estimate was "about 1 to 2 hours" for 10 to 15 rounds, from S3.2's batches of
   400 requests.
2. **The first paid morning** (one case, 2026-10-08, started 06:55 UTC) showed that a batch of a
   single request waits far longer: its rounds waited from about 2 minutes to about 3 hours each,
   most of the time queueing, not working; after 10.5 hours it had finished nine rounds and was
   still waiting on the tenth (ad-hoc, read from the morning's log; S3.3's report script re-derives
   the run's minutes). A 10-case morning needs the same number of rounds, so it would take a day or
   more.
3. **A long morning is not free.** While it runs it holds the Mac awake, the live lock, and every
   push to the branch (a live run cannot resume on different code), and the next morning cannot
   start.
4. **A sync run could not be resumed.** `scoring/runner.py:refuse_sync_resume` refuses a resumed
   sync run because the evaluation runner's sync path records no replies. The loop's sync driver
   does: `agent/drive.py:drive_sync` writes each reply to `replies.jsonl` as it arrives and replays
   them on a resume, so only calls not yet answered are sent again.

## Decision

1. **Live runs use the standard price, through the sync driver** (`price_variant="standard"`,
   `sync=True`). The model, reasoning level, reply budget, text and tools are unchanged; the label
   stays `VERSION_1`. The pinned live settings (`live.morning.VERSION_1_SETTINGS`) record the new
   price variant.
2. **A sync run of the loop (arm C) can be resumed**: the refusal applies to the evaluation
   runner's arms only. An interrupted live morning is resumed by the next morning exactly as
   before; every reply already on disk is replayed, not paid for again.
3. **The projection per case for the caps** (`EXPECTED_COST_PER_CASE_USD`) is raised to reflect
   the standard price. The caps themselves stand: $0.30 a case, $5 a month of live spend, S3.3's
   stop at $10 of its own spend (decision 0163).
4. **The batch-window timing is dropped**: a morning starts any time after the recorder's night
   has finished; the late-start warning, which was about the batch queue, goes.

## Why

1. **A morning must end in a sitting.** At the standard price a 10-case morning takes about half an
   hour (about 12 calls a case at about 12 seconds each, `docs/results/s3-probe-dev.txt`), so the
   Mac, the lock and the branch are free again the same morning.
2. **The cost stays small.** The standard price is about twice the batch price per token; at the
   held-out loop's $0.0098 a case computed on batch, that is about $0.02 a case, more on large
   dockets, inside every cap.
3. **The roadmap's live path is the standard price** (roadmap §4, "The live path does not" use
   batch); S3.3 now rehearses it, so S4 inherits a measured live path.
4. **Andy, 2026-10-08:** "Yes we need to change to standard pricing, this won't work".

## What this rules out

- **Staying on batch.** The strongest case: half the price, and the exact service version 1 was
  measured on. Rejected: one case took more than ten hours, which makes daily mornings unworkable.
- **Batch with many cases per round to shorten the waits.** The waits are per batch, not per
  request, and the 10-a-day limit (0157) caps the batch size; it would not shorten a morning enough.
- **Recording an interrupted sync run's cases as not coded.** Simpler. Rejected: an interruption is
  the system's fault, not the case's; the spec resumes an interrupted run (§6).

## Status

Accepted, 2026-10-08 (Andy, during S3.3's first paid morning).

## Glossary

- **Standard price**: the provider's normal service; answers in seconds, at the full price.
- **Sync driver**: the loop's driver that sends one call at a time and records each reply.
- **Resume**: continuing an interrupted run from its folder, replaying the replies on disk.
