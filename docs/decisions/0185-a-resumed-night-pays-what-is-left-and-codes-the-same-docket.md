# 0185 — A resumed night pays only what is left, and codes the docket it began with

From the S4 final review, 2026-10-12. Amends [0170](0170-live-runs-have-their-own-key-and-the-full-cap-rule.md)
(the full-cap rule on a resume), [0175](0175-fetch-failures-are-counted-and-every-message-has-a-runbook-row.md) and
[0176](0176-the-docket-is-frozen-by-its-hashes.md) (what the closure record's hashes describe).
Detail: the S4 specification, §9.3, and the plan's Deviations ("final review, wave A").

## Context

1. **A night killed mid-run is resumed the next night from the bucket** (decision 0177; the run
   folder is pushed after every reply). The cases' results are written only when the run ends, so
   a killed run's cases all read as unanswered.
2. **The resume's money check charged every unanswered case a fresh $0.30.** The room it was
   compared with had already lost what the killed run spent. A full night killed mid-run was then
   refused every night until the month's spend reset. A reviewer showed this with a test.
3. **A resume fetched each docket again**, because the container's docket cache is not kept
   between nights (0176 item 2: no document is kept). The closure record's hashes then described
   the second fetch. If the NTSB changed a document in between, the record named a file the case
   was not coded from, and the replayed calls could fail and crash the night every night.

## Decision

1. **A resume is charged the remaining exposure.** For each unanswered case, that is $0.30 less the
   computed cost already recorded for it, and never below zero. The sum must fit the night's room
   (0170). The billed spend in `usage_monthly` is at most the computed cost, so this never lets a
   night spend past the cap.
2. **Each run records its dockets before its first model call**, in `dockets.json` in the run
   folder: for each case, the listing page's SHA-256, a SHA-256 of the parsed listing entries
   (position, title, link), each document's SHA-256 and the documents first offered. It holds
   hashes and positions only, never a title or any text. The closure record's hashes come from it.
3. **A resume compares the re-fetched dockets with `dockets.json`** before any model call, using
   the parsed entries and the document hashes, not the page bytes, which can change for unrelated
   reasons. If any case's docket differs, the night refuses the resume with the alert
   `docket-changed`, and Andy tells Claude. A docket that fails to fetch on resume stays the
   `fetch-failed` stop (0175) and counts against no case. The run is never finished on different
   evidence.
4. **A resume that fails for any other reason stops the night with the alert `resume-failed`.**
   The steps that need no store (later scores, the export, the night record) still run, so the
   failure does not repeat as a crash.

## Why

1. **A crash on a launch night must not stall the backfill for weeks** while the runbook says to
   do nothing.
2. **0176's audit claim is that the hashes show which file was coded.** That is only true if the
   hashes are taken when the case is coded, not on a later fetch.
3. **Refusing is honest and rare.** It needs a kill and a changed docket on the same case. Dropping
   only the changed case was preferred, but the runner's resume compares the whole run
   specification, case list included, so one case cannot be removed from a run.

## What this rules out

- **Charging a full $0.30 a case on resume.** Rejected: see context 2.
- **Hashing the docket at closure from a re-fetch.** Rejected: see context 3.
- **Keeping the documents in the bucket until the run finishes.** It would let a resume read the
  same files. Rejected by 0176 item 2: no document is kept.
- **Finishing a resumed case on a changed docket.** Rejected: the case would be coded from
  evidence the model never saw in full.

## Status

Accepted, 2026-10-12 (Controller ruling in the final review, under Andy's approval of the plan; put
to Andy at the deploy hand-off).
