# Coding memory: the cause lookup's confirmation on dev-400, the registration (decision 0212)

This file fixes the confirmation's steps and its rule **before any paid step**, so none of them
can be chosen after a result is seen. Andy reads and signs it first. Decision:
[0212](../decisions/0212-the-cause-lookup-is-confirmed-once-on-dev-400.md). Plan:
`docs/plans/2026-10-17-coding-memory-confirm-dev400.md`, Task 3. The cause-lookup registration,
`docs/rounds/memory-cause-lookup.md`, governs everything this file does not change.

**What committing this file does.** In code, it lets the coding test's tables, counts and
cause-lookup conditions, and the apply step, read `dev-400`. All of them refuse it until this file
is committed. Nothing here touches Ellery version 1, S4's nights or the board.

## 1. The question

On 401 cases that no memory test has seen and no lesson was learned from, does the cause lookup
still help GPT-6 Luna code better than the counts the coding tools already give?

**Why ask it.** On the steering slice the cause lookup passed: finding recall@10 +2.9 points
[+0.6, +5.3] over counts, top-1 +2.5, top-3 +4.0 (`docs/results/memory-cause-lookup-dev.txt`). That
was the steering slice's fourth look at a memory, so part of the gain may be selection. `dev-400`
had no part in choosing anything.

## 2. What stays from the cause-lookup test

Everything in the method: the snapshot `pilot-2010-recount` and its hash; the apply step (Sonnet
5.5 at effort high, in batches, all 198 lessons in id order, the cause sentence alone, 4,000 reply
tokens); the lookup rule (named lessons with at least 10 learning cases, highest fit first, K = 5);
the coding tools' post-pass; GPT-6 Luna batch at reasoning `medium`; guidance `r3-loc-stall` and
`r6-aircraft-control`; the `mem` statistics; the $0.05 per-case cap; the stop rule. The 2% refusal
on failed apply replies (more than 8 of 401) and the refusal to resume a finished apply run stand.

## 3. What changes

Only the sample, and so the comparison runs: `dev-400`, 401 cases, none in `dev-steer-400`, all
outside the pool the lessons were learned from (the `mem` statistics refuse a sample their pool
holds, `coding_stats.refuse_pool_holding`; `tests/test_memory_cause_apply.py` checks the pool
leaves out every `dev-400` case). How many have a probable-cause sentence is printed by the apply
step's counts file (`without a cause sentence`) and recorded by every coding run. `dev-400` gets its
own tables run and its own two counts runs; nothing from the steering slice is reused.

## 4. The paid steps, and the commands, in order

1. **Tables(a)** (OpenRouter): `make mem-coding-answer REPEAT=a SAMPLE=dev-400`
2. **Counts(a) and counts(b)** (OpenRouter), over tables(a):
   `make mem-coding-tools SOURCE=<tables-a> REPEAT=a`, then the same with `REPEAT=b`
3. **The apply step** (Claude, plan credit):
   `make mem-cause-apply SNAPSHOT=pilot-2010-recount SAMPLE=dev-400`. It writes
   `docs/results/memory-cause-apply-dev400.txt`, counts only; commit it. It reads no score.
4. **The cause lookup** (OpenRouter), over tables(a):
   `make mem-coding-cause-lookup SOURCE=<tables-a> SNAPSHOT=pilot-2010-recount K=5 APPLIES=<apply run>`
5. **The reading** (free):
   `make mem-confirm-result TA=<tables-a> CA=<counts-a> CB=<counts-b> CAUSE=<cause lookup>`, then
   commit `docs/results/memory-confirm-dev400.txt`.

Every step needs a clean tree. Anything unexpected goes under the plan's Deviations as it happens.

## 5. The noise

**noise = counts(b) − counts(a), both on `dev-400`.** It is read from this test's own runs, so it is
not known when this is signed.

## 6. The stop rule, word for word

The registered rule is the docstring of `confirm_rule` in `scripts/memory_confirm_result.py`, word
for word:

```text
Decision 0212, as registered in docs/rounds/memory-confirm-dev400.md.

``looked`` is cause lookup minus counts(a) on dev-400; ``noise`` is counts(b) minus counts(a)
on dev-400. Pass only if the finding gain exceeds the noise on findings, and neither
occurrence measure falls by more than its own noise: the rule of decisions 0204, 0210 and
0211, read on dev-400.
```

**The exact inequalities.** Let L = cause lookup − counts(a) and N = counts(b) − counts(a), each a
paired point estimate on `dev-400`. The confirmation **passes** only if all three hold:

- L(finding recall@10) **>** |N(finding recall@10)|;
- L(top-1) **≥** −|N(top-1)|;
- L(top-3) **≥** −|N(top-3)|.

The rule reads point estimates. The 95% intervals are printed beside them and decide what is
recommended next (§9).

## 7. Failed cases count as wrong

As in the pilot (its §9, decision 0136). A case with no answer in tables(a) fails in every
post-pass alike.

## 8. Spend and expected cost

From the steering runs' own records (`spend.jsonl` in each run folder):

- **On OpenRouter**, kind `coding-test`, on the $40 guard and the side track's $10 line ($8.68
  left, `make mem-spend EST=0` on 2026-10-17): tables $0.15, counts $0.12 each, cause lookup $0.18, so **about
  $0.57**. Each step checks the line first (`make mem-spend`, 4.01 a step).
- **On plan credit**, kind `learning`, the learner's monthly line of $90: the apply step cost
  $1.5604 on the steering slice, so **about $1.56**. Its worst-case projection is checked before it
  sends.

## 9. What is published either way, and what follows

`docs/results/memory-confirm-dev400.txt` is committed whatever it says, counts only: each run's
measures with intervals and failed cases; the noise; cause lookup − counts(a), which decides; the
lessons per case; and the verdict, last line, `rule on dev-400: PASS` or `FAIL`, with every
`not passed:` reason before it.

**What follows, fixed now:**

- **Passed, and the finding gain's 95% interval is above zero:** the cause lookup is reported as
  confirmed on development cases. Next, as Andy asked, a better lookup is tried on the steering
  slice and confirmed once on `dev-seal-400`, under its own decision; connecting the memory to the
  agent is a separate decision after that.
- **Passed, but the interval includes zero:** reported as a thin confirmation. The better lookup
  may still be tried, as Andy's call, in a record.
- **Not passed:** the steering-slice pass is reported as not confirmed, and the side track stops
  as it stands.

## 10. What had been seen when this was written

- **Every memory result on the steering slice** (`memory-pilot-dev.txt`, `memory-lookup-dev.txt`,
  `memory-cause-apply-dev.txt`, `memory-cause-lookup-dev.txt`).
- **On `dev-400`: only that its cases lie outside the learning pool, and an unscripted count of
  how many have a cause sentence (all of them).** No coding-test answer, apply answer or memory result on `dev-400` has been seen. Earlier
  stages read `dev-400` many times (S2.7, S3.1), on arm B and the loop, not on this test.

## 11. Prediction (optional)

None is required. Andy may write one here before signing.

## Glossary

- **Apply step:** the learner's call that reads one cause sentence and lists the lessons that
  cover it.
- **Cause lookup:** for one case, the five best fitting lessons among those the apply step named
  for its cause sentence.
- **Confirmation:** the same method run once on cases that had no part in choosing it.
- **Counts:** the coding tools' output (how often the NTSB used each code), from the `mem`
  statistics.
- **Learning pool:** the development cases the lessons were learned from; `dev-400` is outside it.
- **Noise:** counts(b) − counts(a): how much a repeat run moves each measure.
- **Points:** the difference between two percentages.
- **Steering slice:** `dev-steer-400`, the 401 cases used to choose the method.
- **Top-1 / top-3:** the NTSB's first occurrence code is the answer's first guess / any of its up to
  three guesses.

Approved by Andy, 2026-10-17
