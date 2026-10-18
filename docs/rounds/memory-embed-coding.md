# Coding memory: every embedding lookup goes to the coding test, the registration (decision 0214)

This file fixes the round's steps and rules **before any paid step**, so none of them can be
chosen after a coding result is seen. Andy reads and signs it first.
Decision: [0214](../decisions/0214-every-embedding-lookup-goes-to-the-coding-test.md).
Design: `docs/specs/2026-10-08-coding-memory-design.md` §13.13. Plan:
`docs/plans/2026-10-18-coding-memory-embed-coding.md`. The embedding-lookup registration,
`docs/rounds/memory-embed-lookup.md`, governs everything this file does not change.

**What committing this file does.** In code, it lets `scripts/memory_embed_choices.py` write
choices and `scripts/memory_embed_coding_result.py` read the coding runs. Both refuse until this
file is committed. Nothing here touches Ellery version 1, S4's nights or the board.

## 1. The question

Does any of four embedding lookups help GPT-6 Luna code better than today's cause lookup, on
cases that had no part in choosing it?

**Why ask it again.** 0213's free gate stopped every embedding lookup before a coding run. The
review of 2026-10-18 found that the gate's precision mostly scored the first code, while the
memory's benefit is on findings (`docs/results/memory-proxy-check-dev.txt`). The coding test
measures what counts, at about $0.18 a run.

## 2. What stays from 0213

The snapshot `pilot-2010-recount` and its hash; K = 5; the support floor of 10 (106 lessons
eligible); the coding test of 0211 (the counts post-pass, GPT-6 Luna batch at reasoning `medium`,
guidance `r3-loc-stall` and `r6-aircraft-control`, the `mem` statistics, the $0.05 per-case cap,
failed cases counted as wrong); today's cause lookup, unchanged, as the comparison on both
samples; 0213's rule, word for word (§5); `dev-seal-400`'s steps (§4 step 4).

## 3. The four candidates

All over 0213's embedding run of `openai/text-embedding-3-large` on the steering slice
(`20261017T180227Z-2e3e730-memory-embed-dev-steer-400-openai-text-embedding-3-large`), every
lesson of the snapshot, kept or pushed out. Fit is a lesson's support share (agrees over applies).

1. **`openai/text-embedding-3-large`:** the five eligible lessons nearest the cause sentence by
   cosine; ties by fit, then cases applied to, then id (`lookup.by_similarity`, 0213's lookup).
2. **`pick:openai/text-embedding-3-large`:** 0213's picking run, unchanged
   (`20261017T181956Z-8627513-memory-cause-pick-dev-steer-400-openai-text-embedding-3-large`).
3. **`fit:openai/text-embedding-3-large`:** the five with the highest cosine × fit; ties by fit,
   then cases applied to, then id (`lookup.by_similarity_fit`).
4. **`fill:openai/text-embedding-3-large`:** today's cause lookup; for a case it gives no lesson,
   the one eligible lesson nearest by cosine (`lookup.by_fit_or_nearest`).

## 4. The steps, and the commands, in order

1. **The choices** (free): `make mem-embed-choices`, which refuses any run but §3's. It writes
   `docs/results/memory-embed-choices-dev.txt` (a description; it decides nothing) and four
   choices runs, one per candidate; commit the file.
2. **The steering coding runs** (OpenRouter, about $0.18 each), one per choices run:
   `make mem-coding-embed-lookup SOURCE=20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a CHOICES=<choices run>`.
3. **The steering reading** (free): `make mem-embed-coding-result EMBEDS="<the four runs>"`. It
   writes `docs/results/memory-embed-coding-dev.txt`; commit it. It refuses a choices run not
   made from §3's runs. Its last line names the winner or `none`; `none` stops the round here,
   and the result is published.
4. **On `dev-seal-400`**, only if step 3 names a winner, as `docs/rounds/memory-embed-lookup.md`
   §4 step 8, with these changes:
   1. to 3. as there: tables(a), counts(a) and counts(b), today's apply step (plan credit), which
      writes `docs/results/memory-cause-apply-devseal.txt`; commit it;
   4. today's cause lookup, as there;
   5. the large model's embeddings of `dev-seal-400`'s cause sentences:
      `make mem-embed MODEL=openai/text-embedding-3-large SAMPLE=dev-seal-400`; and, only if the
      winner is the picking call, `make mem-cause-pick EMBEDS=<that run> SAMPLE=dev-seal-400`;
   6. the winner's choices: `make mem-embed-choices SAMPLE=dev-seal-400 APPLIES=<apply run>
      EMBEDS=<embed run> CANDIDATE=<winner> [PICKS=<pick run>]`, which writes
      `docs/results/memory-embed-choices-devseal.txt` (a description); commit it;
   7. embed-lookup: `make mem-coding-embed-lookup SOURCE=<tables-a> CHOICES=<choices run>`;
   8. the reading: `make mem-embed-result SAMPLE=dev-seal-400 ...`, which writes
      `docs/results/memory-embed-confirm-devseal.txt`; commit it.

Every step needs a clean tree. Anything unexpected goes under the plan's Deviations as it happens.

## 5. The rule for each candidate, word for word (0213's, unchanged)

The docstring of `embed_rule` in `scripts/memory_embed_result.py`, as
`docs/rounds/memory-embed-lookup.md` §6 registered it:

```text
Decision 0213, as registered in docs/rounds/memory-embed-lookup.md.

``looked`` is embed lookup minus today's cause lookup; ``noise`` is counts(b) minus counts(a);
all on one sample. Pass only if the finding gain exceeds the noise on findings, and neither
occurrence measure falls by more than its own noise: the rule of decisions 0204 and 0210 to
0212, with today's cause lookup in place of counts(a).
```

With L = embed lookup − cause lookup and N = counts(b) − counts(a), paired point estimates on the
sample read: L(finding recall@10) **>** |N(finding recall@10)|, L(top-1) **≥** −|N(top-1)| and
L(top-3) **≥** −|N(top-3)|. On the steering slice N is top-1 +0.2, top-3 +0.7, finding recall@10
−0.3 (`docs/results/memory-cause-lookup-dev.txt`).

## 6. The selection rule, word for word

The docstring of `selection_rule` in `scripts/memory_embed_coding_result.py`:

```text
Decision 0214, as registered in docs/rounds/memory-embed-coding.md.

Each candidate is read by decision 0213's rule against today's cause lookup. Of those that
pass, the one with the largest finding gain goes forward; an exact tie goes to the earlier in
the order embedding, pick, fit, fill. None passing gives none.
```

"The finding gain" is L(finding recall@10). "Embedding, pick, fit, fill" is §3's order.

## 7. Failures

As `docs/rounds/memory-embed-lookup.md` §7. A case with no vector gets no lesson under candidates
1, 2 and 3 (the picking call sent it nothing), and keeps today's lessons under candidate 4.

## 8. Spend and expected cost

- **On OpenRouter** (the $40 guard and the side track's $10 line, $8.12 left on 2026-10-18, `make
  mem-spend EST=0`): four steering runs, about $0.73; on `dev-seal-400` about $0.93 (its tables
  and counts runs and today's cause lookup about $0.75, the winner's run about $0.18, embeddings
  under a cent). **About $1.66.**
- **On plan credit** (the $90 learning line, $39.02 spent this month on 2026-10-18, read by
  `scoring/budget.py:learning_month_spent`):
  `dev-seal-400`'s apply step about $1.50, and, if the picking call wins, a picking call there
  about $2.90 ($2.8987 on the steering slice), checked by its worst-case projection.

## 9. What is published either way, and what follows

`docs/results/memory-embed-choices-dev.txt` and `memory-embed-coding-dev.txt` and, if reached,
`memory-cause-apply-devseal.txt`, `memory-embed-choices-devseal.txt` and
`memory-embed-confirm-devseal.txt` are committed whatever they say, counts only.

- **Passes on `dev-seal-400`, and the finding gain's 95% interval is above zero:** the winner
  replaces today's cause lookup as the memory's lookup. Connecting the memory to the agent stays a
  separate decision (0201).
- **Passes, but the interval includes zero:** a thin confirmation. Today's lookup stays unless Andy
  decides otherwise, in a record.
- **No winner on steering, or a fail on `dev-seal-400`:** today's cause lookup stays the memory's
  lookup, and the result is published as it stands.

In every case, no further lookup round is run on `pilot-2010-recount` (decision 0214 item 6).

## 10. What had been seen when this was written

- **Every memory result on the steering slice and on `dev-400`** (`docs/results/memory-*.txt`),
  including 0213's coverage reading and `docs/results/memory-proxy-check-dev.txt`.
- **The lesson coverage of candidates 3 and 4 on the steering slice**, from the review's
  uncommitted scripts (step 1 prints it again). No coding run of any candidate.
- **On `dev-seal-400`, nothing from the memory.** S2.7 read it once, on arm B
  (`docs/results/s27-sealed-dev.txt`).

## 11. Prediction (optional)

None is required. Andy may write one here before signing.

## Glossary

- **Candidate:** one way of choosing each case's lessons, named by its method and its embedding
  model.
- **Cosine × fit:** how close a lesson's wording is to the cause sentence, times how often the
  lesson was right on the cases it applied to.
- **Fill:** today's lookup, with one nearest lesson added only where it gives none.
- **Finding gain:** the candidate's finding recall@10 minus today's cause lookup's, paired.
- **Noise:** how much two identical counts runs differ; a gain must exceed it.
- **Steering slice:** `dev-steer-400`, the 401 cases used to choose the method.

Approved by Andy, 2026-10-18
