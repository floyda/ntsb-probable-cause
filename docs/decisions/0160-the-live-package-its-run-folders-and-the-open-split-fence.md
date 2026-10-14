# 0160 — The `live` package, its three seams, run folders built to move, and the open-split fence in code

From the S3.3 design session with Andy (2026-10-07). Detail:
[the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §8. Corrects the premise of
[0154](0154-the-live-run-is-at-closure.md) item 5 that a docket document can be "classed as
synthesis".

## Context

1. **S4 runs the same work in the cloud**, writing to its own store and ledger.
2. **The $40 guard reads spend from `data/runs/*/run.jsonl`** (`scoring/budget.py`), so live run
   folders must live there to be counted.
3. **Live cases are open-split cases** ([0024](0024-open-split-enters-measurements-only-as-numbers.md)).
4. **Disk space** (ad-hoc, `du`, 2026-10-07): the development docket cache holds 1,603 cases in
   28 GB, about 17 MB a case; a loop run's folder is about 80 KB a case.
5. **There is no synthesis class of docket document.** Decision
   [0056](0056-the-deny-list-cannot-be-filled-from-titles.md) removed title-based classing: every
   readable document is offered (`docket/filter.py`), and the reader's statuses are five (`read`,
   `unreadable: scan`, `unreadable: not a pdf`, `skipped: photo-only`, `fetch failed`;
   `docket/manifest.py`). Withheld text is caught by the guard on the text: a probable-cause
   sentence refuses the whole case, and an analysis or narrative sentence marks it
   ([0077](0077-analysis-sentences-in-docket-documents-mark-the-case.md), 0078).

## Decision

1. **A library package, `live`, and a command, `ntsb-live`**, named for what they become in S4.
   The run is the existing `AgentRunner`, unchanged, given fetched records.
2. **Three seams**, each with only its local version in S3.3: where results are written (local run
   folders; S4 adds its store), where spending is counted (the local run folders), and where the
   store copy comes from (`store/sync.py`'s `pull`, read-only).
3. **Run folders under `data/runs`, sample `live`, built to move to a private bucket:**
   self-contained (no absolute path; the raw records and the closure night copied in), every file
   versioned, no secret, and a manifest of every file's size and SHA-256.
4. **The closure record**, one per case, holds what S4 and the site need: the closure night and
   wait; when it was coded; the commit, prompt version, price, model and training cut-off; the
   lockfile's checksum; each listed document's title, the reader's status for it and Ellery's read
   or skip; whether a preliminary narrative was present; the outcome, marks and scores. Titles
   only, never document text.
5. **The open-split fence, in code:** every development and evaluation command refuses a `live`
   run; live documents go to their own cache (`data/live-docket/`); nothing in the library or the
   other commands imports `live`; `live` cannot upload the store; only the counts file is
   committed.
6. **Cleanup:** when a run has finished, its downloaded documents and the store copy are deleted.
7. **No document is shown as "withheld as synthesis".** For S4 and S5, a document that held the
   NTSB's probable cause appears as the case's "not coded: guard"; marks appear as marks.

## Why

1. **Reuse without rework.** The queue, fetching, run and scoring carry into S4 unchanged; only
   the seams gain cloud versions. Andy: "Yes that's much better, less work and confusion later".
2. **Portability without design.** Andy: "local run folders with S3 bucket in mind without
   designing it". The four folder rules make the move a plain copy.
3. **A guarantee is code, not a sentence** (0016; S1's review lesson).
4. **Disk.** Andy: "I will also need to be careful on disk space so some cleanup might be
   important". Without cleanup about 100 closures a month would add about 1.7 GB (estimate).
5. **The correction** follows the code: the closure record can only report statuses that exist.

## What this rules out

- **A copy to S3 now.** Durable and ready for S4. Rejected: it puts open-case model text in the
  cloud before S4 designs where it belongs, and S4 re-codes the backfill anyway.
- **The recorder's store as the home for live results.** Rejected: the store has one writer, the
  03:00 task, and holds only what the recorder observes, never verdict-derived data.
- **A package named `shadow`.** Rejected: S4 would rename or rewrap it.

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07; the correction
of Decision 7 found while writing the plan, the same day, and recorded in the specification §8.2).

## Glossary

- **Seam**: a narrow point where one implementation can be swapped for another.
- **Manifest**: a list of every file in a run folder with its size and checksum.
- **Mark**: a note on a case (0077, 0078) that never reaches the model.
