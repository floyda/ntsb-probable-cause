# Coding memory: the embedding lookup, the registration (decision 0213)

This file fixes the embedding lookup's steps and rules **before any paid step**, the shape probe
included, so none of them can be chosen after a result is seen. Andy reads and signs it first.
Decision: [0213](../decisions/0213-an-embedding-lookup-is-tried-on-the-steering-slice-and-confirmed-on-dev-seal-400.md).
Design: `docs/specs/2026-10-08-coding-memory-design.md` §13. Plan:
`docs/plans/2026-10-17-coding-memory-embed-lookup.md`. The cause-lookup registration,
`docs/rounds/memory-cause-lookup.md`, governs everything this file does not change.

**What committing this file does.** In code, it lets the embedding scripts send their first
request, and lets the coding test's tables, counts, cause-lookup and embed-lookup conditions, the
apply step and the embedding step read `dev-seal-400`. All of them refuse until this file is
committed. Nothing here touches Ellery version 1, S4's nights or the board.

## 1. The question

Does a lookup that finds lessons by embedding search help GPT-6 Luna code better than today's
cause lookup, on cases that had no part in choosing it?

**Why ask it.** Today's lookup is limited by how few lessons the apply step names: on the steering
slice, 39 of 401 cases got none and 19 got the full five (`docs/results/memory-cause-apply-dev.txt`);
on `dev-400`, 33 got none and 26 the full five (`docs/results/memory-cause-apply-dev400.txt`).

## 2. What stays from the cause-lookup test

The snapshot `pilot-2010-recount` and its hash; K = 5; the support floor of 10 (106 lessons
eligible); the coding tools' post-pass; GPT-6 Luna batch at reasoning `medium`; guidance
`r3-loc-stall` and `r6-aircraft-control`; the `mem` statistics; the $0.05 per-case cap; failed
cases counted as wrong (0136). Today's cause lookup, unchanged, is the comparison on both samples.

## 3. The method

- **Embedded text:** each of the 198 lessons as `statement (scope: scope)`; each case's
  probable-cause sentence alone. No code is embedded.
- **The lookup:** for one case, the five eligible lessons with the highest cosine similarity to
  its cause sentence. Ties: higher fit, then more cases applied to, then lesson id.
- **The candidates:** `qwen/qwen3-embedding-8b`, `openai/text-embedding-3-small`,
  `openai/text-embedding-3-large`, with their list prices read from the saved model list.

## 4. The paid steps, and the commands, in order

1. **The model list** (free): `make mem-embed-models`.
2. **The shape probe** (OpenRouter, cents): `make mem-embed-probe`. It writes
   `docs/results/memory-embed-probe.txt` and the test fixtures; commit both.
3. **The embeddings on the steering slice** (OpenRouter, under $0.03), once per model:
   `make mem-embed MODEL=<id>`.
4. **The coverage reading and the gate** (free): `make mem-coverage EMBEDS="<the three runs>"`. It writes
   `docs/results/memory-coverage-dev.txt`; commit it. Its last line names the winner or `none`.
5. **Only if step 4 prints `winner: none`, the picking call** (plan credit):
   `make mem-cause-pick EMBEDS=<the highest hit rate's embedding run>`, then
   `make mem-coverage EMBEDS="<the three runs>" PICKS=<pick run>`, which adds the picking call to
   the same file. If its last line is `none` again, the method stops here
   and the result is published.
6. **The steering coding run** (OpenRouter, about $0.18):
   `make mem-coding-embed-lookup SOURCE=20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a CHOICES=<choices run>`.
7. **The steering reading** (free): `make mem-embed-result ...`, which writes
   `docs/results/memory-embed-lookup-dev.txt`; commit it. If it fails, stop here.
8. **On `dev-seal-400`**, only if step 7 passes:
   1. tables(a): `make mem-coding-answer REPEAT=a SAMPLE=dev-seal-400`;
   2. counts(a) and counts(b) over it: `make mem-coding-tools SOURCE=<tables-a> REPEAT=a`, then `b`;
   3. today's apply step (plan credit): `make mem-cause-apply SNAPSHOT=pilot-2010-recount SAMPLE=dev-seal-400`,
      which writes `docs/results/memory-cause-apply-devseal.txt`; commit it;
   4. today's cause lookup: `make mem-coding-cause-lookup SOURCE=<tables-a> SNAPSHOT=pilot-2010-recount K=5 APPLIES=<apply run>`;
   5. the winning model's embeddings of `dev-seal-400`'s cause sentences:
      `make mem-embed MODEL=<model> SAMPLE=dev-seal-400`; and, if the winner is the picking call,
      `make mem-cause-pick EMBEDS=<that run> SAMPLE=dev-seal-400`;
   6. its choices file: `make mem-coverage SAMPLE=dev-seal-400 APPLIES=<apply run> EMBEDS=<embed run>
      MODEL=<model> [PICKS=<pick run>]`, which writes `docs/results/memory-coverage-devseal.txt`
      (a description; it decides nothing); commit it;
   7. embed-lookup: `make mem-coding-embed-lookup SOURCE=<tables-a> CHOICES=<choices run>`;
   8. the reading: `make mem-embed-result SAMPLE=dev-seal-400 ...`, which writes
      `docs/results/memory-embed-confirm-devseal.txt`; commit it.

Every step needs a clean tree. Anything unexpected goes under the plan's Deviations as it happens.

## 5. The gate, word for word

The registered gate is the docstring of `gate_rule` in `scripts/memory_coverage.py`, word for word:

```text
Decision 0213, as registered in docs/rounds/memory-embed-lookup.md.

A candidate passes only if its hit rate minus today's cause lookup's, paired on the same
cases, is positive with its whole 95% interval above zero, and its precision is no lower
than today's. Of those that pass, the highest hit rate goes forward; an exact tie goes to the
lower list price. None passing gives none.
```

**Definitions.** A chosen lesson agrees with a case by `memory/curate.py:agrees`. Hit rate: the
share of the sample's cases where at least one chosen lesson agrees; a case with no lesson is a
miss. Precision: lessons that agree over lessons handed out.

## 6. The rule, word for word

The registered rule is the docstring of `embed_rule` in `scripts/memory_embed_result.py`, word for
word:

```text
Decision 0213, as registered in docs/rounds/memory-embed-lookup.md.

``looked`` is embed lookup minus today's cause lookup; ``noise`` is counts(b) minus counts(a);
all on one sample. Pass only if the finding gain exceeds the noise on findings, and neither
occurrence measure falls by more than its own noise: the rule of decisions 0204 and 0210 to
0212, with today's cause lookup in place of counts(a).
```

**The exact inequalities.** Let L = embed lookup − cause lookup and N = counts(b) − counts(a), each
a paired point estimate on the sample read. The step **passes** only if all three hold:

- L(finding recall@10) **>** |N(finding recall@10)|;
- L(top-1) **≥** −|N(top-1)|;
- L(top-3) **≥** −|N(top-3)|.

On the steering slice N is already known: top-1 +0.2, top-3 +0.7, finding recall@10 −0.3
(`docs/results/memory-cause-lookup-dev.txt`). On `dev-seal-400` it is read from that sample's own
runs.

## 7. Failures

- All 198 lessons must embed, or the step stops. At most 2% of a sample's cause sentences (8 of
  401) may fail to embed; more stops the step. A case with no vector gets no lesson and is counted.
- The picking call: more than 2% failed replies (8 of 401) refuses its use, as for the apply step.
- A reply that does not match the probe's saved shape is refused, and nothing reaches the cache.

## 8. Spend and expected cost

- **On OpenRouter** (the $40 guard and the side track's $10 line, $8.13 left on 2026-10-17, `make
  mem-spend EST=0`): the probe and embeddings under $0.05, kind `embedding`; the steering coding
  run about $0.18 (the steering cause lookup cost $0.1814); `dev-seal-400` about $0.75 (`dev-400`'s
  four runs cost $0.5529, plus about $0.18). **About $0.97.**
- **On plan credit** (the $90 learning line): `dev-seal-400`'s apply step, about $1.50 ($1.5604 on
  steering, $1.4307 on `dev-400`). The picking call, if it runs, is checked by its worst-case
  projection before it sends.

## 9. What is published either way, and what follows

`docs/results/memory-embed-probe.txt`, `memory-coverage-dev.txt`, `memory-embed-lookup-dev.txt`
and, if reached, `memory-cause-apply-devseal.txt`, `memory-coverage-devseal.txt` and
`memory-embed-confirm-devseal.txt` are committed whatever they say, counts only. The readings end in
their verdict lines.

- **Passes on `dev-seal-400`, and the finding gain's 95% interval is above zero:** the new method
  replaces today's cause lookup as the memory's lookup. Connecting the memory to the agent stays a
  separate decision (0201).
- **Passes, but the interval includes zero:** a thin confirmation. Today's lookup stays unless Andy
  decides otherwise, in a record.
- **Fails the gate, the steering rule, or the `dev-seal-400` rule:** today's cause lookup stays the
  memory's lookup, and the result is published as it stands.

## 10. What had been seen when this was written

- **Every memory result on the steering slice and on `dev-400`**, including the apply step's
  counts on both (`docs/results/memory-*.txt`).
- **The embedding model list's prices** (fetched 2026-10-17, to a scratch file).
- **On the steering slice, no lesson coverage of any lookup** and no embedding. On `dev-seal-400`,
  nothing from the memory: no coding-test answer, apply answer or embedding. S2.7 read
  `dev-seal-400` once, on arm B (`docs/results/s27-sealed-dev.txt`).

## 11. Prediction (optional)

None is required. Andy may write one here before signing.

## Glossary

- **Agrees:** a lesson's predicted first code and finding categories match the case's codes, on
  each part it predicts (`curate.agrees`).
- **Choices file:** each case's chosen lesson ids, written once and read by the coding run.
- **Cosine similarity:** how close two vectors point; 1 is the same direction.
- **Embedding:** the list of numbers a model returns for a text.
- **Hit rate / precision:** see §5.
- **Picking call:** the learner choosing up to five lessons from a shortlist of 20.
- **Steering slice:** `dev-steer-400`, the 401 cases used to choose the method.

Approved by Andy, 2026-10-17
