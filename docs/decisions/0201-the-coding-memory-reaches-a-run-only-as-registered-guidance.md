# 0201 — The coding memory reaches a run only as registered, fingerprinted guidance

From Andy, 2026-10-14. Detail: `docs/specs/2026-10-08-coding-memory-design.md` §3 and §5.

## Context

1. **The learner writes a memory file** from development verdicts
   ([0200](0200-a-model-may-read-development-verdicts-to-learn-coding-lessons.md)). It changes
   from period to period.
2. **Guidance already has a safe path into a run**: a named file, a fingerprint in the prompt
   version, and a registration committed before use (decision
   [0098](0098-guidance-rounds-stop-rule-and-prediction.md)); `make s27-check-guidance` checks
   that no guidance sentence is in withheld text.
3. **Ellery version 1 is frozen.** Its fingerprint covers the text of `r3-loc-stall` and
   `r6-aircraft-control`, the code tables, `scoring/tables/coding_stats_s3.json` and the
   model-facing text in `agent/` and `model/tool_text.py`; every live night refuses to run if it
   moves (S4, 2026-10-14).

## Decision

1. **A memory snapshot is a file**, one per period, named for its period and fingerprinted.
   It reaches an answering run or a coding test only by name, and the run's prompt version
   carries its fingerprint.
2. **Before any use, a snapshot passes three checks**: no lesson shares a sentence with the
   withheld text of any case it may be scored on (the guidance check); no lesson copies a run of
   eight or more words from any pool probable-cause sentence; no lesson holds a case number, a
   date, a place, a registration, a name or an operator. They run in three places, because the
   first two need case data that is never in git (rule 4):
   - **Locally**, a command runs all three and writes a stamp beside the snapshot: its
     fingerprint, the checks run, how many sentences each compared against, the date and the
     commit. The stamp is committed with the snapshot.
   - **In continuous integration**, which has no case data, the identifier check runs on every
     committed snapshot, and every snapshot must have a stamp whose fingerprint matches it. A
     snapshot edited after its check fails.
   - **In the code**, a coding test or a run refuses a snapshot without a matching stamp.
3. **A run that uses a snapshot needs its own registration** under `docs/rounds/`, committed
   first, naming the snapshot.
4. **Nothing in version 1's fingerprint is edited.** A memory is never added to Ellery version 1,
   to S4's nights or to the board. It can enter only a later version, measured as one, by Andy's
   decision.
5. **The cap is about 6,000 tokens** (Andy, 2026-10-14), roughly 60 lessons. A lesson enters a
   full memory only by beating the weakest lesson on counted support; every snapshot records the
   lessons pushed out and their support.

## Why

1. **One path for text that steers the model.** Guidance and memory are the same kind of thing:
   words placed before the evidence. Reusing guidance's path reuses its guard and its record.
2. **The checks catch what the learner might carry.** A lesson is meant to be general; the
   checks prove it holds no withheld sentence, no copied cause and nothing that identifies a
   case. These are fatalities, and rule 6 applies to every lesson. Each check runs where its
   inputs are, and the stamp ties the local result to the exact file, so nothing unchecked is
   committed unnoticed or used. Eight words allows common phrases ("the pilot's failure to
   maintain") and catches a quoted cause (Andy, 2026-10-14).
3. **Leaving version 1 alone keeps S4 sound.** S4's done-means needs every live case coded by
   version 1 (S4 specification §17).

## What this rules out

- **Retrieving lessons per case by a tool.** Smaller prompts. Rejected for now: it adds a
  retrieval step with its own contamination test, before the memory has shown it helps.
- **No cap.** Simpler. Rejected: a growing memory gets hard to audit and invites lessons that
  help one group and hurt another (round 6, [0106](0106-round-6-kept-by-override.md)).
- **Editing `r3-loc-stall` or `r6-aircraft-control` to carry lessons.** Rejected: it moves
  version 1's fingerprint and stops S4's nights.

## Status

Accepted.
