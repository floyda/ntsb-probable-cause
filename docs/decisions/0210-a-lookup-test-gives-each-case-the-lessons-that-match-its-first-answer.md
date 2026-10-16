# 0210 — A lookup test gives each case the lessons that match its first answer

From Andy, 2026-10-16 ("Yes let's give this a go"). Detail: the registration
`docs/rounds/memory-lookup.md` and the plan `docs/plans/2026-10-16-coding-memory-lookup.md`.

## Context

1. **The pilot's memory was one fixed note for every case.** All of it was read on every call, so
   it was capped at 6,000 estimated tokens (0201). It held 15 lessons after 2010; the learner had
   written 198, about 63,000 tokens. The median kept lesson is about 416 estimated tokens, against
   the 100 the design note assumed (§11 question 3).
2. **The kept lessons barely touched findings**, the measure the stop rule reads: the 15 name 7
   finding categories, the 198 name 60.
3. **0201 put off looking lessons up per case** "before the memory has shown it helps". The cap
   made that hard to show, and the count behind the cap was faulty (0209).
4. **Looking up past cases did not help once**: S3.1's precedent probe found the nearest earlier
   cases "not promising" for first codes and for findings
   (`docs/results/s3-precedent-probe-dev.txt`, `s3-finding-precedent-dev.txt`). Lessons are not
   cases, but the warning stands.

## Decision

1. **A lookup condition is added to the coding test.** After the model's first answer (tables run
   a), a script picks for each case up to five lessons from `pilot-2010-recount` whose codes match
   that answer, and the coding tools' post-pass runs with those lessons in place of the whole
   memory. The exact rule for matching, ranking and the support floor is in the registration.
2. **The query is the model's own answer.** Its occurrence codes and finding categories decide the
   match. In the coding test the model's input is the NTSB's probable-cause sentence (0205), so the
   test measures coding alone; on a live case the query would be the agent's own draft.
3. **The refilled note is run beside it.** The memory condition re-run on `pilot-2010-recount`
   (6,000-token cap, corrected ranking) shows how much of the pilot's thin result came from the
   faulty count.
4. **A registration is committed first** and names the stop rule; lookup runs are refused without
   it. Andy signs it before either paid run.
5. **No learner call.** Both runs reuse lessons already paid for. The coding tests count on the
   $40 guard and the side track's $10 line.

## Why

1. **It tests the question the pilot meant to ask**: whether learned coding knowledge helps, with
   each case shown the lessons for its own situation rather than the same 15.
2. **Matching by codes needs no new model.** Every lesson lists the codes it predicts, so a script
   matches them, as the coding tools look up counts; it gives the same result every time and can
   be read and checked.
3. **It is cheap.** The two pilot memory runs cost $0.1315 and $0.1339; a lookup run reads fewer
   lesson tokens per case.

## What this rules out

- **Matching by text similarity.** Not now: it needs an embedding model, a new dependency, and is
  harder to explain. Added only if code matching reaches too few lessons.
- **The full pass as designed** (periods to 2019 under the fixed cap). Not run: each year adds
  lessons and the cap keeps the same few; 2010 pushed out 183, against 87 after 2009.
- **Connecting the memory to Ellery version 1, S4 or the board.** Unchanged from 0201.

## Status

Accepted. Amends 0201's "What this rules out" (retrieving lessons per case) for this test only.
