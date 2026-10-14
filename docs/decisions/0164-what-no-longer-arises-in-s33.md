# 0164 — What no longer arises in S3.3: the expected-change field moves to version 2; no later triggers; no "more may arrive"

From the S3.3 design session with Andy (2026-10-06), after decisions 0154 to 0156 settled the
live run. Detail: [the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §3.3 and
§15. Amends the timing of [0148](0148-results-one-and-four-made-measurable.md) item 4.

## Context

1. **0148 item 4** placed a structured expected-change field ("expected change: none / confirms /
   changes the answer to ...") with "the agent's next text change (S3.3)".
2. **0156** puts version 1, unchanged, on the board; a change of text is a new version.
3. **0122** built later triggers (`agent/later.py`) for live cases, where evidence was expected to
   arrive in several steps.
4. **At closure the docket is complete**: of 300 documents that appeared at closures, none
   appeared later (`docs/results/s5-recorder-report-2026-10-06.txt`).

## Decision

1. **The structured expected-change field moves to version 2.** It changes Ellery's text, so it
   cannot come with version 1.
2. **`later.py` stays built, tested and unused on live cases.** Each case is coded once, at
   closure ([0157](0157-s33-codes-closures-through-a-queue.md)), so no later trigger happens.
3. **Ellery is not told that more documents may arrive.** At closure the docket is complete, and
   telling it would change its text.

## Why

1. **Version 1 runs as measured** (0156); every one of these would change what it receives or how
   it runs.
2. **The questions were the S3 specification's**, written when live runs were planned on open
   cases with evidence arriving over months; 0154 removed that premise.

## What this rules out

- **Adding the field in S3.3 as version 1.1.** It would make result 4 testable sooner. Rejected:
  a new version needs a registered comparison before the board (0156 item 4), and that work
  belongs with version 2.

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).

## Glossary

- **Expected-change field**: a structured prediction of how a document will move the hypothesis.
- **Later trigger**: a second run on a case when new evidence arrives (0122).
