# 0153 — A counts-only diagnosis of S3.2's held-out runs, fixed before it is read

Extends [0142](0142-frozen-means-an-unchanged-prompt-version.md)'s single use of `heldout-400` by
one reading of the runs already made. From Andy, 2026-10-05, after S3.2's verdict: "I think it has
to be B otherwise how can I determine where to focus my efforts".

## Context

1. **The verdict** (`docs/results/s32-claims-heldout.txt`): on `heldout-400` the loop is worse than
   S3's full arm B on occurrence top-1, −9.5 points [−14.0, −5.2], at equal billed cost. On
   `dev-400` the two were level.
2. **What the committed numbers already say.** The loop's 6 failures explain at most about 1.5 of
   the 9.5 points (the both-answered reading is still −8.9 [−13.2, −4.6]). On `dev-400`, arm B's
   fixed coding step added +6.8 points of top-1 to its answer
   (`docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`), while removing the loop's coding tools
   changed nothing measurable (`docs/results/s32-coding-ablation-dev.txt`). The loop read every
   document on offer on only 41.9% of dockets with five or more documents, and without the docket
   it loses −8.5 points.
3. **What they cannot say**: how the held-out gap divides between the coding step, skipped
   reading and the rest. Only the held-out runs hold that, and `dev-400` shows no gap to divide.
4. **The rule it touches.** Held-out is read only for a registered use (0026, 0142). This reading
   is not part of S3.2's registration.

## Decision

1. **One diagnostic reading of S3.2's six held-out runs** (arm A; arm B's answer, tool
   post-pass and ordering check; the loop; the loop without the docket), by one committed script,
   `scripts/exploratory/s32_heldout_diagnosis.py`, which writes
   `docs/results/s32-heldout-diagnosis.txt`. No model call, no new run, $0. Counts only: no case
   number, no case or model text. The script refuses to read a held-out run unless this record is
   committed.
2. **The breakdowns are fixed here, before any is read**, all on occurrence top-1 under S3.2's
   failure rule (decision 0146) unless stated, with paired 95% intervals:
   1. **Arm B by stage**: the loop against arm B's answer alone, after its tools step, and after its
      ordering check; and arm B's own stages against each other (answer → tools, tools → check).
      This places arm B's lead.
   2. **The gap by group**: loop minus arm B (final) for fatal and non-fatal cases, and by documents
      offered (none, 1, 2–4, 5 or more).
   3. **Reading**: the gap on cases where the loop read every document on offer against cases where
      it left some unread; and within the loop, top-1 of its hypothesis before reading (H0) against
      its answer, on the cases it answered.
   4. **Coding**: within the loop, its last hypothesis before coding against its answer — how
      often coding changed the first code, and how many changes fixed or broke it; the same count
      for arm B's tools step (answer → tools) and for its check (tools → check).
   5. **Failures**: each arm's failures by kind (as printed in the claims file), and the gap with
      the loop's failed cases left out.
   6. **Wins and losses**: cases right in arm B only and in the loop only, overall and in the groups
      of item 2.
3. **It decides nothing and claims nothing.** It is exploratory (decision 0059). Its use is to
   choose what to work on next; every figure is read as a lead, with its interval.
4. **The cost is written down now: `heldout-400` can no longer test a later version of the agent.**
   Once its errors have shaped what is changed, a held-out score for the changed agent would be
   flattered. A later version (v2, decision 0140) is tested on `dev-seal-s3-400`, still sealed, and
   head to head on live cases; any further held-out use needs a new sample from later years and
   its own record.

## Why

1. **Effort should go where the loss is.** The committed numbers name two suspects, the coding
   step and skipped reading, and cannot tell them apart.
2. **Fixing the breakdowns first** keeps this a measurement, not a search through the data for a
   story.
3. **The cost is small and stated.** `heldout-400` was already closed for v1
   (`docs/rounds/s3-2-used.md`), and v2's tests were already planned on the sealed sample and on
   live cases (0140, 0141).

## What this rules out

- **Diagnosing on `dev-400` only.** Clean and free. Rejected: the arms were level there, so it
  cannot show where held-out's 9.5 points went.
- **Reading held-out freely.** Faster. Rejected by Why 2.
- **A new held-out run to test a hypothesis.** Rejected: it would spend held-out on a question,
  and v2's test belongs to the sealed sample and the live board.

## Status

Accepted, 2026-10-05 (Andy, after S3.2's verdict).

## Glossary

- **Exploratory**: a script that sets no bar and decides nothing (0059).
- **H0**: the loop's hypothesis before it reads any document.
- **Fix / break**: a change of first code that turns a wrong answer right, or a right one wrong.
