# 0162 — The preliminary narrative is left out of live runs, and its presence is counted

From the S3.3 design session with Andy (2026-10-07). Detail:
[the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §5. Answers the S3
specification's §20 open question.

## Context

1. **Evaluation never has the preliminary narrative**
   ([0023](0023-evidence-by-source-with-measured-availability.md) item 5): the API is said to delete
   it at closure, and S0 found it empty in all 19,641 closed cases.
2. **Whether it is already gone on the closure night**, when a closure run reads the record, has
   not been checked.
3. **`split_record` treats it as evidence** (`fields.py`), and the payload renders every evidence
   role that holds a value, so a live run would send it if the API still held it.

## Decision

1. **Every live run excludes `prelim_narrative`**, through the split's existing exclusion set. The
   model's text is then identical to a record without one; the prompt version is unaffected.
2. **Each run records whether the API still held one**, and the results file counts those cases.

## Why

1. **Live runs then match evaluation whatever the API does on the night**, so version 1 runs live
   on the evidence it was measured on.
2. **The count turns an unchecked assumption into a number** for S4.
3. **Andy, 2026-10-07:** "A kept out".

## What this rules out

- **Leaving it to the API.** Simpler. Rejected: some runs could silently see evidence evaluation
  never had, and nothing would record which.
- **Reading it on purpose**, from the record or the recorder's copy. Rejected: at closure the
  docket holds the fuller account, and a new input makes a new version
  ([0156](0156-the-board-runs-ellery-version-1.md) item 4).

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).

## Glossary

- **Preliminary narrative**: the investigator's early account, published weeks after the accident.
- **Exclusion set**: the evidence roles a run leaves out; the split builds the evidence without them.
