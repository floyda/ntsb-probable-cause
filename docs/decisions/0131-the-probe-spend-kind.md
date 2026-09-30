# 0131 — The `probe` spend kind, and the relabel of the learning probe's rows

From the S3 design session (2026-09-29 to 2026-09-30): spend kind choice B. Detail:
[the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §10.1 item 2.

## Context

Paid work that is not an evaluation run is written as `SpendRecord` rows, in one `spend.jsonl`
per job ([0081](0081-transcription-is-evidence-preparation.md)). A row's `kind` is one of
`inventory`, `transcriber-test` and `transcription`, and the reader refuses any other kind.

The learning probe (pull request #18) wrote its rows with the kind `inventory`, the closest
existing kind. A new kind would have made `month_spent` fail on every other branch that read
the shared runs folder. It was a known mislabel, logged in the probe plan's Deviations and
reported to Andy (`docs/plans/2026-09-29-s3-learning-probe.md`). `inventory` names S2.6's page
inventory, not a probe.

The three jobs and their costs (the probe plan's Deviations, and the two probe reports):

| job | what it was | cost |
|---|---|---|
| `s3-probe-20260929T122117-64b8cee` | smoke run, 1 case | $0.0692 |
| `s3-probe-20260929T123038-64b8cee` | run 1, 20 cases | $0.5542 |
| `s3-probe-20260929T130538-551c884` | run 2, 20 cases | $0.5721 |

In all $1.1954, counted in September's total (probe plan Deviations). S2.8's branch was the
other work that constrained adding a kind (spec §10.1 item 2); S2.8 is now cancelled
([0132](0132-s28-is-cancelled.md)).

## Decision

1. **`SpendRecord.kind` gains `probe`**: paid work that tests a shape or a flow, and is neither
   an evaluation run nor evidence preparation. S3.1's native-tool shape probe writes it
   ([0124](0124-native-tool-calling-and-a-cacheable-conversation.md)).
2. **The three jobs' rows are relabelled** from `inventory` to `probe`. Costs, calls and every
   other field stay unchanged.
3. **The original rows are kept beside the new ones**, in each job's folder, as
   `spend-before-relabel.jsonl`. The budget code reads only `spend.jsonl` (`month_spent` and
   `stage_spent` read `*/spend.jsonl`), so nothing is counted twice. A test proves it (spec §16).
4. **The relabel runs once**, by a script that refuses if the kept file already exists or if
   any row's kind is not `inventory`, and that checks the total is unchanged.

## Why

1. **A row should say what the money bought.** Any count by kind would otherwise put the
   probe's $1.1954 under S2.6's page inventory.
2. **Nothing is lost.** The original rows stay as they were written, and the month's total does
   not move.
3. **The reason for waiting is gone.** With S2.8 cancelled, no other branch in use reads the
   shared runs folder with the old reader.

## What this rules out

- **Leaving the rows as `inventory`, with the mislabel noted.** No code change. Rejected by
  Why 1.
- **Rewriting the rows in place, with no copy.** Simpler. Rejected: it would lose what was
  written at the time.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
