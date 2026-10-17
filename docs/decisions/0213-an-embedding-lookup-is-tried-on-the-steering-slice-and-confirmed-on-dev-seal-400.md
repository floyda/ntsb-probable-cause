# 0213 — An embedding lookup is tried on the steering slice and confirmed once on dev-seal-400

From Andy, 2026-10-17, one choice at a time: "yes let's continue onwards to look at those two
options", then "Yes beat today's results", "Yes that sounds like a good plan", "May as well try all
three", the gate and the fallback's model ("Yes"), and the design note's §13 ("I agree"). Detail:
the design note `docs/specs/2026-10-08-coding-memory-design.md` §13, the registration
`docs/rounds/memory-embed-lookup.md` and the plan `docs/plans/2026-10-17-coding-memory-embed-lookup.md`.

## Context

1. **The cause lookup passed on the steering slice and was confirmed on `dev-400`** (0211, 0212):
   finding recall@10 +2.9 points [+0.6, +5.3] and +2.6 [+0.8, +4.5] over counts
   (`docs/results/memory-cause-lookup-dev.txt`, `docs/results/memory-confirm-dev400.txt`).
2. **What limits it is how few lessons the apply step names.** On the steering slice: a mean of
   2.34 lessons named a case, 39 cases with no lesson after the support floor, 19 with the full
   five (`docs/results/memory-cause-apply-dev.txt`). On `dev-400`: 33 with none, 26 with five
   (`docs/results/memory-cause-apply-dev400.txt`). Ranking those short lists better would change
   little.
3. **OpenRouter offers an embeddings service** (`POST /api/v1/embeddings`), on the product's
   transport and key ([API reference](https://openrouter.ai/docs/api-reference/embeddings)). Its
   model list, fetched on 2026-10-17, prices `qwen/qwen3-embedding-8b` at $0.01,
   `openai/text-embedding-3-small` at $0.02 and `openai/text-embedding-3-large` at $0.13 per
   million input tokens. Embedding the 198 lessons and two samples' cause sentences is about
   75,000 tokens. Today's apply step costs $1.43 to $1.56 of plan credit per 400 cases.
4. **Each lesson records what it predicts** (a first occurrence code, finding categories), and
   the learner's support count already tests that against a case's codes
   (`memory/curate.py:agrees`). So a lookup's lessons can be scored against the steering slice's
   verdicts by script, with no model call.
5. **`dev-seal-400` has never been read by the memory**, and 0212 kept it for this.

## Decision

1. **The bar is today's cause lookup, not the counts condition.**
2. **Embedding search, as a new method.** Each lesson's statement and scope, and each case's cause
   sentence, are embedded through OpenRouter. A case gets the five eligible lessons (support floor
   10) closest to its cause sentence. Fixed: K = 5, the floor, the embedded text, the snapshot
   `pilot-2010-recount`, and the whole coding test of 0211. The only choice is the model.
3. **Three candidate models:** `qwen/qwen3-embedding-8b`, `openai/text-embedding-3-small` and
   `openai/text-embedding-3-large`, read from the saved list.
4. **A free gate before any coding run.** Lesson coverage on the steering slice: hit rate (cases
   where at least one chosen lesson agrees) and precision (the share of lessons handed out that
   agree), by `curate.agrees`. A candidate passes if its hit rate is higher than today's lookup's
   with the paired 95% interval above zero, and its precision is no lower. The highest passing
   hit rate goes forward; an exact tie goes to the lower list price.
5. **A fallback only if none passes:** the learner (Sonnet 5.5 at high, plan credit) reads each
   case's 20 closest lessons from the highest-hit-rate model and names up to five, best first, or
   none. Gated the same way. If it fails, the method stops.
6. **One coding run on the steering slice**, condition `embed-lookup`, over the tables run today's
   cause lookup used. With L = embed-lookup − cause lookup and N = counts(b) − counts(a), it passes
   only if L(finding recall@10) > |N|, L(top-1) ≥ −|N| and L(top-3) ≥ −|N|.
7. **Then once on `dev-seal-400`, only if steering passes:** its own tables run, two counts runs,
   today's apply step and cause lookup, and embed-lookup with the winning method unchanged. The
   same rule, read there. The memory scripts refuse `dev-seal-400` until the registration is
   committed; on it they allow the tables, counts, cause-lookup and embed-lookup conditions only.
8. **What follows is fixed in the registration.** Passing on `dev-seal-400` with the finding
   gain's interval above zero makes the new method the memory's lookup; a pass whose interval
   includes zero is a thin confirmation and changes nothing unless Andy decides in a record; a
   fail on either sample keeps today's lookup.
9. **Verdict text goes to the embedding providers.** The cause sentence reaches GPT-6 Luna in the
   coding test already (0205); embedding sends it, and the lessons, to the embedding models'
   providers through OpenRouter. Development cases only; the text is public.
10. **Spend.** OpenRouter (the $40 guard and the side track's $10 line): the probe and embeddings
    under $0.05, a new spend kind `embedding`; the steering coding run about $0.18; `dev-seal-400`
    about $0.75. Plan credit (the $90 learning line): `dev-seal-400`'s apply step about $1.50, and
    the picking call if it runs, checked by its worst-case projection.
11. **A registration is committed first**, after Andy signs it. No paid step, the shape probe
    included, runs before.

## Why

1. **It targets the measured limit.** Embedding search gives every case candidates, where the
   apply step gives 33 to 39 cases none.
2. **It is cheap, and it is on the product's transport.** About a hundredth of today's apply step,
   through OpenRouter (0009), so it could serve live cases if a later decision connects the memory
   to the agent.
3. **The free gate keeps paid steering looks to one.** Three models are compared without a coding
   run; only one lookup reaches the coding test on steering.
4. **`dev-seal-400` decides.** The model is chosen and first read on the steering slice, its fifth
   look at a memory method; only a sample with no part in the choice can say whether it helps.
5. **The fallback adds judgement only where needed.** Embedding matches wording, not meaning. If
   that hands out weak lessons, the learner's judgement over a short list is the next step, at a
   fraction of today's apply step.

## What this rules out

- **Changing today's cause lookup.** It is the comparison, unchanged on both samples.
- **Choosing anything on `dev-seal-400`.** The winning method runs there unchanged, once.
- **Sending more than one lookup to a coding run on steering.**
- **A local embedding model.** It would add a heavy dependency to the strict toolchain (0011) and
  a second path beside the product's transport.
- **Using `dev-seal-s3-400` or reading `dev-400` again.** The first stays sealed for Ellery
  version 2 (0141); the second was read once by the memory (0212).
- **Connecting the memory to Ellery version 1, S4 or the board.** Unchanged from 0201.

## Status

Accepted. Uses `dev-seal-400` as 0212 item 3 kept it; adds the spend kind `embedding` to 0207's
side-track line.
