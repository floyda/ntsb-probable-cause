# 0204 — The coding test, the agreement check and the pilot's stop rule

From Andy, 2026-10-14. Detail: `docs/specs/2026-10-08-coding-memory-design.md` §6 and §7.

## Context

1. **Running the agent to measure each memory snapshot is slow and docket-heavy.** A cheaper
   measure is needed after every period.
2. **The memory must beat the counts, not nothing.** S3's fixed coding-tools step already adds
   top-1 +6.8% and finding recall@10 +4.7% to S2.7's answer
   (`docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`).
3. **Findings are what the NTSB codes most consistently**: identical cause sentences agree on
   flagged findings at recall@10 74.1%, against 37.5% on the first occurrence code
   (`docs/results/s3-finding-consistency-dev.txt`, `s3-coding-consistency-dev.txt`). They are the
   live board's headline ([0029](0029-live-headline-is-the-finding-score.md)).

## Decision

1. **The coding test.** GPT-6 Luna, batch, reasoning `medium`, codes a case from its NTSB
   probable-cause sentence and the code tables, answering in the agent's format (up to three
   occurrence guesses; findings in the two stages of
   [0025](0025-scoring-targets-from-ntsb-code-tables.md)), scored with the harness's columns.
   Three conditions: **tables**; **counts** (the tables and the coding tools' output in arm B's
   fixed order, from `coding_stats_mem`, [0203](0203-the-steering-slice-and-statistics-without-it.md));
   **memory** (the counts and a snapshot).
2. **The noise.** The tables and counts conditions run twice each on the steering slice. The
   noise is the paired difference between the two counts runs, on each measure.
3. **The agreement check.** Before Haiku 5.5's apply decisions count, Haiku at effort `low` and
   Sonnet 5.5 at effort `high` (the reference) decide which lessons apply on the same 100
   learning-part cases. Haiku is accepted if it agrees with Sonnet on at least 90% of the
   case-and-lesson pairs that either model marks as applying. If it misses, Haiku at `medium`
   is checked once on the same cases by the same bar; if it misses again, Sonnet applies, at
   `high`.
4. **The pilot.** Learn 2009, then 2010 (one event year a period, Andy 2026-10-14), running the
   memory condition after each.
5. **The stop rule** (Andy, 2026-10-14). The pilot passes only if the memory condition beats the
   counts condition on finding recall@10 by more than the noise, and is not worse beyond the noise
   on occurrence top-1 or top-3. Otherwise it stops and is reported as it stands. Top-1 and top-3
   are reported either way; a gain there without a finding gain is "not passed", and any override
   is Andy's, in a record.
6. **The registration** `docs/rounds/memory-pilot.md`, naming the conditions, the noise, the
   agreement check and the stop rule, is committed before the first memory condition runs. If
   the pilot passes, the full pass and the transfer check on `dev-400` get their own registration.

## Why

1. **It measures coding alone, on the product's model.** The reading of the evidence is taken
   out, so a change in score is the memory's.
2. **Memory against counts is the fair comparison** (context 2).
3. **One named measure is harder to pass by luck** than any one of three, and it is the one the
   measurements say the memory can move (context 3).
4. **A 90% bar on the pairs either model marks** ignores the many easy "does not apply" answers,
   which would make almost any model look in agreement. The 90% itself is judgement, not a
   measurement (Andy, 2026-10-14).

## What this rules out

- **Measuring each snapshot with a full arm B run.** Closer to the product. Rejected: slower and
  docket-heavy; it is kept for the transfer check, once.
- **A gain on any of top-1, top-3 or findings.** More forgiving. Rejected: three chances to pass by
  luck, and no stated purpose.
- **Accepting Haiku without a check.** Cheaper. Rejected: its errors would enter every support
  count.

## Status

Accepted.
