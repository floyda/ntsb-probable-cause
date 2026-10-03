# 0081 — Transcription is evidence preparation, costed apart from the agent's per-case cap

Extends [0030](0030-cost-in-usd-cap-and-budget-in-code.md).

## Context

0030 has two limits: a per-case cap on what the agent spends deciding one case, and a monthly
budget on all spending. Transcription is a third kind of cost: paid once per page, then reused
by every run, every arm and, later, the loop and the live path. A fatal docket with 120 scanned
pages costs roughly $0.03 to transcribe at the front-runner's price (estimate), against a
per-case cap of $0.05.

## Decision

1. Each page is transcribed once and cached, keyed by the page image's hash, the model, the
   instruction's version and the resolution. The cache sits under `NTSB_DATA_DIR`, never
   committed.
2. Transcription cost counts against the **monthly budget** and its reservation (0045).
3. It does **not** count against the agent's **per-case cap**. It is recorded per page and
   reported per case in its own column.

## Why

1. **The cap bounds the agent's reasoning, not the evidence's preparation.** Counting it would
   leave the least room to reason in the cases with the most scanned evidence.
2. **Equal cost between arms (0022) must not depend on run order.** Arm B and the loop share one
   cache; charging it to whichever run came first would make the comparison order-dependent.
3. **Nothing is hidden.** The per-case column lets the Methods page show both the agent's spend
   and the whole cost of a case.

## What this rules out

- **Transcription inside the per-case cap.** Rejected for reasons 1 and 2.
- **Transcribing afresh in every run.** Pays the same cost many times and lets runs differ by a
  transcription's randomness.

Andy's note, carried to S3: the agent's cap might itself scale with the amount of evidence.
Whatever S3 decides, arm B and the loop get the same cap on the same case, enforced before the
call.

## Status

Accepted, 2026-09-23 (Andy: "Yes keep it out").
