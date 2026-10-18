# 0214 — Every embedding lookup goes to the coding test, which decides; one is confirmed on dev-seal-400

From Andy, 2026-10-18: "Can we send out a fable reviewing subagent to look at if there is
something we have missed or find a reason/cause", then, after the review: "I approve all runs
required to confirm once and for all the benefits available". Detail: the design note
`docs/specs/2026-10-08-coding-memory-design.md` §13.13, the registration
`docs/rounds/memory-embed-coding.md` and the plan `docs/plans/2026-10-18-coding-memory-embed-coding.md`.

## Context

1. **0213 stopped at its free gate.** On `dev-steer-400`, three embedding models and a picking
   call each found an agreeing lesson for more cases than today's cause lookup, at best +5.5
   points [+2.7, +8.2], but at lower precision (36.3% at best against 45.6%), so no coding run
   was made (`docs/results/memory-coverage-dev.txt`).
2. **An independent review read the run folders on 2026-10-18.** It found no bug: it rebuilt the
   coverage file exactly. It found that the gate's precision mostly measures the first code
   (`docs/results/memory-proxy-check-dev.txt`, a free exploratory check written after it):
   - A lesson agrees only if every part it predicts matches. 103 of the 106 eligible lessons
     predict a first code, and all 106 predict finding categories.
   - On the first-code part, today's lookup is right 45.2% of the time (379 of 839),
     `openai/text-embedding-3-large` 25.1%, the picking call 37.3%. On the finding part, 94.3%,
     80.9% and 90.8%.
   - On the finding part the new lookups reach more cases than today's: +9.0 points [+6.2,
     +12.0] for the large model, +6.2 [+3.7, +9.0] for the picking call. The memory's measured
     benefit is on finding recall@10 (0211, 0212).
3. **The comparison was not like for like.** Today's lookup hands out 0 to 5 lessons (39, 90,
   113, 93, 47 and 19 cases); embedding search always hands out five, and precision falls with
   rank for every lookup (today's 51.9% at rank 1, 31.6% at rank 5). A five-a-case lookup could
   not reach a precision set by a lookup giving 2.19 a case.
4. **Agreement is a weak guide to the coding benefit.** In today's cause-lookup coding run, by
   its lessons, finding recall@10 against counts(a): cases with no lesson −5.1 points (noise in
   the same cases −6.2), lessons none agreeing +5.3 (noise +3.6), at least one agreeing +2.8
   (noise −1.9); top-3 +7.0 where a lesson agrees (noise +0.9). Over their own noise the cases
   with an agreeing lesson gained more, mostly on top-3, so first-code agreement is not
   irrelevant either. The coding test measures what counts; lesson coverage cannot stand in for
   it.
5. **A coding run is cheap.** About $0.18 on OpenRouter (the steering cause lookup cost $0.1814);
   the side track's $10 line has $8.12 left (`make mem-spend EST=0`, 2026-10-18).
6. **The picking call cost $2.8987 of plan credit** (its run's spend row, printed by the proxy
   check), 1.86 times the apply step's $1.5604, not "a fraction" of it as 0213's "Why" item 5
   expected.

## Decision

1. **0213's coverage gate is not used again.** Its result stands as published. Lesson coverage
   is printed from now on as a description only, with each part apart.
2. **Four candidates go to the coding test**, all over 0213's `openai/text-embedding-3-large`
   embedding run on the steering slice, the snapshot `pilot-2010-recount`, K = 5 and the
   support floor of 10:
   - **`openai/text-embedding-3-large`**: the five nearest by cosine (0213's lookup);
   - **`pick:openai/text-embedding-3-large`**: 0213's picking run, unchanged;
   - **`fit:openai/text-embedding-3-large`**: the five with the highest cosine × fit (the
     lesson's support share), so a lesson close in wording but rarely right ranks lower;
   - **`fill:openai/text-embedding-3-large`**: today's cause lookup, and for a case it gives no
     lesson, the one nearest by cosine.
3. **One steering coding run each**, condition `embed-lookup`, over the tables run today's cause
   lookup used. Each is read by 0213's rule unchanged: with L = embed-lookup − cause lookup and
   N = counts(b) − counts(a), it passes only if L(finding recall@10) > |N|, L(top-1) ≥ −|N| and
   L(top-3) ≥ −|N|.
4. **One goes forward.** Of the candidates that pass, the one with the largest L(finding
   recall@10); an exact tie goes to the earlier in the order of item 2. None passing: the
   method stops and today's cause lookup stays.
5. **Then once on `dev-seal-400`**, as 0213 items 7 and 8: that sample's own tables, counts and
   apply runs, today's cause lookup, and the winner unchanged (for the picking call, a new
   picking call on that sample), read by the same rule, with the outcomes 0213 fixed.
6. **This closes the lookup question for `pilot-2010-recount`.** Whatever `dev-seal-400` says,
   no further lookup round is run on this snapshot.
7. **Spend.** OpenRouter: four steering runs, about $0.73; `dev-seal-400` about $0.93 (its four
   runs about $0.75 and the winner's run about $0.18; embeddings under a cent). Plan credit:
   `dev-seal-400`'s apply step about $1.50, and a picking call there about $2.90 if it wins.
8. **A registration is committed first**, after Andy signs it. No paid step runs before.

## Why

1. **The coding test is the measure that counts.** 0213's gate stood in for it, and the review
   showed the stand-in mostly scored the first code while the memory helps findings.
2. **It is cheap enough to test all four.** Four runs cost about $0.73. Dropping a better lookup
   because of a weak stand-in would cost more than that.
3. **The four cover the leads the review found.** The plain lookup and the picking call were 0213's
   candidates; ranking by fit as well addresses the weak, wordy lessons cosine hands out; the fill
   keeps today's lookup and gives the 39 cases with no lesson one each.
4. **`dev-seal-400` still decides.** Choosing the best of four on the steering slice can favour a
   lucky one; a sample with no part in the choice says whether it helps.
5. **Only one embedding model.** `openai/text-embedding-3-large` led the other two on hit rate,
   precision and both finding-part measures (`docs/results/memory-proxy-check-dev.txt`; on the
   first-code part's case hit `openai/text-embedding-3-small` was 0.3 points ahead), and its
   embeddings are already paid for.

## What this rules out

- **Using lesson coverage as a gate again.**
- **More candidates after a coding run is seen**, other embedding models, a tuned weight between
  cosine and fit, or a wider shortlist for the picking call.
- **Choosing anything on `dev-seal-400`**, or running more than the winner there.
- **Any further lookup round on `pilot-2010-recount`** after `dev-seal-400` is read.
- **Changing today's cause lookup**; it stays the comparison on both samples.
- **Using `dev-seal-s3-400`, reading `dev-400` again, or connecting the memory to Ellery version 1,
  S4 or the board** (0141, 0212, 0201).

## Status

Accepted. Replaces 0213 items 4 to 6 (the gate, the fallback's place, one steering coding run) for
this round; 0213's published result is unchanged.
